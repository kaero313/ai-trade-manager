from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import feedparser
import httpx
from opensearchpy.helpers import async_bulk

from app.core.config import settings
from app.services.news_scraper import RSS_FEED_URLS
from app.services.ai.providers.gemini import AIProviderRateLimitError, GeminiAnalyzer
from app.services.rag.opensearch_client import (
    EMBEDDING_DIMENSION,
    INGESTION_RUNS_INDEX_NAME,
    INDEX_NAME,
    ensure_market_news_index_for_ingestion,
    ensure_market_news_ingestion_runs_index,
    get_opensearch_client,
)

logger = logging.getLogger(__name__)

CRYPTO_PANIC_ENDPOINT = "https://cryptopanic.com/api/v1/posts/"
NAVER_NEWS_ENDPOINT = "https://openapi.naver.com/v1/search/news.json"
CRYPTO_PANIC_FETCH_LIMIT = 10
NAVER_FETCH_LIMIT = 10
MARKET_NEWS_TTL_DAYS = 28
INGESTION_RUN_TTL_DAYS = 14
EMBEDDING_MODEL = "gemini-embedding-001"
GEMINI_EMBEDDING_BATCH_SIZE = 100
EMBEDDING_STATUS_EMBEDDED = "embedded"
EMBEDDING_STATUS_MISSING = "missing"
EMBEDDING_STATUS_RATE_LIMITED = "rate_limited"
EMBEDDING_STATUS_FAILED = "failed"
EMBEDDING_ERROR_CREDENTIALS_MISSING = "credentials_missing"
EMBEDDING_ERROR_RATE_LIMITED = "rate_limited"
EMBEDDING_ERROR_GENERATION_FAILED = "generation_failed"
EMBEDDING_ERROR_INVALID_DIMENSION = "invalid_dimension"
NEWS_HTTP_TIMEOUT = 10.0
RSS_FETCH_LIMIT_PER_FEED = 8
RSS_FETCH_LIMIT_TOTAL = 32
RSS_ARTICLE_CRAWL_CONCURRENCY = 4
CRAWLED_BODY_MIN_CHARS = 500
CRAWLED_BODY_MIN_GAIN_CHARS = 200
SINGLE_CHUNK_MAX_CHARS = 1200
CHUNK_MAX_CHARS = 900
CHUNK_OVERLAP_CHARS = 120
NAVER_NEWS_QUERIES = (
    "\ube44\ud2b8\ucf54\uc778",
    "\uc5c5\ube44\ud2b8",
    "\uac00\uc0c1\uc790\uc0b0",
)


@dataclass(slots=True)
class RawNewsDocument:
    title: str
    content: str
    published_at: datetime
    source: str
    link: str
    content_source: str = "api"
    crawl_status: str = "not_applicable"
    crawl_error: str | None = None


@dataclass(slots=True)
class RawNewsChunk:
    parent_id: str
    title: str
    content: str
    published_at: datetime
    source: str
    link: str
    content_source: str
    crawl_status: str
    crawl_error: str | None
    chunk_index: int
    chunk_count: int
    content_length: int
    chunk_text_length: int
    is_chunked: bool


@dataclass(slots=True)
class ChunkEmbeddingResult:
    status: str
    error: str | None = None
    embedding: list[float] | None = None
    model: str | None = None
    generated_at: datetime | None = None


@dataclass(slots=True)
class EmbeddingGenerationResult:
    chunks: dict[str, ChunkEmbeddingResult] = field(default_factory=dict)
    requested: int = 0
    succeeded: int = 0
    missing: int = 0
    failed: int = 0
    error: str | None = None


@dataclass(slots=True)
class SourceHealth:
    source: str
    type: str
    enabled: bool
    status: str = "success"
    fetched: int = 0
    error: str | None = None
    parse_warning: bool = False
    crawled: int = 0
    crawl_failed: int = 0
    crawl_skipped: int = 0
    rss_summary_used: int = 0
    crawl_error_breakdown: dict[str, int] = field(default_factory=dict)


def _serialize_source_health(health: SourceHealth) -> dict[str, Any]:
    return {
        "source": health.source,
        "type": health.type,
        "enabled": health.enabled,
        "status": health.status,
        "fetched": health.fetched,
        "error": health.error,
        "parse_warning": health.parse_warning,
        "crawled": health.crawled,
        "crawl_failed": health.crawl_failed,
        "crawl_skipped": health.crawl_skipped,
        "rss_summary_used": health.rss_summary_used,
        "crawl_error_breakdown": dict(health.crawl_error_breakdown),
    }


def _clean_text(raw: Any) -> str:
    text = str(raw or "")
    text = unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


class _ArticleBodyExtractor(HTMLParser):
    _IGNORED_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form"}
    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_stack: list[str] = []
        self._container_stack: list[str] = []
        self._article_body_parts: list[str] = []
        self._article_parts: list[str] = []
        self._main_parts: list[str] = []
        self._paragraphs: list[str] = []
        self._current_paragraph: list[str] | None = None
        self._meta_descriptions: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        attrs_by_name = {name.lower(): str(value or "") for name, value in attrs}

        if tag_name == "meta":
            meta_name = (
                attrs_by_name.get("property")
                or attrs_by_name.get("name")
                or ""
            ).strip().lower()
            if meta_name in {"og:description", "description", "twitter:description"}:
                content = _clean_text(attrs_by_name.get("content"))
                if content:
                    self._meta_descriptions.append(content)

        if self._ignored_stack or tag_name in self._IGNORED_TAGS:
            if tag_name not in self._VOID_TAGS:
                self._ignored_stack.append(tag_name)
            return

        class_names = set(attrs_by_name.get("class", "").split())
        itemprop = attrs_by_name.get("itemprop", "").strip().lower()
        if (
            itemprop == "articlebody"
            or "article_content" in class_names
            or "article-body" in class_names
        ):
            self._container_stack.append("article_body")

        if tag_name in {"article", "main"}:
            self._container_stack.append(tag_name)
        elif tag_name == "p":
            self._current_paragraph = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if self._ignored_stack:
            if tag_name == self._ignored_stack[-1]:
                self._ignored_stack.pop()
            return

        if tag_name == "p" and self._current_paragraph is not None:
            paragraph = _clean_text(" ".join(self._current_paragraph))
            if paragraph:
                self._paragraphs.append(paragraph)
            self._current_paragraph = None
            return

        if tag_name in {"article", "main"}:
            for index in range(len(self._container_stack) - 1, -1, -1):
                if self._container_stack[index] == tag_name:
                    del self._container_stack[index]
                    break
            return

        if "article_body" in self._container_stack and tag_name in {"div", "section"}:
            for index in range(len(self._container_stack) - 1, -1, -1):
                if self._container_stack[index] == "article_body":
                    del self._container_stack[index]
                    break

    def handle_data(self, data: str) -> None:
        if self._ignored_stack:
            return

        text = str(data or "").strip()
        if not text:
            return

        if "article_body" in self._container_stack:
            self._article_body_parts.append(text)
        if "article" in self._container_stack:
            self._article_parts.append(text)
        if "main" in self._container_stack:
            self._main_parts.append(text)
        if self._current_paragraph is not None:
            self._current_paragraph.append(text)

    def extract_best(self) -> str:
        candidates = [
            " ".join(self._article_body_parts),
            " ".join(self._article_parts),
            " ".join(self._main_parts),
            " ".join(self._paragraphs),
            " ".join(self._meta_descriptions),
        ]
        normalized_candidates = [_clean_text(candidate) for candidate in candidates]
        normalized_candidates = [candidate for candidate in normalized_candidates if candidate]
        if not normalized_candidates:
            return ""
        return max(normalized_candidates, key=len)


def _extract_article_body_from_html(html: str) -> str:
    extractor = _ArticleBodyExtractor()
    try:
        extractor.feed(str(html or ""))
        extractor.close()
    except Exception:
        logger.debug("Article HTML parsing failed.", exc_info=True)
        return ""
    return extractor.extract_best()


def _parse_datetime(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=UTC)
        return raw.astimezone(UTC)

    if not raw:
        return datetime.now(UTC)

    text = str(raw).strip()
    if not text:
        return datetime.now(UTC)

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        pass

    try:
        return parsedate_to_datetime(text).astimezone(UTC)
    except (TypeError, ValueError, IndexError, OverflowError):
        return datetime.now(UTC)


def _parse_feed_datetime(entry: Any) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        raw = entry.get(key) if hasattr(entry, "get") else None
        if raw:
            try:
                return datetime(*raw[:6], tzinfo=UTC)
            except (TypeError, ValueError, IndexError, OverflowError):
                continue

    for key in ("published", "updated", "created"):
        raw = entry.get(key) if hasattr(entry, "get") else None
        if raw:
            return _parse_datetime(raw)

    return datetime.now(UTC)


def _build_document_id(document: RawNewsDocument) -> str:
    published_key = document.published_at.isoformat()
    unique_key = document.link or document.title
    return hashlib.sha256(f"{document.source}|{unique_key}|{published_key}".encode("utf-8")).hexdigest()


def _build_chunk_id(chunk: RawNewsChunk) -> str:
    return f"{chunk.parent_id}:{chunk.chunk_index}"


def _serialize_chunk(
    chunk: RawNewsChunk,
    embedding_result: ChunkEmbeddingResult | None = None,
) -> dict[str, Any]:
    embedding_state = embedding_result or ChunkEmbeddingResult(status=EMBEDDING_STATUS_MISSING)
    payload: dict[str, Any] = {
        "title": chunk.title,
        "content": chunk.content,
        "source": chunk.source,
        "link": chunk.link,
        "published_at": chunk.published_at.isoformat(),
        "parent_id": chunk.parent_id,
        "content_source": chunk.content_source,
        "crawl_status": chunk.crawl_status,
        "crawl_error": chunk.crawl_error,
        "chunk_index": chunk.chunk_index,
        "chunk_count": chunk.chunk_count,
        "content_length": chunk.content_length,
        "chunk_text_length": chunk.chunk_text_length,
        "is_chunked": chunk.is_chunked,
        "embedding_status": embedding_state.status,
        "embedding_error": embedding_state.error,
        "embedding_model": embedding_state.model,
        "embedding_generated_at": embedding_state.generated_at.isoformat()
        if embedding_state.generated_at
        else None,
    }
    if embedding_state.embedding:
        payload["embedding"] = embedding_state.embedding
    return payload


def _is_fallback_document(document: RawNewsDocument) -> bool:
    title = document.title.lower()
    content = document.content.lower()
    link = document.link.lower()
    combined = " ".join([title, content, link])
    if link.startswith("dummy://"):
        return True
    if "fallback" not in combined:
        return False
    return any(
        marker in combined
        for marker in (
            "credentials are unavailable",
            "credentials unavailable",
            "request failed",
            "generated to keep the rag ingestion pipeline alive",
        )
    )


def _prefer_real_documents(documents: list[RawNewsDocument]) -> list[RawNewsDocument]:
    real_documents = [document for document in documents if not _is_fallback_document(document)]
    if real_documents:
        return real_documents
    return documents


def _split_content_into_chunks(content: str) -> list[str]:
    normalized = str(content or "").strip()
    if not normalized:
        return []
    if len(normalized) <= SINGLE_CHUNK_MAX_CHARS:
        return [normalized]

    chunks: list[str] = []
    start = 0
    step = CHUNK_MAX_CHARS - CHUNK_OVERLAP_CHARS
    while start < len(normalized):
        end = min(start + CHUNK_MAX_CHARS, len(normalized))
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start += step
    return chunks


def _build_document_chunks(document: RawNewsDocument) -> list[RawNewsChunk]:
    content = document.content.strip() or document.title.strip()
    chunks = _split_content_into_chunks(content)
    if not chunks:
        chunks = [document.title.strip()]

    parent_id = _build_document_id(document)
    chunk_count = len(chunks)
    content_length = len(content)
    is_chunked = chunk_count > 1
    return [
        RawNewsChunk(
            parent_id=parent_id,
            title=document.title,
            content=chunk_text,
            published_at=document.published_at,
            source=document.source,
            link=document.link,
            content_source=document.content_source,
            crawl_status=document.crawl_status,
            crawl_error=document.crawl_error,
            chunk_index=index,
            chunk_count=chunk_count,
            content_length=content_length,
            chunk_text_length=len(chunk_text),
            is_chunked=is_chunked,
        )
        for index, chunk_text in enumerate(chunks)
    ]


def _build_news_chunks(documents: list[RawNewsDocument]) -> list[RawNewsChunk]:
    chunks: list[RawNewsChunk] = []
    for document in documents:
        chunks.extend(_build_document_chunks(document))
    return chunks


def _daily_dummy_published_at() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _dummy_news_documents(source: str) -> list[RawNewsDocument]:
    published_at = _daily_dummy_published_at()
    if source == "cryptopanic":
        return [
            RawNewsDocument(
                title="Global crypto market remains in wait-and-see mode",
                content="Fallback global market headline because CryptoPanic credentials are unavailable.",
                published_at=published_at,
                source=source,
                link="dummy://cryptopanic/global-market-wait-and-see",
                content_source="fallback",
            ),
            RawNewsDocument(
                title="Bitcoin volatility check fallback feed",
                content="Fallback global market headline because the CryptoPanic request failed.",
                published_at=published_at,
                source=source,
                link="dummy://cryptopanic/bitcoin-volatility-check",
                content_source="fallback",
            ),
            RawNewsDocument(
                title="Macro liquidity watch fallback update",
                content="Fallback global market headline generated to keep the RAG ingestion pipeline alive.",
                published_at=published_at,
                source=source,
                link="dummy://cryptopanic/macro-liquidity-watch",
                content_source="fallback",
            ),
        ]

    return [
        RawNewsDocument(
            title="KRW market fallback headline",
            content="Fallback local market headline because Naver credentials are unavailable.",
            published_at=published_at,
            source=source,
            link="dummy://naver/krw-market-standby",
            content_source="fallback",
        ),
        RawNewsDocument(
            title="Upbit volatility check fallback",
            content="Fallback local market headline because the Naver request failed.",
            published_at=published_at,
            source=source,
            link="dummy://naver/upbit-volatility-check",
            content_source="fallback",
        ),
        RawNewsDocument(
            title="Local crypto regulation watch fallback",
            content="Fallback local market headline generated to keep the RAG ingestion pipeline alive.",
            published_at=published_at,
            source=source,
            link="dummy://naver/local-crypto-monitoring",
            content_source="fallback",
        ),
    ]


def _rss_source_name(feed_url: str) -> str:
    parsed = urlparse(feed_url)
    host = parsed.netloc.lower().removeprefix("www.")
    return f"rss:{host or 'unknown'}"


def _rss_entry_to_document(feed_url: str, entry: Any) -> RawNewsDocument | None:
    if not hasattr(entry, "get"):
        return None

    title = _clean_text(entry.get("title"))
    content = _clean_text(
        entry.get("summary")
        or entry.get("description")
        or entry.get("subtitle")
        or title
    )
    link = _clean_text(entry.get("link"))
    if not title or not link:
        return None

    return RawNewsDocument(
        title=title,
        content=content or title,
        published_at=_parse_feed_datetime(entry),
        source=_rss_source_name(feed_url),
        link=link,
        content_source="rss_summary",
        crawl_status="skipped",
    )


def _is_crawlable_rss_document(document: RawNewsDocument) -> bool:
    if _is_fallback_document(document):
        return False
    if document.content_source != "rss_summary" or not document.source.startswith("rss:"):
        return False
    scheme = urlparse(document.link).scheme.lower()
    return scheme in {"http", "https"}


def _is_google_news_aggregator_document(document: RawNewsDocument) -> bool:
    parsed = urlparse(document.link)
    host = parsed.netloc.lower().removeprefix("www.")
    return document.source == "rss:news.google.com" or host == "news.google.com"


def _should_use_crawled_body(original_content: str, crawled_body: str) -> bool:
    normalized_original = _clean_text(original_content)
    normalized_body = _clean_text(crawled_body)
    if len(normalized_body) < CRAWLED_BODY_MIN_CHARS:
        return False
    return len(normalized_body) >= len(normalized_original) + CRAWLED_BODY_MIN_GAIN_CHARS


def _fetch_error_code(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"http_{exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return "request_failed"
    return "request_failed"


async def _crawl_rss_article_body(
    client: httpx.AsyncClient,
    document: RawNewsDocument,
) -> tuple[str | None, str | None]:
    try:
        response = await client.get(document.link)
        response.raise_for_status()
    except httpx.TimeoutException:
        return None, "timeout"
    except httpx.HTTPStatusError as exc:
        return None, f"http_{exc.response.status_code}"
    except httpx.RequestError:
        return None, "request_failed"
    except Exception:
        logger.debug("RSS article crawl failed unexpectedly: link=%s", document.link, exc_info=True)
        return None, "request_failed"

    content_type = str(response.headers.get("content-type") or "").lower()
    if content_type and "html" not in content_type:
        return None, "non_html"

    body = _extract_article_body_from_html(response.text)
    if not _should_use_crawled_body(document.content, body):
        return None, "short_body"
    return _clean_text(body), None


async def _enrich_rss_documents_with_crawl(
    client: httpx.AsyncClient,
    documents: list[RawNewsDocument],
) -> tuple[list[RawNewsDocument], dict[str, int]]:
    stats = {
        "crawled": 0,
        "crawl_failed": 0,
        "crawl_skipped": 0,
        "rss_summary_used": 0,
    }
    semaphore = asyncio.Semaphore(RSS_ARTICLE_CRAWL_CONCURRENCY)

    async def enrich(document: RawNewsDocument) -> RawNewsDocument:
        if _is_google_news_aggregator_document(document):
            document.crawl_status = "skipped"
            document.crawl_error = "google_news_aggregator"
            stats["crawl_skipped"] += 1
            stats["rss_summary_used"] += 1
            return document

        if not _is_crawlable_rss_document(document):
            document.crawl_status = "skipped"
            document.crawl_error = "not_crawlable"
            stats["crawl_skipped"] += 1
            stats["rss_summary_used"] += 1
            return document

        async with semaphore:
            body, error = await _crawl_rss_article_body(client, document)

        if body:
            document.content = body
            document.content_source = "crawled_body"
            document.crawl_status = "success"
            document.crawl_error = None
            stats["crawled"] += 1
            return document

        document.content_source = "rss_summary"
        document.crawl_status = "failed"
        document.crawl_error = error or "unknown"
        stats["crawl_failed"] += 1
        stats["rss_summary_used"] += 1
        return document

    enriched = await asyncio.gather(*(enrich(document) for document in documents))
    return list(enriched), stats


def _apply_crawl_health_to_sources(
    source_health: list[SourceHealth],
    documents: list[RawNewsDocument],
) -> None:
    documents_by_source: dict[str, list[RawNewsDocument]] = {}
    for document in documents:
        documents_by_source.setdefault(document.source, []).append(document)

    for health in source_health:
        source_documents = documents_by_source.get(health.source, [])
        if not source_documents:
            continue

        health.crawled = sum(1 for document in source_documents if document.crawl_status == "success")
        health.crawl_failed = sum(1 for document in source_documents if document.crawl_status == "failed")
        health.crawl_skipped = sum(1 for document in source_documents if document.crawl_status == "skipped")
        health.rss_summary_used = sum(
            1
            for document in source_documents
            if document.content_source == "rss_summary"
        )
        health.crawl_error_breakdown = dict(
            Counter(
                str(document.crawl_error)
                for document in source_documents
                if document.crawl_error
            )
        )
        if health.status == "success" and (health.parse_warning or health.crawl_failed > 0):
            health.status = "partial"


async def _fetch_rss_news(
    client: httpx.AsyncClient,
) -> tuple[list[RawNewsDocument], list[SourceHealth]]:
    documents: list[RawNewsDocument] = []
    source_health: list[SourceHealth] = []
    for feed_url in RSS_FEED_URLS:
        source_name = _rss_source_name(feed_url)
        health = SourceHealth(source=source_name, type="rss", enabled=True)
        source_health.append(health)

        try:
            response = await client.get(feed_url)
            response.raise_for_status()
            parsed = await asyncio.to_thread(feedparser.parse, response.content)
        except Exception as exc:
            health.status = "failed"
            health.error = _fetch_error_code(exc)
            logger.exception("RSS 뉴스 수집 실패: feed=%s", feed_url)
            continue

        if getattr(parsed, "bozo", False):
            health.parse_warning = True
            logger.warning("RSS 파싱 경고가 발생했습니다: feed=%s", feed_url)

        feed_documents: list[RawNewsDocument] = []
        entries = getattr(parsed, "entries", []) or []
        for entry in entries[:RSS_FETCH_LIMIT_PER_FEED]:
            document = _rss_entry_to_document(feed_url, entry)
            if document is not None:
                feed_documents.append(document)

        health.fetched = len(feed_documents)
        if feed_documents:
            health.status = "partial" if health.parse_warning else "success"
            documents.extend(feed_documents)
        else:
            health.status = "failed"
            health.error = "parse_warning" if health.parse_warning else "no_entries"

    deduplicated = _deduplicate_documents(documents)[:RSS_FETCH_LIMIT_TOTAL]
    included_sources = {document.source for document in deduplicated}
    for health in source_health:
        if health.source not in included_sources:
            health.fetched = 0
    return deduplicated, source_health


async def _fetch_cryptopanic_news(
    client: httpx.AsyncClient,
) -> tuple[list[RawNewsDocument], SourceHealth]:
    health = SourceHealth(
        source="cryptopanic",
        type="api",
        enabled=bool(settings.cryptopanic_api_key),
    )
    if not settings.cryptopanic_api_key:
        health.status = "skipped"
        health.error = "credentials_missing"
        logger.warning("CryptoPanic API key is missing. Falling back to dummy documents.")
        return _dummy_news_documents("cryptopanic"), health

    try:
        response = await client.get(
            CRYPTO_PANIC_ENDPOINT,
            params={
                "auth_token": settings.cryptopanic_api_key,
                "public": "true",
                "kind": "news",
            },
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        health.status = "failed"
        health.error = _fetch_error_code(exc)
        logger.exception("CryptoPanic fetch failed. Falling back to dummy documents.")
        return _dummy_news_documents("cryptopanic"), health

    results = payload.get("results") or []
    documents: list[RawNewsDocument] = []
    for item in results[:CRYPTO_PANIC_FETCH_LIMIT]:
        metadata = item.get("metadata") or {}
        title = _clean_text(item.get("title"))
        content = _clean_text(metadata.get("description") or item.get("body") or title)
        link = _clean_text(item.get("url") or "")
        if not title:
            continue
        documents.append(
            RawNewsDocument(
                title=title,
                content=content or title,
                published_at=_parse_datetime(item.get("published_at")),
                source="cryptopanic",
                link=link,
            )
        )

    health.fetched = len(documents)
    health.status = "success" if documents else "failed"
    health.error = None if documents else "no_results"
    return documents, health


async def _fetch_naver_news(
    client: httpx.AsyncClient,
) -> tuple[list[RawNewsDocument], SourceHealth]:
    health = SourceHealth(
        source="naver",
        type="api",
        enabled=bool(settings.naver_client_id and settings.naver_client_secret),
    )
    if not settings.naver_client_id or not settings.naver_client_secret:
        health.status = "skipped"
        health.error = "credentials_missing"
        logger.warning("Naver API credentials are missing. Falling back to dummy documents.")
        return _dummy_news_documents("naver"), health

    documents: list[RawNewsDocument] = []
    errors: list[str] = []
    headers = {
        "X-Naver-Client-Id": settings.naver_client_id,
        "X-Naver-Client-Secret": settings.naver_client_secret,
    }

    for query in NAVER_NEWS_QUERIES:
        try:
            response = await client.get(
                NAVER_NEWS_ENDPOINT,
                headers=headers,
                params={
                    "query": query,
                    "display": NAVER_FETCH_LIMIT,
                    "sort": "date",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            errors.append(_fetch_error_code(exc))
            logger.exception("Naver news fetch failed for query=%s", query)
            continue

        for item in payload.get("items") or []:
            title = _clean_text(item.get("title"))
            description = _clean_text(item.get("description"))
            link = _clean_text(item.get("originallink") or item.get("link"))
            if not title:
                continue
            documents.append(
                RawNewsDocument(
                    title=title,
                    content=description or title,
                    published_at=_parse_datetime(item.get("pubDate")),
                    source="naver",
                    link=link,
                )
            )

    health.fetched = len(documents)
    if documents:
        health.status = "partial" if errors else "success"
        health.error = errors[0] if errors else None
        return documents, health

    health.status = "failed"
    health.error = errors[0] if errors else "no_results"
    return _dummy_news_documents("naver"), health


def _deduplicate_documents(documents: list[RawNewsDocument]) -> list[RawNewsDocument]:
    deduplicated: dict[str, RawNewsDocument] = {}
    for document in documents:
        deduplicated[_build_document_id(document)] = document
    return list(deduplicated.values())


def get_configured_market_news_sources() -> list[dict[str, Any]]:
    return [
        {
            "source": "rss",
            "enabled": True,
            "feed_count": len(RSS_FEED_URLS),
            "feeds": list(RSS_FEED_URLS),
        },
        {
            "source": "cryptopanic",
            "enabled": bool(settings.cryptopanic_api_key),
        },
        {
            "source": "naver",
            "enabled": bool(settings.naver_client_id and settings.naver_client_secret),
        },
    ]


def _new_embedding_result(
    chunks: list[RawNewsChunk],
    *,
    status: str,
    error: str | None = None,
) -> EmbeddingGenerationResult:
    chunk_results = {
        _build_chunk_id(chunk): ChunkEmbeddingResult(status=status, error=error)
        for chunk in chunks
    }
    return _finalize_embedding_result(chunk_results, requested=len(chunks), error=error)


def _finalize_embedding_result(
    chunk_results: dict[str, ChunkEmbeddingResult],
    *,
    requested: int,
    error: str | None = None,
) -> EmbeddingGenerationResult:
    succeeded = sum(1 for result in chunk_results.values() if result.status == EMBEDDING_STATUS_EMBEDDED)
    missing = max(requested - succeeded, 0)
    failed = sum(1 for result in chunk_results.values() if result.error is not None)
    return EmbeddingGenerationResult(
        chunks=chunk_results,
        requested=requested,
        succeeded=succeeded,
        missing=missing,
        failed=failed,
        error=error,
    )


async def _generate_embeddings(chunks: list[RawNewsChunk]) -> EmbeddingGenerationResult:
    if not chunks:
        return EmbeddingGenerationResult()

    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY가 없어 문서를 임베딩 없이 인덱싱합니다.")
        return _new_embedding_result(
            chunks,
            status=EMBEDDING_STATUS_MISSING,
            error=EMBEDDING_ERROR_CREDENTIALS_MISSING,
        )

    texts = [f"{chunk.title}\n\n{chunk.content}" for chunk in chunks]
    analyzer = GeminiAnalyzer()
    chunk_results: dict[str, ChunkEmbeddingResult] = {
        _build_chunk_id(chunk): ChunkEmbeddingResult(status=EMBEDDING_STATUS_MISSING)
        for chunk in chunks
    }
    representative_error: str | None = None
    try:
        for start_index in range(0, len(texts), GEMINI_EMBEDDING_BATCH_SIZE):
            batch = texts[start_index : start_index + GEMINI_EMBEDDING_BATCH_SIZE]
            batch_chunks = chunks[start_index : start_index + len(batch)]
            try:
                embedding_values = await analyzer.generate_embeddings(
                    batch,
                    task_type="RETRIEVAL_DOCUMENT",
                )
            except AIProviderRateLimitError as exc:
                representative_error = EMBEDDING_ERROR_RATE_LIMITED
                logger.warning("Gemini 임베딩 쿨다운으로 남은 청크를 임베딩 없이 인덱싱합니다: %s", exc)
                for chunk in chunks[start_index:]:
                    chunk_results[_build_chunk_id(chunk)] = ChunkEmbeddingResult(
                        status=EMBEDDING_STATUS_RATE_LIMITED,
                        error=EMBEDDING_ERROR_RATE_LIMITED,
                    )
                break
            except Exception:
                representative_error = EMBEDDING_ERROR_GENERATION_FAILED
                logger.exception("Gemini 임베딩 생성 실패. 남은 청크를 임베딩 없이 인덱싱합니다.")
                for chunk in chunks[start_index:]:
                    chunk_results[_build_chunk_id(chunk)] = ChunkEmbeddingResult(
                        status=EMBEDDING_STATUS_FAILED,
                        error=EMBEDDING_ERROR_GENERATION_FAILED,
                    )
                break

            generated_at = datetime.now(UTC)
            if len(embedding_values) != len(batch_chunks):
                representative_error = representative_error or EMBEDDING_ERROR_GENERATION_FAILED
                logger.warning(
                    "Gemini 임베딩 응답 개수가 요청 개수와 다릅니다: requested=%s received=%s",
                    len(batch_chunks),
                    len(embedding_values),
                )
                for chunk in batch_chunks:
                    chunk_results[_build_chunk_id(chunk)] = ChunkEmbeddingResult(
                        status=EMBEDDING_STATUS_FAILED,
                        error=EMBEDDING_ERROR_GENERATION_FAILED,
                    )
                continue

            for index, embedding in enumerate(embedding_values):
                chunk = batch_chunks[index]
                chunk_id = _build_chunk_id(chunk)
                if len(embedding) != EMBEDDING_DIMENSION:
                    representative_error = representative_error or EMBEDDING_ERROR_INVALID_DIMENSION
                    logger.warning("예상과 다른 Gemini 임베딩 차원입니다: chunk_id=%s", chunk_id)
                    chunk_results[chunk_id] = ChunkEmbeddingResult(
                        status=EMBEDDING_STATUS_FAILED,
                        error=EMBEDDING_ERROR_INVALID_DIMENSION,
                    )
                    continue
                chunk_results[chunk_id] = ChunkEmbeddingResult(
                    status=EMBEDDING_STATUS_EMBEDDED,
                    embedding=embedding,
                    model=EMBEDDING_MODEL,
                    generated_at=generated_at,
                )
    finally:
        aclose = getattr(analyzer, "aclose", None)
        if callable(aclose):
            await aclose()
        else:
            analyzer.close()

    return _finalize_embedding_result(
        chunk_results,
        requested=len(chunks),
        error=representative_error,
    )


async def _bulk_upsert_chunks(
    chunks: list[RawNewsChunk],
    embeddings: EmbeddingGenerationResult,
) -> tuple[int, list[Any]]:
    if not chunks:
        return 0, []

    actions = []
    for chunk in chunks:
        chunk_id = _build_chunk_id(chunk)
        actions.append(
            {
                "_op_type": "index",
                "_index": INDEX_NAME,
                "_id": chunk_id,
                "_source": _serialize_chunk(chunk, embeddings.chunks.get(chunk_id)),
            }
        )

    client = get_opensearch_client()
    success_count, errors = await async_bulk(
        client,
        actions,
        raise_on_error=False,
        raise_on_exception=False,
    )
    if success_count:
        try:
            await client.indices.refresh(index=INDEX_NAME)
        except Exception:
            logger.warning("market_news 인덱스 refresh에 실패했습니다.", exc_info=True)
    return int(success_count), list(errors)


def _fallback_document_query() -> dict[str, Any]:
    return {
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


def _source_parent_ids(documents: list[RawNewsDocument]) -> dict[str, set[str]]:
    parent_ids: dict[str, set[str]] = {}
    for document in documents:
        if _is_fallback_document(document):
            continue
        parent_ids.setdefault(document.source, set()).add(_build_document_id(document))
    return parent_ids


async def _delete_stale_source_documents(source_parent_ids: dict[str, set[str]]) -> int:
    client = get_opensearch_client()
    deleted = 0
    for source, parent_ids in source_parent_ids.items():
        if not parent_ids:
            continue

        response = await client.delete_by_query(
            index=INDEX_NAME,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"source": source}},
                        ],
                        "must_not": [
                            {"terms": {"parent_id": sorted(parent_ids)}},
                        ],
                    }
                }
            },
            conflicts="proceed",
            ignore_unavailable=True,
            refresh=True,
        )
        deleted += int(response.get("deleted", 0))
    return deleted


async def _delete_fallback_documents() -> int:
    client = get_opensearch_client()
    response = await client.delete_by_query(
        index=INDEX_NAME,
        body={"query": _fallback_document_query()},
        conflicts="proceed",
        ignore_unavailable=True,
        refresh=True,
    )
    return int(response.get("deleted", 0))


async def _delete_expired_documents() -> int:
    cutoff = (datetime.now(UTC) - timedelta(days=MARKET_NEWS_TTL_DAYS)).isoformat()
    client = get_opensearch_client()
    response = await client.delete_by_query(
        index=INDEX_NAME,
        body={
            "query": {
                "range": {
                    "published_at": {
                        "lt": cutoff,
                    }
                }
            }
        },
        conflicts="proceed",
        ignore_unavailable=True,
        refresh=True,
    )
    return int(response.get("deleted", 0))


async def _delete_expired_ingestion_runs() -> int:
    cutoff = (datetime.now(UTC) - timedelta(days=INGESTION_RUN_TTL_DAYS)).isoformat()
    client = get_opensearch_client()
    response = await client.delete_by_query(
        index=INGESTION_RUNS_INDEX_NAME,
        body={
            "query": {
                "range": {
                    "finished_at": {
                        "lt": cutoff,
                    }
                }
            }
        },
        conflicts="proceed",
        ignore_unavailable=True,
        refresh=True,
    )
    return int(response.get("deleted", 0))


def _refresh_deleted_total(stats: dict[str, Any]) -> None:
    stats["deleted"] = (
        stats.get("stale_deleted", 0)
        + stats.get("fallback_deleted", 0)
        + stats.get("expired_deleted", 0)
    )


def _resolve_ingestion_run_status(stats: dict[str, Any], source_health: list[SourceHealth]) -> str:
    if stats.get("indexed", 0) <= 0:
        return "failed"
    if stats.get("errors", 0) > 0 or stats.get("embedding_missing", 0) > 0:
        return "partial"
    if any(health.enabled and health.status in {"failed", "partial"} for health in source_health):
        return "partial"
    return "success"


async def _store_ingestion_run(
    *,
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    stats: dict[str, Any],
    source_health: list[SourceHealth],
) -> None:
    if not await ensure_market_news_ingestion_runs_index():
        return

    client = get_opensearch_client()
    payload: dict[str, Any] = {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "status": _resolve_ingestion_run_status(stats, source_health),
        "fetched": stats["fetched"],
        "indexed": stats["indexed"],
        "deleted": stats["deleted"],
        "errors": stats["errors"],
        "crawled": stats["crawled"],
        "crawl_failed": stats["crawl_failed"],
        "crawl_skipped": stats["crawl_skipped"],
        "rss_summary_used": stats["rss_summary_used"],
        "stale_deleted": stats["stale_deleted"],
        "fallback_deleted": stats["fallback_deleted"],
        "expired_deleted": stats["expired_deleted"],
        "embedding_requested": stats["embedding_requested"],
        "embedding_succeeded": stats["embedding_succeeded"],
        "embedding_missing": stats["embedding_missing"],
        "embedding_failed": stats["embedding_failed"],
        "embedding_error": stats["embedding_error"],
        "source_health": [_serialize_source_health(health) for health in source_health],
    }
    await client.index(
        index=INGESTION_RUNS_INDEX_NAME,
        id=run_id,
        body=payload,
        refresh=True,
    )
    await _delete_expired_ingestion_runs()


async def run_market_news_ingestion_job() -> dict[str, Any]:
    run_id = uuid4().hex
    started_at = datetime.now(UTC)
    source_health: list[SourceHealth] = []
    stats = {
        "fetched": 0,
        "indexed": 0,
        "deleted": 0,
        "errors": 0,
        "crawled": 0,
        "crawl_failed": 0,
        "crawl_skipped": 0,
        "rss_summary_used": 0,
        "stale_deleted": 0,
        "fallback_deleted": 0,
        "expired_deleted": 0,
        "embedding_requested": 0,
        "embedding_succeeded": 0,
        "embedding_missing": 0,
        "embedding_failed": 0,
        "embedding_error": None,
    }
    index_ready = False

    try:
        index_ready = await ensure_market_news_index_for_ingestion()
        if not index_ready:
            logger.warning("market_news 인덱스 준비 실패로 ingestion 작업을 건너뜁니다.")
            stats["errors"] += 1
            return stats

        async with httpx.AsyncClient(
            timeout=NEWS_HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "ai-trade-manager/0.1"},
        ) as client:
            cryptopanic_result, naver_result, rss_result = await asyncio.gather(
                _fetch_cryptopanic_news(client),
                _fetch_naver_news(client),
                _fetch_rss_news(client),
            )
            cryptopanic_documents, cryptopanic_health = cryptopanic_result
            naver_documents, naver_health = naver_result
            rss_documents, rss_health = rss_result
            rss_documents, crawl_stats = await _enrich_rss_documents_with_crawl(
                client,
                rss_documents,
            )
            _apply_crawl_health_to_sources(rss_health, rss_documents)
            source_health = [cryptopanic_health, naver_health, *rss_health]
            stats.update(crawl_stats)

        documents = _deduplicate_documents(
            _prefer_real_documents([*cryptopanic_documents, *naver_documents, *rss_documents])
        )
        stats["fetched"] = len(documents)
        chunks = _build_news_chunks(documents)
        embeddings = await _generate_embeddings(chunks)
        stats["embedding_requested"] = embeddings.requested
        stats["embedding_succeeded"] = embeddings.succeeded
        stats["embedding_missing"] = embeddings.missing
        stats["embedding_failed"] = embeddings.failed
        stats["embedding_error"] = embeddings.error

        indexed_count, bulk_errors = await _bulk_upsert_chunks(chunks, embeddings)
        stats["indexed"] = indexed_count
        if bulk_errors:
            stats["errors"] += len(bulk_errors)
            logger.warning("OpenSearch bulk indexing reported %s errors.", len(bulk_errors))
        if indexed_count:
            source_parent_ids = _source_parent_ids(documents)
            stats["stale_deleted"] = await _delete_stale_source_documents(source_parent_ids)
            if source_parent_ids:
                stats["fallback_deleted"] = await _delete_fallback_documents()
            _refresh_deleted_total(stats)
    except Exception:
        stats["errors"] += 1
        logger.exception("market_news ingestion job failed.")
    finally:
        if index_ready:
            try:
                stats["expired_deleted"] = await _delete_expired_documents()
                _refresh_deleted_total(stats)
            except Exception:
                logger.exception("Failed to delete expired market_news documents.")
                stats["errors"] += 1
        try:
            await _store_ingestion_run(
                run_id=run_id,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                stats=stats,
                source_health=source_health,
            )
        except Exception:
            logger.exception("Failed to store market_news ingestion run.")

    logger.info(
        (
            "market_news ingestion finished: fetched=%s indexed=%s deleted=%s errors=%s "
            "crawled=%s crawl_failed=%s crawl_skipped=%s rss_summary_used=%s "
            "stale_deleted=%s fallback_deleted=%s expired_deleted=%s "
            "embedding_requested=%s embedding_succeeded=%s embedding_missing=%s "
            "embedding_failed=%s embedding_error=%s"
        ),
        stats["fetched"],
        stats["indexed"],
        stats["deleted"],
        stats["errors"],
        stats["crawled"],
        stats["crawl_failed"],
        stats["crawl_skipped"],
        stats["rss_summary_used"],
        stats["stale_deleted"],
        stats["fallback_deleted"],
        stats["expired_deleted"],
        stats["embedding_requested"],
        stats["embedding_succeeded"],
        stats["embedding_missing"],
        stats["embedding_failed"],
        stats["embedding_error"],
    )
    return stats
