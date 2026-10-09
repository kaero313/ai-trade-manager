from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace

import pytest

scheduler_module = importlib.import_module("app.core.scheduler")


class _FailOnQuerySession:
    async def execute(self, _statement):
        raise AssertionError("runtime 정지 시 watchlist DB 조회를 수행하면 안 됩니다.")


class _SessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *_args) -> None:
        return None


class _SessionFactory:
    def __init__(self, session: object) -> None:
        self.session = session

    def __call__(self) -> _SessionContext:
        return _SessionContext(self.session)


class _WatchlistResult:
    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols

    def scalars(self) -> _WatchlistResult:
        return self

    def all(self) -> list[str]:
        return self.symbols


class _WatchlistSession:
    async def execute(self, _statement):
        return _WatchlistResult(["KRW-BTC", "KRW-ETH"])


@pytest.mark.asyncio
async def test_inactive_runtime_skips_all_autonomous_risk_provider_and_trade_calls(
    monkeypatch,
    caplog,
) -> None:
    caplog.set_level(logging.INFO, logger=scheduler_module.logger.name)
    session = _FailOnQuerySession()
    calls = {
        "hard_risk": 0,
        "analysis": 0,
        "trade": 0,
        "status": 0,
    }

    async def get_inactive_runtime(received_session):
        assert received_session is session
        return SimpleNamespace(is_active=False)

    async def update_runtime_status(received_session, **kwargs):
        assert received_session is session
        assert kwargs["latest_action"] == "봇 정지 상태로 자율주행 AI 분석 건너뜀"
        calls["status"] += 1

    async def hard_risk(_db):
        calls["hard_risk"] += 1
        return scheduler_module.RiskCheckResult(
            status=scheduler_module.RiskCheckStatus.DISABLED,
        )

    async def analysis(_db, _symbol):
        calls["analysis"] += 1

    async def trade(_db, _symbol):
        calls["trade"] += 1

    monkeypatch.setattr(
        scheduler_module,
        "AsyncSessionLocal",
        _SessionFactory(session),
    )
    monkeypatch.setattr(
        scheduler_module,
        "get_or_create_bot_config",
        get_inactive_runtime,
    )
    monkeypatch.setattr(
        scheduler_module,
        "update_bot_runtime_status",
        update_runtime_status,
    )
    monkeypatch.setattr(scheduler_module, "execute_hard_tp_sl_check", hard_risk)
    monkeypatch.setattr(scheduler_module, "execute_ai_analysis", analysis)
    monkeypatch.setattr(scheduler_module, "execute_ai_trade", trade)

    await scheduler_module.autonomous_ai_analyst_job()

    assert calls == {
        "hard_risk": 0,
        "analysis": 0,
        "trade": 0,
        "status": 1,
    }
    assert "봇 정지 상태로 자율주행 AI 분석 건너뜀" in caplog.text


@pytest.mark.asyncio
async def test_autonomous_cycle_skips_failed_symbol_and_passes_exact_analysis_id(
    monkeypatch,
) -> None:
    session = _WatchlistSession()
    analysis_calls: list[str] = []
    trade_calls: list[tuple[str, int | None, object]] = []

    async def get_active_runtime(received_session):
        assert received_session is session
        return SimpleNamespace(is_active=True)

    async def hard_risk(received_session):
        assert received_session is session
        return scheduler_module.RiskCheckResult(
            status=scheduler_module.RiskCheckStatus.DISABLED,
        )

    async def load_config(received_session):
        assert received_session is session
        return object()

    def keep_symbols(symbols, _config):
        return symbols

    async def analysis(_db, symbol: str):
        analysis_calls.append(symbol)
        if symbol == "KRW-BTC":
            raise RuntimeError("analysis commit failed")
        return SimpleNamespace(id=202, symbol=symbol)

    async def trade(
        _db,
        symbol: str,
        *,
        analysis_id: int | None = None,
        risk_check=None,
    ):
        trade_calls.append((symbol, analysis_id, risk_check.status))

    monkeypatch.setattr(scheduler_module, "AsyncSessionLocal", _SessionFactory(session))
    monkeypatch.setattr(
        scheduler_module,
        "get_or_create_bot_config",
        get_active_runtime,
    )
    monkeypatch.setattr(scheduler_module, "execute_hard_tp_sl_check", hard_risk)
    monkeypatch.setattr(scheduler_module, "load_entry_gate_config", load_config)
    monkeypatch.setattr(scheduler_module, "filter_trade_symbols", keep_symbols)
    monkeypatch.setattr(scheduler_module, "execute_ai_analysis", analysis)
    monkeypatch.setattr(scheduler_module, "execute_ai_trade", trade)
    monkeypatch.setattr(
        scheduler_module,
        "AUTONOMOUS_AI_ANALYST_SYMBOL_DELAY_SECONDS",
        0,
    )

    await scheduler_module.autonomous_ai_analyst_job()

    assert analysis_calls == ["KRW-BTC", "KRW-ETH"]
    assert trade_calls == [
        ("KRW-ETH", 202, scheduler_module.RiskCheckStatus.DISABLED),
    ]


@pytest.mark.asyncio
async def test_autonomous_cycle_preserves_unknown_risk_after_hard_check_failure(
    monkeypatch,
) -> None:
    session = _WatchlistSession()
    received_risk = []

    async def get_active_runtime(_db):
        return SimpleNamespace(is_active=True)

    async def hard_risk(_db):
        raise RuntimeError("risk check failed")

    async def load_config(_db):
        return object()

    async def analysis(_db, symbol: str):
        return SimpleNamespace(id=303, symbol=symbol)

    async def trade(
        _db,
        _symbol: str,
        *,
        analysis_id: int | None = None,
        risk_check=None,
    ):
        assert analysis_id == 303
        received_risk.append(risk_check)

    monkeypatch.setattr(scheduler_module, "AsyncSessionLocal", _SessionFactory(session))
    monkeypatch.setattr(scheduler_module, "get_or_create_bot_config", get_active_runtime)
    monkeypatch.setattr(scheduler_module, "execute_hard_tp_sl_check", hard_risk)
    monkeypatch.setattr(scheduler_module, "load_entry_gate_config", load_config)
    monkeypatch.setattr(
        scheduler_module,
        "filter_trade_symbols",
        lambda symbols, _config: symbols[:1],
    )
    monkeypatch.setattr(scheduler_module, "execute_ai_analysis", analysis)
    monkeypatch.setattr(scheduler_module, "execute_ai_trade", trade)

    await scheduler_module.autonomous_ai_analyst_job()

    assert len(received_risk) == 1
    assert received_risk[0].status is scheduler_module.RiskCheckStatus.UNKNOWN
    assert received_risk[0].reasons == ("HARD_RISK_CHECK_FAILED",)


@pytest.mark.asyncio
async def test_reconciliation_continues_without_reading_runtime_state(monkeypatch) -> None:
    events: list[str] = []
    broker = object()

    async def unexpected_runtime_read(_db):
        raise AssertionError("reconciliation은 runtime 상태를 읽으면 안 됩니다.")

    class _ReconciliationService:
        def __init__(self, session_factory, received_broker, submission_barrier):
            assert session_factory is scheduler_module.AsyncSessionLocal
            assert received_broker is broker
            assert submission_barrier is not None

        async def reconcile_due(self, limit: int = 20):
            events.append(f"reconcile:{limit}")
            return []

    class _LiquidationCoordinator:
        def __init__(self, session_factory, received_broker, submission_barrier):
            assert session_factory is scheduler_module.AsyncSessionLocal
            assert received_broker is broker
            assert submission_barrier is not None

        async def refresh_in_progress_operations(self):
            events.append("refresh-liquidations")
            return 0

    monkeypatch.setattr(
        scheduler_module,
        "get_or_create_bot_config",
        unexpected_runtime_read,
    )
    monkeypatch.setattr(
        scheduler_module.BrokerFactory,
        "get_broker",
        classmethod(lambda cls, _broker_id: broker),
    )
    monkeypatch.setattr(
        scheduler_module,
        "LiveOrderExecutionService",
        _ReconciliationService,
    )
    monkeypatch.setattr(
        scheduler_module,
        "LiquidationCoordinator",
        _LiquidationCoordinator,
    )

    await scheduler_module.live_order_reconciliation_job()

    assert events == ["reconcile:20", "refresh-liquidations"]
