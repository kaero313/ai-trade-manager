from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.db.live_order_control_repository import (
    CONTROL_ACTION_ARMED,
    CONTROL_ACTION_LIQUIDATION_AUTHORIZED,
    CONTROL_ACTION_LIQUIDATION_REVOKED,
    CONTROL_SOURCE_AUTH_FAILURE,
    EMERGENCY_AUTHORIZATION_ACTIVE,
    EMERGENCY_AUTHORIZATION_REVOKED,
    LIVE_ORDER_MODE_ARMED,
    LIVE_ORDER_MODE_BLOCK_ALL,
    LIVE_ORDER_MODE_EXIT_ONLY,
    LiveOrderControlEventRecord,
    LiveOrderControlRecord,
    LiveOrderControlRequestSupersededError,
    LiveOrderControlTransitionResult,
    build_control_request_fingerprint,
)
from app.models.domain import LiquidationOperation
from app.services.trading.live_order_control import (
    ARM_CONFIRMATION,
    ArmLiveOrdersCommand,
    AuthFailureBlockCommand,
    AuthorizeEmergencyLiquidationCommand,
    BlockLiveOrdersCommand,
    CloseEmergencyLiquidationCommand,
    PrepareEmergencyLiquidationCommand,
    LiveOrderControlDrainPendingError,
    LiveOrderControlPolicyError,
    LiveOrderControlService,
    LiveOrderControlStateUnavailableError,
)

NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


def _control(
    *,
    mode: str = LIVE_ORDER_MODE_BLOCK_ALL,
    generation: int = 3,
    version: int = 7,
    operation_id: int | None = None,
) -> LiveOrderControlRecord:
    return LiveOrderControlRecord(
        id=1,
        broker="UPBIT",
        account_scope="primary",
        mode=mode,
        active_liquidation_operation_id=operation_id,
        generation=generation,
        version=version,
        reason_code="INITIALIZED",
        reason_text="초기 차단 상태입니다.",
        changed_source="SYSTEM",
        changed_actor_ref=None,
        armed_at=None,
        blocked_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _operation(
    *,
    operation_id: int,
    request_id: UUID,
    status: str = "PREPARING",
    authorization_status: str = EMERGENCY_AUTHORIZATION_REVOKED,
) -> LiquidationOperation:
    operation = LiquidationOperation(
        id=operation_id,
        idempotency_key=str(request_id),
        status=status,
        target_snapshot=[{"market": "KRW-BTC", "volume": "0.1"}],
        emergency_authorization_status=authorization_status,
    )
    operation.emergency_authorized_at = NOW if authorization_status == "ACTIVE" else None
    operation.emergency_control_generation = 3 if authorization_status == "ACTIVE" else None
    operation.emergency_control_event_id = 10 if authorization_status == "ACTIVE" else None
    operation.emergency_authorized_source = "REST" if authorization_status == "ACTIVE" else None
    operation.emergency_revoked_at = NOW if authorization_status == "REVOKED" else None
    operation.emergency_revocation_reason = (
        "FAIL_CLOSED_NOT_AUTHORIZED" if authorization_status == "REVOKED" else None
    )
    operation.emergency_closed_at = NOW if authorization_status == "CLOSED" else None
    return operation


class _FakeSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.flush_count = 0

    async def flush(self) -> None:
        self.flush_count += 1
        self.events.append("flush")


class _FakeLease:
    def __init__(self, events: list[str], db: _FakeSession) -> None:
        self._events = events
        self._db = db

    @asynccontextmanager
    async def transaction(self):
        self._events.append("transaction-enter")
        try:
            yield self._db
        finally:
            self._events.append("transaction-exit")


class _FakeBarrier:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.db = _FakeSession(self.events)

    @asynccontextmanager
    async def exclusive(self, *, timeout_seconds: float | None = None):
        del timeout_seconds
        self.events.append("exclusive-enter")
        try:
            yield _FakeLease(self.events, self.db)
        finally:
            self.events.append("exclusive-exit")


class _FakeStateStore:
    def __init__(self) -> None:
        self.bot_active = True
        self.trading_mode = "live"
        self.operations: dict[int, LiquidationOperation] = {}
        self.events: list[str] = []

    async def get_bot_active(self, db) -> bool:
        del db
        return self.bot_active

    async def set_bot_active(self, db, *, is_active: bool) -> None:
        del db
        self.bot_active = is_active
        self.events.append(f"bot-active:{is_active}")

    async def get_trading_mode(self, db) -> str | None:
        del db
        return self.trading_mode

    async def get_liquidation_operation_for_update(self, db, operation_id: int):
        del db
        return self.operations.get(operation_id)


class _FakeRepository:
    def __init__(self, control: LiveOrderControlRecord) -> None:
        self.control = control
        self.rollout_enabled = True
        self.blocking_intent = False
        self.submitting_intent = False
        self.submitting_intent_id: int | None = None
        self.submitting_exclusions: list[int | None] = []
        self.events_by_request_id: dict[str, LiveOrderControlEventRecord] = {}
        self.transition_calls: list[dict[str, object]] = []
        self.audit_events: list[str] = []
        self.blocking_include_prepared: list[bool] = []
        self._next_event_id = 100

    async def get_event(self, db, request_id):
        del db
        return self.events_by_request_id.get(str(request_id))

    async def get_latest_event(self, db, *, control_id: int):
        del db
        events = [
            event
            for event in self.events_by_request_id.values()
            if event.control_id == control_id
        ]
        return max(events, key=lambda event: event.id, default=None)

    async def get_control(self, db, *, for_update: bool = False, **kwargs):
        del db, for_update, kwargs
        return self.control

    async def get_rollout_flag(self, db) -> bool:
        del db
        return self.rollout_enabled

    async def disable_rollout_flag(self, db) -> None:
        del db
        self.rollout_enabled = False
        self.audit_events.append("rollout-disabled")

    async def has_blocking_intent(self, db, *, include_prepared: bool = True, **kwargs):
        del db, kwargs
        self.blocking_include_prepared.append(include_prepared)
        return self.blocking_intent

    async def has_submitting_intent(self, db, **kwargs) -> bool:
        del db
        excluded = kwargs.get("exclude_intent_id")
        self.submitting_exclusions.append(excluded)
        if not self.submitting_intent:
            return False
        if excluded is None or self.submitting_intent_id is None:
            return True
        return self.submitting_intent_id != excluded

    async def transition_control(self, db, **kwargs):
        del db
        self.transition_calls.append(kwargs)
        request_id = str(kwargs["request_id"])
        existing = self.events_by_request_id.get(request_id)
        if existing is not None:
            assert existing.request_fingerprint == kwargs["request_fingerprint"]
            return LiveOrderControlTransitionResult(
                control=self.control,
                event=existing,
                replayed=True,
                permission_scope_changed=False,
            )

        target_mode = str(kwargs["target_mode"])
        target_operation_id = kwargs["active_liquidation_operation_id"]
        permission_changed = (
            self.control.mode != target_mode
            or self.control.active_liquidation_operation_id != target_operation_id
        )
        next_generation = self.control.generation + int(permission_changed)
        event = LiveOrderControlEventRecord(
            id=self._next_event_id,
            control_id=self.control.id,
            generation=next_generation,
            request_id=request_id,
            request_fingerprint=str(kwargs["request_fingerprint"]),
            action=str(kwargs["action"]),
            from_mode=self.control.mode,
            to_mode=target_mode,
            reason_code=str(kwargs["reason_code"]),
            reason_text=str(kwargs["reason_text"]),
            source=str(kwargs["source"]),
            actor_ref=kwargs["actor_ref"],
            liquidation_operation_id=kwargs.get("event_liquidation_operation_id"),
            created_at=kwargs["now"],
        )
        self._next_event_id += 1
        self.control = replace(
            self.control,
            mode=target_mode,
            active_liquidation_operation_id=target_operation_id,
            generation=next_generation,
            version=self.control.version + 1,
            reason_code=str(kwargs["reason_code"]),
            reason_text=str(kwargs["reason_text"]),
            changed_source=str(kwargs["source"]),
            changed_actor_ref=kwargs["actor_ref"],
            updated_at=kwargs["now"],
        )
        self.events_by_request_id[request_id] = event
        return LiveOrderControlTransitionResult(
            control=self.control,
            event=event,
            replayed=False,
            permission_scope_changed=permission_changed,
        )


def _service(
    repository: _FakeRepository,
    state_store: _FakeStateStore,
) -> tuple[LiveOrderControlService, _FakeBarrier]:
    barrier = _FakeBarrier()
    service = LiveOrderControlService(
        barrier=barrier,
        repository=repository,  # type: ignore[arg-type]
        state_store=state_store,
        clock=lambda: NOW,
    )
    return service, barrier


def test_arm_validates_policy_and_transitions_inside_exclusive_lease() -> None:
    request_id = uuid4()
    repository = _FakeRepository(_control())
    state_store = _FakeStateStore()
    service, barrier = _service(repository, state_store)
    command = ArmLiveOrdersCommand(
        request_id=request_id,
        expected_generation=3,
        expected_version=7,
        reason_code="OPERATOR_ARMED",
        reason_text="운영자가 배포 후 실주문 재무장을 확인했습니다.",
        source="REST",
        actor_ref="rest-admin",
        confirmation=ARM_CONFIRMATION,
    )

    result = asyncio.run(service.arm(command))

    assert result.control.mode == LIVE_ORDER_MODE_ARMED
    assert result.control.generation == 4
    assert result.event.action == CONTROL_ACTION_ARMED
    assert barrier.events == [
        "exclusive-enter",
        "transaction-enter",
        "transaction-exit",
        "exclusive-exit",
    ]
    transition = repository.transition_calls[0]
    assert transition["expected_generation"] == 3
    assert transition["expected_version"] == 7
    assert transition["request_fingerprint"] == build_control_request_fingerprint(
        action=CONTROL_ACTION_ARMED,
        expected_generation=3,
        expected_version=7,
        target_mode=LIVE_ORDER_MODE_ARMED,
        active_liquidation_operation_id=None,
        reason_code="OPERATOR_ARMED",
        reason_text=command.reason_text,
        source="REST",
        actor_ref="rest-admin",
        confirmation=ARM_CONFIRMATION,
    )


def test_arm_fails_closed_when_blocking_intent_exists() -> None:
    repository = _FakeRepository(_control())
    repository.blocking_intent = True
    state_store = _FakeStateStore()
    service, _ = _service(repository, state_store)
    command = ArmLiveOrdersCommand(
        request_id=uuid4(),
        expected_generation=3,
        expected_version=7,
        reason_code="OPERATOR_ARMED",
        reason_text="미해결 주문이 없음을 운영자가 확인했습니다.",
        source="REST",
        actor_ref="rest-admin",
        confirmation=ARM_CONFIRMATION,
    )

    with pytest.raises(LiveOrderControlPolicyError) as exc_info:
        asyncio.run(service.arm(command))

    assert exc_info.value.error_code == "LIVE_ORDER_GATE_BLOCKED"
    assert repository.transition_calls == []
    assert repository.blocking_include_prepared == [False]


def test_stop_revokes_scoped_liquidation_and_blocks_without_stale_cas() -> None:
    request_id = uuid4()
    operation_id = 42
    repository = _FakeRepository(
        _control(
            mode=LIVE_ORDER_MODE_EXIT_ONLY,
            generation=8,
            version=11,
            operation_id=operation_id,
        )
    )
    state_store = _FakeStateStore()
    state_store.operations[operation_id] = _operation(
        operation_id=operation_id,
        request_id=uuid4(),
        authorization_status=EMERGENCY_AUTHORIZATION_ACTIVE,
    )
    service, _ = _service(repository, state_store)
    command = BlockLiveOrdersCommand(
        request_id=request_id,
        reason_code="OPERATOR_STOPPED",
        reason_text="운영자가 전체 실주문과 청산 권한을 즉시 정지했습니다.",
        source="REST",
        actor_ref="rest-admin",
    )

    result = asyncio.run(service.stop_bot(command))
    replay = asyncio.run(service.stop_bot(command))

    assert result.control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert result.control.generation == 9
    assert result.event.action == CONTROL_ACTION_LIQUIDATION_REVOKED
    assert result.event.liquidation_operation_id == operation_id
    assert state_store.bot_active is False
    operation = state_store.operations[operation_id]
    assert operation.emergency_authorization_status == EMERGENCY_AUTHORIZATION_REVOKED
    assert operation.emergency_revoked_at == NOW
    assert replay.replayed is True
    assert len(repository.events_by_request_id) == 1
    transition = repository.transition_calls[0]
    assert transition["expected_generation"] is None
    assert "expected_version" not in transition


def test_stop_commits_block_but_does_not_report_success_while_submission_is_inflight() -> None:
    repository = _FakeRepository(
        _control(mode=LIVE_ORDER_MODE_ARMED, generation=5, version=9)
    )
    repository.submitting_intent = True
    state_store = _FakeStateStore()
    service, barrier = _service(repository, state_store)

    with pytest.raises(LiveOrderControlDrainPendingError) as exc_info:
        asyncio.run(
            service.stop_bot(
                BlockLiveOrdersCommand(
                    request_id=uuid4(),
                    reason_code="OPERATOR_STOPPED",
                    reason_text="운영자가 진행 중 제출까지 확인하기 위해 실주문을 정지했습니다.",
                    source="REST",
                    actor_ref="rest-admin",
                )
            )
        )

    assert exc_info.value.error_code == "ORDER_GATE_DRAIN_PENDING"
    assert repository.control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert state_store.bot_active is False
    assert barrier.events[-1] == "exclusive-exit"


def test_auth_failure_atomically_disables_rollout_and_blocks_gate() -> None:
    repository = _FakeRepository(
        _control(mode=LIVE_ORDER_MODE_ARMED, generation=5, version=9)
    )
    repository.submitting_intent = True
    repository.submitting_intent_id = 91
    state_store = _FakeStateStore()
    service, barrier = _service(repository, state_store)

    result = asyncio.run(
        service.trip_on_auth_failure(
            AuthFailureBlockCommand(
                request_id=uuid4(),
                reason_code="NO_AUTHORIZATION_IP",
                reason_text="Upbit HTTP 401 IP authorization failure",
                completed_post_intent_id=91,
            )
        )
    )

    assert result.control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert repository.rollout_enabled is False
    assert repository.audit_events == ["rollout-disabled"]
    assert repository.submitting_exclusions == [91]
    assert repository.transition_calls[0]["source"] == CONTROL_SOURCE_AUTH_FAILURE
    assert barrier.events[0:2] == ["exclusive-enter", "transaction-enter"]
    assert barrier.events[-2:] == ["transaction-exit", "exclusive-exit"]


def test_auth_failure_ignores_only_completed_post_and_reports_other_orphan() -> None:
    repository = _FakeRepository(
        _control(mode=LIVE_ORDER_MODE_ARMED, generation=5, version=9)
    )
    repository.submitting_intent = True
    repository.submitting_intent_id = 92
    state_store = _FakeStateStore()
    service, _ = _service(repository, state_store)

    with pytest.raises(LiveOrderControlDrainPendingError):
        asyncio.run(
            service.trip_on_auth_failure(
                AuthFailureBlockCommand(
                    request_id=uuid4(),
                    reason_code="JWT_VERIFICATION",
                    reason_text="현재 POST 외의 미확정 제출이 남아 전체 차단 상태를 확인합니다.",
                    completed_post_intent_id=91,
                )
            )
        )

    assert repository.control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert repository.rollout_enabled is False
    assert repository.submitting_exclusions == [91]


def test_liquidation_preparation_blocks_before_snapshot_and_replays_idempotently() -> None:
    operation_id = 42
    operation_request_id = uuid4()
    repository = _FakeRepository(
        _control(mode=LIVE_ORDER_MODE_ARMED, generation=5, version=9)
    )
    state_store = _FakeStateStore()
    state_store.operations[operation_id] = _operation(
        operation_id=operation_id,
        request_id=operation_request_id,
    )
    service, _ = _service(repository, state_store)
    prepare_request_id = uuid4()
    command = PrepareEmergencyLiquidationCommand(
        request_id=prepare_request_id,
        operation_id=operation_id,
        reason_code="EMERGENCY_LIQUIDATION_PREPARE",
        reason_text="전량청산 대상 조회 전에 일반 실주문을 먼저 차단합니다.",
        source="REST",
        actor_ref="liquidation-coordinator",
    )

    first = asyncio.run(service.prepare_liquidation(command))
    replay = asyncio.run(service.prepare_liquidation(command))

    assert first.control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert first.control.active_liquidation_operation_id is None
    assert state_store.bot_active is False
    assert replay.replayed is True
    assert len(repository.events_by_request_id) == 1


def test_liquidation_preparation_commits_block_but_reports_drain_pending() -> None:
    operation_id = 42
    repository = _FakeRepository(
        _control(mode=LIVE_ORDER_MODE_ARMED, generation=5, version=9)
    )
    repository.submitting_intent = True
    state_store = _FakeStateStore()
    state_store.operations[operation_id] = _operation(
        operation_id=operation_id,
        request_id=uuid4(),
    )
    service, barrier = _service(repository, state_store)

    with pytest.raises(LiveOrderControlDrainPendingError) as exc_info:
        asyncio.run(
            service.prepare_liquidation(
                PrepareEmergencyLiquidationCommand(
                    request_id=uuid4(),
                    operation_id=operation_id,
                    reason_code="EMERGENCY_LIQUIDATION_PREPARE",
                    reason_text="진행 중 제출 종료를 확인하고 청산 대상을 확정합니다.",
                    source="REST",
                    actor_ref="liquidation-coordinator",
                )
            )
        )

    assert exc_info.value.error_code == "ORDER_GATE_DRAIN_PENDING"
    assert repository.control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert state_store.bot_active is False
    assert barrier.events[-1] == "exclusive-exit"


def test_liquidation_preparation_cannot_replay_after_newer_stop_event() -> None:
    operation_id = 42
    repository = _FakeRepository(
        _control(mode=LIVE_ORDER_MODE_ARMED, generation=5, version=9)
    )
    state_store = _FakeStateStore()
    state_store.operations[operation_id] = _operation(
        operation_id=operation_id,
        request_id=uuid4(),
    )
    service, _ = _service(repository, state_store)
    prepare = PrepareEmergencyLiquidationCommand(
        request_id=uuid4(),
        operation_id=operation_id,
        reason_code="EMERGENCY_LIQUIDATION_PREPARE",
        reason_text="전량청산 대상 조회 전에 일반 실주문을 먼저 차단합니다.",
        source="REST",
        actor_ref="liquidation-coordinator",
    )

    asyncio.run(service.prepare_liquidation(prepare))
    asyncio.run(
        service.block(
            BlockLiveOrdersCommand(
                request_id=uuid4(),
                reason_code="OPERATOR_BLOCK",
                reason_text="운영자가 준비 중인 청산을 포함해 신규 실주문을 다시 차단했습니다.",
                source="REST",
                actor_ref="rest-admin",
            )
        )
    )

    with pytest.raises(LiveOrderControlRequestSupersededError):
        asyncio.run(service.prepare_liquidation(prepare))


def test_liquidation_authorization_binds_operation_and_replays_idempotently() -> None:
    request_id = uuid4()
    operation_id = 77
    repository = _FakeRepository(_control(generation=4, version=6))
    state_store = _FakeStateStore()
    state_store.operations[operation_id] = _operation(
        operation_id=operation_id,
        request_id=request_id,
    )
    service, _ = _service(repository, state_store)
    command = AuthorizeEmergencyLiquidationCommand(
        request_id=request_id,
        operation_id=operation_id,
        expected_generation=4,
        expected_version=6,
        reason_code="OPERATOR_LIQUIDATION",
        reason_text="운영자가 보유 자산 전량청산 범위를 명시적으로 승인했습니다.",
        source="REST",
        actor_ref="rest-admin",
    )

    first = asyncio.run(service.authorize_liquidation(command))
    replay = asyncio.run(service.authorize_liquidation(command))

    operation = state_store.operations[operation_id]
    assert first.control.mode == LIVE_ORDER_MODE_EXIT_ONLY
    assert first.control.active_liquidation_operation_id == operation_id
    assert first.event.action == CONTROL_ACTION_LIQUIDATION_AUTHORIZED
    assert operation.emergency_authorization_status == EMERGENCY_AUTHORIZATION_ACTIVE
    assert operation.emergency_control_generation == first.control.generation
    assert operation.emergency_control_event_id == first.event.id
    assert operation.emergency_authorized_source == "REST"
    assert operation.emergency_revoked_at is None
    assert state_store.bot_active is False
    assert replay.replayed is True
    assert len(repository.events_by_request_id) == 1


def test_liquidation_authorization_requires_immutable_target_snapshot() -> None:
    request_id = uuid4()
    operation_id = 78
    repository = _FakeRepository(_control(generation=4, version=6))
    state_store = _FakeStateStore()
    operation = _operation(operation_id=operation_id, request_id=request_id)
    operation.target_snapshot = []
    state_store.operations[operation_id] = operation
    service, _ = _service(repository, state_store)

    with pytest.raises(LiveOrderControlPolicyError) as exc_info:
        asyncio.run(
            service.authorize_liquidation(
                AuthorizeEmergencyLiquidationCommand(
                    request_id=request_id,
                    operation_id=operation_id,
                    expected_generation=4,
                    expected_version=6,
                    reason_code="OPERATOR_LIQUIDATION",
                    reason_text="운영자가 보유 자산 전량청산 범위를 명시적으로 승인했습니다.",
                    source="REST",
                    actor_ref="rest-admin",
                )
            )
        )

    assert exc_info.value.error_code == "EMERGENCY_AUTH_REQUIRED"
    assert repository.transition_calls == []


def test_explicitly_revoked_liquidation_cannot_be_reauthorized() -> None:
    request_id = uuid4()
    operation_id = 79
    repository = _FakeRepository(_control(generation=4, version=6))
    state_store = _FakeStateStore()
    operation = _operation(operation_id=operation_id, request_id=request_id)
    operation.emergency_revocation_reason = "운영자가 청산 권한을 명시적으로 폐기했습니다."
    state_store.operations[operation_id] = operation
    service, _ = _service(repository, state_store)

    with pytest.raises(LiveOrderControlPolicyError) as exc_info:
        asyncio.run(
            service.authorize_liquidation(
                AuthorizeEmergencyLiquidationCommand(
                    request_id=request_id,
                    operation_id=operation_id,
                    expected_generation=4,
                    expected_version=6,
                    reason_code="OPERATOR_LIQUIDATION",
                    reason_text="운영자가 보유 자산 전량청산 범위를 명시적으로 승인했습니다.",
                    source="REST",
                    actor_ref="rest-admin",
                )
            )
        )

    assert exc_info.value.error_code == "EMERGENCY_AUTH_REVOKED"
    assert repository.transition_calls == []


def test_terminal_liquidation_cannot_replay_active_authorization() -> None:
    request_id = uuid4()
    operation_id = 80
    repository = _FakeRepository(_control(generation=4, version=6))
    state_store = _FakeStateStore()
    operation = _operation(operation_id=operation_id, request_id=request_id)
    state_store.operations[operation_id] = operation
    service, _ = _service(repository, state_store)
    command = AuthorizeEmergencyLiquidationCommand(
        request_id=request_id,
        operation_id=operation_id,
        expected_generation=4,
        expected_version=6,
        reason_code="OPERATOR_LIQUIDATION",
        reason_text="운영자가 보유 자산 전량청산 범위를 명시적으로 승인했습니다.",
        source="REST",
        actor_ref="rest-admin",
    )
    asyncio.run(service.authorize_liquidation(command))
    operation.status = "COMPLETED"

    with pytest.raises(
        LiveOrderControlStateUnavailableError,
        match="재생된 청산 승인 event",
    ):
        asyncio.run(service.authorize_liquidation(command))


def test_revoked_liquidation_finalizer_never_reopens_gate() -> None:
    operation_id = 91
    repository = _FakeRepository(_control())
    state_store = _FakeStateStore()
    state_store.operations[operation_id] = _operation(
        operation_id=operation_id,
        request_id=uuid4(),
        status="FAILED",
        authorization_status=EMERGENCY_AUTHORIZATION_REVOKED,
    )
    service, _ = _service(repository, state_store)

    result = asyncio.run(
        service.close_liquidation(
            CloseEmergencyLiquidationCommand(
                request_id=uuid4(),
                operation_id=operation_id,
                reason_code="LIQUIDATION_FINALIZED",
                reason_text="청산 실패 결과 병합",
                source="SYSTEM",
                actor_ref="liquidation-worker",
            )
        )
    )

    assert result.transition is None
    assert result.skipped_due_to_revocation is True
    assert result.control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert repository.transition_calls == []
