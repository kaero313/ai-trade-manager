from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.services.brokers.base import BaseBrokerClient


class SimulatedBroker(BaseBrokerClient):
    def __init__(
        self,
        initial_krw_balance: float,
        fee_rate: float = 0.0005,
    ) -> None:
        self._krw_balance = float(initial_krw_balance)
        self._fee_rate = max(float(fee_rate), 0.0)
        self._coin_balances: dict[str, float] = {}
        self._avg_buy_prices: dict[str, float] = {}
        self._current_prices: dict[str, float] = {}
        self._current_time: datetime = datetime.now(timezone.utc)
        self.trade_log: list[dict[str, Any]] = []

    def set_current_price(
        self,
        market: str,
        price: float,
        timestamp: datetime | None = None,
    ) -> None:
        normalized_market = str(market or "").strip().upper()
        normalized_price = float(price)
        if not normalized_market:
            raise ValueError("market is required")
        if normalized_price <= 0:
            raise ValueError("price must be greater than zero")

        self._current_prices[normalized_market] = normalized_price
        if timestamp is not None:
            if timestamp.tzinfo is None:
                self._current_time = timestamp.replace(tzinfo=timezone.utc)
            else:
                self._current_time = timestamp.astimezone(timezone.utc)

    def get_krw_balance(self) -> float:
        return self._krw_balance

    def get_coin_balance(self, coin: str) -> float:
        normalized_coin = str(coin or "").strip().upper()
        return float(self._coin_balances.get(normalized_coin, 0.0))

    async def get_accounts(self) -> list[dict[str, Any]]:
        accounts: list[dict[str, Any]] = [
            {
                "currency": "KRW",
                "balance": f"{self._krw_balance:.12f}",
                "locked": "0",
                "avg_buy_price": "0",
                "unit_currency": "KRW",
            }
        ]

        for coin, balance in sorted(self._coin_balances.items()):
            if balance <= 0:
                continue
            accounts.append(
                {
                    "currency": coin,
                    "balance": f"{balance:.12f}",
                    "locked": "0",
                    "avg_buy_price": f"{self._avg_buy_prices.get(coin, 0.0):.12f}",
                    "unit_currency": "KRW",
                }
            )
        return accounts

    async def get_ticker(self, markets: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for market in markets:
            normalized_market = str(market or "").strip().upper()
            if not normalized_market:
                continue
            price = self._current_prices.get(normalized_market)
            if price is None:
                continue
            rows.append(
                {
                    "market": normalized_market,
                    "trade_price": price,
                    "signed_change_rate": 0.0,
                    "acc_trade_price_24h": 0.0,
                }
            )
        return rows

    async def get_all_markets(self) -> list[dict[str, Any]]:
        return [
            {"market": market, "korean_name": market, "english_name": market}
            for market in sorted(self._current_prices.keys())
        ]

    async def get_candles(
        self,
        market: str,
        timeframe: str,
        count: int,
    ) -> list[dict[str, Any]]:
        _ = (market, timeframe, count)
        return []

    async def get_orders_open(
        self,
        market: str | None = None,
        states: list[str] | None = None,
        page: int | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> Any:
        _ = (market, states, page, limit, order_by)
        return []

    async def get_orders_closed(
        self,
        market: str | None = None,
        states: list[str] | None = None,
        page: int | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> Any:
        _ = (market, states, page, limit, order_by)
        return list(self.trade_log)

    async def create_order(
        self,
        market: str,
        side: str,
        ord_type: str,
        volume: str | None = None,
        price: str | None = None,
        identifier: str | None = None,
    ) -> Any:
        normalized_market = str(market or "").strip().upper()
        if not normalized_market:
            raise ValueError("market is required")

        current_price = self._current_prices.get(normalized_market)
        if current_price is None or current_price <= 0:
            raise ValueError(f"current price is not set for {normalized_market}")

        normalized_side = str(side or "").strip().lower()
        if normalized_side in {"buy", "bid"}:
            return self._create_buy_order(
                market=normalized_market,
                ord_type=ord_type,
                price=price,
                identifier=identifier,
                current_price=current_price,
            )
        if normalized_side in {"sell", "ask"}:
            return self._create_sell_order(
                market=normalized_market,
                ord_type=ord_type,
                volume=volume,
                identifier=identifier,
                current_price=current_price,
            )
        raise ValueError(f"unsupported side: {side}")

    async def cancel_order(
        self,
        uuid_: str | None = None,
        identifier: str | None = None,
    ) -> Any:
        _ = (uuid_, identifier)
        return {"status": "ignored"}

    def _create_buy_order(
        self,
        market: str,
        ord_type: str,
        price: str | None,
        identifier: str | None,
        current_price: float,
    ) -> dict[str, Any]:
        if str(ord_type or "").strip().lower() != "price":
            raise ValueError("simulated buy supports ord_type='price' only")

        krw_to_spend = self._to_float(price)
        if krw_to_spend <= 0:
            raise ValueError("price must be greater than zero for simulated buy")

        fee = krw_to_spend * self._fee_rate
        total_cost = krw_to_spend + fee
        if self._krw_balance < total_cost:
            raise ValueError("insufficient KRW balance")

        qty = krw_to_spend / current_price
        coin = self._coin_from_market(market)
        prev_qty = self._coin_balances.get(coin, 0.0)
        prev_avg = self._avg_buy_prices.get(coin, 0.0)
        next_qty = prev_qty + qty
        next_avg = ((prev_qty * prev_avg) + (qty * current_price)) / next_qty if next_qty > 0 else 0.0

        self._krw_balance -= total_cost
        self._coin_balances[coin] = next_qty
        self._avg_buy_prices[coin] = next_avg

        order = {
            "uuid": str(uuid4()),
            "identifier": identifier,
            "market": market,
            "side": "buy",
            "ord_type": "price",
            "price": current_price,
            "executed_volume": qty,
            "volume": qty,
            "paid_fee": fee,
            "created_at": self._current_time.isoformat(),
        }
        self.trade_log.append(order)
        return order

    def _create_sell_order(
        self,
        market: str,
        ord_type: str,
        volume: str | None,
        identifier: str | None,
        current_price: float,
    ) -> dict[str, Any]:
        if str(ord_type or "").strip().lower() != "market":
            raise ValueError("simulated sell supports ord_type='market' only")

        sell_qty = self._to_float(volume)
        if sell_qty <= 0:
            raise ValueError("volume must be greater than zero for simulated sell")

        coin = self._coin_from_market(market)
        available_qty = self._coin_balances.get(coin, 0.0)
        if sell_qty - available_qty > 1e-8:
            raise ValueError("insufficient coin balance")
        sell_qty = min(sell_qty, available_qty)

        gross = sell_qty * current_price
        fee = gross * self._fee_rate
        net = gross - fee

        next_qty = available_qty - sell_qty
        self._coin_balances[coin] = max(next_qty, 0.0)
        if self._coin_balances[coin] <= 0:
            self._avg_buy_prices[coin] = 0.0
        self._krw_balance += net

        order = {
            "uuid": str(uuid4()),
            "identifier": identifier,
            "market": market,
            "side": "sell",
            "ord_type": "market",
            "price": current_price,
            "executed_volume": sell_qty,
            "volume": sell_qty,
            "paid_fee": fee,
            "created_at": self._current_time.isoformat(),
        }
        self.trade_log.append(order)
        return order

    @staticmethod
    def _coin_from_market(market: str) -> str:
        value = str(market or "").strip().upper()
        if "-" in value:
            return value.split("-", 1)[1]
        return value

    @staticmethod
    def _to_float(value: str | float | int | None) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
