from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.domain import Asset, OrderHistory, Position

router = APIRouter()


class OrderHistoryResponse(BaseModel):
    id: int
    position_id: int
    symbol: str
    side: str
    price: float
    qty: float
    broker: str
    executed_at: datetime


@router.get("/", response_model=list[OrderHistoryResponse])
async def list_orders(db: AsyncSession = Depends(get_db)) -> list[OrderHistoryResponse]:
    stmt = (
        select(OrderHistory, Position, Asset)
        .join(Position, Position.id == OrderHistory.position_id)
        .join(Asset, Asset.id == Position.asset_id)
        .order_by(desc(OrderHistory.executed_at), desc(OrderHistory.id))
        .limit(50)
    )
    result = await db.execute(stmt)

    orders: list[OrderHistoryResponse] = []
    for order, position, asset in result.all():
        orders.append(
            OrderHistoryResponse(
                id=order.id,
                position_id=position.id,
                symbol=asset.symbol,
                side=order.side,
                price=order.price,
                qty=order.qty,
                broker=order.broker,
                executed_at=order.executed_at,
            )
        )
    return orders
