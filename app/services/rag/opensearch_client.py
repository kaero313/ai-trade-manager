import logging

from opensearchpy import AsyncOpenSearch

from app.core.config import settings

INDEX_NAME = "market_news"
EMBEDDING_DIMENSION = 1536
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
            "embedding": {
                "type": "knn_vector",
                "dimension": EMBEDDING_DIMENSION,
                "method": {
                    "name": "hnsw",
                    "engine": "nmslib",
                    "space_type": "cosinesimil",
                },
            },
        }
    },
}

_opensearch_client: AsyncOpenSearch | None = None


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


async def ensure_market_news_index() -> bool:
    client = get_opensearch_client()
    try:
        index_exists = await client.indices.exists(index=INDEX_NAME)
    except Exception:
        logger.exception("market_news 인덱스 존재 여부 확인에 실패했습니다: index=%s", INDEX_NAME)
        return False

    if index_exists:
        return True

    try:
        await client.indices.create(index=INDEX_NAME, body=MARKET_NEWS_INDEX_BODY)
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
