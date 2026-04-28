from app.api.routes.portfolio import _build_local_portfolio_briefing
from app.api.routes.portfolio import _build_portfolio_briefing_prompt
from app.api.routes.portfolio import _extract_portfolio_symbols
from app.api.routes.portfolio import _normalize_briefing_report
from app.schemas.portfolio import AssetItem


def test_extract_portfolio_symbols_excludes_krw() -> None:
    items = [
        AssetItem(
            broker="PAPER",
            currency="KRW",
            balance=10000,
            locked=0,
            avg_buy_price=1,
            current_price=1,
            total_value=10000,
            pnl_percentage=0,
        ),
        AssetItem(
            broker="PAPER",
            currency="btc",
            balance=0.01,
            locked=0,
            avg_buy_price=100000000,
            current_price=101000000,
            total_value=1010000,
            pnl_percentage=1,
        ),
    ]

    assert _extract_portfolio_symbols(items) == ["KRW-BTC"]


def test_portfolio_briefing_prompt_is_single_call_context() -> None:
    prompt = _build_portfolio_briefing_prompt(
        total_net_worth=58000,
        total_pnl=-900,
        cash_balance=800,
        holdings_context=["- KRW-BTC: 평가금액 ₩57,000, 수익률 -1.20%, 수량 0.00060000, AI HOLD 77%, 이유: 변동성 관찰"],
        snapshot_context="기간 손익 데이터: 스냅샷 12개 기준 총 자산 변화 -₩500, 손익 변화 -₩300.",
        sentiment_context="시장 심리: 50/100 Neutral.",
        portfolio_error=None,
    )

    assert "3줄 이내" in prompt
    assert "KRW-BTC" in prompt
    assert "AI HOLD 77%" in prompt
    assert "매수/매도 단정 대신" in prompt


def test_local_portfolio_briefing_uses_current_data() -> None:
    briefing = _build_local_portfolio_briefing(
        total_net_worth=58000,
        total_pnl=-900,
        cash_balance=800,
        holdings_context=["- KRW-BTC: 평가금액 ₩57,000, 수익률 -1.20%, 수량 0.00060000, 최근 AI 판단 없음"],
        snapshot_context="기간 손익 데이터: 스냅샷 12개 기준 총 자산 변화 -₩500, 손익 변화 -₩300.",
    )

    assert "현재 총 자산" in briefing
    assert "KRW-BTC" in briefing
    assert "기간 손익 데이터" in briefing


def test_normalize_briefing_report_removes_markdown_heading() -> None:
    report = _normalize_briefing_report(
        "### 포트폴리오 분석 리포트 * 현재 총 자산은 ₩58,000입니다.\n"
        "*   **현금 비중:** 현금 비중이 낮아 변동성 대응 여력이 제한됩니다.\n"
        "1. 손실 종목 회복 강도를 확인해야 합니다.\n"
        "추가 줄은 제거됩니다."
    )

    assert report == (
        "현재 총 자산은 ₩58,000입니다.\n"
        "현금 비중: 현금 비중이 낮아 변동성 대응 여력이 제한됩니다.\n"
        "손실 종목 회복 강도를 확인해야 합니다."
    )
