import asyncio

import pytest
from fastapi import HTTPException

from app.api.dependencies import require_admin_token
from app.core.config import settings


def test_admin_token_missing_server_config_returns_503(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(require_admin_token(x_admin_token="token"))

    assert exc_info.value.status_code == 503


def test_admin_token_missing_request_returns_401(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "server-token")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(require_admin_token())

    assert exc_info.value.status_code == 401


def test_admin_token_mismatch_returns_403(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "server-token")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(require_admin_token(x_admin_token="wrong-token"))

    assert exc_info.value.status_code == 403


def test_admin_token_accepts_x_admin_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "server-token")

    asyncio.run(require_admin_token(x_admin_token="server-token"))


def test_admin_token_accepts_bearer_authorization(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "server-token")

    asyncio.run(require_admin_token(authorization="Bearer server-token"))
