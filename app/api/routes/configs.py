import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduler import reload_scheduler_jobs
from app.db.repository import AI_BRIEFING_TIME_KEY
from app.db.repository import AUTONOMOUS_AI_INTERVAL_HOURS_KEY
from app.db.repository import AUTONOMOUS_AI_INTERVAL_MINUTES_KEY
from app.db.repository import NEWS_INTERVAL_HOURS_KEY
from app.db.repository import PAPER_TRADING_KRW_BALANCE_KEY
from app.db.repository import SENTIMENT_INTERVAL_MINUTES_KEY
from app.db.repository import bulk_upsert_system_configs
from app.db.repository import list_system_configs
from app.db.session import get_db
from app.models.domain import OrderHistory, Position, SystemConfig
from app.models.schemas import SystemConfigItem
from app.models.schemas import SystemConfigUpdateItem

router = APIRouter()
logger = logging.getLogger(__name__)

DEFAULT_RESET_PAPER_BALANCE = "10000000"
PAPER_BALANCE_DESCRIPTION = "모의투자용 가상 KRW 자본금"

SCHEDULER_CONFIG_KEYS = {
    NEWS_INTERVAL_HOURS_KEY,
    SENTIMENT_INTERVAL_MINUTES_KEY,
    AI_BRIEFING_TIME_KEY,
    AUTONOMOUS_AI_INTERVAL_HOURS_KEY,
    AUTONOMOUS_AI_INTERVAL_MINUTES_KEY,
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
        raise HTTPException(status_code=400, detail="중복된 config_key 는 허용되지 않습니다.")

    configs = await bulk_upsert_system_configs(
        db,
        [(item.config_key, item.config_value) for item in payload],
    )

    if any(config_key in SCHEDULER_CONFIG_KEYS for config_key in config_keys):
        try:
            await reload_scheduler_jobs()
        except Exception:
            logger.error(
                "SystemConfig 저장 후 스케줄러 리로드 적용에 실패했습니다.",
                exc_info=True,
            )

    return [
        SystemConfigItem(
            id=config.id,
            config_key=config.config_key,
            config_value=config.config_value,
            description=config.description,
        )
        for config in configs
    ]


@router.post("/paper/reset")
async def reset_paper_trading_state(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        deleted_order_history_result = await db.execute(
            delete(OrderHistory).where(OrderHistory.is_paper.is_(True))
        )
        deleted_position_result = await db.execute(
            delete(Position).where(Position.is_paper.is_(True))
        )

        paper_balance_result = await db.execute(
            select(SystemConfig).where(SystemConfig.config_key == PAPER_TRADING_KRW_BALANCE_KEY)
        )
        paper_balance_config = paper_balance_result.scalar_one_or_none()
        if paper_balance_config is None:
            paper_balance_config = SystemConfig(
                config_key=PAPER_TRADING_KRW_BALANCE_KEY,
                config_value=DEFAULT_RESET_PAPER_BALANCE,
                description=PAPER_BALANCE_DESCRIPTION,
            )
            db.add(paper_balance_config)
        else:
            paper_balance_config.config_value = DEFAULT_RESET_PAPER_BALANCE

        await db.commit()
        return {
            "message": "모의투자 상태가 초기화되었습니다.",
            "deleted_order_history_count": int(deleted_order_history_result.rowcount or 0),
            "deleted_position_count": int(deleted_position_result.rowcount or 0),
            "paper_trading_krw_balance": DEFAULT_RESET_PAPER_BALANCE,
        }
    except Exception as exc:
        await db.rollback()
        logger.error("모의투자 리셋 API 처리 실패: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="모의투자 상태 초기화에 실패했습니다.") from exc
