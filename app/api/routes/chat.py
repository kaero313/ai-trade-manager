import json
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduler import reload_scheduler_jobs
from app.db.repository import AI_BRIEFING_TIME_KEY
from app.db.repository import AUTONOMOUS_AI_INTERVAL_HOURS_KEY
from app.db.repository import AUTONOMOUS_AI_INTERVAL_MINUTES_KEY
from app.db.repository import NEWS_INTERVAL_HOURS_KEY
from app.db.repository import SENTIMENT_INTERVAL_MINUTES_KEY
from app.db.repository import bulk_upsert_system_configs
from app.db.repository import get_chat_sessions
from app.db.repository import get_recent_chat_messages
from app.db.session import get_db
from app.models.schemas import ChatApproveRequest
from app.models.schemas import ChatMessageCreateRequest
from app.models.schemas import ChatMessageItem
from app.models.schemas import ChatSessionCreateResponse
from app.models.schemas import ChatSessionItem
from app.models.schemas import SystemConfigItem
from app.services.chat.orchestrator import run_chat_stream

router = APIRouter()
logger = logging.getLogger(__name__)

SCHEDULER_CONFIG_KEYS = {
    NEWS_INTERVAL_HOURS_KEY,
    SENTIMENT_INTERVAL_MINUTES_KEY,
    AI_BRIEFING_TIME_KEY,
    AUTONOMOUS_AI_INTERVAL_HOURS_KEY,
    AUTONOMOUS_AI_INTERVAL_MINUTES_KEY,
}


def _serialize_system_configs(configs: list[object]) -> list[SystemConfigItem]:
    return [
        SystemConfigItem(
            id=config.id,
            config_key=config.config_key,
            config_value=config.config_value,
            description=config.description,
        )
        for config in configs
    ]


def _to_sse_payload(event: dict[str, str]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


@router.post("/sessions", response_model=ChatSessionCreateResponse)
async def create_chat_session() -> ChatSessionCreateResponse:
    return ChatSessionCreateResponse(session_id=str(uuid4()))


@router.get("/sessions", response_model=list[ChatSessionItem])
async def list_chat_sessions(db: AsyncSession = Depends(get_db)) -> list[ChatSessionItem]:
    sessions = await get_chat_sessions(db)
    return [ChatSessionItem.model_validate(session) for session in sessions]


@router.post("/sessions/{session_id}/messages")
async def stream_chat_messages(
    session_id: str,
    payload: ChatMessageCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    normalized_session_id = session_id.strip()
    normalized_content = payload.content.strip()

    if not normalized_session_id:
        raise HTTPException(status_code=400, detail="session_id가 비어 있습니다.")
    if not normalized_content:
        raise HTTPException(status_code=400, detail="메시지 내용이 비어 있습니다.")

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in run_chat_stream(normalized_session_id, normalized_content, db):
                yield _to_sse_payload(event)
        except Exception as exc:
            logger.error("SSE 스트림 처리 중 예외 발생", exc_info=True)
            yield _to_sse_payload({"type": "error", "agent_name": "system", "content": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageItem])
async def get_chat_session_messages(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[ChatMessageItem]:
    normalized_session_id = session_id.strip()
    if not normalized_session_id:
        raise HTTPException(status_code=400, detail="session_id가 비어 있습니다.")

    messages = await get_recent_chat_messages(db, normalized_session_id, limit=50)
    return [ChatMessageItem.model_validate(message) for message in messages]


@router.post("/sessions/{session_id}/approve", response_model=list[SystemConfigItem])
async def approve_chat_config_change(
    session_id: str,
    payload: ChatApproveRequest,
    db: AsyncSession = Depends(get_db),
) -> list[SystemConfigItem]:
    normalized_session_id = session_id.strip()
    normalized_config_key = payload.config_key.strip()

    if not normalized_session_id:
        raise HTTPException(status_code=400, detail="session_id가 비어 있습니다.")
    if not normalized_config_key:
        raise HTTPException(status_code=400, detail="config_key가 비어 있습니다.")

    configs = await bulk_upsert_system_configs(
        db,
        [(normalized_config_key, payload.config_value)],
    )

    if normalized_config_key in SCHEDULER_CONFIG_KEYS:
        try:
            await reload_scheduler_jobs()
        except Exception:
            logger.error(
                "채팅 승인 기반 시스템 설정 반영 후 스케줄러 재로드에 실패했습니다.",
                exc_info=True,
            )

    return _serialize_system_configs(configs)
