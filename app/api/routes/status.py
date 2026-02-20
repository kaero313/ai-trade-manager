from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.schemas import BotStatus
from app.services.bot_service import get_bot_status

router = APIRouter()


@router.get("/status", response_model=BotStatus)
async def get_status(db: AsyncSession = Depends(get_db)) -> BotStatus:
    return await get_bot_status(db)
