import asyncio
from datetime import UTC, datetime, timedelta

from app.api.routes import news as news_route
from app.services.ai.provider_router import resolve_provider_candidates
from app.services.rag import ingestion as rag_ingestion
from app.services.rag.opensearch_client import (
    EMBEDDING_DIMENSION,
    KNN_ENGINE,
    KNN_SPACE_TYPE,
    MARKET_NEWS_INDEX_BODY,
    _has_expected_chunk_mapping,
    _is_expected_embedding_mapping,
)
from app.services.trading import ai_analyst
from app.services.trading.ai_executor import DEFAULT_MAX_ALLOCATION_PCT


def test_market_news_index_uses_opensearch_3_lucene_knn() -> None:
    properties = MARKET_NEWS_INDEX_BODY["mappings"]["properties"]
    embedding = properties["embedding"]

    assert embedding["type"] == "knn_vector"
    assert embedding["dimension"] == 1536
    assert embedding["method"]["name"] == "hnsw"
    assert embedding["method"]["engine"] == "lucene"
    assert embedding["method"]["space_type"] == "cosinesimil"
    assert EMBEDDING_DIMENSION == 1536
    assert KNN_ENGINE == "lucene"
    assert KNN_SPACE_TYPE == "cosinesimil"
    assert properties["parent_id"]["type"] == "keyword"
    assert properties["chunk_index"]["type"] == "integer"
    assert properties["chunk_count"]["type"] == "integer"
    assert properties["content_length"]["type"] == "integer"
    assert properties["chunk_text_length"]["type"] == "integer"
    assert properties["is_chunked"]["type"] == "boolean"


def test_rss_entry_to_document_normalizes_real_news() -> None:
    document = rag_ingestion._rss_entry_to_document(
        "https://www.tokenpost.kr/rss",
        {
            "title": "<b>비트코인</b> 반등",
            "summary": "<p>거래량이 증가했습니다.</p>",
            "link": "https://example.com/news/1",
            "published": "Wed, 06 May 2026 03:00:00 GMT",
        },
    )

    assert document is not None
    assert document.title == "비트코인 반등"
    assert document.content == "거래량이 증가했습니다."
    assert document.link == "https://example.com/news/1"
    assert document.source == "rss:tokenpost.kr"
    assert document.published_at == datetime(2026, 5, 6, 3, 0, tzinfo=UTC)


def test_real_rss_documents_exclude_dummy_documents() -> None:
    dummy = rag_ingestion._dummy_news_documents("naver")[0]
    real = rag_ingestion.RawNewsDocument(
        title="실제 시장 뉴스",
        content="원화 마켓 거래대금이 증가했습니다.",
        published_at=datetime(2026, 5, 6, 3, 0, tzinfo=UTC),
        source="rss:tokenpost.kr",
        link="https://example.com/news/real",
    )

    assert rag_ingestion._prefer_real_documents([dummy, real]) == [real]
    assert rag_ingestion._prefer_real_documents([dummy]) == [dummy]


def test_short_news_document_builds_single_chunk() -> None:
    document = rag_ingestion.RawNewsDocument(
        title="BTC market update",
        content="Short RSS summary for a single chunk.",
        published_at=datetime(2026, 5, 6, 3, 0, tzinfo=UTC),
        source="rss:example.com",
        link="https://example.com/news/short",
    )

    chunks = rag_ingestion._build_document_chunks(document)

    assert len(chunks) == 1
    assert chunks[0].parent_id == rag_ingestion._build_document_id(document)
    assert rag_ingestion._build_chunk_id(chunks[0]) == f"{chunks[0].parent_id}:0"
    assert chunks[0].chunk_index == 0
    assert chunks[0].chunk_count == 1
    assert chunks[0].content_length == len(document.content)
    assert chunks[0].chunk_text_length == len(document.content)
    assert chunks[0].is_chunked is False


def test_long_news_document_builds_overlapped_chunks() -> None:
    content = "".join(f"{index:04d}" for index in range(500))
    document = rag_ingestion.RawNewsDocument(
        title="Long market analysis",
        content=content,
        published_at=datetime(2026, 5, 6, 3, 0, tzinfo=UTC),
        source="rss:example.com",
        link="https://example.com/news/long",
    )

    chunks = rag_ingestion._build_document_chunks(document)

    assert len(chunks) > 1
    assert all(chunk.chunk_count == len(chunks) for chunk in chunks)
    assert all(chunk.content_length == len(content) for chunk in chunks)
    assert all(chunk.is_chunked for chunk in chunks)
    assert len(chunks[0].content) == rag_ingestion.CHUNK_MAX_CHARS
    assert chunks[0].content[-rag_ingestion.CHUNK_OVERLAP_CHARS :] == chunks[1].content[
        : rag_ingestion.CHUNK_OVERLAP_CHARS
    ]


def test_chunk_serialization_includes_chunk_metadata() -> None:
    document = rag_ingestion.RawNewsDocument(
        title="Serialized market update",
        content="Serialization test content.",
        published_at=datetime(2026, 5, 6, 3, 0, tzinfo=UTC),
        source="rss:example.com",
        link="https://example.com/news/serialize",
    )
    chunk = rag_ingestion._build_document_chunks(document)[0]

    payload = rag_ingestion._serialize_chunk(chunk, [0.1] * EMBEDDING_DIMENSION)

    assert payload["parent_id"] == chunk.parent_id
    assert payload["chunk_index"] == 0
    assert payload["chunk_count"] == 1
    assert payload["content_length"] == len(document.content)
    assert payload["chunk_text_length"] == len(document.content)
    assert payload["is_chunked"] is False
    assert len(payload["embedding"]) == EMBEDDING_DIMENSION


def test_generate_embeddings_returns_empty_without_gemini_key(monkeypatch) -> None:
    monkeypatch.setattr(rag_ingestion.settings, "GEMINI_API_KEY", None)
    document = rag_ingestion.RawNewsDocument(
        title="실제 시장 뉴스",
        content="임베딩 키가 없어도 문서 저장은 가능해야 합니다.",
        published_at=datetime(2026, 5, 6, 3, 0, tzinfo=UTC),
        source="rss:tokenpost.kr",
        link="https://example.com/news/no-embedding",
    )

    chunks = rag_ingestion._build_document_chunks(document)

    assert asyncio.run(rag_ingestion._generate_embeddings(chunks)) == {}


def test_rag_status_response_counts_real_fallback_and_embedding_documents() -> None:
    class FakeIndices:
        async def exists(self, index: str) -> bool:
            assert index == "market_news"
            return True

    class FakeOpenSearchClient:
        indices = FakeIndices()

        async def search(self, index: str, body: dict) -> dict:
            assert index == "market_news"
            assert body["size"] == 0
            return {
                "hits": {"total": {"value": 4}},
                "aggregations": {
                    "fallback_documents": {"doc_count": 1},
                    "embedded_documents": {"doc_count": 2},
                    "missing_embedding_documents": {"doc_count": 2},
                    "parent_documents": {"value": 3},
                    "chunk_documents": {"doc_count": 4},
                    "chunked_parent_documents": {
                        "doc_count": 2,
                        "parents": {"value": 1},
                    },
                    "latest_published_at": {"value": 1778025600000},
                    "source_breakdown": {
                        "buckets": [
                            {"key": "rss:tokenpost.kr", "doc_count": 3},
                            {"key": "naver", "doc_count": 1},
                        ]
                    },
                },
            }

    response = asyncio.run(news_route._build_rag_status_response(FakeOpenSearchClient()))

    assert response.status == "degraded"
    assert response.index_exists is True
    assert response.total_documents == 4
    assert response.parent_documents == 3
    assert response.chunk_documents == 4
    assert response.chunked_parent_documents == 1
    assert response.avg_chunks_per_parent == 1.3333
    assert response.real_documents == 3
    assert response.fallback_documents == 1
    assert response.embedded_documents == 2
    assert response.missing_embedding_documents == 2
    assert response.latest_published_at == "2026-05-06T00:00:00+00:00"
    assert response.source_breakdown == {"rss:tokenpost.kr": 3, "naver": 1}


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


def test_chunk_mapping_validation_rejects_legacy_mapping() -> None:
    legacy_mapping = {
        "market_news": {
            "mappings": {
                "properties": {
                    "embedding": MARKET_NEWS_INDEX_BODY["mappings"]["properties"]["embedding"],
                }
            }
        }
    }

    assert not _has_expected_chunk_mapping(legacy_mapping)


def test_hybrid_news_merge_deduplicates_parent_and_excludes_fallback() -> None:
    published_at = datetime(2026, 5, 7, 0, 0, tzinfo=UTC).isoformat()
    vector_items = [
        {
            "parent_id": "parent-a",
            "title": "Vector chunk",
            "content": "Vector semantic match",
            "link": "https://example.com/a",
            "published_at": published_at,
            "search_score": 0.9,
        },
        {
            "parent_id": "parent-b",
            "title": "Vector only",
            "content": "Secondary semantic match",
            "link": "https://example.com/b",
            "published_at": published_at,
            "search_score": 0.4,
        },
        {
            "parent_id": "fallback",
            "title": "Fallback item",
            "content": "Fallback generated because credentials are unavailable",
            "link": "dummy://fallback",
            "published_at": published_at,
            "search_score": 1.0,
        },
    ]
    keyword_items = [
        {
            "parent_id": "parent-a",
            "title": "Keyword chunk",
            "content": "Keyword exact match",
            "link": "https://example.com/a",
            "published_at": published_at,
            "search_score": 12.0,
        },
        {
            "parent_id": "parent-c",
            "title": "Keyword only",
            "content": "BM25 match",
            "link": "https://example.com/c",
            "published_at": published_at,
            "search_score": 6.0,
        },
    ]

    merged = ai_analyst._merge_hybrid_news_results(vector_items, keyword_items, limit=3)

    parent_ids = [item["parent_id"] for item in merged]
    assert len(merged) == 3
    assert parent_ids.count("parent-a") == 1
    assert "fallback" not in parent_ids
    assert all("hybrid_score" in item for item in merged)


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
