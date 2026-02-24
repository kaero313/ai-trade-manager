import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def run_loop(self) -> None:
        logger.info("TradingEngine run_loop 시작")
        try:
            pass
        finally:
            logger.info("TradingEngine run_loop 종료")
