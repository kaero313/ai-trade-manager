import asyncio
import logging
from contextlib import suppress
from typing import Any

from app.core.config import settings
from app.db.repository import get_or_create_bot_config
from app.db.session import AsyncSessionLocal
from app.models.schemas import BotConfig as BotConfigSchema
from app.services.bot_service import get_bot_status, start_bot, stop_bot
from app.services.telegram import TelegramClient, telegram
from app.services.brokers.factory import BrokerFactory
from app.services.brokers.upbit import UpbitAPIError

logger = logging.getLogger(__name__)
broker = BrokerFactory.get_broker("UPBIT")


class TelegramBotService:
    def __init__(
        self,
        client: TelegramClient,
        poll_timeout: int = 20,
        poll_interval: int = 2,
    ) -> None:
        self.client = client
        self.poll_timeout = poll_timeout
        self.poll_interval = poll_interval
        self._offset: int | None = None
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if not self.client.enabled:
            logger.info("Telegram bot disabled; missing token")
            return
        if self._task:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="telegram-bot")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        logger.info("Telegram bot polling started")
        while not self._stop_event.is_set():
            try:
                updates = await self.client.get_updates(
                    offset=self._offset,
                    timeout=self.poll_timeout,
                )
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        self._offset = update_id + 1
                    await self._handle_update(update)
            except Exception as exc:
                logger.exception("Telegram polling error: %s", exc)
                await asyncio.sleep(self.poll_interval)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            return

        if self.client.chat_id and str(chat_id) != str(self.client.chat_id):
            logger.warning("Telegram message from unauthorized chat_id=%s", chat_id)
            return

        text = (message.get("text") or "").strip()
        if not text or not text.startswith("/"):
            return

        command, *args = text.split()
        cmd = command.split("@", 1)[0].lower()

        if cmd in ("/start", "/run"):
            async with AsyncSessionLocal() as db:
                status = await start_bot(db)
            await self.client.send_message(self._format_status(status), chat_id=chat_id)
            return

        if cmd in ("/stop", "/halt"):
            async with AsyncSessionLocal() as db:
                status = await stop_bot(db)
            await self.client.send_message(self._format_status(status), chat_id=chat_id)
            return

        if cmd in ("/status", "/health"):
            async with AsyncSessionLocal() as db:
                status = await get_bot_status(db)
            await self.client.send_message(self._format_status(status), chat_id=chat_id)
            return

        if cmd in ("/balance", "/accounts"):
            await self._handle_balance(chat_id)
            return

        if cmd in ("/pnl", "/profit"):
            await self.client.send_message("수익률 계산은 아직 미구현입니다.", chat_id=chat_id)
            return

        if cmd in ("/positions", "/pos"):
            await self.client.send_message("현재 포지션 조회는 아직 미구현입니다.", chat_id=chat_id)
            return

        if cmd in ("/setrisk",):
            await self._handle_setrisk(chat_id, args)
            return

        if cmd in ("/help", "/starthelp"):
            await self.client.send_message(self._help_text(), chat_id=chat_id)
            return

        await self.client.send_message("지원하지 않는 명령입니다. /help를 입력하세요.", chat_id=chat_id)

    async def _handle_balance(self, chat_id: int) -> None:
        if not settings.upbit_access_key or not settings.upbit_secret_key:
            await self.client.send_message(
                "Upbit 키가 설정되지 않았습니다. .env의 UPBIT_ACCESS_KEY/SECRET_KEY를 확인하세요.",
                chat_id=chat_id,
            )
            return

        try:
            accounts = await broker.get_accounts()
        except UpbitAPIError as exc:
            payload = exc.to_dict()
            await self.client.send_message(
                f"Upbit 오류: {payload.get('error_name')} {payload.get('message')}",
                chat_id=chat_id,
            )
            return

        lines = ["[잔고]"]
        for item in accounts:
            currency = item.get("currency")
            balance = item.get("balance")
            locked = item.get("locked")
            avg_buy = item.get("avg_buy_price")
            if not self._has_value(balance, locked):
                continue
            line = f"{currency}: {balance} (locked {locked})"
            if avg_buy:
                line += f" avg {avg_buy}"
            lines.append(line)

        if len(lines) == 1:
            lines.append("표시할 잔고가 없습니다.")
        await self.client.send_message("\n".join(lines), chat_id=chat_id)

    async def _handle_setrisk(self, chat_id: int, args: list[str]) -> None:
        if not args:
            await self.client.send_message(self._risk_usage(), chat_id=chat_id)
            return

        updates = {}
        for arg in args:
            if "=" not in arg:
                continue
            key, value = arg.split("=", 1)
            updates[key.strip().lower()] = value.strip()

        if not updates:
            await self.client.send_message(self._risk_usage(), chat_id=chat_id)
            return

        async with AsyncSessionLocal() as db:
            bot_config = await get_or_create_bot_config(db)
            config = BotConfigSchema.model_validate(bot_config.config_json or {})
            risk = config.risk
            changed = []

            def set_pct(field: str, raw: str) -> None:
                nonlocal risk
                try:
                    val = float(raw)
                except ValueError:
                    return
                if val > 1:
                    val = val / 100.0
                setattr(risk, field, val)
                changed.append(f"{field}={val}")

            def set_int(field: str, raw: str) -> None:
                nonlocal risk
                try:
                    val = int(raw)
                except ValueError:
                    return
                setattr(risk, field, val)
                changed.append(f"{field}={val}")

            if "daily_loss" in updates:
                set_pct("max_daily_loss_pct", updates["daily_loss"])
            if "max_capital" in updates:
                set_pct("max_capital_pct", updates["max_capital"])
            if "position" in updates:
                set_pct("position_size_pct", updates["position"])
            if "max_positions" in updates:
                set_int("max_concurrent_positions", updates["max_positions"])
            if "cooldown" in updates:
                set_int("cooldown_minutes", updates["cooldown"])

            if changed:
                config.risk = risk
                bot_config.config_json = config.model_dump()
                await db.commit()
                await self.client.send_message(
                    "리스크 설정 변경: " + ", ".join(changed),
                    chat_id=chat_id,
                )
            else:
                await self.client.send_message(self._risk_usage(), chat_id=chat_id)

    def _format_status(self, status) -> str:
        heartbeat = status.last_heartbeat or "-"
        err = status.last_error or "-"
        return f"봇 상태: {'실행 중' if status.running else '중지'}\n마지막 하트비트: {heartbeat}\n최근 오류: {err}"

    def _help_text(self) -> str:
        return (
            "명령 목록:\n"
            "/start, /stop, /status\n"
            "/balance, /pnl, /positions\n"
            "/setrisk daily_loss=5 max_capital=10 position=20 max_positions=3 cooldown=60\n"
        )

    def _risk_usage(self) -> str:
        return (
            "리스크 설정 사용법:\n"
            "/setrisk daily_loss=5 max_capital=10 position=20 max_positions=3 cooldown=60"
        )

    @staticmethod
    def _has_value(balance: Any, locked: Any) -> bool:
        try:
            return float(balance or 0) > 0 or float(locked or 0) > 0
        except (TypeError, ValueError):
            return False


telegram_bot = TelegramBotService(telegram)
