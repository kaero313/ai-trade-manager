from __future__ import annotations

import logging
from inspect import signature
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.api.routes import slack as slack_route
from app.core.config import settings
from app.core.logging import configure_http_client_logging
from app.services import slack as slack_service
from app.services.slack import SlackClient


class _SlackClient:
    def __init__(self, *, enabled: bool = True, error: Exception | None = None) -> None:
        self.enabled = enabled
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def send_message(
        self,
        *,
        text: str,
        username: str | None = None,
        icon_emoji: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "text": text,
                "username": username,
                "icon_emoji": icon_emoji,
            }
        )
        if self.error is not None:
            raise self.error


def _test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(slack_route.router, prefix="/api")
    return app


def test_slack_client_does_not_expose_webhook_override() -> None:
    assert "webhook_url" not in signature(SlackClient.send_message).parameters


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 500])
async def test_slack_client_does_not_log_webhook_secret(
    monkeypatch,
    caplog,
    status_code: int,
) -> None:
    secret_url = "https://hooks.slack.com/services/T000/B000/secret-token"
    original_async_client = httpx.AsyncClient

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    def client_factory(*args, **kwargs):
        return original_async_client(
            *args,
            **kwargs,
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(slack_service.httpx, "AsyncClient", client_factory)
    configure_http_client_logging(logging.INFO)
    caplog.set_level(logging.INFO)
    client = SlackClient(secret_url)

    if status_code >= 400:
        with pytest.raises(httpx.HTTPStatusError):
            await client.send_message("보안 로그 테스트")
    else:
        await client.send_message("보안 로그 테스트")

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
    assert secret_url not in caplog.text
    assert "secret-token" not in caplog.text


async def _post_slack_test(
    payload: dict[str, Any],
    *,
    admin_token: str | None = None,
) -> httpx.Response:
    headers = {"X-Admin-Token": admin_token} if admin_token is not None else {}
    transport = httpx.ASGITransport(app=_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/slack/test", json=payload, headers=headers)


@pytest.mark.asyncio
async def test_slack_test_requires_admin_authentication(monkeypatch) -> None:
    client = _SlackClient()
    monkeypatch.setattr(settings, "admin_api_token", "server-admin-token")
    monkeypatch.setattr(slack_route, "slack_client", client)

    missing_response = await _post_slack_test({"text": "테스트"})
    mismatch_response = await _post_slack_test(
        {"text": "테스트"},
        admin_token="wrong-token",
    )

    assert missing_response.status_code == 401
    assert mismatch_response.status_code == 403
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra_field",
    [
        {"webhook_url": "https://attacker.invalid/slack"},
        {"unexpected": "value"},
    ],
)
async def test_slack_test_rejects_all_additional_fields(
    monkeypatch,
    extra_field: dict[str, str],
) -> None:
    client = _SlackClient()
    monkeypatch.setattr(settings, "admin_api_token", "server-admin-token")
    monkeypatch.setattr(slack_route, "slack_client", client)

    response = await _post_slack_test(
        {"text": "테스트", **extra_field},
        admin_token="server-admin-token",
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"
    assert client.calls == []


@pytest.mark.asyncio
async def test_slack_test_uses_only_server_configured_client(monkeypatch) -> None:
    client = _SlackClient()
    monkeypatch.setattr(settings, "admin_api_token", "server-admin-token")
    monkeypatch.setattr(slack_route, "slack_client", client)

    response = await _post_slack_test(
        {
            "text": "서버 설정 웹훅 테스트",
            "username": "AI Trade Manager",
            "icon_emoji": ":chart_with_upwards_trend:",
        },
        admin_token="server-admin-token",
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "detail": None}
    assert client.calls == [
        {
            "text": "서버 설정 웹훅 테스트",
            "username": "AI Trade Manager",
            "icon_emoji": ":chart_with_upwards_trend:",
        }
    ]
    assert "webhook_url" not in slack_route.SlackTestRequest.model_fields


@pytest.mark.asyncio
async def test_slack_test_does_not_expose_delivery_error_details(
    monkeypatch,
    caplog,
) -> None:
    secret_error = "https://hooks.slack.com/services/secret-token"
    client = _SlackClient(error=RuntimeError(secret_error))
    monkeypatch.setattr(settings, "admin_api_token", "server-admin-token")
    monkeypatch.setattr(slack_route, "slack_client", client)
    caplog.set_level(logging.ERROR, logger=slack_route.logger.name)

    response = await _post_slack_test(
        {"text": "오류 응답 테스트"},
        admin_token="server-admin-token",
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Slack 테스트 메시지 전송에 실패했습니다."}
    assert secret_error not in response.text
    assert len(caplog.records) == 1
    assert caplog.records[0].event == "slack_test_delivery_failed"
    assert caplog.records[0].error_type == "RuntimeError"
    assert caplog.records[0].exc_info is None
    assert secret_error not in caplog.text


@pytest.mark.asyncio
async def test_slack_test_reports_missing_server_configuration(monkeypatch) -> None:
    client = _SlackClient(enabled=False)
    monkeypatch.setattr(settings, "admin_api_token", "server-admin-token")
    monkeypatch.setattr(slack_route, "slack_client", client)

    response = await _post_slack_test(
        {"text": "테스트"},
        admin_token="server-admin-token",
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Slack 웹훅이 서버에 설정되지 않았습니다."}
    assert client.calls == []
