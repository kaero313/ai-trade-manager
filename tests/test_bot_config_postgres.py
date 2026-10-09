from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from copy import deepcopy
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.api.routes import config as config_route
from app.models.domain import BotConfig as BotConfigORM
from app.models.schemas import BotConfig
from app.services import bot_service


def _test_database_url() -> str:
    raw_url = str(os.getenv("TEST_DATABASE_URL") or "").strip()
    if not raw_url:
        if os.getenv("CI"):
            pytest.fail("CI PostgreSQL 테스트에는 TEST_DATABASE_URL이 필요합니다.")
        pytest.skip("TEST_DATABASE_URL이 없어 PostgreSQL 통합 테스트를 건너뜁니다.")
    parsed = make_url(raw_url)
    if not parsed.drivername.startswith("postgresql"):
        pytest.fail("TEST_DATABASE_URL은 PostgreSQL 테스트 DB를 가리켜야 합니다.")
    if not (parsed.database or "").endswith("_test"):
        pytest.fail("PostgreSQL 테스트 DB 이름은 _test로 끝나야 합니다.")
    return raw_url


@pytest_asyncio.fixture
async def pg_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine: AsyncEngine = create_async_engine(_test_database_url(), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        original = await session.get(BotConfigORM, 1)
        original_values = (
            {
                column.name: deepcopy(getattr(original, column.name))
                for column in BotConfigORM.__table__.columns
            }
            if original is not None
            else None
        )
        await session.execute(delete(BotConfigORM).where(BotConfigORM.id == 1))
        session.add(
            BotConfigORM(
                id=1,
                config_json={
                    **BotConfig().model_dump(),
                    "metadata": {"owner": "postgres-cas-test"},
                },
                config_version=1,
                is_active=False,
            )
        )
        await session.commit()
    try:
        yield session_factory
    finally:
        async with session_factory() as session:
            await session.execute(delete(BotConfigORM).where(BotConfigORM.id == 1))
            if original_values is not None:
                session.add(BotConfigORM(**original_values))
            await session.commit()
        await engine.dispose()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_runtime_update_and_config_cas_preserve_both_changes(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    heartbeat = datetime(2026, 7, 15, 3, 4, 5, tzinfo=timezone.utc)
    requested_config = BotConfig(
        symbols=["KRW-ETH"],
        allocation_pct_per_symbol=[0.75],
        trade_mode="manual",
    )
    response = Response()

    async with (
        pg_session_factory() as config_session,
        pg_session_factory() as runtime_session,
    ):
        config_snapshot = await config_session.get(BotConfigORM, 1)
        runtime_snapshot = await runtime_session.get(BotConfigORM, 1)
        assert config_snapshot is not None
        assert runtime_snapshot is not None
        assert config_snapshot.config_version == runtime_snapshot.config_version == 1

        await asyncio.gather(
            config_route.update_config(
                requested_config,
                response=response,
                if_match='"1"',
                db=config_session,
                _admin=None,
            ),
            bot_service.update_bot_runtime_status(
                runtime_session,
                last_heartbeat=heartbeat.isoformat(),
                last_error=None,
                latest_action="PostgreSQL 경합 검증",
                updated_at=heartbeat.isoformat(),
            ),
        )

    async with pg_session_factory() as session:
        stored = await session.scalar(select(BotConfigORM).where(BotConfigORM.id == 1))

    assert stored is not None
    assert stored.config_json["symbols"] == ["KRW-ETH"]
    assert stored.config_json["allocation_pct_per_symbol"] == [0.75]
    assert stored.config_json["trade_mode"] == "manual"
    assert stored.config_json["metadata"] == {"owner": "postgres-cas-test"}
    assert stored.config_version == 2
    assert stored.runtime_last_heartbeat == heartbeat
    assert stored.runtime_last_error is None
    assert stored.runtime_latest_action == "PostgreSQL 경합 검증"
    assert stored.runtime_updated_at == heartbeat
    assert response.headers["etag"] == '"2"'
    assert response.headers["x-config-version"] == "2"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_same_bot_config_version_allows_one_writer_and_stale_writer_changes_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    candidates = (
        BotConfig(symbols=["KRW-ETH"], allocation_pct_per_symbol=[0.5]),
        BotConfig(symbols=["KRW-XRP"], allocation_pct_per_symbol=[0.25]),
    )

    async with (
        pg_session_factory() as first_session,
        pg_session_factory() as second_session,
    ):
        first_snapshot = await first_session.get(BotConfigORM, 1)
        second_snapshot = await second_session.get(BotConfigORM, 1)
        assert first_snapshot is not None
        assert second_snapshot is not None
        assert first_snapshot.config_version == second_snapshot.config_version == 1

        results = await asyncio.gather(
            config_route.update_config(
                candidates[0],
                response=Response(),
                if_match="1",
                db=first_session,
                _admin=None,
            ),
            config_route.update_config(
                candidates[1],
                response=Response(),
                if_match="1",
                db=second_session,
                _admin=None,
            ),
            return_exceptions=True,
        )

    successful_indices = [
        index for index, result in enumerate(results) if isinstance(result, BotConfig)
    ]
    conflicts = [result for result in results if isinstance(result, HTTPException)]
    assert len(successful_indices) == 1
    assert len(conflicts) == 1
    assert conflicts[0].status_code == 409

    winner = candidates[successful_indices[0]]
    loser = candidates[1 - successful_indices[0]]
    async with pg_session_factory() as session:
        stored = await session.scalar(select(BotConfigORM).where(BotConfigORM.id == 1))

    assert stored is not None
    assert stored.config_json["symbols"] == winner.symbols
    assert stored.config_json["allocation_pct_per_symbol"] == winner.allocation_pct_per_symbol
    assert stored.config_json["symbols"] != loser.symbols
    assert stored.config_version == 2
    assert stored.config_json["metadata"] == {"owner": "postgres-cas-test"}
