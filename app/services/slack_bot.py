import asyncio
import logging
import threading
from functools import wraps
from typing import Any, Callable
from uuid import uuid4

from app.core.config import settings
from app.db.live_order_control_repository import CONTROL_SOURCE_SLACK
from app.db.session import AsyncSessionLocal, engine
from app.models.schemas import BotStatus
from app.services.bot_service import get_bot_status, start_bot
from app.services.portfolio.aggregator import PortfolioService
from app.services.trading.live_order_control import (
    BlockLiveOrdersCommand,
    LiveOrderControlService,
)
from app.services.trading.live_order_submission_barrier import LiveOrderSubmissionBarrier

logger = logging.getLogger(__name__)


def _live_order_control_service() -> LiveOrderControlService:
    return LiveOrderControlService(barrier=LiveOrderSubmissionBarrier(engine))


class SlackBot:
    def __init__(self) -> None:
        self._app: Any | None = None
        self._handler: Any | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._fallback_client: Any | None = None
        self._stop_event = threading.Event()

    @property
    def _bot_token(self) -> str:
        return (settings.slack_bot_token or "").strip()

    @property
    def _app_token(self) -> str:
        return (settings.slack_app_token or "").strip()

    @property
    def _allowed_user_id(self) -> str:
        primary = (settings.slack_allowed_user_id or "").strip()
        if primary:
            return primary

        legacy = (settings.slack_allowed_user_ids or "").strip()
        if not legacy:
            return ""
        return legacy.split(",", maxsplit=1)[0].strip()

    @property
    def enabled(self) -> bool:
        return bool(self._bot_token and self._app_token and self._allowed_user_id)

    def start(self) -> None:
        if not self.enabled:
            logger.info("SlackBot 비활성화: 토큰 또는 허용 사용자 ID가 비어 있습니다.")
            return

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if not self._ensure_initialized():
                return

            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="slack-bolt-socket",
                daemon=True,
            )
            self._thread.start()
            logger.info("SlackBot Socket Mode 리스너 시작")

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            handler = self._handler
            thread = self._thread
            self._stop_event.set()

        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning("SlackBot 스레드가 timeout 내 종료되지 않았습니다.")
                self._close_handler(handler)
        elif handler is not None:
            self._close_handler(handler)

        with self._lock:
            if self._thread is thread:
                self._thread = None
            if thread is None or not thread.is_alive():
                self._handler = None
                self._app = None
                self._fallback_client = None

    def send_message(
        self,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> None:
        if not text and not blocks:
            return
        if not self._bot_token:
            logger.debug("SlackBot send_message 패스: bot token이 비어 있습니다.")
            return

        try:
            client = self._get_web_client()
            channel = self._resolve_notification_channel(client)
            if not channel:
                logger.warning("SlackBot send_message 실패: 대상 채널/유저를 찾지 못했습니다.")
                return

            payload: dict[str, Any] = {
                "channel": channel,
                "text": text or "알림",
            }
            if blocks is not None:
                payload["blocks"] = blocks
            client.chat_postMessage(**payload)
        except Exception:
            logger.exception("SlackBot 즉시 알림 발송 중 오류가 발생했습니다.")

    def _run(self) -> None:
        handler = self._handler
        if handler is None:
            return

        try:
            connect_method = getattr(handler, "connect", None)
            if not callable(connect_method):
                raise RuntimeError("Slack SocketModeHandler does not provide connect().")
            connect_method()
            self._stop_event.wait()
        except Exception:
            logger.exception("SlackBot Socket Mode 실행 중 오류가 발생했습니다.")
        finally:
            self._close_handler(handler)
            with self._lock:
                self._thread = None

    def _close_handler(self, handler: Any | None) -> None:
        if handler is None:
            return

        disconnect_method = getattr(handler, "disconnect", None)
        if callable(disconnect_method):
            try:
                disconnect_method()
            except Exception:
                logger.exception("SlackBot Socket Mode 연결 해제 중 오류가 발생했습니다.")

        close_method = getattr(handler, "close", None)
        if callable(close_method):
            try:
                close_method()
            except Exception:
                logger.exception("SlackBot Socket Mode 종료 중 오류가 발생했습니다.")

    def _ensure_initialized(self) -> bool:
        if self._handler is not None and self._app is not None:
            return True

        try:
            from slack_bolt import App
            from slack_bolt.adapter.socket_mode import SocketModeHandler
        except Exception:
            logger.exception("slack_bolt 로딩 실패: 패키지 설치 상태를 확인하세요.")
            return False

        app = App(token=self._bot_token)
        self._register_handlers(app)
        self._app = app
        self._handler = SocketModeHandler(app, self._app_token)
        return True

    def _get_web_client(self) -> Any:
        if self._app is not None and getattr(self._app, "client", None) is not None:
            return self._app.client

        if self._fallback_client is None:
            from slack_sdk import WebClient

            self._fallback_client = WebClient(token=self._bot_token)
        return self._fallback_client

    def _resolve_notification_channel(self, client: Any) -> str | None:
        preferred = self._first_csv(settings.slack_trade_channel_ids)
        if preferred:
            return self._normalize_destination(client, preferred)

        allowed_user = self._allowed_user_id
        if allowed_user:
            return self._normalize_destination(client, allowed_user)
        return None

    def _normalize_destination(self, client: Any, destination: str) -> str | None:
        target = destination.strip().upper()
        if not target:
            return None

        if target.startswith(("C", "G", "D")):
            return target

        if target.startswith("U"):
            try:
                opened = client.conversations_open(users=target)
                channel = ((opened or {}).get("channel") or {}).get("id")
                if isinstance(channel, str) and channel.strip():
                    return channel.strip()
            except Exception:
                logger.exception("Slack DM 채널 열기 실패: user=%s", target)
                return None

        return target

    @staticmethod
    def _first_csv(value: str | None) -> str | None:
        if not value:
            return None
        for item in value.split(","):
            stripped = item.strip()
            if stripped:
                return stripped
        return None

    def require_auth(self, handler: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(handler)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            ack = kwargs.get("ack")
            if callable(ack):
                try:
                    ack()
                except Exception:
                    logger.exception("Slack ack 처리 중 오류가 발생했습니다.")
                kwargs["ack"] = lambda *a, **k: None

            body = kwargs.get("body")
            user_id = self._extract_user_id(body if isinstance(body, dict) else {})
            if not self._is_authorized(user_id):
                self._reply_unauthorized(kwargs)
                return None

            return handler(*args, **kwargs)

        return wrapper

    def _register_handlers(self, app: Any) -> None:
        @app.event("app_mention")
        @self.require_auth
        def _on_app_mention(body: dict[str, Any], say: Callable[..., Any], **_: Any) -> None:
            text = str((body.get("event") or {}).get("text") or "").strip()
            if text:
                say("명령을 수신했습니다. Socket Mode 연결은 정상입니다.")

        @app.event("message")
        @self.require_auth
        def _on_message(body: dict[str, Any], say: Callable[..., Any], **_: Any) -> None:
            event = body.get("event") or {}
            if not isinstance(event, dict):
                return
            if event.get("bot_id") or event.get("subtype") == "bot_message":
                return
            text = str(event.get("text") or "").strip()
            if not text:
                return
            say("메시지를 수신했습니다.")

        @app.command("/ping")
        @self.require_auth
        def _on_ping(
            ack: Callable[..., Any],
            respond: Callable[..., Any],
            **_: Any,
        ) -> None:
            ack()
            respond("pong: Slack Socket Mode 연결 정상")

        @app.command("/status")
        @self.require_auth
        def _on_status(
            respond: Callable[..., Any],
            **_: Any,
        ) -> None:
            try:
                total_net_worth, status = asyncio.run(self._load_status_snapshot())
                blocks = self._build_status_blocks(
                    total_net_worth=total_net_worth,
                    status=status,
                )
                respond(text="봇 상태 리포트", blocks=blocks)
            except Exception:
                logger.exception("Slack /status 처리 중 오류가 발생했습니다.")
                respond("상태 조회 중 오류가 발생했습니다.")

        @app.command("/stop")
        @self.require_auth
        def _on_stop(
            body: dict[str, Any],
            respond: Callable[..., Any],
            **_: Any,
        ) -> None:
            try:
                user_id = self._extract_user_id(body)
                asyncio.run(self._execute_stop(user_id=user_id))
                respond("🛑 봇 런타임 정지와 신규 실주문 차단(BLOCK_ALL)이 완료되었습니다.")
            except Exception:
                logger.exception("Slack /stop 처리 중 오류가 발생했습니다.")
                respond(
                    "봇 정지와 실주문 차단에 실패했습니다. 성공 상태로 처리하지 않았으며 "
                    "/status로 현재 상태를 확인해 주세요."
                )

        @app.command("/start")
        @self.require_auth
        def _on_start(
            respond: Callable[..., Any],
            **_: Any,
        ) -> None:
            try:
                status = asyncio.run(self._execute_start())
                respond(
                    "🚀 분석 런타임이 다시 시작되었습니다. 실주문 차단 상태는 유지되며 "
                    "gate를 자동 재무장하지 않았습니다. "
                    f"현재 실주문 상태: {status.live_order_mode}"
                )
            except Exception:
                logger.exception("Slack /start 처리 중 오류가 발생했습니다.")
                respond("봇 시작 처리 중 오류가 발생했습니다.")

        @app.command("/briefing")
        @self.require_auth
        def _on_briefing(
            respond: Callable[..., Any],
            **_: Any,
        ) -> None:
            try:
                from app.core.scheduler import trigger_daily_ai_briefing_now

                trigger_daily_ai_briefing_now()
                respond("모닝 브리핑 생성을 시작했습니다. 잠시만 기다려 주세요.")
            except Exception:
                logger.exception("Slack /briefing 처리 중 오류가 발생했습니다.")
                respond("브리핑 생성 요청 처리 중 오류가 발생했습니다.")

    async def _load_status_snapshot(self) -> tuple[float, BotStatus]:
        async with AsyncSessionLocal() as db:
            summary = await PortfolioService(db).get_aggregated_portfolio()
            status = await get_bot_status(db)
        return summary.total_net_worth, status

    async def _execute_stop(self, *, user_id: str) -> BotStatus:
        if not self._is_authorized(user_id):
            raise PermissionError("검증되지 않은 Slack 사용자는 봇을 정지할 수 없습니다.")
        command = BlockLiveOrdersCommand(
            request_id=uuid4(),
            reason_code="MESSENGER_STOP",
            reason_text="검증된 Slack 운영자가 봇 런타임과 신규 실주문을 함께 정지했습니다.",
            source=CONTROL_SOURCE_SLACK,
            actor_ref=f"slack:{user_id}",
        )
        await _live_order_control_service().stop_bot(command)
        async with AsyncSessionLocal() as db:
            return await get_bot_status(db)

    async def _execute_start(self) -> BotStatus:
        async with AsyncSessionLocal() as db:
            return await start_bot(db)

    def _build_status_blocks(
        self,
        total_net_worth: float,
        status: BotStatus,
    ) -> list[dict[str, Any]]:
        rollout_label = "ON" if status.live_order_rollout_enabled else "OFF"
        active_operation = status.live_order_active_liquidation_operation_id or "-"
        liquidation_phase = status.live_order_liquidation_phase or "-"
        liquidation_remaining = status.live_order_liquidation_remaining or 0
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*현재 총 자산:* "
                        f"{self._format_krw(total_net_worth)}\n"
                        "*런타임 상태:* "
                        f"[{self._format_running_label(status.running)}]\n"
                        "\n*실주문 Gate*\n"
                        f"• 모드: `{status.live_order_mode}`\n"
                        f"• generation/version: "
                        f"`{status.live_order_generation}/{status.live_order_version}`\n"
                        f"• rollout: `{rollout_label}`\n"
                        f"• 활성 청산 operation: `{active_operation}`\n"
                        f"• 청산 phase/잔여: `{liquidation_phase}/{liquidation_remaining}`\n"
                        f"• 사유: {status.live_order_reason}"
                    ),
                },
            },
        ]

    def _extract_user_id(self, payload: dict[str, Any]) -> str:
        user_id = payload.get("user_id")
        if isinstance(user_id, str) and user_id.strip():
            return user_id.strip()

        event = payload.get("event")
        if isinstance(event, dict):
            event_user = event.get("user")
            if isinstance(event_user, str) and event_user.strip():
                return event_user.strip()

        user = payload.get("user")
        if isinstance(user, dict):
            nested_id = user.get("id")
            if isinstance(nested_id, str) and nested_id.strip():
                return nested_id.strip()
        if isinstance(user, str) and user.strip():
            return user.strip()

        return ""

    def _is_authorized(self, user_id: str) -> bool:
        allowed_user_id = self._allowed_user_id
        if not allowed_user_id:
            return False
        return user_id == allowed_user_id

    def _reply_unauthorized(self, kwargs: dict[str, Any]) -> None:
        respond = kwargs.get("respond")
        if callable(respond):
            try:
                respond("권한이 없습니다")
            except Exception:
                logger.exception("Slack unauthorized respond 전송 실패")
            return

        say = kwargs.get("say")
        if callable(say):
            try:
                say("권한이 없습니다")
            except Exception:
                logger.exception("Slack unauthorized say 전송 실패")

    @staticmethod
    def _format_krw(value: float) -> str:
        return f"{value:,.0f}원"

    @staticmethod
    def _format_running_label(is_running: bool) -> str:
        return "Running" if is_running else "Paused"


slack_bot = SlackBot()
