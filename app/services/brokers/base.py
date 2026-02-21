from abc import ABC, abstractmethod
from typing import Any


class BaseBrokerClient(ABC):
    @abstractmethod
    async def get_accounts(self) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def get_ticker(self, markets: list[str]) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def get_orders_open(
        self,
        market: str | None = None,
        states: list[str] | None = None,
        page: int | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> Any:
        pass

    @abstractmethod
    async def get_orders_closed(
        self,
        market: str | None = None,
        states: list[str] | None = None,
        page: int | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> Any:
        pass

    @abstractmethod
    async def create_order(
        self,
        market: str,
        side: str,
        ord_type: str,
        volume: str | None = None,
        price: str | None = None,
        identifier: str | None = None,
    ) -> Any:
        pass

    @abstractmethod
    async def cancel_order(
        self,
        uuid_: str | None = None,
        identifier: str | None = None,
    ) -> Any:
        pass
