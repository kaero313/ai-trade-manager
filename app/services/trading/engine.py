import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import AsyncSessionLocal
from app.models.domain import BotConfig
from app.services.brokers.factory import BrokerFactory
from app.services.brokers.upbit import UpbitAPIError

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
                        if trade_mode == "grid":
                            await self._check_and_execute_grid(db, bot_config)
                        else:
                            logger.info("지원되지 않는 거래 모드입니다: mode=%s", trade_mode)
                except Exception:
                    logger.exception("TradingEngine 루프 처리 중 예외 발생")

                await asyncio.sleep(5)
        finally:
            logger.info("TradingEngine run_loop 종료")

    async def _check_and_execute_grid(self, db: AsyncSession, config: BotConfig) -> None:
        _ = db

        config_json = config.config_json if isinstance(config.config_json, dict) else {}

        target_coin = getattr(config, "target_coin", None) or config_json.get("target_coin")
        upper_bound_raw = getattr(config, "grid_upper_bound", None)
        lower_bound_raw = getattr(config, "grid_lower_bound", None)

        if upper_bound_raw is None:
            upper_bound_raw = config_json.get("grid_upper_bound")
        if lower_bound_raw is None:
            lower_bound_raw = config_json.get("grid_lower_bound")

        if not target_coin or upper_bound_raw is None or lower_bound_raw is None:
            logger.warning("그리드 설정값이 부족합니다. target_coin/grid_upper_bound/grid_lower_bound를 확인하세요.")
            return

        try:
            grid_upper_bound = float(upper_bound_raw)
            grid_lower_bound = float(lower_bound_raw)
        except (TypeError, ValueError):
            logger.warning(
                "그리드 설정값 파싱에 실패했습니다. upper=%s lower=%s",
                upper_bound_raw,
                lower_bound_raw,
            )
            return

        market = f"KRW-{str(target_coin).upper()}"
        broker = BrokerFactory.get_broker("UPBIT")

        try:
            tickers = await broker.get_ticker([market])
        except UpbitAPIError as exc:
            logger.exception("현재가 조회 실패(UpbitAPIError): market=%s error=%s", market, exc)
            return
        except Exception:
            logger.exception("현재가 조회 중 예외가 발생했습니다: market=%s", market)
            return

        if not tickers or not isinstance(tickers[0], dict):
            logger.warning("현재가 조회 결과가 비어 있습니다: market=%s", market)
            return

        current_price_raw = tickers[0].get("trade_price")
        try:
            current_price = float(current_price_raw)
        except (TypeError, ValueError):
            logger.warning("현재가 파싱 실패: market=%s trade_price=%s", market, current_price_raw)
            return

        if current_price > grid_upper_bound:
            logger.info(
                "매도 조건 달성 로그: market=%s current_price=%s upper_bound=%s",
                market,
                current_price,
                grid_upper_bound,
            )
        elif current_price < grid_lower_bound:
            logger.info(
                "매수 조건 달성 로그: market=%s current_price=%s lower_bound=%s",
                market,
                current_price,
                grid_lower_bound,
            )
