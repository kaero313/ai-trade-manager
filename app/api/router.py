from fastapi import APIRouter

from app.api.routes.ai import router as ai_router
from app.api.routes.config import router as config_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.health import router as health_router
from app.api.routes.orders import router as orders_router
from app.api.routes.positions import router as positions_router
from app.api.routes.slack import router as slack_router
from app.api.routes.status import router as status_router
from app.api.routes.upbit import router as upbit_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(dashboard_router)
api_router.include_router(status_router)
api_router.include_router(config_router)
api_router.include_router(positions_router)
api_router.include_router(orders_router, prefix="/orders", tags=["orders"])
api_router.include_router(upbit_router)
api_router.include_router(slack_router)
api_router.include_router(ai_router, prefix="/ai", tags=["ai"])
