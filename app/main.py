from fastapi import FastAPI

from app.api.router import api_router
from app.core.logging import configure_logging
from app.db.repository import get_or_create_bot_config
from app.db.session import AsyncSessionLocal
from app.services.slack_socket import slack_socket_service
from app.services.telegram_bot import telegram_bot


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Trading Bot")

    app.include_router(api_router, prefix="/api")

    @app.on_event("startup")
    async def _startup() -> None:
        async with AsyncSessionLocal() as db:
            await get_or_create_bot_config(db)
        await telegram_bot.start()
        await slack_socket_service.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await telegram_bot.stop()
        await slack_socket_service.stop()

    return app


app = create_app()
