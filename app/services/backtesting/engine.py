import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.services.backtesting.data_loader import fetch_historical_data
from app.services.backtesting.simulated_broker import SimulatedBroker
from app.services.indicators import IndicatorCalculator

logger = logging.getLogger(__name__)

MIN_ORDER_KRW = 5_000.0


@dataclass(frozen=True, slots=True)
class AIPolicyStrategyParams:
    ema_fast: int = 12
    ema_slow: int = 26
    rsi_period: int = 14
    rsi_min: int = 45
    trailing_stop_pct: float = 0.03


@dataclass(frozen=True, slots=True)
class AIPolicyConfig:
    min_confidence: int = 85
    max_allocation_pct: float = 30.0
    take_profit_pct: float = 5.0
    stop_loss_pct: float = -3.0
    cooldown_minutes: int = 60


@dataclass(frozen=True, slots=True)
class AIPolicySignal:
    decision: str
    confidence: int
    recommended_weight: int
    reason: str
    is_risk_exit: bool = False


def _normalize_datetime_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class AIPolicyBacktestEngine:
    def __init__(self, fee_rate: float = 0.0005) -> None:
        self._is_running = True
        self._fee_rate = max(float(fee_rate), 0.0)
        self._indicator_calculator = IndicatorCalculator()

    def stop(self) -> None:
        self._is_running = False

    async def run(
        self,
        market: str,
        start_date: datetime,
        end_date: datetime,
        initial_balance: float,
        timeframe: str = "60m",
        strategy: Mapping[str, Any] | AIPolicyStrategyParams | None = None,
        policy: Mapping[str, Any] | AIPolicyConfig | None = None,
    ) -> dict[str, Any]:
        market_symbol = str(market or "").strip().upper()
        if not market_symbol:
            raise ValueError("market is required")

        start_utc = _normalize_datetime_utc(start_date)
        end_utc = _normalize_datetime_utc(end_date)
        if start_utc > end_utc:
            raise ValueError("start_date must be earlier than or equal to end_date")

        initial_balance_value = float(initial_balance)
        if initial_balance_value <= 0:
            raise ValueError("initial_balance must be greater than zero")

        strategy_params = _coerce_strategy_params(strategy)
        policy_config = _coerce_policy_config(policy)
        _validate_strategy_params(strategy_params)

        logger.info(
            "AI policy backtest started: market=%s timeframe=%s start=%s end=%s",
            market_symbol,
            timeframe,
            start_utc.isoformat(),
            end_utc.isoformat(),
        )

        candles = await fetch_historical_data(
            market=market_symbol,
            timeframe=timeframe,
            start_date=start_utc,
            end_date=end_utc,
        )
        enriched_candles = self._indicator_calculator.calculate_from_candles(candles)

        broker = SimulatedBroker(
            initial_krw_balance=initial_balance_value,
            fee_rate=self._fee_rate,
        )
        target_coin = market_symbol.split("-", 1)[1] if "-" in market_symbol else market_symbol
        closes = [_to_float(candle.get("close")) for candle in candles]
        ema_fast_values = _ema_series(closes, strategy_params.ema_fast)
        ema_slow_values = _ema_series(closes, strategy_params.ema_slow)
        rsi_values = _rsi_series(closes, strategy_params.rsi_period)

        trades: list[dict[str, Any]] = []
        equity_curve: list[dict[str, Any]] = []
        drawdown_curve: list[dict[str, Any]] = []
        processed_bars = 0
        last_timestamp: str | None = None
        last_close = 0.0
        peak_equity = initial_balance_value
        position_qty = 0.0
        avg_entry_price = 0.0
        highest_price_since_entry = 0.0
        next_trade_at: datetime | None = None

        for index, candle in enumerate(candles):
            if not self._is_running:
                logger.info("AI policy backtest interrupted by stop signal.")
                break

            processed_bars = index + 1
            last_timestamp = str(candle.get("timestamp") or "").strip()
            tick_time = _parse_timestamp(last_timestamp)
            close_price = _to_float(candle.get("close"))
            if tick_time is None or close_price <= 0:
                continue

            last_close = close_price
            broker.set_current_price(market_symbol, close_price, tick_time)
            if position_qty > 0:
                highest_price_since_entry = max(highest_price_since_entry, close_price)

            signal = _resolve_signal(
                close_price=close_price,
                ema_fast=ema_fast_values[index],
                ema_slow=ema_slow_values[index],
                rsi=rsi_values[index],
                position_qty=position_qty,
                avg_entry_price=avg_entry_price,
                highest_price_since_entry=highest_price_since_entry,
                strategy=strategy_params,
                policy=policy_config,
                next_trade_at=next_trade_at,
                current_time=tick_time,
            )

            if signal.decision == "BUY":
                order = await self._try_buy(
                    broker=broker,
                    market=market_symbol,
                    price=close_price,
                    signal=signal,
                    policy=policy_config,
                    initial_balance=initial_balance_value,
                    position_qty=position_qty,
                )
                if order is not None:
                    trade = _build_trade_row(index, tick_time, order, broker, target_coin, signal)
                    trades.append(trade)
                    executed_qty = _to_float(order.get("executed_volume"))
                    previous_cost = position_qty * avg_entry_price
                    position_qty = broker.get_coin_balance(target_coin)
                    if position_qty > 0:
                        avg_entry_price = (previous_cost + executed_qty * close_price) / position_qty
                        highest_price_since_entry = max(highest_price_since_entry, close_price)
                    next_trade_at = tick_time + timedelta(minutes=policy_config.cooldown_minutes)

            elif signal.decision == "SELL":
                order = await self._try_sell(
                    broker=broker,
                    market=market_symbol,
                    signal=signal,
                    position_qty=position_qty,
                )
                if order is not None:
                    trade = _build_trade_row(index, tick_time, order, broker, target_coin, signal)
                    trades.append(trade)
                    position_qty = broker.get_coin_balance(target_coin)
                    if position_qty <= 1e-12:
                        position_qty = 0.0
                        avg_entry_price = 0.0
                        highest_price_since_entry = 0.0
                    next_trade_at = tick_time + timedelta(minutes=policy_config.cooldown_minutes)

            equity = broker.get_krw_balance() + (broker.get_coin_balance(target_coin) * close_price)
            peak_equity = max(peak_equity, equity)
            pnl_pct = ((equity - initial_balance_value) / initial_balance_value) * 100.0
            drawdown_pct = ((peak_equity - equity) / peak_equity) * 100.0 if peak_equity > 0 else 0.0
            equity_curve.append(
                {
                    "time": int(tick_time.timestamp()),
                    "equity": equity,
                    "pnl_pct": pnl_pct,
                }
            )
            drawdown_curve.append(
                {
                    "time": int(tick_time.timestamp()),
                    "drawdown_pct": drawdown_pct,
                }
            )

        final_position_qty = broker.get_coin_balance(target_coin)
        final_balance = broker.get_krw_balance()
        if last_close > 0:
            final_balance += final_position_qty * last_close

        logger.info(
            "AI policy backtest finished: market=%s processed=%s final_balance=%s",
            market_symbol,
            processed_bars,
            final_balance,
        )

        return {
            "market": market_symbol,
            "timeframe": timeframe,
            "start_date": start_utc.isoformat(),
            "end_date": end_utc.isoformat(),
            "bars_processed": processed_bars,
            "last_timestamp": last_timestamp,
            "initial_balance": initial_balance_value,
            "final_balance": final_balance,
            "position_qty": final_position_qty,
            "strategy": _strategy_to_dict(strategy_params),
            "policy": _policy_to_dict(policy_config),
            "candles": enriched_candles,
            "trades": trades,
            "equity_curve": equity_curve,
            "drawdown_curve": drawdown_curve,
        }

    async def _try_buy(
        self,
        *,
        broker: SimulatedBroker,
        market: str,
        price: float,
        signal: AIPolicySignal,
        policy: AIPolicyConfig,
        initial_balance: float,
        position_qty: float,
    ) -> dict[str, Any] | None:
        current_equity = broker.get_krw_balance() + (position_qty * price)
        max_position_value = current_equity * (policy.max_allocation_pct / 100.0)
        current_position_value = position_qty * price
        remaining_budget = max(max_position_value - current_position_value, 0.0)
        target_budget = remaining_budget * (signal.recommended_weight / 100.0)
        available_cash = broker.get_krw_balance()
        spendable_cash = available_cash / (1.0 + self._fee_rate)
        order_krw = min(target_budget, spendable_cash)

        if initial_balance <= 0 or order_krw < MIN_ORDER_KRW:
            return None

        try:
            return await broker.create_order(
                market=market,
                side="bid",
                ord_type="price",
                price=_fmt_number(order_krw),
            )
        except ValueError as exc:
            logger.info("AI policy buy skipped: market=%s reason=%s", market, exc)
            return None

    async def _try_sell(
        self,
        *,
        broker: SimulatedBroker,
        market: str,
        signal: AIPolicySignal,
        position_qty: float,
    ) -> dict[str, Any] | None:
        sell_ratio = 1.0 if signal.is_risk_exit else signal.recommended_weight / 100.0
        sell_qty = min(position_qty, position_qty * sell_ratio)
        if sell_qty <= 1e-12:
            return None

        try:
            return await broker.create_order(
                market=market,
                side="ask",
                ord_type="market",
                volume=_fmt_number(sell_qty),
            )
        except ValueError as exc:
            logger.info("AI policy sell skipped: market=%s reason=%s", market, exc)
            return None


BacktestEngine = AIPolicyBacktestEngine


def _coerce_strategy_params(
    value: Mapping[str, Any] | AIPolicyStrategyParams | None,
) -> AIPolicyStrategyParams:
    if isinstance(value, AIPolicyStrategyParams):
        return value
    payload = value if isinstance(value, Mapping) else {}
    return AIPolicyStrategyParams(
        ema_fast=_coerce_int(payload.get("ema_fast"), 12, minimum=2, maximum=250),
        ema_slow=_coerce_int(payload.get("ema_slow"), 26, minimum=3, maximum=400),
        rsi_period=_coerce_int(
            payload.get("rsi_period", payload.get("rsi")),
            14,
            minimum=2,
            maximum=100,
        ),
        rsi_min=_coerce_int(payload.get("rsi_min"), 45, minimum=1, maximum=99),
        trailing_stop_pct=_coerce_float(
            payload.get("trailing_stop_pct"),
            0.03,
            minimum=0.0,
            maximum=1.0,
        ),
    )


def _coerce_policy_config(value: Mapping[str, Any] | AIPolicyConfig | None) -> AIPolicyConfig:
    if isinstance(value, AIPolicyConfig):
        return value
    payload = value if isinstance(value, Mapping) else {}
    return AIPolicyConfig(
        min_confidence=_coerce_int(payload.get("min_confidence"), 85, minimum=0, maximum=100),
        max_allocation_pct=_coerce_float(
            payload.get("max_allocation_pct"),
            30.0,
            minimum=0.0,
            maximum=100.0,
        ),
        take_profit_pct=_coerce_float(
            payload.get("take_profit_pct"),
            5.0,
            minimum=0.0,
            maximum=1_000.0,
        ),
        stop_loss_pct=_coerce_float(
            payload.get("stop_loss_pct"),
            -3.0,
            minimum=-100.0,
            maximum=0.0,
        ),
        cooldown_minutes=_coerce_int(
            payload.get("cooldown_minutes"),
            60,
            minimum=0,
            maximum=24 * 60,
        ),
    )


def _validate_strategy_params(strategy: AIPolicyStrategyParams) -> None:
    if strategy.ema_fast >= strategy.ema_slow:
        raise ValueError("ema_fast must be smaller than ema_slow")


def _resolve_signal(
    *,
    close_price: float,
    ema_fast: float | None,
    ema_slow: float | None,
    rsi: float | None,
    position_qty: float,
    avg_entry_price: float,
    highest_price_since_entry: float,
    strategy: AIPolicyStrategyParams,
    policy: AIPolicyConfig,
    next_trade_at: datetime | None,
    current_time: datetime,
) -> AIPolicySignal:
    if next_trade_at is not None and current_time < next_trade_at:
        return AIPolicySignal("HOLD", 0, 0, "cooldown")

    if position_qty > 0 and avg_entry_price > 0:
        pnl_pct = ((close_price - avg_entry_price) / avg_entry_price) * 100.0
        if policy.take_profit_pct > 0 and pnl_pct >= policy.take_profit_pct:
            return AIPolicySignal("SELL", 100, 100, "take_profit", True)
        if policy.stop_loss_pct < 0 and pnl_pct <= policy.stop_loss_pct:
            return AIPolicySignal("SELL", 100, 100, "stop_loss", True)
        trailing_stop_price = highest_price_since_entry * (1.0 - strategy.trailing_stop_pct)
        if strategy.trailing_stop_pct > 0 and close_price <= trailing_stop_price:
            return AIPolicySignal("SELL", 100, 100, "trailing_stop", True)

    if ema_fast is None or ema_slow is None or rsi is None or ema_slow <= 0:
        return AIPolicySignal("HOLD", 0, 0, "insufficient_indicators")

    ema_gap_pct = ((ema_fast - ema_slow) / ema_slow) * 100.0
    if position_qty > 0 and ema_fast < ema_slow and rsi < strategy.rsi_min:
        confidence = _clamp_int(55 + abs(ema_gap_pct) * 5 + (strategy.rsi_min - rsi), 0, 95)
        if confidence >= policy.min_confidence:
            return AIPolicySignal("SELL", confidence, 100, "trend_breakdown")
        return AIPolicySignal("HOLD", confidence, 0, "sell_confidence_below_threshold")

    if position_qty <= 0 and ema_fast > ema_slow and close_price > ema_fast and rsi >= strategy.rsi_min:
        confidence = _clamp_int(50 + min(25.0, ema_gap_pct * 5) + min(20.0, rsi - strategy.rsi_min), 0, 95)
        if confidence >= policy.min_confidence:
            recommended_weight = _clamp_int(confidence, 10, 100)
            return AIPolicySignal("BUY", confidence, recommended_weight, "ai_policy_buy")
        return AIPolicySignal("HOLD", confidence, 0, "buy_confidence_below_threshold")

    return AIPolicySignal("HOLD", 0, 0, "no_signal")


def _build_trade_row(
    index: int,
    timestamp: datetime,
    order: dict[str, Any],
    broker: SimulatedBroker,
    target_coin: str,
    signal: AIPolicySignal,
) -> dict[str, Any]:
    side = str(order.get("side") or "").lower().strip()
    return {
        "index": index,
        "timestamp": timestamp.isoformat(),
        "side": side,
        "price": _to_float(order.get("price")),
        "qty": _to_float(order.get("executed_volume")),
        "fee": _to_float(order.get("paid_fee")),
        "krw_balance": broker.get_krw_balance(),
        "coin_balance": broker.get_coin_balance(target_coin),
        "reason": signal.reason,
        "confidence": signal.confidence,
        "recommended_weight": signal.recommended_weight,
    }


def _ema_series(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = []
    alpha = 2.0 / (period + 1.0)
    ema: float | None = None
    for index, value in enumerate(values):
        if value <= 0:
            result.append(None)
            continue
        ema = value if ema is None else (value * alpha) + (ema * (1.0 - alpha))
        result.append(ema if index >= period - 1 else None)
    return result


def _rsi_series(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None for _ in values]
    for index in range(period, len(values)):
        gains = 0.0
        losses = 0.0
        for prev_index in range(index - period + 1, index + 1):
            change = values[prev_index] - values[prev_index - 1]
            if change >= 0:
                gains += change
            else:
                losses += abs(change)
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss <= 0:
            result[index] = 100.0
        else:
            rs_value = avg_gain / avg_loss
            result[index] = 100.0 - (100.0 / (1.0 + rs_value))
    return result


def _strategy_to_dict(strategy: AIPolicyStrategyParams) -> dict[str, Any]:
    return {
        "ema_fast": strategy.ema_fast,
        "ema_slow": strategy.ema_slow,
        "rsi_period": strategy.rsi_period,
        "rsi_min": strategy.rsi_min,
        "trailing_stop_pct": strategy.trailing_stop_pct,
    }


def _policy_to_dict(policy: AIPolicyConfig) -> dict[str, Any]:
    return {
        "min_confidence": policy.min_confidence,
        "max_allocation_pct": policy.max_allocation_pct,
        "take_profit_pct": policy.take_profit_pct,
        "stop_loss_pct": policy.stop_loss_pct,
        "cooldown_minutes": policy.cooldown_minutes,
    }


def _coerce_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min(parsed, maximum), minimum)


def _coerce_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min(parsed, maximum), minimum)


def _clamp_int(value: float, minimum: int, maximum: int) -> int:
    return max(min(int(round(value)), maximum), minimum)


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fmt_number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".") or "0"


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
