import asyncio
from contextlib import asynccontextmanager

import pytest

from app.models.domain import BotConfig as BotConfigORM
from app.models.schemas import BotStatus
from app.services import bot_service


class _ControlSession:
    def __init__(self) -> None:
        self.bot_config = BotConfigORM(id=1, config_json={}, is_active=False)
        self.flush_count = 0

    async def get(self, _model, _identity, *, with_for_update=False):
        assert with_for_update is True
        return self.bot_config

    def add(self, _value) -> None:
        raise AssertionError("기존 BotConfig 테스트에서는 add가 호출되면 안 됩니다.")

    async def flush(self) -> None:
        self.flush_count += 1
        await asyncio.sleep(0)


class _Lease:
    def __init__(self, control_db: _ControlSession) -> None:
        self.control_db = control_db

    @asynccontextmanager
    async def transaction(self):
        yield self.control_db


class _SerialBarrier:
    def __init__(self, control_db: _ControlSession) -> None:
        self.control_db = control_db
        self.lock = asyncio.Lock()
        self.exclusive_call_count = 0
        self.active_holders = 0
        self.max_active_holders = 0

    @asynccontextmanager
    async def exclusive(self):
        self.exclusive_call_count += 1
        async with self.lock:
            self.active_holders += 1
            self.max_active_holders = max(
                self.max_active_holders,
                self.active_holders,
            )
            try:
                yield _Lease(self.control_db)
            finally:
                self.active_holders -= 1


class _RequestSession:
    def __init__(self) -> None:
        self.rollback_count = 0

    def in_transaction(self) -> bool:
        return True

    async def rollback(self) -> None:
        self.rollback_count += 1


@pytest.mark.asyncio
async def test_start_bot_uses_same_exclusive_barrier_and_atomic_runtime_update(
    monkeypatch,
) -> None:
    control_db = _ControlSession()
    barrier = _SerialBarrier(control_db)
    request_db = _RequestSession()

    async def current_status(db):
        assert db is request_db
        return BotStatus(running=control_db.bot_config.is_active)

    monkeypatch.setattr(bot_service, "get_bot_status", current_status)

    async def competing_live_transition() -> None:
        async with barrier.exclusive() as lease:
            async with lease.transaction():
                await asyncio.sleep(0)

    result, _ = await asyncio.gather(
        bot_service.start_bot(request_db, barrier=barrier),  # type: ignore[arg-type]
        competing_live_transition(),
    )

    assert result.running is True
    assert control_db.bot_config.is_active is True
    assert control_db.bot_config.runtime_latest_action == bot_service.DEFAULT_START_ACTION
    assert control_db.bot_config.runtime_last_error is None
    assert control_db.bot_config.runtime_updated_at is not None
    assert control_db.bot_config.config_json == {}
    assert barrier.exclusive_call_count == 2
    assert barrier.max_active_holders == 1
    assert request_db.rollback_count == 1
