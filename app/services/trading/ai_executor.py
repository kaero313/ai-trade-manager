import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import AI_ANALYSIS_MAX_AGE_MINUTES_KEY
from app.db.repository import AI_MIN_CONFIDENCE_TRADE_KEY
from app.db.repository import HARD_STOP_LOSS_PCT_KEY
from app.db.repository import HARD_TAKE_PROFIT_PCT_KEY
from app.db.repository import MAX_ALLOCATION_PCT_KEY
from app.db.repository import get_system_config_value
from app.models.domain import AIAnalysisLog, Asset, OrderHistory, Position
from app.schemas.portfolio import AssetItem, PortfolioSummary
from app.services.bot_service import get_bot_status
from app.services.brokers.factory import BrokerFactory
from app.services.brokers.upbit import UpbitAPIError
from app.services.portfolio.aggregator import PortfolioService
from app.services.slack import slack_client
from app.services.trading.paper import apply_paper_fill
from app.services.trading.paper import build_paper_order_result
from app.services.trading.paper import get_trading_mode

logger = logging.getLogger(__name__)

DEFAULT_AI_MIN_CONFIDENCE_TRADE = 70
DEFAULT_AI_ANALYSIS_MAX_AGE_MINUTES = 90
DEFAULT_MAX_ALLOCATION_PCT = 10.0
DEFAULT_HARD_TAKE_PROFIT_PCT = 0.0
DEFAULT_HARD_STOP_LOSS_PCT = 0.0
MIN_ORDER_KRW = 5000.0
ORDER_REASON_TP_SELL = "TP_SELL"
ORDER_REASON_SL_SELL = "SL_SELL"


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _extract_quote_currency(symbol: str) -> str:
    normalized_symbol = _normalize_symbol(symbol)
    if "-" not in normalized_symbol:
        return "KRW"
    return normalized_symbol.split("-", 1)[0]


def _extract_target_currency(symbol: str) -> str:
    normalized_symbol = _normalize_symbol(symbol)
    if "-" not in normalized_symbol:
        return normalized_symbol
    return normalized_symbol.split("-", 1)[1]


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _fmt_number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".") or "0"


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_int_config(
    raw_value: str | None,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(str(raw_value).strip())
    except (TypeError, ValueError, AttributeError):
        return default

    if parsed < minimum or parsed > maximum:
        return default
    return parsed


def _parse_float_config(
    raw_value: str | None,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(str(raw_value).strip())
    except (TypeError, ValueError, AttributeError):
        return default

    if parsed < minimum or parsed > maximum:
        return default
    return parsed


def _find_portfolio_item(portfolio: PortfolioSummary, currency: str) -> AssetItem | None:
    normalized_currency = str(currency or "").strip().upper()
    for item in portfolio.items:
        if item.currency.upper() == normalized_currency:
            return item
    return None


def _available_amount(item: AssetItem | None) -> float:
    if item is None:
        return 0.0
    return max(_to_float(item.balance) - _to_float(item.locked), 0.0)


def _resolve_weighted_amount(total_amount: float, recommended_weight: int) -> float:
    weight_ratio = max(0.0, min(float(recommended_weight), 100.0)) / 100.0
    return total_amount * weight_ratio


async def _load_executor_thresholds(db: AsyncSession) -> tuple[int, int]:
    min_confidence_raw = await get_system_config_value(
        db,
        AI_MIN_CONFIDENCE_TRADE_KEY,
        default=str(DEFAULT_AI_MIN_CONFIDENCE_TRADE),
    )
    max_age_raw = await get_system_config_value(
        db,
        AI_ANALYSIS_MAX_AGE_MINUTES_KEY,
        default=str(DEFAULT_AI_ANALYSIS_MAX_AGE_MINUTES),
    )

    min_confidence = _parse_int_config(
        min_confidence_raw,
        default=DEFAULT_AI_MIN_CONFIDENCE_TRADE,
        minimum=0,
        maximum=100,
    )
    max_age_minutes = _parse_int_config(
        max_age_raw,
        default=DEFAULT_AI_ANALYSIS_MAX_AGE_MINUTES,
        minimum=1,
        maximum=24 * 60,
    )
    return min_confidence, max_age_minutes


async def _load_max_allocation_pct(db: AsyncSession) -> float:
    raw_value = await get_system_config_value(
        db,
        MAX_ALLOCATION_PCT_KEY,
        default=str(DEFAULT_MAX_ALLOCATION_PCT),
    )
    return _parse_float_config(
        raw_value,
        default=DEFAULT_MAX_ALLOCATION_PCT,
        minimum=0.0,
        maximum=100.0,
    )


async def _load_hard_tp_sl_thresholds(db: AsyncSession) -> tuple[float, float]:
    take_profit_raw = await get_system_config_value(
        db,
        HARD_TAKE_PROFIT_PCT_KEY,
        default=str(DEFAULT_HARD_TAKE_PROFIT_PCT),
    )
    stop_loss_raw = await get_system_config_value(
        db,
        HARD_STOP_LOSS_PCT_KEY,
        default=str(DEFAULT_HARD_STOP_LOSS_PCT),
    )

    hard_take_profit_pct = _parse_float_config(
        take_profit_raw,
        default=DEFAULT_HARD_TAKE_PROFIT_PCT,
        minimum=0.0,
        maximum=1000.0,
    )
    hard_stop_loss_pct = _parse_float_config(
        stop_loss_raw,
        default=DEFAULT_HARD_STOP_LOSS_PCT,
        minimum=-1000.0,
        maximum=0.0,
    )
    return hard_take_profit_pct, hard_stop_loss_pct


async def _load_latest_analysis(db: AsyncSession, symbol: str) -> AIAnalysisLog | None:
    result = await db.execute(
        select(AIAnalysisLog)
        .where(AIAnalysisLog.symbol == _normalize_symbol(symbol))
        .order_by(desc(AIAnalysisLog.created_at), desc(AIAnalysisLog.id))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _is_analysis_stale(analysis: AIAnalysisLog, max_age_minutes: int) -> bool:
    created_at = _normalize_datetime(analysis.created_at)
    return created_at < (datetime.now(UTC) - timedelta(minutes=max_age_minutes))


async def _resolve_current_price(symbol: str, portfolio_item: AssetItem | None) -> float:
    if portfolio_item is not None and _to_float(portfolio_item.current_price) > 0:
        return _to_float(portfolio_item.current_price)

    broker = BrokerFactory.get_broker("UPBIT")
    tickers = await broker.get_ticker([_normalize_symbol(symbol)])
    if not tickers:
        return 0.0
    return _to_float(tickers[0].get("trade_price"))


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _normalize_datetime(parsed)


def _resolve_order_price(order_result: dict[str, Any], fallback_price: float) -> float:
    for key in ("price", "avg_price", "trade_price"):
        price = _to_float(order_result.get(key))
        if price > 0:
            return price
    return fallback_price


def _resolve_order_qty(order_result: dict[str, Any], fallback_qty: float) -> float:
    for key in ("executed_volume", "volume"):
        qty = _to_float(order_result.get(key))
        if qty > 0:
            return qty
    return fallback_qty


async def _get_or_create_asset(db: AsyncSession, market: str) -> Asset:
    result = await db.execute(select(Asset).where(Asset.symbol == market))
    asset = result.scalar_one_or_none()
    if asset is not None:
        return asset

    asset = Asset(
        symbol=market,
        asset_type="crypto",
        base_currency=_extract_quote_currency(market),
        is_active=True,
    )
    db.add(asset)
    await db.flush()
    return asset


async def _get_or_create_position(
    db: AsyncSession,
    asset_id: int,
    fallback_price: float,
    *,
    is_paper: bool,
) -> Position:
    result = await db.execute(
        select(Position)
        .where(Position.asset_id == asset_id, Position.is_paper.is_(is_paper))
        .order_by(Position.id.asc())
    )
    position = result.scalars().first()
    if position is not None:
        return position

    position = Position(
        asset_id=asset_id,
        avg_entry_price=max(fallback_price, 0.0),
        quantity=0.0,
        status="open",
        is_paper=is_paper,
    )
    db.add(position)
    await db.flush()
    return position


async def _record_order_history(
    *,
    db: AsyncSession,
    symbol: str,
    analysis: AIAnalysisLog | None,
    side: str,
    order_result: dict[str, Any],
    fallback_price: float,
    fallback_qty: float,
    order_reason: str | None = None,
    is_paper: bool = False,
) -> None:
    resolved_price = _resolve_order_price(order_result, fallback_price)
    resolved_qty = _resolve_order_qty(order_result, fallback_qty)
    if resolved_price <= 0 or resolved_qty <= 0:
        logger.warning(
            "AI 주문 이력 기록 스킵: 체결 가격/수량을 확정할 수 없습니다. symbol=%s side=%s price=%s qty=%s",
            symbol,
            side,
            resolved_price,
            resolved_qty,
        )
        return

    executed_at = _parse_datetime(order_result.get("created_at")) or datetime.now(UTC)

    try:
        asset = await _get_or_create_asset(db, symbol)
        position = await _get_or_create_position(db, asset.id, resolved_price, is_paper=is_paper)
        db.add(
            OrderHistory(
                position_id=position.id,
                ai_analysis_log_id=analysis.id if analysis is not None else None,
                side=side,
                order_reason=order_reason,
                is_paper=is_paper,
                price=resolved_price,
                qty=resolved_qty,
                broker="UPBIT",
                executed_at=executed_at,
            )
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("AI 주문 이력 기록 실패: symbol=%s side=%s error=%s", symbol, side, exc, exc_info=True)


async def _send_trade_notification(
    *,
    symbol: str,
    decision: str,
    confidence: int,
    recommended_weight: int,
    order_result: dict[str, Any],
) -> None:
    order_uuid = str(order_result.get("uuid") or "").strip()
    lines = [
        f"[AI 자율 체결 알림] {symbol} 시장가 {decision} (확신도: {confidence}%, 추천 비중: {recommended_weight}%)",
    ]
    if order_uuid:
        lines.append(f"주문 UUID: {order_uuid}")

    try:
        await slack_client.send_message(
            "\n".join(lines),
            username="AI Executor",
            icon_emoji=":robot_face:",
        )
    except Exception as exc:
        logger.warning("Slack 자율 체결 알림 전송 실패: %s", exc, exc_info=True)


async def execute_hard_tp_sl_check(db: AsyncSession) -> set[str]:
    hard_take_profit_pct, hard_stop_loss_pct = await _load_hard_tp_sl_thresholds(db)
    tp_enabled = hard_take_profit_pct > 0
    sl_enabled = hard_stop_loss_pct < 0

    if not tp_enabled and not sl_enabled:
        logger.info("하드 TP/SL 체크 우회: TP/SL 임계값이 모두 비활성화되었습니다.")
        return set()

    portfolio = await PortfolioService(db).get_aggregated_portfolio()
    if portfolio.error is not None:
        logger.warning("하드 TP/SL 체크 스킵: 포트폴리오 조회 실패 error=%s", portfolio.error)
        return set()

    trading_mode = await get_trading_mode(db)
    broker = BrokerFactory.get_broker("UPBIT") if trading_mode == "live" else None
    liquidated_symbols: set[str] = set()

    for item in portfolio.items:
        currency = str(item.currency or "").strip().upper()
        if not currency or currency == "KRW":
            continue

        available_qty = _available_amount(item)
        if available_qty <= 0:
            continue

        pnl_percentage = _to_float(item.pnl_percentage)
        trigger_reason: str | None = None
        if tp_enabled and pnl_percentage >= hard_take_profit_pct:
            trigger_reason = ORDER_REASON_TP_SELL
        elif sl_enabled and pnl_percentage <= hard_stop_loss_pct:
            trigger_reason = ORDER_REASON_SL_SELL

        if trigger_reason is None:
            continue

        symbol = _normalize_symbol(f"KRW-{currency}")
        try:
            current_price = await _resolve_current_price(symbol, item)
        except (ValueError, UpbitAPIError) as exc:
            logger.warning(
                "하드 TP/SL 현재가 조회 실패: symbol=%s error=%s",
                symbol,
                exc,
                exc_info=True,
            )
            continue
        except Exception as exc:
            logger.error(
                "하드 TP/SL 현재가 조회 중 예기치 못한 오류: symbol=%s error=%s",
                symbol,
                exc,
                exc_info=True,
            )
            continue

        estimated_order_value = available_qty * current_price
        if estimated_order_value < MIN_ORDER_KRW:
            logger.info(
                "하드 TP/SL 스킵: 최소 주문 금액 미만입니다. symbol=%s reason=%s estimated_value=%s",
                symbol,
                trigger_reason,
                estimated_order_value,
            )
            continue

        if trading_mode == "paper":
            executed_at = datetime.now(UTC)
            order_result = build_paper_order_result(
                market=symbol,
                side="ask",
                ord_type="market",
                executed_price=current_price,
                executed_qty=available_qty,
                executed_at=executed_at,
            )
            try:
                await apply_paper_fill(
                    db=db,
                    symbol=symbol,
                    side="sell",
                    executed_price=current_price,
                    executed_qty=available_qty,
                    executed_at=executed_at,
                    order_reason=trigger_reason,
                )
                await db.commit()
            except ValueError as exc:
                await db.rollback()
                logger.info(
                    "하드 TP/SL paper 매도 스킵: symbol=%s reason=%s error=%s",
                    symbol,
                    trigger_reason,
                    exc,
                )
                continue
            except Exception as exc:
                await db.rollback()
                logger.error(
                    "하드 TP/SL paper 매도 중 예기치 못한 오류: symbol=%s reason=%s error=%s",
                    symbol,
                    trigger_reason,
                    exc,
                    exc_info=True,
                )
                continue
        else:
            try:
                raw_order = await broker.create_order(
                    market=symbol,
                    side="ask",
                    ord_type="market",
                    volume=_fmt_number(available_qty),
                )
            except (ValueError, UpbitAPIError) as exc:
                logger.warning(
                    "하드 TP/SL 시장가 매도 실패: symbol=%s reason=%s error=%s",
                    symbol,
                    trigger_reason,
                    exc,
                    exc_info=True,
                )
                continue
            except Exception as exc:
                logger.error(
                    "하드 TP/SL 시장가 매도 중 예기치 못한 오류: symbol=%s reason=%s error=%s",
                    symbol,
                    trigger_reason,
                    exc,
                    exc_info=True,
                )
                continue

            order_result = raw_order if isinstance(raw_order, dict) else {}
            await _record_order_history(
                db=db,
                symbol=symbol,
                analysis=None,
                side="sell",
                order_result=order_result,
                fallback_price=current_price,
                fallback_qty=available_qty,
                order_reason=trigger_reason,
                is_paper=False,
            )

        liquidated_symbols.add(symbol)
        logger.info(
            "하드 TP/SL 시장가 매도 성공: symbol=%s reason=%s pnl_percentage=%s qty=%s uuid=%s mode=%s",
            symbol,
            trigger_reason,
            pnl_percentage,
            available_qty,
            order_result.get("uuid"),
            trading_mode,
        )

    return liquidated_symbols


async def _execute_buy_trade(
    *,
    db: AsyncSession,
    symbol: str,
    analysis: AIAnalysisLog,
    portfolio: PortfolioSummary,
    trading_mode: str,
) -> None:
    quote_currency = _extract_quote_currency(symbol)
    target_currency = _extract_target_currency(symbol)
    cash_item = _find_portfolio_item(portfolio, quote_currency)
    target_item = _find_portfolio_item(portfolio, target_currency)
    available_krw = _available_amount(cash_item)

    if available_krw <= 0:
        logger.info("AI 매수 스킵: 사용 가능한 %s 잔고가 없습니다. symbol=%s", quote_currency, symbol)
        return

    total_krw = max(_to_float(portfolio.total_net_worth), 0.0)
    max_allocation_pct = await _load_max_allocation_pct(db)
    max_budget = total_krw * (max_allocation_pct / 100.0)
    current_position_value = max(_to_float(target_item.total_value) if target_item is not None else 0.0, 0.0)
    remaining_budget = max(max_budget - current_position_value, 0.0)

    if remaining_budget <= 0:
        logger.info(
            "AI 매수 스킵: 종목당 최대 비중 한도에 도달했습니다. symbol=%s total_krw=%s max_budget=%s current_position_value=%s",
            symbol,
            total_krw,
            max_budget,
            current_position_value,
        )
        return

    target_budget = _resolve_weighted_amount(remaining_budget, analysis.recommended_weight)
    if target_budget <= 0:
        logger.info(
            "AI 매수 스킵: 계산된 목표 예산이 0 이하입니다. symbol=%s target_budget=%s remaining_budget=%s",
            symbol,
            target_budget,
            remaining_budget,
        )
        return

    fee_buffer = 0.995  # 0.5% 여유분 (업비트 수수료 0.05% 대비 충분한 버퍼)
    order_amount_krw = target_budget * fee_buffer
    if order_amount_krw < MIN_ORDER_KRW:
        order_amount_krw = MIN_ORDER_KRW

    if order_amount_krw > available_krw:
        logger.info(
            "AI 매수 스킵: 가용 KRW보다 주문 금액이 큽니다. symbol=%s available_krw=%s order_amount=%s target_budget=%s",
            symbol,
            available_krw,
            order_amount_krw,
            target_budget,
        )
        return

    logger.info(
        "AI 매수 시도: symbol=%s total_krw=%s max_allocation_pct=%s max_budget=%s current_position_value=%s remaining_budget=%s target_budget=%s total_avail=%s order_amount=%s mode=%s",
        symbol,
        total_krw,
        max_allocation_pct,
        max_budget,
        current_position_value,
        remaining_budget,
        target_budget,
        available_krw,
        order_amount_krw,
        trading_mode,
    )
    if trading_mode == "paper":
        try:
            executed_price = await _resolve_current_price(symbol, target_item)
        except (ValueError, UpbitAPIError) as exc:
            logger.warning("AI paper 매수 스킵: 현재가 조회 실패 symbol=%s error=%s", symbol, exc, exc_info=True)
            return
        except Exception as exc:
            logger.error("AI paper 매수 현재가 조회 중 예기치 못한 오류: symbol=%s error=%s", symbol, exc, exc_info=True)
            return

        if executed_price <= 0:
            logger.info("AI paper 매수 스킵: 현재가가 유효하지 않습니다. symbol=%s", symbol)
            return

        executed_qty = order_amount_krw / executed_price
        executed_at = datetime.now(UTC)
        order_result = build_paper_order_result(
            market=symbol,
            side="bid",
            ord_type="price",
            executed_price=executed_price,
            executed_qty=executed_qty,
            executed_at=executed_at,
        )
        try:
            await apply_paper_fill(
                db=db,
                symbol=symbol,
                side="buy",
                executed_price=executed_price,
                executed_qty=executed_qty,
                executed_at=executed_at,
                ai_analysis_log_id=analysis.id,
            )
            await db.commit()
        except ValueError as exc:
            await db.rollback()
            logger.info("AI paper 매수 스킵: symbol=%s error=%s", symbol, exc)
            return
        except Exception as exc:
            await db.rollback()
            logger.error("AI paper 매수 적용 중 예기치 못한 오류: symbol=%s error=%s", symbol, exc, exc_info=True)
            return
    else:
        broker = BrokerFactory.get_broker("UPBIT")
        try:
            raw_order = await broker.create_order(
                market=symbol,
                side="bid",
                ord_type="price",
                price=_fmt_number(order_amount_krw),
            )
        except (ValueError, UpbitAPIError) as exc:
            logger.warning("AI 시장가 매수 실패: symbol=%s error=%s", symbol, exc, exc_info=True)
            return
        except Exception as exc:
            logger.error("AI 시장가 매수 중 예기치 못한 오류: symbol=%s error=%s", symbol, exc, exc_info=True)
            return

        order_result = raw_order if isinstance(raw_order, dict) else {}
        fallback_price = _resolve_order_price(order_result, 0.0)
        if fallback_price <= 0:
            try:
                fallback_price = await _resolve_current_price(symbol, None)
            except Exception as exc:
                logger.warning("AI 매수 체결가 보정 실패: symbol=%s error=%s", symbol, exc, exc_info=True)
                fallback_price = 0.0
        fallback_qty = order_amount_krw / fallback_price if fallback_price > 0 else 0.0
        await _record_order_history(
            db=db,
            symbol=symbol,
            analysis=analysis,
            side="buy",
            order_result=order_result,
            fallback_price=fallback_price,
            fallback_qty=fallback_qty,
            is_paper=False,
        )

    logger.info(
        "AI 시장가 매수 성공: symbol=%s confidence=%s weight=%s uuid=%s mode=%s",
        symbol,
        analysis.confidence,
        analysis.recommended_weight,
        order_result.get("uuid"),
        trading_mode,
    )
    await _send_trade_notification(
        symbol=symbol,
        decision="BUY",
        confidence=analysis.confidence,
        recommended_weight=analysis.recommended_weight,
        order_result=order_result,
    )


async def _execute_sell_trade(
    *,
    db: AsyncSession,
    symbol: str,
    analysis: AIAnalysisLog,
    portfolio: PortfolioSummary,
    trading_mode: str,
) -> None:
    target_currency = _extract_target_currency(symbol)
    coin_item = _find_portfolio_item(portfolio, target_currency)
    available_qty = _available_amount(coin_item)

    if available_qty <= 0:
        logger.info("AI 매도 스킵: 매도 가능한 코인 잔고가 없습니다. symbol=%s", symbol)
        return

    sell_volume = min(
        _resolve_weighted_amount(available_qty, analysis.recommended_weight),
        available_qty,
    )
    if sell_volume <= 0:
        logger.info("AI 매도 스킵: 계산된 매도 수량이 0 이하입니다. symbol=%s", symbol)
        return

    try:
        current_price = await _resolve_current_price(symbol, coin_item)
    except (ValueError, UpbitAPIError) as exc:
        logger.warning("AI 매도 스킵: 현재가 조회 실패 symbol=%s error=%s", symbol, exc, exc_info=True)
        return
    except Exception as exc:
        logger.error("AI 매도 현재가 조회 중 예기치 못한 오류: symbol=%s error=%s", symbol, exc, exc_info=True)
        return

    estimated_order_value = sell_volume * current_price
    if estimated_order_value < MIN_ORDER_KRW:
        logger.info(
            "AI 매도 스킵: 최소 주문 금액 미만입니다. symbol=%s estimated_value=%s",
            symbol,
            estimated_order_value,
        )
        return

    if trading_mode == "paper":
        executed_at = datetime.now(UTC)
        order_result = build_paper_order_result(
            market=symbol,
            side="ask",
            ord_type="market",
            executed_price=current_price,
            executed_qty=sell_volume,
            executed_at=executed_at,
        )
        try:
            await apply_paper_fill(
                db=db,
                symbol=symbol,
                side="sell",
                executed_price=current_price,
                executed_qty=sell_volume,
                executed_at=executed_at,
                ai_analysis_log_id=analysis.id,
            )
            await db.commit()
        except ValueError as exc:
            await db.rollback()
            logger.info("AI paper 매도 스킵: symbol=%s error=%s", symbol, exc)
            return
        except Exception as exc:
            await db.rollback()
            logger.error("AI paper 매도 적용 중 예기치 못한 오류: symbol=%s error=%s", symbol, exc, exc_info=True)
            return
    else:
        broker = BrokerFactory.get_broker("UPBIT")
        try:
            raw_order = await broker.create_order(
                market=symbol,
                side="ask",
                ord_type="market",
                volume=_fmt_number(sell_volume),
            )
        except (ValueError, UpbitAPIError) as exc:
            logger.warning("AI 시장가 매도 실패: symbol=%s error=%s", symbol, exc, exc_info=True)
            return
        except Exception as exc:
            logger.error("AI 시장가 매도 중 예기치 못한 오류: symbol=%s error=%s", symbol, exc, exc_info=True)
            return

        order_result = raw_order if isinstance(raw_order, dict) else {}
        await _record_order_history(
            db=db,
            symbol=symbol,
            analysis=analysis,
            side="sell",
            order_result=order_result,
            fallback_price=current_price,
            fallback_qty=sell_volume,
            is_paper=False,
        )

    logger.info(
        "AI 시장가 매도 성공: symbol=%s confidence=%s weight=%s uuid=%s mode=%s",
        symbol,
        analysis.confidence,
        analysis.recommended_weight,
        order_result.get("uuid"),
        trading_mode,
    )
    await _send_trade_notification(
        symbol=symbol,
        decision="SELL",
        confidence=analysis.confidence,
        recommended_weight=analysis.recommended_weight,
        order_result=order_result,
    )


async def execute_ai_trade(db: AsyncSession, symbol: str) -> None:
    normalized_symbol = _normalize_symbol(symbol)
    if not normalized_symbol:
        logger.info("AI 실행 스킵: symbol 이 비어 있습니다.")
        return

    status = await get_bot_status(db)
    if not status.running:
        logger.info("봇 꺼짐 - 반자율 탐색 모드 유지: symbol=%s", normalized_symbol)
        return

    min_confidence, max_age_minutes = await _load_executor_thresholds(db)

    latest_analysis = await _load_latest_analysis(db, normalized_symbol)
    if latest_analysis is None:
        logger.info("AI 실행 스킵: 최신 분석 로그가 없습니다. symbol=%s", normalized_symbol)
        return

    if _is_analysis_stale(latest_analysis, max_age_minutes):
        logger.info(
            "AI 실행 스킵: 분석 로그가 만료되었습니다. symbol=%s created_at=%s max_age_minutes=%s",
            normalized_symbol,
            latest_analysis.created_at,
            max_age_minutes,
        )
        return

    if latest_analysis.decision == "HOLD":
        logger.info("AI 실행 스킵: 관망 결정입니다. symbol=%s", normalized_symbol)
        return

    if latest_analysis.confidence < min_confidence:
        logger.info(
            "AI 실행 스킵: 확신도 부족. symbol=%s confidence=%s min_confidence=%s",
            normalized_symbol,
            latest_analysis.confidence,
            min_confidence,
        )
        return

    if latest_analysis.recommended_weight <= 0:
        logger.info(
            "AI 실행 스킵: 추천 비중이 0 이하입니다. symbol=%s recommended_weight=%s",
            normalized_symbol,
            latest_analysis.recommended_weight,
        )
        return

    portfolio = await PortfolioService(db).get_aggregated_portfolio()
    if portfolio.error is not None:
        logger.warning(
            "AI 실행 스킵: 포트폴리오 조회 실패. symbol=%s error=%s",
            normalized_symbol,
            portfolio.error,
        )
        return

    trading_mode = await get_trading_mode(db)
    if latest_analysis.decision == "BUY":
        await _execute_buy_trade(
            db=db,
            symbol=normalized_symbol,
            analysis=latest_analysis,
            portfolio=portfolio,
            trading_mode=trading_mode,
        )
        return

    if latest_analysis.decision == "SELL":
        await _execute_sell_trade(
            db=db,
            symbol=normalized_symbol,
            analysis=latest_analysis,
            portfolio=portfolio,
            trading_mode=trading_mode,
        )
        return

    logger.info(
        "AI 실행 스킵: 지원되지 않는 decision 값입니다. symbol=%s decision=%s",
        normalized_symbol,
        latest_analysis.decision,
    )
