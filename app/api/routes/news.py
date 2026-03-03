import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.services.news_analyzer import analyze_market_sentiment
from app.services.news_scraper import fetch_crypto_news

router = APIRouter()
SENTIMENT_CACHE_TTL_SECONDS = 900
_SENTIMENT_CACHE_LOCK = threading.Lock()
_SENTIMENT_CACHE: dict[str, Any] = {
    "payload": None,
    "cached_at": None,
}


class NewsItem(BaseModel):
    title: str = Field(...)
    summary: str = Field(...)
    link: str = Field(...)


class NewsResponse(BaseModel):
    analysis_completed_at: str = Field(...)
    count: int = Field(...)
    items: list[NewsItem] = Field(default_factory=list)


class SentimentResponse(BaseModel):
    score: int = Field(...)
    summary: list[str] = Field(default_factory=list)
    news_articles: list[NewsItem] = Field(default_factory=list)
    updated_at: datetime = Field(...)


def _build_news_items(raw_items: list[Any]) -> list[NewsItem]:
    return [
        NewsItem(
            title=str(item.get("title") or ""),
            summary=str(item.get("summary") or ""),
            link=str(item.get("link") or ""),
        )
        for item in raw_items
        if isinstance(item, dict)
    ]


def _snapshot_sentiment_cache() -> dict[str, Any]:
    with _SENTIMENT_CACHE_LOCK:
        return {
            "payload": _SENTIMENT_CACHE.get("payload"),
            "cached_at": _SENTIMENT_CACHE.get("cached_at"),
        }


def _cache_is_valid(snapshot: dict[str, Any], now_utc: datetime) -> bool:
    cached_at = snapshot.get("cached_at")
    if not isinstance(cached_at, datetime):
        return False
    return now_utc - cached_at < timedelta(seconds=SENTIMENT_CACHE_TTL_SECONDS)


def _store_sentiment_cache(response: SentimentResponse) -> None:
    with _SENTIMENT_CACHE_LOCK:
        _SENTIMENT_CACHE["payload"] = response.model_dump()
        _SENTIMENT_CACHE["cached_at"] = datetime.now(timezone.utc)


def _normalize_score(raw_score: Any) -> int:
    try:
        score = int(float(raw_score))
    except (TypeError, ValueError):
        score = 50
    return max(0, min(100, score))


@router.get("/", response_model=NewsResponse)
async def get_news() -> NewsResponse:
    payload = fetch_crypto_news()
    raw_items = payload.get("items") or []
    items = _build_news_items(raw_items)
    analysis_completed_at = str(payload.get("analysis_completed_at") or "")
    return NewsResponse(
        analysis_completed_at=analysis_completed_at,
        count=len(items),
        items=items,
    )


@router.get("/sentiment", response_model=SentimentResponse)
async def get_news_sentiment(
    force_refresh: bool = Query(False, description="true면 캐시를 무시하고 강제 재분석합니다."),
) -> SentimentResponse:
    now_utc = datetime.now(timezone.utc)
    if not force_refresh:
        snapshot = _snapshot_sentiment_cache()
        if _cache_is_valid(snapshot, now_utc) and isinstance(snapshot.get("payload"), dict):
            return SentimentResponse(**snapshot["payload"])

    news_payload = fetch_crypto_news(force_refresh=True)
    raw_items = news_payload.get("items") or []
    news_articles = _build_news_items(raw_items)

    sentiment_payload = await analyze_market_sentiment(
        [item.model_dump() for item in news_articles]
    )
    summary = sentiment_payload.get("summary")
    if not isinstance(summary, list):
        summary = []
    normalized_summary = [str(line).strip() for line in summary if str(line).strip()][:3]
    while len(normalized_summary) < 3:
        normalized_summary.append("요약 데이터가 부족하여 기본 문구로 대체되었습니다.")

    response = SentimentResponse(
        score=_normalize_score(sentiment_payload.get("score", 50)),
        summary=normalized_summary,
        news_articles=news_articles,
        updated_at=now_utc,
    )
    _store_sentiment_cache(response)
    return response
