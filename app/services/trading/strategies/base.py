from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.services.brokers.base import BaseBrokerClient


@dataclass(slots=True)
class StrategyExecutionResult:
    executed: bool = False
    side: str | None = None
    order_result: dict[str, Any] | None = None
    reason: str | None = None
    executed_price: float = 0.0
    executed_qty: float = 0.0
    cooldown_until: datetime | None = None


class BaseTradingStrategy(Protocol):
    async def execute(
        self,
        current_price: float,
        broker: BaseBrokerClient,
        current_time: datetime | None = None,
    ) -> StrategyExecutionResult:
        ...
