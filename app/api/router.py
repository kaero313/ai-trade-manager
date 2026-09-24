from fastapi import APIRouter, Depends

from app.api.dependencies import require_public_market_rate_limit
from app.api.dependencies import require_rate_limited_admin_token
from app.api.routes.auth import router as auth_router
from app.api.routes.ai import router as ai_router
from app.api.routes.backtest import router as backtest_router
from app.api.routes.chat import router as chat_router
from app.api.routes.config import router as config_router
from app.api.routes.configs import router as configs_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.favorites import router as favorites_router
from app.api.routes.health import router as health_router
from app.api.routes.markets import router as markets_router
from app.api.routes.news import router as news_router
from app.api.routes.orders import router as orders_router
from app.api.routes.portfolio import router as portfolio_router
from app.api.routes.positions import router as positions_router
from app.api.routes.slack import router as slack_router
from app.api.routes.status import router as status_router
from app.api.routes.upbit import router as upbit_router

api_router = APIRouter()
api_router.include_router(health_router)
admin_dependencies = [Depends(require_rate_limited_admin_token)]

api_router.include_router(auth_router)
api_router.include_router(dashboard_router, dependencies=admin_dependencies)
api_router.include_router(status_router, dependencies=admin_dependencies)
api_router.include_router(config_router, dependencies=admin_dependencies)
api_router.include_router(
    configs_router,
    prefix="/system",
    tags=["system"],
    dependencies=admin_dependencies,
)
api_router.include_router(
    chat_router,
    prefix="/chat",
    tags=["chat"],
    dependencies=admin_dependencies,
)
api_router.include_router(positions_router, dependencies=admin_dependencies)
api_router.include_router(
    favorites_router,
    prefix="/favorites",
    tags=["favorites"],
    dependencies=admin_dependencies,
)
api_router.include_router(
    markets_router,
    prefix="/markets",
    tags=["markets"],
    dependencies=[Depends(require_public_market_rate_limit)],
)
api_router.include_router(
    orders_router,
    prefix="/orders",
    tags=["orders"],
    dependencies=admin_dependencies,
)
api_router.include_router(
    portfolio_router,
    prefix="/portfolio",
    tags=["portfolio"],
    dependencies=admin_dependencies,
)
api_router.include_router(news_router, prefix="/news", tags=["news"])
api_router.include_router(upbit_router, dependencies=admin_dependencies)
api_router.include_router(slack_router, dependencies=admin_dependencies)
api_router.include_router(
    ai_router,
    prefix="/ai",
    tags=["ai"],
    dependencies=admin_dependencies,
)
api_router.include_router(
    backtest_router,
    prefix="/backtest",
    tags=["backtest"],
    dependencies=admin_dependencies,
)
