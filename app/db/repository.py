import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import AIChatMessage as AIChatMessageORM
from app.models.domain import BotConfig as BotConfigORM
from app.models.domain import PortfolioSnapshot as PortfolioSnapshotORM
from app.models.domain import SystemConfig as SystemConfigORM
from app.models.schemas import BotConfig as BotConfigSchema
from app.models.schemas import MarketSentimentSnapshot

BOT_CONFIG_METADATA_KEY = "metadata"
MARKET_SENTIMENT_METADATA_KEY = "market_sentiment"
NEWS_INTERVAL_HOURS_KEY = "news_interval_hours"
SENTIMENT_INTERVAL_MINUTES_KEY = "sentiment_interval_minutes"
AI_BRIEFING_TIME_KEY = "ai_briefing_time"
AUTONOMOUS_AI_INTERVAL_HOURS_KEY = "autonomous_ai_interval_hours"
AUTONOMOUS_AI_INTERVAL_MINUTES_KEY = "autonomous_ai_interval_minutes"
MAX_ALLOCATION_PCT_KEY = "max_allocation_pct"
HARD_TAKE_PROFIT_PCT_KEY = "hard_take_profit_pct"
HARD_STOP_LOSS_PCT_KEY = "hard_stop_loss_pct"
TRADING_MODE_KEY = "trading_mode"
PAPER_TRADING_KRW_BALANCE_KEY = "paper_trading_krw_balance"
MARKET_SENTIMENT_SNAPSHOT_KEY = "market_sentiment_snapshot"
AI_MIN_CONFIDENCE_TRADE_KEY = "ai_min_confidence_trade"
AI_ANALYSIS_MAX_AGE_MINUTES_KEY = "ai_analysis_max_age_minutes"
AI_CUSTOM_PERSONA_PROMPT_KEY = "ai_custom_persona_prompt"

SYSTEM_CONFIG_SEEDS: tuple[dict[str, str], ...] = (
    {
        "config_key": NEWS_INTERVAL_HOURS_KEY,
        "config_value": "4",
        "description": "시장 뉴스 수집 주기(시간)",
    },
    {
        "config_key": SENTIMENT_INTERVAL_MINUTES_KEY,
        "config_value": "5",
        "description": "시장 심리 지수 갱신 주기(분)",
    },
    {
        "config_key": AI_BRIEFING_TIME_KEY,
        "config_value": "08:30",
        "description": "일일 AI 브리핑 실행 시각(HH:MM)",
    },
    {
        "config_key": AUTONOMOUS_AI_INTERVAL_HOURS_KEY,
        "config_value": "1",
        "description": "Watchlist AI 자율주행 분석 주기(시간)",
    },
    {
        "config_key": AUTONOMOUS_AI_INTERVAL_MINUTES_KEY,
        "config_value": "15",
        "description": "AI 단타 자율주행 분석 주기 단위(분)",
    },
    {
        "config_key": MAX_ALLOCATION_PCT_KEY,
        "config_value": "10",
        "description": "종목당 베팅 최대 한도: 총 KRW 자산 대비 %",
    },
    {
        "config_key": HARD_TAKE_PROFIT_PCT_KEY,
        "config_value": "5.0",
        "description": "강제 익절율 %, 0이면 무시",
    },
    {
        "config_key": HARD_STOP_LOSS_PCT_KEY,
        "config_value": "-3.0",
        "description": "강제 손절율 %, 0이면 무시",
    },
    {
        "config_key": TRADING_MODE_KEY,
        "config_value": "live",
        "description": "거래 실행 모드(live/paper)",
    },
    {
        "config_key": PAPER_TRADING_KRW_BALANCE_KEY,
        "config_value": "10000000",
        "description": "모의투자용 가상 KRW 자본금",
    },
    {
        "config_key": AI_MIN_CONFIDENCE_TRADE_KEY,
        "config_value": "70",
        "description": "AI 자율 체결 최소 확신도(0~100)",
    },
    {
        "config_key": AI_ANALYSIS_MAX_AGE_MINUTES_KEY,
        "config_value": "90",
        "description": "AI 분석 로그 최대 유효 시간(분)",
    },
    {
        "config_key": AI_CUSTOM_PERSONA_PROMPT_KEY,
        "config_value": "",
        "description": "AI 커스텀 매매 페르소나 프롬프트",
    },
)


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


async def get_system_config(db: AsyncSession, config_key: str) -> SystemConfigORM | None:
    result = await db.execute(
        select(SystemConfigORM).where(SystemConfigORM.config_key == config_key)
    )
    return result.scalar_one_or_none()


async def get_system_config_value(
    db: AsyncSession,
    config_key: str,
    default: str | None = None,
) -> str | None:
    config = await get_system_config(db, config_key)
    if config is None:
        return default
    return config.config_value


async def list_system_configs(db: AsyncSession) -> list[SystemConfigORM]:
    result = await db.execute(select(SystemConfigORM).order_by(SystemConfigORM.id))
    return list(result.scalars().all())


async def upsert_system_config(
    db: AsyncSession,
    config_key: str,
    config_value: str,
    description: str | None = None,
) -> SystemConfigORM:
    config = await get_system_config(db, config_key)
    if config is None:
        config = SystemConfigORM(
            config_key=config_key,
            config_value=config_value,
            description=description,
        )
        db.add(config)
    else:
        config.config_value = config_value
        if description is not None:
            config.description = description

    await db.commit()
    await db.refresh(config)
    return config


async def bulk_upsert_system_configs(
    db: AsyncSession,
    items: Sequence[tuple[str, str]],
) -> list[SystemConfigORM]:
    if not items:
        return await list_system_configs(db)

    values_by_key = {config_key: config_value for config_key, config_value in items}
    result = await db.execute(
        select(SystemConfigORM).where(SystemConfigORM.config_key.in_(values_by_key))
    )
    existing_configs = {
        config.config_key: config for config in result.scalars().all()
    }

    for config_key, config_value in values_by_key.items():
        existing_config = existing_configs.get(config_key)
        if existing_config is None:
            db.add(
                SystemConfigORM(
                    config_key=config_key,
                    config_value=config_value,
                )
            )
            continue

        existing_config.config_value = config_value

    await db.commit()
    return await list_system_configs(db)


async def seed_system_configs_if_empty(db: AsyncSession) -> None:
    result = await db.execute(select(SystemConfigORM.config_key))
    existing_keys = set(result.scalars().all())

    missing_configs = [
        SystemConfigORM(
            config_key=item["config_key"],
            config_value=item["config_value"],
            description=item["description"],
        )
        for item in SYSTEM_CONFIG_SEEDS
        if item["config_key"] not in existing_keys
    ]
    if not missing_configs:
        return

    db.add_all(missing_configs)
    await db.commit()


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


BOT_RUNTIME_STATUS_KEY = "runtime_status"


def extract_bot_runtime_status(raw_payload: Any) -> dict[str, Any]:
    metadata = extract_bot_config_metadata(raw_payload)
    runtime_status = metadata.get(BOT_RUNTIME_STATUS_KEY)
    if isinstance(runtime_status, dict):
        return dict(runtime_status)
    return {}


def merge_bot_runtime_status(existing_payload: Any, runtime_status: dict[str, Any]) -> dict[str, Any]:
    payload = normalize_bot_config_payload(existing_payload)
    metadata = extract_bot_config_metadata(existing_payload)
    if runtime_status:
        metadata[BOT_RUNTIME_STATUS_KEY] = dict(runtime_status)
    else:
        metadata.pop(BOT_RUNTIME_STATUS_KEY, None)

    if metadata:
        payload[BOT_CONFIG_METADATA_KEY] = metadata
    else:
        payload.pop(BOT_CONFIG_METADATA_KEY, None)
    return payload


async def read_cached_market_sentiment(db: AsyncSession) -> MarketSentimentSnapshot | None:
    raw_snapshot = await get_system_config_value(db, MARKET_SENTIMENT_SNAPSHOT_KEY)
    if raw_snapshot is None:
        return None

    try:
        payload = json.loads(raw_snapshot)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    try:
        return MarketSentimentSnapshot.model_validate(payload)
    except Exception:
        return None


async def store_market_sentiment_cache(
    db: AsyncSession,
    sentiment: MarketSentimentSnapshot,
) -> SystemConfigORM:
    return await upsert_system_config(
        db=db,
        config_key=MARKET_SENTIMENT_SNAPSHOT_KEY,
        config_value=json.dumps(sentiment.model_dump(mode="json"), ensure_ascii=False),
        description="Alternative.me 시장 심리 지수 캐시(JSON)",
    )


async def save_chat_message(
    db: AsyncSession,
    session_id: str,
    role: str,
    content: str,
    agent_name: str | None = None,
    is_tool_call: bool = False,
) -> AIChatMessageORM:
    message = AIChatMessageORM(
        session_id=session_id,
        role=role,
        content=content,
        agent_name=agent_name,
        is_tool_call=is_tool_call,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def delete_chat_session_messages(db: AsyncSession, session_id: str) -> None:
    await db.execute(
        delete(AIChatMessageORM).where(AIChatMessageORM.session_id == session_id)
    )
    await db.commit()


async def save_portfolio_snapshot(
    db: AsyncSession,
    total_net_worth: float,
    total_pnl: float,
    snapshot_data: list[dict[str, Any]],
) -> PortfolioSnapshotORM:
    snapshot = PortfolioSnapshotORM(
        total_net_worth=total_net_worth,
        total_pnl=total_pnl,
        snapshot_data=snapshot_data,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def get_portfolio_snapshots(
    db: AsyncSession,
    limit: int = 168,
) -> list[PortfolioSnapshotORM]:
    result = await db.execute(
        select(PortfolioSnapshotORM)
        .order_by(desc(PortfolioSnapshotORM.created_at))
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_recent_chat_messages(
    db: AsyncSession,
    session_id: str,
    limit: int = 20,
) -> list[AIChatMessageORM]:
    if limit <= 0:
        return []

    result = await db.execute(
        select(AIChatMessageORM)
        .where(
            AIChatMessageORM.session_id == session_id,
            AIChatMessageORM.is_tool_call.is_(False),
        )
        .order_by(desc(AIChatMessageORM.created_at), desc(AIChatMessageORM.id))
        .limit(limit)
    )
    messages = list(result.scalars().all())
    messages.reverse()
    return messages


async def search_chat_history(
    db: AsyncSession,
    session_id: str,
    keyword: str,
) -> list[AIChatMessageORM]:
    normalized_keyword = keyword.strip()
    if not normalized_keyword:
        return []

    result = await db.execute(
        select(AIChatMessageORM)
        .where(
            AIChatMessageORM.session_id == session_id,
            AIChatMessageORM.content.ilike(f"%{normalized_keyword}%"),
        )
        .order_by(desc(AIChatMessageORM.created_at), desc(AIChatMessageORM.id))
    )
    return list(result.scalars().all())


async def get_chat_sessions(db: AsyncSession) -> list[dict[str, Any]]:
    ranked_messages = (
        select(
            AIChatMessageORM.session_id.label("session_id"),
            AIChatMessageORM.created_at.label("created_at"),
            AIChatMessageORM.content.label("content"),
            func.row_number()
            .over(
                partition_by=AIChatMessageORM.session_id,
                order_by=(desc(AIChatMessageORM.created_at), desc(AIChatMessageORM.id)),
            )
            .label("row_number"),
        )
        .where(AIChatMessageORM.is_tool_call.is_(False))
        .subquery()
    )

    result = await db.execute(
        select(
            ranked_messages.c.session_id,
            ranked_messages.c.created_at,
            ranked_messages.c.content,
        )
        .where(ranked_messages.c.row_number == 1)
        .order_by(desc(ranked_messages.c.created_at), ranked_messages.c.session_id)
    )

    sessions: list[dict[str, Any]] = []
    for row in result.all():
        preview_source = (row.content or "").strip()
        sessions.append(
            {
                "session_id": row.session_id,
                "created_at": row.created_at,
                "content_preview": preview_source[:120],
            }
        )

    return sessions
