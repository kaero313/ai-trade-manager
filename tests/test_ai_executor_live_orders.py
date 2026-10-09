import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.schemas.portfolio import AssetItem, PortfolioSummary
from app.services.trading import ai_executor
from app.services.trading.live_order_execution import LiveOrderRequest, LiveOrderResult


class FakeLiveOrderService:
    def __init__(self, result: LiveOrderResult) -> None:
        self.result = result
        self.requests: list[LiveOrderRequest] = []

    async def execute(self, request: LiveOrderRequest) -> LiveOrderResult:
        self.requests.append(request)
        return self.result


class _TransactionTrackingDb:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


def _live_result(
    submission_status: str,
    *,
    error_code: str | None = None,
    replayed: bool = False,
) -> LiveOrderResult:
    return LiveOrderResult(
        intent_id=17,
        identifier="a" * 32,
        submission_status=submission_status,
        exchange_uuid="upbit-order-17" if submission_status == "ACCEPTED" else None,
        exchange_state="wait" if submission_status == "ACCEPTED" else None,
        projection_status="PENDING",
        order_history_id=None,
        error_code=error_code,
        error_message="test error" if error_code else None,
        replayed=replayed,
    )


def _asset(
    currency: str,
    *,
    balance: float,
    current_price: float,
    total_value: float,
    pnl_percentage: float = 0,
) -> AssetItem:
    return AssetItem(
        broker="UPBIT",
        currency=currency,
        balance=balance,
        locked=0,
        avg_buy_price=current_price,
        current_price=current_price,
        total_value=total_value,
        pnl_percentage=pnl_percentage,
    )


def _portfolio(*items: AssetItem, total_net_worth: float = 100_000) -> PortfolioSummary:
    return PortfolioSummary(
        total_net_worth=total_net_worth,
        total_pnl=0,
        items=list(items),
    )


@pytest.mark.parametrize(("replayed", "notification_count"), [(False, 1), (True, 0)])
def test_live_buy_uses_central_service_and_decimal_quote_amount(
    monkeypatch,
    replayed: bool,
    notification_count: int,
) -> None:
    result = _live_result("ACCEPTED", replayed=replayed)
    service = FakeLiveOrderService(result)
    notifications: list[LiveOrderResult] = []

    async def load_max_allocation(_db) -> float:
        return 30.0

    async def load_max_buy_weight(_db) -> float:
        return 30.0

    async def capture_notification(**kwargs) -> None:
        notifications.append(kwargs["result"])

    async def fail_history_recording(**_kwargs) -> bool:
        raise AssertionError("live 주문에서 즉시 체결 이력을 기록하면 안 됩니다")

    monkeypatch.setattr(ai_executor, "_load_max_allocation_pct", load_max_allocation)
    monkeypatch.setattr(ai_executor, "_load_ai_max_buy_weight_pct", load_max_buy_weight)
    monkeypatch.setattr(ai_executor, "_build_live_order_execution_service", lambda: service)
    monkeypatch.setattr(ai_executor, "_send_live_order_accepted_notification", capture_notification)
    monkeypatch.setattr(ai_executor, "_record_paper_order_history", fail_history_recording)

    analysis = SimpleNamespace(id=7, confidence=90, recommended_weight=10)
    db = _TransactionTrackingDb()
    portfolio = _portfolio(
        _asset("KRW", balance=100_000, current_price=1, total_value=100_000),
        _asset("BTC", balance=0, current_price=100_000_000, total_value=0),
    )

    actual = asyncio.run(
        ai_executor._execute_buy_trade(
            db=db,
            symbol="KRW-BTC",
            analysis=analysis,
            primary_recommended_weight=10,
            portfolio=portfolio,
            trading_mode="live",
        )
    )

    assert actual is result
    assert db.commit_count == 1
    assert notifications == [result] * notification_count
    assert len(service.requests) == 1
    request = service.requests[0]
    assert request.source_type == "AI_ANALYSIS"
    assert request.source_ref == "analysis:7:KRW-BTC:bid"
    assert request.market == "KRW-BTC"
    assert request.side == "bid"
    assert request.ord_type == "price"
    assert request.price == Decimal("9950")
    assert request.volume is None
    assert request.ai_analysis_log_id == 7
    assert request.execution_policy == "GENERAL"


def test_live_sell_unknown_returns_result_without_success_notification(monkeypatch) -> None:
    result = _live_result("UNKNOWN", error_code="ORDER_CONFIRMATION_PENDING")
    service = FakeLiveOrderService(result)

    async def fail_notification(**_kwargs) -> None:
        raise AssertionError("미확정 주문을 성공 알림으로 전송하면 안 됩니다")

    async def fail_history_recording(**_kwargs) -> bool:
        raise AssertionError("미확정 주문에서 체결 이력을 기록하면 안 됩니다")

    monkeypatch.setattr(ai_executor, "_build_live_order_execution_service", lambda: service)
    monkeypatch.setattr(ai_executor, "_send_live_order_accepted_notification", fail_notification)
    monkeypatch.setattr(ai_executor, "_record_paper_order_history", fail_history_recording)

    analysis = SimpleNamespace(id=8, confidence=88, recommended_weight=50)
    db = _TransactionTrackingDb()
    portfolio = _portfolio(
        _asset("BTC", balance=1, current_price=10_000, total_value=10_000),
        total_net_worth=10_000,
    )

    actual = asyncio.run(
        ai_executor._execute_sell_trade(
            db=db,
            symbol="KRW-BTC",
            analysis=analysis,
            portfolio=portfolio,
            trading_mode="live",
        )
    )

    assert actual is result
    assert db.commit_count == 1
    assert len(service.requests) == 1
    request = service.requests[0]
    assert request.source_type == "AI_ANALYSIS"
    assert request.source_ref == "analysis:8:KRW-BTC:ask"
    assert request.side == "ask"
    assert request.ord_type == "market"
    assert request.price is None
    assert request.volume == Decimal("0.5")
    assert request.ai_analysis_log_id == 8


@pytest.mark.parametrize(
    ("submission_status", "error_code", "expected_blocked"),
    [
        ("ACCEPTED", None, True),
        ("SUBMITTING", None, True),
        ("UNKNOWN", "ORDER_CONFIRMATION_PENDING", True),
        ("ACCEPTED", "BLOCKING_INTENT", True),
        ("REJECTED", "under_min_total_ask", False),
    ],
)
def test_hard_risk_exit_excludes_only_blocking_live_intents(
    monkeypatch,
    submission_status: str,
    error_code: str | None,
    expected_blocked: bool,
) -> None:
    result = _live_result(submission_status, error_code=error_code)
    service = FakeLiveOrderService(result)
    db = _TransactionTrackingDb()
    portfolio = _portfolio(
        _asset(
            "BTC",
            balance=1,
            current_price=10_000,
            total_value=10_000,
            pnl_percentage=20,
        ),
        total_net_worth=10_000,
    )

    async def load_thresholds(_db) -> tuple[float, float]:
        return 10.0, -10.0

    async def get_mode(_db) -> str:
        return "live"

    async def get_portfolio() -> PortfolioSummary:
        return portfolio

    monkeypatch.setattr(ai_executor, "_load_hard_tp_sl_thresholds", load_thresholds)
    monkeypatch.setattr(ai_executor, "get_trading_mode", get_mode)
    monkeypatch.setattr(
        ai_executor,
        "PortfolioService",
        lambda _db: SimpleNamespace(get_aggregated_portfolio=get_portfolio),
    )
    monkeypatch.setattr(ai_executor, "_build_live_order_execution_service", lambda: service)

    risk_result = asyncio.run(ai_executor.execute_hard_tp_sl_check(db))

    assert risk_result.status is ai_executor.RiskCheckStatus.UNHEALTHY
    assert risk_result.affected_symbols == {"KRW-BTC"}
    assert risk_result.liquidated_symbols == (
        {"KRW-BTC"} if expected_blocked else set()
    )
    assert db.commit_count == 1
    assert len(service.requests) == 1
    request = service.requests[0]
    assert request.source_type == "HARD_RISK_EXIT"
    assert request.source_ref.startswith("risk_exit:")
    assert len(request.source_ref.removeprefix("risk_exit:")) == 32
    int(request.source_ref.removeprefix("risk_exit:"), 16)
    assert request.market == "KRW-BTC"
    assert request.side == "ask"
    assert request.ord_type == "market"
    assert request.price is None
    assert request.volume == Decimal("1")
    assert request.reason == ai_executor.ORDER_REASON_TP_SELL
    assert request.execution_policy == "GENERAL"


def test_execute_ai_trade_returns_live_order_result_to_caller(monkeypatch) -> None:
    result = _live_result("UNKNOWN", error_code="ORDER_CONFIRMATION_PENDING")
    analysis = SimpleNamespace(
        id=9,
        symbol="KRW-BTC",
        decision="SELL",
        confidence=90,
        recommended_weight=50,
        created_at=datetime.now(UTC),
    )
    portfolio = _portfolio(
        _asset("BTC", balance=1, current_price=10_000, total_value=10_000),
        total_net_worth=10_000,
    )

    async def get_status(_db):
        return SimpleNamespace(running=True)

    async def load_thresholds(_db) -> tuple[int, int]:
        return 75, 90

    async def load_analysis(_db, analysis_id: int):
        assert analysis_id == analysis.id
        return analysis

    async def get_portfolio() -> PortfolioSummary:
        return portfolio

    async def get_mode(_db) -> str:
        return "live"

    async def execute_sell(**_kwargs) -> LiveOrderResult:
        return result

    monkeypatch.setattr(ai_executor, "get_bot_status", get_status)
    monkeypatch.setattr(ai_executor, "_load_executor_thresholds", load_thresholds)
    monkeypatch.setattr(ai_executor, "_load_analysis_by_id", load_analysis)
    monkeypatch.setattr(
        ai_executor,
        "PortfolioService",
        lambda _db: SimpleNamespace(get_aggregated_portfolio=get_portfolio),
    )
    monkeypatch.setattr(ai_executor, "get_trading_mode", get_mode)
    monkeypatch.setattr(ai_executor, "_execute_sell_trade", execute_sell)

    actual = asyncio.run(
        ai_executor.execute_ai_trade(
            object(),
            "krw-btc",
            analysis_id=analysis.id,
        )
    )

    assert actual is result
