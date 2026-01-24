from fastapi import APIRouter

from app.api.routes.bot import router as bot_router
from app.api.routes.config import router as config_router
from app.api.routes.health import router as health_router
from app.api.routes.orders import router as orders_router
from app.api.routes.positions import router as positions_router
from app.api.routes.slack import router as slack_router
from app.api.routes.status import router as status_router
from app.api.routes.upbit import router as upbit_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(status_router)
api_router.include_router(config_router)
api_router.include_router(bot_router)
api_router.include_router(positions_router)
api_router.include_router(orders_router)
api_router.include_router(upbit_router)
api_router.include_router(slack_router)
