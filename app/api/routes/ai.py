from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.domain import AIAnalysisLog
from app.models.schemas import AIAnalysisLogItem
from app.services.ai.analyzer import AIAnalyzerFactory
from app.services.ai.formatter import format_portfolio_for_llm
from app.services.portfolio.aggregator import PortfolioService

router = APIRouter()


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


@router.get("/analyze")
async def analyze_portfolio(provider: str = "openai", db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    portfolio = await PortfolioService(db).get_aggregated_portfolio()
    portfolio_str = format_portfolio_for_llm(portfolio)
    resolved_provider = (provider or "openai").strip().lower()
    if resolved_provider not in {"openai", "gemini"}:
        resolved_provider = "openai"

    analyzer = AIAnalyzerFactory.get_analyzer(resolved_provider)
    report = await analyzer.generate_report(portfolio_str)
    return {"provider": resolved_provider, "report": report}


@router.get("/latest-analysis", response_model=AIAnalysisLogItem | None)
async def get_latest_analysis(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> AIAnalysisLogItem | None:
    normalized_symbol = _normalize_symbol(symbol)
    if not normalized_symbol:
        raise HTTPException(status_code=400, detail="symbol query parameter is required")

    result = await db.execute(
        select(AIAnalysisLog)
        .where(AIAnalysisLog.symbol == normalized_symbol)
        .order_by(desc(AIAnalysisLog.created_at), desc(AIAnalysisLog.id))
        .limit(1)
    )
    latest_analysis = result.scalar_one_or_none()
    if latest_analysis is None:
        return None

    return AIAnalysisLogItem.model_validate(latest_analysis)
