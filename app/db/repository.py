from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import BotConfig as BotConfigORM
from app.models.schemas import BotConfig as BotConfigSchema


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
