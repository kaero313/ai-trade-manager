import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import AsyncSessionLocal
from app.models.domain import Asset, BotConfig, OrderHistory, Position
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
                        if trade_mode == "grid" and bot_config is not None:
                            await self._check_and_execute_grid(db, bot_config)
                        else:
                            logger.info("지원되지 않는 거래 모드입니다: mode=%s", trade_mode)
                except Exception:
                    logger.exception("TradingEngine 루프 처리 중 예외 발생")

                await asyncio.sleep(5)
        finally:
            logger.info("TradingEngine run_loop 종료")

    async def _check_and_execute_grid(self, db: AsyncSession, config: BotConfig) -> None:
        config_json = config.config_json if isinstance(config.config_json, dict) else {}

        target_coin = getattr(config, "target_coin", None) or config_json.get("target_coin")
        upper_bound_raw = getattr(config, "grid_upper_bound", None)
        lower_bound_raw = getattr(config, "grid_lower_bound", None)

        if upper_bound_raw is None:
            upper_bound_raw = config_json.get("grid_upper_bound")
        if lower_bound_raw is None:
            lower_bound_raw = config_json.get("grid_lower_bound")

        if not target_coin or upper_bound_raw is None or lower_bound_raw is None:
            logger.warning(
                "그리드 설정값이 부족합니다. target_coin/grid_upper_bound/grid_lower_bound를 확인하세요."
            )
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

        now_utc = datetime.now(timezone.utc)
        cooldown_until = self._parse_datetime(config_json.get("grid_cooldown_until"))
        if cooldown_until is not None and cooldown_until > now_utc:
            logger.info("그리드 주문 쿨타임 적용 중입니다. next_order_at=%s", cooldown_until.isoformat())
            return

        signal_side: str | None = None
        if current_price > grid_upper_bound:
            signal_side = "sell"
        elif current_price < grid_lower_bound:
            signal_side = "buy"

        if signal_side is None:
            return

        order_result: dict[str, Any]
        order_krw = self._to_float(config_json.get("grid_order_krw", 10000))
        sell_volume = 0.0

        try:
            if signal_side == "buy":
                if order_krw <= 0:
                    logger.warning("매수 주문 금액이 유효하지 않습니다: grid_order_krw=%s", order_krw)
                    return

                order_result = await broker.create_order(
                    market=market,
                    side="bid",
                    ord_type="price",
                    price=self._fmt_number(order_krw),
                )
                logger.info("매수 조건 달성 로그: market=%s current_price=%s", market, current_price)
            else:
                accounts = await broker.get_accounts()
                available_qty = self._get_available_coin(accounts, str(target_coin).upper())
                if available_qty <= 0:
                    logger.warning("매도 가능한 잔고가 없습니다: coin=%s", str(target_coin).upper())
                    return

                sell_pct_raw = self._to_float(config_json.get("grid_sell_pct", 1.0))
                sell_ratio = sell_pct_raw / 100.0 if sell_pct_raw > 1 else sell_pct_raw
                sell_ratio = min(max(sell_ratio, 0.0), 1.0)
                if sell_ratio <= 0:
                    logger.warning("매도 비율이 유효하지 않습니다: grid_sell_pct=%s", sell_pct_raw)
                    return

                sell_volume = available_qty * sell_ratio
                if sell_volume <= 0:
                    logger.warning("계산된 매도 수량이 0 이하입니다: sell_volume=%s", sell_volume)
                    return

                order_result = await broker.create_order(
                    market=market,
                    side="ask",
                    ord_type="market",
                    volume=self._fmt_number(sell_volume),
                )
                logger.info("매도 조건 달성 로그: market=%s current_price=%s", market, current_price)
        except UpbitAPIError as exc:
            logger.exception("주문 실행 실패(UpbitAPIError): market=%s side=%s error=%s", market, signal_side, exc)
            return
        except Exception:
            logger.exception("주문 실행 중 예외가 발생했습니다: market=%s side=%s", market, signal_side)
            return

        if not isinstance(order_result, dict):
            logger.warning("주문 응답 형식이 dict가 아닙니다: market=%s side=%s", market, signal_side)
            return

        try:
            asset = await self._get_or_create_asset(db, market)
            position = await self._get_or_create_position(db, asset.id, current_price)

            executed_price = self._resolve_order_price(order_result, current_price)
            executed_qty = self._resolve_order_qty(
                order_result=order_result,
                side=signal_side,
                current_price=current_price,
                order_krw=order_krw,
                sell_volume=sell_volume,
            )
            executed_at = self._resolve_executed_at(order_result)

            history = OrderHistory(
                position_id=position.id,
                side=signal_side,
                price=executed_price,
                qty=executed_qty,
                broker="UPBIT",
                executed_at=executed_at,
            )
            db.add(history)

            cooldown_seconds = int(self._to_float(config_json.get("grid_cooldown_seconds", 30)))
            cooldown_seconds = max(cooldown_seconds, 1)
            next_cooldown = now_utc + timedelta(seconds=cooldown_seconds)

            updated_config = dict(config_json)
            updated_config["grid_cooldown_until"] = next_cooldown.isoformat()
            config.config_json = updated_config

            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("주문 성공 후 DB 기록 중 예외가 발생했습니다: market=%s side=%s", market, signal_side)

    async def _get_or_create_asset(self, db: AsyncSession, market: str) -> Asset:
        result = await db.execute(select(Asset).where(Asset.symbol == market))
        asset = result.scalar_one_or_none()
        if asset is not None:
            return asset

        asset = Asset(
            symbol=market,
            asset_type="crypto",
            base_currency="KRW",
            is_active=True,
        )
        db.add(asset)
        await db.flush()
        return asset

    async def _get_or_create_position(
        self,
        db: AsyncSession,
        asset_id: int,
        current_price: float,
    ) -> Position:
        result = await db.execute(
            select(Position).where(Position.asset_id == asset_id).order_by(Position.id.asc())
        )
        position = result.scalars().first()
        if position is not None:
            return position

        position = Position(
            asset_id=asset_id,
            avg_entry_price=current_price,
            quantity=0.0,
            status="open",
        )
        db.add(position)
        await db.flush()
        return position

    def _resolve_order_price(self, order_result: dict[str, Any], fallback_price: float) -> float:
        for key in ("price", "avg_price"):
            price = self._to_float(order_result.get(key))
            if price > 0:
                return price
        return fallback_price

    def _resolve_order_qty(
        self,
        order_result: dict[str, Any],
        side: str,
        current_price: float,
        order_krw: float,
        sell_volume: float,
    ) -> float:
        for key in ("executed_volume", "volume"):
            qty = self._to_float(order_result.get(key))
            if qty > 0:
                return qty

        if side == "buy" and current_price > 0 and order_krw > 0:
            return order_krw / current_price

        if side == "sell" and sell_volume > 0:
            return sell_volume

        return 0.0

    def _resolve_executed_at(self, order_result: dict[str, Any]) -> datetime:
        created_at = order_result.get("created_at")
        parsed = self._parse_datetime(created_at)
        return parsed if parsed is not None else datetime.now(timezone.utc)

    def _get_available_coin(self, accounts: list[dict[str, Any]], coin: str) -> float:
        for account in accounts:
            currency = str(account.get("currency") or "").upper()
            if currency != coin:
                continue

            balance = self._to_float(account.get("balance"))
            locked = self._to_float(account.get("locked"))
            return max(balance - locked, 0.0)
        return 0.0

    def _parse_datetime(self, value: Any) -> datetime | None:
        if not value or not isinstance(value, str):
            return None

        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _to_float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _fmt_number(self, value: float) -> str:
        return f"{value:.8f}".rstrip("0").rstrip(".") or "0"
