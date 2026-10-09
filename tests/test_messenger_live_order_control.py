from __future__ import annotations

from typing import Any

import pytest

from app.core.config import settings
from app.models.schemas import BotStatus
from app.services import slack_bot as slack_module
from app.services import telegram_bot as telegram_module
from app.services.slack_bot import SlackBot
from app.services.telegram_bot import TelegramBotService
from app.services.trading.live_order_submission_barrier import (
    LiveOrderSubmissionBarrierTimeoutError,
)


def _status(*, running: bool = False, mode: str = "BLOCK_ALL") -> BotStatus:
    return BotStatus(
        running=running,
        last_heartbeat="2026-07-10T12:00:00+00:00",
        last_error=None,
        latest_action="테스트 상태",
        live_order_mode=mode,
        live_order_generation=4,
        live_order_version=8,
        live_order_reason_code="MESSENGER_STOP",
        live_order_reason="검증된 메신저 운영자가 실주문을 차단했습니다.",
        live_order_source="SLACK",
        live_order_rollout_enabled=True,
        live_order_state_available=True,
    )


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback


class _SessionFactory:
    def __call__(self) -> _SessionContext:
        return _SessionContext()


class _SlackApp:
    def __init__(self) -> None:
        self.commands: dict[str, Any] = {}
        self.events: dict[str, Any] = {}

    def command(self, name: str):
        def decorator(handler):
            self.commands[name] = handler
            return handler

        return decorator

    def event(self, name: str):
        def decorator(handler):
            self.events[name] = handler
            return handler

        return decorator


class _TelegramClient:
    def __init__(self, chat_id: str | None = "42") -> None:
        self.chat_id = chat_id
        self.enabled = True
        self.messages: list[tuple[str, int | str | None]] = []

    async def send_message(
        self,
        text: str,
        chat_id: int | str | None = None,
    ) -> None:
        self.messages.append((text, chat_id))


def _telegram_message_update(
    text: str,
    *,
    chat_id: int = 42,
    user_id: int = 7,
    chat_type: str = "private",
) -> dict[str, Any]:
    return {
        "message": {
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"id": user_id, "is_bot": False},
            "text": text,
        }
    }


def _configure_slack_user(monkeypatch, user_id: str = "U123") -> None:
    monkeypatch.setattr(settings, "slack_allowed_user_id", user_id)
    monkeypatch.setattr(settings, "slack_allowed_user_ids", None)


@pytest.mark.asyncio
async def test_slack_stop_uses_control_service_with_verified_actor(monkeypatch) -> None:
    _configure_slack_user(monkeypatch)
    commands = []

    class _ControlService:
        async def stop_bot(self, command):
            commands.append(command)

    async def fake_status(_db):
        return _status()

    monkeypatch.setattr(
        slack_module,
        "_live_order_control_service",
        lambda: _ControlService(),
    )
    monkeypatch.setattr(slack_module, "AsyncSessionLocal", _SessionFactory())
    monkeypatch.setattr(slack_module, "get_bot_status", fake_status)

    result = await SlackBot()._execute_stop(user_id="U123")

    assert result.running is False
    assert result.live_order_mode == "BLOCK_ALL"
    assert len(commands) == 1
    assert commands[0].source == "SLACK"
    assert commands[0].actor_ref == "slack:U123"
    assert commands[0].reason_code == "MESSENGER_STOP"


@pytest.mark.asyncio
async def test_slack_stop_rejects_unverified_actor_before_control_service(
    monkeypatch,
) -> None:
    _configure_slack_user(monkeypatch)

    def forbidden_service():
        raise AssertionError("검증 전에는 제어 서비스를 생성하면 안 됩니다.")

    monkeypatch.setattr(slack_module, "_live_order_control_service", forbidden_service)

    with pytest.raises(PermissionError):
        await SlackBot()._execute_stop(user_id="U999")


def test_slack_stop_timeout_is_never_reported_as_success(monkeypatch) -> None:
    _configure_slack_user(monkeypatch)
    bot = SlackBot()
    app = _SlackApp()
    bot._register_handlers(app)
    responses: list[str] = []

    async def failed_stop(*, user_id: str):
        assert user_id == "U123"
        raise LiveOrderSubmissionBarrierTimeoutError(
            lock_mode="exclusive",
            timeout_seconds=1,
        )

    monkeypatch.setattr(bot, "_execute_stop", failed_stop)

    app.commands["/stop"](
        body={"user_id": "U123"},
        respond=responses.append,
    )

    assert len(responses) == 1
    assert "실패" in responses[0]
    assert "차단(BLOCK_ALL)이 완료되었습니다" not in responses[0]
    assert "/arm" not in app.commands


def test_slack_status_separates_runtime_and_order_gate() -> None:
    text = SlackBot()._build_status_blocks(
        total_net_worth=1_234_567,
        status=_status(running=True),
    )[0]["text"]["text"]

    assert "런타임 상태" in text
    assert "실주문 Gate" in text
    assert "BLOCK_ALL" in text
    assert "4/8" in text


def test_slack_start_reports_runtime_only_and_keeps_gate_blocked(monkeypatch) -> None:
    _configure_slack_user(monkeypatch)
    bot = SlackBot()
    app = _SlackApp()
    bot._register_handlers(app)
    responses: list[str] = []

    async def fake_start():
        return _status(running=True)

    monkeypatch.setattr(bot, "_execute_start", fake_start)

    app.commands["/start"](
        body={"user_id": "U123"},
        respond=responses.append,
    )

    assert len(responses) == 1
    assert "실주문 차단 상태는 유지" in responses[0]
    assert "자동 재무장하지 않았습니다" in responses[0]
    assert "BLOCK_ALL" in responses[0]


@pytest.mark.asyncio
async def test_telegram_stop_uses_control_service_with_verified_chat(monkeypatch) -> None:
    client = _TelegramClient(chat_id="42")
    service = TelegramBotService(client, allowed_user_id="7")
    commands = []

    class _ControlService:
        async def stop_bot(self, command):
            commands.append(command)

    async def fake_status(_db):
        return _status()

    monkeypatch.setattr(
        telegram_module,
        "_live_order_control_service",
        lambda: _ControlService(),
    )
    monkeypatch.setattr(telegram_module, "AsyncSessionLocal", _SessionFactory())
    monkeypatch.setattr(telegram_module, "get_bot_status", fake_status)

    await service._handle_update(_telegram_message_update("/stop"))

    assert len(commands) == 1
    assert commands[0].source == "TELEGRAM"
    assert commands[0].actor_ref == "telegram:user:7"
    assert commands[0].reason_code == "MESSENGER_STOP"
    assert "차단(BLOCK_ALL)이 완료되었습니다" in client.messages[0][0]
    assert "[런타임]" in client.messages[0][0]
    assert "[실주문 Gate]" in client.messages[0][0]


@pytest.mark.asyncio
async def test_telegram_stop_timeout_is_never_reported_as_success(monkeypatch) -> None:
    client = _TelegramClient(chat_id="42")
    service = TelegramBotService(client, allowed_user_id="7")

    class _ControlService:
        async def stop_bot(self, _command):
            raise LiveOrderSubmissionBarrierTimeoutError(
                lock_mode="exclusive",
                timeout_seconds=1,
            )

    monkeypatch.setattr(
        telegram_module,
        "_live_order_control_service",
        lambda: _ControlService(),
    )

    await service._handle_update(_telegram_message_update("/halt"))

    assert len(client.messages) == 1
    assert "실패" in client.messages[0][0]
    assert "차단(BLOCK_ALL)이 완료되었습니다" not in client.messages[0][0]


@pytest.mark.asyncio
async def test_telegram_start_is_runtime_only_and_reports_gate(monkeypatch) -> None:
    client = _TelegramClient(chat_id="42")
    service = TelegramBotService(client, allowed_user_id="7")

    async def fake_start(_db):
        return _status(running=True)

    def forbidden_control_service():
        raise AssertionError("Telegram /start는 order gate를 변경하면 안 됩니다.")

    monkeypatch.setattr(telegram_module, "AsyncSessionLocal", _SessionFactory())
    monkeypatch.setattr(telegram_module, "start_bot", fake_start)
    monkeypatch.setattr(
        telegram_module,
        "_live_order_control_service",
        forbidden_control_service,
    )

    await service._handle_update(_telegram_message_update("/start"))

    assert len(client.messages) == 1
    assert "자동 재무장하지 않으며 차단 상태를 유지" in client.messages[0][0]
    assert "[런타임]" in client.messages[0][0]
    assert "[실주문 Gate]" in client.messages[0][0]


@pytest.mark.asyncio
async def test_telegram_rejects_commands_without_configured_chat(monkeypatch) -> None:
    client = _TelegramClient(chat_id=None)
    service = TelegramBotService(client, allowed_user_id="7")

    def forbidden_control_service():
        raise AssertionError("검증되지 않은 chat에서는 제어 서비스를 생성하면 안 됩니다.")

    monkeypatch.setattr(
        telegram_module,
        "_live_order_control_service",
        forbidden_control_service,
    )

    await service._handle_update(_telegram_message_update("/stop"))

    assert client.messages == []


@pytest.mark.parametrize(
    "update",
    [
        pytest.param(
            _telegram_message_update("/stop", user_id=8),
            id="different-user",
        ),
        pytest.param(
            _telegram_message_update("/stop", chat_id=43),
            id="different-chat",
        ),
        pytest.param(
            {
                "message": {
                    "chat": {"id": 42, "type": "private"},
                    "text": "/stop",
                }
            },
            id="missing-sender",
        ),
        pytest.param(
            {
                "message": {
                    "chat": {"id": "42", "type": "private"},
                    "from": {"id": 7, "is_bot": False},
                    "text": "/stop",
                }
            },
            id="string-chat-id",
        ),
        pytest.param(
            {
                "message": {
                    "chat": {"id": True, "type": "private"},
                    "from": {"id": 7, "is_bot": False},
                    "text": "/stop",
                }
            },
            id="boolean-chat-id",
        ),
        pytest.param(
            {
                "message": {
                    "chat": {"id": 42, "type": "private"},
                    "from": {"id": "7", "is_bot": False},
                    "text": "/stop",
                }
            },
            id="string-user-id",
        ),
        pytest.param(
            {
                "message": {
                    "chat": {"id": 42, "type": "private"},
                    "from": {"id": True, "is_bot": False},
                    "text": "/stop",
                }
            },
            id="boolean-user-id",
        ),
        pytest.param(
            {
                "message": {
                    "chat": {"id": 42, "type": "private"},
                    "from": {"id": 7},
                    "text": "/stop",
                }
            },
            id="missing-is-bot",
        ),
        pytest.param(
            {
                "message": {
                    "chat": {"id": 42, "type": "private"},
                    "from": {"id": 7, "is_bot": True},
                    "text": "/stop",
                }
            },
            id="bot-sender",
        ),
        pytest.param(
            {
                "message": {
                    "chat": {"id": 42, "type": "supergroup"},
                    "from": {"id": 7, "is_bot": False},
                    "sender_chat": {"id": 42, "type": "supergroup"},
                    "text": "/stop",
                }
            },
            id="anonymous-admin",
        ),
        pytest.param(
            {
                "message": {
                    "chat": {"id": 42, "type": "supergroup"},
                    "from": {"id": 7, "is_bot": False},
                    "sender_chat": {"id": -10099, "type": "channel"},
                    "text": "/stop",
                }
            },
            id="send-as-channel",
        ),
        pytest.param(
            {
                "message": {
                    "chat": {"id": 42, "type": "channel"},
                    "from": {"id": 7, "is_bot": False},
                    "text": "/stop",
                }
            },
            id="channel-chat",
        ),
        pytest.param(
            {
                "message": {
                    "chat": {"id": 42},
                    "from": {"id": 7, "is_bot": False},
                    "text": "/stop",
                }
            },
            id="missing-chat-type",
        ),
    ],
)
@pytest.mark.asyncio
async def test_telegram_rejects_unverified_sender_before_control_service(
    monkeypatch,
    update: dict[str, Any],
) -> None:
    client = _TelegramClient(chat_id="42")
    service = TelegramBotService(client, allowed_user_id="7")

    def forbidden_control_service():
        raise AssertionError("발신자 검증 전에는 제어 서비스를 생성하면 안 됩니다.")

    monkeypatch.setattr(
        telegram_module,
        "_live_order_control_service",
        forbidden_control_service,
    )

    await service._handle_update(update)

    assert client.messages == []


@pytest.mark.parametrize("chat_type", ["private", "group", "supergroup"])
def test_telegram_accepts_verified_human_sender_in_supported_chat_type(
    chat_type: str,
) -> None:
    client = _TelegramClient(chat_id="42")
    service = TelegramBotService(client, allowed_user_id="7")
    message = _telegram_message_update("/status", chat_type=chat_type)["message"]

    actor = service._authorize_message(message)

    assert actor is not None
    assert actor.user_id == 7
    assert actor.chat_id == 42
    assert actor.actor_ref == "telegram:user:7"


@pytest.mark.parametrize("update_type", ["edited_message", "channel_post", "edited_channel_post"])
@pytest.mark.asyncio
async def test_telegram_ignores_non_message_updates(
    monkeypatch,
    update_type: str,
) -> None:
    client = _TelegramClient(chat_id="42")
    service = TelegramBotService(client, allowed_user_id="7")
    update = _telegram_message_update("/stop")
    message = update.pop("message")

    def forbidden_control_service():
        raise AssertionError("message 이외 update가 명령을 실행했습니다.")

    monkeypatch.setattr(
        telegram_module,
        "_live_order_control_service",
        forbidden_control_service,
    )

    await service._handle_update({update_type: message})

    assert client.messages == []


@pytest.mark.asyncio
async def test_telegram_rejects_command_targeted_to_another_bot(monkeypatch) -> None:
    client = _TelegramClient(chat_id="42")
    service = TelegramBotService(client, allowed_user_id="7")

    def forbidden_control_service():
        raise AssertionError("다른 봇 대상 명령이 실행됐습니다.")

    monkeypatch.setattr(
        telegram_module,
        "_live_order_control_service",
        forbidden_control_service,
    )

    await service._handle_update(_telegram_message_update("/stop@other_bot"))

    assert client.messages == []


@pytest.mark.asyncio
async def test_telegram_rejection_log_does_not_expose_identity_or_message(
    caplog,
) -> None:
    client = _TelegramClient(chat_id="987654321")
    service = TelegramBotService(client, allowed_user_id="123456789")
    caplog.set_level("WARNING", logger="app.services.telegram_bot")

    await service._handle_update(
        _telegram_message_update(
            "/stop private-command-body",
            chat_id=987654321,
            user_id=222222222,
        )
    )

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "telegram_update_rejected"
    ]
    assert len(records) == 1
    assert records[0].getMessage() == "Telegram update rejected."
    assert "987654321" not in caplog.text
    assert "222222222" not in caplog.text
    assert "private-command-body" not in caplog.text


@pytest.mark.parametrize("text", [None, 123, {}, [], "일반 대화"])
@pytest.mark.asyncio
async def test_telegram_ignores_non_command_payload_without_identity_warning(
    caplog,
    text: Any,
) -> None:
    client = _TelegramClient(chat_id="42")
    service = TelegramBotService(client, allowed_user_id="7")
    update = _telegram_message_update("/placeholder", user_id=999)
    update["message"]["text"] = text
    caplog.set_level("WARNING", logger="app.services.telegram_bot")

    await service._handle_update(update)

    assert client.messages == []
    assert not [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "telegram_update_rejected"
    ]
