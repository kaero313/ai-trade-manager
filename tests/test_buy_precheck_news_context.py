from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.schemas import AIAnalysisResponse
from app.schemas.portfolio import PortfolioSummary
from app.services.ai.provider_router import AIProviderExecutionResult
from app.services.rag import ingestion
from app.services.trading import ai_analyst, ai_executor
from app.services.trading.analysis_lineage import AI_ANALYSIS_STAGE_BUY_PRECHECK
from app.services.trading.analysis_lineage import BUY_PRECHECK_PROMPT_VERSION
from app.services.trading.analysis_lineage import hash_analysis_context


class _PersistenceDb:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.added[-1].id = 701

    async def refresh(self, value: Any) -> None:
        value.created_at = datetime(2026, 7, 14, 2, 0, tzinfo=UTC)

    async def rollback(self) -> None:
        raise AssertionError("정상 BUY precheck 저장에서 rollback하면 안 됩니다.")


def _primary_analysis() -> SimpleNamespace:
    return SimpleNamespace(
        id=41,
        symbol="KRW-BTC",
        decision="BUY",
        confidence=90,
        recommended_weight=20,
        reasoning="primary analysis",
        created_at=datetime(2026, 7, 14, 1, 0, tzinfo=UTC),
    )


def _entry_gate() -> SimpleNamespace:
    return SimpleNamespace(to_log_dict=lambda: {"allowed": True, "score": 80})


def _portfolio() -> PortfolioSummary:
    return PortfolioSummary(total_net_worth=100_000, total_pnl=0, items=[])


def _approved_result() -> AIProviderExecutionResult:
    return AIProviderExecutionResult(
        value=AIAnalysisResponse(
            decision="BUY",
            confidence=88,
            recommended_weight=12,
            reasoning="fresh news approved",
        ),
        provider="openai",
        model="gpt-precheck-news-test",
        fallback_used=False,
    )


@pytest.mark.asyncio
async def test_buy_precheck_refreshes_then_queries_once_and_freezes_whitelisted_news(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _PersistenceDb()
    events: list[str] = []
    captured: dict[str, Any] = {}

    async def load_config(_db: object) -> tuple[bool, int]:
        return True, 30

    async def refresh_news(*, max_age_minutes: int) -> dict[str, Any]:
        assert max_age_minutes == 30
        events.append("refresh")
        return {"enabled": True, "refreshed": True, "reason": "stale_or_missing"}

    async def load_news(symbol: str) -> dict[str, Any]:
        assert symbol == "KRW-BTC"
        events.append("query")
        return {
            "items": [
                {
                    "title": "새 BTC 뉴스",
                    "summary": "가" * 250,
                    "source": "NEWS_A",
                    "published_at": "2026-07-14T01:59:00+00:00",
                    "link": "https://example.com/a",
                    "content": "prompt에 포함되면 안 되는 전문",
                    "parent_id": "secret-parent",
                    "search_score": 99,
                },
                {"title": "뉴스 B", "summary": "요약 B", "source": "NEWS_B"},
                {"title": "뉴스 C", "summary": "요약 C", "source": "NEWS_C"},
                {"title": "뉴스 D", "summary": "요약 D", "source": "NEWS_D"},
            ],
            "error": None,
            "internal": "prompt에 포함되면 안 되는 검색 메타데이터",
        }

    class FakeRouter:
        def __init__(self, received_db: object) -> None:
            assert received_db is db

        async def generate_structured_analysis(self, **kwargs: Any) -> AIProviderExecutionResult:
            events.append("provider")
            captured.update(kwargs)
            return _approved_result()

    monkeypatch.setattr(ai_executor, "_load_buy_precheck_news_refresh_config", load_config)
    monkeypatch.setattr(ingestion, "refresh_market_news_for_buy_precheck_if_stale", refresh_news)
    monkeypatch.setattr(ai_executor, "_load_buy_precheck_news_context", load_news)
    monkeypatch.setattr(ai_executor, "AIProviderRouter", FakeRouter)

    saved = await ai_executor._run_buy_precheck(
        db=db,
        symbol="KRW-BTC",
        analysis=_primary_analysis(),
        entry_gate=_entry_gate(),
        portfolio=_portfolio(),
        trading_mode="live",
        min_confidence=75,
    )

    assert events == ["refresh", "query", "provider"]
    prompt = captured["user_prompt"]
    payload = json.loads(prompt)
    news = payload["buy_precheck_news_context"]
    assert len(news["items"]) == 3
    assert set(news["items"][0]) == {"title", "summary", "source", "published_at", "link"}
    assert news["items"][0]["title"] == "새 BTC 뉴스"
    assert len(news["items"][0]["summary"]) <= 180
    assert news["items"][0]["summary"].endswith("...")
    assert "prompt에 포함되면 안 되는 전문" not in prompt
    assert "secret-parent" not in prompt
    assert "search_score" not in prompt
    assert prompt == json.dumps(
        payload,
        ensure_ascii=False,
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert saved is db.added[0]
    assert saved.stage == AI_ANALYSIS_STAGE_BUY_PRECHECK
    assert saved.parent_analysis_id == 41
    assert saved.prompt_version == BUY_PRECHECK_PROMPT_VERSION == "buy_precheck.v2"
    assert saved.context_sha256 == hash_analysis_context(prompt)


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh_mode", ["disabled", "failed"])
async def test_buy_precheck_queries_news_even_when_refresh_is_disabled_or_fails(
    monkeypatch: pytest.MonkeyPatch,
    refresh_mode: str,
) -> None:
    db = _PersistenceDb()
    query_count = 0
    captured: dict[str, Any] = {}

    async def load_config(_db: object) -> tuple[bool, int]:
        return refresh_mode == "failed", 30

    async def refresh_news(*, max_age_minutes: int) -> dict[str, Any]:
        assert max_age_minutes == 30
        raise RuntimeError("refresh unavailable")

    async def load_news(symbol: str) -> dict[str, Any]:
        nonlocal query_count
        assert symbol == "KRW-BTC"
        query_count += 1
        return {
            "items": [{"title": "캐시 뉴스", "summary": "기존 인덱스 뉴스"}],
            "error": None,
        }

    class FakeRouter:
        def __init__(self, _db: object) -> None:
            pass

        async def generate_structured_analysis(self, **kwargs: Any) -> AIProviderExecutionResult:
            captured.update(kwargs)
            return _approved_result()

    monkeypatch.setattr(ai_executor, "_load_buy_precheck_news_refresh_config", load_config)
    monkeypatch.setattr(ingestion, "refresh_market_news_for_buy_precheck_if_stale", refresh_news)
    monkeypatch.setattr(ai_executor, "_load_buy_precheck_news_context", load_news)
    monkeypatch.setattr(ai_executor, "AIProviderRouter", FakeRouter)

    saved = await ai_executor._run_buy_precheck(
        db=db,
        symbol="KRW-BTC",
        analysis=_primary_analysis(),
        entry_gate=_entry_gate(),
        portfolio=_portfolio(),
        trading_mode="live",
        min_confidence=75,
    )

    payload = json.loads(captured["user_prompt"])
    assert query_count == 1
    assert payload["buy_precheck_news_context"]["items"][0]["title"] == "캐시 뉴스"
    if refresh_mode == "disabled":
        assert payload["buy_precheck_news_refresh"]["reason"] == "disabled"
    else:
        assert payload["buy_precheck_news_refresh"]["reason"] == "refresh_context_failed"
    assert saved is not None


@pytest.mark.asyncio
async def test_buy_precheck_news_query_failure_does_not_auto_veto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _PersistenceDb()
    captured: dict[str, Any] = {}
    query_count = 0

    async def load_config(_db: object) -> tuple[bool, int]:
        return False, 30

    async def load_news(_symbol: str) -> dict[str, Any]:
        nonlocal query_count
        query_count += 1
        raise RuntimeError("search unavailable")

    class FakeRouter:
        def __init__(self, _db: object) -> None:
            pass

        async def generate_structured_analysis(self, **kwargs: Any) -> AIProviderExecutionResult:
            captured.update(kwargs)
            return _approved_result()

    monkeypatch.setattr(ai_executor, "_load_buy_precheck_news_refresh_config", load_config)
    monkeypatch.setattr(ai_executor, "_load_buy_precheck_news_context", load_news)
    monkeypatch.setattr(ai_executor, "AIProviderRouter", FakeRouter)

    saved = await ai_executor._run_buy_precheck(
        db=db,
        symbol="KRW-BTC",
        analysis=_primary_analysis(),
        entry_gate=_entry_gate(),
        portfolio=_portfolio(),
        trading_mode="live",
        min_confidence=75,
    )

    payload = json.loads(captured["user_prompt"])
    assert query_count == 1
    assert payload["buy_precheck_news_context"] == {
        "items": [],
        "error": "NEWS_SEARCH_FAILED",
    }
    assert saved is not None
    assert saved.decision == "BUY"


@pytest.mark.asyncio
async def test_buy_precheck_news_search_boundary_normalizes_symbol_and_queries_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any] | None]] = []

    async def search(symbol: str, market_row: dict[str, Any] | None) -> dict[str, Any]:
        calls.append((symbol, market_row))
        return {"items": [], "error": "NO_NEWS_DATA_AVAILABLE"}

    monkeypatch.setattr(ai_analyst, "_search_news_documents", search)

    result = await ai_analyst.search_news_for_buy_precheck("krw-btc")

    assert result["error"] == "NO_NEWS_DATA_AVAILABLE"
    assert calls == [("KRW-BTC", None)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "trading_mode", "expected_execution"),
    [
        ("BUY", "paper", "buy"),
        ("SELL", "paper", "sell"),
        ("SELL", "live", "sell"),
    ],
)
async def test_buy_precheck_news_path_is_live_buy_only(
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
    trading_mode: str,
    expected_execution: str,
) -> None:
    analysis = SimpleNamespace(
        id=81,
        symbol="KRW-BTC",
        decision=decision,
        confidence=90,
        recommended_weight=20,
        reasoning="route test",
        created_at=datetime.now(UTC),
    )
    executions: list[str] = []

    async def get_status(_db: object) -> SimpleNamespace:
        return SimpleNamespace(running=True)

    async def load_analysis(_db: object, analysis_id: int) -> SimpleNamespace:
        assert analysis_id == analysis.id
        return analysis

    async def load_thresholds(_db: object) -> tuple[int, int]:
        return 75, 90

    async def get_portfolio() -> PortfolioSummary:
        return _portfolio()

    async def get_mode(_db: object) -> str:
        return trading_mode

    async def allow_entry(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            allowed=True,
            shadow_mode=False,
            to_log_dict=lambda: {"allowed": True},
        )

    async def unexpected_precheck(**_kwargs: Any) -> None:
        raise AssertionError("live BUY가 아닌 경로에서 뉴스 precheck를 호출하면 안 됩니다.")

    async def execute_buy(**_kwargs: Any) -> None:
        executions.append("buy")

    async def execute_sell(**_kwargs: Any) -> None:
        executions.append("sell")

    monkeypatch.setattr(ai_executor, "get_bot_status", get_status)
    monkeypatch.setattr(ai_executor, "_load_analysis_by_id", load_analysis)
    monkeypatch.setattr(ai_executor, "_load_executor_thresholds", load_thresholds)
    monkeypatch.setattr(
        ai_executor,
        "PortfolioService",
        lambda _db: SimpleNamespace(get_aggregated_portfolio=get_portfolio),
    )
    monkeypatch.setattr(ai_executor, "get_trading_mode", get_mode)
    monkeypatch.setattr(ai_executor, "evaluate_ai_buy_entry_gate", allow_entry)
    monkeypatch.setattr(ai_executor, "_run_buy_precheck", unexpected_precheck)
    monkeypatch.setattr(ai_executor, "_execute_buy_trade", execute_buy)
    monkeypatch.setattr(ai_executor, "_execute_sell_trade", execute_sell)

    await ai_executor.execute_ai_trade(
        object(),
        analysis.symbol,
        analysis_id=analysis.id,
        risk_check=(
            ai_executor.RiskCheckResult(status=ai_executor.RiskCheckStatus.HEALTHY)
            if decision == "BUY"
            else None
        ),
    )

    assert executions == [expected_execution]
