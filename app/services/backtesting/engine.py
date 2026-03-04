import logging
from datetime import datetime, timezone
from typing import Any

from app.services.backtesting.data_loader import fetch_historical_data

logger = logging.getLogger(__name__)


def _normalize_datetime_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class BacktestEngine:
    def __init__(self) -> None:
        self._is_running = True

    def stop(self) -> None:
        self._is_running = False

    async def run(
        self,
        market: str,
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        timeframe: str = "60m",
    ) -> dict[str, Any]:
        market_symbol = str(market or "").strip().upper()
        start_utc = _normalize_datetime_utc(start_date)
        end_utc = _normalize_datetime_utc(end_date)
        if start_utc > end_utc:
            raise ValueError("start_date must be earlier than or equal to end_date")

        logger.info(
            "Backtest run started: market=%s timeframe=%s start=%s end=%s initial_balance=%s",
            market_symbol,
            timeframe,
            start_utc.isoformat(),
            end_utc.isoformat(),
            initial_balance,
        )

        candles = await fetch_historical_data(
            market=market_symbol,
            timeframe=timeframe,
            start_date=start_utc,
            end_date=end_utc,
        )

        cash = float(initial_balance)
        position_qty = 0.0
        trades: list[dict[str, Any]] = []
        processed_bars = 0
        last_timestamp: str | None = None

        for index, candle in enumerate(candles):
            if not self._is_running:
                logger.info("Backtest run interrupted by stop signal.")
                break

            processed_bars = index + 1
            last_timestamp = str(candle.get("timestamp") or "")
            await self._on_tick(index=index, candle=candle)

        final_balance = cash
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
            "initial_balance": float(initial_balance),
            "final_balance": final_balance,
            "position_qty": position_qty,
            "trades": trades,
        }

    async def _on_tick(self, index: int, candle: dict[str, Any]) -> None:
        _ = (index, candle)
        return None
