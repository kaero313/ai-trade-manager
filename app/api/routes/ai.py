from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.ai.analyzer import AIAnalyzerFactory
from app.services.ai.formatter import format_portfolio_for_llm
from app.services.portfolio.aggregator import PortfolioService

router = APIRouter()


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
