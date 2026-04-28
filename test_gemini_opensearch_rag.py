from datetime import UTC, datetime, timedelta

from app.services.ai.provider_router import resolve_provider_candidates
from app.services.rag.opensearch_client import (
    EMBEDDING_DIMENSION,
    KNN_ENGINE,
    KNN_SPACE_TYPE,
    MARKET_NEWS_INDEX_BODY,
    _is_expected_embedding_mapping,
)
from app.services.trading.ai_executor import DEFAULT_MAX_ALLOCATION_PCT


def test_market_news_index_uses_opensearch_3_lucene_knn() -> None:
    embedding = MARKET_NEWS_INDEX_BODY["mappings"]["properties"]["embedding"]

    assert embedding["type"] == "knn_vector"
    assert embedding["dimension"] == 1536
    assert embedding["method"]["name"] == "hnsw"
    assert embedding["method"]["engine"] == "lucene"
    assert embedding["method"]["space_type"] == "cosinesimil"
    assert EMBEDDING_DIMENSION == 1536
    assert KNN_ENGINE == "lucene"
    assert KNN_SPACE_TYPE == "cosinesimil"


def test_market_news_mapping_validation_rejects_legacy_nmslib() -> None:
    assert not _is_expected_embedding_mapping(
        {
            "type": "knn_vector",
            "dimension": 1536,
            "method": {
                "name": "hnsw",
                "engine": "nmslib",
                "space_type": "cosinesimil",
            },
        }
    )


def test_news_sentiment_provider_priority_supports_openai_fallback() -> None:
    now = datetime(2026, 4, 28, 3, 0, tzinfo=UTC)

    candidates = resolve_provider_candidates(
        priority_value=["gemini", "openai"],
        settings_value={
            "gemini": {"enabled": True, "model": "gemini-3-flash-preview"},
            "openai": {"enabled": True, "model": "gpt-5-mini"},
        },
        status_value={
            "gemini": {
                "blocked_until": (now + timedelta(hours=1)).isoformat(),
                "reason": "rate_limit",
            }
        },
        now=now,
        available_providers={"gemini": True, "openai": True},
    )

    assert [candidate.provider for candidate in candidates] == ["openai"]


def test_default_max_allocation_pct_is_30() -> None:
    assert DEFAULT_MAX_ALLOCATION_PCT == 30.0
