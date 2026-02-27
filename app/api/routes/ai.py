from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.ai.analyzer import generate_portfolio_report
from app.services.ai.formatter import format_portfolio_for_llm
from app.services.portfolio.aggregator import PortfolioService

router = APIRouter()


@router.get("/analyze")
async def analyze_portfolio(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    portfolio = await PortfolioService(db).get_aggregated_portfolio()
    portfolio_str = format_portfolio_for_llm(portfolio)
    report = await generate_portfolio_report(portfolio_str)
    return {"report": report}
