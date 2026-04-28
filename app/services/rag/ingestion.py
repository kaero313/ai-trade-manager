from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any

import httpx
from opensearchpy.helpers import async_bulk

from app.core.config import settings
from app.services.ai.providers.gemini import AIProviderRateLimitError, GeminiAnalyzer
from app.services.rag.opensearch_client import (
    EMBEDDING_DIMENSION,
    INDEX_NAME,
    ensure_market_news_index,
    get_opensearch_client,
)

logger = logging.getLogger(__name__)

CRYPTO_PANIC_ENDPOINT = "https://cryptopanic.com/api/v1/posts/"
NAVER_NEWS_ENDPOINT = "https://openapi.naver.com/v1/search/news.json"
CRYPTO_PANIC_FETCH_LIMIT = 10
NAVER_FETCH_LIMIT = 10
MARKET_NEWS_TTL_DAYS = 28
EMBEDDING_MODEL = "gemini-embedding-001"
NEWS_HTTP_TIMEOUT = 10.0
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


def _clean_text(raw: Any) -> str:
    text = str(raw or "")
    text = unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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


def _build_document_id(document: RawNewsDocument) -> str:
    published_key = document.published_at.isoformat()
    unique_key = document.link or document.title
    return hashlib.sha256(f"{document.source}|{unique_key}|{published_key}".encode("utf-8")).hexdigest()


def _serialize_document(document: RawNewsDocument, embedding: list[float] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": document.title,
        "content": document.content,
        "source": document.source,
        "link": document.link,
        "published_at": document.published_at.isoformat(),
    }
    if embedding:
        payload["embedding"] = embedding
    return payload


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
            ),
            RawNewsDocument(
                title="Bitcoin volatility check fallback feed",
                content="Fallback global market headline because the CryptoPanic request failed.",
                published_at=published_at,
                source=source,
                link="dummy://cryptopanic/bitcoin-volatility-check",
            ),
            RawNewsDocument(
                title="Macro liquidity watch fallback update",
                content="Fallback global market headline generated to keep the RAG ingestion pipeline alive.",
                published_at=published_at,
                source=source,
                link="dummy://cryptopanic/macro-liquidity-watch",
            ),
        ]

    return [
        RawNewsDocument(
            title="KRW market fallback headline",
            content="Fallback local market headline because Naver credentials are unavailable.",
            published_at=published_at,
            source=source,
            link="dummy://naver/krw-market-standby",
        ),
        RawNewsDocument(
            title="Upbit volatility check fallback",
            content="Fallback local market headline because the Naver request failed.",
            published_at=published_at,
            source=source,
            link="dummy://naver/upbit-volatility-check",
        ),
        RawNewsDocument(
            title="Local crypto regulation watch fallback",
            content="Fallback local market headline generated to keep the RAG ingestion pipeline alive.",
            published_at=published_at,
            source=source,
            link="dummy://naver/local-crypto-monitoring",
        ),
    ]


async def _fetch_cryptopanic_news(client: httpx.AsyncClient) -> list[RawNewsDocument]:
    if not settings.cryptopanic_api_key:
        logger.warning("CryptoPanic API key is missing. Falling back to dummy documents.")
        return _dummy_news_documents("cryptopanic")

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
    except Exception:
        logger.exception("CryptoPanic fetch failed. Falling back to dummy documents.")
        return _dummy_news_documents("cryptopanic")

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

    return documents


async def _fetch_naver_news(client: httpx.AsyncClient) -> list[RawNewsDocument]:
    if not settings.naver_client_id or not settings.naver_client_secret:
        logger.warning("Naver API credentials are missing. Falling back to dummy documents.")
        return _dummy_news_documents("naver")

    documents: list[RawNewsDocument] = []
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
        except Exception:
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

    return documents or _dummy_news_documents("naver")


def _deduplicate_documents(documents: list[RawNewsDocument]) -> list[RawNewsDocument]:
    deduplicated: dict[str, RawNewsDocument] = {}
    for document in documents:
        deduplicated[_build_document_id(document)] = document
    return list(deduplicated.values())


async def _generate_embeddings(documents: list[RawNewsDocument]) -> dict[str, list[float]]:
    if not documents:
        return {}

    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY가 없어 문서를 임베딩 없이 인덱싱합니다.")
        return {}

    texts = [f"{document.title}\n\n{document.content}" for document in documents]
    analyzer = GeminiAnalyzer()
    try:
        embedding_values = await analyzer.generate_embeddings(
            texts,
            task_type="RETRIEVAL_DOCUMENT",
        )
    except AIProviderRateLimitError:
        raise
    except Exception:
        logger.exception("Gemini 임베딩 생성 실패. 문서를 임베딩 없이 인덱싱합니다.")
        return {}

    embeddings: dict[str, list[float]] = {}
    for index, embedding in enumerate(embedding_values):
        if len(embedding) != EMBEDDING_DIMENSION:
            logger.warning("예상과 다른 Gemini 임베딩 차원입니다: index=%s", index)
            continue
        embeddings[_build_document_id(documents[index])] = embedding

    return embeddings


async def _bulk_upsert_documents(
    documents: list[RawNewsDocument],
    embeddings: dict[str, list[float]],
) -> tuple[int, list[Any]]:
    if not documents:
        return 0, []

    actions = []
    for document in documents:
        document_id = _build_document_id(document)
        actions.append(
            {
                "_op_type": "index",
                "_index": INDEX_NAME,
                "_id": document_id,
                "_source": _serialize_document(document, embeddings.get(document_id)),
            }
        )

    client = get_opensearch_client()
    success_count, errors = await async_bulk(
        client,
        actions,
        raise_on_error=False,
        raise_on_exception=False,
    )
    return int(success_count), list(errors)


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


async def run_market_news_ingestion_job() -> dict[str, int]:
    stats = {
        "fetched": 0,
        "indexed": 0,
        "deleted": 0,
        "errors": 0,
    }
    index_ready = False

    try:
        index_ready = await ensure_market_news_index()
        if not index_ready:
            logger.warning("market_news 인덱스 준비 실패로 ingestion 작업을 건너뜁니다.")
            return stats

        async with httpx.AsyncClient(
            timeout=NEWS_HTTP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "ai-trade-manager/0.1"},
        ) as client:
            cryptopanic_documents, naver_documents = await asyncio.gather(
                _fetch_cryptopanic_news(client),
                _fetch_naver_news(client),
            )

        documents = _deduplicate_documents([*cryptopanic_documents, *naver_documents])
        stats["fetched"] = len(documents)
        try:
            embeddings = await _generate_embeddings(documents)
        except AIProviderRateLimitError as exc:
            stats["errors"] += 1
            logger.warning("Gemini 임베딩 쿨다운으로 market_news ingestion을 중단합니다: %s", exc)
            return stats

        indexed_count, bulk_errors = await _bulk_upsert_documents(documents, embeddings)
        stats["indexed"] = indexed_count
        if bulk_errors:
            stats["errors"] += len(bulk_errors)
            logger.warning("OpenSearch bulk indexing reported %s errors.", len(bulk_errors))
    except Exception:
        stats["errors"] += 1
        logger.exception("market_news ingestion job failed.")
    finally:
        if index_ready:
            try:
                stats["deleted"] = await _delete_expired_documents()
            except Exception:
                logger.exception("Failed to delete expired market_news documents.")
                stats["errors"] += 1

    logger.info(
        "market_news ingestion finished: fetched=%s indexed=%s deleted=%s errors=%s",
        stats["fetched"],
        stats["indexed"],
        stats["deleted"],
        stats["errors"],
    )
    return stats
