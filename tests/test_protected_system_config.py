import asyncio

import pytest
from fastapi import HTTPException

from app.api.routes import chat as chat_route
from app.api.routes import configs as configs_route
from app.db.repository import (
    LIVE_ORDER_V2_ENABLED_KEY,
    TRADING_MODE_KEY,
    ProtectedSystemConfigError,
    bulk_upsert_system_configs,
    upsert_system_config,
)
from app.models.schemas import ChatApproveRequest, SystemConfigUpdateItem


class _NeverUsedSession:
    def __getattr__(self, name: str):
        raise AssertionError(f"보호 key 거절 전에 DB 접근이 발생했습니다: {name}")


@pytest.mark.parametrize(
    ("config_key", "config_value"),
    [
        (LIVE_ORDER_V2_ENABLED_KEY, "true"),
        (TRADING_MODE_KEY, "live"),
    ],
)
def test_common_repository_rejects_protected_trading_control_keys(
    config_key: str,
    config_value: str,
) -> None:
    db = _NeverUsedSession()

    with pytest.raises(ProtectedSystemConfigError):
        asyncio.run(
            upsert_system_config(
                db,  # type: ignore[arg-type]
                config_key,
                config_value,
            )
        )
    with pytest.raises(ProtectedSystemConfigError):
        asyncio.run(
            bulk_upsert_system_configs(
                db,  # type: ignore[arg-type]
                [(config_key, config_value)],
            )
        )


@pytest.mark.parametrize(
    ("config_key", "config_value"),
    [
        (LIVE_ORDER_V2_ENABLED_KEY, "true"),
        (TRADING_MODE_KEY, "live"),
    ],
)
def test_system_config_api_maps_protected_key_to_conflict(
    config_key: str,
    config_value: str,
) -> None:
    payload = [
        SystemConfigUpdateItem(
            config_key=config_key,
            config_value=config_value,
            expected_version=1,
        )
    ]

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            configs_route.update_system_configs(
                payload,
                _NeverUsedSession(),  # type: ignore[arg-type]
                None,
            )
        )

    assert exc_info.value.status_code == 409


@pytest.mark.parametrize(
    ("config_key", "config_value"),
    [
        (LIVE_ORDER_V2_ENABLED_KEY, "true"),
        (TRADING_MODE_KEY, "live"),
    ],
)
def test_chat_approval_cannot_change_protected_trading_control(
    monkeypatch,
    config_key: str,
    config_value: str,
) -> None:
    async def session_exists(_db, session_id: str) -> str:
        return session_id

    monkeypatch.setattr(chat_route, "_get_required_chat_session_id", session_exists)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            chat_route.approve_chat_config_change(
                "chat-session",
                ChatApproveRequest(
                    config_key=config_key,
                    config_value=config_value,
                    expected_version=1,
                ),
                _NeverUsedSession(),  # type: ignore[arg-type]
                None,
            )
        )

    assert exc_info.value.status_code == 409
