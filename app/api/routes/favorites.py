from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.domain import Favorite
from app.schemas.favorite import FavoriteCreateRequest, FavoriteResponse

router = APIRouter()


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _normalize_broker(broker: str) -> str:
    return str(broker or "").strip().upper()


@router.get("/", response_model=list[FavoriteResponse])
async def list_favorites(db: AsyncSession = Depends(get_db)) -> list[FavoriteResponse]:
    stmt = select(Favorite).order_by(desc(Favorite.created_at), desc(Favorite.id))
    result = await db.execute(stmt)
    favorites = result.scalars().all()
    return [FavoriteResponse.model_validate(item) for item in favorites]


@router.post("/", response_model=FavoriteResponse)
async def create_favorite(
    payload: FavoriteCreateRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> FavoriteResponse:
    symbol = _normalize_symbol(payload.symbol)
    broker = _normalize_broker(payload.broker)
    if not symbol or not broker:
        raise HTTPException(status_code=400, detail="symbol and broker must not be empty")

    stmt = select(Favorite).where(Favorite.symbol == symbol)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing is not None:
        return FavoriteResponse.model_validate(existing)

    favorite = Favorite(symbol=symbol, broker=broker)
    db.add(favorite)
    await db.commit()
    await db.refresh(favorite)
    response.status_code = status.HTTP_201_CREATED
    return FavoriteResponse.model_validate(favorite)


@router.delete("/{symbol}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_favorite(symbol: str, db: AsyncSession = Depends(get_db)) -> Response:
    normalized_symbol = _normalize_symbol(symbol)
    if not normalized_symbol:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    stmt = select(Favorite).where(Favorite.symbol == normalized_symbol)
    result = await db.execute(stmt)
    favorite = result.scalar_one_or_none()
    if favorite is not None:
        await db.delete(favorite)
        await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
