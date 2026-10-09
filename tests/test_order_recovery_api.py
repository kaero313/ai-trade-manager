import asyncio
import importlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from app.api.routes import orders as orders_route
from app.api.routes import status as status_route
from app.models.schemas import (
    LiquidateAllRequest,
    LiquidationOperationResponse,
    ResolveNoOrderRequest,
)
from app.services.brokers.upbit import UpbitAPIError
from app.services.trading.liquidation import _build_target_snapshot
from app.services.trading.account_balances import AccountBalanceValidationError
from app.services.trading.liquidation import _classify_operation_status
from app.services.trading.live_order_execution import LiveOrderResult


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _FakeOrderIntentDb:
    def __init__(self, *results):
        self._results = list(results)
        self.rollback_called = False
        self.flush_called = False

    async def execute(self, _statement):
        return _ScalarResult(self._results.pop(0))

    async def rollback(self):
        self.rollback_called = True

    def begin(self):
        return _Transaction()

    async def flush(self):
        self.flush_called = True

    def expire_all(self):
        return None


def _intent(now: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=17,
        intent_key="i" * 64,
        identifier="a" * 32,
        source_type="TEST",
        source_ref="test:17",
        market="KRW-BTC",
        side="ask",
        ord_type="market",
        requested_price=None,
        requested_volume="0.01",
        submission_status="UNKNOWN",
        exchange_uuid=None,
        exchange_state=None,
        projection_status="PENDING",
        executed_volume=None,
        average_fill_price=None,
        last_error_code="ORDER_NOT_FOUND",
        last_error_message=None,
        reconcile_attempt_count=5,
        not_found_count=5,
        first_not_found_at=now - timedelta(minutes=12),
        last_not_found_at=now - timedelta(minutes=1),
        unknown_at=now - timedelta(minutes=16),
        created_at=now - timedelta(minutes=20),
        updated_at=now - timedelta(minutes=1),
        submitted_at=now - timedelta(minutes=20),
        last_checked_at=now - timedelta(minutes=1),
        next_reconcile_at=now,
        reconcile_lease_until=None,
        resolved_at=None,
        resolved_by=None,
        resolution_note=None,
        version=5,
    )


def test_liquidation_target_snapshot_is_stable_and_sorted() -> None:
    targets = _build_target_snapshot(
        [
            {"currency": "ETH", "balance": "2.5", "locked": "0.5"},
            {"currency": "KRW", "balance": "10000", "locked": "0"},
            {"currency": "BTC", "balance": "1", "locked": "0.25"},
        ]
    )

    assert targets == [
        {"market": "KRW-BTC", "volume": "1"},
        {"market": "KRW-ETH", "volume": "2.5"},
    ]


def test_liquidation_target_snapshot_rejects_invalid_balance() -> None:
    with pytest.raises(AccountBalanceValidationError):
        _build_target_snapshot(
            [{"currency": "XRP", "balance": "10", "locked": "invalid"}]
        )


def test_liquidation_blocking_intent_is_counted_as_failure() -> None:
    status_value = _classify_operation_status(
        [
            {
                "market": "KRW-BTC",
                "intent_id": 1,
                "submission_status": "ACCEPTED",
                "exchange_state": "done",
                "projection_status": "APPLIED",
                "executed_volume": "0.01",
                "remaining_volume": "0",
            },
            {
                "market": "KRW-ETH",
                "intent_id": 2,
                "submission_status": "UNKNOWN",
                "projection_status": "PENDING",
                "error_code": "BLOCKING_INTENT",
            },
        ]
    )

    assert status_value == "PARTIAL"


def test_liquidation_cancelled_without_fill_is_failed() -> None:
    status_value = _classify_operation_status(
        [
            {
                "market": "KRW-BTC",
                "intent_id": 1,
                "submission_status": "ACCEPTED",
                "exchange_state": "cancel",
                "projection_status": "SKIPPED",
                "executed_volume": "0",
                "remaining_volume": "0.01",
            }
        ]
    )

    assert status_value == "FAILED"


def test_liquidation_target_without_intent_stays_in_progress() -> None:
    status_value = _classify_operation_status(
        [
            {
                "market": "KRW-BTC",
                "intent_id": None,
                "submission_status": "PREPARING",
                "error_code": None,
            }
        ]
    )

    assert status_value == "IN_PROGRESS"


def test_liquidation_revoked_target_without_intent_is_failed() -> None:
    status_value = _classify_operation_status(
        [
            {
                "market": "KRW-BTC",
                "intent_id": None,
                "submission_status": "ABANDONED",
                "projection_status": "SKIPPED",
                "error_code": "EMERGENCY_AUTH_REVOKED",
            }
        ]
    )

    assert status_value == "FAILED"


def test_liquidate_endpoint_requires_uuid4() -> None:
    with pytest.raises(HTTPException) as exc_info:
        status_route._validate_idempotency_key("not-a-uuid")

    assert exc_info.value.status_code == 400


def test_no_order_resolution_reason_rejects_whitespace_only_value() -> None:
    with pytest.raises(ValueError):
        ResolveNoOrderRequest(
            exchange_ui_verified=True,
            resolution_note=" " * 10,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda intent, now: setattr(intent, "unknown_at", now - timedelta(minutes=14)),
        lambda intent, _now: setattr(intent, "not_found_count", 4),
        lambda intent, now: (
            setattr(intent, "first_not_found_at", now - timedelta(minutes=9)),
            setattr(intent, "last_not_found_at", now),
        ),
    ],
)
def test_no_order_resolution_requires_all_audit_conditions(mutation) -> None:
    now = datetime.now(UTC)
    intent = _intent(now)
    mutation(intent, now)

    with pytest.raises(HTTPException) as exc_info:
        orders_route._validate_no_order_resolution(intent, now)

    assert exc_info.value.status_code == 409


def test_liquidate_endpoint_returns_202_for_in_progress(monkeypatch) -> None:
    now = datetime.now(UTC)
    operation = LiquidationOperationResponse(
        id=3,
        idempotency_key=str(uuid4()),
        status="IN_PROGRESS",
        items=[],
        created_at=now,
        updated_at=now,
    )

    class _Coordinator:
        async def execute(self, idempotency_key: str, **_kwargs):
            assert idempotency_key == operation.idempotency_key
            return operation

    async def fake_stop_bot(_db):
        return None

    monkeypatch.setattr(status_route, "_liquidation_coordinator", lambda: _Coordinator())
    monkeypatch.setattr(status_route, "stop_bot", fake_stop_bot)
    response = Response()

    result = asyncio.run(
        status_route.liquidate_all_endpoint(
            payload=LiquidateAllRequest(
                scope="ACCOUNT_ALL",
                confirmation="CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL",
            ),
            response=response,
            idempotency_key=operation.idempotency_key,
            db=object(),
            _admin=None,
        )
    )

    assert result.id == 3
    assert response.status_code == 202


def test_manual_reconcile_returns_latest_intent(monkeypatch) -> None:
    now = datetime.now(UTC)
    intent = _intent(now)
    intent.submission_status = "ACCEPTED"
    intent.exchange_uuid = "exchange-uuid"
    intent.exchange_state = "wait"
    db = _FakeOrderIntentDb(intent)

    class _Service:
        async def reconcile_intent(self, intent_id: int):
            return LiveOrderResult(
                intent_id=intent_id,
                identifier=intent.identifier,
                submission_status="ACCEPTED",
                exchange_uuid=intent.exchange_uuid,
                exchange_state="wait",
                projection_status="PENDING",
                order_history_id=None,
                error_code=None,
                error_message=None,
            )

    monkeypatch.setattr(orders_route, "_live_order_service", lambda: _Service())

    response = asyncio.run(
        orders_route.reconcile_order_intent(17, db=db, _admin=None)
    )

    assert response.id == 17
    assert response.submission_status == "ACCEPTED"
    assert response.exchange_state == "wait"


def test_resolve_no_order_records_fresh_404(monkeypatch) -> None:
    now = datetime.now(UTC)
    intent = _intent(now)
    db = _FakeOrderIntentDb(intent, intent, intent)

    class _Broker:
        async def get_order(self, uuid_=None, identifier=None):
            assert uuid_ is None
            assert identifier == intent.identifier
            raise UpbitAPIError(404, {"error": "order_not_found"})

    monkeypatch.setattr(
        orders_route.BrokerFactory,
        "get_broker",
        classmethod(lambda cls, _broker_id: _Broker()),
    )

    response = asyncio.run(
        orders_route.resolve_order_intent_as_not_created(
            17,
            ResolveNoOrderRequest(
                exchange_ui_verified=True,
                resolution_note="Upbit 거래 화면에서 주문이 없음을 확인했습니다.",
            ),
            db=db,
            _admin=None,
        )
    )

    assert db.rollback_called is True
    assert db.flush_called is True
    assert response.submission_status == "NO_ORDER_CONFIRMED"
    assert response.projection_status == "SKIPPED"
    assert intent.not_found_count == 6
    assert intent.last_not_found_at >= now
    assert intent.last_checked_at >= now


def test_resolve_no_order_rejects_active_reconciliation_lease() -> None:
    now = datetime.now(UTC)
    intent = _intent(now)
    intent.reconcile_lease_until = now + timedelta(seconds=30)
    db = _FakeOrderIntentDb(intent, intent)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            orders_route.resolve_order_intent_as_not_created(
                17,
                ResolveNoOrderRequest(
                    exchange_ui_verified=True,
                    resolution_note="Upbit 거래 화면에서 주문 없음 확인",
                ),
                db=db,
                _admin=None,
            )
        )

    assert exc_info.value.status_code == 409


def test_scheduler_runs_order_and_liquidation_recovery(monkeypatch) -> None:
    scheduler_module = importlib.import_module("app.core.scheduler")
    events: list[str] = []
    broker = object()

    class _ReconciliationService:
        def __init__(self, session_factory, received_broker, submission_barrier):
            assert session_factory is scheduler_module.AsyncSessionLocal
            assert received_broker is broker
            assert submission_barrier is not None

        async def reconcile_due(self, limit: int = 20):
            events.append(f"reconcile:{limit}")
            return []

    class _LiquidationCoordinator:
        def __init__(self, session_factory, received_broker, submission_barrier):
            assert session_factory is scheduler_module.AsyncSessionLocal
            assert received_broker is broker
            assert submission_barrier is not None

        async def refresh_in_progress_operations(self):
            events.append("refresh-liquidations")
            return 0

    monkeypatch.setattr(
        scheduler_module.BrokerFactory,
        "get_broker",
        classmethod(lambda cls, _broker_id: broker),
    )
    monkeypatch.setattr(
        scheduler_module,
        "LiveOrderExecutionService",
        _ReconciliationService,
    )
    monkeypatch.setattr(
        scheduler_module,
        "LiquidationCoordinator",
        _LiquidationCoordinator,
    )

    asyncio.run(scheduler_module.live_order_reconciliation_job())

    assert events == ["reconcile:20", "refresh-liquidations"]
