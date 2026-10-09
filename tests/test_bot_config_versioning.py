from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException, Response

from app.api.routes import config as config_route
from app.models.domain import BotConfig as BotConfigORM
from app.models.domain import SystemConfig
from app.models.schemas import BotConfig
from app.services import bot_service


class _ScalarResult:
    def __init__(self, value: int | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> int | None:
        return self.value


class _ConfigSession:
    def __init__(
        self,
        bot_config: BotConfigORM,
        *,
        cas_result: int | None = None,
    ) -> None:
        self.bot_config = bot_config
        self.cas_result = cas_result
        self.execute_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.last_statement = None

    async def execute(self, statement):
        self.execute_count += 1
        self.last_statement = statement
        return _ScalarResult(self.cas_result)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class _RuntimeSession:
    def __init__(self, bot_config: BotConfigORM) -> None:
        self.bot_config = bot_config
        self.commit_count = 0
        self.refresh_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, value) -> None:
        assert value is self.bot_config
        self.refresh_count += 1


class _NeverUsedSession:
    def __getattr__(self, name: str):
        raise AssertionError(f"If-Match 검증 전에 DB 접근이 발생했습니다: {name}")


def _bot_config(*, version: int = 1) -> BotConfigORM:
    return BotConfigORM(
        id=1,
        config_json={"symbols": ["KRW-BTC"], "metadata": {"owner": "operator"}},
        config_version=version,
        is_active=False,
    )


def test_config_models_define_positive_version_constraints() -> None:
    bot_constraints = {item.name for item in BotConfigORM.__table__.constraints}
    system_constraints = {item.name for item in SystemConfig.__table__.constraints}

    assert "ck_bot_configs_config_version" in bot_constraints
    assert "ck_system_configs_version" in system_constraints
    assert BotConfigORM.__table__.c.config_version.server_default is not None
    assert SystemConfig.__table__.c.version.server_default is not None


@pytest.mark.asyncio
async def test_get_config_returns_etag_and_version_header(monkeypatch) -> None:
    bot_config = _bot_config(version=7)

    async def get_config(_db):
        return bot_config

    monkeypatch.setattr(config_route, "get_or_create_bot_config", get_config)
    response = Response()

    result = await config_route.get_config(
        response=response,
        db=object(),  # type: ignore[arg-type]
    )

    assert result.symbols == ["KRW-BTC"]
    assert response.headers["etag"] == '"7"'
    assert response.headers["x-config-version"] == "7"


@pytest.mark.asyncio
async def test_update_config_requires_if_match_before_database_access() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await config_route.update_config(
            BotConfig(),
            response=Response(),
            if_match=None,
            db=_NeverUsedSession(),  # type: ignore[arg-type]
            _admin=None,
        )

    assert exc_info.value.status_code == 428


@pytest.mark.asyncio
async def test_update_config_rejects_stale_version_without_write(monkeypatch) -> None:
    bot_config = _bot_config(version=4)
    db = _ConfigSession(bot_config)

    async def get_config(_db):
        return bot_config

    monkeypatch.setattr(config_route, "get_or_create_bot_config", get_config)

    with pytest.raises(HTTPException) as exc_info:
        await config_route.update_config(
            BotConfig(trade_mode="manual"),
            response=Response(),
            if_match='"3"',
            db=db,  # type: ignore[arg-type]
            _admin=None,
        )

    assert exc_info.value.status_code == 409
    assert db.execute_count == 0
    assert db.commit_count == 0
    assert db.rollback_count == 1


@pytest.mark.asyncio
async def test_update_config_uses_single_cas_and_preserves_metadata(monkeypatch) -> None:
    bot_config = _bot_config(version=4)
    db = _ConfigSession(bot_config, cas_result=5)

    async def get_config(_db):
        return bot_config

    monkeypatch.setattr(config_route, "get_or_create_bot_config", get_config)
    response = Response()

    result = await config_route.update_config(
        BotConfig(trade_mode="manual"),
        response=response,
        if_match='W/"4"',
        db=db,  # type: ignore[arg-type]
        _admin=None,
    )

    assert result.trade_mode == "manual"
    assert db.execute_count == 1
    assert db.commit_count == 1
    assert db.rollback_count == 0
    assert "config_version" in str(db.last_statement)
    assert "runtime_" not in str(db.last_statement)
    assert db.last_statement.compile().params["config_json"]["metadata"] == {
        "owner": "operator"
    }
    assert response.headers["etag"] == '"5"'
    assert response.headers["x-config-version"] == "5"


@pytest.mark.asyncio
async def test_update_config_maps_cas_race_to_conflict(monkeypatch) -> None:
    bot_config = _bot_config(version=4)
    db = _ConfigSession(bot_config, cas_result=None)

    async def get_config(_db):
        return bot_config

    monkeypatch.setattr(config_route, "get_or_create_bot_config", get_config)

    with pytest.raises(HTTPException) as exc_info:
        await config_route.update_config(
            BotConfig(),
            response=Response(),
            if_match="4",
            db=db,  # type: ignore[arg-type]
            _admin=None,
        )

    assert exc_info.value.status_code == 409
    assert db.execute_count == 1
    assert db.commit_count == 0
    assert db.rollback_count == 1


@pytest.mark.asyncio
async def test_runtime_update_does_not_change_config_payload_or_version(monkeypatch) -> None:
    bot_config = _bot_config(version=9)
    original_payload = bot_config.config_json
    db = _RuntimeSession(bot_config)

    async def get_config(_db):
        return bot_config

    monkeypatch.setattr(bot_service, "get_or_create_bot_config", get_config)
    heartbeat = datetime(2026, 7, 15, 1, 2, 3, tzinfo=timezone.utc)

    updated = await bot_service.update_bot_runtime_status(
        db,  # type: ignore[arg-type]
        last_heartbeat=heartbeat.isoformat(),
        last_error=None,
        latest_action="상태 확인",
    )

    assert updated.runtime_last_heartbeat == heartbeat
    assert updated.runtime_latest_action == "상태 확인"
    assert updated.config_json is original_payload
    assert updated.config_version == 9
    assert db.commit_count == 1
    assert db.refresh_count == 1
