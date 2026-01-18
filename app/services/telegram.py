import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class TelegramClient:
    def __init__(self, token: str | None, chat_id: str | None) -> None:
        self.token = token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    async def send_message(self, text: str) -> None:
        if not self.enabled:
            logger.debug("Telegram disabled; skip send")
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload: dict[str, Any] = {"chat_id": self.chat_id, "text": text}
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload)


telegram = TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id)
