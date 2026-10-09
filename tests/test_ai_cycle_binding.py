from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.routes import ai as ai_route
from app.models.schemas import AIAnalysisResponse
from app.services.trading import ai_analyst
from app.services.trading import ai_executor
from app.services.trading.ai_analyst import _persist_ai_analysis_log


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"
EXPECTED_EXECUTOR_CALLERS = {
    "app/api/routes/ai.py",
    "app/core/scheduler.py",
}
PRIMARY_LINEAGE = {
    "provider": "openai",
    "model": "gpt-test",
    "fallback_used": False,
    "context_sha256": "a" * 64,
}


class _AnalysisPersistenceDb:
    def __init__(
        self,
        *,
        commit_error: Exception | None = None,
        refresh_error: Exception | None = None,
        persisted_id: int | None = 73,
    ) -> None:
        self.commit_error = commit_error
        self.refresh_error = refresh_error
        self.persisted_id = persisted_id
        self.added: list[Any] = []
        self.rollback_count = 0
        self.refresh_count = 0

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.added[-1].id = self.persisted_id

    async def refresh(self, value: Any) -> None:
        assert value is self.added[-1]
        self.refresh_count += 1
        if self.refresh_error is not None:
            raise self.refresh_error
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


@pytest.mark.asyncio
async def test_analysis_persistence_returns_the_committed_log() -> None:
    db = _AnalysisPersistenceDb()

    saved = await _persist_ai_analysis_log(
        db,
        "krw-btc",
        AIAnalysisResponse(
            decision="BUY",
            confidence=82,
            recommended_weight=20,
            reasoning="저장 성공",
        ),
        **PRIMARY_LINEAGE,
    )

    assert saved is db.added[0]
    assert saved.id == 73
    assert saved.symbol == "KRW-BTC"
    assert db.refresh_count == 1
    assert db.rollback_count == 0


@pytest.mark.asyncio
async def test_analysis_commit_failure_rolls_back_and_propagates() -> None:
    commit_error = RuntimeError("analysis commit failed")
    db = _AnalysisPersistenceDb(commit_error=commit_error)

    with pytest.raises(RuntimeError, match="analysis commit failed") as exc_info:
        await _persist_ai_analysis_log(
            db,
            "KRW-BTC",
            AIAnalysisResponse(
                decision="BUY",
                confidence=82,
                recommended_weight=20,
                reasoning="저장 실패",
            ),
            **PRIMARY_LINEAGE,
        )

    assert exc_info.value is commit_error
    assert db.rollback_count == 1
    assert db.refresh_count == 0


@pytest.mark.asyncio
async def test_analysis_refresh_failure_rolls_back_and_propagates() -> None:
    refresh_error = RuntimeError("analysis refresh failed")
    db = _AnalysisPersistenceDb(refresh_error=refresh_error)

    with pytest.raises(RuntimeError, match="analysis refresh failed") as exc_info:
        await _persist_ai_analysis_log(
            db,
            "KRW-BTC",
            AIAnalysisResponse(
                decision="BUY",
                confidence=82,
                recommended_weight=20,
                reasoning="refresh 실패",
            ),
            **PRIMARY_LINEAGE,
        )

    assert exc_info.value is refresh_error
    assert db.rollback_count == 1
    assert db.refresh_count == 1


@pytest.mark.asyncio
async def test_analysis_missing_id_rolls_back_and_propagates() -> None:
    db = _AnalysisPersistenceDb(persisted_id=None)

    with pytest.raises(RuntimeError, match="ID"):
        await _persist_ai_analysis_log(
            db,
            "KRW-BTC",
            AIAnalysisResponse(
                decision="SELL",
                confidence=88,
                recommended_weight=100,
                reasoning="ID 미확정",
            ),
            **PRIMARY_LINEAGE,
        )

    assert db.added[0].id is None
    assert db.rollback_count == 1
    assert db.refresh_count == 1


@pytest.mark.asyncio
async def test_execute_ai_analysis_propagates_real_persistence_failure(
    monkeypatch,
) -> None:
    commit_error = RuntimeError("analysis commit failed")
    db = _AnalysisPersistenceDb(commit_error=commit_error)

    async def gather_context(_db: object, symbol: str) -> dict[str, str]:
        assert symbol == "KRW-BTC"
        return {"symbol": symbol}

    async def get_config(*_args, **_kwargs) -> str:
        return ""

    async def load_feedback(_db: object, _symbol: str) -> str:
        return ""

    class FakeRouter:
        def __init__(self, received_db: object) -> None:
            assert received_db is db

        async def generate_structured_analysis(self, **_kwargs):
            return SimpleNamespace(
                value=AIAnalysisResponse(
                    decision="BUY",
                    confidence=82,
                    recommended_weight=20,
                    reasoning="저장 실패 전파",
                ),
                provider="openai",
                model="gpt-test",
                fallback_used=False,
            )

    monkeypatch.setattr(ai_analyst, "gather_market_context", gather_context)
    monkeypatch.setattr(
        ai_analyst,
        "format_market_context_for_llm",
        lambda _context: "context",
    )
    monkeypatch.setattr(ai_analyst, "get_system_config_value", get_config)
    monkeypatch.setattr(ai_analyst, "_load_recent_failure_feedback", load_feedback)
    monkeypatch.setattr(ai_analyst, "AIProviderRouter", FakeRouter)

    with pytest.raises(RuntimeError, match="analysis commit failed") as exc_info:
        await ai_analyst.execute_ai_analysis(db, "KRW-BTC")

    assert exc_info.value is commit_error
    assert db.rollback_count == 1


@pytest.mark.asyncio
async def test_test_analysis_api_keeps_existing_response_contract(monkeypatch) -> None:
    analysis = _analysis(74, decision="BUY", confidence=82, recommended_weight=20)

    async def execute_analysis(_db: object, symbol: str):
        assert symbol == "KRW-BTC"
        return analysis

    monkeypatch.setattr(ai_route, "execute_ai_analysis", execute_analysis)

    response = await ai_route.trigger_ai_analysis_now("krw-btc", db=object())

    assert response == {
        "symbol": "KRW-BTC",
        "decision": "BUY",
        "confidence": 82,
        "recommended_weight": 20,
        "reasoning": "exact analysis 74",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("analysis_id", "loaded_analysis", "expected_loads"),
    [
        (None, None, []),
        (999, None, [999]),
        (41, _analysis(41, symbol="KRW-ETH"), [41]),
    ],
)
async def test_execute_ai_trade_fails_closed_for_invalid_analysis_identity(
    monkeypatch,
    analysis_id: int | None,
    loaded_analysis: SimpleNamespace | None,
    expected_loads: list[int],
) -> None:
    loaded_ids: list[int] = []

    async def load_by_id(_db: object, received_id: int):
        loaded_ids.append(received_id)
        return loaded_analysis

    class UnexpectedPortfolioService:
        def __init__(self, _db: object) -> None:
            raise AssertionError("잘못된 분석 identity에서 포트폴리오를 조회하면 안 됩니다.")

    monkeypatch.setattr(ai_executor, "get_bot_status", _running_status)
    monkeypatch.setattr(ai_executor, "_load_analysis_by_id", load_by_id)
    monkeypatch.setattr(ai_executor, "PortfolioService", UnexpectedPortfolioService)

    result = await ai_executor.execute_ai_trade(
        object(),
        "KRW-BTC",
        analysis_id=analysis_id,
    )

    assert result is None
    assert loaded_ids == expected_loads


@pytest.mark.asyncio
async def test_exact_analysis_id_is_not_replaced_by_newer_analysis(
    monkeypatch,
) -> None:
    analysis_a = _analysis(51, decision="SELL")
    analysis_b = _analysis(52, decision="BUY")
    analyses = {analysis_a.id: analysis_a, analysis_b.id: analysis_b}
    db = _AnalysisQueryDb(analyses)
    executed_analysis_ids: list[int] = []
    sentinel = object()

    async def execute_sell(**kwargs):
        executed_analysis_ids.append(kwargs["analysis"].id)
        return sentinel

    monkeypatch.setattr(ai_executor, "get_bot_status", _running_status)
    monkeypatch.setattr(ai_executor, "_load_executor_thresholds", _executor_thresholds)
    monkeypatch.setattr(
        ai_executor,
        "PortfolioService",
        lambda _db: SimpleNamespace(get_aggregated_portfolio=_healthy_portfolio),
    )
    monkeypatch.setattr(ai_executor, "get_trading_mode", _paper_mode)
    monkeypatch.setattr(ai_executor, "_execute_sell_trade", execute_sell)

    result = await ai_executor.execute_ai_trade(
        db,
        "KRW-BTC",
        analysis_id=analysis_a.id,
    )

    assert result is sentinel
    assert db.requested_ids == [analysis_a.id]
    assert executed_analysis_ids == [analysis_a.id]


@pytest.mark.asyncio
async def test_exact_buy_analysis_keeps_entry_gate_and_execution_flow(monkeypatch) -> None:
    analysis = _analysis(61, decision="BUY")
    executed_analysis_ids: list[int] = []
    sentinel = object()

    async def load_by_id(_db: object, analysis_id: int):
        assert analysis_id == analysis.id
        return analysis

    async def allow_entry(*_args, **_kwargs):
        return SimpleNamespace(
            allowed=True,
            shadow_mode=False,
            to_log_dict=lambda: {"allowed": True},
        )

    async def execute_buy(**kwargs):
        executed_analysis_ids.append(kwargs["analysis"].id)
        assert kwargs["primary_recommended_weight"] == analysis.recommended_weight
        return sentinel

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

    result = await ai_executor.execute_ai_trade(
        object(),
        "KRW-BTC",
        analysis_id=analysis.id,
        risk_check=ai_executor.RiskCheckResult(
            status=ai_executor.RiskCheckStatus.HEALTHY,
        ),
    )

    assert result is sentinel
    assert executed_analysis_ids == [analysis.id]


@pytest.mark.asyncio
async def test_exact_hold_analysis_does_not_reach_portfolio_or_order(monkeypatch) -> None:
    analysis = _analysis(62, decision="HOLD", recommended_weight=0)

    async def load_by_id(_db: object, analysis_id: int):
        assert analysis_id == analysis.id
        return analysis

    class UnexpectedPortfolioService:
        def __init__(self, _db: object) -> None:
            raise AssertionError("HOLD 분석에서 포트폴리오를 조회하면 안 됩니다.")

    monkeypatch.setattr(ai_executor, "get_bot_status", _running_status)
    monkeypatch.setattr(ai_executor, "_load_analysis_by_id", load_by_id)
    monkeypatch.setattr(ai_executor, "_load_executor_thresholds", _executor_thresholds)
    monkeypatch.setattr(ai_executor, "PortfolioService", UnexpectedPortfolioService)

    result = await ai_executor.execute_ai_trade(
        object(),
        "KRW-BTC",
        analysis_id=analysis.id,
        risk_check=ai_executor.RiskCheckResult(
            status=ai_executor.RiskCheckStatus.HEALTHY,
        ),
    )

    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "analysis",
    [
        _analysis(71, created_at=datetime.now(UTC) - timedelta(minutes=91)),
        _analysis(72, confidence=74),
    ],
)
async def test_exact_analysis_preserves_stale_and_confidence_guards(
    monkeypatch,
    analysis: SimpleNamespace,
) -> None:
    async def load_by_id(_db: object, analysis_id: int):
        assert analysis_id == analysis.id
        return analysis

    class UnexpectedPortfolioService:
        def __init__(self, _db: object) -> None:
            raise AssertionError("stale/confidence 차단 후 포트폴리오를 조회하면 안 됩니다.")

    monkeypatch.setattr(ai_executor, "get_bot_status", _running_status)
    monkeypatch.setattr(ai_executor, "_load_analysis_by_id", load_by_id)
    monkeypatch.setattr(ai_executor, "_load_executor_thresholds", _executor_thresholds)
    monkeypatch.setattr(ai_executor, "PortfolioService", UnexpectedPortfolioService)

    result = await ai_executor.execute_ai_trade(
        object(),
        "KRW-BTC",
        analysis_id=analysis.id,
    )

    assert result is None


@pytest.mark.asyncio
async def test_exact_buy_analysis_preserves_entry_gate_veto(monkeypatch) -> None:
    analysis = _analysis(81, decision="BUY")

    async def load_by_id(_db: object, analysis_id: int):
        assert analysis_id == analysis.id
        return analysis

    async def deny_entry(*_args, **_kwargs):
        return SimpleNamespace(
            allowed=False,
            shadow_mode=False,
            to_log_dict=lambda: {"allowed": False},
        )

    async def unexpected_buy(**_kwargs):
        raise AssertionError("EntryGate 거절 뒤 주문 실행 함수에 도달하면 안 됩니다.")

    monkeypatch.setattr(ai_executor, "get_bot_status", _running_status)
    monkeypatch.setattr(ai_executor, "_load_analysis_by_id", load_by_id)
    monkeypatch.setattr(ai_executor, "_load_executor_thresholds", _executor_thresholds)
    monkeypatch.setattr(
        ai_executor,
        "PortfolioService",
        lambda _db: SimpleNamespace(get_aggregated_portfolio=_healthy_portfolio),
    )
    monkeypatch.setattr(ai_executor, "get_trading_mode", _paper_mode)
    monkeypatch.setattr(ai_executor, "evaluate_ai_buy_entry_gate", deny_entry)
    monkeypatch.setattr(ai_executor, "_execute_buy_trade", unexpected_buy)

    result = await ai_executor.execute_ai_trade(
        object(),
        "KRW-BTC",
        analysis_id=analysis.id,
        risk_check=ai_executor.RiskCheckResult(
            status=ai_executor.RiskCheckStatus.HEALTHY,
        ),
    )

    assert result is None


@pytest.mark.architecture
def test_production_ai_trade_callers_pass_explicit_cycle_context() -> None:
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
            if not any(keyword.arg == "risk_check" for keyword in node.keywords):
                violations.append(f"{relative_path}:{node.lineno}:risk_check")

    assert callers == EXPECTED_EXECUTOR_CALLERS
    assert not violations, "cycle context가 없는 AI 주문 실행 호출:\n" + "\n".join(violations)


@pytest.mark.architecture
def test_ai_executor_has_no_latest_analysis_fallback() -> None:
    path = APP_ROOT / "services" / "trading" / "ai_executor.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    latest_analysis_references = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "_load_latest_analysis":
            latest_analysis_references.append(node.lineno)
        if isinstance(node, ast.Attribute) and node.attr == "_load_latest_analysis":
            latest_analysis_references.append(node.lineno)

    assert latest_analysis_references == []
