import logging
from typing import Any

from opensearchpy import AsyncOpenSearch

from app.core.config import settings

INDEX_NAME = "market_news"
EMBEDDING_DIMENSION = 1536
KNN_METHOD_NAME = "hnsw"
KNN_ENGINE = "lucene"
KNN_SPACE_TYPE = "cosinesimil"
logger = logging.getLogger(__name__)

MARKET_NEWS_INDEX_BODY = {
    "settings": {
        "index": {
            "knn": True,
        }
    },
    "mappings": {
        "properties": {
            "title": {"type": "text"},
            "content": {"type": "text"},
            "source": {"type": "keyword"},
            "link": {"type": "keyword"},
            "published_at": {"type": "date"},
            "parent_id": {"type": "keyword"},
            "content_source": {"type": "keyword"},
            "crawl_status": {"type": "keyword"},
            "crawl_error": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "chunk_count": {"type": "integer"},
            "content_length": {"type": "integer"},
            "chunk_text_length": {"type": "integer"},
            "is_chunked": {"type": "boolean"},
            "embedding": {
                "type": "knn_vector",
                "dimension": EMBEDDING_DIMENSION,
                "method": {
                    "name": KNN_METHOD_NAME,
                    "engine": KNN_ENGINE,
                    "space_type": KNN_SPACE_TYPE,
                },
            },
        }
    },
}

_opensearch_client: AsyncOpenSearch | None = None
EXPECTED_CHUNK_FIELD_TYPES = {
    "parent_id": "keyword",
    "content_source": "keyword",
    "crawl_status": "keyword",
    "crawl_error": "keyword",
    "chunk_index": "integer",
    "chunk_count": "integer",
    "content_length": "integer",
    "chunk_text_length": "integer",
    "is_chunked": "boolean",
}


def get_opensearch_client() -> AsyncOpenSearch:
    global _opensearch_client

    if _opensearch_client is None:
        _opensearch_client = AsyncOpenSearch(
            hosts=[settings.opensearch_url],
            use_ssl=settings.opensearch_url.startswith("https://"),
            verify_certs=False,
        )

    return _opensearch_client


async def close_opensearch_client() -> None:
    global _opensearch_client

    if _opensearch_client is not None:
        await _opensearch_client.close()
        _opensearch_client = None


def _extract_properties_mapping(mapping_response: dict[str, Any]) -> dict[str, Any]:
    index_mapping = mapping_response.get(INDEX_NAME)
    if not isinstance(index_mapping, dict):
        index_mapping = next(
            (value for value in mapping_response.values() if isinstance(value, dict)),
            {},
        )

    mappings = index_mapping.get("mappings") if isinstance(index_mapping, dict) else {}
    properties = mappings.get("properties") if isinstance(mappings, dict) else {}
    return properties if isinstance(properties, dict) else {}


def _extract_embedding_mapping(mapping_response: dict[str, Any]) -> dict[str, Any] | None:
    properties = _extract_properties_mapping(mapping_response)
    embedding = properties.get("embedding")
    return embedding if isinstance(embedding, dict) else None


def _is_expected_embedding_mapping(embedding: dict[str, Any] | None) -> bool:
    if not isinstance(embedding, dict):
        return False

    method = embedding.get("method")
    if not isinstance(method, dict):
        return False

    return (
        embedding.get("type") == "knn_vector"
        and int(embedding.get("dimension") or 0) == EMBEDDING_DIMENSION
        and method.get("name") == KNN_METHOD_NAME
        and method.get("engine") == KNN_ENGINE
        and method.get("space_type") == KNN_SPACE_TYPE
    )


def _has_expected_chunk_mapping(mapping_response: dict[str, Any]) -> bool:
    properties = _extract_properties_mapping(mapping_response)
    for field_name, expected_type in EXPECTED_CHUNK_FIELD_TYPES.items():
        field_mapping = properties.get(field_name)
        if not isinstance(field_mapping, dict) or field_mapping.get("type") != expected_type:
            return False
    return True


def _is_expected_market_news_mapping(mapping_response: dict[str, Any]) -> bool:
    return (
        _is_expected_embedding_mapping(_extract_embedding_mapping(mapping_response))
        and _has_expected_chunk_mapping(mapping_response)
    )


async def _create_market_news_index(client: AsyncOpenSearch) -> bool:
    try:
        await client.indices.create(index=INDEX_NAME, body=MARKET_NEWS_INDEX_BODY)
        logger.info(
            "market_news 인덱스 생성 완료: engine=%s dimension=%s",
            KNN_ENGINE,
            EMBEDDING_DIMENSION,
        )
        return True
    except Exception as exc:
        details = getattr(exc, "info", None)
        logger.error(
            "market_news 인덱스 생성 실패: index=%s details=%s",
            INDEX_NAME,
            details if details is not None else str(exc),
            exc_info=True,
        )
        return False


async def ensure_market_news_index(*, rebuild_on_mismatch: bool = False) -> bool:
    client = get_opensearch_client()
    try:
        index_exists = await client.indices.exists(index=INDEX_NAME)
    except Exception:
        logger.exception("market_news 인덱스 존재 여부 확인에 실패했습니다: index=%s", INDEX_NAME)
        return False

    if not index_exists:
        return await _create_market_news_index(client)

    try:
        mapping_response = await client.indices.get_mapping(index=INDEX_NAME)
    except Exception:
        logger.exception("market_news 인덱스 매핑 확인에 실패했습니다: index=%s", INDEX_NAME)
        return False

    if _is_expected_market_news_mapping(mapping_response):
        return True

    logger.warning(
        "market_news 인덱스 매핑이 현재 OpenSearch 설정과 달라 재생성합니다: current=%s",
        _extract_properties_mapping(mapping_response),
    )
    if not rebuild_on_mismatch:
        return False

    try:
        await client.indices.delete(index=INDEX_NAME, ignore_unavailable=True)
    except Exception:
        logger.exception("market_news 인덱스 삭제에 실패했습니다: index=%s", INDEX_NAME)
        return False

    return await _create_market_news_index(client)


async def ensure_market_news_index_for_ingestion() -> bool:
    return await ensure_market_news_index(rebuild_on_mismatch=True)
