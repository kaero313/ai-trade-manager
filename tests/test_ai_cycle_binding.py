from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.routes import ai as ai_route
from app.core import scheduler
from app.models.schemas import AIAnalysisResponse
from app.services.trading import ai_analyst, ai_executor
from app.services.trading.ai_analyst import _persist_ai_analysis_log


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"
EXPECTED_EXECUTOR_CALLERS = {
    "app/api/routes/ai.py",
    "app/core/scheduler.py",
}


class _AnalysisPersistenceDb:
    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.commit_error = commit_error
        self.added: list[Any] = []
        self.rollback_count = 0
        self.refresh_count = 0

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.added[-1].id = 73

    async def refresh(self, value: Any) -> None:
        assert value is self.added[-1]
        self.refresh_count += 1
        value.created_at = datetime(2026, 7, 14, 1, 2, 3, tzinfo=UTC)

    async def rollback(self) -> None:
        self.rollback_count += 1


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value


class _AnalysisQueryDb:
    def __init__(self, analyses: dict[int, Any]) -> None:
        self.analyses = analyses
        self.requested_ids: list[int] = []

    async def execute(self, statement: Any) -> _ScalarResult:
        compiled = statement.compile()
        sql = str(compiled).upper()
        requested_ids = [
            value
            for value in compiled.params.values()
            if isinstance(value, int) and value in self.analyses
        ]
        assert "AI_ANALYSIS_LOGS.ID" in sql
        assert "ORDER BY" not in sql
        assert len(requested_ids) == 1
        analysis_id = requested_ids[0]
        self.requested_ids.append(analysis_id)
        return _ScalarResult(self.analyses[analysis_id])


class _FavoriteScalars:
    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols

    def all(self) -> list[str]:
        return list(self.symbols)


class _FavoriteResult:
    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols

    def scalars(self) -> _FavoriteScalars:
        return _FavoriteScalars(self.symbols)


class _SchedulerDb:
    def __init__(self, symbols: list[str]) -> None:
        self.symbols = symbols

    async def execute(self, _statement: Any) -> _FavoriteResult:
        return _FavoriteResult(self.symbols)


class _SessionContext:
    def __init__(self, db: object) -> None:
        self.db = db

    async def __aenter__(self) -> object:
        return self.db

    async def __aexit__(self, *_args: Any) -> None:
        return None


def _analysis(
    analysis_id: int,
    *,
    symbol: str = "KRW-BTC",
    decision: str = "SELL",
    confidence: int = 90,
    recommended_weight: int = 25,
    created_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=analysis_id,
        symbol=symbol,
        decision=decision,
        confidence=confidence,
        recommended_weight=recommended_weight,
        reasoning=f"exact analysis {analysis_id}",
        created_at=created_at or datetime.now(UTC),
    )


async def _running_status(_db: object) -> SimpleNamespace:
    return SimpleNamespace(running=True)


async def _executor_thresholds(_db: object) -> tuple[int, int]:
    return 75, 90


async def _paper_mode(_db: object) -> str:
    return "paper"


async def _healthy_portfolio() -> SimpleNamespace:
    return SimpleNamespace(error=None)


def test_analysis_persistence_returns_the_committed_log() -> None:
    db = _AnalysisPersistenceDb()

    saved = asyncio.run(
        _persist_ai_analysis_log(
            db,
            "krw-btc",
            AIAnalysisResponse(
                decision="BUY",
                confidence=82,
                recommended_weight=20,
                reasoning="저장 성공",
            ),
        )
    )

    assert saved is db.added[0]
    assert saved.id == 73
    assert saved.symbol == "KRW-BTC"
    assert db.refresh_count == 1
    assert db.rollback_count == 0


def test_analysis_commit_failure_rolls_back_and_propagates() -> None:
    commit_error = RuntimeError("analysis commit failed")
    db = _AnalysisPersistenceDb(commit_error=commit_error)

    with pytest.raises(RuntimeError, match="analysis commit failed") as exc_info:
        asyncio.run(
            _persist_ai_analysis_log(
                db,
                "KRW-BTC",
                AIAnalysisResponse(
                    decision="BUY",
                    confidence=82,
                    recommended_weight=20,
                    reasoning="저장 실패",
                ),
            )
        )

    assert exc_info.value is commit_error
    assert db.rollback_count == 1
    assert db.refresh_count == 0


def test_execute_ai_analysis_propagates_real_persistence_failure(monkeypatch) -> None:
    commit_error = RuntimeError("analysis commit failed")
    db = _AnalysisPersistenceDb(commit_error=commit_error)

    async def gather_context(_db: object, symbol: str) -> dict[str, str]:
        assert symbol == "KRW-BTC"
        return {"symbol": symbol}

    async def get_config(*_args: Any, **_kwargs: Any) -> str:
        return ""

    async def load_feedback(_db: object, _symbol: str) -> str:
        return ""

    class FakeRouter:
        def __init__(self, received_db: object) -> None:
            assert received_db is db

        async def generate_structured_analysis(self, **_kwargs: Any) -> SimpleNamespace:
            return SimpleNamespace(
                value=AIAnalysisResponse(
                    decision="BUY",
                    confidence=82,
                    recommended_weight=20,
                    reasoning="저장 실패 전파",
                )
            )

    monkeypatch.setattr(ai_analyst, "gather_market_context", gather_context)
    monkeypatch.setattr(ai_analyst, "format_market_context_for_llm", lambda _context: "context")
    monkeypatch.setattr(ai_analyst, "get_system_config_value", get_config)
    monkeypatch.setattr(ai_analyst, "_load_recent_failure_feedback", load_feedback)
    monkeypatch.setattr(ai_analyst, "AIProviderRouter", FakeRouter)

    with pytest.raises(RuntimeError, match="analysis commit failed") as exc_info:
        asyncio.run(ai_analyst.execute_ai_analysis(db, "KRW-BTC"))

    assert exc_info.value is commit_error
    assert db.rollback_count == 1


def test_test_analysis_api_keeps_existing_response_contract(monkeypatch) -> None:
    analysis = _analysis(74, decision="BUY", confidence=82, recommended_weight=20)

    async def execute_analysis(_db: object, symbol: str) -> SimpleNamespace:
        assert symbol == "KRW-BTC"
        return analysis

    monkeypatch.setattr(ai_route, "execute_ai_analysis", execute_analysis)

    response = asyncio.run(ai_route.trigger_ai_analysis_now("krw-btc", db=object()))

    assert response == {
        "symbol": "KRW-BTC",
        "decision": "BUY",
        "confidence": 82,
        "recommended_weight": 20,
        "reasoning": "exact analysis 74",
    }


@pytest.mark.parametrize(
    ("analysis_id", "loaded_analysis", "expected_loads"),
    [
        (None, None, []),
        (999, None, [999]),
        (41, _analysis(41, symbol="KRW-ETH"), [41]),
    ],
)
def test_execute_ai_trade_fails_closed_for_invalid_analysis_identity(
    monkeypatch,
    analysis_id: int | None,
    loaded_analysis: SimpleNamespace | None,
    expected_loads: list[int],
) -> None:
    loaded_ids: list[int] = []

    async def load_by_id(_db: object, received_id: int) -> SimpleNamespace | None:
        loaded_ids.append(received_id)
        return loaded_analysis

    class UnexpectedPortfolioService:
        def __init__(self, _db: object) -> None:
            raise AssertionError("잘못된 분석 identity에서 포트폴리오를 조회하면 안 됩니다.")

    monkeypatch.setattr(ai_executor, "get_bot_status", _running_status)
    monkeypatch.setattr(ai_executor, "_load_analysis_by_id", load_by_id)
    monkeypatch.setattr(ai_executor, "PortfolioService", UnexpectedPortfolioService)

    result = asyncio.run(
        ai_executor.execute_ai_trade(
            object(),
            "KRW-BTC",
            analysis_id=analysis_id,
        )
    )

    assert result is None
    assert loaded_ids == expected_loads


def test_exact_analysis_id_is_not_replaced_by_newer_analysis(monkeypatch) -> None:
    analysis_a = _analysis(51, decision="SELL")
    analysis_b = _analysis(52, decision="BUY")
    db = _AnalysisQueryDb({analysis_a.id: analysis_a, analysis_b.id: analysis_b})
    executed_analysis_ids: list[int] = []

    async def execute_sell(**kwargs: Any) -> None:
        executed_analysis_ids.append(kwargs["analysis"].id)

    monkeypatch.setattr(ai_executor, "get_bot_status", _running_status)
    monkeypatch.setattr(ai_executor, "_load_executor_thresholds", _executor_thresholds)
    monkeypatch.setattr(
        ai_executor,
        "PortfolioService",
        lambda _db: SimpleNamespace(get_aggregated_portfolio=_healthy_portfolio),
    )
    monkeypatch.setattr(ai_executor, "get_trading_mode", _paper_mode)
    monkeypatch.setattr(ai_executor, "_execute_sell_trade", execute_sell)

    asyncio.run(
        ai_executor.execute_ai_trade(
            db,
            "KRW-BTC",
            analysis_id=analysis_a.id,
        )
    )

    assert db.requested_ids == [analysis_a.id]
    assert executed_analysis_ids == [analysis_a.id]


def test_exact_buy_analysis_keeps_entry_gate_and_execution_flow(monkeypatch) -> None:
    analysis = _analysis(61, decision="BUY")
    executed_analysis_ids: list[int] = []

    async def load_by_id(_db: object, analysis_id: int) -> SimpleNamespace:
        assert analysis_id == analysis.id
        return analysis

    async def allow_entry(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            allowed=True,
            shadow_mode=False,
            to_log_dict=lambda: {"allowed": True},
        )

    async def execute_buy(**kwargs: Any) -> None:
        executed_analysis_ids.append(kwargs["analysis"].id)

    monkeypatch.setattr(ai_executor, "get_bot_status", _running_status)
    monkeypatch.setattr(ai_executor, "_load_analysis_by_id", load_by_id)
    monkeypatch.setattr(ai_executor, "_load_executor_thresholds", _executor_thresholds)
    monkeypatch.setattr(
        ai_executor,
        "PortfolioService",
        lambda _db: SimpleNamespace(get_aggregated_portfolio=_healthy_portfolio),
    )
    monkeypatch.setattr(ai_executor, "get_trading_mode", _paper_mode)
    monkeypatch.setattr(ai_executor, "evaluate_ai_buy_entry_gate", allow_entry)
    monkeypatch.setattr(ai_executor, "_execute_buy_trade", execute_buy)

    asyncio.run(
        ai_executor.execute_ai_trade(
            object(),
            "KRW-BTC",
            analysis_id=analysis.id,
        )
    )

    assert executed_analysis_ids == [analysis.id]


def test_exact_hold_analysis_does_not_reach_portfolio_or_order(monkeypatch) -> None:
    analysis = _analysis(62, decision="HOLD", recommended_weight=0)

    async def load_by_id(_db: object, analysis_id: int) -> SimpleNamespace:
        assert analysis_id == analysis.id
        return analysis

    class UnexpectedPortfolioService:
        def __init__(self, _db: object) -> None:
            raise AssertionError("HOLD 분석에서 포트폴리오를 조회하면 안 됩니다.")

    monkeypatch.setattr(ai_executor, "get_bot_status", _running_status)
    monkeypatch.setattr(ai_executor, "_load_analysis_by_id", load_by_id)
    monkeypatch.setattr(ai_executor, "_load_executor_thresholds", _executor_thresholds)
    monkeypatch.setattr(ai_executor, "PortfolioService", UnexpectedPortfolioService)

    result = asyncio.run(
        ai_executor.execute_ai_trade(
            object(),
            "KRW-BTC",
            analysis_id=analysis.id,
        )
    )

    assert result is None


@pytest.mark.parametrize(
    "analysis",
    [
        _analysis(71, created_at=datetime.now(UTC) - timedelta(minutes=91)),
        _analysis(72, confidence=74),
    ],
)
def test_exact_analysis_preserves_stale_and_confidence_guards(
    monkeypatch,
    analysis: SimpleNamespace,
) -> None:
    async def load_by_id(_db: object, analysis_id: int) -> SimpleNamespace:
        assert analysis_id == analysis.id
        return analysis

    class UnexpectedPortfolioService:
        def __init__(self, _db: object) -> None:
            raise AssertionError("stale/confidence 차단 후 포트폴리오를 조회하면 안 됩니다.")

    monkeypatch.setattr(ai_executor, "get_bot_status", _running_status)
    monkeypatch.setattr(ai_executor, "_load_analysis_by_id", load_by_id)
    monkeypatch.setattr(ai_executor, "_load_executor_thresholds", _executor_thresholds)
    monkeypatch.setattr(ai_executor, "PortfolioService", UnexpectedPortfolioService)

    result = asyncio.run(
        ai_executor.execute_ai_trade(
            object(),
            "KRW-BTC",
            analysis_id=analysis.id,
        )
    )

    assert result is None


def test_scheduler_uses_each_cycle_analysis_id_and_continues_after_failure(monkeypatch) -> None:
    db = _SchedulerDb(["KRW-BTC", "KRW-ETH"])
    analyzed: list[str] = []
    traded: list[tuple[str, int | None]] = []

    async def hard_risk_check(_db: object) -> set[str]:
        return set()

    async def load_gate(_db: object) -> SimpleNamespace:
        return SimpleNamespace()

    def filter_symbols(symbols: list[str], _config: object) -> list[str]:
        return symbols

    async def execute_analysis(_db: object, symbol: str) -> SimpleNamespace:
        analyzed.append(symbol)
        if symbol == "KRW-BTC":
            raise RuntimeError("analysis persistence failed")
        return _analysis(92, symbol=symbol)

    async def execute_trade(
        _db: object,
        symbol: str,
        *,
        analysis_id: int | None = None,
    ) -> None:
        traded.append((symbol, analysis_id))

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(scheduler, "AsyncSessionLocal", lambda: _SessionContext(db))
    monkeypatch.setattr(scheduler, "execute_hard_tp_sl_check", hard_risk_check)
    monkeypatch.setattr(scheduler, "load_entry_gate_config", load_gate)
    monkeypatch.setattr(scheduler, "filter_trade_symbols", filter_symbols)
    monkeypatch.setattr(scheduler, "execute_ai_analysis", execute_analysis)
    monkeypatch.setattr(scheduler, "execute_ai_trade", execute_trade)
    monkeypatch.setattr(scheduler.asyncio, "sleep", no_sleep)

    asyncio.run(scheduler.autonomous_ai_analyst_job())

    assert analyzed == ["KRW-BTC", "KRW-ETH"]
    assert traded == [("KRW-ETH", 92)]


def test_production_ai_trade_callers_pass_explicit_analysis_id() -> None:
    callers: set[str] = set()
    violations: list[str] = []

    for path in APP_ROOT.rglob("*.py"):
        relative_path = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if function_name != "execute_ai_trade":
                continue
            callers.add(relative_path)
            if not any(keyword.arg == "analysis_id" for keyword in node.keywords):
                violations.append(f"{relative_path}:{node.lineno}")

    assert callers == EXPECTED_EXECUTOR_CALLERS
    assert not violations, "analysis_id가 없는 AI 주문 실행 호출:\n" + "\n".join(violations)


def test_ai_executor_has_no_latest_analysis_fallback() -> None:
    path = APP_ROOT / "services" / "trading" / "ai_executor.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    latest_analysis_references: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "_load_latest_analysis":
            latest_analysis_references.append(node.lineno)
        if isinstance(node, ast.Attribute) and node.attr == "_load_latest_analysis":
            latest_analysis_references.append(node.lineno)

    assert latest_analysis_references == []
