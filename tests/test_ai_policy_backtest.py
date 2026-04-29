import asyncio
from datetime import UTC, datetime, timedelta

from app.api.routes import backtest as backtest_route
from app.services.backtesting.engine import AIPolicyBacktestEngine


def _candles(prices: list[float]) -> list[dict[str, float | str]]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rows: list[dict[str, float | str]] = []
    previous = prices[0]
    for index, price in enumerate(prices):
        timestamp = start + timedelta(hours=index)
        rows.append(
            {
                "timestamp": timestamp.isoformat(),
                "open": previous,
                "high": max(previous, price) * 1.01,
                "low": min(previous, price) * 0.99,
                "close": price,
                "volume": 1000.0 + index,
            }
        )
        previous = price
    return rows


async def _run_with_prices(
    monkeypatch,
    prices: list[float],
    *,
    strategy: dict | None = None,
    policy: dict | None = None,
) -> dict:
    async def fake_fetch_historical_data(**_kwargs):
        return _candles(prices)

    monkeypatch.setattr(
        "app.services.backtesting.engine.fetch_historical_data",
        fake_fetch_historical_data,
    )
    engine = AIPolicyBacktestEngine()
    return await engine.run(
        market="KRW-BTC",
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        end_date=datetime(2026, 1, 5, tzinfo=UTC),
        initial_balance=1_000_000,
        timeframe="60m",
        strategy=strategy
        or {
            "ema_fast": 5,
            "ema_slow": 12,
            "rsi_period": 5,
            "rsi_min": 50,
            "trailing_stop_pct": 0.05,
        },
        policy=policy
        or {
            "min_confidence": 70,
            "max_allocation_pct": 30,
            "take_profit_pct": 1_000,
            "stop_loss_pct": -100,
            "cooldown_minutes": 0,
        },
    )


def test_ai_policy_backtest_buys_in_uptrend(monkeypatch) -> None:
    prices = [100 + index for index in range(80)]

    result = asyncio.run(_run_with_prices(monkeypatch, prices))

    assert any(trade["side"] == "buy" for trade in result["trades"])
    assert result["equity_curve"]
    assert result["drawdown_curve"]


def test_ai_policy_backtest_sells_on_risk_exit(monkeypatch) -> None:
    prices = [100 + index for index in range(35)] + [135 - (index * 3) for index in range(20)]

    result = asyncio.run(_run_with_prices(monkeypatch, prices))

    sell_reasons = {
        trade["reason"]
        for trade in result["trades"]
        if trade["side"] == "sell"
    }
    assert sell_reasons & {"trailing_stop", "stop_loss"}


def test_ai_policy_backtest_skips_when_confidence_is_too_high(monkeypatch) -> None:
    prices = [100 + index for index in range(80)]

    result = asyncio.run(
        _run_with_prices(
            monkeypatch,
            prices,
            policy={
                "min_confidence": 99,
                "max_allocation_pct": 30,
                "take_profit_pct": 1_000,
                "stop_loss_pct": -100,
                "cooldown_minutes": 0,
            },
        )
    )

    assert result["trades"] == []


def test_ai_policy_backtest_respects_max_allocation(monkeypatch) -> None:
    prices = [100 + index for index in range(80)]

    result = asyncio.run(
        _run_with_prices(
            monkeypatch,
            prices,
            policy={
                "min_confidence": 50,
                "max_allocation_pct": 10,
                "take_profit_pct": 1_000,
                "stop_loss_pct": -100,
                "cooldown_minutes": 0,
            },
        )
    )

    buy_trade = next(trade for trade in result["trades"] if trade["side"] == "buy")
    assert buy_trade["price"] * buy_trade["qty"] <= 100_000


def test_backtest_ai_briefing_falls_back_when_provider_fails(monkeypatch) -> None:
    class BrokenRouter:
        def __init__(self, _db) -> None:
            pass

        async def generate_report(self, _prompt: str):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(backtest_route, "AIProviderRouter", BrokenRouter)

    briefing = asyncio.run(
        backtest_route._build_ai_briefing(
            object(),
            {
                "summary": {
                    "total_return_pct": 3.2,
                    "max_drawdown_pct": 4.1,
                    "number_of_trades": 2,
                },
                "meta": {"market": "KRW-BTC"},
            },
        )
    )

    assert briefing.fallback is True
    assert "KRW-BTC" in briefing.content
