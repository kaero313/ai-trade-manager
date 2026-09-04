"""PostgreSQL 세션 advisory lock 기반 실주문 제출 배리어.

이 모듈은 세션 단위 lock을 사용하므로 transaction pooling 방식의 PgBouncer와
호환되지 않는다. 운영 연결은 PostgreSQL 세션이 lease 전체에서 고정되는 direct
connection 또는 session pooling 방식이어야 한다.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Final, Literal, Protocol, runtime_checkable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

LIVE_ORDER_SUBMISSION_ADVISORY_LOCK_KEY: Final = 5_740_495_976_316_385_210

DEFAULT_SHARED_LOCK_TIMEOUT_SECONDS: Final = 5.0
DEFAULT_EXCLUSIVE_LOCK_TIMEOUT_SECONDS: Final = 30.0
MAX_LOCK_TIMEOUT_SECONDS: Final = 300.0

_LOCK_TIMEOUT_SQLSTATE: Final = "55P03"
_SHARED: Final = "shared"
_EXCLUSIVE: Final = "exclusive"

_SET_LOCAL_LOCK_TIMEOUT = text(
    "SELECT set_config('lock_timeout', :lock_timeout, true)"
)
_LOCK_STATEMENTS = {
    _SHARED: text("SELECT pg_advisory_lock_shared(:lock_key)"),
    _EXCLUSIVE: text("SELECT pg_advisory_lock(:lock_key)"),
}
_UNLOCK_STATEMENTS = {
    _SHARED: text("SELECT pg_advisory_unlock_shared(:lock_key)"),
    _EXCLUSIVE: text("SELECT pg_advisory_unlock(:lock_key)"),
}


class LiveOrderSubmissionBarrierError(RuntimeError):
    """실주문 제출 배리어의 안정적인 상위 오류 형식."""

    error_code = "ORDER_GATE_STATE_UNAVAILABLE"


class LiveOrderSubmissionBarrierTimeoutError(LiveOrderSubmissionBarrierError):
    """정해진 시간 안에 shared/exclusive lock을 획득하지 못한 경우."""

    error_code = "ORDER_GATE_BARRIER_TIMEOUT"

    def __init__(self, *, lock_mode: str, timeout_seconds: float) -> None:
        super().__init__(
            f"실주문 제출 {lock_mode} 배리어를 {timeout_seconds:g}초 안에 획득하지 "
            "못했습니다."
        )
        self.lock_mode = lock_mode
        self.timeout_seconds = timeout_seconds


class LiveOrderSubmissionBarrierUnavailableError(LiveOrderSubmissionBarrierError):
    """배리어 연결, 상태 또는 해제를 신뢰할 수 없는 경우."""

    def __init__(
        self,
        message: str,
        *,
        phase: Literal["connect", "acquire", "lease", "release"] = "lease",
    ) -> None:
        super().__init__(message)
        self.phase = phase


class ConnectionBoundSessionFactory(Protocol):
    """lease가 소유한 동일 connection에 세션을 바인딩하는 팩터리."""

    def __call__(self, connection: AsyncConnection) -> AsyncSession: ...


@runtime_checkable
class LiveOrderSubmissionLease(Protocol):
    """제출 권한 lock을 보유하는 동안 사용할 수 있는 DB lease 계약."""

    @property
    def has_active_transaction(self) -> bool: ...

    def transaction(self) -> AbstractAsyncContextManager[AsyncSession]: ...

    async def assert_no_transaction(self) -> None: ...


@runtime_checkable
class LiveOrderSubmissionBarrierProtocol(Protocol):
    """fake 배리어로 대체 가능한 실주문 제출 배리어 계약."""

    def shared(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> AbstractAsyncContextManager[LiveOrderSubmissionLease]: ...

    def exclusive(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> AbstractAsyncContextManager[LiveOrderSubmissionLease]: ...


def _default_session_factory(connection: AsyncConnection) -> AsyncSession:
    return AsyncSession(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
    )


class _PostgresLiveOrderSubmissionLease:
    def __init__(
        self,
        connection: AsyncConnection,
        session_factory: ConnectionBoundSessionFactory,
    ) -> None:
        self._connection = connection
        self._session_factory = session_factory
        self._released = False
        self._transaction_open = False

    @property
    def has_active_transaction(self) -> bool:
        return self._transaction_open or self._connection.in_transaction()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """같은 PostgreSQL connection에서 짧은 원자적 작업을 수행한다."""
        self._assert_usable()
        if self.has_active_transaction:
            raise LiveOrderSubmissionBarrierUnavailableError(
                "lease connection에 이미 열린 트랜잭션이 있습니다.",
                phase="lease",
            )

        session = self._session_factory(self._connection)
        self._transaction_open = True
        try:
            async with session.begin():
                yield session
        except BaseException:
            await _finish_session_safely(session)
            raise
        else:
            await _finish_session_safely(session)
        finally:
            self._transaction_open = False

        if self._connection.in_transaction():
            await _rollback_safely(self._connection)
            raise LiveOrderSubmissionBarrierUnavailableError(
                "lease 트랜잭션 종료 후 connection이 idle 상태가 아닙니다.",
                phase="lease",
            )

    async def assert_no_transaction(self) -> None:
        """외부 POST 직전 열린 DB 트랜잭션이 없음을 강제한다."""
        self._assert_usable()
        if self.has_active_transaction:
            raise LiveOrderSubmissionBarrierUnavailableError(
                "외부 주문 호출 중에는 DB 트랜잭션을 열 수 없습니다.",
                phase="lease",
            )

    def _assert_usable(self) -> None:
        if self._released or self._connection.closed or self._connection.invalidated:
            raise LiveOrderSubmissionBarrierUnavailableError(
                "이미 해제되었거나 사용할 수 없는 제출 lease입니다.",
                phase="lease",
            )

    def _mark_released(self) -> None:
        self._released = True


class LiveOrderSubmissionBarrier:
    """계정 전체의 신규 Upbit POST를 PostgreSQL 세션 lock으로 선형화한다."""

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        session_factory: ConnectionBoundSessionFactory | None = None,
        shared_lock_timeout_seconds: float = DEFAULT_SHARED_LOCK_TIMEOUT_SECONDS,
        exclusive_lock_timeout_seconds: float = DEFAULT_EXCLUSIVE_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("실주문 제출 배리어에는 PostgreSQL AsyncEngine이 필요합니다.")

        self._engine = engine
        self._session_factory = session_factory or _default_session_factory
        self._shared_timeout_seconds = _validate_timeout(
            shared_lock_timeout_seconds,
            name="shared_lock_timeout_seconds",
        )
        self._exclusive_timeout_seconds = _validate_timeout(
            exclusive_lock_timeout_seconds,
            name="exclusive_lock_timeout_seconds",
        )

    @asynccontextmanager
    async def shared(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> AsyncIterator[LiveOrderSubmissionLease]:
        """일반/청산 주문 하나의 최종 승인과 POST 구간을 보호한다."""
        timeout = self._resolve_timeout(
            timeout_seconds,
            default=self._shared_timeout_seconds,
            name="timeout_seconds",
        )
        async with self._lease(lock_mode=_SHARED, timeout_seconds=timeout) as lease:
            yield lease

    @asynccontextmanager
    async def exclusive(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> AsyncIterator[LiveOrderSubmissionLease]:
        """정지/재무장/청산 권한 전이와 기존 POST drain을 보호한다."""
        timeout = self._resolve_timeout(
            timeout_seconds,
            default=self._exclusive_timeout_seconds,
            name="timeout_seconds",
        )
        async with self._lease(lock_mode=_EXCLUSIVE, timeout_seconds=timeout) as lease:
            yield lease

    def _resolve_timeout(
        self,
        value: float | None,
        *,
        default: float,
        name: str,
    ) -> float:
        if value is None:
            return default
        return _validate_timeout(value, name=name)

    @asynccontextmanager
    async def _lease(
        self,
        *,
        lock_mode: str,
        timeout_seconds: float,
    ) -> AsyncIterator[LiveOrderSubmissionLease]:
        connection: AsyncConnection | None = None
        try:
            connection = await self._engine.connect()
            await self._acquire(
                connection,
                lock_mode=lock_mode,
                timeout_seconds=timeout_seconds,
            )
        except asyncio.CancelledError:
            if connection is not None:
                await _run_cleanup_shielded(
                    lambda: _invalidate_and_close_safely(connection)
                )
            raise
        except LiveOrderSubmissionBarrierError:
            if connection is not None:
                await _run_cleanup_shielded(
                    lambda: _invalidate_and_close_safely(connection)
                )
            raise
        except Exception as exc:
            if connection is not None:
                await _run_cleanup_shielded(
                    lambda: _invalidate_and_close_safely(connection)
                )
            raise LiveOrderSubmissionBarrierUnavailableError(
                f"실주문 제출 {lock_mode} 배리어를 사용할 수 없습니다.",
                phase="connect",
            ) from exc

        if connection is None:  # pragma: no cover - engine 계약 방어
            raise LiveOrderSubmissionBarrierUnavailableError(
                "PostgreSQL connection을 획득하지 못했습니다.",
                phase="connect",
            )

        lease = _PostgresLiveOrderSubmissionLease(
            connection,
            self._session_factory,
        )
        try:
            yield lease
        finally:
            lease._mark_released()
            await _run_cleanup_shielded(
                lambda: self._release(connection, lock_mode=lock_mode)
            )

    async def _acquire(
        self,
        connection: AsyncConnection,
        *,
        lock_mode: str,
        timeout_seconds: float,
    ) -> None:
        timeout_milliseconds = max(1, math.ceil(timeout_seconds * 1000))
        try:
            await connection.execute(
                _SET_LOCAL_LOCK_TIMEOUT,
                {"lock_timeout": f"{timeout_milliseconds}ms"},
            )
            await connection.execute(
                _LOCK_STATEMENTS[lock_mode],
                {"lock_key": LIVE_ORDER_SUBMISSION_ADVISORY_LOCK_KEY},
            )
            # session lock만 남기고 lock_timeout 설정 및 획득 트랜잭션은 즉시 닫는다.
            await connection.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _is_lock_timeout(exc):
                raise LiveOrderSubmissionBarrierTimeoutError(
                    lock_mode=lock_mode,
                    timeout_seconds=timeout_seconds,
                ) from exc
            raise LiveOrderSubmissionBarrierUnavailableError(
                f"실주문 제출 {lock_mode} 배리어 획득에 실패했습니다.",
                phase="acquire",
            ) from exc

        if connection.in_transaction():
            raise LiveOrderSubmissionBarrierUnavailableError(
                "배리어 획득 트랜잭션이 commit 후에도 열려 있습니다.",
                phase="acquire",
            )

    async def _release(
        self,
        connection: AsyncConnection,
        *,
        lock_mode: str,
    ) -> None:
        if connection.in_transaction():
            await _invalidate_and_close_safely(connection)
            raise LiveOrderSubmissionBarrierUnavailableError(
                "열린 트랜잭션이 남아 제출 배리어 connection을 폐기했습니다.",
                phase="release",
            )

        try:
            result = await connection.execute(
                _UNLOCK_STATEMENTS[lock_mode],
                {"lock_key": LIVE_ORDER_SUBMISSION_ADVISORY_LOCK_KEY},
            )
            unlocked = result.scalar_one()
            if unlocked is not True:
                raise LiveOrderSubmissionBarrierUnavailableError(
                    f"실주문 제출 {lock_mode} 배리어가 현재 세션에 없었습니다.",
                    phase="release",
                )
            await connection.commit()
        except BaseException as exc:
            await _invalidate_and_close_safely(connection)
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, LiveOrderSubmissionBarrierError):
                raise
            raise LiveOrderSubmissionBarrierUnavailableError(
                f"실주문 제출 {lock_mode} 배리어 해제에 실패했습니다.",
                phase="release",
            ) from exc

        try:
            await connection.close()
        except Exception as exc:
            await _invalidate_and_close_safely(connection)
            raise LiveOrderSubmissionBarrierUnavailableError(
                "배리어 해제 후 PostgreSQL connection 반환에 실패했습니다.",
                phase="release",
            ) from exc


def _validate_timeout(value: float, *, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0 or parsed > MAX_LOCK_TIMEOUT_SECONDS:
        raise ValueError(
            f"{name}은 0초 초과 {MAX_LOCK_TIMEOUT_SECONDS:g}초 이하의 유한값이어야 합니다."
        )
    return parsed


def _is_lock_timeout(exc: BaseException) -> bool:
    pending: list[BaseException] = [exc]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        sqlstate = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if sqlstate == _LOCK_TIMEOUT_SQLSTATE:
            return True
        for nested in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return "lock timeout" in str(exc).lower()


async def _finish_session_safely(session: AsyncSession) -> None:
    try:
        await session.close()
    except Exception as exc:
        raise LiveOrderSubmissionBarrierUnavailableError(
            "connection-bound AsyncSession을 닫지 못했습니다.",
            phase="lease",
        ) from exc


async def _rollback_safely(connection: AsyncConnection) -> None:
    try:
        await connection.rollback()
    except Exception:
        await _invalidate_and_close_safely(connection)


async def _invalidate_and_close_safely(connection: AsyncConnection) -> None:
    """불확실한 session lock이 pool에 재진입하지 않게 물리 연결을 폐기한다."""
    try:
        if not connection.closed:
            await connection.invalidate()
    except Exception:
        pass
    try:
        if not connection.closed:
            await connection.close()
    except Exception:
        pass


async def _run_cleanup_shielded(
    cleanup_factory: Callable[[], Awaitable[None]],
) -> None:
    """호출 task가 취소되어도 unlock/connection 폐기가 끝날 때까지 기다린다."""
    cleanup_task = asyncio.create_task(cleanup_factory())
    cancellation: asyncio.CancelledError | None = None
    while not cleanup_task.done():
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError as exc:
            cancellation = cancellation or exc

    cleanup_task.result()
    if cancellation is not None:
        raise cancellation
