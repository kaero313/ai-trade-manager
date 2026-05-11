import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx

from app.api.routes import news as news_route
from app.services.ai.provider_router import resolve_provider_candidates
from app.services.rag import ingestion as rag_ingestion
from app.services.rag.opensearch_client import (
    EMBEDDING_DIMENSION,
    INGESTION_RUNS_INDEX_NAME,
    KNN_ENGINE,
    KNN_SPACE_TYPE,
    INGESTION_RUNS_INDEX_BODY,
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
    assert properties["content_source"]["type"] == "keyword"
    assert properties["crawl_status"]["type"] == "keyword"
    assert properties["crawl_error"]["type"] == "keyword"
    assert properties["chunk_index"]["type"] == "integer"
    assert properties["chunk_count"]["type"] == "integer"
    assert properties["content_length"]["type"] == "integer"
    assert properties["chunk_text_length"]["type"] == "integer"
    assert properties["is_chunked"]["type"] == "boolean"


def test_ingestion_runs_index_tracks_source_health() -> None:
    properties = INGESTION_RUNS_INDEX_BODY["mappings"]["properties"]
    source_health = properties["source_health"]["properties"]

    assert INGESTION_RUNS_INDEX_NAME == "market_news_ingestion_runs"
    assert properties["run_id"]["type"] == "keyword"
    assert properties["status"]["type"] == "keyword"
    assert properties["stale_deleted"]["type"] == "integer"
    assert properties["fallback_deleted"]["type"] == "integer"
    assert properties["expired_deleted"]["type"] == "integer"
    assert source_health["source"]["type"] == "keyword"
    assert source_health["status"]["type"] == "keyword"
    assert source_health["crawl_error_breakdown"]["type"] == "object"


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
    assert document.content_source == "rss_summary"
    assert document.crawl_status == "skipped"


def test_extract_article_body_from_html_prefers_article_text() -> None:
    article_text = " ".join(["Bitcoin market liquidity is improving."] * 40)
    nav_text = "Navigation text should be ignored."
    html = f"""
    <html>
      <head><meta property="og:description" content="Short market summary"></head>
      <body>
        <nav>{nav_text}</nav>
        <article><p>{article_text}</p></article>
      </body>
    </html>
    """

    extracted = rag_ingestion._extract_article_body_from_html(html)

    assert "Bitcoin market liquidity is improving." in extracted
    assert nav_text not in extracted


def test_extract_article_body_survives_ignored_void_tags() -> None:
    body_text = " ".join(["TokenPost article body keeps the useful market context."] * 30)
    html = f"""
    <html>
      <body>
        <header><img src="/logo.png"><span>Navigation</span></header>
        <div class="article_content" itemprop="articleBody">
          <p>{body_text}</p>
        </div>
      </body>
    </html>
    """

    extracted = rag_ingestion._extract_article_body_from_html(html)

    assert "TokenPost article body keeps the useful market context." in extracted
    assert "Navigation" not in extracted
    assert len(extracted) > 500


def test_rss_article_crawl_replaces_summary_with_body() -> None:
    body_text = " ".join(["Institutional Bitcoin demand expanded in Asian trading."] * 35)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.com/news/body"
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=f"<html><body><main><p>{body_text}</p></main></body></html>",
        )

    document = rag_ingestion.RawNewsDocument(
        title="BTC body test",
        content="Short RSS summary.",
        published_at=datetime(2026, 5, 6, 3, 0, tzinfo=UTC),
        source="rss:example.com",
        link="https://example.com/news/body",
        content_source="rss_summary",
        crawl_status="skipped",
    )

    async def run() -> tuple[list[rag_ingestion.RawNewsDocument], dict[str, int]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await rag_ingestion._enrich_rss_documents_with_crawl(client, [document])

    enriched, stats = asyncio.run(run())

    assert enriched[0].content == rag_ingestion._clean_text(body_text)
    assert enriched[0].content_source == "crawled_body"
    assert enriched[0].crawl_status == "success"
    assert enriched[0].crawl_error is None
    assert stats["crawled"] == 1
    assert stats["rss_summary_used"] == 0


def test_rss_article_crawl_falls_back_for_non_html_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"title": "not html"},
        )

    document = rag_ingestion.RawNewsDocument(
        title="BTC non html test",
        content="RSS summary remains available.",
        published_at=datetime(2026, 5, 6, 3, 0, tzinfo=UTC),
        source="rss:example.com",
        link="https://example.com/news/json",
        content_source="rss_summary",
        crawl_status="skipped",
    )

    async def run() -> tuple[list[rag_ingestion.RawNewsDocument], dict[str, int]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await rag_ingestion._enrich_rss_documents_with_crawl(client, [document])

    enriched, stats = asyncio.run(run())

    assert enriched[0].content == "RSS summary remains available."
    assert enriched[0].content_source == "rss_summary"
    assert enriched[0].crawl_status == "failed"
    assert enriched[0].crawl_error == "non_html"
    assert stats["crawl_failed"] == 1
    assert stats["rss_summary_used"] == 1


def test_rss_article_crawl_falls_back_for_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    document = rag_ingestion.RawNewsDocument(
        title="BTC timeout test",
        content="RSS summary after timeout.",
        published_at=datetime(2026, 5, 6, 3, 0, tzinfo=UTC),
        source="rss:example.com",
        link="https://example.com/news/timeout",
        content_source="rss_summary",
        crawl_status="skipped",
    )

    async def run() -> tuple[list[rag_ingestion.RawNewsDocument], dict[str, int]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await rag_ingestion._enrich_rss_documents_with_crawl(client, [document])

    enriched, stats = asyncio.run(run())

    assert enriched[0].content == "RSS summary after timeout."
    assert enriched[0].crawl_status == "failed"
    assert enriched[0].crawl_error == "timeout"
    assert stats["crawl_failed"] == 1


def test_short_crawled_body_keeps_rss_summary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body><article><p>Too short.</p></article></body></html>",
        )

    document = rag_ingestion.RawNewsDocument(
        title="BTC short body test",
        content="RSS summary after short body.",
        published_at=datetime(2026, 5, 6, 3, 0, tzinfo=UTC),
        source="rss:example.com",
        link="https://example.com/news/short-body",
        content_source="rss_summary",
        crawl_status="skipped",
    )

    async def run() -> tuple[list[rag_ingestion.RawNewsDocument], dict[str, int]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await rag_ingestion._enrich_rss_documents_with_crawl(client, [document])

    enriched, stats = asyncio.run(run())

    assert enriched[0].content == "RSS summary after short body."
    assert enriched[0].crawl_status == "failed"
    assert enriched[0].crawl_error == "short_body"
    assert stats["rss_summary_used"] == 1


def test_google_news_rss_document_skips_article_crawl() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500)

    document = rag_ingestion.RawNewsDocument(
        title="Google News aggregated story",
        content="RSS summary remains the usable fallback.",
        published_at=datetime(2026, 5, 6, 3, 0, tzinfo=UTC),
        source="rss:news.google.com",
        link="https://news.google.com/rss/articles/example?oc=5",
        content_source="rss_summary",
        crawl_status="skipped",
    )

    async def run() -> tuple[list[rag_ingestion.RawNewsDocument], dict[str, int]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await rag_ingestion._enrich_rss_documents_with_crawl(client, [document])

    enriched, stats = asyncio.run(run())

    assert calls == []
    assert enriched[0].content == "RSS summary remains the usable fallback."
    assert enriched[0].crawl_status == "skipped"
    assert enriched[0].crawl_error == "google_news_aggregator"
    assert stats["crawl_skipped"] == 1
    assert stats["rss_summary_used"] == 1


def test_rss_fetch_records_http_404_source_health(monkeypatch) -> None:
    monkeypatch.setattr(rag_ingestion, "RSS_FEED_URLS", ["https://example.com/rss"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    async def run() -> tuple[list[rag_ingestion.RawNewsDocument], list[rag_ingestion.SourceHealth]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await rag_ingestion._fetch_rss_news(client)

    documents, source_health = asyncio.run(run())

    assert documents == []
    assert len(source_health) == 1
    assert source_health[0].source == "rss:example.com"
    assert source_health[0].status == "failed"
    assert source_health[0].error == "http_404"
    assert source_health[0].fetched == 0


def test_rss_fetch_records_parse_warning_with_entries(monkeypatch) -> None:
    monkeypatch.setattr(rag_ingestion, "RSS_FEED_URLS", ["https://example.com/rss"])
    monkeypatch.setattr(
        rag_ingestion.feedparser,
        "parse",
        lambda _: SimpleNamespace(
            bozo=True,
            entries=[
                {
                    "title": "BTC parse warning",
                    "summary": "RSS summary",
                    "link": "https://example.com/news/1",
                    "published": "Wed, 06 May 2026 03:00:00 GMT",
                }
            ],
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<rss></rss>", request=request)

    async def run() -> tuple[list[rag_ingestion.RawNewsDocument], list[rag_ingestion.SourceHealth]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await rag_ingestion._fetch_rss_news(client)

    documents, source_health = asyncio.run(run())

    assert len(documents) == 1
    assert source_health[0].status == "partial"
    assert source_health[0].parse_warning is True
    assert source_health[0].fetched == 1


def test_api_and_dummy_documents_are_not_crawlable() -> None:
    api_document = rag_ingestion.RawNewsDocument(
        title="API news",
        content="API supplied description.",
        published_at=datetime(2026, 5, 6, 3, 0, tzinfo=UTC),
        source="cryptopanic",
        link="https://example.com/api-news",
    )
    dummy_document = rag_ingestion._dummy_news_documents("naver")[0]

    assert not rag_ingestion._is_crawlable_rss_document(api_document)
    assert not rag_ingestion._is_crawlable_rss_document(dummy_document)


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
    assert payload["content_source"] == "api"
    assert payload["crawl_status"] == "not_applicable"
    assert payload["crawl_error"] is None
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


def test_generate_embeddings_closes_gemini_client(monkeypatch) -> None:
    monkeypatch.setattr(rag_ingestion.settings, "GEMINI_API_KEY", "test-key")
    analyzers: list[object] = []

    class FakeAnalyzer:
        def __init__(self) -> None:
            self.closed = False
            analyzers.append(self)

        async def generate_embeddings(self, texts: list[str], *, task_type: str) -> list[list[float]]:
            assert task_type == "RETRIEVAL_DOCUMENT"
            return [[0.1] * EMBEDDING_DIMENSION for _ in texts]

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(rag_ingestion, "GeminiAnalyzer", FakeAnalyzer)
    document = rag_ingestion.RawNewsDocument(
        title="Embedding close test",
        content="Embedding content",
        published_at=datetime(2026, 5, 6, 3, 0, tzinfo=UTC),
        source="rss:tokenpost.kr",
        link="https://example.com/news/embedding-close",
    )
    chunks = rag_ingestion._build_document_chunks(document)

    embeddings = asyncio.run(rag_ingestion._generate_embeddings(chunks))

    assert embeddings
    assert getattr(analyzers[0], "closed") is True


def test_stale_delete_targets_only_sources_with_current_parents(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeOpenSearchClient:
        async def delete_by_query(self, **kwargs) -> dict:
            calls.append(kwargs)
            return {"deleted": 2}

    monkeypatch.setattr(rag_ingestion, "get_opensearch_client", lambda: FakeOpenSearchClient())

    deleted = asyncio.run(
        rag_ingestion._delete_stale_source_documents(
            {
                "rss:tokenpost.kr": {"parent-a", "parent-b"},
                "rss:failed.example": set(),
            }
        )
    )

    assert deleted == 2
    assert len(calls) == 1
    assert calls[0]["index"] == "market_news"
    bool_query = calls[0]["body"]["query"]["bool"]
    assert bool_query["filter"] == [{"term": {"source": "rss:tokenpost.kr"}}]
    assert bool_query["must_not"] == [{"terms": {"parent_id": ["parent-a", "parent-b"]}}]


def test_fallback_delete_uses_dummy_and_fallback_markers(monkeypatch) -> None:
    calls: list[dict] = []

    class FakeOpenSearchClient:
        async def delete_by_query(self, **kwargs) -> dict:
            calls.append(kwargs)
            return {"deleted": 3}

    monkeypatch.setattr(rag_ingestion, "get_opensearch_client", lambda: FakeOpenSearchClient())

    deleted = asyncio.run(rag_ingestion._delete_fallback_documents())

    assert deleted == 3
    assert calls[0]["body"]["query"]["bool"]["minimum_should_match"] == 1
    assert {"wildcard": {"link": "dummy://*"}} in calls[0]["body"]["query"]["bool"]["should"]


def test_rag_status_response_counts_real_fallback_and_embedding_documents() -> None:
    class FakeIndices:
        async def exists(self, index: str) -> bool:
            assert index in {"market_news", INGESTION_RUNS_INDEX_NAME}
            return True

    class FakeOpenSearchClient:
        indices = FakeIndices()

        async def search(self, index: str, body: dict) -> dict:
            if index == INGESTION_RUNS_INDEX_NAME:
                assert body["size"] == 1
                return {
                    "hits": {
                        "hits": [
                            {
                                "_source": {
                                    "run_id": "run-1",
                                    "status": "partial",
                                    "fetched": 4,
                                    "indexed": 4,
                                    "source_health": [
                                        {
                                            "source": "rss:tokenpost.kr",
                                            "status": "partial",
                                            "error": None,
                                            "fetched": 3,
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                }

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
                    "crawled_parent_documents": {
                        "doc_count": 2,
                        "parents": {"value": 1},
                    },
                    "rss_summary_parent_documents": {
                        "doc_count": 1,
                        "parents": {"value": 1},
                    },
                    "crawl_failed_parent_documents": {
                        "doc_count": 1,
                        "parents": {"value": 1},
                    },
                    "crawl_skipped_parent_documents": {
                        "doc_count": 1,
                        "parents": {"value": 1},
                    },
                    "avg_content_length": {"value": 1350.5},
                    "avg_chunk_text_length": {"value": 675.25},
                    "latest_published_at": {"value": 1778025600000},
                    "source_breakdown": {
                        "buckets": [
                            {"key": "rss:tokenpost.kr", "doc_count": 3},
                            {"key": "naver", "doc_count": 1},
                        ]
                    },
                    "content_source_breakdown": {
                        "buckets": [
                            {"key": "crawled_body", "doc_count": 2},
                            {"key": "rss_summary", "doc_count": 1},
                            {"key": "fallback", "doc_count": 1},
                        ]
                    },
                    "crawl_status_breakdown": {
                        "buckets": [
                            {"key": "success", "doc_count": 2},
                            {"key": "failed", "doc_count": 1},
                            {"key": "not_applicable", "doc_count": 1},
                        ]
                    },
                    "crawl_error_breakdown": {
                        "buckets": [
                            {"key": "short_body", "doc_count": 2},
                            {"key": "google_news_aggregator", "doc_count": 1},
                        ]
                    },
                    "crawl_error_by_source": {
                        "buckets": [
                            {
                                "key": "rss:tokenpost.kr",
                                "errors": {
                                    "buckets": [
                                        {"key": "short_body", "doc_count": 2},
                                    ]
                                },
                            },
                            {
                                "key": "rss:news.google.com",
                                "errors": {
                                    "buckets": [
                                        {"key": "google_news_aggregator", "doc_count": 1},
                                    ]
                                },
                            },
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
    assert response.crawled_parent_documents == 1
    assert response.rss_summary_parent_documents == 1
    assert response.crawl_failed_parent_documents == 1
    assert response.crawl_skipped_parent_documents == 1
    assert response.avg_content_length == 1350.5
    assert response.avg_chunk_text_length == 675.25
    assert response.real_documents == 3
    assert response.fallback_documents == 1
    assert response.embedded_documents == 2
    assert response.missing_embedding_documents == 2
    assert response.latest_published_at == "2026-05-06T00:00:00+00:00"
    assert response.source_breakdown == {"rss:tokenpost.kr": 3, "naver": 1}
    assert response.content_source_breakdown == {
        "crawled_body": 2,
        "rss_summary": 1,
        "fallback": 1,
    }
    assert response.crawl_status_breakdown == {
        "success": 2,
        "failed": 1,
        "not_applicable": 1,
    }
    assert response.crawl_error_breakdown == {
        "short_body": 2,
        "google_news_aggregator": 1,
    }
    assert response.crawl_error_by_source == {
        "rss:tokenpost.kr": {"short_body": 2},
        "rss:news.google.com": {"google_news_aggregator": 1},
    }
    assert response.latest_ingestion is not None
    assert response.latest_ingestion["run_id"] == "run-1"
    assert response.latest_ingestion["source_health"][0]["source"] == "rss:tokenpost.kr"


def test_rag_status_keeps_response_when_ingestion_run_index_is_unavailable() -> None:
    class FakeIndices:
        async def exists(self, index: str) -> bool:
            if index == INGESTION_RUNS_INDEX_NAME:
                raise RuntimeError("run index unavailable")
            assert index == "market_news"
            return True

    class FakeOpenSearchClient:
        indices = FakeIndices()

        async def search(self, index: str, body: dict) -> dict:
            assert index == "market_news"
            return {
                "hits": {"total": {"value": 1}},
                "aggregations": {
                    "fallback_documents": {"doc_count": 0},
                    "embedded_documents": {"doc_count": 1},
                    "missing_embedding_documents": {"doc_count": 0},
                    "parent_documents": {"value": 1},
                    "chunk_documents": {"doc_count": 1},
                },
            }

    response = asyncio.run(news_route._build_rag_status_response(FakeOpenSearchClient()))

    assert response.status == "healthy"
    assert response.latest_ingestion is None


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
