import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from app.models.schemas import AIAnalysisResponse
from app.schemas.portfolio import PortfolioSummary
from app.services.ai import provider_router
from app.services.ai.provider_router import AIProviderCandidate
from app.services.ai.provider_router import AIProviderDeadline
from app.services.ai.provider_router import AIProviderRouter
from app.services.ai.provider_router import AIProviderUnavailableError
from app.services.ai.providers.base import AIProviderTimeoutError
from app.services.trading import ai_analyst
from app.services.trading import ai_executor


pytestmark = pytest.mark.asyncio


class _StructuredPayload(BaseModel):
    decision: str


def _build_router(candidates: list[AIProviderCandidate]) -> AIProviderRouter:
    router = AIProviderRouter(object())  # type: ignore[arg-type]
    router.get_candidates = AsyncMock(return_value=candidates)  # type: ignore[method-assign]
    router.mark_success = AsyncMock()  # type: ignore[method-assign]
    router.mark_error = AsyncMock()  # type: ignore[method-assign]
    router.mark_rate_limited = AsyncMock()  # type: ignore[method-assign]
    return router


async def test_first_attempt_success_is_not_marked_as_fallback() -> None:
    candidate = AIProviderCandidate(provider="gemini", model="gemini-test")
    router = _build_router([candidate])

    result = await router.execute(
        AsyncMock(return_value="primary-success"),
        purpose="trade_analysis",
    )

    assert result.value == "primary-success"
    assert result.provider == "gemini"
    assert result.model == "gemini-test"
    assert result.fallback_used is False


async def test_first_provider_timeout_falls_back_once_and_marks_regular_error() -> None:
    candidates = [
        AIProviderCandidate(provider="gemini", model="gemini-test"),
        AIProviderCandidate(provider="openai", model="openai-test"),
    ]
    router = _build_router(candidates)
    attempts: list[str] = []

    async def operation(candidate: AIProviderCandidate) -> str:
        attempts.append(candidate.provider)
        if candidate.provider == "gemini":
            await asyncio.Event().wait()
        return "fallback-success"

    result = await router.execute(
        operation,
        purpose="trade_analysis",
        deadline=AIProviderDeadline(attempt_seconds=0.02, total_seconds=0.08),
    )

    assert result.value == "fallback-success"
    assert result.provider == "openai"
    assert result.fallback_used is True
    assert attempts == ["gemini", "openai"]
    router.mark_error.assert_awaited_once()
    provider, error = router.mark_error.await_args.args
    assert provider == "gemini"
    assert isinstance(error, AIProviderTimeoutError)
    router.mark_rate_limited.assert_not_awaited()
    router.mark_success.assert_awaited_once_with("openai")


async def test_all_provider_timeouts_respect_total_deadline() -> None:
    candidates = [
        AIProviderCandidate(provider="gemini", model="gemini-test"),
        AIProviderCandidate(provider="openai", model="openai-test"),
    ]
    router = _build_router(candidates)
    attempts: list[str] = []
    loop = asyncio.get_running_loop()

    async def operation(candidate: AIProviderCandidate) -> str:
        attempts.append(candidate.provider)
        await asyncio.Event().wait()
        return "unreachable"

    started_at = loop.time()
    with pytest.raises(AIProviderUnavailableError):
        await asyncio.wait_for(
            router.execute(
                operation,
                deadline=AIProviderDeadline(
                    attempt_seconds=0.025,
                    total_seconds=0.10,
                ),
            ),
            timeout=0.25,
        )
    elapsed = loop.time() - started_at

    assert attempts == ["gemini", "openai"]
    assert elapsed < 0.20
    assert router.mark_error.await_count == 2
    assert all(
        isinstance(call.args[1], AIProviderTimeoutError)
        for call in router.mark_error.await_args_list
    )
    router.mark_rate_limited.assert_not_awaited()
    router.mark_success.assert_not_awaited()


async def test_fallback_disabled_attempts_only_preferred_provider_once() -> None:
    preferred = AIProviderCandidate(provider="openai", model="openai-test")
    router = _build_router([])
    attempts = 0

    async def get_candidates(
        preferred_provider: str | None = None,
        *,
        purpose: str | None = None,
        allow_fallback: bool = True,
    ) -> list[AIProviderCandidate]:
        assert preferred_provider == "openai"
        assert purpose == "buy_precheck"
        assert allow_fallback is False
        return [preferred]

    router.get_candidates = get_candidates  # type: ignore[method-assign]

    async def operation(candidate: AIProviderCandidate) -> str:
        nonlocal attempts
        attempts += 1
        assert candidate == preferred
        await asyncio.Event().wait()
        return "unreachable"

    with pytest.raises(AIProviderUnavailableError):
        await router.execute(
            operation,
            preferred_provider="openai",
            purpose="buy_precheck",
            allow_fallback=False,
            deadline=AIProviderDeadline(attempt_seconds=0.02, total_seconds=0.08),
        )

    assert attempts == 1
    router.mark_error.assert_awaited_once()
    router.mark_rate_limited.assert_not_awaited()
    router.mark_success.assert_not_awaited()


async def test_external_task_cancellation_is_not_converted_to_fallback() -> None:
    candidates = [
        AIProviderCandidate(provider="gemini", model="gemini-test"),
        AIProviderCandidate(provider="openai", model="openai-test"),
    ]
    router = _build_router(candidates)
    entered = asyncio.Event()
    attempts: list[str] = []

    async def operation(candidate: AIProviderCandidate) -> str:
        attempts.append(candidate.provider)
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    task = asyncio.create_task(
        router.execute(
            operation,
            deadline=AIProviderDeadline(attempt_seconds=0.20, total_seconds=0.30),
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=0.10)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert attempts == ["gemini"]
    router.mark_success.assert_not_awaited()
    router.mark_error.assert_not_awaited()
    router.mark_rate_limited.assert_not_awaited()


async def test_primary_provider_deadline_failure_persists_current_cycle_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted: list[AIAnalysisResponse] = []

    class TimeoutRouter:
        def __init__(self, _db: object) -> None:
            pass

        async def generate_structured_analysis(self, **_kwargs):
            raise AIProviderUnavailableError("provider deadline exceeded")

    async def gather_context(_db: object, symbol: str) -> dict[str, str]:
        return {"symbol": symbol}

    async def get_config(*_args, **_kwargs) -> str:
        return ""

    async def load_feedback(_db: object, _symbol: str) -> str:
        return ""

    async def persist(
        _db: object,
        symbol: str,
        analysis: AIAnalysisResponse,
        **lineage: object,
    ) -> SimpleNamespace:
        assert symbol == "KRW-BTC"
        assert lineage["provider"] == "SYSTEM"
        assert lineage["model"] == "DETERMINISTIC_HOLD"
        assert lineage["fallback_used"] is True
        assert len(str(lineage["context_sha256"])) == 64
        persisted.append(analysis)
        return SimpleNamespace(id=37, symbol=symbol, **analysis.model_dump())

    monkeypatch.setattr(ai_analyst, "AIProviderRouter", TimeoutRouter)
    monkeypatch.setattr(ai_analyst, "gather_market_context", gather_context)
    monkeypatch.setattr(ai_analyst, "format_market_context_for_llm", lambda _context: "context")
    monkeypatch.setattr(ai_analyst, "get_system_config_value", get_config)
    monkeypatch.setattr(ai_analyst, "_load_recent_failure_feedback", load_feedback)
    monkeypatch.setattr(ai_analyst, "_persist_ai_analysis_log", persist)

    result = await ai_analyst.execute_ai_analysis(object(), "krw-btc")

    assert result.id == 37
    assert result.decision == "HOLD"
    assert result.recommended_weight == 0
    assert len(persisted) == 1
    assert persisted[0].decision == "HOLD"


async def test_buy_precheck_deadline_failure_never_reaches_order_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = SimpleNamespace(
        id=41,
        symbol="KRW-BTC",
        decision="BUY",
        confidence=90,
        recommended_weight=10,
        reasoning="primary buy",
        created_at=datetime.now(UTC),
    )
    portfolio = PortfolioSummary(total_net_worth=100_000, total_pnl=0, items=[])
    persisted_holds: list[str] = []

    class TimeoutRouter:
        def __init__(self, _db: object) -> None:
            pass

        async def generate_structured_analysis(self, **kwargs):
            assert kwargs["purpose"] == "buy_precheck"
            assert kwargs["allow_fallback"] is False
            raise AIProviderUnavailableError("buy precheck deadline exceeded")

    async def get_status(_db: object) -> SimpleNamespace:
        return SimpleNamespace(running=True)

    async def load_analysis(_db: object, analysis_id: int) -> SimpleNamespace:
        assert analysis_id == analysis.id
        return analysis

    async def load_thresholds(_db: object) -> tuple[int, int]:
        return 75, 90

    async def get_portfolio() -> PortfolioSummary:
        return portfolio

    async def get_mode(_db: object) -> str:
        return "live"

    async def allow_entry(*_args, **_kwargs) -> SimpleNamespace:
        return SimpleNamespace(
            allowed=True,
            shadow_mode=False,
            to_log_dict=lambda: {"allowed": True},
        )

    async def load_live_buy_enabled(_db: object) -> bool:
        return True

    async def load_news_refresh(_db: object) -> tuple[bool, int]:
        return False, 30

    async def load_news_context(_symbol: str) -> dict[str, object]:
        return {"items": [], "error": "NO_NEWS_DATA_AVAILABLE"}

    async def persist_hold(
        _db: object,
        *,
        symbol: str,
        reason: str,
        parent_analysis_id: int,
        context_sha256: str,
    ) -> SimpleNamespace:
        assert symbol == analysis.symbol
        assert parent_analysis_id == analysis.id
        assert len(context_sha256) == 64
        persisted_holds.append(reason)
        return SimpleNamespace(id=42, decision="HOLD")

    async def unexpected_order(**_kwargs):
        raise AssertionError("BUY precheck timeout 뒤 주문 경로를 호출하면 안 됩니다.")

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
    monkeypatch.setattr(ai_executor, "_load_live_buy_enabled", load_live_buy_enabled)
    monkeypatch.setattr(
        ai_executor,
        "_load_buy_precheck_news_refresh_config",
        load_news_refresh,
    )
    monkeypatch.setattr(
        ai_executor,
        "_load_buy_precheck_news_context",
        load_news_context,
    )
    monkeypatch.setattr(ai_executor, "AIProviderRouter", TimeoutRouter)
    monkeypatch.setattr(ai_executor, "_persist_buy_precheck_hold", persist_hold)
    monkeypatch.setattr(ai_executor, "_execute_buy_trade", unexpected_order)

    result = await ai_executor.execute_ai_trade(
        object(),
        analysis.symbol,
        analysis_id=analysis.id,
        risk_check=ai_executor.RiskCheckResult(
            status=ai_executor.RiskCheckStatus.HEALTHY,
        ),
    )

    assert result is None
    assert len(persisted_holds) == 1


@pytest.mark.parametrize("method_name", ["generate_report", "generate_structured_analysis"])
@pytest.mark.parametrize("should_timeout", [False, True])
async def test_generated_analyzer_is_always_closed(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    should_timeout: bool,
) -> None:
    candidate = AIProviderCandidate(provider="openai", model="openai-test")
    router = _build_router([candidate])

    class FakeAnalyzer:
        def __init__(self) -> None:
            self.aclose = AsyncMock()

        async def generate_report(self, _prompt: str) -> str:
            if should_timeout:
                await asyncio.Event().wait()
            return "report"

        async def generate_structured_analysis(
            self,
            *,
            system_prompt: str,
            user_prompt: str,
            response_model: type[_StructuredPayload],
        ) -> _StructuredPayload:
            del system_prompt, user_prompt
            if should_timeout:
                await asyncio.Event().wait()
            return response_model(decision="HOLD")

    analyzer = FakeAnalyzer()
    monkeypatch.setattr(
        provider_router.AIAnalyzerFactory,
        "get_analyzer",
        lambda *_args, **_kwargs: analyzer,
    )
    monkeypatch.setattr(
        provider_router,
        "resolve_provider_deadline",
        lambda _purpose: AIProviderDeadline(
            attempt_seconds=0.02,
            total_seconds=0.04,
        ),
    )

    if should_timeout:
        with pytest.raises(AIProviderUnavailableError):
            if method_name == "generate_report":
                await router.generate_report("prompt", purpose="portfolio_briefing")
            else:
                await router.generate_structured_analysis(
                    system_prompt="system",
                    user_prompt="user",
                    response_model=_StructuredPayload,
                    purpose="trade_analysis",
                )
    elif method_name == "generate_report":
        result = await router.generate_report("prompt", purpose="portfolio_briefing")
        assert result.value == "report"
        assert result.fallback_used is False
    else:
        result = await router.generate_structured_analysis(
            system_prompt="system",
            user_prompt="user",
            response_model=_StructuredPayload,
            purpose="trade_analysis",
        )
        assert result.value == _StructuredPayload(decision="HOLD")
        assert result.fallback_used is False

    analyzer.aclose.assert_awaited_once()
