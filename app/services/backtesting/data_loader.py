import asyncio
import csv
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

UPBIT_MINUTE_UNITS = {1, 3, 5, 10, 15, 30, 60, 240}
UPBIT_PAGE_SIZE = 200
UPBIT_REQUEST_GAP_SECONDS = 0.12


def _normalize_market(market: str) -> str:
    normalized = str(market or "").strip().upper()
    if not normalized:
        raise ValueError("market is required")
    return normalized


def _normalize_datetime_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resolve_candle_path(timeframe: str) -> tuple[str, str]:
    normalized = str(timeframe or "").strip().lower()
    if normalized in {"day", "days"}:
        return "days", "/v1/candles/days"

    minute_match = re.fullmatch(r"(\d+)m", normalized)
    if minute_match:
        minute_unit = int(minute_match.group(1))
        if minute_unit not in UPBIT_MINUTE_UNITS:
            raise ValueError(
                f"Unsupported minute timeframe: {timeframe}. "
                f"Supported units: {sorted(UPBIT_MINUTE_UNITS)}"
            )
        return f"{minute_unit}m", f"/v1/candles/minutes/{minute_unit}"

    raise ValueError("timeframe must be days or supported minute format like 60m")


def _parse_upbit_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialize_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _cache_file_path(
    market: str,
    timeframe: str,
    start_utc: datetime,
    end_utc: datetime,
) -> Path:
    cache_dir = _project_root() / "data" / "backtesting" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    market_token = market.replace("-", "_")
    start_token = start_utc.strftime("%Y%m%dT%H%M%SZ")
    end_token = end_utc.strftime("%Y%m%dT%H%M%SZ")
    return cache_dir / f"{market_token}_{timeframe}_{start_token}_{end_token}.csv"


def _read_cached_csv(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None

    try:
        rows: list[dict[str, Any]] = []
        with path.open("r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                timestamp = str(row.get("timestamp") or "").strip()
                if not timestamp:
                    continue
                rows.append(
                    {
                        "timestamp": timestamp,
                        "open": _to_float(row.get("open")),
                        "high": _to_float(row.get("high")),
                        "low": _to_float(row.get("low")),
                        "close": _to_float(row.get("close")),
                        "volume": _to_float(row.get("volume")),
                    }
                )
        rows.sort(key=lambda item: item["timestamp"])
        return rows
    except Exception:
        logger.exception("Backtest candle cache read failed: path=%s", path)
        return None


def _write_cached_csv(path: Path, candles: list[dict[str, Any]]) -> None:
    try:
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=["timestamp", "open", "high", "low", "close", "volume"],
            )
            writer.writeheader()
            writer.writerows(candles)
    except Exception:
        logger.exception("Backtest candle cache write failed: path=%s", path)


def _format_to_param(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _normalize_upbit_candle(row: dict[str, Any]) -> tuple[datetime, dict[str, Any]] | None:
    timestamp = _parse_upbit_utc(row.get("candle_date_time_utc"))
    if timestamp is None:
        return None

    candle = {
        "timestamp": _serialize_utc(timestamp),
        "open": _to_float(row.get("opening_price")),
        "high": _to_float(row.get("high_price")),
        "low": _to_float(row.get("low_price")),
        "close": _to_float(row.get("trade_price")),
        "volume": _to_float(row.get("candle_acc_trade_volume")),
    }
    return timestamp, candle


async def _fetch_page(
    client: httpx.AsyncClient,
    url: str,
    market: str,
    to_cursor: datetime | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"market": market, "count": UPBIT_PAGE_SIZE}
    if to_cursor is not None:
        params["to"] = _format_to_param(to_cursor)

    response = await client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


async def fetch_historical_data(
    market: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
) -> list[dict[str, Any]]:
    market_symbol = _normalize_market(market)
    normalized_timeframe, candle_path = _resolve_candle_path(timeframe)
    start_utc = _normalize_datetime_utc(start_date)
    end_utc = _normalize_datetime_utc(end_date)
    if start_utc > end_utc:
        raise ValueError("start_date must be earlier than or equal to end_date")

    cache_path = _cache_file_path(market_symbol, normalized_timeframe, start_utc, end_utc)
    cached = _read_cached_csv(cache_path)
    if cached is not None:
        logger.info(
            "Backtest OHLCV cache hit: market=%s timeframe=%s rows=%s",
            market_symbol,
            normalized_timeframe,
            len(cached),
        )
        return cached

    logger.info(
        "Backtest OHLCV cache miss: market=%s timeframe=%s start=%s end=%s",
        market_symbol,
        normalized_timeframe,
        start_utc.isoformat(),
        end_utc.isoformat(),
    )

    request_url = f"{settings.upbit_base_url.rstrip('/')}{candle_path}"
    to_cursor: datetime | None = end_utc
    oldest_seen: datetime | None = None
    raw_rows: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=settings.upbit_timeout) as client:
        while True:
            page_rows = await _fetch_page(client, request_url, market_symbol, to_cursor)
            if not page_rows:
                break

            raw_rows.extend(page_rows)
            page_oldest: datetime | None = None
            for row in page_rows:
                parsed = _parse_upbit_utc(row.get("candle_date_time_utc"))
                if parsed is None:
                    continue
                if page_oldest is None or parsed < page_oldest:
                    page_oldest = parsed

            if page_oldest is None:
                break
            if page_oldest <= start_utc:
                break
            if oldest_seen is not None and page_oldest >= oldest_seen:
                logger.warning(
                    "Backtest OHLCV pagination did not advance. stopping loop: market=%s timeframe=%s",
                    market_symbol,
                    normalized_timeframe,
                )
                break

            oldest_seen = page_oldest
            to_cursor = page_oldest - timedelta(seconds=1)
            await asyncio.sleep(UPBIT_REQUEST_GAP_SECONDS)

    normalized_rows: dict[str, dict[str, Any]] = {}
    for row in raw_rows:
        normalized = _normalize_upbit_candle(row)
        if normalized is None:
            continue
        timestamp, candle = normalized
        if timestamp < start_utc or timestamp > end_utc:
            continue
        normalized_rows[candle["timestamp"]] = candle

    candles = sorted(normalized_rows.values(), key=lambda item: item["timestamp"])
    _write_cached_csv(cache_path, candles)

    logger.info(
        "Backtest OHLCV fetch completed: market=%s timeframe=%s rows=%s",
        market_symbol,
        normalized_timeframe,
        len(candles),
    )
    return candles
