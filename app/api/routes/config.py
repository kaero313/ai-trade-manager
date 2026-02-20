from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import get_or_create_bot_config
from app.db.session import get_db
from app.models.schemas import BotConfig

router = APIRouter()


@router.get("/config", response_model=BotConfig)
async def get_config(db: AsyncSession = Depends(get_db)) -> BotConfig:
    bot_config = await get_or_create_bot_config(db)
    return BotConfig.model_validate(bot_config.config_json or {})


@router.post("/config", response_model=BotConfig)
async def update_config(config: BotConfig, db: AsyncSession = Depends(get_db)) -> BotConfig:
    bot_config = await get_or_create_bot_config(db)
    bot_config.config_json = config.model_dump()
    await db.commit()
    await db.refresh(bot_config)
    return BotConfig.model_validate(bot_config.config_json or {})
