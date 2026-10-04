from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.db.live_order_control_repository import (
    CONTROL_ACTION_LIQUIDATION_AUTHORIZED,
    EMERGENCY_AUTHORIZATION_ACTIVE,
    EMERGENCY_AUTHORIZATION_CLOSED,
    EMERGENCY_AUTHORIZATION_REVOKED,
    LIVE_ORDER_MODE_ARMED,
    LIVE_ORDER_MODE_EXIT_ONLY,
    EmergencyLiquidationAuthorizationRecord,
    LiveOrderControlRecord,
    LiveOrderSubmissionGateSnapshot,
)
from app.models.domain import LiquidationOperation
from app.services.trading.liquidation import (
    LIQUIDATION_TERMINAL_STATUSES,
    LiquidationCoordinator,
    liquidation_operation_response,
)
from app.services.trading.live_order_control import (
    INITIAL_EMERGENCY_REVOCATION_REASON,
    LiveOrderControlPolicyError,
)

NOW = datetime(2026, 7, 10, tzinfo=UTC)
OPERATION_KEY = "11111111-1111-4111-8111-111111111111"


def _operation(
    *,
    status: str = "IN_PROGRESS",
    authorization_status: str = EMERGENCY_AUTHORIZATION_REVOKED,
    revocation_reason: str | None = INITIAL_EMERGENCY_REVOCATION_REASON,
) -> LiquidationOperation:
    operation = LiquidationOperation(
        id=7,
        idempotency_key=OPERATION_KEY,
        status=status,
        target_snapshot=[{"market": "KRW-BTC", "volume": "0.1"}],
        result_snapshot=[],
        created_at=NOW,
        updated_at=NOW,
        completed_at=(NOW if status in LIQUIDATION_TERMINAL_STATUSES else None),
        emergency_authorization_status=authorization_status,
        emergency_revoked_at=(
            NOW if authorization_status == EMERGENCY_AUTHORIZATION_REVOKED else None
        ),
        emergency_revocation_reason=(
            revocation_reason
            if authorization_status == EMERGENCY_AUTHORIZATION_REVOKED
            else None
        ),
        emergency_closed_at=(
            NOW if authorization_status == EMERGENCY_AUTHORIZATION_CLOSED else None
        ),
    )
    if authorization_status == EMERGENCY_AUTHORIZATION_ACTIVE:
        operation.emergency_authorized_at = NOW
        operation.emergency_control_generation = 4
        operation.emergency_control_event_id = 13
        operation.emergency_authorized_source = "SYSTEM"
    return operation


def _control(
    *,
    mode: str,
    operation_id: int | None,
    generation: int = 4,
    version: int = 8,
) -> LiveOrderControlRecord:
    return LiveOrderControlRecord(
        id=1,
        broker="UPBIT",
        account_scope="primary",
        mode=mode,
        active_liquidation_operation_id=operation_id,
        generation=generation,
        version=version,
        reason_code="TEST",
        reason_text="test",
        changed_source="SYSTEM",
        changed_actor_ref=None,
        armed_at=None,
        blocked_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


class _FakeSession:
    def __init__(self, operation: LiquidationOperation) -> None:
        self.operation = operation

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def get(self, _model, operation_id: int):
        return self.operation if operation_id == self.operation.id else None

    async def commit(self) -> None:
        return None


class _FakeSessionFactory:
    def __init__(self, operation: LiquidationOperation) -> None:
        self.operation = operation

    def __call__(self) -> _FakeSession:
        return _FakeSession(self.operation)


class _FakeControlRepository:
    def __init__(self, gate: LiveOrderSubmissionGateSnapshot) -> None:
        self.gate = gate
        self.transition_calls: list[dict[str, object]] = []
        self.event = None

    async def get_submission_gate_snapshot(self, _db):
        return self.gate

    async def get_control(self, _db, *, for_update: bool = False):
        assert for_update
        return self.gate.control

    async def get_event(self, _db, _request_id):
        return self.event

    async def transition_control(self, _db, **kwargs):
        self.transition_calls.append(kwargs)
        return SimpleNamespace()


class _FakeControlService:
    def __init__(self, *, prepare_in_transaction_error: Exception | None = None) -> None:
        self.prepare_commands = []
        self.prepare_in_transaction_commands = []
        self.prepare_in_transaction_error = prepare_in_transaction_error
        self.authorize_commands = []
        self.close_commands = []
        self.close_in_transaction_commands = []

    async def prepare_liquidation(self, command):
        self.prepare_commands.append(command)
        return SimpleNamespace()

    async def prepare_liquidation_in_transaction(self, _db, command):
        self.prepare_in_transaction_commands.append(command)
        if self.prepare_in_transaction_error is not None:
            raise self.prepare_in_transaction_error
        return SimpleNamespace(), False

    async def authorize_liquidation(self, command):
        self.authorize_commands.append(command)
        return SimpleNamespace()

    async def close_liquidation(self, command):
        self.close_commands.append(command)
        return SimpleNamespace()

    async def close_liquidation_in_transaction(self, _db, command):
        self.close_in_transaction_commands.append(command)
        return SimpleNamespace()


class _FakeStateStore:
    def __init__(
        self,
        operation: LiquidationOperation,
        *,
        trading_mode: str | None = "live",
    ) -> None:
        self.operation = operation
        self.trading_mode = trading_mode
        self.bot_active_values: list[bool] = []

    async def get_liquidation_operation_for_update(self, _db, operation_id: int):
        return self.operation if operation_id == self.operation.id else None

    async def set_bot_active(self, _db, *, is_active: bool) -> None:
        self.bot_active_values.append(is_active)

    async def get_trading_mode(self, _db) -> str | None:
        return self.trading_mode


class _FakeLeaseDb:
    async def flush(self) -> None:
        return None


class _FakeLease:
    def __init__(self) -> None:
        self.db = _FakeLeaseDb()

    @asynccontextmanager
    async def transaction(self):
        yield self.db


class _FakeBarrier:
    @asynccontextmanager
    async def exclusive(self):
        yield _FakeLease()


class _OperationHarness(LiquidationCoordinator):
    def __init__(self, operation: LiquidationOperation) -> None:
        self.operation = operation
        self.closed_ids: list[int] = []
        self.preparation_calls = 0
        self.target_snapshot_calls = 0
        self.order_service = SimpleNamespace(execute=self._unexpected_order)
        self._order_service = self.order_service

    async def _unexpected_order(self, _request):
        raise AssertionError("주문 실행 경로가 호출되면 안 됩니다.")

    async def _create_or_get_operation(self, _idempotency_key: str):
        return self.operation

    async def _prepare_snapshot_and_authorize(self, _operation: LiquidationOperation):
        self.preparation_calls += 1
        self.target_snapshot_calls += 1
        return self.operation.target_snapshot

    async def _close_terminal_operation(self, operation_id: int) -> None:
        self.closed_ids.append(operation_id)


@pytest.mark.asyncio
async def test_closed_terminal_replay_is_pure_lookup_without_gate_finalizer() -> None:
    operation = _operation(
        status="COMPLETED",
        authorization_status=EMERGENCY_AUTHORIZATION_CLOSED,
        revocation_reason=None,
    )
    coordinator = _OperationHarness(operation)

    response = await coordinator.execute(OPERATION_KEY)

    assert response.status == "COMPLETED"
    assert coordinator.preparation_calls == 0
    assert coordinator.target_snapshot_calls == 0
    assert coordinator.closed_ids == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["IN_PROGRESS", "FAILED"])
async def test_explicitly_revoked_operation_cannot_be_reauthorized(status: str) -> None:
    operation = _operation(
        status=status,
        revocation_reason="관리자가 청산 권한을 명시적으로 폐기했습니다.",
    )
    coordinator = _OperationHarness(operation)

    with pytest.raises(LiveOrderControlPolicyError) as raised:
        await coordinator.execute(OPERATION_KEY)

    assert raised.value.error_code == "EMERGENCY_AUTH_REVOKED"
    assert coordinator.preparation_calls == 0
    assert coordinator.target_snapshot_calls == 0
    assert coordinator.closed_ids == []


@pytest.mark.asyncio
async def test_initial_operation_blocks_and_drains_before_target_snapshot() -> None:
    operation = _operation(status="PREPARING")

    class _PreparationOrderHarness(_OperationHarness):
        def __init__(self, current: LiquidationOperation) -> None:
            super().__init__(current)
            self.events: list[str] = []

        async def _prepare_snapshot_and_authorize(
            self,
            _operation: LiquidationOperation,
        ):
            self.events.extend(["prepare", "snapshot"])
            self.operation.target_snapshot = []
            self.operation.status = "NO_ASSETS"
            self.operation.completed_at = NOW
            return []

        async def get_operation(self, operation_id: int):
            await self._close_terminal_operation(operation_id)
            return liquidation_operation_response(self.operation)

    coordinator = _PreparationOrderHarness(operation)

    response = await coordinator.execute(OPERATION_KEY)

    assert response.status == "NO_ASSETS"
    assert coordinator.events == ["prepare", "snapshot"]


@pytest.mark.asyncio
async def test_prepare_failure_never_reads_accounts_or_builds_snapshot() -> None:
    operation = _operation(status="PREPARING")

    class _PreparationFailureHarness(_OperationHarness):
        async def _prepare_snapshot_and_authorize(
            self,
            _operation: LiquidationOperation,
        ):
            raise LiveOrderControlPolicyError(
                "진행 중 제출 drain을 확인하지 못했습니다.",
                error_code="ORDER_GATE_DRAIN_PENDING",
            )

    coordinator = _PreparationFailureHarness(operation)

    with pytest.raises(LiveOrderControlPolicyError) as raised:
        await coordinator.execute(OPERATION_KEY)

    assert raised.value.error_code == "ORDER_GATE_DRAIN_PENDING"
    assert coordinator.target_snapshot_calls == 0


@pytest.mark.asyncio
async def test_paper_mode_prepare_marks_operation_failed_instead_of_leaving_orphan() -> None:
    operation = _operation(status="PREPARING")
    operation.target_snapshot = None
    operation.result_snapshot = None
    control = _control(
        mode=LIVE_ORDER_MODE_ARMED,
        operation_id=None,
    )
    service = _FakeControlService()
    coordinator = object.__new__(LiquidationCoordinator)
    coordinator._submission_barrier = _FakeBarrier()
    coordinator._control_state_store = _FakeStateStore(
        operation,
        trading_mode="paper",
    )
    coordinator._control_repository = _FakeControlRepository(
        LiveOrderSubmissionGateSnapshot(
            rollout_enabled=True,
            bot_active=False,
            control=control,
            trading_mode="paper",
            trading_mode_state_available=True,
        )
    )
    coordinator._control_service = service

    with pytest.raises(LiveOrderControlPolicyError) as raised:
        await coordinator._prepare_snapshot_and_authorize(operation)

    assert raised.value.error_code == "TRADING_MODE_LIVE_REQUIRED"
    assert operation.status == "FAILED"
    assert operation.completed_at is not None
    assert operation.emergency_authorization_status == EMERGENCY_AUTHORIZATION_REVOKED
    assert operation.emergency_revocation_reason == "TRADING_MODE_LIVE_REQUIRED"
    assert service.prepare_in_transaction_commands == []


@pytest.mark.asyncio
async def test_prepare_policy_failure_marks_operation_failed_instead_of_leaving_orphan() -> None:
    operation = _operation(status="PREPARING")
    operation.target_snapshot = None
    operation.result_snapshot = None
    control = _control(
        mode=LIVE_ORDER_MODE_ARMED,
        operation_id=None,
    )
    service = _FakeControlService(
        prepare_in_transaction_error=LiveOrderControlPolicyError(
            "실주문 rollout이 비활성화되어 청산을 준비할 수 없습니다.",
            error_code="LIVE_ORDER_V2_DISABLED",
        )
    )
    coordinator = object.__new__(LiquidationCoordinator)
    coordinator._submission_barrier = _FakeBarrier()
    coordinator._control_state_store = _FakeStateStore(operation, trading_mode="live")
    coordinator._control_repository = _FakeControlRepository(
        LiveOrderSubmissionGateSnapshot(
            rollout_enabled=False,
            bot_active=False,
            control=control,
            trading_mode="live",
            trading_mode_state_available=True,
        )
    )
    coordinator._control_service = service

    with pytest.raises(LiveOrderControlPolicyError) as raised:
        await coordinator._prepare_snapshot_and_authorize(operation)

    assert raised.value.error_code == "LIVE_ORDER_V2_DISABLED"
    assert operation.status == "FAILED"
    assert operation.completed_at is not None
    assert operation.emergency_authorization_status == EMERGENCY_AUTHORIZATION_REVOKED
    assert operation.emergency_revocation_reason == "LIVE_ORDER_V2_DISABLED"
    assert len(service.prepare_in_transaction_commands) == 1


@pytest.mark.asyncio
async def test_active_same_operation_replay_reuses_exit_only_authorization() -> None:
    operation = _operation(authorization_status=EMERGENCY_AUTHORIZATION_ACTIVE)
    control = _control(mode=LIVE_ORDER_MODE_EXIT_ONLY, operation_id=operation.id)
    authorization = EmergencyLiquidationAuthorizationRecord(
        operation_id=operation.id,
        operation_idempotency_key=operation.idempotency_key,
        operation_status="IN_PROGRESS",
        authorization_status=EMERGENCY_AUTHORIZATION_ACTIVE,
        control_generation=control.generation,
        control_event_id=13,
        authorized_source="SYSTEM",
        event_control_id=control.id,
        event_generation=control.generation,
        event_request_id=operation.idempotency_key,
        event_request_fingerprint="a" * 64,
        event_action=CONTROL_ACTION_LIQUIDATION_AUTHORIZED,
        event_to_mode=LIVE_ORDER_MODE_EXIT_ONLY,
        event_source="SYSTEM",
        event_liquidation_operation_id=operation.id,
        target_snapshot=(("KRW-BTC", "0.1"),),
    )
    repository = _FakeControlRepository(
        LiveOrderSubmissionGateSnapshot(
            rollout_enabled=True,
            bot_active=False,
            control=control,
            emergency_authorization=authorization,
            trading_mode="live",
            trading_mode_state_available=True,
        )
    )
    service = _FakeControlService()
    coordinator = object.__new__(LiquidationCoordinator)
    coordinator._session_factory = _FakeSessionFactory(operation)
    coordinator._control_repository = repository
    coordinator._control_service = service

    await coordinator._ensure_liquidation_authorized(operation)

    assert service.authorize_commands == []


@pytest.mark.asyncio
async def test_initial_operation_authorization_uses_operation_uuid_and_control_cas() -> None:
    operation = _operation()
    control = _control(
        mode=LIVE_ORDER_MODE_ARMED,
        operation_id=None,
        generation=3,
        version=9,
    )
    repository = _FakeControlRepository(
        LiveOrderSubmissionGateSnapshot(
            rollout_enabled=True,
            bot_active=True,
            control=control,
        )
    )
    service = _FakeControlService()
    coordinator = object.__new__(LiquidationCoordinator)
    coordinator._session_factory = _FakeSessionFactory(operation)
    coordinator._control_repository = repository
    coordinator._control_service = service

    await coordinator._ensure_liquidation_authorized(operation)

    assert len(service.authorize_commands) == 1
    command = service.authorize_commands[0]
    assert command.request_id == OPERATION_KEY
    assert command.operation_id == operation.id
    assert command.expected_generation == 3
    assert command.expected_version == 9
    assert command.source == "REST"


@pytest.mark.asyncio
async def test_no_assets_path_uses_terminal_close_lifecycle() -> None:
    operation = _operation(status="PREPARING")

    class _NoAssetsHarness(_OperationHarness):
        async def _prepare_snapshot_and_authorize(
            self,
            _operation: LiquidationOperation,
        ):
            self.preparation_calls += 1
            self.target_snapshot_calls += 1
            self.operation.target_snapshot = []
            self.operation.status = "NO_ASSETS"
            self.operation.completed_at = NOW
            return []

        async def get_operation(self, operation_id: int):
            await self._close_terminal_operation(operation_id)
            return liquidation_operation_response(self.operation)

    coordinator = _NoAssetsHarness(operation)

    response = await coordinator.execute(OPERATION_KEY)

    assert response.status == "NO_ASSETS"
    assert coordinator.preparation_calls == 1
    assert coordinator.closed_ids == [operation.id]


@pytest.mark.asyncio
async def test_refresh_worker_path_recovers_terminal_control_close() -> None:
    operation = _operation(
        status="PARTIAL",
        authorization_status=EMERGENCY_AUTHORIZATION_ACTIVE,
        revocation_reason=None,
    )

    class _RefreshHarness(LiquidationCoordinator):
        def __init__(self) -> None:
            self.atomic_refresh_ids: list[int] = []

        async def _refresh_operation_state(self, _operation_id: int):
            self.atomic_refresh_ids.append(_operation_id)
            return liquidation_operation_response(operation)

    coordinator = _RefreshHarness()

    response = await coordinator.refresh_operation(operation.id)

    assert response.status == "PARTIAL"
    assert coordinator.atomic_refresh_ids == [operation.id]


@pytest.mark.asyncio
async def test_active_terminal_close_uses_stable_separate_uuid4() -> None:
    operation = _operation(
        status="FAILED",
        authorization_status=EMERGENCY_AUTHORIZATION_ACTIVE,
        revocation_reason=None,
    )
    service = _FakeControlService()

    coordinator = object.__new__(LiquidationCoordinator)
    coordinator._control_service = service

    await coordinator._finalize_terminal_in_transaction(object(), operation)
    await coordinator._finalize_terminal_in_transaction(object(), operation)

    request_ids = [
        command.request_id for command in service.close_in_transaction_commands
    ]
    assert len(request_ids) == 2
    assert request_ids[0] == request_ids[1]
    assert isinstance(request_ids[0], UUID)
    assert request_ids[0].version == 4
    assert str(request_ids[0]) != operation.idempotency_key


@pytest.mark.asyncio
async def test_initial_terminal_block_is_conditional_and_stops_runtime() -> None:
    operation = _operation(status="NO_ASSETS")
    control = _control(mode=LIVE_ORDER_MODE_ARMED, operation_id=None)
    repository = _FakeControlRepository(
        LiveOrderSubmissionGateSnapshot(
            rollout_enabled=True,
            bot_active=True,
            control=control,
        )
    )
    state_store = _FakeStateStore(operation)

    class _BlockHarness(LiquidationCoordinator):
        async def _get_operation_model(self, _operation_id: int):
            return operation

    coordinator = object.__new__(_BlockHarness)
    coordinator._submission_barrier = _FakeBarrier()
    coordinator._control_repository = repository
    coordinator._control_state_store = state_store

    should_close = await coordinator._block_initial_terminal_operation(operation.id)

    assert should_close is True
    assert state_store.bot_active_values == [False]
    assert len(repository.transition_calls) == 1
    assert repository.transition_calls[0]["target_mode"] == "BLOCK_ALL"
    assert operation.emergency_authorization_status == EMERGENCY_AUTHORIZATION_CLOSED
    assert operation.emergency_closed_at is not None
    assert operation.emergency_revoked_at is None
    assert operation.emergency_revocation_reason is None


@pytest.mark.asyncio
async def test_initial_terminal_does_not_revoke_other_active_operation() -> None:
    operation = _operation(status="NO_ASSETS")
    repository = _FakeControlRepository(
        LiveOrderSubmissionGateSnapshot(
            rollout_enabled=True,
            bot_active=False,
            control=_control(mode=LIVE_ORDER_MODE_EXIT_ONLY, operation_id=999),
        )
    )
    state_store = _FakeStateStore(operation)

    class _ConflictHarness(LiquidationCoordinator):
        async def _get_operation_model(self, _operation_id: int):
            return operation

    coordinator = object.__new__(_ConflictHarness)
    coordinator._submission_barrier = _FakeBarrier()
    coordinator._control_repository = repository
    coordinator._control_state_store = state_store

    with pytest.raises(LiveOrderControlPolicyError) as raised:
        await coordinator._block_initial_terminal_operation(operation.id)

    assert raised.value.error_code == "ORDER_GATE_GENERATION_CONFLICT"
    assert state_store.bot_active_values == []
    assert repository.transition_calls == []
