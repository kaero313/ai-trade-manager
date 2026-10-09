import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes import status as status_route
from app.core.config import settings
from app.models.schemas import (
    AdminReauthRequest,
    EnableLiveTradingModeRequest,
    EnablePaperTradingModeRequest,
    TradingModeStatus,
)


def test_reauth_body_does_not_accept_admin_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "fresh-admin-token")
    monkeypatch.setattr(
        settings,
        "admin_reauth_signing_secret",
        "9M5yG2!qR7#vX4@kL8$pN6^tB3&zC1*wH0+sD",
    )
    assert "admin_token" not in AdminReauthRequest.model_fields

    response = asyncio.run(
        status_route.reauthenticate_admin_endpoint(
            AdminReauthRequest(purpose="ENABLE_LIVE_TRADING"),
            admin_token="fresh-admin-token",
        )
    )

    assert response.reauth_proof
    assert response.expires_at > datetime.now(UTC)
    assert "fresh-admin-token" not in response.reauth_proof


def test_reauth_without_separate_strong_signing_secret_returns_503(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "fresh-admin-token")
    monkeypatch.setattr(settings, "admin_reauth_signing_secret", None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            status_route.reauthenticate_admin_endpoint(
                AdminReauthRequest(purpose="ENABLE_LIVE_TRADING"),
                admin_token="fresh-admin-token",
            )
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error_code"] == "ADMIN_REAUTH_UNAVAILABLE"


def test_live_mode_endpoint_builds_expected_snapshot_command(monkeypatch) -> None:
    captured = []

    class _Service:
        async def enable_live(self, command):
            captured.append(command)
            return SimpleNamespace()

    async def current_status(_db, **_kwargs):
        return TradingModeStatus(
            mode="live",
            version=2,
            state_available=True,
            mirror_consistent=True,
        )

    monkeypatch.setattr(status_route, "_trading_mode_control_service", lambda: _Service())
    monkeypatch.setattr(status_route, "get_trading_mode_status", current_status)
    request_id = uuid4()
    response = asyncio.run(
        status_route.enable_live_trading_mode_endpoint(
            EnableLiveTradingModeRequest(
                expected_version=1,
                expected_gate_generation=3,
                expected_gate_version=5,
                reason="운영자 검증을 모두 마쳐 live 모드를 전환합니다.",
                confirmation="ENABLE_LIVE_TRADING",
                reauth_proof="signed-proof",
            ),
            idempotency_key=str(request_id),
            db=object(),
            _admin=None,
        )
    )

    assert response.mode == "live"
    assert str(captured[0].request_id) == str(request_id)
    assert captured[0].expected_gate_generation == 3
    assert captured[0].expected_gate_version == 5


def test_paper_mode_endpoint_does_not_require_reauth(monkeypatch) -> None:
    captured = []

    class _Service:
        async def enable_paper(self, command):
            captured.append(command)
            return SimpleNamespace()

    async def current_status(_db, **_kwargs):
        return TradingModeStatus(
            mode="paper",
            version=3,
            state_available=True,
            mirror_consistent=True,
        )

    monkeypatch.setattr(status_route, "_trading_mode_control_service", lambda: _Service())
    monkeypatch.setattr(status_route, "get_trading_mode_status", current_status)
    response = asyncio.run(
        status_route.enable_paper_trading_mode_endpoint(
            EnablePaperTradingModeRequest(
                expected_version=2,
                reason="운영자 요청으로 안전한 paper 모드로 전환합니다.",
            ),
            idempotency_key=str(uuid4()),
            db=object(),
            _admin=None,
        )
    )

    assert response.mode == "paper"
    assert captured[0].expected_version == 2
    assert not hasattr(captured[0], "reauth_proof")


def test_trading_mode_conflict_maps_to_http_409(monkeypatch) -> None:
    async def current_status(_db, **_kwargs):
        return TradingModeStatus()

    async def gate_status(_db, **_kwargs):
        return status_route.LiveOrderGateStatus()

    async def failed_operation():
        error = status_route.TradingModeControlServiceError(
            "mode version conflict",
            error_code="TRADING_MODE_VERSION_CONFLICT",
        )
        raise error

    monkeypatch.setattr(status_route, "get_trading_mode_status", current_status)
    monkeypatch.setattr(status_route, "get_live_order_gate_status", gate_status)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            status_route._execute_trading_mode_command(
                failed_operation(),
                object(),
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "TRADING_MODE_VERSION_CONFLICT"
