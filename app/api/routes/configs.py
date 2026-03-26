from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduler import reload_scheduler_jobs
from app.db.repository import AI_BRIEFING_TIME_KEY
from app.db.repository import NEWS_INTERVAL_HOURS_KEY
from app.db.repository import SENTIMENT_INTERVAL_MINUTES_KEY
from app.db.repository import bulk_upsert_system_configs
from app.db.repository import list_system_configs
from app.db.session import get_db
from app.models.schemas import SystemConfigItem
from app.models.schemas import SystemConfigUpdateItem

router = APIRouter()

SCHEDULER_CONFIG_KEYS = {
    NEWS_INTERVAL_HOURS_KEY,
    SENTIMENT_INTERVAL_MINUTES_KEY,
    AI_BRIEFING_TIME_KEY,
}


@router.get("/configs", response_model=list[SystemConfigItem])
async def get_system_configs(db: AsyncSession = Depends(get_db)) -> list[SystemConfigItem]:
    configs = await list_system_configs(db)
    return [
        SystemConfigItem(
            id=config.id,
            config_key=config.config_key,
            config_value=config.config_value,
            description=config.description,
        )
        for config in configs
    ]


@router.put("/configs", response_model=list[SystemConfigItem])
async def update_system_configs(
    payload: list[SystemConfigUpdateItem],
    db: AsyncSession = Depends(get_db),
) -> list[SystemConfigItem]:
    if not payload:
        raise HTTPException(status_code=400, detail="최소 1개 이상의 설정값이 필요합니다.")

    config_keys = [item.config_key for item in payload]
    if len(config_keys) != len(set(config_keys)):
        raise HTTPException(status_code=400, detail="중복된 config_key는 허용되지 않습니다.")

    configs = await bulk_upsert_system_configs(
        db,
        [(item.config_key, item.config_value) for item in payload],
    )

    if any(config_key in SCHEDULER_CONFIG_KEYS for config_key in config_keys):
        await reload_scheduler_jobs()

    return [
        SystemConfigItem(
            id=config.id,
            config_key=config.config_key,
            config_value=config.config_value,
            description=config.description,
        )
        for config in configs
    ]
