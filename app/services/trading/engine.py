import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import AsyncSessionLocal
from app.models.domain import BotConfig

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self._is_running = True

    async def run_loop(self) -> None:
        logger.info("TradingEngine run_loop 시작")
        try:
            while self._is_running:
                try:
                    async with AsyncSessionLocal() as db:
                        result = await db.execute(select(BotConfig).where(BotConfig.id == 1))
                        bot_config = result.scalar_one_or_none()

                        is_active = bool(bot_config.is_active) if bot_config else False
                        config_json = bot_config.config_json if bot_config else {}
                        if not isinstance(config_json, dict):
                            config_json = {}
                        trade_mode = str(config_json.get("trade_mode", "grid"))

                    if not is_active:
                        logger.info("봇이 일시 정지 상태입니다.")
                        await asyncio.sleep(5)
                        continue

                    logger.info("트레이딩 루프 활성 상태 감지: mode=%s", trade_mode)
                except Exception:
                    logger.exception("TradingEngine 루프 처리 중 예외 발생")

                await asyncio.sleep(5)
        finally:
            logger.info("TradingEngine run_loop 종료")
