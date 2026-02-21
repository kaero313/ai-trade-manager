from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.portfolio import PortfolioSummary
from app.services.portfolio.aggregator import PortfolioService

router = APIRouter()


@router.get("/dashboard", response_model=PortfolioSummary)
async def get_dashboard_snapshot(db: AsyncSession = Depends(get_db)) -> PortfolioSummary:
    portfolio = await PortfolioService(db).get_aggregated_portfolio()
    return portfolio
