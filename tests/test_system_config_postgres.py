from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.repository import AI_MAX_CONCURRENT_POSITIONS_KEY
from app.db.repository import MAX_ALLOCATION_PCT_KEY
from app.models.domain import SystemConfig
from app.services.system_config_service import SystemConfigConflictError
from app.services.system_config_service import SystemConfigMutation
from app.services.system_config_service import update_public_system_configs


_TEST_KEYS = (MAX_ALLOCATION_PCT_KEY, AI_MAX_CONCURRENT_POSITIONS_KEY)


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
        original_rows = [
            {
                "config_key": row.config_key,
                "config_value": row.config_value,
                "description": row.description,
                "version": row.version,
            }
            for row in (
                await session.execute(
                    select(SystemConfig).where(SystemConfig.config_key.in_(_TEST_KEYS))
                )
            ).scalars().all()
        ]
        await session.execute(delete(SystemConfig).where(SystemConfig.config_key.in_(_TEST_KEYS)))
        session.add_all(
            [
                SystemConfig(
                    config_key=MAX_ALLOCATION_PCT_KEY,
                    config_value="30",
                    description="설정 CAS PostgreSQL 테스트",
                    version=1,
                ),
                SystemConfig(
                    config_key=AI_MAX_CONCURRENT_POSITIONS_KEY,
                    config_value="2",
                    description="설정 CAS PostgreSQL 테스트",
                    version=1,
                ),
            ]
        )
        await session.commit()
    try:
        yield session_factory
    finally:
        async with session_factory() as session:
            await session.execute(delete(SystemConfig).where(SystemConfig.config_key.in_(_TEST_KEYS)))
            session.add_all(SystemConfig(**values) for values in original_rows)
            await session.commit()
        await engine.dispose()


async def _update_allocation(
    session_factory: async_sessionmaker[AsyncSession],
    value: str,
) -> list[SystemConfig]:
    async with session_factory() as session:
        return await update_public_system_configs(
            session,
            [SystemConfigMutation(MAX_ALLOCATION_PCT_KEY, value, 1)],
        )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_same_system_config_version_allows_exactly_one_concurrent_writer(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    results = await asyncio.gather(
        _update_allocation(pg_session_factory, "20"),
        _update_allocation(pg_session_factory, "25"),
        return_exceptions=True,
    )

    assert sum(isinstance(result, list) for result in results) == 1
    assert sum(isinstance(result, SystemConfigConflictError) for result in results) == 1
    async with pg_session_factory() as session:
        row = await session.scalar(
            select(SystemConfig).where(SystemConfig.config_key == MAX_ALLOCATION_PCT_KEY)
        )
    assert row is not None
    assert row.config_value in {"20", "25"}
    assert row.version == 2


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_stale_member_of_multi_key_update_writes_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        with pytest.raises(SystemConfigConflictError):
            await update_public_system_configs(
                session,
                [
                    SystemConfigMutation(MAX_ALLOCATION_PCT_KEY, "20", 1),
                    SystemConfigMutation(AI_MAX_CONCURRENT_POSITIONS_KEY, "4", 999),
                ],
            )

    async with pg_session_factory() as session:
        rows = (
            await session.execute(
                select(SystemConfig)
                .where(SystemConfig.config_key.in_(_TEST_KEYS))
                .order_by(SystemConfig.config_key)
            )
        ).scalars().all()
    assert [(row.config_key, row.config_value, row.version) for row in rows] == [
        (AI_MAX_CONCURRENT_POSITIONS_KEY, "2", 1),
        (MAX_ALLOCATION_PCT_KEY, "30", 1),
    ]
