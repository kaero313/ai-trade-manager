from datetime import datetime, timezone
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import extract_bot_runtime_status
from app.db.repository import get_or_create_bot_config
from app.db.repository import merge_bot_runtime_status
from app.models.domain import BotConfig as BotConfigORM
from app.models.schemas import BotStatus

_UNSET = object()
DEFAULT_IDLE_ACTION = "AI 엔진 대기 중..."
DEFAULT_START_ACTION = "AI 엔진 시작됨"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_runtime_status(raw_payload: Any, *, is_running: bool) -> dict[str, Any]:
    status = extract_bot_runtime_status(raw_payload)
    latest_action = str(status.get("latest_action") or "").strip()
    if not latest_action:
        latest_action = DEFAULT_IDLE_ACTION if not is_running else DEFAULT_START_ACTION
    return {
        "last_heartbeat": status.get("last_heartbeat"),
        "last_error": status.get("last_error"),
        "latest_action": latest_action,
        "updated_at": status.get("updated_at"),
    }


async def update_bot_runtime_status(
    db: AsyncSession,
    *,
    last_heartbeat: str | None | object = _UNSET,
    last_error: str | None | object = _UNSET,
    latest_action: str | None | object = _UNSET,
    updated_at: str | None | object = _UNSET,
) -> BotConfigORM:
    bot_config = await get_or_create_bot_config(db)
    runtime_status = _normalize_runtime_status(
        bot_config.config_json,
        is_running=bool(bot_config.is_active),
    )

    if last_heartbeat is not _UNSET:
        runtime_status["last_heartbeat"] = last_heartbeat
    if last_error is not _UNSET:
        runtime_status["last_error"] = last_error
    if latest_action is not _UNSET:
        runtime_status["latest_action"] = latest_action
    runtime_status["updated_at"] = (
        updated_at if updated_at is not _UNSET else _utc_now_iso()
    )

    bot_config.config_json = merge_bot_runtime_status(bot_config.config_json, runtime_status)
    await db.commit()
    await db.refresh(bot_config)
    return bot_config


def _to_bot_status(bot_config: BotConfigORM) -> BotStatus:
    is_running = bool(bot_config.is_active)
    runtime_status = _normalize_runtime_status(bot_config.config_json, is_running=is_running)
    return BotStatus(
        running=is_running,
        last_heartbeat=runtime_status.get("last_heartbeat"),
        last_error=runtime_status.get("last_error"),
        latest_action=str(runtime_status.get("latest_action") or DEFAULT_IDLE_ACTION),
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
    bot_config = await update_bot_runtime_status(
        db,
        latest_action=DEFAULT_START_ACTION,
        last_error=None,
    )
    return _to_bot_status(bot_config)


async def stop_bot(db: AsyncSession) -> BotStatus:
    await get_or_create_bot_config(db)
    await db.execute(
        update(BotConfigORM)
        .where(BotConfigORM.id == 1)
        .values(is_active=False)
    )
    await db.commit()
    bot_config = await update_bot_runtime_status(
        db,
        latest_action=DEFAULT_IDLE_ACTION,
    )
    return _to_bot_status(bot_config)
