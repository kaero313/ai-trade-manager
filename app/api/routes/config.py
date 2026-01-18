from fastapi import APIRouter

from app.core.state import state
from app.models.schemas import BotConfig

router = APIRouter()


@router.get("/config", response_model=BotConfig)
def get_config() -> BotConfig:
    return state.config


@router.post("/config", response_model=BotConfig)
def update_config(config: BotConfig) -> BotConfig:
    state.config = config
    return state.config
