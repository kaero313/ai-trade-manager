from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.domain import Asset, OrderHistory, Position

router = APIRouter()
MAX_DISPLAY_PNL_ABS_PERCENTAGE = 50.0


class OrderHistoryResponse(BaseModel):
    id: int
    position_id: int
    symbol: str
    side: str
    price: float
    qty: float
    trade_amount_krw: float
    pnl_percentage: float | None = None
    broker: str
    executed_at: datetime


def _to_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_side(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"ask", "sell"}:
        return "sell"
    if normalized in {"bid", "buy"}:
        return "buy"
    return normalized


def _calculate_trade_amount_krw(order: OrderHistory) -> float:
    return max(_to_float(order.price), 0.0) * max(_to_float(order.qty), 0.0)


def _calculate_pnl_percentage(order: OrderHistory, position: Position) -> float | None:
    if _normalize_side(order.side) != "sell":
        return None

    avg_entry_price = max(_to_float(position.avg_entry_price), 0.0)
    executed_price = max(_to_float(order.price), 0.0)
    if avg_entry_price <= 0 or executed_price <= 0:
        return None
    pnl_percentage = ((executed_price - avg_entry_price) / avg_entry_price) * 100
    if abs(pnl_percentage) > MAX_DISPLAY_PNL_ABS_PERCENTAGE:
        return None
    return pnl_percentage


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
                trade_amount_krw=_calculate_trade_amount_krw(order),
                pnl_percentage=_calculate_pnl_percentage(order, position),
                broker=order.broker,
                executed_at=order.executed_at,
            )
        )
    return orders
