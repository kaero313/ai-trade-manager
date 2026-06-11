import threading

from app.core.config import settings
from app.services.slack_bot import SlackBot


class FakeSocketModeHandler:
    def __init__(self) -> None:
        self.connected = threading.Event()
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.close_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1
        self.connected.set()

    def disconnect(self) -> None:
        self.disconnect_calls += 1

    def close(self) -> None:
        self.close_calls += 1


def _configure_slack_env(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setattr(settings, "SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setattr(settings, "SLACK_ALLOWED_USER_ID", "U123")
    monkeypatch.setattr(settings, "slack_bot_token", None)
    monkeypatch.setattr(settings, "slack_app_token", None)
    monkeypatch.setattr(settings, "slack_allowed_user_ids", None)


def test_slack_bot_start_uses_connect_and_keeps_thread_alive(monkeypatch) -> None:
    _configure_slack_env(monkeypatch)
    bot = SlackBot()
    handler = FakeSocketModeHandler()
    bot._app = object()
    bot._handler = handler

    bot.start()

    assert handler.connected.wait(timeout=2)
    assert handler.connect_calls == 1
    assert bot._thread is not None
    assert bot._thread.is_alive()

    bot.stop(timeout=2)

    assert handler.disconnect_calls >= 1
    assert handler.close_calls >= 1
    assert bot._thread is None
    assert bot._handler is None
    assert bot._app is None


def test_slack_bot_start_does_not_duplicate_alive_listener(monkeypatch) -> None:
    _configure_slack_env(monkeypatch)
    bot = SlackBot()
    handler = FakeSocketModeHandler()
    bot._app = object()
    bot._handler = handler

    bot.start()
    assert handler.connected.wait(timeout=2)

    bot.start()

    assert handler.connect_calls == 1
    bot.stop(timeout=2)


def test_slack_bot_start_skips_when_required_env_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SLACK_BOT_TOKEN", "")
    monkeypatch.setattr(settings, "SLACK_APP_TOKEN", "")
    monkeypatch.setattr(settings, "SLACK_ALLOWED_USER_ID", "")
    monkeypatch.setattr(settings, "slack_bot_token", None)
    monkeypatch.setattr(settings, "slack_app_token", None)
    monkeypatch.setattr(settings, "slack_allowed_user_ids", None)
    bot = SlackBot()
    initialized = False

    def fail_if_called() -> bool:
        nonlocal initialized
        initialized = True
        return True

    bot._ensure_initialized = fail_if_called

    bot.start()

    assert initialized is False
    assert bot._thread is None
