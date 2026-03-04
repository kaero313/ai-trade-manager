import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.brokers.factory import BrokerFactory
from app.services.brokers.upbit import UpbitAPIError

router = APIRouter()
broker = BrokerFactory.get_broker("UPBIT")

MARKETS_CACHE_TTL_SECONDS = 300
MAX_TICKER_SYMBOLS = 100

_MARKETS_CACHE_LOCK = threading.Lock()
_MARKETS_CACHE: dict[str, Any] = {
    "payload": None,
    "cached_at": None,
}


class MarketItem(BaseModel):
    market: str = Field(...)
    korean_name: str = Field(default="")
    english_name: str = Field(default="")


class TickerItem(BaseModel):
    symbol: str = Field(...)
    current_price: float = Field(...)
    signed_change_rate: float = Field(...)
    acc_trade_price_24h: float = Field(...)


class CandleItem(BaseModel):
    time: int | str = Field(...)
    open: float = Field(...)
    high: float = Field(...)
    low: float = Field(...)
    close: float = Field(...)
    volume: float = Field(...)


def _snapshot_markets_cache() -> dict[str, Any]:
    with _MARKETS_CACHE_LOCK:
        return {
            "payload": _MARKETS_CACHE.get("payload"),
            "cached_at": _MARKETS_CACHE.get("cached_at"),
        }


def _cache_is_valid(snapshot: dict[str, Any], now_utc: datetime) -> bool:
    cached_at = snapshot.get("cached_at")
    if not isinstance(cached_at, datetime):
        return False
    return now_utc - cached_at < timedelta(seconds=MARKETS_CACHE_TTL_SECONDS)


def _store_markets_cache(items: list[MarketItem]) -> None:
    with _MARKETS_CACHE_LOCK:
        _MARKETS_CACHE["payload"] = [item.model_dump() for item in items]
        _MARKETS_CACHE["cached_at"] = datetime.now(timezone.utc)


def _parse_symbol_csv(symbols: str) -> list[str]:
    parsed: list[str] = []
    for raw in symbols.split(","):
        item = raw.strip().upper()
        if not item:
            continue
        parsed.append(item)
    return list(dict.fromkeys(parsed))


def _is_minute_timeframe(timeframe: str) -> bool:
    return re.fullmatch(r"\d+m", str(timeframe or "").strip().lower()) is not None


def _parse_candle_time(raw_time: Any) -> datetime | None:
    text = str(raw_time or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def _safe_call(coro):
    try:
        return await coro
    except UpbitAPIError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.to_dict()) from exc


@router.get("/", response_model=list[MarketItem])
async def get_markets() -> list[MarketItem]:
    now_utc = datetime.now(timezone.utc)
    snapshot = _snapshot_markets_cache()
    payload = snapshot.get("payload")
    if _cache_is_valid(snapshot, now_utc) and isinstance(payload, list):
        return [MarketItem(**item) for item in payload if isinstance(item, dict)]

    raw_markets = await _safe_call(broker.get_all_markets())
    items: list[MarketItem] = []
    for row in raw_markets:
        if not isinstance(row, dict):
            continue
        market = str(row.get("market") or "").strip().upper()
        if not market:
            continue
        items.append(
            MarketItem(
                market=market,
                korean_name=str(row.get("korean_name") or "").strip(),
                english_name=str(row.get("english_name") or "").strip(),
            )
        )

    _store_markets_cache(items)
    return items


@router.get("/tickers", response_model=list[TickerItem])
async def get_tickers(
    symbols: str = Query(..., description="Comma-separated symbols, e.g. KRW-BTC,KRW-ETH"),
) -> list[TickerItem]:
    parsed_symbols = _parse_symbol_csv(symbols)
    if not parsed_symbols:
        raise HTTPException(status_code=400, detail="symbols query parameter is required")
    if len(parsed_symbols) > MAX_TICKER_SYMBOLS:
        raise HTTPException(
            status_code=400,
            detail=f"symbols supports up to {MAX_TICKER_SYMBOLS} items",
        )

    raw_tickers = await _safe_call(broker.get_ticker(parsed_symbols))
    items: list[TickerItem] = []
    for row in raw_tickers:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("market") or "").strip().upper()
        if not symbol:
            continue
        items.append(
            TickerItem(
                symbol=symbol,
                current_price=_to_float(row.get("trade_price")),
                signed_change_rate=_to_float(row.get("signed_change_rate")),
                acc_trade_price_24h=_to_float(row.get("acc_trade_price_24h")),
            )
        )
    return items


@router.get("/{symbol}/candles", response_model=list[CandleItem])
async def get_candles(
    symbol: str,
    timeframe: str = Query("days", description="days, weeks, months, or minute format like 60m"),
    count: int = Query(200, ge=1, le=200),
) -> list[CandleItem]:
    market = str(symbol or "").strip().upper()
    if not market:
        raise HTTPException(status_code=400, detail="symbol is required")

    try:
        raw_candles = await _safe_call(
            broker.get_candles(
                market=market,
                timeframe=timeframe,
                count=count,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    is_minute = _is_minute_timeframe(timeframe)
    items: list[CandleItem] = []
    for row in reversed(raw_candles):
        if not isinstance(row, dict):
            continue
        candle_time = _parse_candle_time(row.get("candle_date_time_utc"))
        if candle_time is None:
            continue

        time_value: int | str
        if is_minute:
            time_value = int(candle_time.timestamp())
        else:
            time_value = candle_time.date().isoformat()

        items.append(
            CandleItem(
                time=time_value,
                open=_to_float(row.get("opening_price")),
                high=_to_float(row.get("high_price")),
                low=_to_float(row.get("low_price")),
                close=_to_float(row.get("trade_price")),
                volume=_to_float(row.get("candle_acc_trade_volume")),
            )
        )

    return items
