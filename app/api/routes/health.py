import logging

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}


@router.get("/health/live")
async def health_live() -> dict:
    # liveness는 프로세스 생존만 확인한다. DB나 외부 의존성을 건드리지 않으므로
    # DB 장애가 프로세스 재시작으로 번지지 않는다.
    return {"status": "ok"}


@router.get("/health/ready")
async def health_ready(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    # readiness는 트래픽 수용 가능 여부를 확인한다. DB 접속 실패는 처리되지 않은
    # 500이 아니라 503으로 알려 기동 게이트가 미준비 상태로 구분하게 한다.
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        # 외부 노출 금지 계약에 따라 예외 원문·traceback 없이 타입만 남긴다.
        logger.warning("health_ready_db_unavailable error_type=%s", type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "db": "disconnected"},
        )
    return JSONResponse(content={"status": "ok", "db": "connected"})
