import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.domain import BotConfig
from app.services.bot_service import update_bot_runtime_status

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
                    async with self.session_factory() as db:
                        result = await db.execute(select(BotConfig).where(BotConfig.id == 1))
                        bot_config = result.scalar_one_or_none()
                        is_active = bool(bot_config.is_active) if bot_config else False

                        await self._set_runtime_status(
                            db,
                            latest_action=(
                                "AI 모드 대기 중..."
                                if is_active
                                else "봇이 일시 정지 상태입니다."
                            ),
                        )
                except Exception as exc:
                    logger.error(
                        "TradingEngine 루프 처리 중 예외가 발생했습니다. 다음 주기에서 계속 실행합니다.",
                        exc_info=True,
                    )
                    await self._record_runtime_error("트레이딩 엔진 상태 갱신 실패", exc)

                await asyncio.sleep(5)
        finally:
            logger.info("TradingEngine run_loop 종료")

    async def _set_runtime_status(
        self,
        db: AsyncSession,
        *,
        latest_action: str,
        last_error: str | None = None,
    ) -> None:
        await update_bot_runtime_status(
            db,
            last_heartbeat=datetime.now(timezone.utc).isoformat(),
            latest_action=latest_action,
            last_error=last_error,
        )

    async def _record_runtime_error(self, latest_action: str, error: Exception) -> None:
        try:
            async with self.session_factory() as db:
                await self._set_runtime_status(
                    db,
                    latest_action=latest_action,
                    last_error=self._format_runtime_error(error),
                )
        except Exception:
            logger.exception("트레이딩 엔진 오류 상태를 저장하지 못했습니다.")

    @staticmethod
    def _format_runtime_error(error: Exception) -> str:
        message = str(error).strip()
        if not message:
            return error.__class__.__name__
        return f"{error.__class__.__name__}: {message}"[:240]
