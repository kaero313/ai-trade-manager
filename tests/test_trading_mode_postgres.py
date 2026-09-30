import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.trading_mode_repository import (
    TRADING_MODE_ACTION_LIVE_ENABLED,
    TRADING_MODE_ACTION_PAPER_CONFIRMED,
    TRADING_MODE_LIVE,
    TRADING_MODE_PAPER,
    TradingModeReauthConflictError,
    TradingModeRepository,
    build_trading_mode_request_fingerprint,
)
from app.models.domain import SystemConfig, TradingModeControl, TradingModeControlEvent


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
        pytest.fail("운영 DB 오접속 방지를 위해 테스트 DB 이름은 _test로 끝나야 합니다.")
    return raw_url


async def _seed_paper_state(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session, session.begin():
        session.add(
            SystemConfig(
                config_key="trading_mode",
                config_value=TRADING_MODE_PAPER,
                description="PostgreSQL 거래 모드 테스트 mirror",
            )
        )
        control = TradingModeControl(
            id=1,
            mode=TRADING_MODE_PAPER,
            version=1,
            reason_code="TEST_INITIALIZED",
            reason_text="PostgreSQL 거래 모드 테스트 fail-closed 초기화",
            changed_source="SYSTEM",
            changed_actor_ref="pytest",
        )
        session.add(control)
        await session.flush()
        session.add(
            TradingModeControlEvent(
                control_id=control.id,
                version=control.version,
                request_id=None,
                request_fingerprint=None,
                reauth_jti=None,
                action="INITIALIZED",
                from_mode=None,
                to_mode=TRADING_MODE_PAPER,
                reason_code=control.reason_code,
                reason_text=control.reason_text,
                source="SYSTEM",
                actor_ref="pytest",
                legacy_raw_value="live",
            )
        )


@pytest_asyncio.fixture
async def pg_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(_test_database_url(), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    truncate = text(
        "TRUNCATE TABLE trading_mode_control_events, trading_mode_controls, "
        "system_configs RESTART IDENTITY CASCADE"
    )
    async with engine.begin() as connection:
        await connection.execute(truncate)
    await _seed_paper_state(session_factory)
    try:
        yield session_factory
    finally:
        async with engine.begin() as connection:
            await connection.execute(truncate)
        await engine.dispose()


def _transition_values(
    *,
    request_id: UUID,
    expected_version: int,
    target_mode: str,
    action: str,
    reauth_jti: UUID | None,
) -> dict[str, object]:
    reason_code = "TEST_LIVE_ENABLED" if target_mode == TRADING_MODE_LIVE else "TEST_PAPER"
    reason_text = (
        "PostgreSQL 테스트에서 실거래 모드를 명시적으로 승인합니다."
        if target_mode == TRADING_MODE_LIVE
        else "PostgreSQL 테스트에서 거래 모드를 안전한 paper로 전환합니다."
    )
    fingerprint = build_trading_mode_request_fingerprint(
        action=action,
        expected_version=expected_version,
        target_mode=target_mode,
        reason_code=reason_code,
        reason_text=reason_text,
        source="REST",
        actor_ref="admin:pytest",
        confirmation="ENABLE_LIVE_TRADING" if target_mode == TRADING_MODE_LIVE else None,
        reauth_jti=str(reauth_jti) if reauth_jti is not None else None,
    )
    return {
        "request_id": request_id,
        "request_fingerprint": fingerprint,
        "expected_version": expected_version,
        "target_mode": target_mode,
        "action": action,
        "reason_code": reason_code,
        "reason_text": reason_text,
        "source": "REST",
        "actor_ref": "admin:pytest",
        "reauth_jti": reauth_jti,
    }


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_same_live_request_in_eight_sessions_applies_once(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = TradingModeRepository()
    values = _transition_values(
        request_id=uuid4(),
        expected_version=1,
        target_mode=TRADING_MODE_LIVE,
        action=TRADING_MODE_ACTION_LIVE_ENABLED,
        reauth_jti=uuid4(),
    )

    async def execute_once():
        async with pg_session_factory() as session, session.begin():
            return await repository.transition(session, **values)  # type: ignore[arg-type]

    results = await asyncio.gather(*(execute_once() for _ in range(8)))
    assert sum(not result.replayed for result in results) == 1
    assert sum(result.replayed for result in results) == 7

    async with pg_session_factory() as session:
        control = await repository.get_control(session)
        event_count = await session.scalar(
            select(func.count(TradingModeControlEvent.id)).where(
                TradingModeControlEvent.action == TRADING_MODE_ACTION_LIVE_ENABLED
            )
        )
        mirror = await session.scalar(
            select(SystemConfig.config_value).where(SystemConfig.config_key == "trading_mode")
        )
    assert control is not None
    assert (control.mode, control.version, event_count, mirror) == (
        TRADING_MODE_LIVE,
        2,
        1,
        TRADING_MODE_LIVE,
    )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_paper_transition_repairs_missing_mirror_and_reauth_is_single_use(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    repository = TradingModeRepository()
    reauth_jti = uuid4()
    live_values = _transition_values(
        request_id=uuid4(),
        expected_version=1,
        target_mode=TRADING_MODE_LIVE,
        action=TRADING_MODE_ACTION_LIVE_ENABLED,
        reauth_jti=reauth_jti,
    )
    async with pg_session_factory() as session, session.begin():
        await repository.transition(session, **live_values)  # type: ignore[arg-type]

    paper_values = _transition_values(
        request_id=uuid4(),
        expected_version=2,
        target_mode=TRADING_MODE_PAPER,
        action=TRADING_MODE_ACTION_PAPER_CONFIRMED,
        reauth_jti=None,
    )
    async with pg_session_factory() as session, session.begin():
        mirror = await session.scalar(
            select(SystemConfig).where(SystemConfig.config_key == "trading_mode")
        )
        assert mirror is not None
        await session.delete(mirror)
    async with pg_session_factory() as session, session.begin():
        paper_result = await repository.transition(
            session,
            **paper_values,  # type: ignore[arg-type]
        )
    assert not paper_result.replayed
    assert paper_result.control.mode == TRADING_MODE_PAPER

    reused_values = _transition_values(
        request_id=uuid4(),
        expected_version=3,
        target_mode=TRADING_MODE_LIVE,
        action=TRADING_MODE_ACTION_LIVE_ENABLED,
        reauth_jti=reauth_jti,
    )
    async with pg_session_factory() as session:
        with pytest.raises(TradingModeReauthConflictError):
            async with session.begin():
                await repository.transition(
                    session,
                    **reused_values,  # type: ignore[arg-type]
                )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_trading_mode_events_reject_update_and_delete(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        event = await session.scalar(select(TradingModeControlEvent).limit(1))
        assert event is not None
        event.reason_text = "감사 event를 변조하려는 테스트"
        with pytest.raises(DBAPIError, match="append-only"):
            await session.commit()
        await session.rollback()

    async with pg_session_factory() as session:
        event = await session.scalar(select(TradingModeControlEvent).limit(1))
        assert event is not None
        await session.delete(event)
        with pytest.raises(DBAPIError, match="append-only"):
            await session.commit()
        await session.rollback()
