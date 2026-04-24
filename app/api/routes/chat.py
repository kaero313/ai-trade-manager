import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduler import reload_scheduler_jobs
from app.db.repository import AI_BRIEFING_TIME_KEY
from app.db.repository import AUTONOMOUS_AI_INTERVAL_HOURS_KEY
from app.db.repository import AUTONOMOUS_AI_INTERVAL_MINUTES_KEY
from app.db.repository import NEWS_INTERVAL_HOURS_KEY
from app.db.repository import SENTIMENT_INTERVAL_MINUTES_KEY
from app.db.repository import bulk_upsert_system_configs
from app.db.repository import create_chat_session_record
from app.db.repository import delete_chat_session_record
from app.db.repository import get_chat_session_record
from app.db.repository import get_chat_sessions
from app.db.repository import get_recent_chat_messages
from app.db.session import get_db
from app.models.domain import ChatSessionSurface
from app.models.schemas import ChatApproveRequest
from app.models.schemas import ChatMessageCreateRequest
from app.models.schemas import ChatMessageItem
from app.models.schemas import ChatSessionCreateRequest
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


async def _get_required_chat_session_id(
    db: AsyncSession,
    session_id: str,
) -> str:
    normalized_session_id = session_id.strip()
    if not normalized_session_id:
        raise HTTPException(status_code=400, detail="session_id 는 비어 있을 수 없습니다.")

    session = await get_chat_session_record(db, normalized_session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="채팅 세션을 찾을 수 없습니다.")

    return normalized_session_id


@router.post("/sessions", response_model=ChatSessionCreateResponse)
async def create_chat_session(
    payload: ChatSessionCreateRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ChatSessionCreateResponse:
    surface = payload.surface if payload is not None else ChatSessionSurface.AI_BANKER
    session = await create_chat_session_record(db, surface)
    return ChatSessionCreateResponse(session_id=session.session_id)


@router.get("/sessions", response_model=list[ChatSessionItem])
async def list_chat_sessions(
    surface: ChatSessionSurface = Query(default=ChatSessionSurface.AI_BANKER),
    db: AsyncSession = Depends(get_db),
) -> list[ChatSessionItem]:
    sessions = await get_chat_sessions(db, surface)
    return [ChatSessionItem.model_validate(session) for session in sessions]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    normalized_session_id = await _get_required_chat_session_id(db, session_id)
    await delete_chat_session_record(db, normalized_session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{session_id}/messages")
async def stream_chat_messages(
    session_id: str,
    payload: ChatMessageCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    normalized_session_id = await _get_required_chat_session_id(db, session_id)
    normalized_content = payload.content.strip()

    if not normalized_content:
        raise HTTPException(status_code=400, detail="메시지 내용은 비어 있을 수 없습니다.")

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in run_chat_stream(normalized_session_id, normalized_content, db):
                yield _to_sse_payload(event)
        except Exception as exc:
            logger.error("SSE 스트림 처리 중 예외가 발생했습니다.", exc_info=True)
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
    normalized_session_id = await _get_required_chat_session_id(db, session_id)
    messages = await get_recent_chat_messages(db, normalized_session_id, limit=50)
    return [ChatMessageItem.model_validate(message) for message in messages]


@router.post("/sessions/{session_id}/approve", response_model=list[SystemConfigItem])
async def approve_chat_config_change(
    session_id: str,
    payload: ChatApproveRequest,
    db: AsyncSession = Depends(get_db),
) -> list[SystemConfigItem]:
    await _get_required_chat_session_id(db, session_id)
    normalized_config_key = payload.config_key.strip()

    if not normalized_config_key:
        raise HTTPException(status_code=400, detail="config_key 는 비어 있을 수 없습니다.")

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
