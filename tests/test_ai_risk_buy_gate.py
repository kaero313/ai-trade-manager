from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.schemas.portfolio import AssetItem, PortfolioSummary
from app.services.trading import ai_executor


def _asset(
    currency: str,
    *,
    balance: float = 1.0,
    locked: float = 0.0,
    avg_buy_price: float = 10_000.0,
    current_price: float = 10_000.0,
    pnl_percentage: float = 0.0,
) -> AssetItem:
    return AssetItem(
        broker="UPBIT",
        currency=currency,
        balance=balance,
        locked=locked,
        avg_buy_price=avg_buy_price,
        current_price=current_price,
        total_value=(balance + locked) * current_price,
        pnl_percentage=pnl_percentage,
    )


def _portfolio(
    *items: AssetItem,
    error: str | None = None,
    is_stale: bool = False,
) -> PortfolioSummary:
    return PortfolioSummary(
        total_net_worth=sum(item.total_value for item in items),
        total_pnl=0.0,
        items=list(items),
        error=error,
        is_stale=is_stale,
    )


def _analysis(*, decision: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=901,
        symbol="KRW-BTC",
        decision=decision,
        confidence=90,
        recommended_weight=20,
        created_at=datetime.now(UTC),
    )


async def _running_status(_db: object) -> SimpleNamespace:
    return SimpleNamespace(running=True)


async def _executor_thresholds(_db: object) -> tuple[int, int]:
    return 75, 90


async def _paper_mode(_db: object) -> str:
    return "paper"


def _portfolio_service(portfolio: PortfolioSummary):
    async def get_aggregated_portfolio() -> PortfolioSummary:
        return portfolio

    return lambda _db: SimpleNamespace(
        get_aggregated_portfolio=get_aggregated_portfolio,
    )


@pytest.mark.asyncio
async def test_risk_check_result_is_immutable_and_allows_only_safe_statuses() -> None:
    healthy = ai_executor.RiskCheckResult(
        status=ai_executor.RiskCheckStatus.HEALTHY,
    )
    disabled = ai_executor.RiskCheckResult(
        status=ai_executor.RiskCheckStatus.DISABLED,
    )
    unhealthy = ai_executor.RiskCheckResult(
        status=ai_executor.RiskCheckStatus.UNHEALTHY,
    )
    unknown = ai_executor.RiskCheckResult(
        status=ai_executor.RiskCheckStatus.UNKNOWN,
    )

    assert healthy.allows_new_buy is True
    assert disabled.allows_new_buy is True
    assert unhealthy.allows_new_buy is False
    assert unknown.allows_new_buy is False
    with pytest.raises(FrozenInstanceError):
        healthy.status = ai_executor.RiskCheckStatus.UNKNOWN


@pytest.mark.asyncio
async def test_new_buy_risk_is_disabled_without_loading_portfolio(monkeypatch) -> None:
    async def load_thresholds(_db: object) -> tuple[float, float]:
        return 0.0, 0.0

    class UnexpectedPortfolioService:
        def __init__(self, _db: object) -> None:
            raise AssertionError("비활성 리스크 점검에서 포트폴리오를 조회하면 안 됩니다.")

    monkeypatch.setattr(ai_executor, "_load_hard_tp_sl_thresholds", load_thresholds)
    monkeypatch.setattr(ai_executor, "PortfolioService", UnexpectedPortfolioService)

    result = await ai_executor.evaluate_new_buy_risk_health(object())

    assert result.status is ai_executor.RiskCheckStatus.DISABLED
    assert result.allows_new_buy is True
    assert result.reasons == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("take_profit", "stop_loss"),
    [
        (float("nan"), 0.0),
        (0.0, float("nan")),
        (-1.0, 0.0),
        (0.0, 1.0),
        (1001.0, 0.0),
        (0.0, -1001.0),
    ],
)
async def test_invalid_risk_threshold_never_becomes_disabled(
    monkeypatch,
    take_profit: float,
    stop_loss: float,
) -> None:
    async def load_thresholds(_db: object) -> tuple[float, float]:
        return take_profit, stop_loss

    portfolio = _portfolio(_asset("BTC"))
    monkeypatch.setattr(ai_executor, "_load_hard_tp_sl_thresholds", load_thresholds)
    monkeypatch.setattr(ai_executor, "PortfolioService", _portfolio_service(portfolio))

    result = await ai_executor.evaluate_new_buy_risk_health(object())

    assert result.status is ai_executor.RiskCheckStatus.UNKNOWN
    assert result.allows_new_buy is False
    assert result.reasons == ("INVALID_RISK_THRESHOLD",)


@pytest.mark.asyncio
async def test_risk_threshold_load_failure_is_unknown(monkeypatch) -> None:
    async def load_thresholds(_db: object) -> tuple[float, float]:
        raise ValueError("invalid risk config")

    monkeypatch.setattr(ai_executor, "_load_hard_tp_sl_thresholds", load_thresholds)

    result = await ai_executor.evaluate_new_buy_risk_health(object())

    assert result.status is ai_executor.RiskCheckStatus.UNKNOWN
    assert result.reasons == ("RISK_THRESHOLD_LOAD_FAILED",)


@pytest.mark.asyncio
async def test_new_buy_risk_is_healthy_for_complete_portfolio_without_trigger(
    monkeypatch,
) -> None:
    async def load_thresholds(_db: object) -> tuple[float, float]:
        return 10.0, -10.0

    portfolio = _portfolio(
        _asset("KRW", balance=100_000.0, current_price=1.0),
        _asset("BTC", pnl_percentage=3.0),
    )
    monkeypatch.setattr(ai_executor, "_load_hard_tp_sl_thresholds", load_thresholds)
    monkeypatch.setattr(ai_executor, "PortfolioService", _portfolio_service(portfolio))

    result = await ai_executor.evaluate_new_buy_risk_health(object())

    assert result.status is ai_executor.RiskCheckStatus.HEALTHY
    assert result.allows_new_buy is True
    assert result.affected_symbols == frozenset()


@pytest.mark.asyncio
async def test_new_buy_risk_is_unhealthy_for_hard_threshold_trigger(monkeypatch) -> None:
    async def load_thresholds(_db: object) -> tuple[float, float]:
        return 10.0, -10.0

    portfolio = _portfolio(_asset("BTC", pnl_percentage=12.0))
    monkeypatch.setattr(ai_executor, "_load_hard_tp_sl_thresholds", load_thresholds)
    monkeypatch.setattr(ai_executor, "PortfolioService", _portfolio_service(portfolio))

    result = await ai_executor.evaluate_new_buy_risk_health(object())

    assert result.status is ai_executor.RiskCheckStatus.UNHEALTHY
    assert result.allows_new_buy is False
    assert result.affected_symbols == frozenset({"KRW-BTC"})
    assert "THRESHOLD_TRIGGERED:KRW-BTC:TP_SELL" in result.reasons


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("portfolio", "expected_reason"),
    [
        (_portfolio(error="UPBIT_API_ERROR"), "PORTFOLIO_ERROR:UPBIT_API_ERROR"),
        (_portfolio(is_stale=True), "PORTFOLIO_STALE"),
        (
            _portfolio(_asset("BTC", current_price=0.0)),
            "INVALID_CURRENT_PRICE:BTC",
        ),
        (
            _portfolio(_asset("BTC", current_price=float("nan"))),
            "INVALID_CURRENT_PRICE:BTC",
        ),
        (
            _portfolio(_asset("BTC", avg_buy_price=0.0)),
            "INVALID_AVG_BUY_PRICE:BTC",
        ),
        (
            _portfolio(_asset("BTC", avg_buy_price=float("nan"))),
            "INVALID_AVG_BUY_PRICE:BTC",
        ),
    ],
)
async def test_new_buy_risk_is_unknown_for_incomplete_portfolio(
    monkeypatch,
    portfolio: PortfolioSummary,
    expected_reason: str,
) -> None:
    async def load_thresholds(_db: object) -> tuple[float, float]:
        return 10.0, -10.0

    monkeypatch.setattr(ai_executor, "_load_hard_tp_sl_thresholds", load_thresholds)
    monkeypatch.setattr(ai_executor, "PortfolioService", _portfolio_service(portfolio))

    result = await ai_executor.evaluate_new_buy_risk_health(object())

    assert result.status is ai_executor.RiskCheckStatus.UNKNOWN
    assert result.allows_new_buy is False
    assert expected_reason in result.reasons


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "risk_check",
    [
        None,
        ai_executor.RiskCheckResult(status=ai_executor.RiskCheckStatus.UNKNOWN),
        ai_executor.RiskCheckResult(status=ai_executor.RiskCheckStatus.UNHEALTHY),
    ],
)
async def test_buy_fails_closed_before_portfolio_entry_gate_and_order(
    monkeypatch,
    risk_check: ai_executor.RiskCheckResult | None,
) -> None:
    analysis = _analysis(decision="BUY")

    async def load_analysis(_db: object, analysis_id: int):
        assert analysis_id == analysis.id
        return analysis

    class UnexpectedPortfolioService:
        def __init__(self, _db: object) -> None:
            raise AssertionError("차단된 BUY에서 포트폴리오를 조회하면 안 됩니다.")

    async def unexpected_entry_gate(*_args, **_kwargs):
        raise AssertionError("차단된 BUY에서 EntryGate를 실행하면 안 됩니다.")

    async def unexpected_buy_order(**_kwargs):
        raise AssertionError("차단된 BUY에서 주문 경로를 실행하면 안 됩니다.")

    monkeypatch.setattr(ai_executor, "get_bot_status", _running_status)
    monkeypatch.setattr(ai_executor, "_load_analysis_by_id", load_analysis)
    monkeypatch.setattr(ai_executor, "_load_executor_thresholds", _executor_thresholds)
    monkeypatch.setattr(ai_executor, "PortfolioService", UnexpectedPortfolioService)
    monkeypatch.setattr(ai_executor, "evaluate_ai_buy_entry_gate", unexpected_entry_gate)
    monkeypatch.setattr(ai_executor, "_execute_buy_trade", unexpected_buy_order)

    result = await ai_executor.execute_ai_trade(
        object(),
        analysis.symbol,
        analysis_id=analysis.id,
        risk_check=risk_check,
    )

    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [ai_executor.RiskCheckStatus.HEALTHY, ai_executor.RiskCheckStatus.DISABLED],
)
async def test_safe_risk_status_keeps_existing_buy_path(monkeypatch, status) -> None:
    analysis = _analysis(decision="BUY")
    portfolio = _portfolio(_asset("KRW", balance=100_000.0, current_price=1.0))
    calls: list[str] = []
    sentinel = object()

    async def load_analysis(_db: object, analysis_id: int):
        assert analysis_id == analysis.id
        return analysis

    async def allow_entry(*_args, **_kwargs):
        calls.append("entry_gate")
        return SimpleNamespace(
            allowed=True,
            shadow_mode=False,
            to_log_dict=lambda: {"allowed": True},
        )

    async def execute_buy(**kwargs):
        calls.append("buy")
        assert kwargs["analysis"] is analysis
        assert kwargs["portfolio"] is portfolio
        return sentinel

    monkeypatch.setattr(ai_executor, "get_bot_status", _running_status)
    monkeypatch.setattr(ai_executor, "_load_analysis_by_id", load_analysis)
    monkeypatch.setattr(ai_executor, "_load_executor_thresholds", _executor_thresholds)
    monkeypatch.setattr(ai_executor, "PortfolioService", _portfolio_service(portfolio))
    monkeypatch.setattr(ai_executor, "get_trading_mode", _paper_mode)
    monkeypatch.setattr(ai_executor, "evaluate_ai_buy_entry_gate", allow_entry)
    monkeypatch.setattr(ai_executor, "_execute_buy_trade", execute_buy)

    result = await ai_executor.execute_ai_trade(
        object(),
        analysis.symbol,
        analysis_id=analysis.id,
        risk_check=ai_executor.RiskCheckResult(status=status),
    )

    assert result is sentinel
    assert calls == ["entry_gate", "buy"]


@pytest.mark.asyncio
async def test_unknown_risk_does_not_block_existing_sell_path(monkeypatch) -> None:
    analysis = _analysis(decision="SELL")
    portfolio = _portfolio(_asset("BTC"))
    sentinel = object()

    async def load_analysis(_db: object, analysis_id: int):
        assert analysis_id == analysis.id
        return analysis

    async def unexpected_entry_gate(*_args, **_kwargs):
        raise AssertionError("SELL에서 BUY EntryGate를 실행하면 안 됩니다.")

    async def execute_sell(**kwargs):
        assert kwargs["analysis"] is analysis
        assert kwargs["portfolio"] is portfolio
        return sentinel

    monkeypatch.setattr(ai_executor, "get_bot_status", _running_status)
    monkeypatch.setattr(ai_executor, "_load_analysis_by_id", load_analysis)
    monkeypatch.setattr(ai_executor, "_load_executor_thresholds", _executor_thresholds)
    monkeypatch.setattr(ai_executor, "PortfolioService", _portfolio_service(portfolio))
    monkeypatch.setattr(ai_executor, "get_trading_mode", _paper_mode)
    monkeypatch.setattr(ai_executor, "evaluate_ai_buy_entry_gate", unexpected_entry_gate)
    monkeypatch.setattr(ai_executor, "_execute_sell_trade", execute_sell)

    result = await ai_executor.execute_ai_trade(
        object(),
        analysis.symbol,
        analysis_id=analysis.id,
        risk_check=ai_executor.RiskCheckResult(
            status=ai_executor.RiskCheckStatus.UNKNOWN,
            reasons=("RISK_CHECK_FAILED",),
        ),
    )

    assert result is sentinel
