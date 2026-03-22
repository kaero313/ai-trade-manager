import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import get_or_create_bot_config
from app.db.repository import read_cached_market_sentiment
from app.db.repository import store_market_sentiment_cache
from app.models.schemas import MarketSentimentSnapshot

logger = logging.getLogger(__name__)

ALTERNATIVE_ME_FNG_URL = "https://api.alternative.me/fng/?limit=1"
SENTIMENT_HTTP_TIMEOUT = 10.0


class MarketSentimentFetchError(RuntimeError):
    pass


def _parse_snapshot(payload: dict[str, Any]) -> MarketSentimentSnapshot:
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and metadata.get("error"):
        raise MarketSentimentFetchError("Alternative.me 응답에 오류가 포함되어 있습니다.")

    items = payload.get("data")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise MarketSentimentFetchError("Alternative.me 응답 데이터가 비어 있습니다.")

    current = items[0]
    try:
        score = int(str(current.get("value") or "").strip())
    except ValueError as exc:
        raise MarketSentimentFetchError("Alternative.me 점수 형식이 올바르지 않습니다.") from exc

    classification = str(current.get("value_classification") or "").strip()
    if not classification:
        raise MarketSentimentFetchError("Alternative.me 분류 정보가 비어 있습니다.")

    timestamp_raw = current.get("timestamp")
    try:
        updated_at = datetime.fromtimestamp(int(str(timestamp_raw).strip()), tz=UTC)
    except (TypeError, ValueError) as exc:
        raise MarketSentimentFetchError("Alternative.me 시각 정보가 올바르지 않습니다.") from exc

    return MarketSentimentSnapshot(
        score=max(0, min(100, score)),
        classification=classification,
        updated_at=updated_at,
    )


async def fetch_market_sentiment() -> MarketSentimentSnapshot:
    try:
        async with httpx.AsyncClient(timeout=SENTIMENT_HTTP_TIMEOUT) as client:
            response = await client.get(ALTERNATIVE_ME_FNG_URL)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise MarketSentimentFetchError("Alternative.me API 요청에 실패했습니다.") from exc

    payload = response.json()
    if not isinstance(payload, dict):
        raise MarketSentimentFetchError("Alternative.me 응답 형식이 올바르지 않습니다.")

    return _parse_snapshot(payload)


async def get_cached_market_sentiment(db: AsyncSession) -> MarketSentimentSnapshot | None:
    bot_config = await get_or_create_bot_config(db)
    return read_cached_market_sentiment(bot_config.config_json)


async def refresh_market_sentiment_cache(db: AsyncSession) -> MarketSentimentSnapshot:
    snapshot = await fetch_market_sentiment()
    await store_market_sentiment_cache(db, snapshot)
    logger.info(
        "Market sentiment cache refreshed: score=%s classification=%s updated_at=%s",
        snapshot.score,
        snapshot.classification,
        snapshot.updated_at.isoformat(),
    )
    return snapshot


async def get_or_refresh_market_sentiment(db: AsyncSession) -> MarketSentimentSnapshot:
    cached = await get_cached_market_sentiment(db)
    if cached is not None:
        return cached
    return await refresh_market_sentiment_cache(db)
