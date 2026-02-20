from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import get_or_create_bot_config
from app.models.domain import BotConfig as BotConfigORM
from app.models.schemas import BotStatus


def _to_bot_status(bot_config: BotConfigORM) -> BotStatus:
    return BotStatus(
        running=bool(bot_config.is_active),
        last_heartbeat=None,
        last_error=None,
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
