from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes import chat as chat_route
from app.api.routes import configs as configs_route
from app.db.repository import MAX_ALLOCATION_PCT_KEY
from app.db.repository import AI_PROVIDER_STATUS_KEY
from app.db.repository import SLACK_PORTFOLIO_ALERT_SETTINGS_KEY
from app.models.schemas import AIProviderStatusResetRequest
from app.models.schemas import ChatApproveRequest
from app.models.schemas import SystemConfigUpdateItem
from app.services.chat import tools as chat_tools_module
from app.services.chat.tools import build_chat_tools
from app.services.system_config_service import SystemConfigMutation
from app.services.system_config_service import SystemConfigConflictError


class _AsyncContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback


def _config(
    key: str = MAX_ALLOCATION_PCT_KEY,
    value: str = "25",
    version: int = 2,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        config_key=key,
        config_value=value,
        description=None,
        version=version,
    )


@pytest.mark.parametrize("invalid_version", [True, False, 1.0, "1"])
@pytest.mark.parametrize(
    "schema",
    [
        lambda version: SystemConfigUpdateItem(
            config_key=MAX_ALLOCATION_PCT_KEY,
            config_value="20",
            expected_version=version,
        ),
        lambda version: AIProviderStatusResetRequest(expected_version=version),
        lambda version: ChatApproveRequest(
            config_key=MAX_ALLOCATION_PCT_KEY,
            config_value="20",
            expected_version=version,
        ),
    ],
)
def test_expected_version_request_fields_are_strict_integers(
    invalid_version: Any,
    schema: Any,
) -> None:
    with pytest.raises(ValidationError):
        schema(invalid_version)


@pytest.mark.asyncio
async def test_scheduler_reload_failure_reports_saved_state_truthfully(monkeypatch) -> None:
    saved = _config()

    async def update(_db: object, _mutations: list[SystemConfigMutation]) -> list[Any]:
        return [saved]

    async def list_configs(_db: object) -> list[Any]:
        return [saved]

    async def fail_reload() -> None:
        raise RuntimeError("reload failed")

    monkeypatch.setattr(configs_route, "update_public_system_configs", update)
    monkeypatch.setattr(configs_route, "list_system_configs", list_configs)
    monkeypatch.setattr(configs_route, "reload_scheduler_jobs", fail_reload)

    with pytest.raises(HTTPException) as exc_info:
        await configs_route.update_system_configs(
            [
                SystemConfigUpdateItem(
                    config_key="news_interval_hours",
                    config_value="12",
                    expected_version=1,
                )
            ],
            object(),  # type: ignore[arg-type]
            None,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["saved"] is True
    assert exc_info.value.detail["code"] == "SCHEDULER_RELOAD_FAILED"


@pytest.mark.asyncio
async def test_system_config_route_rejects_whitespace_key_before_reload() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await configs_route.update_system_configs(
            [
                SystemConfigUpdateItem(
                    config_key=" news_interval_hours ",
                    config_value="12",
                    expected_version=1,
                )
            ],
            object(),  # type: ignore[arg-type]
            None,
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_chat_approval_rejects_whitespace_key(monkeypatch) -> None:
    async def session_exists(_db: object, session_id: str) -> str:
        return session_id

    async def forbidden_update(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise AssertionError("공백 key가 중앙 설정 writer까지 전달되었습니다.")

    monkeypatch.setattr(chat_route, "_get_required_chat_session_id", session_exists)
    monkeypatch.setattr(chat_route, "update_public_system_configs", forbidden_update)

    with pytest.raises(HTTPException) as exc_info:
        await chat_route.approve_chat_config_change(
            "session-1",
            ChatApproveRequest(
                config_key=f" {MAX_ALLOCATION_PCT_KEY}",
                config_value="20",
                expected_version=1,
            ),
            object(),  # type: ignore[arg-type]
            None,
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("config_key", ["unknown_config", AI_PROVIDER_STATUS_KEY])
async def test_system_config_route_rejects_unknown_and_internal_keys(
    config_key: str,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await configs_route.update_system_configs(
            [
                SystemConfigUpdateItem(
                    config_key=config_key,
                    config_value="{}",
                    expected_version=1,
                )
            ],
            object(),  # type: ignore[arg-type]
            None,
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_system_config_route_maps_stale_version_to_conflict(monkeypatch) -> None:
    async def stale(_db: object, _mutations: list[SystemConfigMutation]) -> list[Any]:
        raise SystemConfigConflictError("stale", config_key=MAX_ALLOCATION_PCT_KEY)

    monkeypatch.setattr(configs_route, "update_public_system_configs", stale)
    with pytest.raises(HTTPException) as exc_info:
        await configs_route.update_system_configs(
            [
                SystemConfigUpdateItem(
                    config_key=MAX_ALLOCATION_PCT_KEY,
                    config_value="20",
                    expected_version=1,
                )
            ],
            object(),  # type: ignore[arg-type]
            None,
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_ai_banker_proposal_freezes_current_value_and_version(monkeypatch) -> None:
    current = _config(value="30", version=7)

    async def get_config(_db: object, config_key: str) -> Any:
        assert config_key == MAX_ALLOCATION_PCT_KEY
        return current

    monkeypatch.setattr(chat_tools_module, "AsyncSessionLocal", _AsyncContext)
    monkeypatch.setattr(chat_tools_module, "get_system_config", get_config)
    propose = next(tool for tool in build_chat_tools("session-1") if tool.name == "propose_config_change")

    raw_result = await propose.ainvoke(
        {"config_key": MAX_ALLOCATION_PCT_KEY, "new_value": "025.00"}
    )
    result = json.loads(raw_result)

    assert result["config_key"] == MAX_ALLOCATION_PCT_KEY
    assert result["current_value"] == "30"
    assert result["new_value"] == "25"
    assert result["expected_version"] == 7
    assert result["requires_approval"] is True


@pytest.mark.asyncio
async def test_ai_banker_slack_settings_approval_reloads_scheduler(monkeypatch) -> None:
    saved = _config(SLACK_PORTFOLIO_ALERT_SETTINGS_KEY, "{}", 2)
    reloaded = False

    async def session_exists(_db: object, session_id: str) -> str:
        return session_id

    async def update(_db: object, _mutations: list[SystemConfigMutation]) -> list[Any]:
        return [saved]

    async def list_configs(_db: object) -> list[Any]:
        return [saved]

    async def reload_scheduler() -> None:
        nonlocal reloaded
        reloaded = True

    monkeypatch.setattr(chat_route, "_get_required_chat_session_id", session_exists)
    monkeypatch.setattr(chat_route, "update_public_system_configs", update)
    monkeypatch.setattr(chat_route, "list_system_configs", list_configs)
    monkeypatch.setattr(chat_route, "reload_scheduler_jobs", reload_scheduler)

    result = await chat_route.approve_chat_config_change(
        "session-1",
        ChatApproveRequest(
            config_key=SLACK_PORTFOLIO_ALERT_SETTINGS_KEY,
            config_value="{}",
            expected_version=1,
        ),
        object(),  # type: ignore[arg-type]
        None,
    )

    assert reloaded is True
    assert result[0].config_key == SLACK_PORTFOLIO_ALERT_SETTINGS_KEY
    assert result[0].version == 2
