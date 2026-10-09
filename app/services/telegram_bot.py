import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.db.live_order_control_repository import CONTROL_SOURCE_TELEGRAM
from app.db.repository import AI_ENTRY_SCORE_THRESHOLD_KEY
from app.db.repository import AI_MAX_BUY_WEIGHT_PCT_KEY
from app.db.repository import AI_MAX_CONCURRENT_POSITIONS_KEY
from app.db.repository import AI_MIN_CONFIDENCE_TRADE_KEY
from app.db.repository import MAX_ALLOCATION_PCT_KEY
from app.db.repository import get_system_config
from app.db.session import AsyncSessionLocal, engine
from app.models.schemas import BotStatus
from app.services.bot_service import get_bot_status, start_bot
from app.services.telegram import TelegramClient, telegram
from app.services.brokers.factory import BrokerFactory
from app.services.brokers.upbit import UpbitAPIError
from app.services.trading.live_order_control import (
    BlockLiveOrdersCommand,
    LiveOrderControlService,
)
from app.services.trading.live_order_submission_barrier import LiveOrderSubmissionBarrier
from app.services.system_config_service import SystemConfigMutation
from app.services.system_config_service import SystemConfigServiceError
from app.services.system_config_service import update_public_system_configs

logger = logging.getLogger(__name__)
broker = BrokerFactory.get_broker("UPBIT")
_ALLOWED_CHAT_TYPES = frozenset({"private", "group", "supergroup"})
_TELEGRAM_RISK_KEYS = {
    "max_allocation": MAX_ALLOCATION_PCT_KEY,
    "max_buy_weight": AI_MAX_BUY_WEIGHT_PCT_KEY,
    "max_positions": AI_MAX_CONCURRENT_POSITIONS_KEY,
    "entry_score": AI_ENTRY_SCORE_THRESHOLD_KEY,
    "min_confidence": AI_MIN_CONFIDENCE_TRADE_KEY,
}


@dataclass(frozen=True, slots=True)
class _AuthorizedTelegramActor:
    user_id: int
    chat_id: int

    @property
    def actor_ref(self) -> str:
        return f"telegram:user:{self.user_id}"


def _live_order_control_service() -> LiveOrderControlService:
    return LiveOrderControlService(barrier=LiveOrderSubmissionBarrier(engine))


class TelegramBotService:
    def __init__(
        self,
        client: TelegramClient,
        allowed_user_id: int | str | None = None,
        poll_timeout: int = 20,
        poll_interval: int = 2,
    ) -> None:
        self.client = client
        self._allowed_user_id = self._parse_configured_id(
            allowed_user_id,
            positive_only=True,
        )
        self._configured_chat_id = self._parse_configured_id(
            client.chat_id,
            positive_only=False,
        )
        self.poll_timeout = poll_timeout
        self.poll_interval = poll_interval
        self._offset: int | None = None
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    @property
    def polling_enabled(self) -> bool:
        return bool(
            self.client.enabled
            and self._allowed_user_id is not None
            and self._configured_chat_id is not None
        )

    async def start(self) -> None:
        if not self.polling_enabled:
            logger.info("Telegram bot polling disabled; required settings are missing")
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
        if not self.polling_enabled:
            return
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
                logger.error(
                    "Telegram polling failed.",
                    extra={
                        "event": "telegram_polling_failed",
                        "error_type": type(exc).__name__,
                    },
                )
                await asyncio.sleep(self.poll_interval)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return

        raw_text = message.get("text")
        if not isinstance(raw_text, str):
            return
        text = raw_text.strip()
        if not text or not text.startswith("/"):
            return

        actor = self._authorize_message(message)
        if actor is None:
            return
        chat_id = actor.chat_id

        command, *args = text.split()
        if "@" in command:
            self._log_rejected_update("targeted_command")
            return
        cmd = command.lower()

        if cmd in ("/start", "/run"):
            try:
                async with AsyncSessionLocal() as db:
                    status = await start_bot(db)
            except Exception as exc:
                self._log_command_failure("start", exc)
                await self.client.send_message(
                    "봇 런타임 시작에 실패했습니다. 성공 상태로 처리하지 않았습니다.",
                    chat_id=chat_id,
                )
                return
            await self.client.send_message(
                self._format_status(status)
                + "\n시작 명령은 실주문 gate를 자동 재무장하지 않으며 차단 상태를 유지합니다.",
                chat_id=chat_id,
            )
            return

        if cmd in ("/stop", "/halt"):
            try:
                status = await self._execute_stop(actor=actor)
            except Exception as exc:
                self._log_command_failure("stop", exc)
                await self.client.send_message(
                    "봇 정지와 실주문 차단에 실패했습니다. 성공 상태로 처리하지 않았으며 "
                    "/status로 현재 상태를 확인해 주세요.",
                    chat_id=chat_id,
                )
                return
            await self.client.send_message(
                "봇 런타임 정지와 신규 실주문 차단(BLOCK_ALL)이 완료되었습니다.\n"
                + self._format_status(status),
                chat_id=chat_id,
            )
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

        updates: dict[str, str] = {}
        for arg in args:
            if "=" not in arg:
                await self.client.send_message(self._risk_usage(), chat_id=chat_id)
                return
            key, value = arg.split("=", 1)
            normalized_key = key.strip().lower()
            if (
                normalized_key not in _TELEGRAM_RISK_KEYS
                or normalized_key in updates
                or not value.strip()
            ):
                await self.client.send_message(
                    "지원하지 않거나 중복된 리스크 설정이 포함되어 변경하지 않았습니다.\n"
                    + self._risk_usage(),
                    chat_id=chat_id,
                )
                return
            updates[normalized_key] = value.strip()

        if not updates:
            await self.client.send_message(self._risk_usage(), chat_id=chat_id)
            return

        async with AsyncSessionLocal() as db:
            mutations: list[SystemConfigMutation] = []
            for command_key, raw_value in updates.items():
                config_key = _TELEGRAM_RISK_KEYS[command_key]
                current = await get_system_config(db, config_key)
                if current is None:
                    await self.client.send_message(
                        f"필수 설정 {config_key}가 없어 변경하지 않았습니다.",
                        chat_id=chat_id,
                    )
                    return
                mutations.append(
                    SystemConfigMutation(
                        config_key=config_key,
                        config_value=raw_value,
                        expected_version=current.version,
                    )
                )
            try:
                changed = await update_public_system_configs(db, mutations)
            except SystemConfigServiceError as exc:
                await self.client.send_message(
                    f"리스크 설정을 변경하지 않았습니다: {exc}",
                    chat_id=chat_id,
                )
                return

            await self.client.send_message(
                "리스크 설정 변경: "
                + ", ".join(
                    f"{config.config_key}={config.config_value} (version={config.version})"
                    for config in changed
                ),
                chat_id=chat_id,
            )

    async def _execute_stop(self, *, actor: _AuthorizedTelegramActor) -> BotStatus:
        if (
            actor.user_id != self._allowed_user_id
            or actor.chat_id != self._configured_chat_id
        ):
            raise PermissionError("검증되지 않은 Telegram 사용자는 봇을 정지할 수 없습니다.")
        command = BlockLiveOrdersCommand(
            request_id=uuid4(),
            reason_code="MESSENGER_STOP",
            reason_text="검증된 Telegram 운영자가 봇 런타임과 신규 실주문을 함께 정지했습니다.",
            source=CONTROL_SOURCE_TELEGRAM,
            actor_ref=actor.actor_ref,
        )
        await _live_order_control_service().stop_bot(command)
        async with AsyncSessionLocal() as db:
            return await get_bot_status(db)

    def _format_status(self, status: BotStatus) -> str:
        heartbeat = status.last_heartbeat or "-"
        err = status.last_error or "-"
        rollout = "ON" if status.live_order_rollout_enabled else "OFF"
        active_operation = status.live_order_active_liquidation_operation_id or "-"
        liquidation_phase = status.live_order_liquidation_phase or "-"
        liquidation_remaining = status.live_order_liquidation_remaining or 0
        return (
            "[런타임]\n"
            f"상태: {'실행 중' if status.running else '중지'}\n"
            f"마지막 하트비트: {heartbeat}\n"
            f"최근 오류: {err}\n\n"
            "[실주문 Gate]\n"
            f"모드: {status.live_order_mode}\n"
            "generation/version: "
            f"{status.live_order_generation}/{status.live_order_version}\n"
            f"rollout: {rollout}\n"
            f"활성 청산 operation: {active_operation}\n"
            f"청산 phase/잔여: {liquidation_phase}/{liquidation_remaining}\n"
            f"사유: {status.live_order_reason}"
        )

    def _authorize_message(
        self,
        message: dict[str, Any],
    ) -> _AuthorizedTelegramActor | None:
        if "sender_chat" in message:
            self._log_rejected_update("sender_chat")
            return None

        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            self._log_rejected_update("missing_identity")
            return None

        chat_id = self._exact_int(chat.get("id"))
        user_id = self._exact_int(sender.get("id"))
        if chat_id is None or user_id is None:
            self._log_rejected_update("invalid_identity")
            return None
        if chat.get("type") not in _ALLOWED_CHAT_TYPES:
            self._log_rejected_update("invalid_chat_type")
            return None
        if sender.get("is_bot") is not False:
            self._log_rejected_update("invalid_sender_type")
            return None
        if (
            self._configured_chat_id is None
            or self._allowed_user_id is None
            or chat_id != self._configured_chat_id
            or user_id != self._allowed_user_id
        ):
            self._log_rejected_update("identity_mismatch")
            return None
        return _AuthorizedTelegramActor(user_id=user_id, chat_id=chat_id)

    @staticmethod
    def _exact_int(value: Any) -> int | None:
        return value if type(value) is int else None

    @staticmethod
    def _parse_configured_id(
        value: int | str | None,
        *,
        positive_only: bool,
    ) -> int | None:
        if type(value) is int:
            parsed = value
        elif isinstance(value, str):
            normalized = value.strip()
            digits = normalized
            if not positive_only and normalized.startswith("-"):
                digits = normalized[1:]
            if not digits or not digits.isascii() or not digits.isdigit():
                return None
            parsed = int(normalized)
        else:
            return None

        if positive_only:
            return parsed if parsed > 0 else None
        return parsed if parsed != 0 else None

    @staticmethod
    def _log_rejected_update(rejection_reason: str) -> None:
        logger.warning(
            "Telegram update rejected.",
            extra={
                "event": "telegram_update_rejected",
                "rejection_reason": rejection_reason,
            },
        )

    @staticmethod
    def _log_command_failure(command: str, exc: Exception) -> None:
        logger.error(
            "Telegram command failed.",
            extra={
                "event": "telegram_command_failed",
                "command": command,
                "error_type": type(exc).__name__,
            },
        )

    def _help_text(self) -> str:
        return (
            "명령 목록:\n"
            "/start, /stop, /status\n"
            "/balance, /pnl, /positions\n"
            "/setrisk max_allocation=30 max_buy_weight=20 max_positions=3 "
            "entry_score=60 min_confidence=75\n"
        )

    def _risk_usage(self) -> str:
        return (
            "리스크 설정 사용법:\n"
            "/setrisk max_allocation=30 max_buy_weight=20 max_positions=3 "
            "entry_score=60 min_confidence=75"
        )

    @staticmethod
    def _has_value(balance: Any, locked: Any) -> bool:
        try:
            return float(balance or 0) > 0 or float(locked or 0) > 0
        except (TypeError, ValueError):
            return False


telegram_bot = TelegramBotService(
    telegram,
    allowed_user_id=settings.telegram_allowed_user_id,
)
