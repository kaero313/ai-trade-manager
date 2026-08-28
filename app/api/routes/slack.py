import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

from app.api.dependencies import require_admin_token
from app.services.slack import slack_client

router = APIRouter()
logger = logging.getLogger(__name__)


class SlackTestRequest(BaseModel):
    text: str = Field(default="Trading bot Slack test message.")
    username: str | None = None
    icon_emoji: str | None = None

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "text": "Slack 연동 테스트",
                }
            ]
        }
    )


class SlackTestResponse(BaseModel):
    ok: bool
    detail: str | None = None


@router.post("/slack/test", response_model=SlackTestResponse)
async def slack_test(
    payload: SlackTestRequest,
    _admin: None = Depends(require_admin_token),
) -> SlackTestResponse:
    if not slack_client.enabled:
        raise HTTPException(
            status_code=503,
            detail="Slack 웹훅이 서버에 설정되지 않았습니다.",
        )

    try:
        await slack_client.send_message(
            text=payload.text,
            username=payload.username,
            icon_emoji=payload.icon_emoji,
        )
    except Exception as exc:
        logger.error(
            "Slack 테스트 메시지 전송에 실패했습니다.",
            extra={
                "event": "slack_test_delivery_failed",
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=502,
            detail="Slack 테스트 메시지 전송에 실패했습니다.",
        ) from None

    return SlackTestResponse(ok=True)
