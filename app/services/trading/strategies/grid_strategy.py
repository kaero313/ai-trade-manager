from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.brokers.base import BaseBrokerClient
from app.services.trading.strategies.base import StrategyExecutionResult


class GridStrategy:
    def __init__(
        self,
        market: str,
        target_coin: str,
        grid_upper_bound: float,
        grid_lower_bound: float,
        grid_order_krw: float,
        grid_sell_pct: float,
        grid_cooldown_seconds: int,
        cooldown_until: datetime | None = None,
    ) -> None:
        self.market = str(market or "").strip().upper()
        self.target_coin = str(target_coin or "").strip().upper()
        self.grid_upper_bound = float(grid_upper_bound)
        self.grid_lower_bound = float(grid_lower_bound)
        self.grid_order_krw = float(grid_order_krw)
        self.grid_sell_pct = float(grid_sell_pct)
        self.grid_cooldown_seconds = max(int(grid_cooldown_seconds), 1)
        self.cooldown_until = cooldown_until

    async def execute(
        self,
        current_price: float,
        broker: BaseBrokerClient,
        current_time: datetime | None = None,
    ) -> StrategyExecutionResult:
        now_utc = current_time.astimezone(timezone.utc) if current_time else datetime.now(timezone.utc)

        if self.cooldown_until is not None and self.cooldown_until > now_utc:
            return StrategyExecutionResult(
                executed=False,
                reason="cooldown",
                cooldown_until=self.cooldown_until,
            )

        if current_price > self.grid_upper_bound:
            return await self._execute_sell(current_price=current_price, broker=broker, now_utc=now_utc)

        if current_price < self.grid_lower_bound:
            return await self._execute_buy(current_price=current_price, broker=broker, now_utc=now_utc)

        return StrategyExecutionResult(executed=False, reason="no_signal")

    async def _execute_buy(
        self,
        current_price: float,
        broker: BaseBrokerClient,
        now_utc: datetime,
    ) -> StrategyExecutionResult:
        if self.grid_order_krw <= 0:
            return StrategyExecutionResult(executed=False, reason="invalid_grid_order_krw")

        raw_order = await broker.create_order(
            market=self.market,
            side="bid",
            ord_type="price",
            price=self._fmt_number(self.grid_order_krw),
        )
        order_result = raw_order if isinstance(raw_order, dict) else {}

        executed_price = self._extract_price(order_result, fallback=current_price)
        executed_qty = self._extract_qty(order_result)
        if executed_qty <= 0 and current_price > 0:
            executed_qty = self.grid_order_krw / current_price

        self.cooldown_until = now_utc + timedelta(seconds=self.grid_cooldown_seconds)
        return StrategyExecutionResult(
            executed=True,
            side="buy",
            order_result=order_result,
            executed_price=executed_price,
            executed_qty=executed_qty,
            cooldown_until=self.cooldown_until,
        )

    async def _execute_sell(
        self,
        current_price: float,
        broker: BaseBrokerClient,
        now_utc: datetime,
    ) -> StrategyExecutionResult:
        accounts = await broker.get_accounts()
        available_qty = self._get_available_coin(accounts=accounts, coin=self.target_coin)
        if available_qty <= 0:
            return StrategyExecutionResult(executed=False, reason="insufficient_coin_balance")

        sell_ratio = self.grid_sell_pct / 100.0 if self.grid_sell_pct > 1 else self.grid_sell_pct
        sell_ratio = min(max(sell_ratio, 0.0), 1.0)
        if sell_ratio <= 0:
            return StrategyExecutionResult(executed=False, reason="invalid_grid_sell_pct")

        sell_volume = available_qty * sell_ratio
        if sell_volume <= 0:
            return StrategyExecutionResult(executed=False, reason="invalid_sell_volume")

        raw_order = await broker.create_order(
            market=self.market,
            side="ask",
            ord_type="market",
            volume=self._fmt_number(sell_volume),
        )
        order_result = raw_order if isinstance(raw_order, dict) else {}

        executed_price = self._extract_price(order_result, fallback=current_price)
        executed_qty = self._extract_qty(order_result)
        if executed_qty <= 0:
            executed_qty = sell_volume

        self.cooldown_until = now_utc + timedelta(seconds=self.grid_cooldown_seconds)
        return StrategyExecutionResult(
            executed=True,
            side="sell",
            order_result=order_result,
            executed_price=executed_price,
            executed_qty=executed_qty,
            cooldown_until=self.cooldown_until,
        )

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _extract_price(self, order_result: dict[str, Any], fallback: float) -> float:
        for key in ("price", "avg_price"):
            parsed = self._to_float(order_result.get(key))
            if parsed > 0:
                return parsed
        return fallback

    def _extract_qty(self, order_result: dict[str, Any]) -> float:
        for key in ("executed_volume", "volume"):
            parsed = self._to_float(order_result.get(key))
            if parsed > 0:
                return parsed
        return 0.0

    @staticmethod
    def _get_available_coin(accounts: list[dict[str, Any]], coin: str) -> float:
        normalized_coin = str(coin or "").strip().upper()
        for account in accounts:
            currency = str(account.get("currency") or "").strip().upper()
            if currency != normalized_coin:
                continue

            try:
                balance = float(account.get("balance") or 0)
            except (TypeError, ValueError):
                balance = 0.0
            try:
                locked = float(account.get("locked") or 0)
            except (TypeError, ValueError):
                locked = 0.0
            return max(balance - locked, 0.0)
        return 0.0

    @staticmethod
    def _fmt_number(value: float) -> str:
        return f"{value:.8f}".rstrip("0").rstrip(".") or "0"
