from opensearchpy import AsyncOpenSearch

from app.core.config import settings

INDEX_NAME = "market_news"
EMBEDDING_DIMENSION = 1536

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


async def ensure_market_news_index() -> None:
    client = get_opensearch_client()
    index_exists = await client.indices.exists(index=INDEX_NAME)

    if index_exists:
        return

    await client.indices.create(index=INDEX_NAME, body=MARKET_NEWS_INDEX_BODY)
