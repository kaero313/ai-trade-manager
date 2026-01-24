import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class SlackClient:
    def __init__(self, webhook_url: str | None, timeout: float = 10.0) -> None:
        self.webhook_url = webhook_url
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    async def send_message(
        self,
        text: str,
        webhook_url: str | None = None,
        username: str | None = None,
        icon_emoji: str | None = None,
    ) -> None:
        url = webhook_url or self.webhook_url
        if not url:
            logger.debug("Slack webhook missing; skip send")
            return

        payload: dict[str, Any] = {"text": text}
        if username:
            payload["username"] = username
        if icon_emoji:
            payload["icon_emoji"] = icon_emoji

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()


slack_client = SlackClient(
    webhook_url=settings.slack_webhook_url,
    timeout=settings.slack_timeout,
)
