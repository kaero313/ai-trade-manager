import logging
from datetime import datetime, timezone
from typing import Any

from app.services.backtesting.data_loader import fetch_historical_data
from app.services.backtesting.simulated_broker import SimulatedBroker
from app.services.trading.strategies.grid_strategy import GridStrategy

logger = logging.getLogger(__name__)


def _normalize_datetime_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class BacktestEngine:
    def __init__(self, fee_rate: float = 0.0005) -> None:
        self._is_running = True
        self._fee_rate = max(float(fee_rate), 0.0)

    def stop(self) -> None:
        self._is_running = False

    async def run(
        self,
        market: str,
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        timeframe: str = "60m",
        grid_upper_bound: float = 100_000_000.0,
        grid_lower_bound: float = 80_000_000.0,
        grid_order_krw: float = 10_000.0,
        grid_sell_pct: float = 100.0,
        grid_cooldown_seconds: int = 60,
    ) -> dict[str, Any]:
        market_symbol = str(market or "").strip().upper()
        if not market_symbol:
            raise ValueError("market is required")
        start_utc = _normalize_datetime_utc(start_date)
        end_utc = _normalize_datetime_utc(end_date)
        if start_utc > end_utc:
            raise ValueError("start_date must be earlier than or equal to end_date")

        initial_balance_value = float(initial_balance)
        grid_upper_bound_value = float(grid_upper_bound)
        grid_lower_bound_value = float(grid_lower_bound)
        grid_order_krw_value = float(grid_order_krw)
        grid_sell_pct_value = float(grid_sell_pct)
        grid_cooldown_seconds_value = int(grid_cooldown_seconds)

        if initial_balance_value <= 0:
            raise ValueError("initial_balance must be greater than zero")
        if grid_lower_bound_value <= 0 or grid_upper_bound_value <= 0:
            raise ValueError("grid bounds must be greater than zero")
        if grid_upper_bound_value <= grid_lower_bound_value:
            raise ValueError("grid_upper_bound must be greater than grid_lower_bound")
        if grid_order_krw_value <= 0:
            raise ValueError("grid_order_krw must be greater than zero")
        if grid_sell_pct_value <= 0 or grid_sell_pct_value > 100:
            raise ValueError("grid_sell_pct must be in (0, 100]")
        if grid_cooldown_seconds_value < 1:
            raise ValueError("grid_cooldown_seconds must be at least 1")

        logger.info(
            "Backtest run started: market=%s timeframe=%s start=%s end=%s initial_balance=%s",
            market_symbol,
            timeframe,
            start_utc.isoformat(),
            end_utc.isoformat(),
            initial_balance_value,
        )

        candles = await fetch_historical_data(
            market=market_symbol,
            timeframe=timeframe,
            start_date=start_utc,
            end_date=end_utc,
        )

        broker = SimulatedBroker(initial_krw_balance=initial_balance_value, fee_rate=self._fee_rate)
        target_coin = market_symbol.split("-", 1)[1] if "-" in market_symbol else market_symbol
        strategy = GridStrategy(
            market=market_symbol,
            target_coin=target_coin,
            grid_upper_bound=grid_upper_bound_value,
            grid_lower_bound=grid_lower_bound_value,
            grid_order_krw=grid_order_krw_value,
            grid_sell_pct=grid_sell_pct_value,
            grid_cooldown_seconds=grid_cooldown_seconds_value,
        )

        trades: list[dict[str, Any]] = []
        processed_bars = 0
        last_timestamp: str | None = None
        last_close = 0.0

        for index, candle in enumerate(candles):
            if not self._is_running:
                logger.info("Backtest run interrupted by stop signal.")
                break

            processed_bars = index + 1
            last_timestamp = str(candle.get("timestamp") or "").strip()
            tick_time = _parse_timestamp(last_timestamp)
            close_price = _to_float(candle.get("close"))
            if tick_time is None or close_price <= 0:
                continue

            last_close = close_price
            broker.set_current_price(market_symbol, close_price, tick_time)
            result = await strategy.execute(
                current_price=close_price,
                broker=broker,
                current_time=tick_time,
            )

            if result.executed:
                trades.append(
                    {
                        "index": index,
                        "timestamp": tick_time.isoformat(),
                        "side": result.side,
                        "price": result.executed_price,
                        "qty": result.executed_qty,
                        "fee": _to_float((result.order_result or {}).get("paid_fee")),
                        "krw_balance": broker.get_krw_balance(),
                        "coin_balance": broker.get_coin_balance(target_coin),
                    }
                )

        position_qty = broker.get_coin_balance(target_coin)
        final_balance = broker.get_krw_balance() + (position_qty * last_close if last_close > 0 else 0.0)
        logger.info(
            "Backtest run finished: market=%s timeframe=%s processed=%s final_balance=%s",
            market_symbol,
            timeframe,
            processed_bars,
            final_balance,
        )

        return {
            "market": market_symbol,
            "timeframe": timeframe,
            "start_date": start_utc.isoformat(),
            "end_date": end_utc.isoformat(),
            "bars_processed": processed_bars,
            "last_timestamp": last_timestamp,
            "initial_balance": initial_balance_value,
            "final_balance": final_balance,
            "position_qty": position_qty,
            "trades": trades,
        }


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
