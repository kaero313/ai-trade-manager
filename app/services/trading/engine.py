import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.domain import Asset, BotConfig, OrderHistory, Position
from app.models.schemas import BotConfig as BotConfigSchema
from app.services.brokers.factory import BrokerFactory
from app.services.brokers.upbit import (
    UpbitAPIError,
    format_upbit_critical_message,
    is_critical_upbit_error,
)
from app.services.slack_bot import slack_bot
from app.services.trading.strategies.grid_strategy import GridStrategy

logger = logging.getLogger(__name__)
CRITICAL_ALERT_COOLDOWN_SECONDS = 60


class TradingEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self._is_running = True
        self._critical_alerts: dict[str, datetime] = {}

    async def run_loop(self) -> None:
        logger.info("TradingEngine run_loop 시작")
        try:
            while self._is_running:
                try:
                    async with self.session_factory() as db:
                        result = await db.execute(select(BotConfig).where(BotConfig.id == 1))
                        bot_config = result.scalar_one_or_none()

                        is_active = bool(bot_config.is_active) if bot_config else False
                        config_json = self._normalize_config_json(
                            bot_config.config_json if bot_config else None
                        )
                        grid_config = self._extract_grid_config(config_json)
                        trade_mode = str(grid_config.get("trade_mode", "grid")).lower().strip() or "grid"

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
        config_json = self._normalize_config_json(config.config_json)
        grid_config = self._extract_grid_config(config_json)

        target_coin = str(grid_config.get("target_coin") or "").upper()
        grid_upper_bound = self._to_float(grid_config.get("grid_upper_bound"))
        grid_lower_bound = self._to_float(grid_config.get("grid_lower_bound"))
        order_krw = self._to_float(grid_config.get("grid_order_krw"))
        grid_sell_pct = self._to_float(grid_config.get("grid_sell_pct"))
        grid_cooldown_seconds = int(self._to_float(grid_config.get("grid_cooldown_seconds")))
        grid_cooldown_seconds = max(grid_cooldown_seconds, 1)

        if not target_coin:
            logger.warning("그리드 target_coin 파싱에 실패하여 이번 tick을 건너뜁니다.")
            return
        if grid_upper_bound <= 0 or grid_lower_bound <= 0 or grid_lower_bound >= grid_upper_bound:
            logger.warning(
                "그리드 상/하단 값이 유효하지 않습니다: lower=%s upper=%s",
                grid_lower_bound,
                grid_upper_bound,
            )
            return

        market = f"KRW-{target_coin}"
        broker = BrokerFactory.get_broker("UPBIT")
        current_price = await self._fetch_current_price(broker, market)
        if current_price is None:
            return
        logger.info("그리드 현재가 조회 성공: market=%s current_price=%s", market, current_price)

        now_utc = datetime.now(timezone.utc)
        cooldown_until = self._parse_datetime(grid_config.get("grid_cooldown_until"))
        strategy = GridStrategy(
            market=market,
            target_coin=target_coin,
            grid_upper_bound=grid_upper_bound,
            grid_lower_bound=grid_lower_bound,
            grid_order_krw=order_krw,
            grid_sell_pct=grid_sell_pct,
            grid_cooldown_seconds=grid_cooldown_seconds,
            cooldown_until=cooldown_until,
        )

        try:
            strategy_result = await strategy.execute(
                current_price=current_price,
                broker=broker,
                current_time=now_utc,
            )
        except UpbitAPIError as exc:
            logger.exception("그리드 전략 실행 실패(UpbitAPIError): market=%s error=%s", market, exc)
            if is_critical_upbit_error(exc):
                await self._notify_critical_error(
                    key=f"upbit:{exc.status_code}:{exc.error_name}:{exc.message}",
                    message=format_upbit_critical_message(exc),
                )
            return
        except Exception as exc:
            logger.exception("그리드 전략 실행 중 예외가 발생했습니다: market=%s", market)
            generic_critical_message = self._resolve_generic_critical_message(exc)
            if generic_critical_message:
                await self._notify_critical_error(
                    key=f"generic:{generic_critical_message}",
                    message=generic_critical_message,
                )
            return

        if not strategy_result.executed:
            reason = str(strategy_result.reason or "no_signal")
            if reason == "cooldown":
                next_order_at = (
                    strategy_result.cooldown_until.isoformat()
                    if strategy_result.cooldown_until is not None
                    else "unknown"
                )
                logger.info("그리드 주문 쿨타임 적용 중입니다. next_order_at=%s", next_order_at)
            elif reason != "no_signal":
                logger.info("그리드 전략 미체결: market=%s reason=%s", market, reason)
            return

        signal_side = str(strategy_result.side or "").lower().strip()
        if signal_side not in {"buy", "sell"}:
            logger.warning("그리드 전략 반환 side 값이 유효하지 않습니다: side=%s market=%s", signal_side, market)
            return

        order_result = strategy_result.order_result if isinstance(strategy_result.order_result, dict) else {}
        if not order_result:
            logger.warning("주문 응답 형식이 dict가 아닙니다: market=%s side=%s", market, signal_side)
            return

        executed_price = (
            strategy_result.executed_price
            if strategy_result.executed_price > 0
            else self._resolve_order_price(order_result, current_price)
        )
        executed_qty = (
            strategy_result.executed_qty
            if strategy_result.executed_qty > 0
            else self._resolve_order_qty(
                order_result=order_result,
                side=signal_side,
                current_price=current_price,
                order_krw=order_krw,
                sell_volume=0.0,
            )
        )
        if executed_qty <= 0:
            logger.warning("주문 체결 수량 계산에 실패했습니다: market=%s side=%s", market, signal_side)
            return

        next_cooldown = strategy_result.cooldown_until or (
            now_utc + timedelta(seconds=grid_cooldown_seconds)
        )

        try:
            asset = await self._get_or_create_asset(db, market)
            position = await self._get_or_create_position(db, asset.id, current_price)
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

            updated_config = self._normalize_config_json(config_json)
            updated_grid = self._extract_grid_config(updated_config)
            updated_grid["grid_cooldown_until"] = next_cooldown.isoformat()
            updated_config["grid"] = updated_grid
            config.config_json = updated_config

            await db.commit()
            await self._notify_order_filled(
                market=market,
                side=signal_side,
                qty=executed_qty,
                price=executed_price,
            )
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

    def _normalize_config_json(self, raw_config: Any) -> dict[str, Any]:
        candidate = raw_config if isinstance(raw_config, dict) else {}
        try:
            normalized = BotConfigSchema.model_validate(candidate).model_dump()
        except Exception:
            logger.exception("봇 설정 JSON 파싱 실패. 기본값으로 대체합니다.")
            normalized = BotConfigSchema().model_dump()

        if isinstance(candidate.get("grid"), dict):
            runtime_grid = dict(candidate["grid"])
            cooldown_until = runtime_grid.get("grid_cooldown_until")
            if cooldown_until is not None:
                normalized_grid = normalized.get("grid", {})
                if not isinstance(normalized_grid, dict):
                    normalized_grid = {}
                normalized_grid = dict(normalized_grid)
                normalized_grid["grid_cooldown_until"] = cooldown_until
                normalized["grid"] = normalized_grid

        legacy_cooldown_until = candidate.get("grid_cooldown_until")
        if legacy_cooldown_until is not None:
            normalized["grid_cooldown_until"] = legacy_cooldown_until

        return normalized

    def _extract_grid_config(self, config_json: dict[str, Any]) -> dict[str, Any]:
        default_grid = BotConfigSchema().grid.model_dump()
        raw_grid = config_json.get("grid", {})
        if not isinstance(raw_grid, dict):
            raw_grid = {}

        merged: dict[str, Any] = dict(default_grid)
        for key in default_grid:
            if key in raw_grid:
                merged[key] = raw_grid[key]
            elif key in config_json:
                merged[key] = config_json[key]

        target_coin = self._normalize_coin_symbol(merged.get("target_coin"))
        merged["target_coin"] = target_coin or str(default_grid["target_coin"])
        merged["grid_upper_bound"] = self._to_float(merged.get("grid_upper_bound")) or self._to_float(
            default_grid["grid_upper_bound"]
        )
        merged["grid_lower_bound"] = self._to_float(merged.get("grid_lower_bound")) or self._to_float(
            default_grid["grid_lower_bound"]
        )
        merged["grid_order_krw"] = self._to_float(merged.get("grid_order_krw")) or self._to_float(
            default_grid["grid_order_krw"]
        )

        sell_pct = self._to_float(merged.get("grid_sell_pct"))
        merged["grid_sell_pct"] = sell_pct if sell_pct > 0 else self._to_float(default_grid["grid_sell_pct"])
        cooldown_seconds = int(self._to_float(merged.get("grid_cooldown_seconds")))
        merged["grid_cooldown_seconds"] = max(cooldown_seconds, 1)

        trade_mode = str(merged.get("trade_mode") or default_grid["trade_mode"]).lower().strip()
        merged["trade_mode"] = trade_mode or str(default_grid["trade_mode"])
        merged["grid_cooldown_until"] = raw_grid.get(
            "grid_cooldown_until",
            config_json.get("grid_cooldown_until"),
        )
        return merged

    def _normalize_coin_symbol(self, raw_coin: Any) -> str | None:
        if raw_coin is None:
            return None
        symbol = str(raw_coin).strip().upper()
        if not symbol:
            return None
        if symbol.startswith("KRW-"):
            symbol = symbol[4:]
        return symbol or None

    async def _fetch_current_price(self, broker: Any, market: str) -> float | None:
        try:
            tickers = await broker.get_ticker([market])
        except UpbitAPIError as exc:
            logger.exception("현재가 조회 실패(UpbitAPIError): market=%s error=%s", market, exc)
            if is_critical_upbit_error(exc):
                await self._notify_critical_error(
                    key=f"ticker:{exc.status_code}:{exc.error_name}:{exc.message}",
                    message=format_upbit_critical_message(exc),
                )
            return None
        except Exception:
            logger.exception("현재가 조회 중 예외가 발생했습니다: market=%s", market)
            return None

        if not isinstance(tickers, list) or not tickers or not isinstance(tickers[0], dict):
            logger.warning("현재가 조회 결과가 비어 있거나 형식이 올바르지 않습니다: market=%s", market)
            return None

        current_price = self._to_float(tickers[0].get("trade_price"))
        if current_price <= 0:
            logger.warning(
                "현재가 파싱 실패 또는 비정상 값입니다: market=%s trade_price=%s",
                market,
                tickers[0].get("trade_price"),
            )
            return None
        return current_price

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

    async def _notify_order_filled(
        self,
        market: str,
        side: str,
        qty: float,
        price: float,
    ) -> None:
        side_label = "매수 완료" if side == "buy" else "매도 완료"
        coin = market.split("-", 1)[1] if "-" in market else market
        qty_text = self._fmt_number(qty)
        price_text = self._fmt_krw(price)
        text = f"✅ [{side_label}] {coin} {qty_text} (가격: {price_text})"
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{side_label}*\n- 마켓: `{market}`\n- 수량: `{qty_text}`\n- 가격: `{price_text}`",
                },
            }
        ]
        await self._send_slack_message(text=text, blocks=blocks)

    async def _notify_critical_error(self, key: str, message: str) -> None:
        if not self._should_send_critical_alert(key):
            return
        text = f"🚨 [에러 발생] {message}"
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🚨 *치명적 에러 발생*\n{message}",
                },
            }
        ]
        await self._send_slack_message(text=text, blocks=blocks)

    async def _send_slack_message(self, text: str, blocks: list[dict[str, Any]] | None = None) -> None:
        try:
            await asyncio.to_thread(slack_bot.send_message, text, blocks)
        except Exception:
            logger.exception("Slack 알림 전송 중 예외가 발생했습니다.")

    def _should_send_critical_alert(self, key: str) -> bool:
        now_utc = datetime.now(timezone.utc)
        last_sent = self._critical_alerts.get(key)
        if last_sent is not None:
            elapsed = (now_utc - last_sent).total_seconds()
            if elapsed < CRITICAL_ALERT_COOLDOWN_SECONDS:
                return False

        self._critical_alerts[key] = now_utc

        stale_threshold = now_utc - timedelta(seconds=CRITICAL_ALERT_COOLDOWN_SECONDS * 5)
        stale_keys = [item_key for item_key, sent_at in self._critical_alerts.items() if sent_at < stale_threshold]
        for stale_key in stale_keys:
            self._critical_alerts.pop(stale_key, None)
        return True

    def _resolve_generic_critical_message(self, error: Exception) -> str | None:
        text = str(error).lower()
        auth_keywords = ("access/secret key not configured", "api key", "access key", "secret key")
        balance_keywords = ("insufficient", "insufficient_funds", "잔고", "부족")

        if any(keyword in text for keyword in auth_keywords):
            return "업비트 API 키 또는 권한 설정이 올바르지 않습니다."
        if any(keyword in text for keyword in balance_keywords):
            return "업비트 잔고가 부족합니다."
        return None

    @staticmethod
    def _fmt_krw(value: float) -> str:
        return f"{value:,.0f}원"
