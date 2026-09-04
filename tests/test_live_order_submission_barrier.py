import asyncio
import os
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.services.trading.live_order_submission_barrier import (
    LIVE_ORDER_SUBMISSION_ADVISORY_LOCK_KEY,
    MAX_LOCK_TIMEOUT_SECONDS,
    LiveOrderSubmissionBarrier,
    LiveOrderSubmissionBarrierTimeoutError,
    LiveOrderSubmissionBarrierUnavailableError,
)


class _FakeResult:
    def __init__(self, value: object = None) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value


class _FakeLockTimeout(Exception):
    sqlstate = "55P03"


class _FakeConnection:
    def __init__(
        self,
        *,
        acquire_error: Exception | None = None,
        unlock_result: bool = True,
        unlock_started: asyncio.Event | None = None,
        allow_unlock: asyncio.Event | None = None,
    ) -> None:
        self.acquire_error = acquire_error
        self.unlock_result = unlock_result
        self.unlock_started = unlock_started
        self.allow_unlock = allow_unlock
        self.closed = False
        self.invalidated = False
        self._in_transaction = False
        self.commits = 0
        self.rollbacks = 0
        self.invalidate_calls = 0
        self.close_calls = 0
        self.executions: list[tuple[str, dict[str, object]]] = []

    def in_transaction(self) -> bool:
        return self._in_transaction

    async def execute(
        self,
        statement: object,
        parameters: dict[str, object] | None = None,
    ) -> _FakeResult:
        sql = str(statement)
        values = parameters or {}
        self.executions.append((sql, values))
        self._in_transaction = True

        if "pg_advisory_unlock" in sql:
            if self.unlock_started is not None:
                self.unlock_started.set()
            if self.allow_unlock is not None:
                await self.allow_unlock.wait()
            return _FakeResult(self.unlock_result)
        if "pg_advisory_lock" in sql and self.acquire_error is not None:
            raise self.acquire_error
        return _FakeResult(None)

    async def commit(self) -> None:
        self.commits += 1
        self._in_transaction = False

    async def rollback(self) -> None:
        self.rollbacks += 1
        self._in_transaction = False

    async def invalidate(self) -> None:
        self.invalidate_calls += 1
        self.invalidated = True
        self._in_transaction = False

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True
        self._in_transaction = False


class _FakeEngine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.connect_calls = 0

    async def connect(self) -> _FakeConnection:
        self.connect_calls += 1
        return self.connection


class _FakeTransaction:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> None:
        self._connection._in_transaction = True

    async def __aexit__(self, *_args: object) -> None:
        self._connection._in_transaction = False


class _FakeSession:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.closed = False

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self.connection)

    async def close(self) -> None:
        self.closed = True


def _barrier(
    connection: _FakeConnection,
    *,
    session_factory: Any = None,
) -> LiveOrderSubmissionBarrier:
    kwargs: dict[str, object] = {}
    if session_factory is not None:
        kwargs["session_factory"] = session_factory
    return LiveOrderSubmissionBarrier(
        cast(AsyncEngine, _FakeEngine(connection)),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_shared_lease_commits_acquisition_and_unlocks_fixed_key() -> None:
    connection = _FakeConnection()
    sessions: list[_FakeSession] = []

    def session_factory(bound_connection: _FakeConnection) -> _FakeSession:
        assert bound_connection is connection
        session = _FakeSession(bound_connection)
        sessions.append(session)
        return session

    barrier = _barrier(connection, session_factory=session_factory)

    async with barrier.shared() as lease:
        assert connection.commits == 1
        assert lease.has_active_transaction is False

        async with lease.transaction() as session:
            assert session is sessions[0]
            assert lease.has_active_transaction is True

        assert sessions[0].closed is True
        assert lease.has_active_transaction is False
        await lease.assert_no_transaction()

    assert connection.commits == 2
    assert connection.closed is True
    assert connection.invalidated is False
    assert [values["lock_key"] for _, values in connection.executions if "lock_key" in values] == [
        LIVE_ORDER_SUBMISSION_ADVISORY_LOCK_KEY,
        LIVE_ORDER_SUBMISSION_ADVISORY_LOCK_KEY,
    ]
    assert "pg_advisory_lock_shared" in connection.executions[1][0]
    assert "pg_advisory_unlock_shared" in connection.executions[2][0]


@pytest.mark.asyncio
async def test_exclusive_uses_exclusive_advisory_functions() -> None:
    connection = _FakeConnection()
    barrier = _barrier(connection)

    async with barrier.exclusive() as lease:
        await lease.assert_no_transaction()

    assert "pg_advisory_lock(" in connection.executions[1][0]
    assert "pg_advisory_lock_shared" not in connection.executions[1][0]
    assert "pg_advisory_unlock(" in connection.executions[2][0]
    assert "pg_advisory_unlock_shared" not in connection.executions[2][0]


@pytest.mark.asyncio
async def test_lock_timeout_is_typed_and_connection_is_physically_discarded() -> None:
    connection = _FakeConnection(acquire_error=_FakeLockTimeout("lock timeout"))
    barrier = _barrier(connection)

    with pytest.raises(LiveOrderSubmissionBarrierTimeoutError) as captured:
        async with barrier.shared(timeout_seconds=0.25):
            pytest.fail("timeout 이후 lease를 반환하면 안 됩니다.")

    assert captured.value.lock_mode == "shared"
    assert captured.value.timeout_seconds == 0.25
    assert connection.invalidate_calls == 1
    assert connection.close_calls == 1


@pytest.mark.asyncio
async def test_unlock_false_raises_release_error_and_discards_connection() -> None:
    connection = _FakeConnection(unlock_result=False)
    barrier = _barrier(connection)
    post_result: dict[str, str] | None = None

    with pytest.raises(LiveOrderSubmissionBarrierUnavailableError) as captured:
        async with barrier.shared():
            # 호출자는 POST 결과를 context 바깥 변수에 먼저 보존해야 한다. release 오류와
            # 결과를 함께 처리해 이미 접수된 주문을 다시 POST하지 않는다.
            post_result = {"uuid": "exchange-order-id"}

    assert captured.value.phase == "release"
    assert post_result == {"uuid": "exchange-order-id"}
    assert connection.invalidate_calls == 1
    assert connection.close_calls == 1


@pytest.mark.asyncio
async def test_task_cancellation_waits_for_unlock_before_returning_connection() -> None:
    unlock_started = asyncio.Event()
    allow_unlock = asyncio.Event()
    entered = asyncio.Event()
    keep_running = asyncio.Event()
    connection = _FakeConnection(
        unlock_started=unlock_started,
        allow_unlock=allow_unlock,
    )
    barrier = _barrier(connection)

    async def submit() -> None:
        async with barrier.shared():
            entered.set()
            await keep_running.wait()

    task = asyncio.create_task(submit())
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    await asyncio.wait_for(unlock_started.wait(), timeout=1)

    assert task.done() is False
    assert connection.close_calls == 0

    allow_unlock.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert connection.commits == 2
    assert connection.close_calls == 1
    assert connection.invalidated is False


@pytest.mark.parametrize(
    "timeout",
    [0, -1, float("inf"), float("nan"), MAX_LOCK_TIMEOUT_SECONDS + 1],
)
def test_timeout_must_be_positive_finite_and_bounded(timeout: float) -> None:
    connection = _FakeConnection()

    with pytest.raises(ValueError):
        LiveOrderSubmissionBarrier(
            cast(AsyncEngine, _FakeEngine(connection)),
            shared_lock_timeout_seconds=timeout,
        )


def _postgres_url() -> str:
    raw_url = str(os.getenv("TEST_DATABASE_URL") or "").strip()
    if not raw_url:
        if os.getenv("CI"):
            pytest.fail("CI PostgreSQL 테스트에는 TEST_DATABASE_URL이 필요합니다.")
        pytest.skip("TEST_DATABASE_URL이 없어 PostgreSQL 배리어 테스트를 건너뜁니다.")

    parsed = make_url(raw_url)
    if not parsed.drivername.startswith("postgresql"):
        pytest.fail("TEST_DATABASE_URL은 PostgreSQL 테스트 DB를 가리켜야 합니다.")
    if not (parsed.database or "").endswith("_test"):
        pytest.fail("운영 DB 오접속 방지를 위해 테스트 DB 이름은 _test로 끝나야 합니다.")
    return raw_url


@pytest_asyncio.fixture
async def pg_barrier_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(_postgres_url(), pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_shared_locks_are_concurrent(
    pg_barrier_engine: AsyncEngine,
) -> None:
    first = LiveOrderSubmissionBarrier(pg_barrier_engine)
    second = LiveOrderSubmissionBarrier(pg_barrier_engine)

    async with first.shared():
        async with second.shared(timeout_seconds=0.5):
            pass


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_exclusive_waits_for_shared_drain(
    pg_barrier_engine: AsyncEngine,
) -> None:
    barrier = LiveOrderSubmissionBarrier(pg_barrier_engine)
    shared_entered = asyncio.Event()
    release_shared = asyncio.Event()
    exclusive_entered = asyncio.Event()

    async def hold_shared() -> None:
        async with barrier.shared():
            shared_entered.set()
            await release_shared.wait()

    async def take_exclusive() -> None:
        async with barrier.exclusive(timeout_seconds=10):
            exclusive_entered.set()

    shared_task = asyncio.create_task(hold_shared())
    await asyncio.wait_for(shared_entered.wait(), timeout=5)
    exclusive_task = asyncio.create_task(take_exclusive())
    await asyncio.sleep(0.1)

    assert exclusive_entered.is_set() is False

    release_shared.set()
    await asyncio.wait_for(asyncio.gather(shared_task, exclusive_task), timeout=15)
    assert exclusive_entered.is_set() is True


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_exclusive_timeout_is_bounded(
    pg_barrier_engine: AsyncEngine,
) -> None:
    barrier = LiveOrderSubmissionBarrier(pg_barrier_engine)

    async with barrier.shared():
        with pytest.raises(LiveOrderSubmissionBarrierTimeoutError):
            async with barrier.exclusive(timeout_seconds=0.05):
                pytest.fail("shared lock 보유 중 exclusive lock이 획득되면 안 됩니다.")


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_unlock_releases_lock_for_independent_session(
    pg_barrier_engine: AsyncEngine,
) -> None:
    barrier = LiveOrderSubmissionBarrier(pg_barrier_engine)

    async with barrier.shared() as lease:
        async with lease.transaction() as session:
            assert await session.scalar(text("SELECT pg_backend_pid()")) is not None
        assert lease.has_active_transaction is False
        await lease.assert_no_transaction()

    probe_engine = create_async_engine(_postgres_url(), poolclass=NullPool)
    try:
        async with probe_engine.connect() as connection:
            acquired = await connection.scalar(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": LIVE_ORDER_SUBMISSION_ADVISORY_LOCK_KEY},
            )
            assert acquired is True
            unlocked = await connection.scalar(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": LIVE_ORDER_SUBMISSION_ADVISORY_LOCK_KEY},
            )
            assert unlocked is True
            await connection.commit()
    finally:
        await probe_engine.dispose()
