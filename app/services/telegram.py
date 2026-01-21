import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class TelegramClient:
    def __init__(
        self,
        token: str | None,
        chat_id: str | None,
        base_url: str = "https://api.telegram.org",
        timeout: float = 10.0,
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    async def send_message(self, text: str, chat_id: int | str | None = None) -> None:
        if not self.enabled:
            logger.debug("Telegram disabled; skip send")
            return
        target_chat_id = chat_id or self.chat_id
        if not target_chat_id:
            logger.debug("Telegram chat_id missing; skip send")
            return
        url = f"{self.base_url}/bot{self.token}/sendMessage"
        payload: dict[str, Any] = {"chat_id": target_chat_id, "text": text}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            await client.post(url, json=payload)

    async def get_updates(
        self,
        offset: int | None = None,
        timeout: int = 20,
    ) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        url = f"{self.base_url}/bot{self.token}/getUpdates"
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        async with httpx.AsyncClient(timeout=self.timeout + timeout) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict) or not data.get("ok"):
                logger.error("Telegram getUpdates error: %s", data)
                return []
            return data.get("result", [])


telegram = TelegramClient(settings.telegram_bot_token, settings.telegram_chat_id)
