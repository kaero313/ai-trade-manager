from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.rate_limit_repository import ApiRateLimitRepository
from app.models.domain import ApiRateLimitWindow
from app.services.rate_limit import ApiRateLimitPolicy, ApiRateLimitService


SUBJECT_HASH = "a" * 64
SUBJECT_SECRET = "rate-limit-postgres-test-secret!" * 2


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
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        _test_database_url(),
        pool_pre_ping=True,
        pool_size=32,
        max_overflow=0,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def pg_session_factory(
    pg_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with pg_engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE api_rate_limit_windows"))
    try:
        yield session_factory
    finally:
        async with pg_engine.begin() as connection:
            await connection.execute(text("TRUNCATE TABLE api_rate_limit_windows"))


async def _consume_once(
    session_factory: async_sessionmaker[AsyncSession],
    repository: ApiRateLimitRepository,
    *,
    policy_key: str,
    subject_hash: str = SUBJECT_HASH,
    request_limit: int,
    window_seconds: int = 60,
):
    async with session_factory() as session:
        async with session.begin():
            return await repository.consume_window(
                session,
                policy_key=policy_key,
                subject_hash=subject_hash,
                request_limit=request_limit,
                window_seconds=window_seconds,
            )


async def _wait_for_stable_minute_window(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        second_in_window = int(
            await session.scalar(
                text(
                    "SELECT floor(extract(epoch FROM statement_timestamp()))::bigint % 60"
                )
            )
            or 0
        )
    if second_in_window > 50:
        await asyncio.sleep(61 - second_in_window)


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(("contenders", "request_limit"), [(8, 3), (32, 11)])
async def test_independent_sessions_allow_exactly_n_requests(
    pg_session_factory: async_sessionmaker[AsyncSession],
    contenders: int,
    request_limit: int,
) -> None:
    repository = ApiRateLimitRepository()
    policy_key = f"PG_CONCURRENCY_{contenders}"
    await _wait_for_stable_minute_window(pg_session_factory)

    decisions = await asyncio.gather(
        *(
            _consume_once(
                pg_session_factory,
                repository,
                policy_key=policy_key,
                request_limit=request_limit,
            )
            for _ in range(contenders)
        )
    )

    assert sum(decision.allowed for decision in decisions) == request_limit
    assert sum(not decision.allowed for decision in decisions) == contenders - request_limit
    async with pg_session_factory() as session:
        row = (
            await session.execute(
                select(ApiRateLimitWindow).where(
                    ApiRateLimitWindow.policy_key == policy_key
                )
            )
        ).scalar_one()
    assert row.request_count == request_limit + 1
    assert row.rejected_count == contenders - request_limit


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_policy_and_window_are_isolated_and_use_database_clock(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = ApiRateLimitRepository()
    first = await _consume_once(
        pg_session_factory,
        repository,
        policy_key="PG_WINDOW_60",
        request_limit=2,
        window_seconds=60,
    )
    second = await _consume_once(
        pg_session_factory,
        repository,
        policy_key="PG_WINDOW_300",
        request_limit=2,
        window_seconds=300,
    )

    assert first.allowed is True
    assert second.allowed is True
    async with pg_session_factory() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT policy_key,
                           window_started_at,
                           last_seen_at,
                           CASE policy_key
                               WHEN 'PG_WINDOW_60' THEN
                                   date_bin(
                                       interval '60 seconds',
                                       last_seen_at,
                                       timestamptz '1970-01-01 00:00:00+00'
                                   )
                               ELSE
                                   date_bin(
                                       interval '300 seconds',
                                       last_seen_at,
                                       timestamptz '1970-01-01 00:00:00+00'
                                   )
                           END AS expected_window
                    FROM api_rate_limit_windows
                    ORDER BY policy_key
                    """
                )
            )
        ).mappings().all()

    assert len(rows) == 2
    assert all(row["window_started_at"] == row["expected_window"] for row in rows)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_new_database_window_does_not_reuse_previous_window(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO api_rate_limit_windows (
                        policy_key, subject_hash, window_started_at,
                        request_count, rejected_count, last_seen_at,
                        created_at, updated_at
                    )
                    SELECT
                        'PG_ROLLOVER', :subject_hash,
                        date_bin(
                            interval '60 seconds', statement_timestamp(),
                            timestamptz '1970-01-01 00:00:00+00'
                        ) - interval '60 seconds',
                        4, 1, statement_timestamp() - interval '60 seconds',
                        statement_timestamp() - interval '60 seconds',
                        statement_timestamp() - interval '60 seconds'
                    """
                ),
                {"subject_hash": SUBJECT_HASH},
            )

    decision = await _consume_once(
        pg_session_factory,
        ApiRateLimitRepository(),
        policy_key="PG_ROLLOVER",
        request_limit=3,
    )

    assert decision.allowed is True
    assert decision.request_count == 1
    async with pg_session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(ApiRateLimitWindow).where(
                ApiRateLimitWindow.policy_key == "PG_ROLLOVER"
            )
        )
    assert count == 2


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_consume_deterministically_removes_windows_older_than_24_hours(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO api_rate_limit_windows (
                        policy_key, subject_hash, window_started_at,
                        request_count, rejected_count, last_seen_at,
                        created_at, updated_at
                    ) VALUES (
                        'PG_EXPIRED', :subject_hash,
                        statement_timestamp() - interval '25 hours',
                        1, 0,
                        statement_timestamp() - interval '25 hours',
                        statement_timestamp() - interval '25 hours',
                        statement_timestamp() - interval '25 hours'
                    )
                    """
                ),
                {"subject_hash": SUBJECT_HASH},
            )

    await _consume_once(
        pg_session_factory,
        ApiRateLimitRepository(),
        policy_key="PG_CLEANUP_TRIGGER",
        request_limit=3,
    )

    async with pg_session_factory() as session:
        expired_count = await session.scalar(
            select(func.count()).select_from(ApiRateLimitWindow).where(
                ApiRateLimitWindow.policy_key == "PG_EXPIRED"
            )
        )
    assert expired_count == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_concurrent_cleanup_and_consume_remain_exact(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    """
                    INSERT INTO api_rate_limit_windows (
                        policy_key, subject_hash, window_started_at,
                        request_count, rejected_count, last_seen_at,
                        created_at, updated_at
                    )
                    SELECT
                        'PG_EXPIRED_' || series,
                        md5(series::text) || md5((series + 100)::text),
                        statement_timestamp() - interval '25 hours'
                            - make_interval(secs => series),
                        1, 0,
                        statement_timestamp() - interval '25 hours',
                        statement_timestamp() - interval '25 hours',
                        statement_timestamp() - interval '25 hours'
                    FROM generate_series(1, 16) AS series
                    """
                )
            )

    repository = ApiRateLimitRepository()
    await _wait_for_stable_minute_window(pg_session_factory)
    decisions = await asyncio.wait_for(
        asyncio.gather(
            *(
                _consume_once(
                    pg_session_factory,
                    repository,
                    policy_key="PG_CONCURRENT_CLEANUP",
                    request_limit=3,
                )
                for _ in range(8)
            )
        ),
        timeout=20,
    )

    assert sum(decision.allowed for decision in decisions) == 3
    assert sum(not decision.allowed for decision in decisions) == 5
    async with pg_session_factory() as session:
        row = (
            await session.execute(
                select(ApiRateLimitWindow).where(
                    ApiRateLimitWindow.policy_key == "PG_CONCURRENT_CLEANUP"
                )
            )
        ).scalar_one()
        expired_count = await session.scalar(
            select(func.count()).select_from(ApiRateLimitWindow).where(
                ApiRateLimitWindow.policy_key.like("PG_EXPIRED_%")
            )
        )

    assert row.request_count == 4
    assert row.rejected_count == 5
    assert expired_count == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_limiter_commit_survives_unrelated_endpoint_rollback(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    endpoint_session = pg_session_factory()
    endpoint_transaction = await endpoint_session.begin()
    service = ApiRateLimitService(pg_session_factory)
    try:
        decision = await service.consume(
            ApiRateLimitPolicy.ADMIN_DB_READ,
            subject_secret=SUBJECT_SECRET,
        )
        await endpoint_transaction.rollback()
    finally:
        await endpoint_session.close()

    assert decision.allowed is True
    async with pg_session_factory() as session:
        count = await session.scalar(
            select(func.count()).select_from(ApiRateLimitWindow).where(
                ApiRateLimitWindow.policy_key == "ADMIN_DB_READ"
            )
        )
    assert count == 1


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_persisted_subject_is_hmac_only_and_schema_has_no_raw_input_columns(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = ApiRateLimitService(pg_session_factory)
    await service.consume(
        ApiRateLimitPolicy.PUBLIC_MARKET_READ,
        subject_secret=SUBJECT_SECRET,
    )

    async with pg_session_factory() as session:
        row = (
            await session.execute(
                select(ApiRateLimitWindow).where(
                    ApiRateLimitWindow.policy_key == "PUBLIC_MARKET_READ"
                )
            )
        ).scalar_one()
        columns = set(
            (
                await session.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'api_rate_limit_windows'
                        """
                    )
                )
            ).scalars()
        )

    assert re.fullmatch(r"[0-9a-f]{64}", row.subject_hash)
    assert SUBJECT_SECRET not in row.subject_hash
    assert columns == {
        "policy_key",
        "subject_hash",
        "window_started_at",
        "request_count",
        "rejected_count",
        "last_seen_at",
        "created_at",
        "updated_at",
    }
    assert not columns & {"token", "ip", "header", "query", "body", "path"}


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_migration_installs_primary_key_checks_and_cleanup_index(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        constraints = set(
            (
                await session.execute(
                    text(
                        """
                        SELECT conname
                        FROM pg_constraint
                        WHERE conrelid = 'api_rate_limit_windows'::regclass
                        """
                    )
                )
            ).scalars()
        )
        indexes = set(
            (
                await session.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = current_schema()
                          AND tablename = 'api_rate_limit_windows'
                        """
                    )
                )
            ).scalars()
        )

    assert {
        "pk_api_rate_limit_windows",
        "ck_api_rate_limit_windows_policy_key",
        "ck_api_rate_limit_windows_subject_hash_hex",
        "ck_api_rate_limit_windows_request_count",
        "ck_api_rate_limit_windows_rejected_count",
    } <= constraints
    assert "ix_api_rate_limit_windows_cleanup_due" in indexes
