import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import PAPER_TRADING_KRW_BALANCE_KEY
from app.db.repository import TRADING_MODE_KEY
from app.db.repository import get_system_config_value
from app.models.domain import Asset
from app.models.domain import OrderHistory
from app.models.domain import Position
from app.models.domain import SystemConfig
from app.services.brokers.base import BaseBrokerClient
from app.services.brokers.factory import BrokerFactory

DEFAULT_TRADING_MODE = "live"
DEFAULT_PAPER_KRW_BALANCE = 10_000_000.0
PAPER_BROKER_NAME = "PAPER"
PAPER_BALANCE_DESCRIPTION = "모의투자용 가상 KRW 자본금"
PAPER_BALANCE_EPSILON = 1e-12


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _fmt_number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".") or "0"


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _extract_target_currency(symbol: str) -> str:
    normalized_symbol = _normalize_symbol(symbol)
    if "-" not in normalized_symbol:
        return normalized_symbol
    return normalized_symbol.split("-", 1)[1]


def _normalize_trading_mode(raw_value: str | None) -> str:
    normalized = str(raw_value or "").strip().lower()
    return "paper" if normalized == "paper" else DEFAULT_TRADING_MODE


async def get_trading_mode(db: AsyncSession) -> str:
    raw_value = await get_system_config_value(db, TRADING_MODE_KEY, DEFAULT_TRADING_MODE)
    return _normalize_trading_mode(raw_value)


async def load_paper_cash_balance(db: AsyncSession) -> float:
    raw_value = await get_system_config_value(
        db,
        PAPER_TRADING_KRW_BALANCE_KEY,
        str(DEFAULT_PAPER_KRW_BALANCE),
    )
    parsed = _to_float(raw_value)
    return parsed if parsed >= 0 else DEFAULT_PAPER_KRW_BALANCE


def build_paper_order_result(
    *,
    market: str,
    side: str,
    ord_type: str,
    executed_price: float,
    executed_qty: float,
    executed_at: datetime | None = None,
) -> dict[str, Any]:
    resolved_executed_at = executed_at or datetime.now(UTC)
    if resolved_executed_at.tzinfo is None:
        resolved_executed_at = resolved_executed_at.replace(tzinfo=UTC)
    else:
        resolved_executed_at = resolved_executed_at.astimezone(UTC)

    return {
        "uuid": f"paper-{uuid.uuid4()}",
        "market": _normalize_symbol(market),
        "side": side,
        "ord_type": ord_type,
        "state": "done",
        "price": _fmt_number(executed_price),
        "avg_price": _fmt_number(executed_price),
        "volume": _fmt_number(executed_qty),
        "executed_volume": _fmt_number(executed_qty),
        "remaining_volume": "0",
        "created_at": resolved_executed_at.isoformat(),
    }


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


async def _get_or_create_asset(db: AsyncSession, market: str) -> Asset:
    normalized_market = _normalize_symbol(market)
    result = await db.execute(select(Asset).where(Asset.symbol == normalized_market))
    asset = result.scalar_one_or_none()
    if asset is not None:
        return asset

    asset = Asset(
        symbol=normalized_market,
        asset_type="crypto",
        base_currency="KRW",
        is_active=True,
    )
    db.add(asset)
    await db.flush()
    return asset


async def _get_existing_paper_position(db: AsyncSession, asset_id: int) -> Position | None:
    result = await db.execute(
        select(Position)
        .where(Position.asset_id == asset_id, Position.is_paper.is_(True))
        .order_by(Position.id.asc())
    )
    return result.scalars().first()


async def _get_or_create_paper_position(
    db: AsyncSession,
    asset_id: int,
    fallback_price: float,
) -> Position:
    position = await _get_existing_paper_position(db, asset_id)
    if position is not None:
        return position

    position = Position(
        asset_id=asset_id,
        avg_entry_price=max(fallback_price, 0.0),
        quantity=0.0,
        status="open",
        is_paper=True,
    )
    db.add(position)
    await db.flush()
    return position


async def list_paper_accounts(db: AsyncSession) -> list[dict[str, Any]]:
    cash_balance = await load_paper_cash_balance(db)
    result = await db.execute(
        select(Position, Asset)
        .join(Asset, Position.asset_id == Asset.id)
        .where(
            Position.is_paper.is_(True),
            Position.status == "open",
            Position.quantity > 0,
        )
        .order_by(Position.id.asc())
    )

    accounts: list[dict[str, Any]] = [
        {
            "currency": "KRW",
            "balance": _fmt_number(cash_balance),
            "locked": "0",
            "avg_buy_price": "0",
        }
    ]
    for position, asset in result.all():
        accounts.append(
            {
                "currency": _extract_target_currency(asset.symbol),
                "balance": _fmt_number(position.quantity),
                "locked": "0",
                "avg_buy_price": _fmt_number(position.avg_entry_price),
            }
        )
    return accounts


async def apply_paper_fill(
    *,
    db: AsyncSession,
    symbol: str,
    side: str,
    executed_price: float,
    executed_qty: float,
    executed_at: datetime | None = None,
    ai_analysis_log_id: int | None = None,
    order_reason: str | None = None,
    broker_name: str = PAPER_BROKER_NAME,
) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    normalized_side = str(side or "").strip().lower()
    resolved_price = max(_to_float(executed_price), 0.0)
    resolved_qty = max(_to_float(executed_qty), 0.0)
    resolved_executed_at = executed_at or datetime.now(UTC)
    if resolved_executed_at.tzinfo is None:
        resolved_executed_at = resolved_executed_at.replace(tzinfo=UTC)
    else:
        resolved_executed_at = resolved_executed_at.astimezone(UTC)

    if normalized_side not in {"buy", "sell"}:
        raise ValueError(f"unsupported_paper_side:{side}")
    if resolved_price <= 0:
        raise ValueError("paper_execution_price_invalid")
    if resolved_qty <= 0:
        raise ValueError("paper_execution_qty_invalid")

    cash_config = await _get_or_create_paper_cash_config(db)
    current_cash = await load_paper_cash_balance(db)
    cash_config.config_value = _fmt_number(current_cash)
    asset = await _get_or_create_asset(db, normalized_symbol)

    if normalized_side == "buy":
        order_value = resolved_price * resolved_qty
        if order_value > current_cash + PAPER_BALANCE_EPSILON:
            raise ValueError("paper_krw_balance_insufficient")

        position = await _get_or_create_paper_position(db, asset.id, resolved_price)
        previous_qty = max(_to_float(position.quantity), 0.0)
        new_qty = previous_qty + resolved_qty
        weighted_cost = (previous_qty * max(_to_float(position.avg_entry_price), 0.0)) + order_value

        position.avg_entry_price = weighted_cost / new_qty if new_qty > 0 else resolved_price
        position.quantity = new_qty
        position.status = "open"
        cash_after = max(current_cash - order_value, 0.0)
    else:
        position = await _get_existing_paper_position(db, asset.id)
        available_qty = max(_to_float(position.quantity) if position is not None else 0.0, 0.0)
        if position is None or resolved_qty > available_qty + PAPER_BALANCE_EPSILON:
            raise ValueError("paper_coin_balance_insufficient")

        remaining_qty = max(available_qty - resolved_qty, 0.0)
        position.quantity = 0.0 if remaining_qty <= PAPER_BALANCE_EPSILON else remaining_qty
        position.status = "closed" if position.quantity <= PAPER_BALANCE_EPSILON else "open"
        cash_after = current_cash + (resolved_price * resolved_qty)

    cash_config.config_value = _fmt_number(cash_after)
    db.add(
        OrderHistory(
            position_id=position.id,
            ai_analysis_log_id=ai_analysis_log_id,
            side=normalized_side,
            order_reason=order_reason,
            is_paper=True,
            price=resolved_price,
            qty=resolved_qty,
            broker=broker_name,
            executed_at=resolved_executed_at,
        )
    )
    await db.flush()
    return {
        "cash_after": cash_after,
        "position_qty": max(_to_float(position.quantity), 0.0),
        "position_status": position.status,
    }


class PaperBroker(BaseBrokerClient):
    def __init__(self, db: AsyncSession, live_broker: BaseBrokerClient | None = None) -> None:
        self.db = db
        self.live_broker = live_broker or BrokerFactory.get_broker("UPBIT")

    async def get_accounts(self) -> list[dict[str, Any]]:
        return await list_paper_accounts(self.db)

    async def get_ticker(self, markets: list[str]) -> list[dict[str, Any]]:
        return await self.live_broker.get_ticker(markets)

    async def get_all_markets(self) -> list[dict[str, Any]]:
        return await self.live_broker.get_all_markets()

    async def get_candles(
        self,
        market: str,
        timeframe: str,
        count: int,
    ) -> list[dict[str, Any]]:
        return await self.live_broker.get_candles(market=market, timeframe=timeframe, count=count)

    async def get_orders_open(
        self,
        market: str | None = None,
        states: list[str] | None = None,
        page: int | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> Any:
        return []

    async def get_orders_closed(
        self,
        market: str | None = None,
        states: list[str] | None = None,
        page: int | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> Any:
        return []

    async def create_order(
        self,
        market: str,
        side: str,
        ord_type: str,
        volume: str | None = None,
        price: str | None = None,
        identifier: str | None = None,
    ) -> Any:
        tickers = await self.live_broker.get_ticker([_normalize_symbol(market)])
        current_price = 0.0
        for ticker in tickers:
            parsed_market = _normalize_symbol(str(ticker.get("market") or ""))
            if parsed_market != _normalize_symbol(market):
                continue
            current_price = max(_to_float(ticker.get("trade_price")), 0.0)
            break

        if current_price <= 0:
            raise ValueError(f"paper_current_price_unavailable:{market}")

        if str(side or "").strip().lower() == "bid":
            spend_amount = max(_to_float(price), 0.0)
            executed_qty = spend_amount / current_price if current_price > 0 else 0.0
            return build_paper_order_result(
                market=market,
                side=side,
                ord_type=ord_type,
                executed_price=current_price,
                executed_qty=executed_qty,
            )

        executed_qty = max(_to_float(volume), 0.0)
        return build_paper_order_result(
            market=market,
            side=side,
            ord_type=ord_type,
            executed_price=current_price,
            executed_qty=executed_qty,
        )

    async def cancel_order(
        self,
        uuid_: str | None = None,
        identifier: str | None = None,
    ) -> Any:
        return {
            "uuid": uuid_,
            "identifier": identifier,
            "state": "cancelled",
        }
