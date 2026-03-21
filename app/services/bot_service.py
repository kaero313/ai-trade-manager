import random

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import get_or_create_bot_config
from app.models.domain import BotConfig as BotConfigORM
from app.models.schemas import BotStatus


RUNNING_ACTIONS = (
    "KRW-BTC 15분봉 지표 분석 중...",
    "그리드 매수망 최적화 연산 중...",
    "시장 심리지수 스크래핑 중...",
)


def _resolve_latest_action(is_running: bool) -> str:
    if not is_running:
        return "AI 엔진 대기 중..."
    return random.choice(RUNNING_ACTIONS)


def _to_bot_status(bot_config: BotConfigORM) -> BotStatus:
    is_running = bool(bot_config.is_active)
    return BotStatus(
        running=is_running,
        last_heartbeat=None,
        last_error=None,
        latest_action=_resolve_latest_action(is_running),
    )


async def get_bot_status(db: AsyncSession) -> BotStatus:
    bot_config = await get_or_create_bot_config(db)
    await db.refresh(bot_config)
    return _to_bot_status(bot_config)


async def start_bot(db: AsyncSession) -> BotStatus:
    await get_or_create_bot_config(db)
    await db.execute(
        update(BotConfigORM)
        .where(BotConfigORM.id == 1)
        .values(is_active=True)
    )
    await db.commit()
    bot_config = await db.get(BotConfigORM, 1)
    return _to_bot_status(bot_config)


async def stop_bot(db: AsyncSession) -> BotStatus:
    await get_or_create_bot_config(db)
    await db.execute(
        update(BotConfigORM)
        .where(BotConfigORM.id == 1)
        .values(is_active=False)
    )
    await db.commit()
    bot_config = await db.get(BotConfigORM, 1)
    return _to_bot_status(bot_config)
