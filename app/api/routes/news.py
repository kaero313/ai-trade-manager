import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.news_analyzer import analyze_market_sentiment
from app.services.news_scraper import fetch_crypto_news
from app.services.rag.ingestion import get_configured_market_news_sources
from app.services.rag.opensearch_client import INGESTION_RUNS_INDEX_NAME
from app.services.rag.opensearch_client import INDEX_NAME
from app.services.rag.opensearch_client import get_opensearch_client

router = APIRouter()
SENTIMENT_CACHE_TTL_SECONDS = 1800
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


class RagStatusResponse(BaseModel):
    status: str = Field(...)
    index_exists: bool = Field(...)
    total_documents: int = Field(...)
    parent_documents: int = Field(...)
    chunk_documents: int = Field(...)
    chunked_parent_documents: int = Field(...)
    avg_chunks_per_parent: float = Field(...)
    crawled_parent_documents: int = Field(...)
    rss_summary_parent_documents: int = Field(...)
    crawl_failed_parent_documents: int = Field(...)
    crawl_skipped_parent_documents: int = Field(...)
    avg_content_length: float = Field(...)
    avg_chunk_text_length: float = Field(...)
    real_documents: int = Field(...)
    fallback_documents: int = Field(...)
    embedded_documents: int = Field(...)
    missing_embedding_documents: int = Field(...)
    embedding_status_breakdown: dict[str, int] = Field(default_factory=dict)
    embedding_error_breakdown: dict[str, int] = Field(default_factory=dict)
    latest_published_at: str | None = Field(default=None)
    source_breakdown: dict[str, int] = Field(default_factory=dict)
    content_source_breakdown: dict[str, int] = Field(default_factory=dict)
    crawl_status_breakdown: dict[str, int] = Field(default_factory=dict)
    crawl_error_breakdown: dict[str, int] = Field(default_factory=dict)
    crawl_error_by_source: dict[str, dict[str, int]] = Field(default_factory=dict)
    latest_ingestion: dict[str, Any] | None = Field(default=None)
    configured_sources: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = Field(default=None)


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


def _build_rag_status_query() -> dict[str, Any]:
    fallback_filter = {
        "bool": {
            "should": [
                {"wildcard": {"link": "dummy://*"}},
                {"match_phrase": {"content": "credentials are unavailable"}},
                {"match_phrase": {"content": "request failed"}},
                {
                    "match_phrase": {
                        "content": "generated to keep the rag ingestion pipeline alive",
                    }
                },
            ],
            "minimum_should_match": 1,
        }
    }
    return {
        "size": 0,
        "aggs": {
            "fallback_documents": {"filter": fallback_filter},
            "embedded_documents": {"filter": {"exists": {"field": "embedding"}}},
            "missing_embedding_documents": {
                "filter": {
                    "bool": {
                        "must_not": [
                            {"exists": {"field": "embedding"}},
                        ]
                    }
                }
            },
            "parent_documents": {"cardinality": {"field": "parent_id"}},
            "chunk_documents": {"filter": {"exists": {"field": "parent_id"}}},
            "chunked_parent_documents": {
                "filter": {"term": {"is_chunked": True}},
                "aggs": {
                    "parents": {"cardinality": {"field": "parent_id"}},
                },
            },
            "crawled_parent_documents": {
                "filter": {"term": {"content_source": "crawled_body"}},
                "aggs": {"parents": {"cardinality": {"field": "parent_id"}}},
            },
            "rss_summary_parent_documents": {
                "filter": {"term": {"content_source": "rss_summary"}},
                "aggs": {"parents": {"cardinality": {"field": "parent_id"}}},
            },
            "crawl_failed_parent_documents": {
                "filter": {"term": {"crawl_status": "failed"}},
                "aggs": {"parents": {"cardinality": {"field": "parent_id"}}},
            },
            "crawl_skipped_parent_documents": {
                "filter": {"term": {"crawl_status": "skipped"}},
                "aggs": {"parents": {"cardinality": {"field": "parent_id"}}},
            },
            "avg_content_length": {"avg": {"field": "content_length"}},
            "avg_chunk_text_length": {"avg": {"field": "chunk_text_length"}},
            "latest_published_at": {"max": {"field": "published_at"}},
            "source_breakdown": {"terms": {"field": "source", "size": 20}},
            "content_source_breakdown": {"terms": {"field": "content_source", "size": 10}},
            "crawl_status_breakdown": {"terms": {"field": "crawl_status", "size": 10}},
            "crawl_error_breakdown": {"terms": {"field": "crawl_error", "size": 20}},
            "embedding_status_breakdown": {"terms": {"field": "embedding_status", "size": 10}},
            "embedding_error_breakdown": {"terms": {"field": "embedding_error", "size": 20}},
            "crawl_error_by_source": {
                "terms": {"field": "source", "size": 20},
                "aggs": {
                    "errors": {"terms": {"field": "crawl_error", "size": 20}},
                },
            },
        },
    }


def _to_int(raw_value: Any) -> int:
    try:
        return int(raw_value or 0)
    except (TypeError, ValueError):
        return 0


def _extract_total_hits(response: dict[str, Any]) -> int:
    total = response.get("hits", {}).get("total", 0)
    if isinstance(total, dict):
        return _to_int(total.get("value"))
    return _to_int(total)


def _extract_doc_count(aggregations: dict[str, Any], key: str) -> int:
    bucket = aggregations.get(key)
    if not isinstance(bucket, dict):
        return 0
    return _to_int(bucket.get("doc_count"))


def _extract_agg_value(aggregations: dict[str, Any], key: str) -> int:
    bucket = aggregations.get(key)
    if not isinstance(bucket, dict):
        return 0
    return _to_int(bucket.get("value"))


def _extract_nested_agg_value(aggregations: dict[str, Any], bucket_key: str, value_key: str) -> int:
    bucket = aggregations.get(bucket_key)
    if not isinstance(bucket, dict):
        return 0
    nested = bucket.get(value_key)
    if not isinstance(nested, dict):
        return 0
    return _to_int(nested.get("value"))


def _extract_source_breakdown(aggregations: dict[str, Any]) -> dict[str, int]:
    return _extract_terms_breakdown(aggregations, "source_breakdown")


def _extract_terms_breakdown(aggregations: dict[str, Any], key: str) -> dict[str, int]:
    terms_bucket = aggregations.get(key)
    if not isinstance(terms_bucket, dict):
        return {}
    buckets = terms_bucket.get("buckets")
    if not isinstance(buckets, list):
        return {}
    return {
        str(bucket.get("key")): _to_int(bucket.get("doc_count"))
        for bucket in buckets
        if isinstance(bucket, dict) and bucket.get("key") is not None
    }


def _extract_agg_float(aggregations: dict[str, Any], key: str) -> float:
    bucket = aggregations.get(key)
    if not isinstance(bucket, dict):
        return 0.0
    try:
        return round(float(bucket.get("value") or 0.0), 4)
    except (TypeError, ValueError):
        return 0.0


def _extract_nested_terms_breakdown(
    aggregations: dict[str, Any],
    key: str,
    nested_key: str,
) -> dict[str, dict[str, int]]:
    parent_bucket = aggregations.get(key)
    if not isinstance(parent_bucket, dict):
        return {}
    buckets = parent_bucket.get("buckets")
    if not isinstance(buckets, list):
        return {}

    breakdown: dict[str, dict[str, int]] = {}
    for bucket in buckets:
        if not isinstance(bucket, dict) or bucket.get("key") is None:
            continue
        nested_bucket = bucket.get(nested_key)
        if not isinstance(nested_bucket, dict):
            continue
        nested_buckets = nested_bucket.get("buckets")
        if not isinstance(nested_buckets, list):
            continue
        breakdown[str(bucket["key"])] = {
            str(item.get("key")): _to_int(item.get("doc_count"))
            for item in nested_buckets
            if isinstance(item, dict) and item.get("key") is not None
        }
    return breakdown


def _extract_latest_published_at(aggregations: dict[str, Any]) -> str | None:
    latest_bucket = aggregations.get("latest_published_at")
    if not isinstance(latest_bucket, dict):
        return None
    value = latest_bucket.get("value")
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _resolve_rag_status(
    *,
    index_exists: bool,
    total_documents: int,
    real_documents: int,
    fallback_documents: int,
    missing_embedding_documents: int,
) -> str:
    if not index_exists or total_documents <= 0:
        return "empty"
    if real_documents <= 0:
        return "degraded"
    if fallback_documents > 0 or missing_embedding_documents > 0:
        return "degraded"
    return "healthy"


async def _fetch_latest_ingestion_status(client: Any) -> dict[str, Any] | None:
    try:
        index_exists = await client.indices.exists(index=INGESTION_RUNS_INDEX_NAME)
        if not index_exists:
            return None

        response = await client.search(
            index=INGESTION_RUNS_INDEX_NAME,
            body={
                "size": 1,
                "query": {"match_all": {}},
                "sort": [{"finished_at": {"order": "desc"}}],
            },
        )
    except Exception:
        return None

    hits = response.get("hits", {}).get("hits", []) if isinstance(response, dict) else []
    if not isinstance(hits, list) or not hits:
        return None

    source = hits[0].get("_source") if isinstance(hits[0], dict) else None
    return source if isinstance(source, dict) else None


async def _build_rag_status_response(client: Any | None = None) -> RagStatusResponse:
    configured_sources = get_configured_market_news_sources()
    search_client = client or get_opensearch_client()
    index_exists = False

    try:
        index_exists = bool(await search_client.indices.exists(index=INDEX_NAME))
        if not index_exists:
            latest_ingestion = await _fetch_latest_ingestion_status(search_client)
            return RagStatusResponse(
                status="empty",
                index_exists=False,
                total_documents=0,
                parent_documents=0,
                chunk_documents=0,
                chunked_parent_documents=0,
                avg_chunks_per_parent=0.0,
                crawled_parent_documents=0,
                rss_summary_parent_documents=0,
                crawl_failed_parent_documents=0,
                crawl_skipped_parent_documents=0,
                avg_content_length=0.0,
                avg_chunk_text_length=0.0,
                real_documents=0,
                fallback_documents=0,
                embedded_documents=0,
                missing_embedding_documents=0,
                embedding_status_breakdown={},
                embedding_error_breakdown={},
                source_breakdown={},
                content_source_breakdown={},
                crawl_status_breakdown={},
                crawl_error_breakdown={},
                crawl_error_by_source={},
                latest_ingestion=latest_ingestion,
                configured_sources=configured_sources,
            )

        response = await search_client.search(index=INDEX_NAME, body=_build_rag_status_query())
    except Exception as exc:
        return RagStatusResponse(
            status="unavailable",
            index_exists=index_exists,
            total_documents=0,
            parent_documents=0,
            chunk_documents=0,
            chunked_parent_documents=0,
            avg_chunks_per_parent=0.0,
            crawled_parent_documents=0,
            rss_summary_parent_documents=0,
            crawl_failed_parent_documents=0,
            crawl_skipped_parent_documents=0,
            avg_content_length=0.0,
            avg_chunk_text_length=0.0,
            real_documents=0,
            fallback_documents=0,
            embedded_documents=0,
            missing_embedding_documents=0,
            embedding_status_breakdown={},
            embedding_error_breakdown={},
            source_breakdown={},
            content_source_breakdown={},
            crawl_status_breakdown={},
            crawl_error_breakdown={},
            crawl_error_by_source={},
            latest_ingestion=None,
            configured_sources=configured_sources,
            error=str(exc),
        )

    aggregations = response.get("aggregations") if isinstance(response, dict) else {}
    if not isinstance(aggregations, dict):
        aggregations = {}

    total_documents = _extract_total_hits(response)
    fallback_documents = _extract_doc_count(aggregations, "fallback_documents")
    embedded_documents = _extract_doc_count(aggregations, "embedded_documents")
    missing_embedding_documents = _extract_doc_count(aggregations, "missing_embedding_documents")
    parent_documents = _extract_agg_value(aggregations, "parent_documents")
    chunk_documents = _extract_doc_count(aggregations, "chunk_documents")
    chunked_parent_documents = _extract_nested_agg_value(
        aggregations,
        "chunked_parent_documents",
        "parents",
    )
    crawled_parent_documents = _extract_nested_agg_value(
        aggregations,
        "crawled_parent_documents",
        "parents",
    )
    rss_summary_parent_documents = _extract_nested_agg_value(
        aggregations,
        "rss_summary_parent_documents",
        "parents",
    )
    crawl_failed_parent_documents = _extract_nested_agg_value(
        aggregations,
        "crawl_failed_parent_documents",
        "parents",
    )
    crawl_skipped_parent_documents = _extract_nested_agg_value(
        aggregations,
        "crawl_skipped_parent_documents",
        "parents",
    )
    avg_chunks_per_parent = round(chunk_documents / parent_documents, 4) if parent_documents else 0.0
    avg_content_length = _extract_agg_float(aggregations, "avg_content_length")
    avg_chunk_text_length = _extract_agg_float(aggregations, "avg_chunk_text_length")
    real_documents = max(total_documents - fallback_documents, 0)
    status = _resolve_rag_status(
        index_exists=index_exists,
        total_documents=total_documents,
        real_documents=real_documents,
        fallback_documents=fallback_documents,
        missing_embedding_documents=missing_embedding_documents,
    )
    latest_ingestion = await _fetch_latest_ingestion_status(search_client)

    return RagStatusResponse(
        status=status,
        index_exists=index_exists,
        total_documents=total_documents,
        parent_documents=parent_documents,
        chunk_documents=chunk_documents,
        chunked_parent_documents=chunked_parent_documents,
        avg_chunks_per_parent=avg_chunks_per_parent,
        crawled_parent_documents=crawled_parent_documents,
        rss_summary_parent_documents=rss_summary_parent_documents,
        crawl_failed_parent_documents=crawl_failed_parent_documents,
        crawl_skipped_parent_documents=crawl_skipped_parent_documents,
        avg_content_length=avg_content_length,
        avg_chunk_text_length=avg_chunk_text_length,
        real_documents=real_documents,
        fallback_documents=fallback_documents,
        embedded_documents=embedded_documents,
        missing_embedding_documents=missing_embedding_documents,
        latest_published_at=_extract_latest_published_at(aggregations),
        source_breakdown=_extract_source_breakdown(aggregations),
        content_source_breakdown=_extract_terms_breakdown(aggregations, "content_source_breakdown"),
        crawl_status_breakdown=_extract_terms_breakdown(aggregations, "crawl_status_breakdown"),
        crawl_error_breakdown=_extract_terms_breakdown(aggregations, "crawl_error_breakdown"),
        embedding_status_breakdown=_extract_terms_breakdown(
            aggregations,
            "embedding_status_breakdown",
        ),
        embedding_error_breakdown=_extract_terms_breakdown(
            aggregations,
            "embedding_error_breakdown",
        ),
        crawl_error_by_source=_extract_nested_terms_breakdown(
            aggregations,
            "crawl_error_by_source",
            "errors",
        ),
        latest_ingestion=latest_ingestion,
        configured_sources=configured_sources,
    )


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


@router.get("/rag/status", response_model=RagStatusResponse)
async def get_rag_status() -> RagStatusResponse:
    return await _build_rag_status_response()


@router.get("/sentiment", response_model=SentimentResponse)
async def get_news_sentiment(
    force_refresh: bool = Query(False, description="true면 캐시를 무시하고 강제 재분석합니다."),
    db: AsyncSession = Depends(get_db),
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
        [item.model_dump() for item in news_articles],
        db,
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
