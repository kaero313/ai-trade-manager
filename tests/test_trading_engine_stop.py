from __future__ import annotations

import asyncio

from app.services.trading.engine import TradingEngine


class _FailOnUseSessionFactory:
    def __call__(self):
        raise AssertionError("정지된 TradingEngine이 DB 세션을 열면 안 됩니다.")


def test_stop_is_public_and_flips_running_flag() -> None:
    engine = TradingEngine(_FailOnUseSessionFactory())

    assert engine.is_running is True

    engine.stop()

    assert engine.is_running is False


def test_stopped_engine_run_loop_exits_without_touching_db() -> None:
    engine = TradingEngine(_FailOnUseSessionFactory())
    engine.stop()

    asyncio.run(asyncio.wait_for(engine.run_loop(), timeout=1))
