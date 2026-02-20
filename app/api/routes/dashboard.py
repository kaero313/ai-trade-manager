from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.repository import get_or_create_bot_config
from app.db.session import get_db
from app.models.schemas import BotConfig as BotConfigSchema
from app.services.bot_service import get_bot_status
from app.services.upbit_client import UpbitAPIError, upbit_client

router = APIRouter()
KST = timezone(timedelta(hours=9))
DONE_HISTORY_MAX_PAGES = 10
DONE_HISTORY_LIMIT = 100
REALIZED_CACHE_TTL = timedelta(seconds=60)

_realized_cache_at: datetime | None = None
_realized_cache_day: str | None = None
_realized_cache_value: dict[str, Any] | None = None


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    cleaned = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dedupe_markets(markets: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for market in markets:
        norm = (market or "").strip().upper()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def _schedule_text(cfg: BotConfigSchema) -> str:
    schedule = cfg.schedule
    if not schedule.enabled:
        return "Disabled"
    if schedule.start_hour is None or schedule.end_hour is None:
        return "KST 24H"
    return f"KST {schedule.start_hour:02d}:00-{schedule.end_hour:02d}:00"


async def _fetch_done_orders_history(
    max_pages: int = DONE_HISTORY_MAX_PAGES,
    limit: int = DONE_HISTORY_LIMIT,
) -> tuple[list[dict[str, Any]], bool]:
    history: list[dict[str, Any]] = []
    reached_cap = False

    for page in range(1, max_pages + 1):
        rows = await upbit_client.get_orders_closed(
            states=["done"],
            page=page,
            limit=limit,
            order_by="desc",
        )
        if not isinstance(rows, list) or not rows:
            break

        for row in rows:
            if isinstance(row, dict):
                history.append(row)

        if len(rows) < limit:
            break

        if page == max_pages:
            reached_cap = True

    return history, reached_cap


def _order_fill_values(order: dict[str, Any]) -> tuple[float, float, float]:
    qty = _to_float(order.get("executed_volume"))
    if qty <= 0:
        qty = _to_float(order.get("volume"))

    funds = _to_float(order.get("funds"))
    avg_price = _to_float(order.get("avg_price"))
    if funds <= 0 and qty > 0 and avg_price > 0:
        funds = qty * avg_price

    fee = _to_float(order.get("paid_fee"))
    return qty, funds, fee


def _estimate_daily_realized_pnl(
    done_orders: list[dict[str, Any]],
    day_start_utc: datetime,
    now_utc: datetime,
) -> dict[str, Any]:
    inventory: dict[str, dict[str, float]] = {}
    daily_realized_pnl = 0.0
    wins = 0
    losses = 0
    missing_cost_events = 0
    analyzed_orders = 0

    sortable: list[tuple[datetime, dict[str, Any]]] = []
    for order in done_orders:
        created_at = _parse_dt(order.get("created_at"))
        if created_at is None:
            continue
        sortable.append((created_at, order))

    sortable.sort(key=lambda pair: pair[0])

    for created_at, order in sortable:
        side = str(order.get("side") or "").lower()
        market = str(order.get("market") or "").upper()
        if not market or side not in ("bid", "ask"):
            continue

        qty, funds, fee = _order_fill_values(order)
        if qty <= 0:
            continue
        analyzed_orders += 1

        position = inventory.setdefault(market, {"qty": 0.0, "cost": 0.0})

        if side == "bid":
            cost_add = max(funds, 0.0) + max(fee, 0.0)
            position["qty"] += qty
            position["cost"] += cost_add
            continue

        proceeds = max(funds, 0.0) - max(fee, 0.0)
        if position["qty"] <= 1e-12 or position["cost"] <= 0:
            cost_removed = max(funds, 0.0)
            missing_cost_events += 1
        else:
            avg_cost = position["cost"] / position["qty"]
            matched_qty = min(qty, position["qty"])
            cost_removed = avg_cost * matched_qty
            position["qty"] -= matched_qty
            position["cost"] -= cost_removed
            if position["qty"] <= 1e-12:
                position["qty"] = 0.0
                position["cost"] = 0.0

            remainder_qty = qty - matched_qty
            if remainder_qty > 1e-12:
                sell_unit_price = (max(funds, 0.0) / qty) if qty > 0 else 0.0
                cost_removed += sell_unit_price * remainder_qty
                missing_cost_events += 1

        pnl = proceeds - cost_removed
        if day_start_utc <= created_at <= now_utc:
            daily_realized_pnl += pnl
            if pnl > 1e-9:
                wins += 1
            elif pnl < -1e-9:
                losses += 1

    return {
        "daily_realized_pnl_krw": daily_realized_pnl,
        "wins": wins,
        "losses": losses,
        "missing_cost_events": missing_cost_events,
        "analyzed_orders": analyzed_orders,
    }


async def _get_daily_realized_stats(day_start_utc: datetime, now_utc: datetime) -> dict[str, Any]:
    global _realized_cache_at, _realized_cache_day, _realized_cache_value

    today_key = day_start_utc.date().isoformat()
    if (
        _realized_cache_at is not None
        and _realized_cache_day == today_key
        and _realized_cache_value is not None
        and now_utc - _realized_cache_at <= REALIZED_CACHE_TTL
    ):
        return _realized_cache_value

    orders, reached_cap = await _fetch_done_orders_history()
    stats = _estimate_daily_realized_pnl(orders, day_start_utc=day_start_utc, now_utc=now_utc)
    stats["history_capped"] = reached_cap

    _realized_cache_at = now_utc
    _realized_cache_day = today_key
    _realized_cache_value = stats
    return stats


@router.get("/dashboard")
async def get_dashboard_snapshot(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    now_kst = now_utc.astimezone(KST)
    day_start_utc = now_kst.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )
    bot_config = await get_or_create_bot_config(db)
    cfg = BotConfigSchema.model_validate(bot_config.config_json or {})
    status = await get_bot_status(db)

    strategy_text = (
        f"EMA {cfg.strategy.ema_fast}/{cfg.strategy.ema_slow} + "
        f"RSI {cfg.strategy.rsi} ({cfg.strategy.rsi_min}+)"
    )
    heartbeat_age_sec: int | None = None
    heartbeat_dt = _parse_dt(status.last_heartbeat)
    if heartbeat_dt:
        heartbeat_age_sec = max(0, int((now_utc - heartbeat_dt).total_seconds()))

    result: dict[str, Any] = {
        "synced_at": now_kst.strftime("%H:%M:%S KST"),
        "strategy_text": strategy_text,
        "schedule_text": _schedule_text(cfg),
        "status": {
            "running": status.running,
            "last_heartbeat": status.last_heartbeat,
            "last_error": status.last_error,
            "heartbeat_age_sec": heartbeat_age_sec,
        },
        "metrics": {
            "total_asset_krw": 0.0,
            "daily_realized_pnl_krw": 0.0,
            "unrealized_pnl_krw": 0.0,
            "capital_usage_pct": 0.0,
            "capital_limit_pct": cfg.risk.max_capital_pct * 100.0,
            "wins": 0,
            "losses": 0,
        },
        "symbols": [],
        "throughput": [0] * 12,
        "alerts": [],
        "positions": [],
        "risk": {
            "capital_usage_pct": 0.0,
            "capital_limit_pct": cfg.risk.max_capital_pct * 100.0,
            "floating_loss_pct": 0.0,
            "max_daily_loss_pct": cfg.risk.max_daily_loss_pct * 100.0,
            "used_positions": 0,
            "max_positions": cfg.risk.max_concurrent_positions,
        },
        "warnings": [],
    }

    if not settings.upbit_access_key or not settings.upbit_secret_key:
        result["warnings"].append("Upbit keys not configured")
        result["alerts"].append(
            {
                "level": "warn",
                "title": "Upbit Key Missing",
                "message": "Set UPBIT_ACCESS_KEY and UPBIT_SECRET_KEY in .env",
                "minutes_ago": None,
            }
        )
        return result

    try:
        accounts = await upbit_client.get_accounts()
    except UpbitAPIError as exc:
        payload = exc.to_dict()
        name = payload.get("error_name") or f"HTTP {exc.status_code}"
        message = payload.get("message") or "failed to fetch account data"
        result["warnings"].append(f"Upbit error: {name} {message}")
        result["alerts"].append(
            {
                "level": "danger",
                "title": "Upbit API Error",
                "message": f"{name} {message}",
                "minutes_ago": None,
            }
        )
        return result

    positions_raw: list[dict[str, Any]] = []
    krw_total = 0.0
    markets: list[str] = []
    for row in accounts:
        currency = str(row.get("currency") or "").upper()
        balance = _to_float(row.get("balance"))
        locked = _to_float(row.get("locked"))
        total = balance + locked
        if currency == "KRW":
            krw_total += total
            continue
        if total <= 0:
            continue

        unit_currency = str(row.get("unit_currency") or "KRW").upper()
        market = f"{unit_currency}-{currency}"
        avg_buy = _to_float(row.get("avg_buy_price"))
        positions_raw.append(
            {
                "market": market,
                "currency": currency,
                "unit_currency": unit_currency,
                "qty": total,
                "avg_buy": avg_buy,
            }
        )
        if unit_currency == "KRW":
            markets.append(market)

    config_markets = [symbol for symbol in cfg.symbols if isinstance(symbol, str)]
    markets.extend(config_markets[:5])
    markets = _dedupe_markets(markets)

    valid_markets: set[str] | None = None
    try:
        market_rows = await upbit_client.get_markets()
        valid_markets = {
            str(item.get("market")).upper()
            for item in market_rows
            if isinstance(item, dict) and isinstance(item.get("market"), str)
        }
    except UpbitAPIError:
        valid_markets = None

    if valid_markets is not None:
        markets = [market for market in markets if market in valid_markets]

    ticker_map: dict[str, dict[str, Any]] = {}
    if markets:
        try:
            tickers = await upbit_client.get_ticker(markets)
            for item in tickers:
                market = str(item.get("market") or "").upper()
                if market:
                    ticker_map[market] = item
        except UpbitAPIError as exc:
            payload = exc.to_dict()
            name = payload.get("error_name") or f"HTTP {exc.status_code}"
            message = payload.get("message") or "ticker fetch failed"
            result["warnings"].append(f"Ticker error: {name} {message}")

    positions: list[dict[str, Any]] = []
    total_coin_value = 0.0
    total_unrealized = 0.0

    for item in positions_raw:
        market = item["market"]
        qty = item["qty"]
        avg_buy = item["avg_buy"]
        ticker = ticker_map.get(market, {})
        now_price = _to_float(ticker.get("trade_price"))

        current_value = 0.0
        if item["unit_currency"] == "KRW" and now_price > 0:
            current_value = now_price * qty
            total_coin_value += current_value

        pnl_pct: float | None = None
        pnl_krw = 0.0
        if now_price > 0 and avg_buy > 0 and item["unit_currency"] == "KRW":
            pnl_pct = (now_price / avg_buy - 1.0) * 100.0
            pnl_krw = (now_price - avg_buy) * qty
            total_unrealized += pnl_krw

        positions.append(
            {
                "market": market,
                "qty": qty,
                "avg_price": avg_buy if avg_buy > 0 else None,
                "now_price": now_price if now_price > 0 else None,
                "pnl_pct": pnl_pct,
                "pnl_krw": pnl_krw if pnl_krw != 0 else None,
                "value_krw": current_value,
            }
        )

    positions.sort(key=lambda row: row.get("value_krw") or 0.0, reverse=True)

    total_asset = krw_total + total_coin_value
    capital_usage_pct = (total_coin_value / total_asset * 100.0) if total_asset > 0 else 0.0
    floating_loss_pct = (
        (abs(total_unrealized) / total_asset * 100.0) if total_asset > 0 and total_unrealized < 0 else 0.0
    )

    realized_daily_pnl = 0.0
    realized_wins = 0
    realized_losses = 0
    try:
        realized_stats = await _get_daily_realized_stats(day_start_utc=day_start_utc, now_utc=now_utc)
        realized_daily_pnl = _to_float(realized_stats.get("daily_realized_pnl_krw"))
        realized_wins = int(realized_stats.get("wins") or 0)
        realized_losses = int(realized_stats.get("losses") or 0)

        if realized_stats.get("history_capped"):
            result["warnings"].append(
                f"PnL history capped at {DONE_HISTORY_MAX_PAGES * DONE_HISTORY_LIMIT} fills."
            )
        missing_cost_events = int(realized_stats.get("missing_cost_events") or 0)
        if missing_cost_events > 0:
            result["warnings"].append(
                f"PnL includes {missing_cost_events} sell fills with inferred cost basis."
            )
    except UpbitAPIError as exc:
        payload = exc.to_dict()
        name = payload.get("error_name") or f"HTTP {exc.status_code}"
        message = payload.get("message") or "daily realized pnl fetch failed"
        result["warnings"].append(f"PnL error: {name} {message}")

    result["positions"] = positions[:10]
    result["metrics"] = {
        "total_asset_krw": total_asset,
        "daily_realized_pnl_krw": realized_daily_pnl,
        "unrealized_pnl_krw": total_unrealized,
        "capital_usage_pct": capital_usage_pct,
        "capital_limit_pct": cfg.risk.max_capital_pct * 100.0,
        "wins": realized_wins,
        "losses": realized_losses,
    }
    result["risk"] = {
        "capital_usage_pct": capital_usage_pct,
        "capital_limit_pct": cfg.risk.max_capital_pct * 100.0,
        "floating_loss_pct": floating_loss_pct,
        "max_daily_loss_pct": cfg.risk.max_daily_loss_pct * 100.0,
        "used_positions": len(positions),
        "max_positions": cfg.risk.max_concurrent_positions,
    }

    pulse_candidates = _dedupe_markets(config_markets[:5]) or [item["market"] for item in positions[:5]]
    symbols: list[dict[str, Any]] = []
    for market in pulse_candidates[:5]:
        ticker = ticker_map.get(market)
        if not ticker:
            continue
        change_pct = _to_float(ticker.get("signed_change_rate")) * 100.0
        symbols.append({"market": market, "change_pct": change_pct})

    if symbols:
        max_abs = max(abs(item["change_pct"]) for item in symbols) or 1.0
        for item in symbols:
            intensity = (abs(item["change_pct"]) / max_abs) * 100.0
            item["intensity_pct"] = max(18.0, min(100.0, intensity))
    result["symbols"] = symbols

    throughput = [0] * 12
    try:
        orders = await upbit_client.get_orders_closed(
            states=["done", "cancel"],
            limit=100,
            order_by="desc",
        )
        for order in orders:
            created_at = _parse_dt(order.get("created_at"))
            if created_at is None:
                continue
            age = now_utc - created_at
            if age.total_seconds() < 0:
                continue
            age_hour = int(age.total_seconds() // 3600)
            if 0 <= age_hour < 12:
                throughput[11 - age_hour] += 1
    except UpbitAPIError as exc:
        payload = exc.to_dict()
        name = payload.get("error_name") or f"HTTP {exc.status_code}"
        message = payload.get("message") or "order history fetch failed"
        result["warnings"].append(f"Orders error: {name} {message}")
    result["throughput"] = throughput

    alerts: list[dict[str, Any]] = []
    if status.last_error:
        alerts.append(
            {
                "level": "danger",
                "title": "Bot Error",
                "message": status.last_error,
                "minutes_ago": None,
            }
        )

    limit_pct = cfg.risk.max_capital_pct * 100.0
    if limit_pct > 0 and capital_usage_pct >= limit_pct:
        alerts.append(
            {
                "level": "danger",
                "title": "Capital Limit Exceeded",
                "message": f"Usage {capital_usage_pct:.2f}% / Limit {limit_pct:.2f}%",
                "minutes_ago": None,
            }
        )
    elif limit_pct > 0 and capital_usage_pct >= limit_pct * 0.8:
        alerts.append(
            {
                "level": "warn",
                "title": "Risk Threshold",
                "message": f"Usage approaching limit ({capital_usage_pct:.2f}% / {limit_pct:.2f}%)",
                "minutes_ago": None,
            }
        )

    worst_position = min(
        (row for row in positions if row.get("pnl_pct") is not None),
        key=lambda row: row["pnl_pct"],
        default=None,
    )
    if worst_position and worst_position["pnl_pct"] <= -2.0:
        alerts.append(
            {
                "level": "danger",
                "title": "Deep Drawdown",
                "message": f"{worst_position['market']} {worst_position['pnl_pct']:.2f}%",
                "minutes_ago": None,
            }
        )

    for warning in result["warnings"][:2]:
        alerts.append(
            {
                "level": "warn",
                "title": "Data Warning",
                "message": warning,
                "minutes_ago": None,
            }
        )

    if not alerts:
        alerts.append(
            {
                "level": "ok",
                "title": "Stable",
                "message": "No critical alerts.",
                "minutes_ago": None,
            }
        )
    result["alerts"] = alerts[:6]

    return result
