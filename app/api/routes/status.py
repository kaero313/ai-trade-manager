from fastapi import APIRouter

from app.core.state import state
from app.models.schemas import BotStatus

router = APIRouter()


@router.get("/status", response_model=BotStatus)
def get_status() -> BotStatus:
    return state.status()
