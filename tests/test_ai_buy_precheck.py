from app.models.schemas import AIAnalysisResponse
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
