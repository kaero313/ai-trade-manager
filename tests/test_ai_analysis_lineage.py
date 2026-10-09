from __future__ import annotations

from datetime import UTC, datetime
import importlib
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.api.routes import ai as ai_route
from app.api.routes import portfolio as portfolio_route
from app.models.schemas import AIAnalysisResponse
from app.schemas.portfolio import PortfolioSummary
from app.services.ai.provider_router import AIProviderExecutionResult
from app.services.ai.provider_router import AIProviderUnavailableError
from app.services.chat import tools as chat_tools
from app.services.trading import accuracy_worker
from app.services.trading import ai_analyst
from app.services.trading import ai_executor
from app.services.trading import entry_policy
from app.services.trading.analysis_lineage import AI_ANALYSIS_DETERMINISTIC_HOLD_MODEL
from app.services.trading.analysis_lineage import AI_ANALYSIS_STAGE_BUY_PRECHECK
from app.services.trading.analysis_lineage import AI_ANALYSIS_STAGE_LEGACY
from app.services.trading.analysis_lineage import AI_ANALYSIS_STAGE_TRADE
from app.services.trading.analysis_lineage import AI_ANALYSIS_SYSTEM_PROVIDER
from app.services.trading.analysis_lineage import BUY_PRECHECK_PROMPT_VERSION
from app.services.trading.analysis_lineage import TRADE_ANALYSIS_PROMPT_VERSION
from app.services.trading.analysis_lineage import hash_analysis_context


class _ScalarValues:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return list(self._values)


class _Result:
    def __init__(
        self,
        *,
        rows: list[Any] | None = None,
        scalars: list[Any] | None = None,
        scalar: Any = None,
    ) -> None:
        self._rows = rows or []
        self._scalars = scalars or []
        self._scalar = scalar

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _ScalarValues:
        return _ScalarValues(self._scalars)

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _CaptureDb:
    def __init__(self, results: list[_Result]) -> None:
        self._results = list(results)
        self.statements: list[Any] = []
        self.commit_count = 0
        self.rollback_count = 0

    async def execute(self, statement: Any) -> _Result:
        self.statements.append(statement)
        assert self._results, "준비된 DB 결과보다 execute 호출이 많습니다."
        return self._results.pop(0)

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class _PersistenceDb:
    def __init__(self, *, first_id: int = 101) -> None:
        self.next_id = first_id
        self.added: list[Any] = []
        self.commit_count = 0
        self.rollback_count = 0

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commit_count += 1
        self.added[-1].id = self.next_id
        self.next_id += 1

    async def refresh(self, value: Any) -> None:
        value.created_at = datetime(2026, 7, 14, 1, 2, 3, tzinfo=UTC)

    async def rollback(self) -> None:
        self.rollback_count += 1


def _compile_sql(statement: Any) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()


def _assert_primary_preferred_legacy_fallback_sql(sql: str) -> None:
    assert "'TRADE_ANALYSIS'" in sql
    assert "'LEGACY_UNKNOWN'" in sql
    assert "'BUY_PRECHECK'" not in sql
    assert "CASE WHEN" in sql
    assert "AI_ANALYSIS_LOGS.STAGE = 'TRADE_ANALYSIS'" in sql


def _primary_analysis(*, analysis_id: int = 41) -> SimpleNamespace:
    return SimpleNamespace(
        id=analysis_id,
        symbol="KRW-BTC",
        decision="BUY",
        confidence=90,
        recommended_weight=20,
        reasoning="primary analysis",
        created_at=datetime(2026, 7, 14, 1, 0, tzinfo=UTC),
        stage=AI_ANALYSIS_STAGE_TRADE,
    )


def _entry_gate() -> SimpleNamespace:
    return SimpleNamespace(to_log_dict=lambda: {"allowed": True, "score": 80})


def _portfolio() -> PortfolioSummary:
    return PortfolioSummary(total_net_worth=100_000, total_pnl=0, items=[])


async def _patch_primary_context(monkeypatch: pytest.MonkeyPatch) -> None:
    async def gather_context(_db: object, symbol: str) -> dict[str, str]:
        return {"symbol": symbol, "price": "100"}

    async def get_config(*_args: Any, **_kwargs: Any) -> str:
        return ""

    async def load_feedback(_db: object, _symbol: str) -> str:
        return ""

    monkeypatch.setattr(ai_analyst, "gather_market_context", gather_context)
    monkeypatch.setattr(
        ai_analyst,
        "format_market_context_for_llm",
        lambda context: f"immutable-context:{context['symbol']}:{context['price']}",
    )
    monkeypatch.setattr(ai_analyst, "get_system_config_value", get_config)
    monkeypatch.setattr(ai_analyst, "_load_recent_failure_feedback", load_feedback)


@pytest.mark.asyncio
async def test_primary_analysis_persists_provider_model_fallback_prompt_and_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _patch_primary_context(monkeypatch)
    db = _PersistenceDb()
    captured: dict[str, Any] = {}

    class FakeRouter:
        def __init__(self, received_db: object) -> None:
            assert received_db is db

        async def generate_structured_analysis(self, **kwargs: Any) -> AIProviderExecutionResult:
            captured.update(kwargs)
            return AIProviderExecutionResult(
                value=AIAnalysisResponse(
                    decision="BUY",
                    confidence=91,
                    recommended_weight=18,
                    reasoning="provider response",
                ),
                provider="openai",
                model="gpt-lineage-test",
                fallback_used=True,
            )

    monkeypatch.setattr(ai_analyst, "AIProviderRouter", FakeRouter)

    saved = await ai_analyst.execute_ai_analysis(db, "krw-btc")

    assert saved is db.added[0]
    assert saved.stage == AI_ANALYSIS_STAGE_TRADE
    assert saved.provider == "openai"
    assert saved.model == "gpt-lineage-test"
    assert saved.fallback_used is True
    assert saved.parent_analysis_id is None
    assert saved.prompt_version == TRADE_ANALYSIS_PROMPT_VERSION
    assert saved.context_sha256 == hash_analysis_context(captured["user_prompt"])
    assert len(saved.context_sha256) == 64


@pytest.mark.asyncio
async def test_primary_provider_failure_persists_deterministic_hold_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _patch_primary_context(monkeypatch)
    db = _PersistenceDb()
    captured: dict[str, Any] = {}

    class UnavailableRouter:
        def __init__(self, received_db: object) -> None:
            assert received_db is db

        async def generate_structured_analysis(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            raise AIProviderUnavailableError("all providers unavailable")

    monkeypatch.setattr(ai_analyst, "AIProviderRouter", UnavailableRouter)

    saved = await ai_analyst.execute_ai_analysis(db, "KRW-BTC")

    assert saved.decision == "HOLD"
    assert saved.recommended_weight == 0
    assert saved.stage == AI_ANALYSIS_STAGE_TRADE
    assert saved.provider == AI_ANALYSIS_SYSTEM_PROVIDER
    assert saved.model == AI_ANALYSIS_DETERMINISTIC_HOLD_MODEL
    assert saved.fallback_used is True
    assert saved.parent_analysis_id is None
    assert saved.prompt_version == TRADE_ANALYSIS_PROMPT_VERSION
    assert saved.context_sha256 == hash_analysis_context(captured["user_prompt"])


async def _disable_precheck_news_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def load_config(_db: object) -> tuple[bool, int]:
        return False, 60

    async def load_news(_symbol: str) -> dict[str, Any]:
        return {"items": [], "error": "NO_NEWS_DATA_AVAILABLE"}

    monkeypatch.setattr(
        ai_executor,
        "_load_buy_precheck_news_refresh_config",
        load_config,
    )
    monkeypatch.setattr(ai_executor, "_load_buy_precheck_news_context", load_news)


@pytest.mark.asyncio
async def test_buy_precheck_success_persists_parent_provider_and_context_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _disable_precheck_news_refresh(monkeypatch)
    db = _PersistenceDb(first_id=201)
    primary = _primary_analysis()
    captured: dict[str, Any] = {}

    class FakeRouter:
        def __init__(self, received_db: object) -> None:
            assert received_db is db

        async def generate_structured_analysis(self, **kwargs: Any) -> AIProviderExecutionResult:
            captured.update(kwargs)
            return AIProviderExecutionResult(
                value=AIAnalysisResponse(
                    decision="BUY",
                    confidence=88,
                    recommended_weight=12,
                    reasoning="approved raw response",
                ),
                provider="openai",
                model="gpt-precheck-test",
                fallback_used=False,
            )

    monkeypatch.setattr(ai_executor, "AIProviderRouter", FakeRouter)

    saved = await ai_executor._run_buy_precheck(
        db=db,
        symbol="KRW-BTC",
        analysis=primary,
        entry_gate=_entry_gate(),
        portfolio=_portfolio(),
        trading_mode="live",
        min_confidence=75,
    )

    assert saved is db.added[0]
    assert saved.stage == AI_ANALYSIS_STAGE_BUY_PRECHECK
    assert saved.parent_analysis_id == primary.id
    assert saved.provider == "openai"
    assert saved.model == "gpt-precheck-test"
    assert saved.fallback_used is False
    assert saved.prompt_version == BUY_PRECHECK_PROMPT_VERSION
    assert saved.context_sha256 == hash_analysis_context(captured["user_prompt"])
    assert saved.decision == "BUY"
    assert saved.confidence == 88
    assert saved.recommended_weight == 12


@pytest.mark.asyncio
async def test_buy_precheck_veto_keeps_raw_provider_response_and_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _disable_precheck_news_refresh(monkeypatch)
    db = _PersistenceDb(first_id=202)
    primary = _primary_analysis()
    captured: dict[str, Any] = {}

    class VetoRouter:
        def __init__(self, received_db: object) -> None:
            assert received_db is db

        async def generate_structured_analysis(self, **kwargs: Any) -> AIProviderExecutionResult:
            captured.update(kwargs)
            return AIProviderExecutionResult(
                value=AIAnalysisResponse(
                    decision="SELL",
                    confidence=93,
                    recommended_weight=7,
                    reasoning="raw veto response",
                ),
                provider="openai",
                model="gpt-precheck-veto",
                fallback_used=False,
            )

    monkeypatch.setattr(ai_executor, "AIProviderRouter", VetoRouter)

    result = await ai_executor._run_buy_precheck(
        db=db,
        symbol="KRW-BTC",
        analysis=primary,
        entry_gate=_entry_gate(),
        portfolio=_portfolio(),
        trading_mode="live",
        min_confidence=75,
    )

    assert result is None
    veto_log = db.added[0]
    assert veto_log.stage == AI_ANALYSIS_STAGE_BUY_PRECHECK
    assert veto_log.parent_analysis_id == primary.id
    assert veto_log.decision == "SELL"
    assert veto_log.confidence == 93
    assert veto_log.recommended_weight == 7
    assert "raw veto response" in veto_log.reasoning
    assert veto_log.provider == "openai"
    assert veto_log.model == "gpt-precheck-veto"
    assert veto_log.context_sha256 == hash_analysis_context(captured["user_prompt"])


@pytest.mark.asyncio
async def test_buy_precheck_failure_persists_parented_deterministic_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _disable_precheck_news_refresh(monkeypatch)
    db = _PersistenceDb(first_id=203)
    primary = _primary_analysis()
    captured: dict[str, Any] = {}

    class UnavailableRouter:
        def __init__(self, received_db: object) -> None:
            assert received_db is db

        async def generate_structured_analysis(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            raise AIProviderUnavailableError("precheck unavailable")

    monkeypatch.setattr(ai_executor, "AIProviderRouter", UnavailableRouter)

    result = await ai_executor._run_buy_precheck(
        db=db,
        symbol="KRW-BTC",
        analysis=primary,
        entry_gate=_entry_gate(),
        portfolio=_portfolio(),
        trading_mode="live",
        min_confidence=75,
    )

    assert result is None
    failure_log = db.added[0]
    assert failure_log.stage == AI_ANALYSIS_STAGE_BUY_PRECHECK
    assert failure_log.parent_analysis_id == primary.id
    assert failure_log.decision == "HOLD"
    assert failure_log.confidence == 0
    assert failure_log.recommended_weight == 0
    assert failure_log.provider == AI_ANALYSIS_SYSTEM_PROVIDER
    assert failure_log.model == AI_ANALYSIS_DETERMINISTIC_HOLD_MODEL
    assert failure_log.fallback_used is True
    assert failure_log.prompt_version == BUY_PRECHECK_PROMPT_VERSION
    assert failure_log.context_sha256 == hash_analysis_context(captured["user_prompt"])


@pytest.mark.asyncio
async def test_executor_analysis_lookup_accepts_only_primary_stage() -> None:
    db = _CaptureDb([_Result(scalar=None)])

    assert await ai_executor._load_analysis_by_id(db, 77) is None

    sql = _compile_sql(db.statements[0])
    assert "AI_ANALYSIS_LOGS.ID = 77" in sql
    assert "AI_ANALYSIS_LOGS.STAGE = 'TRADE_ANALYSIS'" in sql
    assert "'BUY_PRECHECK'" not in sql
    assert "'LEGACY_UNKNOWN'" not in sql


@pytest.mark.asyncio
async def test_latest_batch_portfolio_and_scheduler_prefer_primary_then_legacy() -> None:
    latest_db = _CaptureDb([_Result(scalar=None)])
    assert await ai_route._load_latest_analysis_log(latest_db, "KRW-BTC") is None
    _assert_primary_preferred_legacy_fallback_sql(_compile_sql(latest_db.statements[0]))

    batch_db = _CaptureDb([_Result(rows=[])])
    batch = await ai_route.get_latest_analysis_batch("KRW-BTC", db=batch_db)
    assert batch == {"KRW-BTC": None}
    _assert_primary_preferred_legacy_fallback_sql(_compile_sql(batch_db.statements[0]))

    portfolio_db = _CaptureDb([_Result(rows=[])])
    assert await portfolio_route._load_latest_analysis_map(portfolio_db, ["KRW-BTC"]) == {}
    _assert_primary_preferred_legacy_fallback_sql(
        _compile_sql(portfolio_db.statements[0])
    )

    scheduler_db = _CaptureDb(
        [
            _Result(scalars=["KRW-BTC"]),
            _Result(scalar=None),
        ]
    )
    scheduler_module = importlib.import_module("app.core.scheduler")
    assert await scheduler_module._load_favorite_ai_signals(
        scheduler_db,
        decisions=["BUY", "SELL"],
        min_confidence=75,
    ) == []
    _assert_primary_preferred_legacy_fallback_sql(
        _compile_sql(scheduler_db.statements[1])
    )


@pytest.mark.asyncio
async def test_accuracy_calibration_and_failure_feedback_are_primary_only() -> None:
    accuracy_db = _CaptureDb([_Result(scalars=[])])
    assert await accuracy_worker.update_ai_analysis_accuracy(accuracy_db) == 0
    accuracy_sql = _compile_sql(accuracy_db.statements[0])
    assert "AI_ANALYSIS_LOGS.STAGE = 'TRADE_ANALYSIS'" in accuracy_sql
    assert "'BUY_PRECHECK'" not in accuracy_sql

    calibration_db = _CaptureDb([_Result(scalars=["SUCCESS", "FAIL"])])
    calibration = await entry_policy.load_buy_confidence_calibration(
        calibration_db,
        "KRW-BTC",
        80,
    )
    assert calibration.checked_count == 2
    assert calibration.success_count == 1
    calibration_sql = _compile_sql(calibration_db.statements[0])
    assert "AI_ANALYSIS_LOGS.STAGE = 'TRADE_ANALYSIS'" in calibration_sql
    assert "'BUY_PRECHECK'" not in calibration_sql

    feedback_db = _CaptureDb([_Result(scalars=[])])
    assert await ai_analyst._load_recent_failure_feedback(feedback_db, "KRW-BTC") == ""
    feedback_sql = _compile_sql(feedback_db.statements[0])
    assert "AI_ANALYSIS_LOGS.STAGE = 'TRADE_ANALYSIS'" in feedback_sql
    assert "'BUY_PRECHECK'" not in feedback_sql


@pytest.mark.asyncio
async def test_performance_attributes_precheck_orders_to_parent_and_preserves_pnl() -> None:
    executed_at = datetime(2026, 7, 14, 2, 0, tzinfo=UTC)
    position = SimpleNamespace(id=9)
    asset = SimpleNamespace(symbol="KRW-BTC")
    linked_precheck = SimpleNamespace(
        id=52,
        stage=AI_ANALYSIS_STAGE_BUY_PRECHECK,
        parent_analysis_id=41,
        confidence=99,
        decision="BUY",
    )
    primary = SimpleNamespace(
        id=41,
        stage=AI_ANALYSIS_STAGE_TRADE,
        confidence=80,
        decision="BUY",
    )
    buy = SimpleNamespace(
        id=1,
        side="BUY",
        price=100.0,
        qty=2.0,
        executed_at=executed_at,
        ai_analysis_log_id=52,
    )
    sell = SimpleNamespace(
        id=2,
        side="SELL",
        price=150.0,
        qty=2.0,
        executed_at=executed_at,
        ai_analysis_log_id=52,
    )
    db = _CaptureDb(
        [
            _Result(
                rows=[
                    (buy, position, asset, linked_precheck, primary),
                    (sell, position, asset, linked_precheck, primary),
                ]
            ),
            _Result(rows=[(sell, position, asset, linked_precheck, primary)]),
            _Result(scalars=["SUCCESS", "FAIL"]),
        ]
    )

    summary = await ai_route.get_ai_performance_summary(db=db)

    assert summary.total_trades == 1
    assert summary.winning_trades == 1
    assert summary.losing_trades == 0
    assert summary.total_realized_pnl_krw == pytest.approx(100.0)
    assert summary.avg_confidence == pytest.approx(80.0)
    assert summary.accuracy_rate == pytest.approx(50.0)
    assert len(summary.recent_trades) == 1
    assert summary.recent_trades[0].confidence == primary.confidence
    assert summary.recent_trades[0].decision == primary.decision

    history_sql = _compile_sql(db.statements[0])
    recent_sql = _compile_sql(db.statements[1])
    for sql in (history_sql, recent_sql):
        assert "LINKED_ANALYSIS.STAGE = 'TRADE_ANALYSIS'" in sql
        assert "LINKED_ANALYSIS.STAGE = 'BUY_PRECHECK'" in sql
        assert "PRIMARY_ANALYSIS.ID = LINKED_ANALYSIS.PARENT_ANALYSIS_ID" in sql
        assert "PRIMARY_ANALYSIS.STAGE = 'TRADE_ANALYSIS'" in sql

    accuracy_sql = _compile_sql(db.statements[2])
    assert "AI_ANALYSIS_LOGS.STAGE = 'TRADE_ANALYSIS'" in accuracy_sql
    assert "'BUY_PRECHECK'" not in accuracy_sql


@pytest.mark.asyncio
async def test_manual_cycle_order_lookup_includes_precheck_children() -> None:
    sentinel = object()
    db = _CaptureDb([_Result(scalar=sentinel)])

    loaded = await ai_route._load_latest_order_for_analysis(db, 41)

    assert loaded is sentinel
    sql = _compile_sql(db.statements[0])
    assert "ORDER_LINKED_ANALYSIS.ID = 41" in sql
    assert "ORDER_LINKED_ANALYSIS.STAGE = 'BUY_PRECHECK'" in sql
    assert "ORDER_LINKED_ANALYSIS.PARENT_ANALYSIS_ID = 41" in sql


@pytest.mark.asyncio
async def test_chat_analysis_history_exposes_all_stage_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2026, 7, 14, 3, 0, tzinfo=UTC)
    logs = [
        SimpleNamespace(
            symbol="KRW-BTC",
            decision="BUY",
            confidence=80,
            recommended_weight=20,
            reasoning="primary",
            created_at=created_at,
            stage=AI_ANALYSIS_STAGE_TRADE,
            provider="gemini",
            model="gemini-test",
            fallback_used=False,
            parent_analysis_id=None,
            prompt_version=TRADE_ANALYSIS_PROMPT_VERSION,
            context_sha256="a" * 64,
        ),
        SimpleNamespace(
            symbol="KRW-BTC",
            decision="HOLD",
            confidence=0,
            recommended_weight=0,
            reasoning="precheck failure",
            created_at=created_at,
            stage=AI_ANALYSIS_STAGE_BUY_PRECHECK,
            provider=AI_ANALYSIS_SYSTEM_PROVIDER,
            model=AI_ANALYSIS_DETERMINISTIC_HOLD_MODEL,
            fallback_used=True,
            parent_analysis_id=41,
            prompt_version=BUY_PRECHECK_PROMPT_VERSION,
            context_sha256="b" * 64,
        ),
        SimpleNamespace(
            symbol="KRW-ETH",
            decision="SELL",
            confidence=70,
            recommended_weight=100,
            reasoning="legacy",
            created_at=created_at,
            stage=AI_ANALYSIS_STAGE_LEGACY,
            provider="LEGACY_UNKNOWN",
            model="LEGACY_UNKNOWN",
            fallback_used=None,
            parent_analysis_id=None,
            prompt_version="LEGACY_UNKNOWN",
            context_sha256=None,
        ),
    ]
    db = _CaptureDb([_Result(scalars=logs)])

    class SessionContext:
        async def __aenter__(self) -> _CaptureDb:
            return db

        async def __aexit__(self, *_args: Any) -> None:
            return None

    monkeypatch.setattr(chat_tools, "AsyncSessionLocal", SessionContext)
    tools = chat_tools.build_chat_tools("lineage-session")
    history_tool = next(tool for tool in tools if tool.name == "query_ai_analysis_logs")

    output = await history_tool.ainvoke({"symbol": None, "limit": 5})

    assert "stage=TRADE_ANALYSIS" in output
    assert "stage=BUY_PRECHECK" in output
    assert "stage=LEGACY_UNKNOWN" in output
    assert "provider=gemini" in output
    assert "model=DETERMINISTIC_HOLD" in output
    assert "fallback=True" in output
    assert "parent_analysis_id=41" in output
    assert f"context_sha256={'b' * 64}" in output
    sql = _compile_sql(db.statements[0])
    assert "WHERE" not in sql
