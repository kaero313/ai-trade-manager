import json
from datetime import UTC, datetime
from types import SimpleNamespace

from app.models.schemas import AIAnalysisResponse
from app.schemas.portfolio import PortfolioSummary
from app.services.trading.ai_executor import _build_buy_precheck_system_prompt
from app.services.trading.ai_executor import _build_buy_precheck_user_prompt
from app.services.trading.ai_executor import _is_buy_precheck_approved


def test_buy_precheck_approves_strong_buy() -> None:
    analysis = AIAnalysisResponse(
        decision="BUY",
        confidence=88,
        recommended_weight=20,
        reasoning="BUY 직전 검증 통과",
    )

    assert _is_buy_precheck_approved(analysis, 85) is True


def test_buy_precheck_uses_balanced_confidence_threshold() -> None:
    analysis = AIAnalysisResponse(
        decision="BUY",
        confidence=75,
        recommended_weight=10,
        reasoning="balanced threshold buy",
    )

    assert _is_buy_precheck_approved(analysis, 75) is True


def test_buy_precheck_rejects_non_buy() -> None:
    analysis = AIAnalysisResponse(
        decision="HOLD",
        confidence=95,
        recommended_weight=20,
        reasoning="근거 부족",
    )

    assert _is_buy_precheck_approved(analysis, 85) is False


def test_buy_precheck_rejects_low_confidence_or_weight() -> None:
    low_confidence = AIAnalysisResponse(
        decision="BUY",
        confidence=70,
        recommended_weight=20,
        reasoning="확신도 부족",
    )
    zero_weight = AIAnalysisResponse(
        decision="BUY",
        confidence=90,
        recommended_weight=0,
        reasoning="비중 없음",
    )

    assert _is_buy_precheck_approved(low_confidence, 85) is False
    assert _is_buy_precheck_approved(zero_weight, 85) is False


def test_buy_precheck_prompt_declares_reduce_only_authority() -> None:
    system_prompt = _build_buy_precheck_system_prompt()
    user_prompt = _build_buy_precheck_user_prompt(
        symbol="KRW-BTC",
        analysis=SimpleNamespace(
            decision="BUY",
            confidence=90,
            recommended_weight=12,
            reasoning="primary",
            created_at=datetime.now(UTC),
        ),
        entry_gate=SimpleNamespace(to_log_dict=lambda: {"allowed": True}),
        portfolio=PortfolioSummary(
            total_net_worth=100_000,
            total_pnl=0,
            items=[],
        ),
        trading_mode="live",
        min_confidence=75,
    )
    payload = json.loads(user_prompt)

    assert "늘릴 수 없" in system_prompt
    assert payload["1차_AI_판단"]["recommended_weight"] == 12
    assert any("초과할 수 없습니다" in rule for rule in payload["판정_규칙"])
