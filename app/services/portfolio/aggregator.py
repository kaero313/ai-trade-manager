from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.portfolio import PortfolioSummary


class PortfolioService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_aggregated_portfolio(self) -> PortfolioSummary:
        pass
