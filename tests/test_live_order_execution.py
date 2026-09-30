import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.db.order_intent_repository import (
    CreateOrGetIntentResult,
    OrderIntentRecord,
    reconciliation_backoff,
)
from app.db.live_order_control_repository import (
    EMERGENCY_AUTHORIZATION_ACTIVE,
    LIVE_ORDER_MODE_ARMED,
    LIVE_ORDER_MODE_EXIT_ONLY,
    EmergencyLiquidationAuthorizationRecord,
    LiveOrderControlRecord,
    LiveOrderSubmissionGateSnapshot,
)
from app.services.brokers.upbit import UpbitAPIError
from app.services.trading.live_order_execution import (
    LiveOrderExecutionService,
    LiveOrderRequest,
    build_intent_key,
    build_request_fingerprint,
)
from app.services.trading.live_order_submission_barrier import (
    LiveOrderSubmissionBarrierUnavailableError,
)


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _tb):
        return False

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _FakeSessionFactory:
    def __call__(self):
        return _FakeSession()


class _FakeLease:
    @asynccontextmanager
    async def transaction(self):
        yield _FakeSession()

    @property
    def has_active_transaction(self) -> bool:
        return False

    async def assert_no_transaction(self) -> None:
        return None


class _FakeBarrier:
    def __init__(self) -> None:
        self.shared_count = 0

    @asynccontextmanager
    async def shared(self, **_kwargs):
        self.shared_count += 1
        yield _FakeLease()

    @asynccontextmanager
    async def exclusive(self, **_kwargs):
        yield _FakeLease()


class _AcquireFailBarrier(_FakeBarrier):
    def __init__(self) -> None:
        super().__init__()

    @asynccontextmanager
    async def shared(self, **_kwargs):
        self.shared_count += 1
        if self.shared_count == 2:
            raise LiveOrderSubmissionBarrierUnavailableError(
                "테스트 획득 실패",
                phase="acquire",
            )
        yield _FakeLease()


class _ReleaseFailBarrier(_FakeBarrier):
    def __init__(self) -> None:
        super().__init__()

    @asynccontextmanager
    async def shared(self, **_kwargs):
        self.shared_count += 1
        yield _FakeLease()
        if self.shared_count == 2:
            raise LiveOrderSubmissionBarrierUnavailableError(
                "테스트 해제 실패",
                phase="release",
            )


def _record(**overrides) -> OrderIntentRecord:
    now = datetime.now(UTC)
    values = {
        "id": 1,
        "intent_key": "a" * 64,
        "identifier": "b" * 32,
        "request_fingerprint": "c" * 64,
        "source_type": "AI",
        "source_ref": "analysis:1",
        "market": "KRW-BTC",
        "side": "bid",
        "ord_type": "price",
        "requested_price": Decimal("10000"),
        "requested_volume": None,
        "execution_policy": "GENERAL",
        "ai_analysis_log_id": 1,
        "liquidation_operation_id": None,
        "order_reason": None,
        "broker": "UPBIT",
        "account_scope": "primary",
        "submission_status": "PREPARED",
        "exchange_uuid": None,
        "exchange_state": None,
        "executed_volume": None,
        "executed_funds": None,
        "average_fill_price": None,
        "remaining_volume": None,
        "paid_fee": None,
        "projection_status": "PENDING",
        "post_attempt_count": 0,
        "reconcile_attempt_count": 0,
        "version": 0,
        "next_reconcile_at": None,
        "reconcile_lease_until": None,
        "last_error_code": None,
        "last_error_message": None,
        "not_found_count": 0,
        "first_not_found_at": None,
        "last_not_found_at": None,
        "created_at": now,
        "submitted_at": None,
        "accepted_at": None,
        "unknown_at": None,
        "last_checked_at": None,
        "resolved_at": None,
        "order_history_id": None,
        "prepared_control_generation": 1,
        "prepared_control_mode": LIVE_ORDER_MODE_ARMED,
    }
    values.update(overrides)
    return OrderIntentRecord(**values)


class _FakeRepository:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.current: OrderIntentRecord | None = None
        self.disabled = False
        self.projection_failures = 0

    async def find_intent_by_key(self, _db, intent_key):
        if self.current is not None and self.current.intent_key == intent_key:
            return self.current
        return None

    async def is_live_order_v2_enabled(self, _db):
        return self.enabled and not self.disabled

    async def disable_live_order_v2(self, _db):
        self.disabled = True

    async def create_or_get_intent(self, _db, draft):
        self.current = _record(
            intent_key=draft.intent_key,
            identifier=draft.identifier,
            request_fingerprint=draft.request_fingerprint,
            source_type=draft.source_type,
            source_ref=draft.source_ref,
            market=draft.market,
            side=draft.side,
            ord_type=draft.ord_type,
            requested_price=draft.requested_price,
            requested_volume=draft.requested_volume,
            execution_policy=draft.execution_policy,
            ai_analysis_log_id=draft.ai_analysis_log_id,
            liquidation_operation_id=draft.liquidation_operation_id,
            order_reason=draft.order_reason,
            prepared_control_generation=draft.prepared_control_generation,
            prepared_control_mode=draft.prepared_control_mode,
        )
        return CreateOrGetIntentResult(self.current, created=True, blocking_intent=False)

    async def get_intent(self, _db, _intent_id, **_kwargs):
        return self.current

    async def claim_submission(self, _db, _intent_id, **_kwargs):
        self.current = replace(
            self.current,
            submission_status="SUBMITTING",
            post_attempt_count=1,
            version=self.current.version + 1,
            control_generation=_kwargs["control_generation"],
            control_mode=_kwargs["control_mode"],
            control_event_id=_kwargs["control_event_id"],
            submission_authorized_at=_kwargs["now"],
        )
        return self.current

    async def abandon_prepared(
        self,
        _db,
        _intent_id,
        *,
        error_code,
        error_message,
        **_kwargs,
    ):
        self.current = replace(
            self.current,
            submission_status="ABANDONED",
            projection_status="SKIPPED",
            last_error_code=error_code,
            last_error_message=error_message,
            version=self.current.version + 1,
        )
        return self.current

    async def mark_unknown(
        self,
        _db,
        _intent_id,
        *,
        error_code,
        error_message,
        not_found_count=0,
        **_kwargs,
    ):
        status = (
            "ACCEPTED" if self.current.submission_status == "ACCEPTED" else "UNKNOWN"
        )
        self.current = replace(
            self.current,
            submission_status=status,
            last_error_code=error_code,
            last_error_message=error_message,
            not_found_count=self.current.not_found_count + not_found_count,
        )
        return self.current

    async def claim_reconciliation(self, _db, _intent_id, **_kwargs):
        self.current = replace(
            self.current,
            submission_status=(
                "UNKNOWN"
                if self.current.submission_status == "SUBMITTING"
                else self.current.submission_status
            ),
            reconcile_attempt_count=self.current.reconcile_attempt_count + 1,
        )
        return self.current

    async def claim_due_reconciliation(self, _db, **_kwargs):
        return []

    async def mark_accepted(
        self,
        _db,
        _intent_id,
        *,
        exchange_uuid,
        exchange_state,
        executed_volume,
        executed_funds,
        average_fill_price,
        remaining_volume,
        paid_fee,
        **_kwargs,
    ):
        self.current = replace(
            self.current,
            submission_status="ACCEPTED",
            exchange_uuid=exchange_uuid,
            exchange_state=exchange_state,
            executed_volume=executed_volume,
            executed_funds=executed_funds,
            average_fill_price=average_fill_price,
            remaining_volume=remaining_volume,
            paid_fee=paid_fee,
            last_error_code=None,
            last_error_message=None,
        )
        return self.current

    async def mark_rejected(
        self,
        _db,
        _intent_id,
        *,
        error_code,
        error_message,
        **_kwargs,
    ):
        self.current = replace(
            self.current,
            submission_status="REJECTED",
            projection_status="SKIPPED",
            last_error_code=error_code,
            last_error_message=error_message,
        )
        return self.current

    async def mark_reconciliation_conflict(
        self,
        _db,
        _intent_id,
        *,
        error_message,
        **_kwargs,
    ):
        self.current = replace(
            self.current,
            submission_status="UNKNOWN",
            projection_status="ERROR",
            last_error_code="RECONCILIATION_CONFLICT",
            last_error_message=error_message,
        )
        return self.current

    async def project_terminal_fill(self, _db, _intent_id, **_kwargs):
        if self.projection_failures > 0:
            self.projection_failures -= 1
            raise RuntimeError("일시적인 projection 실패")
        projection = "APPLIED" if (self.current.executed_volume or 0) > 0 else "SKIPPED"
        self.current = replace(
            self.current,
            projection_status=projection,
            order_history_id=7 if projection == "APPLIED" else None,
        )
        return self.current

    async def mark_projection_error(
        self,
        _db,
        _intent_id,
        *,
        error_code,
        error_message,
        **_kwargs,
    ):
        self.current = replace(
            self.current,
            projection_status="ERROR",
            last_error_code=error_code,
            last_error_message=error_message,
        )
        return self.current


class _FakeControlRepository:
    def __init__(
        self,
        order_repository: _FakeRepository,
        snapshot: LiveOrderSubmissionGateSnapshot | None = None,
    ) -> None:
        self._order_repository = order_repository
        self._snapshot = snapshot

    async def get_submission_gate_snapshot(self, _db):
        if self._snapshot is not None:
            return self._snapshot
        now = datetime.now(UTC)
        control = LiveOrderControlRecord(
            id=1,
            broker="UPBIT",
            account_scope="primary",
            mode=LIVE_ORDER_MODE_ARMED,
            active_liquidation_operation_id=None,
            generation=1,
            version=1,
            reason_code="TEST_ARMED",
            reason_text="테스트 일반 실주문 승인",
            changed_source="SYSTEM",
            changed_actor_ref="pytest",
            armed_at=now,
            blocked_at=None,
            created_at=now,
            updated_at=now,
        )
        return LiveOrderSubmissionGateSnapshot(
            rollout_enabled=(
                self._order_repository.enabled
                and not self._order_repository.disabled
            ),
            bot_active=True,
            control=control,
            general_authorization_event_id=1,
            trading_mode="live",
            trading_mode_state_available=True,
        )

    async def get_control(self, db):
        return (await self.get_submission_gate_snapshot(db)).control


class _SequenceControlRepository(_FakeControlRepository):
    def __init__(self, order_repository: _FakeRepository, snapshots):
        super().__init__(order_repository)
        self._snapshots = list(snapshots)

    async def get_submission_gate_snapshot(self, _db):
        if len(self._snapshots) > 1:
            return self._snapshots.pop(0)
        return self._snapshots[0]


class _FakeControlService:
    def __init__(self, order_repository: _FakeRepository) -> None:
        self._order_repository = order_repository
        self.trip_count = 0
        self.commands = []

    async def trip_on_auth_failure(self, command):
        self.trip_count += 1
        self.commands.append(command)
        self._order_repository.disabled = True


class _FakeBroker:
    def __init__(self, create_result, lookup_result) -> None:
        self.create_result = create_result
        self.lookup_result = lookup_result
        self.create_count = 0
        self.lookup_count = 0
        self.identifier: str | None = None

    async def create_order(self, **kwargs):
        self.create_count += 1
        self.identifier = kwargs["identifier"]
        if isinstance(self.create_result, Exception):
            raise self.create_result
        result = dict(self.create_result)
        result.setdefault("identifier", self.identifier)
        return result

    async def get_order(self, **_kwargs):
        self.lookup_count += 1
        if isinstance(self.lookup_result, Exception):
            raise self.lookup_result
        result = dict(self.lookup_result)
        result.setdefault("identifier", self.identifier)
        return result


class _SequenceLookupBroker(_FakeBroker):
    def __init__(self, create_result, lookup_results) -> None:
        super().__init__(create_result, {})
        self.lookup_results = list(lookup_results)

    async def get_order(self, **_kwargs):
        self.lookup_count += 1
        result = self.lookup_results.pop(0)
        if isinstance(result, Exception):
            raise result
        payload = dict(result)
        payload.setdefault("identifier", self.identifier)
        return payload


class _FailingAcceptRepository(_FakeRepository):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_accept = True

    async def mark_accepted(self, *args, **kwargs):
        if self.fail_next_accept:
            self.fail_next_accept = False
            raise RuntimeError("접수 상태 DB 저장 실패")
        return await super().mark_accepted(*args, **kwargs)


class _FailingRejectRepository(_FakeRepository):
    async def mark_rejected(self, *args, **kwargs):
        raise RuntimeError("거절 상태 DB 저장 실패")


def _request() -> LiveOrderRequest:
    return LiveOrderRequest(
        source_type="ai",
        source_ref="analysis:1",
        market="krw-btc",
        side="bid",
        ord_type="price",
        price=Decimal("10000.00"),
        ai_analysis_log_id=1,
    )


def _order_payload(*, market: str = "KRW-BTC", state: str = "wait") -> dict:
    return {
        "uuid": "exchange-order-1",
        "market": market,
        "side": "bid",
        "ord_type": "price",
        "price": "10000",
        "volume": None,
        "state": state,
        "executed_volume": "0",
        "remaining_volume": "0",
        "paid_fee": "0",
        "trades": [],
    }


def _control_record(
    *,
    mode: str = LIVE_ORDER_MODE_ARMED,
    generation: int = 1,
    active_liquidation_operation_id: int | None = None,
) -> LiveOrderControlRecord:
    now = datetime.now(UTC)
    return LiveOrderControlRecord(
        id=1,
        broker="UPBIT",
        account_scope="primary",
        mode=mode,
        active_liquidation_operation_id=active_liquidation_operation_id,
        generation=generation,
        version=1,
        reason_code="TEST_CONTROL",
        reason_text="테스트 실주문 제어",
        changed_source="SYSTEM",
        changed_actor_ref="pytest",
        armed_at=now if mode == LIVE_ORDER_MODE_ARMED else None,
        blocked_at=None,
        created_at=now,
        updated_at=now,
    )


def _emergency_gate(*, volume: str = "0.1") -> LiveOrderSubmissionGateSnapshot:
    control = _control_record(
        mode=LIVE_ORDER_MODE_EXIT_ONLY,
        generation=2,
        active_liquidation_operation_id=31,
    )
    authorization = EmergencyLiquidationAuthorizationRecord(
        operation_id=31,
        operation_idempotency_key="11111111-1111-4111-8111-111111111111",
        operation_status="IN_PROGRESS",
        authorization_status=EMERGENCY_AUTHORIZATION_ACTIVE,
        control_generation=control.generation,
        control_event_id=7,
        authorized_source="REST",
        event_control_id=control.id,
        event_generation=control.generation,
        event_request_id="11111111-1111-4111-8111-111111111111",
        event_request_fingerprint="f" * 64,
        event_action="LIQUIDATION_AUTHORIZED",
        event_to_mode=LIVE_ORDER_MODE_EXIT_ONLY,
        event_source="REST",
        event_liquidation_operation_id=31,
        target_snapshot=(("KRW-BTC", volume),),
    )
    return LiveOrderSubmissionGateSnapshot(
        rollout_enabled=True,
        bot_active=False,
        control=control,
        emergency_authorization=authorization,
        trading_mode="live",
        trading_mode_state_available=True,
    )


def _service(
    broker: _FakeBroker,
    repository: _FakeRepository,
    *,
    barrier=None,
    control_repository=None,
) -> LiveOrderExecutionService:
    service = LiveOrderExecutionService(
        _FakeSessionFactory(),
        broker,
        barrier or _FakeBarrier(),
    )
    service._repository = repository
    service._control_repository = control_repository or _FakeControlRepository(repository)
    service._control_service = _FakeControlService(repository)

    async def no_sleep(_seconds: float) -> None:
        return None

    service._sleep = no_sleep
    return service


def test_hashes_are_canonical_and_separate_business_identity_from_payload() -> None:
    first = _request()
    same = replace(first, price=Decimal("10000"))
    changed = replace(first, price=Decimal("11000"))

    assert build_intent_key(first) == build_intent_key(changed)
    assert build_request_fingerprint(first) == build_request_fingerprint(same)
    assert build_request_fingerprint(first) != build_request_fingerprint(changed)


def test_emergency_source_ref_must_be_derived_from_operation_and_market() -> None:
    with pytest.raises(ValueError, match="source_ref"):
        LiveOrderRequest(
            source_type="EMERGENCY_LIQUIDATION",
            source_ref="caller-controlled-reference",
            market="KRW-BTC",
            side="ask",
            ord_type="market",
            volume=Decimal("0.1"),
            liquidation_operation_id=31,
            execution_policy="EMERGENCY_EXIT",
        )


def test_reconciliation_backoff_uses_required_schedule_and_cap() -> None:
    assert [reconciliation_backoff(count).total_seconds() for count in range(1, 8)] == [
        15,
        30,
        60,
        120,
        300,
        600,
        900,
    ]
    assert reconciliation_backoff(99).total_seconds() == 900


def test_feature_flag_off_does_not_create_intent_or_post() -> None:
    broker = _FakeBroker(_order_payload(), _order_payload())
    repository = _FakeRepository(enabled=False)

    result = asyncio.run(_service(broker, repository).execute(_request()))

    assert result.intent_id is None
    assert result.submission_status == "REJECTED"
    assert result.error_code == "LIVE_ORDER_V2_DISABLED"
    assert repository.current is None
    assert broker.create_count == 0


@pytest.mark.parametrize(
    ("mode", "state_available", "expected_error"),
    [
        ("paper", True, "TRADING_MODE_LIVE_REQUIRED"),
        ("paper", False, "TRADING_MODE_STATE_UNAVAILABLE"),
    ],
)
def test_trading_mode_blocks_intent_preparation_and_post(
    mode: str,
    state_available: bool,
    expected_error: str,
) -> None:
    broker = _FakeBroker(_order_payload(), _order_payload())
    repository = _FakeRepository()
    control_repository = _FakeControlRepository(
        repository,
        LiveOrderSubmissionGateSnapshot(
            rollout_enabled=True,
            bot_active=True,
            control=_control_record(),
            general_authorization_event_id=1,
            trading_mode=mode,
            trading_mode_state_available=state_available,
        ),
    )

    result = asyncio.run(
        _service(
            broker,
            repository,
            control_repository=control_repository,
        ).execute(_request())
    )

    assert result.error_code == expected_error
    assert repository.current is None
    assert broker.create_count == 0


def test_mode_change_between_prepare_and_claim_abandons_without_post() -> None:
    broker = _FakeBroker(_order_payload(), _order_payload())
    repository = _FakeRepository()
    control = _control_record()
    live_snapshot = LiveOrderSubmissionGateSnapshot(
        rollout_enabled=True,
        bot_active=True,
        control=control,
        general_authorization_event_id=1,
        trading_mode="live",
        trading_mode_state_available=True,
    )
    paper_snapshot = replace(
        live_snapshot,
        trading_mode="paper",
    )

    result = asyncio.run(
        _service(
            broker,
            repository,
            control_repository=_SequenceControlRepository(
                repository,
                [live_snapshot, paper_snapshot],
            ),
        ).execute(_request())
    )

    assert result.submission_status == "ABANDONED"
    assert result.error_code == "TRADING_MODE_LIVE_REQUIRED"
    assert broker.create_count == 0


def test_inactive_bot_does_not_create_general_intent_or_post() -> None:
    broker = _FakeBroker(_order_payload(), _order_payload())
    repository = _FakeRepository()
    control_repository = _FakeControlRepository(
        repository,
        LiveOrderSubmissionGateSnapshot(
            rollout_enabled=True,
            bot_active=False,
            control=_control_record(),
            general_authorization_event_id=1,
            trading_mode="live",
            trading_mode_state_available=True,
        ),
    )

    result = asyncio.run(
        _service(
            broker,
            repository,
            control_repository=control_repository,
        ).execute(_request())
    )

    assert result.error_code == "BOT_INACTIVE"
    assert repository.current is None
    assert broker.create_count == 0


def test_stale_prepared_generation_is_abandoned_without_post() -> None:
    request = _request()
    broker = _FakeBroker(_order_payload(), _order_payload())
    repository = _FakeRepository()
    repository.current = _record(
        intent_key=build_intent_key(request),
        request_fingerprint=build_request_fingerprint(request),
        prepared_control_generation=99,
    )

    result = asyncio.run(_service(broker, repository).execute(request))

    assert result.submission_status == "ABANDONED"
    assert result.projection_status == "SKIPPED"
    assert result.error_code == "ORDER_GATE_GENERATION_CONFLICT"
    assert repository.current.post_attempt_count == 0
    assert broker.create_count == 0


def test_barrier_acquisition_failure_leaves_prepared_without_post() -> None:
    broker = _FakeBroker(_order_payload(), _order_payload())
    repository = _FakeRepository()

    result = asyncio.run(
        _service(
            broker,
            repository,
            barrier=_AcquireFailBarrier(),
        ).execute(_request())
    )

    assert result.submission_status == "PREPARED"
    assert result.error_code == "ORDER_GATE_STATE_UNAVAILABLE"
    assert repository.current.post_attempt_count == 0
    assert broker.create_count == 0


def test_barrier_release_failure_preserves_post_result_without_repost() -> None:
    broker = _FakeBroker(_order_payload(), _order_payload())
    repository = _FakeRepository()

    result = asyncio.run(
        _service(
            broker,
            repository,
            barrier=_ReleaseFailBarrier(),
        ).execute(_request())
    )

    assert result.submission_status == "ACCEPTED"
    assert broker.create_count == 1
    assert broker.lookup_count == 1


def test_emergency_exit_requires_exact_immutable_target_snapshot() -> None:
    request = LiveOrderRequest(
        source_type="EMERGENCY_LIQUIDATION",
        source_ref="liquidation:31:KRW-BTC",
        market="KRW-BTC",
        side="ask",
        ord_type="market",
        volume=Decimal("0.2"),
        liquidation_operation_id=31,
        execution_policy="EMERGENCY_EXIT",
    )
    broker = _FakeBroker({}, {})
    repository = _FakeRepository()

    result = asyncio.run(
        _service(
            broker,
            repository,
            control_repository=_FakeControlRepository(
                repository,
                _emergency_gate(volume="0.1"),
            ),
        ).execute(request)
    )

    assert result.error_code == "EMERGENCY_AUTH_REQUIRED"
    assert repository.current is None
    assert broker.create_count == 0


def test_authorized_emergency_exit_posts_once_with_bound_control_audit() -> None:
    request = LiveOrderRequest(
        source_type="EMERGENCY_LIQUIDATION",
        source_ref="liquidation:31:KRW-BTC",
        market="KRW-BTC",
        side="ask",
        ord_type="market",
        volume=Decimal("0.1"),
        liquidation_operation_id=31,
        execution_policy="EMERGENCY_EXIT",
    )
    payload = {
        "uuid": "emergency-order-1",
        "market": "KRW-BTC",
        "side": "ask",
        "ord_type": "market",
        "price": None,
        "volume": "0.1",
        "state": "wait",
        "executed_volume": "0",
        "remaining_volume": "0.1",
        "paid_fee": "0",
        "trades": [],
    }
    broker = _FakeBroker(payload, payload)
    repository = _FakeRepository()

    result = asyncio.run(
        _service(
            broker,
            repository,
            control_repository=_FakeControlRepository(repository, _emergency_gate()),
        ).execute(request)
    )

    assert result.submission_status == "ACCEPTED"
    assert repository.current.control_generation == 2
    assert repository.current.control_mode == LIVE_ORDER_MODE_EXIT_ONLY
    assert repository.current.control_event_id == 7
    assert broker.create_count == 1


def test_timeout_is_reconciled_as_accepted_without_second_post() -> None:
    broker = _FakeBroker(httpx.ReadTimeout("응답 시간 초과"), _order_payload())
    repository = _FakeRepository()

    result = asyncio.run(_service(broker, repository).execute(_request()))

    assert result.submission_status == "ACCEPTED"
    assert result.exchange_uuid == "exchange-order-1"
    assert result.replayed is False
    assert broker.create_count == 1
    assert broker.lookup_count == 1


def test_preparation_and_final_post_each_hold_shared_barrier() -> None:
    broker = _FakeBroker(_order_payload(), _order_payload())
    repository = _FakeRepository()
    barrier = _FakeBarrier()

    result = asyncio.run(
        _service(broker, repository, barrier=barrier).execute(_request())
    )

    assert result.submission_status == "ACCEPTED"
    assert barrier.shared_count == 2
    assert broker.create_count == 1


@pytest.mark.parametrize(
    "create_error",
    [
        UpbitAPIError(500, {"error": {"name": "internal_error"}}),
        ValueError("주문 생성 응답 JSON 파싱 실패"),
    ],
)
def test_uncertain_create_failures_reconcile_without_second_post(create_error) -> None:
    broker = _FakeBroker(create_error, _order_payload())
    repository = _FakeRepository()

    result = asyncio.run(_service(broker, repository).execute(_request()))

    assert result.submission_status == "ACCEPTED"
    assert broker.create_count == 1
    assert broker.lookup_count == 1


def test_lookup_delay_recovers_on_third_identifier_query() -> None:
    not_found = UpbitAPIError(404, {"error": {"name": "order_not_found"}})
    broker = _SequenceLookupBroker(
        httpx.ReadTimeout("응답 시간 초과"),
        [not_found, not_found, _order_payload()],
    )
    repository = _FakeRepository()

    result = asyncio.run(_service(broker, repository).execute(_request()))

    assert result.submission_status == "ACCEPTED"
    assert broker.create_count == 1
    assert broker.lookup_count == 3


def test_restart_from_submitting_reconciles_without_post() -> None:
    request = _request()
    payload = {**_order_payload(), "identifier": "b" * 32}
    broker = _FakeBroker({}, payload)
    repository = _FakeRepository()
    repository.current = _record(
        intent_key=build_intent_key(request),
        request_fingerprint=build_request_fingerprint(request),
        submission_status="SUBMITTING",
        post_attempt_count=1,
        version=1,
    )

    result = asyncio.run(_service(broker, repository).execute(request))

    assert result.submission_status == "ACCEPTED"
    assert broker.create_count == 0
    assert broker.lookup_count == 1


def test_success_response_db_failure_recovers_by_lookup_without_repost() -> None:
    broker = _FakeBroker(_order_payload(), _order_payload())
    repository = _FailingAcceptRepository()
    service = _service(broker, repository)

    with pytest.raises(RuntimeError, match="DB 저장 실패"):
        asyncio.run(service.execute(_request()))

    recovered = asyncio.run(service.reconcile_intent(repository.current.id))

    assert recovered.submission_status == "ACCEPTED"
    assert broker.create_count == 1
    assert broker.lookup_count == 1


def test_successful_create_immediately_refreshes_order_by_identifier() -> None:
    terminal = {
        **_order_payload(state="done"),
        "executed_volume": "0.1",
        "executed_funds": "10000",
        "trades": [{"volume": "0.1", "funds": "10000", "price": "100000"}],
    }
    broker = _FakeBroker(_order_payload(), terminal)
    repository = _FakeRepository()

    result = asyncio.run(_service(broker, repository).execute(_request()))

    assert result.submission_status == "ACCEPTED"
    assert result.exchange_state == "done"
    assert result.projection_status == "APPLIED"
    assert result.order_history_id == 7
    assert broker.create_count == 1
    assert broker.lookup_count == 1


def test_successful_create_keeps_accepted_when_follow_up_lookup_fails() -> None:
    broker = _FakeBroker(_order_payload(), httpx.ReadTimeout("조회 응답 시간 초과"))
    repository = _FakeRepository()

    result = asyncio.run(_service(broker, repository).execute(_request()))

    assert result.submission_status == "ACCEPTED"
    assert result.exchange_uuid == "exchange-order-1"
    assert result.error_code == "READTIMEOUT"
    assert broker.create_count == 1
    assert broker.lookup_count == 1


def test_auth_rejection_disables_live_order_gate() -> None:
    unauthorized = UpbitAPIError(
        401,
        {"error": {"name": "jwt_verification"}},
        error_name="jwt_verification",
    )
    broker = _FakeBroker(unauthorized, _order_payload())
    repository = _FakeRepository()
    service = _service(broker, repository)

    result = asyncio.run(service.execute(_request()))

    assert result.submission_status == "REJECTED"
    assert result.error_code == "JWT_VERIFICATION"
    assert repository.disabled is True
    assert service._control_service.commands[0].completed_post_intent_id == result.intent_id
    assert broker.create_count == 1
    assert broker.lookup_count == 0


def test_named_authorization_rejection_disables_gate_even_with_http_400() -> None:
    unauthorized = UpbitAPIError(
        400,
        {"error": {"name": "no_authorization_token"}},
        error_name="no_authorization_token",
    )
    broker = _FakeBroker(unauthorized, _order_payload())
    repository = _FakeRepository()

    result = asyncio.run(_service(broker, repository).execute(_request()))

    assert result.submission_status == "REJECTED"
    assert repository.disabled is True
    assert broker.create_count == 1


def test_auth_failure_trips_gate_even_when_rejection_persistence_fails() -> None:
    unauthorized = UpbitAPIError(
        401,
        {"error": {"name": "jwt_verification"}},
        error_name="jwt_verification",
    )
    broker = _FakeBroker(unauthorized, _order_payload())
    repository = _FailingRejectRepository()
    service = _service(broker, repository)

    with pytest.raises(RuntimeError, match="DB 저장 실패"):
        asyncio.run(service.execute(_request()))

    assert repository.disabled is True
    assert service._control_service.trip_count == 1
    assert broker.create_count == 1


def test_repeated_auth_failure_for_same_control_generation_reuses_event_request_id() -> None:
    broker = _FakeBroker({}, {})
    repository = _FakeRepository()
    service = _service(broker, repository)
    record = _record(
        submission_status="UNKNOWN",
        control_generation=1,
        control_mode=LIVE_ORDER_MODE_ARMED,
    )

    async def trip_twice() -> None:
        await service._disable_submission_gate(record)
        await service._disable_submission_gate(record)

    asyncio.run(trip_twice())

    commands = service._control_service.commands
    assert len(commands) == 2
    assert commands[0].request_id == commands[1].request_id


def test_authorization_error_during_reconciliation_disables_gate() -> None:
    unauthorized = UpbitAPIError(
        401,
        {"error": {"name": "jwt_verification"}},
        error_name="jwt_verification",
    )
    broker = _FakeBroker(httpx.ReadTimeout("응답 시간 초과"), unauthorized)
    repository = _FakeRepository()

    result = asyncio.run(_service(broker, repository).execute(_request()))

    assert result.submission_status == "UNKNOWN"
    assert repository.disabled is True
    assert broker.create_count == 1
    assert broker.lookup_count == 1


def test_existing_intent_is_marked_replayed_without_second_post() -> None:
    broker = _FakeBroker(httpx.ReadTimeout("응답 시간 초과"), _order_payload())
    repository = _FakeRepository()
    service = _service(broker, repository)

    first = asyncio.run(service.execute(_request()))
    second = asyncio.run(service.execute(_request()))

    assert first.replayed is False
    assert second.replayed is True
    assert second.submission_status == "ACCEPTED"
    assert broker.create_count == 1


def test_timeout_stays_unknown_after_three_not_found_queries() -> None:
    not_found = UpbitAPIError(404, {"error": {"name": "order_not_found"}})
    broker = _FakeBroker(httpx.ReadTimeout("응답 시간 초과"), not_found)
    repository = _FakeRepository()

    result = asyncio.run(_service(broker, repository).execute(_request()))

    assert result.submission_status == "UNKNOWN"
    assert result.error_code == "ORDER_NOT_FOUND"
    assert broker.create_count == 1
    assert broker.lookup_count == 3
    assert repository.current.not_found_count == 3


def test_duplicate_identifier_is_resolved_by_lookup_without_repost() -> None:
    duplicated = UpbitAPIError(
        400,
        {"error": {"name": "duplicated_identifier"}},
        error_name="duplicated_identifier",
    )
    broker = _FakeBroker(duplicated, _order_payload())
    repository = _FakeRepository()

    result = asyncio.run(_service(broker, repository).execute(_request()))

    assert result.submission_status == "ACCEPTED"
    assert broker.create_count == 1
    assert broker.lookup_count == 1


def test_lookup_payload_mismatch_is_unknown_and_blocks_projection() -> None:
    wrong_payload = _order_payload(market="KRW-ETH")
    broker = _FakeBroker(httpx.ReadTimeout("응답 시간 초과"), wrong_payload)
    repository = _FakeRepository()

    result = asyncio.run(_service(broker, repository).execute(_request()))

    assert result.submission_status == "UNKNOWN"
    assert result.error_code == "RECONCILIATION_CONFLICT"
    assert broker.create_count == 1
    assert broker.lookup_count == 1


def test_terminal_projection_error_is_retried_through_reconciliation() -> None:
    terminal = {
        **_order_payload(state="done"),
        "executed_volume": "0.1",
        "executed_funds": "10000",
        "trades": [{"volume": "0.1", "funds": "10000", "price": "100000"}],
    }
    broker = _FakeBroker(terminal, terminal)
    repository = _FakeRepository()
    repository.projection_failures = 1
    service = _service(broker, repository)

    first = asyncio.run(service.execute(_request()))
    recovered = asyncio.run(service.reconcile_intent(first.intent_id))

    assert first.submission_status == "ACCEPTED"
    assert first.projection_status == "ERROR"
    assert recovered.projection_status == "APPLIED"
    assert recovered.order_history_id == 7
    assert broker.create_count == 1
    assert broker.lookup_count == 1


def test_terminal_partial_fill_uses_trade_vwap_without_request_fallback() -> None:
    request = LiveOrderRequest(
        source_type="AI",
        source_ref="analysis:2:KRW-BTC:ask",
        market="KRW-BTC",
        side="ask",
        ord_type="market",
        volume=Decimal("0.1"),
        ai_analysis_log_id=2,
    )
    terminal = {
        "uuid": "partial-order",
        "market": "KRW-BTC",
        "side": "ask",
        "ord_type": "market",
        "price": None,
        "volume": "0.1",
        "state": "cancel",
        "executed_volume": "0.04",
        "remaining_volume": "0.06",
        "paid_fee": "20",
        "trades": [
            {"volume": "0.01", "price": "100000", "funds": "1000"},
            {"volume": "0.03", "price": "110000", "funds": "3300"},
        ],
    }
    broker = _FakeBroker(terminal, terminal)
    repository = _FakeRepository()

    result = asyncio.run(_service(broker, repository).execute(request))

    assert result.exchange_state == "cancel"
    assert result.projection_status == "APPLIED"
    assert repository.current.executed_volume == Decimal("0.04")
    assert repository.current.average_fill_price == Decimal("107500")
    assert broker.create_count == 1
