import asyncio
import logging
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import get_portfolio_snapshots
from app.db.repository import read_cached_market_sentiment
from app.db.repository import save_portfolio_snapshot
from app.db.session import get_db
from app.models.domain import AIAnalysisLog
from app.models.schemas import PortfolioSnapshotItem
from app.models.schemas import PortfolioSnapshotListResponse
from app.services.ai.provider_router import AIProviderRouter
from app.services.ai.provider_router import AIProviderUnavailableError
from app.services.portfolio.aggregator import PortfolioService

router = APIRouter()
logger = logging.getLogger(__name__)
PORTFOLIO_BRIEFING_TIMEOUT_SECONDS = 35


class PortfolioBriefingResponse(BaseModel):
    provider: str = Field(...)
    model: str = Field(...)
    report: str = Field(...)
    fallback: bool = Field(default=False)
    error: str | None = Field(default=None)


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _format_krw(value: float) -> str:
    return f"₩{round(_to_float(value)):,.0f}"


def _format_signed_krw(value: float) -> str:
    amount = _to_float(value)
    if amount > 0:
        return f"+{_format_krw(amount)}"
    if amount < 0:
        return f"-{_format_krw(abs(amount))}"
    return _format_krw(0)


def _format_pct(value: float) -> str:
    percentage = _to_float(value)
    sign = "+" if percentage > 0 else ""
    return f"{sign}{percentage:.2f}%"


def _normalize_holding_symbol(currency: str) -> str | None:
    normalized_currency = str(currency or "").strip().upper()
    if not normalized_currency or normalized_currency == "KRW":
        return None
    return f"KRW-{normalized_currency}"


def _extract_portfolio_symbols(portfolio_items: list[Any]) -> list[str]:
    symbols: list[str] = []
    for item in portfolio_items:
        symbol = _normalize_holding_symbol(getattr(item, "currency", ""))
        if symbol is not None and symbol not in symbols:
            symbols.append(symbol)
    return symbols


async def _load_latest_analysis_map(
    db: AsyncSession,
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}

    ranked_analyses = (
        select(
            AIAnalysisLog.symbol.label("symbol"),
            AIAnalysisLog.decision.label("decision"),
            AIAnalysisLog.confidence.label("confidence"),
            AIAnalysisLog.reasoning.label("reasoning"),
            AIAnalysisLog.created_at.label("created_at"),
            func.row_number()
            .over(
                partition_by=AIAnalysisLog.symbol,
                order_by=(desc(AIAnalysisLog.created_at), desc(AIAnalysisLog.id)),
            )
            .label("row_number"),
        )
        .where(AIAnalysisLog.symbol.in_(symbols))
        .subquery()
    )

    result = await db.execute(
        select(
            ranked_analyses.c.symbol,
            ranked_analyses.c.decision,
            ranked_analyses.c.confidence,
            ranked_analyses.c.reasoning,
            ranked_analyses.c.created_at,
        ).where(ranked_analyses.c.row_number == 1)
    )

    analyses: dict[str, dict[str, Any]] = {}
    for row in result.all():
        symbol = str(row.symbol or "").strip().upper()
        if not symbol:
            continue
        analyses[symbol] = {
            "decision": row.decision,
            "confidence": row.confidence,
            "reasoning": row.reasoning,
            "created_at": row.created_at,
        }
    return analyses


def _build_snapshot_context(snapshots: list[Any]) -> str:
    if not snapshots:
        return "기간 손익 데이터: 아직 스냅샷이 부족합니다."

    sorted_snapshots = sorted(
        snapshots,
        key=lambda snapshot: getattr(snapshot, "created_at", datetime.min),
    )
    first_snapshot = sorted_snapshots[0]
    latest_snapshot = sorted_snapshots[-1]
    net_worth_delta = _to_float(latest_snapshot.total_net_worth) - _to_float(
        first_snapshot.total_net_worth
    )
    pnl_delta = _to_float(latest_snapshot.total_pnl) - _to_float(first_snapshot.total_pnl)

    return (
        "기간 손익 데이터: "
        f"스냅샷 {len(sorted_snapshots)}개 기준 총 자산 변화 {_format_signed_krw(net_worth_delta)}, "
        f"손익 변화 {_format_signed_krw(pnl_delta)}."
    )


def _build_holdings_context(
    portfolio_items: list[Any],
    latest_analysis_map: dict[str, dict[str, Any]],
) -> list[str]:
    coin_items = [
        item
        for item in portfolio_items
        if str(getattr(item, "currency", "") or "").strip().upper() != "KRW"
    ]
    sorted_items = sorted(
        coin_items,
        key=lambda item: _to_float(getattr(item, "total_value", 0)),
        reverse=True,
    )

    if not sorted_items:
        return ["보유 종목: KRW 외 보유 종목이 없습니다."]

    lines: list[str] = []
    for item in sorted_items[:8]:
        currency = str(getattr(item, "currency", "") or "").strip().upper()
        symbol = _normalize_holding_symbol(currency) or currency
        analysis = latest_analysis_map.get(symbol)
        ai_text = "최근 AI 판단 없음"
        if analysis is not None:
            reasoning = str(analysis.get("reasoning") or "").replace("\n", " ").strip()
            if len(reasoning) > 120:
                reasoning = f"{reasoning[:120]}..."
            ai_text = (
                f"AI {analysis.get('decision')} "
                f"{analysis.get('confidence')}%, 이유: {reasoning or '없음'}"
            )

        lines.append(
            f"- {symbol}: 평가금액 {_format_krw(getattr(item, 'total_value', 0))}, "
            f"수익률 {_format_pct(getattr(item, 'pnl_percentage', 0))}, "
            f"수량 {_to_float(getattr(item, 'balance', 0)):.8f}, {ai_text}"
        )
    return lines


def _build_portfolio_briefing_prompt(
    *,
    total_net_worth: float,
    total_pnl: float,
    cash_balance: float,
    holdings_context: list[str],
    snapshot_context: str,
    sentiment_context: str,
    portfolio_error: str | None,
) -> str:
    error_context = f"\n- 포트폴리오 수집 경고: {portfolio_error}" if portfolio_error else ""
    holdings_text = "\n".join(holdings_context)
    return f"""
당신은 투자 보조 AI입니다. 아래 데이터만 근거로 한국어 포트폴리오 브리핑을 작성하세요.

규칙:
- 3줄 이내로 작성합니다.
- 각 줄은 한 문장으로 작성합니다.
- 마크다운 제목, 불릿, 번호 목록은 쓰지 않습니다.
- 매수/매도 단정 대신 관찰, 리스크, 확인 포인트 중심으로 말합니다.
- 숫자는 제공된 값을 우선 사용합니다.

데이터:
- 총 자산: {_format_krw(total_net_worth)}
- 총 손익: {_format_signed_krw(total_pnl)}
- 현금 잔고: {_format_krw(cash_balance)}{error_context}
- {snapshot_context}
- {sentiment_context}
보유 종목:
{holdings_text}
""".strip()


def _build_local_portfolio_briefing(
    *,
    total_net_worth: float,
    total_pnl: float,
    cash_balance: float,
    holdings_context: list[str],
    snapshot_context: str,
) -> str:
    top_holding = holdings_context[0].removeprefix("- ") if holdings_context else "보유 종목 정보가 없습니다."
    return "\n".join(
        [
            f"현재 총 자산은 {_format_krw(total_net_worth)}, 총 손익은 {_format_signed_krw(total_pnl)}입니다.",
            f"현금 잔고는 {_format_krw(cash_balance)}이며, 핵심 보유 현황은 {top_holding}",
            snapshot_context,
        ]
    )


def _normalize_briefing_report(raw_report: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in raw_report.replace("\r\n", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        line = re.sub(r"^[^\w가-힣]*포트폴리오 분석 리포트\s*", "", line)
        line = re.sub(
            r"^portfolio briefing[:\s-]*(analysis\s*&\s*outlook)?\s*",
            "",
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"^\*\*([^*]+?):\*\*\s*", r"\1: ", line)
        line = re.sub(r"^\*\*([^*]+)\*\*:\s*", r"\1: ", line).strip()

        normalized_line = line.casefold()
        is_heading = len(line) <= 80 and any(
            keyword in normalized_line
            for keyword in (
                "portfolio briefing",
                "analysis & outlook",
                "포트폴리오 분석",
                "분석 리포트",
            )
        )
        if is_heading:
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines[:3]).strip()


@router.get("/snapshots", response_model=PortfolioSnapshotListResponse)
async def list_portfolio_snapshots(
    limit: int = 168,
    db: AsyncSession = Depends(get_db),
) -> PortfolioSnapshotListResponse:
    snapshots = await get_portfolio_snapshots(db, limit)
    return PortfolioSnapshotListResponse(
        snapshots=[PortfolioSnapshotItem.model_validate(snapshot) for snapshot in snapshots]
    )


@router.post("/snapshots/now", response_model=PortfolioSnapshotItem)
async def create_portfolio_snapshot_now(
    db: AsyncSession = Depends(get_db),
) -> PortfolioSnapshotItem:
    portfolio = await PortfolioService(db).get_aggregated_portfolio()
    if portfolio.error is not None:
        raise HTTPException(status_code=503, detail=portfolio.error)

    snapshot_data = [
        {
            "currency": item.currency,
            "balance": item.balance,
            "current_price": item.current_price,
            "total_value": item.total_value,
            "pnl_percentage": item.pnl_percentage,
        }
        for item in portfolio.items
    ]

    snapshot = await save_portfolio_snapshot(
        db,
        total_net_worth=portfolio.total_net_worth,
        total_pnl=portfolio.total_pnl,
        snapshot_data=snapshot_data,
    )
    return PortfolioSnapshotItem.model_validate(snapshot)


@router.get("/briefing", response_model=PortfolioBriefingResponse)
async def get_portfolio_briefing(
    db: AsyncSession = Depends(get_db),
) -> PortfolioBriefingResponse:
    portfolio = await PortfolioService(db).get_aggregated_portfolio()
    snapshots = await get_portfolio_snapshots(db, limit=168)
    symbols = _extract_portfolio_symbols(portfolio.items)
    latest_analysis_map = await _load_latest_analysis_map(db, symbols)
    market_sentiment = await read_cached_market_sentiment(db)

    cash_balance = sum(
        _to_float(item.total_value)
        for item in portfolio.items
        if str(item.currency or "").strip().upper() == "KRW"
    )
    holdings_context = _build_holdings_context(portfolio.items, latest_analysis_map)
    snapshot_context = _build_snapshot_context(snapshots)
    sentiment_context = (
        f"시장 심리: {market_sentiment.score}/100 {market_sentiment.classification}."
        if market_sentiment is not None
        else "시장 심리: 캐시된 시장 심리 데이터가 없습니다."
    )
    fallback_report = _build_local_portfolio_briefing(
        total_net_worth=portfolio.total_net_worth,
        total_pnl=portfolio.total_pnl,
        cash_balance=cash_balance,
        holdings_context=holdings_context,
        snapshot_context=snapshot_context,
    )
    prompt = _build_portfolio_briefing_prompt(
        total_net_worth=portfolio.total_net_worth,
        total_pnl=portfolio.total_pnl,
        cash_balance=cash_balance,
        holdings_context=holdings_context,
        snapshot_context=snapshot_context,
        sentiment_context=sentiment_context,
        portfolio_error=portfolio.error,
    )

    try:
        result = await asyncio.wait_for(
            AIProviderRouter(db).generate_report(prompt),
            timeout=PORTFOLIO_BRIEFING_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        logger.warning(
            "Portfolio AI briefing timed out after %s seconds.",
            PORTFOLIO_BRIEFING_TIMEOUT_SECONDS,
        )
        return PortfolioBriefingResponse(
            provider="local",
            model="fallback",
            report=fallback_report,
            fallback=True,
            error=str(exc) or "AI provider timed out.",
        )
    except AIProviderUnavailableError as exc:
        return PortfolioBriefingResponse(
            provider="local",
            model="fallback",
            report=fallback_report,
            fallback=True,
            error=str(exc),
        )
    except Exception as exc:
        logger.exception("Portfolio AI briefing generation failed.")
        return PortfolioBriefingResponse(
            provider="local",
            model="fallback",
            report=fallback_report,
            fallback=True,
            error=str(exc),
        )

    report = _normalize_briefing_report(str(result.value or ""))
    if not report:
        return PortfolioBriefingResponse(
            provider="local",
            model="fallback",
            report=fallback_report,
            fallback=True,
            error="AI provider returned an empty briefing.",
        )

    return PortfolioBriefingResponse(
        provider=result.provider,
        model=result.model,
        report=report,
        fallback=False,
        error=None,
    )
