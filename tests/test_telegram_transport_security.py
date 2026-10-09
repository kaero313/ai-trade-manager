from __future__ import annotations

import logging

import pytest

from app.services import telegram as telegram_module
from app.services import telegram_bot as telegram_bot_module
from app.services.telegram import TelegramClient
from app.services.telegram_bot import TelegramBotService


class _RecordingTelegramClient:
    enabled = True
    chat_id = "42"

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_message(self, message: str, *, chat_id: int | str | None = None) -> None:
        del chat_id
        self.messages.append(message)


@pytest.mark.parametrize(
    ("token", "chat_id", "expected"),
    [
        ("bot-token", "42", True),
        (None, "42", False),
        ("", "42", False),
        ("   ", "42", False),
        ("bot-token", None, False),
        ("bot-token", "", False),
        ("bot-token", "   ", False),
    ],
)
def test_telegram_client_requires_token_and_allowed_chat_id(
    token: str | None,
    chat_id: str | None,
    expected: bool,
) -> None:
    assert TelegramClient(token=token, chat_id=chat_id).enabled is expected


@pytest.mark.parametrize(
    ("chat_id", "allowed_user_id", "expected"),
    [
        ("42", "7", True),
        ("-10042", 7, True),
        ("42", None, False),
        ("42", "", False),
        ("42", "0", False),
        ("42", "-7", False),
        ("42", "not-an-id", False),
        ("42", True, False),
        ("@operator", "7", False),
    ],
)
def test_telegram_polling_requires_numeric_chat_and_positive_user_id(
    chat_id: str,
    allowed_user_id: int | str | bool | None,
    expected: bool,
) -> None:
    client = TelegramClient(token="bot-token", chat_id=chat_id)
    service = TelegramBotService(client, allowed_user_id=allowed_user_id)

    assert service.polling_enabled is expected
    assert client.enabled is True


@pytest.mark.asyncio
async def test_disabled_telegram_client_never_opens_http_client(monkeypatch) -> None:
    class _ForbiddenAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs
            raise AssertionError("비활성 Telegram 클라이언트가 네트워크를 열었습니다.")

    monkeypatch.setattr(telegram_module.httpx, "AsyncClient", _ForbiddenAsyncClient)
    client = TelegramClient(token="bot-token", chat_id=None)

    await client.send_message("메시지", chat_id="42")
    assert await client.get_updates() == []


@pytest.mark.asyncio
async def test_telegram_bot_does_not_start_without_allowed_chat_id() -> None:
    service = TelegramBotService(
        TelegramClient(token="bot-token", chat_id=None),
        allowed_user_id="7",
    )

    await service.start()

    assert service._task is None


@pytest.mark.asyncio
async def test_telegram_bot_does_not_start_without_allowed_user_id() -> None:
    service = TelegramBotService(TelegramClient(token="bot-token", chat_id="42"))

    await service.start()

    assert service._task is None


@pytest.mark.asyncio
async def test_telegram_polling_error_does_not_log_exception_text_or_traceback(
    caplog,
) -> None:
    secret = "telegram-secret-token-in-exception"

    class _FailingClient:
        enabled = True
        chat_id = "42"

        def __init__(self) -> None:
            self.service: TelegramBotService | None = None

        async def get_updates(self, *, offset: int | None, timeout: int):
            del offset, timeout
            assert self.service is not None
            self.service._stop_event.set()
            raise RuntimeError(secret)

    client = _FailingClient()
    service = TelegramBotService(client, allowed_user_id="7", poll_interval=0)
    client.service = service
    caplog.set_level(logging.ERROR, logger="app.services.telegram_bot")

    await service._run()

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "telegram_polling_failed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.getMessage() == "Telegram polling failed."
    assert record.error_type == "RuntimeError"
    assert record.exc_info is None
    assert record.exc_text is None
    assert record.stack_info is None
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_telegram_get_updates_requests_only_new_messages(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "ok": True,
                "result": [{"update_id": 1, "message": {}}, "invalid-update"],
            }

    class _AsyncClient:
        def __init__(self, *, timeout: float) -> None:
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        async def get(self, url: str, *, params: dict[str, object]):
            captured["url"] = url
            captured["params"] = params
            return _Response()

    monkeypatch.setattr(telegram_module.httpx, "AsyncClient", _AsyncClient)
    client = TelegramClient(token="bot-token", chat_id="42")

    updates = await client.get_updates(offset=9, timeout=20)

    assert updates == [{"update_id": 1, "message": {}}]
    assert captured["params"] == {
        "timeout": 20,
        "allowed_updates": '["message"]',
        "offset": 9,
    }


@pytest.mark.asyncio
async def test_telegram_get_updates_failure_log_does_not_expose_payload(
    monkeypatch,
    caplog,
) -> None:
    secret = "telegram-response-secret"

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "ok": False,
                "error_code": 401,
                "description": secret,
            }

    class _AsyncClient:
        def __init__(self, *, timeout: float) -> None:
            del timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        async def get(self, url: str, *, params: dict[str, object]):
            del url, params
            return _Response()

    monkeypatch.setattr(telegram_module.httpx, "AsyncClient", _AsyncClient)
    caplog.set_level(logging.ERROR, logger="app.services.telegram")
    client = TelegramClient(token="bot-token", chat_id="42")

    assert await client.get_updates() == []

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "telegram_get_updates_failed"
    ]
    assert len(records) == 1
    assert records[0].getMessage() == (
        "Telegram getUpdates returned an unsuccessful response."
    )
    assert records[0].exc_info is None
    assert secret not in caplog.text
    assert "bot-token" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    [
        ["daily_loss=5"],
        ["max_allocation=20", "cooldown=60"],
        ["max_positions=3", "max_positions=4"],
        ["max_buy_weight"],
    ],
)
async def test_telegram_setrisk_rejects_legacy_unknown_and_malformed_batch_without_db_access(
    monkeypatch,
    args: list[str],
) -> None:
    def forbidden_session_factory():
        raise AssertionError("거절된 Telegram 설정 요청이 DB에 접근했습니다.")

    monkeypatch.setattr(telegram_bot_module, "AsyncSessionLocal", forbidden_session_factory)
    client = _RecordingTelegramClient()
    service = TelegramBotService(client, allowed_user_id="7")  # type: ignore[arg-type]

    await service._handle_setrisk(42, args)

    assert len(client.messages) == 1
    assert "설정" in client.messages[0] or "사용법" in client.messages[0]
