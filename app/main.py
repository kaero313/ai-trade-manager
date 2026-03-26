import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.logging import configure_logging
from app.core.scheduler import start_scheduler, stop_scheduler
from app.db.repository import get_or_create_bot_config
from app.db.repository import seed_system_configs_if_empty
from app.db.session import AsyncSessionLocal
from app.services.rag.opensearch_client import close_opensearch_client
from app.services.slack_bot import slack_bot
from app.services.telegram_bot import telegram_bot
from app.services.trading.engine import TradingEngine

logger = logging.getLogger(__name__)
trading_engine = TradingEngine(AsyncSessionLocal)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with AsyncSessionLocal() as db:
        await get_or_create_bot_config(db)
        await seed_system_configs_if_empty(db)

    await telegram_bot.start()
    slack_bot.start()
    if not slack_bot.enabled:
        logger.info("SlackBot 패스: SLACK_BOT_TOKEN/SLACK_APP_TOKEN/SLACK_ALLOWED_USER_ID 미설정")

    await start_scheduler()
    trading_task = asyncio.create_task(trading_engine.run_loop(), name="trading-engine-loop")

    try:
        yield
    finally:
        trading_engine._is_running = False
        stop_scheduler()
        try:
            await close_opensearch_client()
        except Exception:
            logger.exception("Failed to close AsyncOpenSearch client.")
        await telegram_bot.stop()
        slack_bot.stop()

        try:
            await asyncio.wait_for(trading_task, timeout=15)
        except asyncio.TimeoutError:
            trading_task.cancel()
            with suppress(asyncio.CancelledError):
                await trading_task


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Trading Bot", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
