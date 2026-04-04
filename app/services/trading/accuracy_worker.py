import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import AIAnalysisLog
from app.services.brokers.factory import BrokerFactory

logger = logging.getLogger(__name__)

ACCURACY_TARGET_AGE_MINUTES = 60
ACCURACY_BATCH_SIZE = 50
ACCURACY_TIMEFRAME = "1m"
ACCURACY_NEAREST_FETCH_COUNT = 3
ACCURACY_AFTER_CURSOR_MINUTES = 2


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_to_param(value: datetime) -> str:
    return _normalize_datetime(value).strftime("%Y-%m-%dT%H:%M:%S")


def _parse_candle_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None

    return _normalize_datetime(parsed)


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _resolve_accuracy_label(decision: str, analysis_price: float, future_price: float) -> str | None:
    normalized_decision = str(decision or "").strip().upper()
    if normalized_decision == "BUY":
        return "SUCCESS" if future_price > analysis_price else "FAIL"
    if normalized_decision == "SELL":
        return "SUCCESS" if future_price < analysis_price else "FAIL"
    return None


def _calculate_price_diff_pct(analysis_price: float, future_price: float) -> float | None:
    if analysis_price <= 0:
        return None
    return ((future_price - analysis_price) / analysis_price) * 100.0


def _extract_trade_price(row: dict[str, Any]) -> float:
    return _to_float(row.get("trade_price"))


def _select_nearest_trade_price(rows: list[dict[str, Any]], target_time: datetime) -> float | None:
    normalized_target = _normalize_datetime(target_time)
    best_row: dict[str, Any] | None = None
    best_distance: float | None = None

    for row in rows:
        candle_time = _parse_candle_datetime(row.get("candle_date_time_utc"))
        price = _extract_trade_price(row)
        if candle_time is None or price <= 0:
            continue

        distance = abs((candle_time - normalized_target).total_seconds())
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_row = row

    if best_row is None:
        return None
    return _extract_trade_price(best_row)


async def _fetch_candles_near_time(broker: Any, symbol: str, target_time: datetime) -> list[dict[str, Any]]:
    request = getattr(broker, "_request", None)
    resolve_candle_path = getattr(broker, "_resolve_candle_path", None)
    if not callable(request) or not callable(resolve_candle_path):
        raise RuntimeError("UPBIT broker does not support internal candle cursor lookup")

    candle_path = resolve_candle_path(ACCURACY_TIMEFRAME)
    normalized_symbol = str(symbol or "").strip().upper()
    before_cursor = _normalize_datetime(target_time)
    after_cursor = before_cursor + timedelta(minutes=ACCURACY_AFTER_CURSOR_MINUTES)

    before_rows = await request(
        "GET",
        candle_path,
        params={
            "market": normalized_symbol,
            "count": ACCURACY_NEAREST_FETCH_COUNT,
            "to": _format_to_param(before_cursor),
        },
        auth=False,
    )
    after_rows = await request(
        "GET",
        candle_path,
        params={
            "market": normalized_symbol,
            "count": ACCURACY_NEAREST_FETCH_COUNT,
            "to": _format_to_param(after_cursor),
        },
        auth=False,
    )

    deduped: dict[str, dict[str, Any]] = {}
    for row in [*(before_rows if isinstance(before_rows, list) else []), *(after_rows if isinstance(after_rows, list) else [])]:
        if not isinstance(row, dict):
            continue
        candle_key = str(row.get("candle_date_time_utc") or "").strip()
        if not candle_key:
            continue
        deduped[candle_key] = row
    return list(deduped.values())


async def _resolve_nearest_trade_price(broker: Any, symbol: str, target_time: datetime) -> float | None:
    rows = await _fetch_candles_near_time(broker, symbol, target_time)
    return _select_nearest_trade_price(rows, target_time)


async def update_ai_analysis_accuracy(db: AsyncSession) -> int:
    now_utc = datetime.now(UTC)
    eligible_before = now_utc - timedelta(minutes=ACCURACY_TARGET_AGE_MINUTES)

    try:
        result = await db.execute(
            select(AIAnalysisLog)
            .where(AIAnalysisLog.accuracy_label.is_(None))
            .where(AIAnalysisLog.decision.in_(("BUY", "SELL")))
            .where(AIAnalysisLog.created_at <= eligible_before)
            .order_by(asc(AIAnalysisLog.created_at), asc(AIAnalysisLog.id))
            .limit(ACCURACY_BATCH_SIZE)
        )
        analysis_logs = result.scalars().all()
        if not analysis_logs:
            return 0

        broker = BrokerFactory.get_broker("UPBIT")
        updated_count = 0

        for analysis in analysis_logs:
            analysis_time = _normalize_datetime(analysis.created_at)
            future_time = analysis_time + timedelta(minutes=ACCURACY_TARGET_AGE_MINUTES)
            try:
                analysis_price = await _resolve_nearest_trade_price(broker, analysis.symbol, analysis_time)
                future_price = await _resolve_nearest_trade_price(broker, analysis.symbol, future_time)
            except Exception as exc:
                logger.warning(
                    "AI 분석 정확도 검증용 시세 조회 실패: symbol=%s analysis_id=%s error=%s",
                    analysis.symbol,
                    analysis.id,
                    exc,
                    exc_info=True,
                )
                continue

            if analysis_price is None or future_price is None or analysis_price <= 0 or future_price <= 0:
                logger.info(
                    "AI 분석 정확도 검증 스킵: 시세 데이터가 부족합니다. symbol=%s analysis_id=%s analysis_price=%s future_price=%s",
                    analysis.symbol,
                    analysis.id,
                    analysis_price,
                    future_price,
                )
                continue

            accuracy_label = _resolve_accuracy_label(analysis.decision, analysis_price, future_price)
            actual_price_diff_pct = _calculate_price_diff_pct(analysis_price, future_price)
            if accuracy_label is None or actual_price_diff_pct is None:
                continue

            analysis.accuracy_label = accuracy_label
            analysis.actual_price_diff_pct = actual_price_diff_pct
            analysis.accuracy_checked_at = datetime.now(UTC)
            updated_count += 1

        if updated_count > 0:
            await db.commit()
        return updated_count
    except Exception:
        await db.rollback()
        logger.error("AI 분석 정확도 워커 실행 중 예외가 발생했습니다.", exc_info=True)
        return 0
