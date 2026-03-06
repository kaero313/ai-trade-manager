from datetime import datetime, timezone
from typing import Any


BUY_COLOR = "#ef4444"
SELL_COLOR = "#3b82f6"


def analyze_backtest_result(backtest_result: dict[str, Any]) -> dict[str, Any]:
    candles = _normalize_candles(backtest_result.get("candles"))
    trades = _normalize_trades(backtest_result.get("trades"))
    initial_balance = _to_float(backtest_result.get("initial_balance"))
    final_balance = _to_float(backtest_result.get("final_balance"))

    total_return_pct = 0.0
    if initial_balance > 0:
        total_return_pct = ((final_balance - initial_balance) / initial_balance) * 100.0

    max_drawdown_pct = _calculate_max_drawdown_pct(initial_balance, trades)
    win_rate = _calculate_win_rate(trades)
    markers = _build_markers(trades)

    summary = {
        "total_return_pct": round(total_return_pct, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "win_rate": round(win_rate, 4),
        "number_of_trades": len(trades),
    }

    meta = {
        "market": str(backtest_result.get("market") or ""),
        "timeframe": str(backtest_result.get("timeframe") or ""),
        "start_date": str(backtest_result.get("start_date") or ""),
        "end_date": str(backtest_result.get("end_date") or ""),
        "bars_processed": int(backtest_result.get("bars_processed") or 0),
        "last_timestamp": str(backtest_result.get("last_timestamp") or ""),
        "initial_balance": initial_balance,
        "final_balance": final_balance,
        "position_qty": _to_float(backtest_result.get("position_qty")),
    }

    return {
        "summary": summary,
        "candles": candles,
        "markers": markers,
        "trades": trades,
        "meta": meta,
    }


def _normalize_candles(raw_candles: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_candles, list):
        return []

    normalized: list[dict[str, Any]] = []
    for row in raw_candles:
        if not isinstance(row, dict):
            continue
        parsed_time = _parse_datetime(str(row.get("timestamp") or "").strip())
        if parsed_time is None:
            continue

        normalized_row: dict[str, Any] = {
            "time": int(parsed_time.timestamp()),
            "open": _to_float(row.get("open")),
            "high": _to_float(row.get("high")),
            "low": _to_float(row.get("low")),
            "close": _to_float(row.get("close")),
            "volume": _to_float(row.get("volume")),
        }
        for key, value in row.items():
            if key in {"timestamp", "open", "high", "low", "close", "volume"}:
                continue
            if key.startswith(("sma_", "ema_", "bb_", "rsi_")):
                normalized_row[key] = _to_optional_float(value)

        normalized.append(normalized_row)

    normalized.sort(key=lambda item: int(item["time"]))
    return normalized


def _normalize_trades(raw_trades: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_trades, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in raw_trades:
        if not isinstance(item, dict):
            continue

        timestamp = str(item.get("timestamp") or "").strip()
        parsed_timestamp = _parse_datetime(timestamp)

        row = {
            "index": int(item.get("index") or 0),
            "timestamp": timestamp,
            "side": str(item.get("side") or "").lower().strip(),
            "price": _to_float(item.get("price")),
            "qty": _to_float(item.get("qty")),
            "fee": _to_float(item.get("fee")),
            "krw_balance": _to_float(item.get("krw_balance")),
            "coin_balance": _to_float(item.get("coin_balance")),
            "_parsed_timestamp": parsed_timestamp,
        }
        normalized.append(row)

    normalized.sort(
        key=lambda row: (
            row["_parsed_timestamp"] or datetime.max.replace(tzinfo=timezone.utc),
            int(row.get("index") or 0),
        )
    )
    for row in normalized:
        row.pop("_parsed_timestamp", None)
    return normalized


def _calculate_max_drawdown_pct(initial_balance: float, trades: list[dict[str, Any]]) -> float:
    equity_curve: list[float] = []
    if initial_balance > 0:
        equity_curve.append(initial_balance)

    for trade in trades:
        price = _to_float(trade.get("price"))
        if price <= 0:
            continue
        krw_balance = _to_float(trade.get("krw_balance"))
        coin_balance = _to_float(trade.get("coin_balance"))
        equity_curve.append(krw_balance + (coin_balance * price))

    if not equity_curve:
        return 0.0

    peak = equity_curve[0]
    max_drawdown_pct = 0.0
    for equity in equity_curve:
        if equity > peak:
            peak = equity
        if peak <= 0:
            continue
        drawdown_pct = ((peak - equity) / peak) * 100.0
        if drawdown_pct > max_drawdown_pct:
            max_drawdown_pct = drawdown_pct
    return max_drawdown_pct


def _calculate_win_rate(trades: list[dict[str, Any]]) -> float:
    open_qty = 0.0
    open_cost = 0.0
    total_closed = 0
    wins = 0

    for trade in trades:
        side = str(trade.get("side") or "").lower().strip()
        price = _to_float(trade.get("price"))
        qty = _to_float(trade.get("qty"))
        fee = max(_to_float(trade.get("fee")), 0.0)
        if price <= 0 or qty <= 0:
            continue

        if side == "buy":
            open_qty += qty
            open_cost += (qty * price) + fee
            continue

        if side != "sell":
            continue

        if open_qty <= 0:
            continue

        matched_qty = min(qty, open_qty)
        if matched_qty <= 0:
            continue

        avg_cost = open_cost / open_qty if open_qty > 0 else 0.0
        matched_fee = fee * (matched_qty / qty) if qty > 0 else 0.0
        realized_cost = avg_cost * matched_qty
        realized_proceeds = (matched_qty * price) - matched_fee
        realized_pnl = realized_proceeds - realized_cost

        open_qty -= matched_qty
        open_cost -= realized_cost
        if open_qty <= 1e-12:
            open_qty = 0.0
            open_cost = 0.0

        total_closed += 1
        if realized_pnl > 0:
            wins += 1

    if total_closed == 0:
        return 0.0
    return (wins / total_closed) * 100.0


def _build_markers(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for trade in trades:
        side = str(trade.get("side") or "").lower().strip()
        if side not in {"buy", "sell"}:
            continue

        parsed_timestamp = _parse_datetime(str(trade.get("timestamp") or "").strip())
        if parsed_timestamp is None:
            continue

        qty = _to_float(trade.get("qty"))
        price = _to_float(trade.get("price"))

        markers.append(
            {
                "time": int(parsed_timestamp.timestamp()),
                "position": "belowBar" if side == "buy" else "aboveBar",
                "shape": "arrowUp" if side == "buy" else "arrowDown",
                "color": BUY_COLOR if side == "buy" else SELL_COLOR,
                "text": f"{side.upper()} {qty:.6f} @ {price:,.0f}",
                "side": side,
                "price": price,
                "qty": qty,
            }
        )
    return markers


def _parse_datetime(value: str) -> datetime | None:
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


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
