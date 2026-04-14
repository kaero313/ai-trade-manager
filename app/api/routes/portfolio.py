from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import get_portfolio_snapshots
from app.db.repository import save_portfolio_snapshot
from app.db.session import get_db
from app.models.schemas import PortfolioSnapshotItem
from app.models.schemas import PortfolioSnapshotListResponse
from app.services.portfolio.aggregator import PortfolioService

router = APIRouter()


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
