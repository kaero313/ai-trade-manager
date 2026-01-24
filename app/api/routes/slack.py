from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.slack import slack_client

router = APIRouter()


class SlackTestRequest(BaseModel):
    text: str = Field(default="Trading bot Slack test message.")
    webhook_url: str | None = None
    username: str | None = None
    icon_emoji: str | None = None


class SlackTestResponse(BaseModel):
    ok: bool
    detail: str | None = None


@router.post("/slack/test", response_model=SlackTestResponse)
async def slack_test(payload: SlackTestRequest) -> SlackTestResponse:
    if not slack_client.enabled and not payload.webhook_url:
        raise HTTPException(
            status_code=400,
            detail="Slack webhook not configured. Set SLACK_WEBHOOK_URL or pass webhook_url.",
        )

    try:
        await slack_client.send_message(
            text=payload.text,
            webhook_url=payload.webhook_url,
            username=payload.username,
            icon_emoji=payload.icon_emoji,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return SlackTestResponse(ok=True)
