import asyncio
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import AI_ANALYSIS_MAX_AGE_MINUTES_KEY
from app.db.repository import AI_MAX_BUY_WEIGHT_PCT_KEY
from app.db.repository import AI_MIN_CONFIDENCE_TRADE_KEY
from app.db.repository import HARD_STOP_LOSS_PCT_KEY
from app.db.repository import HARD_TAKE_PROFIT_PCT_KEY
from app.db.repository import LIVE_BUY_ENABLED_KEY
from app.db.repository import MAX_ALLOCATION_PCT_KEY
from app.db.repository import PAPER_TRADING_KRW_BALANCE_KEY
from app.db.repository import RAG_BUY_PRECHECK_NEWS_MAX_AGE_MINUTES_KEY
from app.db.repository import RAG_BUY_PRECHECK_NEWS_REFRESH_ENABLED_KEY
from app.db.repository import get_system_config_value
from app.db.session import AsyncSessionLocal, engine
from app.models.domain import AIAnalysisLog, Asset, OrderHistory, Position, SystemConfig
from app.models.schemas import AIAnalysisResponse
from app.schemas.portfolio import AssetItem, PortfolioSummary
from app.services.ai.provider_router import AIProviderRouter
from app.services.ai.provider_router import AIProviderUnavailableError
from app.services.bot_service import get_bot_status
from app.services.brokers.factory import BrokerFactory
from app.services.brokers.upbit import UpbitAPIError
from app.services.portfolio.aggregator import PortfolioService
from app.services.slack_bot import slack_bot
from app.services.trading.paper import DEFAULT_PAPER_KRW_BALANCE
from app.services.trading.paper import PAPER_BALANCE_DESCRIPTION
from app.services.trading.paper import PAPER_BALANCE_EPSILON
from app.services.trading.paper import PAPER_BROKER_NAME
from app.services.trading.paper import build_paper_order_result
from app.services.trading.paper import get_trading_mode
from app.services.trading.entry_policy import EntryGateResult
from app.services.trading.entry_policy import evaluate_ai_buy_entry_gate
from app.services.trading.analysis_lineage import AI_ANALYSIS_DETERMINISTIC_HOLD_MODEL
from app.services.trading.analysis_lineage import AI_ANALYSIS_STAGE_BUY_PRECHECK
from app.services.trading.analysis_lineage import AI_ANALYSIS_STAGE_TRADE
from app.services.trading.analysis_lineage import AI_ANALYSIS_SYSTEM_PROVIDER
from app.services.trading.analysis_lineage import BUY_PRECHECK_PROMPT_VERSION
from app.services.trading.analysis_lineage import hash_analysis_context
from app.services.trading.live_order_execution import LiveOrderExecutionService
from app.services.trading.live_order_execution import LiveOrderRequest
from app.services.trading.live_order_execution import LiveOrderResult
from app.services.trading.live_order_submission_barrier import LiveOrderSubmissionBarrier

logger = logging.getLogger(__name__)

DEFAULT_AI_MIN_CONFIDENCE_TRADE = 75
DEFAULT_AI_ANALYSIS_MAX_AGE_MINUTES = 90
DEFAULT_MAX_ALLOCATION_PCT = 30.0
DEFAULT_AI_MAX_BUY_WEIGHT_PCT = 30.0
DEFAULT_LIVE_BUY_ENABLED = False
DEFAULT_BUY_PRECHECK_NEWS_REFRESH_ENABLED = True
DEFAULT_BUY_PRECHECK_NEWS_MAX_AGE_MINUTES = 60
BUY_PRECHECK_NEWS_ITEM_LIMIT = 3
BUY_PRECHECK_NEWS_SUMMARY_MAX_CHARS = 180
DEFAULT_HARD_TAKE_PROFIT_PCT = 0.0
DEFAULT_HARD_STOP_LOSS_PCT = 0.0
MIN_ORDER_KRW = 5000.0
ORDER_REASON_TP_SELL = "TP_SELL"
ORDER_REASON_SL_SELL = "SL_SELL"
LIVE_ORDER_BLOCKING_SUBMISSION_STATUSES = {"ACCEPTED", "SUBMITTING", "UNKNOWN"}


class RiskCheckStatus(StrEnum):
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class RiskCheckResult:
    status: RiskCheckStatus
    liquidated_symbols: frozenset[str] = field(default_factory=frozenset)
    affected_symbols: frozenset[str] = field(default_factory=frozenset)
    reasons: tuple[str, ...] = ()

    @property
    def allows_new_buy(self) -> bool:
        return self.status in {
            RiskCheckStatus.HEALTHY,
            RiskCheckStatus.DISABLED,
        }


@dataclass(frozen=True)
class _HardRiskTrigger:
    symbol: str
    item: AssetItem
    order_reason: str


@dataclass(frozen=True)
class _HardRiskAssessment:
    result: RiskCheckResult
    triggers: tuple[_HardRiskTrigger, ...] = ()


def _build_live_order_execution_service() -> LiveOrderExecutionService:
    return LiveOrderExecutionService(
        AsyncSessionLocal,
        BrokerFactory.get_broker("UPBIT"),
        LiveOrderSubmissionBarrier(engine),
    )


async def _close_caller_transaction_before_live_order(db: AsyncSession) -> None:
    """Upbit POST를 기다리는 동안 호출자 세션의 읽기 트랜잭션도 열어두지 않는다."""
    await db.commit()


def _is_live_order_blocking(result: LiveOrderResult) -> bool:
    return (
        result.submission_status in LIVE_ORDER_BLOCKING_SUBMISSION_STATUSES
        or result.error_code == "BLOCKING_INTENT"
    )


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


def _parse_bool_config(raw_value: str | None, *, default: bool) -> bool:
    normalized = str(raw_value or "").strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _find_portfolio_item(portfolio: PortfolioSummary, currency: str) -> AssetItem | None:
    normalized_currency = str(currency or "").strip().upper()
    for item in portfolio.items:
        if item.currency.upper() == normalized_currency:
            return item
    return None


def _available_amount(item: AssetItem | None) -> float:
    if item is None:
        return 0.0
    return max(_to_float(item.balance), 0.0)


def _resolve_weighted_amount(total_amount: float, recommended_weight: int | float) -> float:
    weight_ratio = max(0.0, min(float(recommended_weight), 100.0)) / 100.0
    return total_amount * weight_ratio


def _resolve_effective_buy_weight(
    primary_recommended_weight: int | float,
    precheck_recommended_weight: int | float,
    hard_cap_weight: int | float,
) -> float:
    try:
        weights = tuple(
            float(value)
            for value in (
                primary_recommended_weight,
                precheck_recommended_weight,
                hard_cap_weight,
            )
        )
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not all(math.isfinite(weight) for weight in weights):
        return 0.0
    return max(0.0, min(100.0, *weights))


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


async def _load_ai_max_buy_weight_pct(db: AsyncSession) -> float:
    raw_value = await get_system_config_value(
        db,
        AI_MAX_BUY_WEIGHT_PCT_KEY,
        default=str(DEFAULT_AI_MAX_BUY_WEIGHT_PCT),
    )
    return _parse_float_config(
        raw_value,
        default=DEFAULT_AI_MAX_BUY_WEIGHT_PCT,
        minimum=0.0,
        maximum=30.0,
    )


async def _load_live_buy_enabled(db: AsyncSession) -> bool:
    raw_value = await get_system_config_value(
        db,
        LIVE_BUY_ENABLED_KEY,
        default=str(DEFAULT_LIVE_BUY_ENABLED).lower(),
    )
    return _parse_bool_config(raw_value, default=DEFAULT_LIVE_BUY_ENABLED)


async def _load_buy_precheck_news_refresh_config(db: AsyncSession) -> tuple[bool, int]:
    enabled_raw = await get_system_config_value(
        db,
        RAG_BUY_PRECHECK_NEWS_REFRESH_ENABLED_KEY,
        default=str(DEFAULT_BUY_PRECHECK_NEWS_REFRESH_ENABLED).lower(),
    )
    max_age_raw = await get_system_config_value(
        db,
        RAG_BUY_PRECHECK_NEWS_MAX_AGE_MINUTES_KEY,
        default=str(DEFAULT_BUY_PRECHECK_NEWS_MAX_AGE_MINUTES),
    )
    return (
        _parse_bool_config(
            enabled_raw,
            default=DEFAULT_BUY_PRECHECK_NEWS_REFRESH_ENABLED,
        ),
        _parse_int_config(
            max_age_raw,
            default=DEFAULT_BUY_PRECHECK_NEWS_MAX_AGE_MINUTES,
            minimum=1,
            maximum=24 * 60,
        ),
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

    hard_take_profit_pct = _finite_float(take_profit_raw)
    hard_stop_loss_pct = _finite_float(stop_loss_raw)
    if (
        hard_take_profit_pct is None
        or hard_take_profit_pct < 0
        or hard_take_profit_pct > 1000
    ):
        raise ValueError("hard_take_profit_pct 설정이 유효하지 않습니다.")
    if (
        hard_stop_loss_pct is None
        or hard_stop_loss_pct < -1000
        or hard_stop_loss_pct > 0
    ):
        raise ValueError("hard_stop_loss_pct 설정이 유효하지 않습니다.")
    return hard_take_profit_pct, hard_stop_loss_pct


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _hard_risk_thresholds_are_valid(
    hard_take_profit_pct: float,
    hard_stop_loss_pct: float,
) -> bool:
    return (
        math.isfinite(hard_take_profit_pct)
        and math.isfinite(hard_stop_loss_pct)
        and 0 <= hard_take_profit_pct <= 1000
        and -1000 <= hard_stop_loss_pct <= 0
    )


def _assess_hard_tp_sl_portfolio(
    portfolio: PortfolioSummary,
    *,
    hard_take_profit_pct: float,
    hard_stop_loss_pct: float,
) -> _HardRiskAssessment:
    if not _hard_risk_thresholds_are_valid(
        hard_take_profit_pct,
        hard_stop_loss_pct,
    ):
        return _HardRiskAssessment(
            result=RiskCheckResult(
                status=RiskCheckStatus.UNKNOWN,
                reasons=("INVALID_RISK_THRESHOLD",),
            ),
        )

    tp_enabled = hard_take_profit_pct > 0
    sl_enabled = hard_stop_loss_pct < 0
    if not tp_enabled and not sl_enabled:
        return _HardRiskAssessment(
            result=RiskCheckResult(status=RiskCheckStatus.DISABLED),
        )

    if portfolio.error is not None:
        return _HardRiskAssessment(
            result=RiskCheckResult(
                status=RiskCheckStatus.UNKNOWN,
                reasons=(f"PORTFOLIO_ERROR:{portfolio.error}",),
            ),
        )
    if portfolio.is_stale:
        return _HardRiskAssessment(
            result=RiskCheckResult(
                status=RiskCheckStatus.UNKNOWN,
                reasons=("PORTFOLIO_STALE",),
            ),
        )

    unknown_reasons: list[str] = []
    triggers: list[_HardRiskTrigger] = []
    for item in portfolio.items:
        currency = str(item.currency or "").strip().upper()
        balance = _finite_float(item.balance)
        locked = _finite_float(item.locked)
        if balance is None or locked is None or balance < 0 or locked < 0:
            unknown_reasons.append(f"INVALID_BALANCE:{currency or 'UNKNOWN'}")
            continue

        exposure = balance + locked
        if exposure <= 0 or currency == "KRW":
            continue
        if not currency:
            unknown_reasons.append("MISSING_CURRENCY")
            continue

        current_price = _finite_float(item.current_price)
        avg_buy_price = _finite_float(item.avg_buy_price)
        pnl_percentage = _finite_float(item.pnl_percentage)
        if current_price is None or current_price <= 0:
            unknown_reasons.append(f"INVALID_CURRENT_PRICE:{currency}")
            continue
        if avg_buy_price is None or avg_buy_price <= 0:
            unknown_reasons.append(f"INVALID_AVG_BUY_PRICE:{currency}")
            continue
        if pnl_percentage is None:
            unknown_reasons.append(f"INVALID_PNL:{currency}")
            continue

        trigger_reason: str | None = None
        if tp_enabled and pnl_percentage >= hard_take_profit_pct:
            trigger_reason = ORDER_REASON_TP_SELL
        elif sl_enabled and pnl_percentage <= hard_stop_loss_pct:
            trigger_reason = ORDER_REASON_SL_SELL
        if trigger_reason is not None:
            triggers.append(
                _HardRiskTrigger(
                    symbol=_normalize_symbol(f"KRW-{currency}"),
                    item=item,
                    order_reason=trigger_reason,
                )
            )

    trigger_reasons = [
        f"THRESHOLD_TRIGGERED:{trigger.symbol}:{trigger.order_reason}"
        for trigger in triggers
    ]
    if unknown_reasons:
        status = RiskCheckStatus.UNKNOWN
    elif triggers:
        status = RiskCheckStatus.UNHEALTHY
    else:
        status = RiskCheckStatus.HEALTHY

    return _HardRiskAssessment(
        result=RiskCheckResult(
            status=status,
            affected_symbols=frozenset(trigger.symbol for trigger in triggers),
            reasons=tuple(dict.fromkeys([*unknown_reasons, *trigger_reasons])),
        ),
        triggers=tuple(triggers),
    )


async def evaluate_new_buy_risk_health(db: AsyncSession) -> RiskCheckResult:
    """부작용 없이 현재 cycle의 신규 BUY 허용 여부를 평가합니다."""

    try:
        hard_take_profit_pct, hard_stop_loss_pct = await _load_hard_tp_sl_thresholds(db)
    except Exception as exc:
        logger.error("신규 BUY 리스크 임계값 조회 실패: %s", exc, exc_info=True)
        return RiskCheckResult(
            status=RiskCheckStatus.UNKNOWN,
            reasons=("RISK_THRESHOLD_LOAD_FAILED",),
        )

    if not _hard_risk_thresholds_are_valid(
        hard_take_profit_pct,
        hard_stop_loss_pct,
    ):
        return RiskCheckResult(
            status=RiskCheckStatus.UNKNOWN,
            reasons=("INVALID_RISK_THRESHOLD",),
        )

    if hard_take_profit_pct == 0 and hard_stop_loss_pct == 0:
        return RiskCheckResult(status=RiskCheckStatus.DISABLED)

    try:
        portfolio = await PortfolioService(db).get_aggregated_portfolio()
    except Exception as exc:
        logger.error("신규 BUY 리스크 포트폴리오 조회 실패: %s", exc, exc_info=True)
        return RiskCheckResult(
            status=RiskCheckStatus.UNKNOWN,
            reasons=("PORTFOLIO_LOOKUP_FAILED",),
        )

    return _assess_hard_tp_sl_portfolio(
        portfolio,
        hard_take_profit_pct=hard_take_profit_pct,
        hard_stop_loss_pct=hard_stop_loss_pct,
    ).result


async def _load_analysis_by_id(db: AsyncSession, analysis_id: int) -> AIAnalysisLog | None:
    result = await db.execute(
        select(AIAnalysisLog)
        .where(AIAnalysisLog.id == analysis_id)
        .where(AIAnalysisLog.stage == AI_ANALYSIS_STAGE_TRADE)
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


def _resolve_trade_fill(order_result: dict[str, Any]) -> tuple[float, float]:
    trades = order_result.get("trades")
    if not isinstance(trades, list):
        return 0.0, 0.0

    total_qty = 0.0
    total_funds = 0.0
    for trade in trades:
        if not isinstance(trade, dict):
            continue

        qty = _to_float(trade.get("volume"))
        if qty <= 0:
            continue

        funds = _to_float(trade.get("funds"))
        if funds <= 0:
            price = _to_float(trade.get("price"))
            funds = price * qty if price > 0 else 0.0
        if funds <= 0:
            continue

        total_qty += qty
        total_funds += funds

    if total_qty <= 0 or total_funds <= 0:
        return 0.0, 0.0
    return total_funds / total_qty, total_qty


def _is_quote_amount_bid(order_result: dict[str, Any], side: str | None) -> bool:
    normalized_side = str(order_result.get("side") or side or "").strip().lower()
    normalized_order_type = str(order_result.get("ord_type") or "").strip().lower()
    return normalized_side in {"bid", "buy"} and normalized_order_type == "price"


def _resolve_order_price(
    order_result: dict[str, Any],
    fallback_price: float,
    *,
    side: str | None = None,
) -> float:
    trade_price, _trade_qty = _resolve_trade_fill(order_result)
    if trade_price > 0:
        return trade_price

    for key in ("avg_price", "trade_price"):
        price = _to_float(order_result.get(key))
        if price > 0:
            return price

    if not _is_quote_amount_bid(order_result, side):
        price = _to_float(order_result.get("price"))
        if price > 0:
            return price

    return fallback_price


def _resolve_order_qty(order_result: dict[str, Any], fallback_qty: float) -> float:
    _trade_price, trade_qty = _resolve_trade_fill(order_result)
    if trade_qty > 0:
        return trade_qty

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


async def _get_existing_position(
    db: AsyncSession,
    asset_id: int,
    *,
    is_paper: bool,
) -> Position | None:
    result = await db.execute(
        select(Position)
        .where(Position.asset_id == asset_id, Position.is_paper.is_(is_paper))
        .order_by(Position.id.asc())
    )
    return result.scalars().first()


async def _get_or_create_paper_cash_config(db: AsyncSession) -> SystemConfig:
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.config_key == PAPER_TRADING_KRW_BALANCE_KEY)
    )
    config = result.scalar_one_or_none()
    if config is not None:
        return config

    config = SystemConfig(
        config_key=PAPER_TRADING_KRW_BALANCE_KEY,
        config_value=_fmt_number(DEFAULT_PAPER_KRW_BALANCE),
        description=PAPER_BALANCE_DESCRIPTION,
    )
    db.add(config)
    await db.flush()
    return config


# paper 체결 전용 이력 기록. live 주문 이력은 OrderIntent reconciliation의
# 정확히 한 번 projection(app/db/order_intent_repository.py)만 기록한다.
async def _record_paper_order_history(
    *,
    db: AsyncSession,
    symbol: str,
    analysis: AIAnalysisLog | None,
    side: str,
    order_result: dict[str, Any],
    fallback_price: float,
    fallback_qty: float,
    order_reason: str | None = None,
) -> bool:
    resolved_price = _resolve_order_price(order_result, fallback_price, side=side)
    resolved_qty = _resolve_order_qty(order_result, fallback_qty)
    if resolved_price <= 0 or resolved_qty <= 0:
        logger.warning(
            "AI paper 주문 이력 기록 스킵: 체결 가격/수량을 확정할 수 없습니다. symbol=%s side=%s price=%s qty=%s",
            symbol,
            side,
            resolved_price,
            resolved_qty,
        )
        return False

    executed_at = _parse_datetime(order_result.get("created_at")) or datetime.now(UTC)

    try:
        asset = await _get_or_create_asset(db, symbol)
        position = await _get_or_create_position(db, asset.id, resolved_price, is_paper=True)
        db.add(
            OrderHistory(
                position_id=position.id,
                ai_analysis_log_id=analysis.id if analysis is not None else None,
                side=side,
                order_reason=order_reason,
                is_paper=True,
                price=resolved_price,
                qty=resolved_qty,
                broker=PAPER_BROKER_NAME,
                executed_at=executed_at,
            )
        )
        await db.commit()
        return True
    except Exception as exc:
        await db.rollback()
        logger.warning(
            "AI paper 주문 이력 기록 실패: symbol=%s side=%s error=%s", symbol, side, exc, exc_info=True
        )
        return False


async def _send_trade_notification(
    *,
    symbol: str,
    decision: str,
    confidence: int,
    recommended_weight: int,
    order_result: dict[str, Any],
    trading_mode: str,
) -> None:
    if trading_mode == "paper":
        return

    order_uuid = str(order_result.get("uuid") or "").strip()
    lines = [
        f"[AI 자율 체결 알림] {symbol} 시장가 {decision} (확신도: {confidence}%, 추천 비중: {recommended_weight}%)",
    ]
    if order_uuid:
        lines.append(f"주문 UUID: {order_uuid}")

    try:
        await asyncio.to_thread(slack_bot.send_message, "\n".join(lines))
    except Exception as exc:
        logger.warning("Slack 자율 체결 알림 전송 실패: %s", exc, exc_info=True)


async def _send_live_order_accepted_notification(
    *,
    symbol: str,
    decision: str,
    confidence: int,
    recommended_weight: int,
    result: LiveOrderResult,
) -> None:
    lines = [
        (
            f"[AI 자율 주문 접수 알림] {symbol} 시장가 {decision} "
            f"(확신도: {confidence}%, 추천 비중: {recommended_weight}%)"
        ),
        f"주문 의도 ID: {result.intent_id}",
    ]
    if result.exchange_uuid:
        lines.append(f"주문 UUID: {result.exchange_uuid}")

    try:
        await asyncio.to_thread(slack_bot.send_message, "\n".join(lines))
    except Exception as exc:
        logger.warning("Slack 자율 주문 접수 알림 전송 실패: %s", exc, exc_info=True)


async def execute_hard_tp_sl_check(db: AsyncSession) -> RiskCheckResult:
    hard_take_profit_pct, hard_stop_loss_pct = await _load_hard_tp_sl_thresholds(db)
    if not _hard_risk_thresholds_are_valid(
        hard_take_profit_pct,
        hard_stop_loss_pct,
    ):
        return RiskCheckResult(
            status=RiskCheckStatus.UNKNOWN,
            reasons=("INVALID_RISK_THRESHOLD",),
        )
    tp_enabled = hard_take_profit_pct > 0
    sl_enabled = hard_stop_loss_pct < 0

    if not tp_enabled and not sl_enabled:
        logger.info("하드 TP/SL 체크 우회: TP/SL 임계값이 모두 비활성화되었습니다.")
        return RiskCheckResult(status=RiskCheckStatus.DISABLED)

    try:
        portfolio = await PortfolioService(db).get_aggregated_portfolio()
    except Exception as exc:
        logger.error("하드 TP/SL 포트폴리오 조회 실패: %s", exc, exc_info=True)
        return RiskCheckResult(
            status=RiskCheckStatus.UNKNOWN,
            reasons=("PORTFOLIO_LOOKUP_FAILED",),
        )

    assessment = _assess_hard_tp_sl_portfolio(
        portfolio,
        hard_take_profit_pct=hard_take_profit_pct,
        hard_stop_loss_pct=hard_stop_loss_pct,
    )
    if not assessment.triggers:
        if assessment.result.status is RiskCheckStatus.UNKNOWN:
            logger.warning(
                "하드 TP/SL 상태 미확정: reasons=%s",
                assessment.result.reasons,
            )
        return assessment.result

    trading_mode = await get_trading_mode(db)
    live_order_service = (
        _build_live_order_execution_service() if trading_mode == "live" else None
    )
    liquidated_symbols: set[str] = set()

    for trigger in assessment.triggers:
        item = trigger.item
        available_qty = _available_amount(item)
        if available_qty <= 0:
            logger.warning(
                "하드 TP/SL 매도 가능 수량 없음: symbol=%s reason=%s",
                trigger.symbol,
                trigger.order_reason,
            )
            continue

        pnl_percentage = _to_float(item.pnl_percentage)
        trigger_reason = trigger.order_reason
        symbol = trigger.symbol
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
            try:
                cash_config = await _get_or_create_paper_cash_config(db)
                current_paper_balance = _to_float(cash_config.config_value)
                if current_paper_balance < 0:
                    current_paper_balance = DEFAULT_PAPER_KRW_BALANCE

                asset = await _get_or_create_asset(db, symbol)
                position = await _get_existing_position(db, asset.id, is_paper=True)
                position_qty = max(_to_float(position.quantity) if position is not None else 0.0, 0.0)
                if position is None or position_qty <= 0:
                    logger.info(
                        "하드 TP/SL paper 매도 스킵: paper 포지션이 없습니다. symbol=%s reason=%s",
                        symbol,
                        trigger_reason,
                    )
                    continue

                realized_sell_qty = position_qty
                if realized_sell_qty <= 0:
                    logger.info(
                        "하드 TP/SL paper 매도 스킵: 청산 수량이 0 이하입니다. symbol=%s reason=%s",
                        symbol,
                        trigger_reason,
                    )
                    continue

                recovered_krw = realized_sell_qty * current_price * 0.9995
                remaining_qty = max(position_qty - realized_sell_qty, 0.0)
                position.quantity = 0.0 if remaining_qty <= PAPER_BALANCE_EPSILON else remaining_qty
                position.status = "closed"
                cash_config.config_value = _fmt_number(current_paper_balance + recovered_krw)
                cash_config.version = int(cash_config.version or 0) + 1
                executed_at = datetime.now(UTC)
                order_result = build_paper_order_result(
                    market=symbol,
                    side="ask",
                    ord_type="market",
                    executed_price=current_price,
                    executed_qty=realized_sell_qty,
                    executed_at=executed_at,
                )

                history_recorded = await _record_paper_order_history(
                    db=db,
                    symbol=symbol,
                    analysis=None,
                    side="sell",
                    order_result=order_result,
                    fallback_price=current_price,
                    fallback_qty=realized_sell_qty,
                    order_reason=trigger_reason,
                )
                if not history_recorded:
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
                await _close_caller_transaction_before_live_order(db)
                live_result = await live_order_service.execute(
                    LiveOrderRequest(
                        source_type="HARD_RISK_EXIT",
                        source_ref=f"risk_exit:{uuid4().hex}",
                        market=symbol,
                        side="ask",
                        ord_type="market",
                        price=None,
                        volume=Decimal(_fmt_number(available_qty)),
                        ai_analysis_log_id=None,
                        liquidation_operation_id=None,
                        reason=trigger_reason,
                        execution_policy="GENERAL",
                    )
                )
            except Exception as exc:
                logger.error(
                    "하드 TP/SL 중앙 주문 접수 중 예기치 못한 오류: symbol=%s reason=%s error=%s",
                    symbol,
                    trigger_reason,
                    exc,
                    exc_info=True,
                )
                continue

            if _is_live_order_blocking(live_result):
                liquidated_symbols.add(symbol)
                if (
                    live_result.submission_status == "ACCEPTED"
                    and live_result.error_code != "BLOCKING_INTENT"
                    and not live_result.replayed
                ):
                    logger.info(
                        "하드 TP/SL 실주문 접수 성공: symbol=%s reason=%s intent_id=%s uuid=%s",
                        symbol,
                        trigger_reason,
                        live_result.intent_id,
                        live_result.exchange_uuid,
                    )
                else:
                    logger.warning(
                        "하드 TP/SL 실주문 확인 중: symbol=%s reason=%s intent_id=%s status=%s error_code=%s",
                        symbol,
                        trigger_reason,
                        live_result.intent_id,
                        live_result.submission_status,
                        live_result.error_code,
                    )
            else:
                logger.warning(
                    "하드 TP/SL 실주문 거절 또는 종결: symbol=%s reason=%s status=%s error_code=%s error=%s",
                    symbol,
                    trigger_reason,
                    live_result.submission_status,
                    live_result.error_code,
                    live_result.error_message,
                )
            continue

        liquidated_symbols.add(symbol)
        logger.info(
            "하드 TP/SL paper 매도 체결 성공: symbol=%s reason=%s pnl_percentage=%s qty=%s uuid=%s",
            symbol,
            trigger_reason,
            pnl_percentage,
            available_qty,
            order_result.get("uuid"),
        )

    return RiskCheckResult(
        status=assessment.result.status,
        liquidated_symbols=frozenset(liquidated_symbols),
        affected_symbols=assessment.result.affected_symbols,
        reasons=assessment.result.reasons,
    )


def _truncate_prompt_text(value: Any, max_chars: int = 900) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def _truncate_buy_precheck_news_summary(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) <= BUY_PRECHECK_NEWS_SUMMARY_MAX_CHARS:
        return text
    return f"{text[: BUY_PRECHECK_NEWS_SUMMARY_MAX_CHARS - 3].rstrip()}..."


def _build_buy_precheck_news_context(payload: Any) -> dict[str, Any]:
    raw_payload = payload if isinstance(payload, dict) else {}
    raw_items = raw_payload.get("items")
    items: list[dict[str, str | None]] = []
    if isinstance(raw_items, list):
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            title = str(raw_item.get("title") or "").strip() or None
            summary = _truncate_buy_precheck_news_summary(
                raw_item.get("summary") or raw_item.get("title")
            )
            items.append(
                {
                    "title": title,
                    "summary": summary,
                    "source": str(raw_item.get("source") or "").strip() or None,
                    "published_at": str(raw_item.get("published_at") or "").strip()
                    or None,
                    "link": str(raw_item.get("link") or "").strip() or None,
                }
            )
            if len(items) >= BUY_PRECHECK_NEWS_ITEM_LIMIT:
                break

    error = str(raw_payload.get("error") or "").strip() or None
    return {
        "items": items,
        "error": error[:240] if error is not None else None,
    }


async def _load_buy_precheck_news_context(symbol: str) -> dict[str, Any]:
    from app.services.trading.ai_analyst import search_news_for_buy_precheck

    return await search_news_for_buy_precheck(symbol)


def _build_buy_precheck_system_prompt() -> str:
    return (
        "당신은 AI-Trade-Manager의 실거래 BUY 직전 2차 검증 Reviewer입니다. "
        "이미 1차 AI 분석, Entry Gate, shadow/live 안전락을 통과한 BUY 후보만 검토합니다. "
        "제공된 데이터만 근거로 삼고, 정보가 부족하거나 안전 정책상 애매하면 HOLD를 선택하세요. "
        "BUY는 기술/심리/뉴스/RAG/포트폴리오 위험이 모두 납득될 때만 유지합니다. "
        "뉴스가 없거나 조회에 실패했다는 이유만으로 자동 HOLD/SELL하지 말고 다른 제공 데이터로 판단하세요. "
        "2차 검증은 1차 recommended_weight를 늘릴 수 없으며 BUY를 차단하거나 비중을 낮추기만 합니다. "
        "반드시 JSON 스키마에 맞춰 decision, confidence, recommended_weight, reasoning을 반환하세요."
    )


def _build_buy_precheck_user_prompt(
    *,
    symbol: str,
    analysis: AIAnalysisLog,
    entry_gate: EntryGateResult,
    portfolio: PortfolioSummary,
    trading_mode: str,
    min_confidence: int,
    news_refresh_status: dict[str, Any] | None = None,
    news_context: dict[str, Any] | None = None,
) -> str:
    target_currency = _extract_target_currency(symbol)
    target_item = _find_portfolio_item(portfolio, target_currency)
    cash_item = _find_portfolio_item(portfolio, _extract_quote_currency(symbol))
    payload = {
        "검증_목적": "BUY 직전 2차 검증",
        "종목": symbol,
        "거래_모드": trading_mode,
        "최소_체결_확신도": min_confidence,
        "1차_AI_판단": {
            "decision": analysis.decision,
            "confidence": analysis.confidence,
            "recommended_weight": analysis.recommended_weight,
            "reasoning": _truncate_prompt_text(analysis.reasoning, 1200),
            "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        },
        "entry_gate": entry_gate.to_log_dict(),
        "buy_precheck_news_refresh": news_refresh_status
        or {"enabled": False, "reason": "disabled"},
        "buy_precheck_news_context": _build_buy_precheck_news_context(news_context),
        "portfolio": {
            "total_net_worth": portfolio.total_net_worth,
            "total_pnl": portfolio.total_pnl,
            "source": portfolio.source,
            "is_stale": portfolio.is_stale,
            "updated_at": portfolio.updated_at,
            "cash": cash_item.model_dump() if cash_item is not None else None,
            "target_position": target_item.model_dump() if target_item is not None else None,
        },
        "판정_규칙": [
            "BUY 유지 시 confidence는 최소 체결 확신도 이상이어야 합니다.",
            "recommended_weight는 1 이상이어야 하며 1차 AI recommended_weight를 초과할 수 없습니다.",
            "근거가 부족하거나 provider/fallback/데이터 지연 위험이 크면 HOLD를 반환하세요.",
            "뉴스가 비어 있거나 조회 오류가 있어도 그 사실만으로 BUY를 자동 거절하지 않습니다.",
            "SELL은 신규 BUY 후보를 명확히 거절해야 할 때만 사용하고, 일반 보류는 HOLD를 사용하세요.",
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )


async def _persist_buy_precheck_log(
    db: AsyncSession,
    *,
    symbol: str,
    analysis: AIAnalysisResponse,
    parent_analysis_id: int,
    provider: str,
    model: str,
    fallback_used: bool,
    context_sha256: str,
) -> AIAnalysisLog:
    reasoning = str(analysis.reasoning or "").strip()
    if not reasoning.startswith("[BUY 직전 검증]"):
        reasoning = f"[BUY 직전 검증] {reasoning}"

    log = AIAnalysisLog(
        symbol=_normalize_symbol(symbol),
        decision=analysis.decision,
        confidence=analysis.confidence,
        recommended_weight=analysis.recommended_weight,
        reasoning=reasoning,
        stage=AI_ANALYSIS_STAGE_BUY_PRECHECK,
        provider=provider,
        model=model,
        fallback_used=fallback_used,
        parent_analysis_id=parent_analysis_id,
        prompt_version=BUY_PRECHECK_PROMPT_VERSION,
        context_sha256=context_sha256,
    )
    try:
        db.add(log)
        await db.commit()
        await db.refresh(log)
        if log.id is None:
            raise RuntimeError("저장된 BUY precheck 로그 ID를 확인할 수 없습니다.")
    except Exception:
        await db.rollback()
        raise
    return log


async def _persist_buy_precheck_hold(
    db: AsyncSession,
    *,
    symbol: str,
    reason: str,
    parent_analysis_id: int,
    context_sha256: str,
) -> AIAnalysisLog:
    return await _persist_buy_precheck_log(
        db,
        symbol=symbol,
        analysis=AIAnalysisResponse(
            decision="HOLD",
            confidence=0,
            recommended_weight=0,
            reasoning=reason,
        ),
        parent_analysis_id=parent_analysis_id,
        provider=AI_ANALYSIS_SYSTEM_PROVIDER,
        model=AI_ANALYSIS_DETERMINISTIC_HOLD_MODEL,
        fallback_used=True,
        context_sha256=context_sha256,
    )


def _is_buy_precheck_approved(analysis: AIAnalysisResponse, min_confidence: int) -> bool:
    return (
        analysis.decision == "BUY"
        and analysis.confidence >= min_confidence
        and analysis.recommended_weight > 0
    )


async def _run_buy_precheck(
    *,
    db: AsyncSession,
    symbol: str,
    analysis: AIAnalysisLog,
    entry_gate: EntryGateResult,
    portfolio: PortfolioSummary,
    trading_mode: str,
    min_confidence: int,
) -> AIAnalysisLog | None:
    parent_analysis_id = analysis.id
    if parent_analysis_id is None:
        logger.error("BUY precheck 차단: primary analysis ID가 없습니다. symbol=%s", symbol)
        return None

    news_refresh_status: dict[str, Any] = {"enabled": False, "reason": "disabled"}
    try:
        refresh_enabled, max_age_minutes = await _load_buy_precheck_news_refresh_config(db)
        if refresh_enabled:
            from app.services.rag.ingestion import refresh_market_news_for_buy_precheck_if_stale

            news_refresh_status = await refresh_market_news_for_buy_precheck_if_stale(
                max_age_minutes=max_age_minutes,
            )
    except Exception as exc:
        logger.warning(
            "BUY precheck news refresh context failed: symbol=%s error=%s",
            symbol,
            exc,
            exc_info=True,
        )
        news_refresh_status = {
            "enabled": True,
            "refreshed": False,
            "reason": "refresh_context_failed",
            "error": str(exc)[:240],
        }

    try:
        news_context = await _load_buy_precheck_news_context(symbol)
    except Exception as exc:
        logger.warning(
            "BUY precheck 뉴스 컨텍스트 조회 실패: symbol=%s error=%s",
            symbol,
            exc,
            exc_info=True,
        )
        news_context = {"items": [], "error": "NEWS_SEARCH_FAILED"}

    system_prompt = _build_buy_precheck_system_prompt()
    user_prompt = _build_buy_precheck_user_prompt(
        symbol=symbol,
        analysis=analysis,
        entry_gate=entry_gate,
        portfolio=portfolio,
        trading_mode=trading_mode,
        min_confidence=min_confidence,
        news_refresh_status=news_refresh_status,
        news_context=news_context,
    )
    context_sha256 = hash_analysis_context(user_prompt)

    try:
        routed_result = await AIProviderRouter(db).generate_structured_analysis(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=AIAnalysisResponse,
            preferred_provider="openai",
            purpose="buy_precheck",
            allow_fallback=False,
        )
    except AIProviderUnavailableError as exc:
        logger.warning(
            "BUY 직전 2차 검증 provider 사용 불가로 매수를 차단합니다. symbol=%s error=%s",
            symbol,
            exc,
        )
        await _persist_buy_precheck_hold(
            db,
            symbol=symbol,
            reason=f"OpenAI BUY 직전 검증을 완료하지 못해 매수를 차단했습니다. 원인: {exc}",
            parent_analysis_id=parent_analysis_id,
            context_sha256=context_sha256,
        )
        return None
    except Exception as exc:
        logger.warning(
            "BUY 직전 2차 검증 실패로 매수를 차단합니다. symbol=%s error=%s",
            symbol,
            exc,
            exc_info=True,
        )
        await _persist_buy_precheck_hold(
            db,
            symbol=symbol,
            reason=f"BUY 직전 검증 중 예외가 발생해 매수를 차단했습니다. 원인: {exc}",
            parent_analysis_id=parent_analysis_id,
            context_sha256=context_sha256,
        )
        return None

    precheck = routed_result.value
    if not _is_buy_precheck_approved(precheck, min_confidence):
        logger.info(
            "BUY 직전 2차 검증이 주문 기준을 통과하지 못해 매수를 차단합니다. symbol=%s decision=%s confidence=%s min_confidence=%s weight=%s provider=%s model=%s",
            symbol,
            precheck.decision,
            precheck.confidence,
            min_confidence,
            precheck.recommended_weight,
            routed_result.provider,
            routed_result.model,
        )
        await _persist_buy_precheck_log(
            db,
            symbol=symbol,
            analysis=precheck,
            parent_analysis_id=parent_analysis_id,
            provider=routed_result.provider,
            model=routed_result.model,
            fallback_used=routed_result.fallback_used,
            context_sha256=context_sha256,
        )
        return None

    precheck_log = await _persist_buy_precheck_log(
        db,
        symbol=symbol,
        analysis=precheck,
        parent_analysis_id=parent_analysis_id,
        provider=routed_result.provider,
        model=routed_result.model,
        fallback_used=routed_result.fallback_used,
        context_sha256=context_sha256,
    )
    logger.info(
        "BUY 직전 2차 검증 통과: symbol=%s provider=%s model=%s confidence=%s weight=%s",
        symbol,
        routed_result.provider,
        routed_result.model,
        precheck.confidence,
        precheck.recommended_weight,
    )
    return precheck_log


async def _execute_buy_trade(
    *,
    db: AsyncSession,
    symbol: str,
    analysis: AIAnalysisLog,
    primary_recommended_weight: int | float,
    portfolio: PortfolioSummary,
    trading_mode: str,
) -> LiveOrderResult | None:
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
    max_buy_weight_pct = await _load_ai_max_buy_weight_pct(db)
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

    effective_recommended_weight = _resolve_effective_buy_weight(
        primary_recommended_weight,
        analysis.recommended_weight,
        max_buy_weight_pct,
    )
    ai_recommended_budget = _resolve_weighted_amount(total_krw, effective_recommended_weight)
    target_budget = min(remaining_budget, ai_recommended_budget)
    if effective_recommended_weight < float(analysis.recommended_weight):
        logger.info(
            "AI 매수 reduce-only 비중 적용: symbol=%s primary_weight=%s precheck_weight=%s hard_cap=%s effective_weight=%s",
            symbol,
            primary_recommended_weight,
            analysis.recommended_weight,
            max_buy_weight_pct,
            effective_recommended_weight,
        )
    if target_budget <= 0:
        logger.info(
            "AI 매수 스킵: 계산된 목표 예산이 0 이하입니다. symbol=%s target_budget=%s remaining_budget=%s",
            symbol,
            target_budget,
            remaining_budget,
        )
        return

    fee_buffer = 0.995  # 0.5% 여유분 (업비트 수수료 0.05% 대비 충분한 버퍼)
    if remaining_budget < MIN_ORDER_KRW:
        logger.info(
            "AI 매수 스킵: 남은 종목 비중 예산이 최소 주문 금액보다 작습니다. symbol=%s remaining_budget=%s min_order=%s",
            symbol,
            remaining_budget,
            MIN_ORDER_KRW,
        )
        return

    if available_krw < MIN_ORDER_KRW:
        logger.info(
            "AI 매수 스킵: 가용 KRW가 최소 주문 금액보다 작습니다. symbol=%s available_krw=%s min_order=%s",
            symbol,
            available_krw,
            MIN_ORDER_KRW,
        )
        return

    if trading_mode == "live" and target_budget < MIN_ORDER_KRW:
        logger.info(
            "AI live 매수 스킵: reduce-only 목표 예산이 최소 주문 금액보다 작습니다. symbol=%s target_budget=%s min_order=%s",
            symbol,
            target_budget,
            MIN_ORDER_KRW,
        )
        return

    order_amount_krw = target_budget * fee_buffer
    if order_amount_krw < MIN_ORDER_KRW:
        order_amount_krw = MIN_ORDER_KRW

    if order_amount_krw > remaining_budget:
        logger.info(
            "AI 매수 스킵: 주문 금액이 남은 종목 비중 예산을 초과합니다. symbol=%s remaining_budget=%s order_amount=%s target_budget=%s",
            symbol,
            remaining_budget,
            order_amount_krw,
            target_budget,
        )
        return

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
        broker = BrokerFactory.get_broker("UPBIT")
        try:
            tickers = await broker.get_ticker([symbol])
        except (ValueError, UpbitAPIError) as exc:
            logger.warning("AI paper 매수 스킵: 현재가 조회 실패 symbol=%s error=%s", symbol, exc, exc_info=True)
            return
        except Exception as exc:
            logger.error("AI paper 매수 현재가 조회 중 예기치 못한 오류: symbol=%s error=%s", symbol, exc, exc_info=True)
            return

        executed_price = _to_float(tickers[0].get("trade_price")) if tickers else 0.0
        if executed_price <= 0:
            logger.info("AI paper 매수 스킵: 현재가가 유효하지 않습니다. symbol=%s", symbol)
            return

        executed_qty = (order_amount_krw / executed_price) * 0.9995
        if executed_qty <= 0:
            logger.info("AI paper 매수 스킵: 계산된 체결 수량이 0 이하입니다. symbol=%s", symbol)
            return

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
            cash_config = await _get_or_create_paper_cash_config(db)
            current_paper_balance = _to_float(cash_config.config_value)
            if current_paper_balance < 0:
                current_paper_balance = DEFAULT_PAPER_KRW_BALANCE

            if order_amount_krw > current_paper_balance:
                logger.info(
                    "AI paper 매수 스킵: 가상 KRW 잔고보다 주문 금액이 큽니다. symbol=%s paper_balance=%s order_amount=%s",
                    symbol,
                    current_paper_balance,
                    order_amount_krw,
                )
                return

            asset = await _get_or_create_asset(db, symbol)
            position = await _get_or_create_position(
                db,
                asset.id,
                executed_price,
                is_paper=True,
            )
            previous_qty = max(_to_float(position.quantity), 0.0)
            previous_cost = previous_qty * max(_to_float(position.avg_entry_price), 0.0)
            new_qty = previous_qty + executed_qty
            total_cost = previous_cost + order_amount_krw

            position.avg_entry_price = total_cost / new_qty if new_qty > 0 else executed_price
            position.quantity = new_qty
            position.status = "open"
            cash_config.config_value = _fmt_number(max(current_paper_balance - order_amount_krw, 0.0))
            cash_config.version = int(cash_config.version or 0) + 1

            history_recorded = await _record_paper_order_history(
                db=db,
                symbol=symbol,
                analysis=analysis,
                side="buy",
                order_result=order_result,
                fallback_price=executed_price,
                fallback_qty=executed_qty,
            )
            if not history_recorded:
                return
        except Exception as exc:
            await db.rollback()
            logger.error("AI paper 매수 적용 중 예기치 못한 오류: symbol=%s error=%s", symbol, exc, exc_info=True)
            return
    else:
        try:
            await _close_caller_transaction_before_live_order(db)
            live_result = await _build_live_order_execution_service().execute(
                LiveOrderRequest(
                    source_type="AI_ANALYSIS",
                    source_ref=f"analysis:{analysis.id}:{symbol}:bid",
                    market=symbol,
                    side="bid",
                    ord_type="price",
                    price=Decimal(_fmt_number(order_amount_krw)),
                    volume=None,
                    ai_analysis_log_id=analysis.id,
                    liquidation_operation_id=None,
                    reason=None,
                    execution_policy="GENERAL",
                )
            )
        except Exception as exc:
            logger.error("AI 중앙 주문 접수 중 예기치 못한 오류: symbol=%s error=%s", symbol, exc, exc_info=True)
            return

        if (
            live_result.submission_status == "ACCEPTED"
            and live_result.error_code != "BLOCKING_INTENT"
        ):
            if live_result.replayed:
                logger.info(
                    "AI 실주문 매수 기존 의도 재조회: symbol=%s intent_id=%s uuid=%s",
                    symbol,
                    live_result.intent_id,
                    live_result.exchange_uuid,
                )
            else:
                logger.info(
                    "AI 실주문 매수 접수 성공: symbol=%s confidence=%s weight=%s intent_id=%s uuid=%s",
                    symbol,
                    analysis.confidence,
                    analysis.recommended_weight,
                    live_result.intent_id,
                    live_result.exchange_uuid,
                )
                await _send_live_order_accepted_notification(
                    symbol=symbol,
                    decision="BUY",
                    confidence=analysis.confidence,
                    recommended_weight=analysis.recommended_weight,
                    result=live_result,
                )
        elif _is_live_order_blocking(live_result):
            logger.warning(
                "AI 실주문 매수 확인 중: symbol=%s intent_id=%s status=%s error_code=%s",
                symbol,
                live_result.intent_id,
                live_result.submission_status,
                live_result.error_code,
            )
        else:
            logger.warning(
                "AI 실주문 매수 거절 또는 종결: symbol=%s status=%s error_code=%s error=%s",
                symbol,
                live_result.submission_status,
                live_result.error_code,
                live_result.error_message,
            )
        return live_result

    logger.info(
        "AI paper 매수 체결 성공: symbol=%s confidence=%s weight=%s uuid=%s",
        symbol,
        analysis.confidence,
        analysis.recommended_weight,
        order_result.get("uuid"),
    )
    await _send_trade_notification(
        symbol=symbol,
        decision="BUY",
        confidence=analysis.confidence,
        recommended_weight=analysis.recommended_weight,
        order_result=order_result,
        trading_mode=trading_mode,
    )
    return None


async def _execute_sell_trade(
    *,
    db: AsyncSession,
    symbol: str,
    analysis: AIAnalysisLog,
    portfolio: PortfolioSummary,
    trading_mode: str,
) -> LiveOrderResult | None:
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
        try:
            cash_config = await _get_or_create_paper_cash_config(db)
            current_paper_balance = _to_float(cash_config.config_value)
            if current_paper_balance < 0:
                current_paper_balance = DEFAULT_PAPER_KRW_BALANCE

            asset = await _get_or_create_asset(db, symbol)
            position = await _get_existing_position(db, asset.id, is_paper=True)
            position_qty = max(_to_float(position.quantity) if position is not None else 0.0, 0.0)
            if position is None or position_qty <= 0:
                logger.info("AI paper 매도 스킵: paper 포지션이 없습니다. symbol=%s", symbol)
                return

            realized_sell_qty = min(sell_volume, position_qty)
            if realized_sell_qty <= 0:
                logger.info("AI paper 매도 스킵: 계산된 실매도 수량이 0 이하입니다. symbol=%s", symbol)
                return

            recovered_krw = realized_sell_qty * current_price * 0.9995
            remaining_qty = max(position_qty - realized_sell_qty, 0.0)
            position.quantity = 0.0 if remaining_qty <= PAPER_BALANCE_EPSILON else remaining_qty
            position.status = "closed" if position.quantity <= PAPER_BALANCE_EPSILON else "open"
            cash_config.config_value = _fmt_number(current_paper_balance + recovered_krw)
            cash_config.version = int(cash_config.version or 0) + 1
            executed_at = datetime.now(UTC)
            order_result = build_paper_order_result(
                market=symbol,
                side="ask",
                ord_type="market",
                executed_price=current_price,
                executed_qty=realized_sell_qty,
                executed_at=executed_at,
            )

            history_recorded = await _record_paper_order_history(
                db=db,
                symbol=symbol,
                analysis=analysis,
                side="sell",
                order_result=order_result,
                fallback_price=current_price,
                fallback_qty=realized_sell_qty,
            )
            if not history_recorded:
                return
        except Exception as exc:
            await db.rollback()
            logger.error("AI paper 매도 적용 중 예기치 못한 오류: symbol=%s error=%s", symbol, exc, exc_info=True)
            return
    else:
        try:
            await _close_caller_transaction_before_live_order(db)
            live_result = await _build_live_order_execution_service().execute(
                LiveOrderRequest(
                    source_type="AI_ANALYSIS",
                    source_ref=f"analysis:{analysis.id}:{symbol}:ask",
                    market=symbol,
                    side="ask",
                    ord_type="market",
                    price=None,
                    volume=Decimal(_fmt_number(sell_volume)),
                    ai_analysis_log_id=analysis.id,
                    liquidation_operation_id=None,
                    reason=None,
                    execution_policy="GENERAL",
                )
            )
        except Exception as exc:
            logger.error("AI 중앙 주문 접수 중 예기치 못한 오류: symbol=%s error=%s", symbol, exc, exc_info=True)
            return

        if (
            live_result.submission_status == "ACCEPTED"
            and live_result.error_code != "BLOCKING_INTENT"
        ):
            if live_result.replayed:
                logger.info(
                    "AI 실주문 매도 기존 의도 재조회: symbol=%s intent_id=%s uuid=%s",
                    symbol,
                    live_result.intent_id,
                    live_result.exchange_uuid,
                )
            else:
                logger.info(
                    "AI 실주문 매도 접수 성공: symbol=%s confidence=%s weight=%s intent_id=%s uuid=%s",
                    symbol,
                    analysis.confidence,
                    analysis.recommended_weight,
                    live_result.intent_id,
                    live_result.exchange_uuid,
                )
                await _send_live_order_accepted_notification(
                    symbol=symbol,
                    decision="SELL",
                    confidence=analysis.confidence,
                    recommended_weight=analysis.recommended_weight,
                    result=live_result,
                )
        elif _is_live_order_blocking(live_result):
            logger.warning(
                "AI 실주문 매도 확인 중: symbol=%s intent_id=%s status=%s error_code=%s",
                symbol,
                live_result.intent_id,
                live_result.submission_status,
                live_result.error_code,
            )
        else:
            logger.warning(
                "AI 실주문 매도 거절 또는 종결: symbol=%s status=%s error_code=%s error=%s",
                symbol,
                live_result.submission_status,
                live_result.error_code,
                live_result.error_message,
            )
        return live_result

    logger.info(
        "AI paper 매도 체결 성공: symbol=%s confidence=%s weight=%s uuid=%s",
        symbol,
        analysis.confidence,
        analysis.recommended_weight,
        order_result.get("uuid"),
    )
    await _send_trade_notification(
        symbol=symbol,
        decision="SELL",
        confidence=analysis.confidence,
        recommended_weight=analysis.recommended_weight,
        order_result=order_result,
        trading_mode=trading_mode,
    )
    return None


async def execute_ai_trade(
    db: AsyncSession,
    symbol: str,
    *,
    analysis_id: int | None = None,
    risk_check: RiskCheckResult | None = None,
) -> LiveOrderResult | None:
    normalized_symbol = _normalize_symbol(symbol)
    if not normalized_symbol:
        logger.info("AI 실행 스킵: symbol 이 비어 있습니다.")
        return

    if (
        not isinstance(analysis_id, int)
        or isinstance(analysis_id, bool)
        or analysis_id <= 0
    ):
        logger.warning(
            "AI 실행 스킵: 유효한 분석 로그 ID가 없습니다. symbol=%s analysis_id=%s",
            normalized_symbol,
            analysis_id,
        )
        return

    status = await get_bot_status(db)
    if not status.running:
        logger.info("봇 꺼짐 - 반자율 탐색 모드 유지: symbol=%s", normalized_symbol)
        return

    analysis = await _load_analysis_by_id(db, analysis_id)
    if analysis is None:
        logger.warning(
            "AI 실행 스킵: 전달된 분석 로그를 찾을 수 없습니다. symbol=%s analysis_id=%s",
            normalized_symbol,
            analysis_id,
        )
        return

    if _normalize_symbol(analysis.symbol) != normalized_symbol:
        logger.error(
            "AI 실행 스킵: 분석 로그의 symbol이 요청과 일치하지 않습니다. symbol=%s analysis_id=%s analysis_symbol=%s",
            normalized_symbol,
            analysis_id,
            analysis.symbol,
        )
        return

    min_confidence, max_age_minutes = await _load_executor_thresholds(db)

    if _is_analysis_stale(analysis, max_age_minutes):
        logger.info(
            "AI 실행 스킵: 분석 로그가 만료되었습니다. symbol=%s analysis_id=%s created_at=%s max_age_minutes=%s",
            normalized_symbol,
            analysis_id,
            analysis.created_at,
            max_age_minutes,
        )
        return

    if analysis.decision == "HOLD":
        logger.info(
            "AI 실행 스킵: 관망 결정입니다. symbol=%s analysis_id=%s",
            normalized_symbol,
            analysis_id,
        )
        return

    if analysis.confidence < min_confidence:
        logger.info(
            "AI 실행 스킵: 확신도 부족. symbol=%s analysis_id=%s confidence=%s min_confidence=%s",
            normalized_symbol,
            analysis_id,
            analysis.confidence,
            min_confidence,
        )
        return

    if analysis.recommended_weight <= 0:
        logger.info(
            "AI 실행 스킵: 추천 비중이 0 이하입니다. symbol=%s analysis_id=%s recommended_weight=%s",
            normalized_symbol,
            analysis_id,
            analysis.recommended_weight,
        )
        return

    if analysis.decision == "BUY" and (
        risk_check is None or not risk_check.allows_new_buy
    ):
        logger.warning(
            "AI BUY 리스크 fail-closed 차단: symbol=%s analysis_id=%s status=%s reasons=%s",
            normalized_symbol,
            analysis_id,
            risk_check.status if risk_check is not None else RiskCheckStatus.UNKNOWN,
            risk_check.reasons if risk_check is not None else ("RISK_CHECK_MISSING",),
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
    if analysis.decision == "BUY":
        entry_gate = await evaluate_ai_buy_entry_gate(
            db,
            symbol=normalized_symbol,
            analysis=analysis,
            portfolio=portfolio,
            min_calibrated_confidence=min_confidence,
        )
        if not entry_gate.allowed:
            logger.info(
                "AI BUY 진입 게이트 스킵: symbol=%s gate=%s",
                normalized_symbol,
                entry_gate.to_log_dict(),
            )
            return

        if entry_gate.shadow_mode:
            logger.info(
                "AI BUY shadow 후보 기록: symbol=%s gate=%s",
                normalized_symbol,
                entry_gate.to_log_dict(),
            )
            return

        if trading_mode == "live" and not await _load_live_buy_enabled(db):
            logger.warning(
                "AI live 신규 매수 잠금: symbol=%s confidence=%s recommended_weight=%s",
                normalized_symbol,
                analysis.confidence,
                analysis.recommended_weight,
            )
            return

        execution_analysis = analysis
        if trading_mode == "live":
            precheck_analysis = await _run_buy_precheck(
                db=db,
                symbol=normalized_symbol,
                analysis=analysis,
                entry_gate=entry_gate,
                portfolio=portfolio,
                trading_mode=trading_mode,
                min_confidence=min_confidence,
            )
            if precheck_analysis is None:
                return
            execution_analysis = precheck_analysis

        return await _execute_buy_trade(
            db=db,
            symbol=normalized_symbol,
            analysis=execution_analysis,
            primary_recommended_weight=analysis.recommended_weight,
            portfolio=portfolio,
            trading_mode=trading_mode,
        )

    if analysis.decision == "SELL":
        return await _execute_sell_trade(
            db=db,
            symbol=normalized_symbol,
            analysis=analysis,
            portfolio=portfolio,
            trading_mode=trading_mode,
        )

    logger.info(
        "AI 실행 스킵: 지원되지 않는 decision 값입니다. symbol=%s decision=%s",
        normalized_symbol,
        analysis.decision,
    )
    return None
