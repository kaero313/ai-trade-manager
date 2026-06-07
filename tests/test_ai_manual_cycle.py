import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes import ai as ai_route
from app.models.schemas import AIManualCycleRequest
from app.services.ai.providers.base import AIProviderRateLimitError


def _analysis(symbol: str = "KRW-BTC") -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        symbol=symbol,
        decision="BUY",
        confidence=80,
        recommended_weight=25,
        reasoning="수동 AI 분석 테스트",
        accuracy_label=None,
        actual_price_diff_pct=None,
        created_at=datetime(2026, 6, 5, 1, 2, 3, tzinfo=UTC),
    )


def test_manual_cycle_requires_trade_confirmation() -> None:
    request = AIManualCycleRequest(symbol="KRW-BTC", confirm_trade_execution=False)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(ai_route.run_manual_ai_cycle(request, db=object()))

    assert exc_info.value.status_code == 400


def test_manual_cycle_runs_analysis_before_trade(monkeypatch) -> None:
    events: list[str] = []
    latest_analysis_calls = 0

    async def fake_execute_ai_analysis(_db, symbol: str):
        events.append(f"analysis:{symbol}")

    async def fake_execute_ai_trade(_db, symbol: str):
        events.append(f"trade:{symbol}")

    async def fake_load_latest_analysis_log(_db, symbol: str):
        nonlocal latest_analysis_calls
        latest_analysis_calls += 1
        if latest_analysis_calls == 1:
            return None
        return _analysis(symbol)

    async def fake_load_latest_order_for_analysis(_db, analysis_id: int):
        assert analysis_id == 42
        return SimpleNamespace(id=7, side="buy")

    monkeypatch.setattr(ai_route, "execute_ai_analysis", fake_execute_ai_analysis)
    monkeypatch.setattr(ai_route, "execute_ai_trade", fake_execute_ai_trade)
    monkeypatch.setattr(ai_route, "_load_latest_analysis_log", fake_load_latest_analysis_log)
    monkeypatch.setattr(ai_route, "_load_latest_order_for_analysis", fake_load_latest_order_for_analysis)

    request = AIManualCycleRequest(symbol="krw-btc", confirm_trade_execution=True)
    response = asyncio.run(ai_route.run_manual_ai_cycle(request, db=object()))

    assert events == ["analysis:KRW-BTC", "trade:KRW-BTC"]
    assert response.symbol == "KRW-BTC"
    assert response.order_created is True
    assert response.order_id == 7
    assert response.order_side == "BUY"
    assert response.message == "신규 체결 있음"


def test_manual_cycle_returns_no_order_when_trade_gate_skips(monkeypatch) -> None:
    latest_analysis_calls = 0

    async def fake_execute_ai_analysis(_db, _symbol: str):
        return None

    async def fake_execute_ai_trade(_db, _symbol: str):
        return None

    async def fake_load_latest_analysis_log(_db, symbol: str):
        nonlocal latest_analysis_calls
        latest_analysis_calls += 1
        if latest_analysis_calls == 1:
            return None
        return _analysis(symbol)

    async def fake_load_latest_order_for_analysis(_db, _analysis_id: int):
        return None

    monkeypatch.setattr(ai_route, "execute_ai_analysis", fake_execute_ai_analysis)
    monkeypatch.setattr(ai_route, "execute_ai_trade", fake_execute_ai_trade)
    monkeypatch.setattr(ai_route, "_load_latest_analysis_log", fake_load_latest_analysis_log)
    monkeypatch.setattr(ai_route, "_load_latest_order_for_analysis", fake_load_latest_order_for_analysis)

    request = AIManualCycleRequest(symbol="KRW-ETH", confirm_trade_execution=True)
    response = asyncio.run(ai_route.run_manual_ai_cycle(request, db=object()))

    assert response.symbol == "KRW-ETH"
    assert response.trade_evaluated is True
    assert response.order_created is False
    assert response.order_id is None
    assert response.order_side is None
    assert response.message == "분석 완료, 신규 체결 없음"


def test_manual_cycle_rate_limit_does_not_run_trade(monkeypatch) -> None:
    trade_called = False

    async def fake_load_latest_analysis_log(_db, _symbol: str):
        return None

    async def fake_execute_ai_analysis(_db, _symbol: str):
        raise AIProviderRateLimitError("provider cooldown", provider="gemini")

    async def fake_execute_ai_trade(_db, _symbol: str):
        nonlocal trade_called
        trade_called = True

    monkeypatch.setattr(ai_route, "execute_ai_analysis", fake_execute_ai_analysis)
    monkeypatch.setattr(ai_route, "execute_ai_trade", fake_execute_ai_trade)
    monkeypatch.setattr(ai_route, "_load_latest_analysis_log", fake_load_latest_analysis_log)

    request = AIManualCycleRequest(symbol="KRW-XRP", confirm_trade_execution=True)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(ai_route.run_manual_ai_cycle(request, db=object()))

    assert exc_info.value.status_code == 429
    assert trade_called is False


def test_manual_cycle_does_not_trade_without_new_analysis_log(monkeypatch) -> None:
    trade_called = False

    async def fake_execute_ai_analysis(_db, _symbol: str):
        return None

    async def fake_execute_ai_trade(_db, _symbol: str):
        nonlocal trade_called
        trade_called = True

    async def fake_load_latest_analysis_log(_db, symbol: str):
        return _analysis(symbol)

    monkeypatch.setattr(ai_route, "execute_ai_analysis", fake_execute_ai_analysis)
    monkeypatch.setattr(ai_route, "execute_ai_trade", fake_execute_ai_trade)
    monkeypatch.setattr(ai_route, "_load_latest_analysis_log", fake_load_latest_analysis_log)

    request = AIManualCycleRequest(symbol="KRW-BTC", confirm_trade_execution=True)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(ai_route.run_manual_ai_cycle(request, db=object()))

    assert exc_info.value.status_code == 500
    assert trade_called is False
