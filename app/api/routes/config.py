from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin_token
from app.db.repository import get_or_create_bot_config
from app.db.repository import merge_bot_config_metadata
from app.db.session import get_db
from app.models.domain import BotConfig as BotConfigORM
from app.models.schemas import BotConfig

router = APIRouter()


def _config_etag(version: int) -> str:
    return f'"{version}"'


def _set_config_version_headers(response: Response, version: int) -> None:
    response.headers["ETag"] = _config_etag(version)
    response.headers["X-Config-Version"] = str(version)


def _parse_if_match(raw_value: str | None) -> int:
    if raw_value is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="설정 변경에는 If-Match 헤더가 필요합니다.",
        )

    candidate = raw_value.strip()
    if candidate.startswith("W/"):
        candidate = candidate[2:].strip()
    if len(candidate) >= 2 and candidate[0] == candidate[-1] == '"':
        candidate = candidate[1:-1]
    if not candidate.isdecimal() or int(candidate) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="If-Match는 GET /config가 반환한 양의 정수 ETag여야 합니다.",
        )
    return int(candidate)


@router.get("/config", response_model=BotConfig)
async def get_config(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> BotConfig:
    bot_config = await get_or_create_bot_config(db)
    _set_config_version_headers(response, bot_config.config_version)
    return BotConfig.model_validate(bot_config.config_json or {})


@router.post("/config", response_model=BotConfig)
async def update_config(
    config: BotConfig,
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> BotConfig:
    expected_version = _parse_if_match(if_match)
    bot_config = await get_or_create_bot_config(db)
    current_version = int(bot_config.config_version)
    if expected_version != current_version:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "BOT_CONFIG_VERSION_CONFLICT",
                "expected_version": expected_version,
                "current_version": current_version,
            },
        )

    merged_config = merge_bot_config_metadata(
        config.model_dump(),
        bot_config.config_json,
    )
    result = await db.execute(
        update(BotConfigORM)
        .where(
            BotConfigORM.id == bot_config.id,
            BotConfigORM.config_version == expected_version,
        )
        .values(
            config_json=merged_config,
            config_version=BotConfigORM.config_version + 1,
        )
        .returning(BotConfigORM.config_version)
    )
    updated_version = result.scalar_one_or_none()
    if updated_version is None:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "BOT_CONFIG_VERSION_CONFLICT",
                "expected_version": expected_version,
            },
        )
    await db.commit()
    _set_config_version_headers(response, updated_version)
    return BotConfig.model_validate(merged_config)
