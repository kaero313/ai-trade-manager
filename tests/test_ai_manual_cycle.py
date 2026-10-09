import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import ai as ai_route
from app.models.schemas import AIManualCycleRequest, LiveOrderGateStatus
from app.services.ai.providers.base import AIProviderRateLimitError
from app.services.trading.ai_executor import RiskCheckResult, RiskCheckStatus
from app.services.trading.live_order_execution import LiveOrderResult


@pytest.fixture(autouse=True)
def _paper_trading_mode(monkeypatch):
    async def get_paper_mode(_db):
        return "paper"

    async def get_disabled_risk(_db):
        return RiskCheckResult(status=RiskCheckStatus.DISABLED)

    monkeypatch.setattr(ai_route, "get_trading_mode", get_paper_mode)
    monkeypatch.setattr(ai_route, "evaluate_new_buy_risk_health", get_disabled_risk)


def _analysis(symbol: str = "KRW-BTC") -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        symbol=symbol,
        stage="TRADE_ANALYSIS",
        provider="openai",
        model="gpt-test",
        fallback_used=False,
        parent_analysis_id=None,
        prompt_version="trade_analysis.v1",
        context_sha256="a" * 64,
        decision="BUY",
        confidence=80,
        recommended_weight=25,
        reasoning="수동 AI 분석 테스트",
        accuracy_label=None,
        actual_price_diff_pct=None,
        created_at=datetime(2026, 6, 5, 1, 2, 3, tzinfo=UTC),
    )


def test_manual_cycle_without_trade_confirmation_runs_analysis_only(monkeypatch) -> None:
    events: list[str] = []

    async def fake_execute_ai_analysis(_db, symbol: str):
        events.append(f"analysis:{symbol}")
        return _analysis(symbol)

    async def fake_execute_ai_trade(
        _db,
        symbol: str,
        *,
        analysis_id: int | None = None,
        risk_check: RiskCheckResult | None = None,
    ):
        events.append(f"trade:{symbol}:{analysis_id}")

    async def unexpected_order_lookup(_db, _analysis_id: int):
        raise AssertionError("분석 전용 요청은 주문 이력을 조회하면 안 됩니다.")

    monkeypatch.setattr(ai_route, "execute_ai_analysis", fake_execute_ai_analysis)
    monkeypatch.setattr(ai_route, "execute_ai_trade", fake_execute_ai_trade)
    monkeypatch.setattr(
        ai_route,
        "_load_latest_order_for_analysis",
        unexpected_order_lookup,
    )
    request = AIManualCycleRequest(symbol="KRW-BTC", confirm_trade_execution=False)

    response = asyncio.run(ai_route.run_manual_ai_cycle(request, db=object()))

    assert events == ["analysis:KRW-BTC"]
    assert response.trade_evaluated is False
    assert response.order_created is False
    assert response.order_id is None
    assert response.order_intent_id is None
    assert response.message == "AI 분석 완료, 실주문 평가는 요청하지 않음"


def test_manual_cycle_runs_analysis_before_trade(monkeypatch) -> None:
    events: list[str] = []

    async def fake_execute_ai_analysis(_db, symbol: str):
        events.append(f"analysis:{symbol}")
        return _analysis(symbol)

    async def fake_execute_ai_trade(
        _db,
        symbol: str,
        *,
        analysis_id: int | None = None,
        risk_check: RiskCheckResult | None = None,
    ):
        assert risk_check is not None
        assert risk_check.status is RiskCheckStatus.DISABLED
        events.append(f"trade:{symbol}:{analysis_id}")

    async def fake_load_latest_order_for_analysis(_db, analysis_id: int):
        assert analysis_id == 42
        return SimpleNamespace(id=7, side="buy")

    monkeypatch.setattr(ai_route, "execute_ai_analysis", fake_execute_ai_analysis)
    monkeypatch.setattr(ai_route, "execute_ai_trade", fake_execute_ai_trade)
    monkeypatch.setattr(
        ai_route, "_load_latest_order_for_analysis", fake_load_latest_order_for_analysis
    )

    request = AIManualCycleRequest(symbol="krw-btc", confirm_trade_execution=True)
    response = asyncio.run(ai_route.run_manual_ai_cycle(request, db=object()))

    assert events == ["analysis:KRW-BTC", "trade:KRW-BTC:42"]
    assert response.symbol == "KRW-BTC"
    assert response.order_created is True
    assert response.order_id == 7
    assert response.order_side == "BUY"
    assert response.message == "신규 체결 있음"


def test_manual_cycle_returns_no_order_when_trade_gate_skips(monkeypatch) -> None:
    async def fake_execute_ai_analysis(_db, symbol: str):
        return _analysis(symbol)

    async def fake_execute_ai_trade(
        _db,
        _symbol: str,
        *,
        analysis_id: int | None = None,
        risk_check: RiskCheckResult | None = None,
    ):
        assert analysis_id == 42
        assert risk_check is not None
        return None

    async def fake_load_latest_order_for_analysis(_db, _analysis_id: int):
        return None

    async def get_live_mode(_db):
        return "live"

    async def get_armed_gate(_db):
        return LiveOrderGateStatus(
            mode="ARMED",
            generation=2,
            version=3,
            state_available=True,
        )

    monkeypatch.setattr(ai_route, "execute_ai_analysis", fake_execute_ai_analysis)
    monkeypatch.setattr(ai_route, "execute_ai_trade", fake_execute_ai_trade)
    monkeypatch.setattr(ai_route, "get_trading_mode", get_live_mode)
    monkeypatch.setattr(ai_route, "get_live_order_gate_status", get_armed_gate)
    monkeypatch.setattr(
        ai_route, "_load_latest_order_for_analysis", fake_load_latest_order_for_analysis
    )

    request = AIManualCycleRequest(symbol="KRW-ETH", confirm_trade_execution=True)
    response = asyncio.run(ai_route.run_manual_ai_cycle(request, db=object()))

    assert response.symbol == "KRW-ETH"
    assert response.trade_evaluated is True
    assert response.order_created is False
    assert response.order_id is None
    assert response.order_side is None
    assert response.message == "분석 완료, 신규 체결 없음"


def test_manual_cycle_returns_live_order_acceptance_state(monkeypatch) -> None:
    async def fake_execute_ai_analysis(_db, symbol: str):
        return _analysis(symbol)

    async def fake_execute_ai_trade(
        _db,
        _symbol: str,
        *,
        analysis_id: int | None = None,
        risk_check: RiskCheckResult | None = None,
    ):
        assert analysis_id == 42
        assert risk_check is not None
        return LiveOrderResult(
            intent_id=91,
            identifier="a" * 32,
            submission_status="ACCEPTED",
            exchange_uuid="exchange-uuid",
            exchange_state="wait",
            projection_status="PENDING",
            order_history_id=None,
            error_code=None,
            error_message=None,
        )

    async def fake_load_latest_order_for_analysis(_db, _analysis_id: int):
        return None

    async def get_live_mode(_db):
        return "live"

    async def get_armed_gate(_db):
        return LiveOrderGateStatus(
            mode="ARMED",
            generation=2,
            version=3,
            state_available=True,
        )

    monkeypatch.setattr(ai_route, "execute_ai_analysis", fake_execute_ai_analysis)
    monkeypatch.setattr(ai_route, "execute_ai_trade", fake_execute_ai_trade)
    monkeypatch.setattr(ai_route, "get_trading_mode", get_live_mode)
    monkeypatch.setattr(ai_route, "get_live_order_gate_status", get_armed_gate)
    monkeypatch.setattr(
        ai_route,
        "_load_latest_order_for_analysis",
        fake_load_latest_order_for_analysis,
    )

    request = AIManualCycleRequest(symbol="KRW-BTC", confirm_trade_execution=True)
    response = asyncio.run(ai_route.run_manual_ai_cycle(request, db=object()))

    assert response.order_created is False
    assert response.order_id is None
    assert response.order_intent_id == 91
    assert response.order_side == "BUY"
    assert response.submission_status == "ACCEPTED"
    assert response.exchange_state == "wait"
    assert "체결 상태를 확인 중" in response.message


def test_manual_buy_cycle_passes_unknown_risk_and_reports_block(monkeypatch) -> None:
    unknown_risk = RiskCheckResult(
        status=RiskCheckStatus.UNKNOWN,
        reasons=("PORTFOLIO_LOOKUP_FAILED",),
    )

    async def fake_execute_ai_analysis(_db, symbol: str):
        return _analysis(symbol)

    async def evaluate_risk(_db):
        return unknown_risk

    async def fake_execute_ai_trade(
        _db,
        _symbol: str,
        *,
        analysis_id: int | None = None,
        risk_check: RiskCheckResult | None = None,
    ):
        assert analysis_id == 42
        assert risk_check is unknown_risk
        return None

    async def no_order(_db, _analysis_id: int):
        return None

    monkeypatch.setattr(ai_route, "execute_ai_analysis", fake_execute_ai_analysis)
    monkeypatch.setattr(ai_route, "evaluate_new_buy_risk_health", evaluate_risk)
    monkeypatch.setattr(ai_route, "execute_ai_trade", fake_execute_ai_trade)
    monkeypatch.setattr(ai_route, "_load_latest_order_for_analysis", no_order)

    response = asyncio.run(
        ai_route.run_manual_ai_cycle(
            AIManualCycleRequest(symbol="KRW-BTC", confirm_trade_execution=True),
            db=object(),
        )
    )

    assert response.order_created is False
    assert "UNKNOWN" in response.message
    assert "신규 BUY를 차단" in response.message


def test_manual_sell_cycle_does_not_require_buy_risk_assessment(monkeypatch) -> None:
    analysis = _analysis()
    analysis.decision = "SELL"
    calls = {"risk": 0, "trade": 0}

    async def fake_execute_ai_analysis(_db, _symbol: str):
        return analysis

    async def unexpected_risk(_db):
        calls["risk"] += 1
        raise AssertionError("SELL은 신규 BUY 리스크 평가를 요구하면 안 됩니다.")

    async def fake_execute_ai_trade(
        _db,
        _symbol: str,
        *,
        analysis_id: int | None = None,
        risk_check: RiskCheckResult | None = None,
    ):
        calls["trade"] += 1
        assert analysis_id == analysis.id
        assert risk_check is None
        return None

    async def no_order(_db, _analysis_id: int):
        return None

    monkeypatch.setattr(ai_route, "execute_ai_analysis", fake_execute_ai_analysis)
    monkeypatch.setattr(ai_route, "evaluate_new_buy_risk_health", unexpected_risk)
    monkeypatch.setattr(ai_route, "execute_ai_trade", fake_execute_ai_trade)
    monkeypatch.setattr(ai_route, "_load_latest_order_for_analysis", no_order)

    response = asyncio.run(
        ai_route.run_manual_ai_cycle(
            AIManualCycleRequest(symbol="KRW-BTC", confirm_trade_execution=True),
            db=object(),
        )
    )

    assert calls == {"risk": 0, "trade": 1}
    assert response.trade_evaluated is True


def test_manual_live_cycle_blocks_trade_when_gate_is_not_armed(monkeypatch) -> None:
    trade_calls = 0

    async def fake_execute_ai_analysis(_db, symbol: str):
        return _analysis(symbol)

    async def fake_execute_ai_trade(
        _db,
        _symbol: str,
        *,
        analysis_id: int | None = None,
        risk_check: RiskCheckResult | None = None,
    ):
        nonlocal trade_calls
        trade_calls += 1

    async def get_live_mode(_db):
        return "live"

    async def get_blocked_gate(_db):
        return LiveOrderGateStatus(
            mode="BLOCK_ALL",
            generation=2,
            version=3,
            state_available=True,
        )

    monkeypatch.setattr(ai_route, "execute_ai_analysis", fake_execute_ai_analysis)
    monkeypatch.setattr(ai_route, "execute_ai_trade", fake_execute_ai_trade)
    monkeypatch.setattr(ai_route, "get_trading_mode", get_live_mode)
    monkeypatch.setattr(ai_route, "get_live_order_gate_status", get_blocked_gate)

    response = asyncio.run(
        ai_route.run_manual_ai_cycle(
            AIManualCycleRequest(
                symbol="KRW-BTC",
                confirm_trade_execution=True,
            ),
            db=object(),
        )
    )

    assert response.trade_evaluated is False
    assert response.order_created is False
    assert trade_calls == 0
    assert "ARMED" in response.message


def test_manual_cycle_rate_limit_does_not_run_trade(monkeypatch) -> None:
    trade_called = False

    async def fake_execute_ai_analysis(_db, _symbol: str):
        raise AIProviderRateLimitError("provider cooldown", provider="gemini")

    async def fake_execute_ai_trade(
        _db,
        _symbol: str,
        *,
        analysis_id: int | None = None,
        risk_check: RiskCheckResult | None = None,
    ):
        nonlocal trade_called
        trade_called = True

    monkeypatch.setattr(ai_route, "execute_ai_analysis", fake_execute_ai_analysis)
    monkeypatch.setattr(ai_route, "execute_ai_trade", fake_execute_ai_trade)

    request = AIManualCycleRequest(symbol="KRW-XRP", confirm_trade_execution=True)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(ai_route.run_manual_ai_cycle(request, db=object()))

    assert exc_info.value.status_code == 429
    assert trade_called is False


@pytest.mark.parametrize("legacy_kind", ["BUY", "SELL", "BUY_PRECHECK"])
def test_manual_cycle_does_not_trade_when_analysis_persistence_fails(
    monkeypatch,
    legacy_kind: str,
) -> None:
    trade_called = False
    latest_lookup_calls = 0

    async def fake_execute_ai_analysis(_db, _symbol: str):
        raise RuntimeError("analysis commit failed")

    async def fake_execute_ai_trade(
        _db,
        _symbol: str,
        *,
        analysis_id: int | None = None,
        risk_check: RiskCheckResult | None = None,
    ):
        nonlocal trade_called
        trade_called = True

    async def unexpected_latest_analysis_lookup(_db, _symbol: str):
        nonlocal latest_lookup_calls
        latest_lookup_calls += 1
        return SimpleNamespace(id=1, decision=legacy_kind)

    monkeypatch.setattr(ai_route, "execute_ai_analysis", fake_execute_ai_analysis)
    monkeypatch.setattr(ai_route, "execute_ai_trade", fake_execute_ai_trade)
    monkeypatch.setattr(
        ai_route,
        "_load_latest_analysis_log",
        unexpected_latest_analysis_lookup,
    )

    request = AIManualCycleRequest(symbol="KRW-BTC", confirm_trade_execution=True)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(ai_route.run_manual_ai_cycle(request, db=object()))

    assert exc_info.value.status_code == 500
    assert trade_called is False
    assert latest_lookup_calls == 0
