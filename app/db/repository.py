from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import BotConfig as BotConfigORM
from app.models.schemas import BotConfig as BotConfigSchema
from app.models.schemas import MarketSentimentSnapshot

BOT_CONFIG_METADATA_KEY = "metadata"
MARKET_SENTIMENT_METADATA_KEY = "market_sentiment"


async def get_or_create_bot_config(db: AsyncSession) -> BotConfigORM:
    bot_config = await db.get(BotConfigORM, 1)
    if bot_config is not None:
        return bot_config

    bot_config = BotConfigORM(
        id=1,
        config_json=BotConfigSchema().model_dump(),
        is_active=True,
    )
    db.add(bot_config)
    await db.commit()
    await db.refresh(bot_config)
    return bot_config


def normalize_bot_config_payload(raw_payload: Any) -> dict[str, Any]:
    if isinstance(raw_payload, dict):
        return dict(raw_payload)
    return {}


def extract_bot_config_metadata(raw_payload: Any) -> dict[str, Any]:
    payload = normalize_bot_config_payload(raw_payload)
    metadata = payload.get(BOT_CONFIG_METADATA_KEY)
    if isinstance(metadata, dict):
        return dict(metadata)
    return {}


def merge_bot_config_metadata(config_payload: dict[str, Any], existing_payload: Any) -> dict[str, Any]:
    merged_payload = dict(config_payload)
    metadata = extract_bot_config_metadata(existing_payload)
    if metadata:
        merged_payload[BOT_CONFIG_METADATA_KEY] = metadata
    return merged_payload


def read_cached_market_sentiment(raw_payload: Any) -> MarketSentimentSnapshot | None:
    metadata = extract_bot_config_metadata(raw_payload)
    sentiment_payload = metadata.get(MARKET_SENTIMENT_METADATA_KEY)
    if not isinstance(sentiment_payload, dict):
        return None
    try:
        return MarketSentimentSnapshot.model_validate(sentiment_payload)
    except Exception:
        return None


async def store_market_sentiment_cache(
    db: AsyncSession,
    sentiment: MarketSentimentSnapshot,
) -> BotConfigORM:
    bot_config = await get_or_create_bot_config(db)
    payload = normalize_bot_config_payload(bot_config.config_json)
    metadata = extract_bot_config_metadata(payload)
    metadata[MARKET_SENTIMENT_METADATA_KEY] = sentiment.model_dump(mode="json")
    payload[BOT_CONFIG_METADATA_KEY] = metadata
    bot_config.config_json = payload
    await db.commit()
    await db.refresh(bot_config)
    return bot_config
