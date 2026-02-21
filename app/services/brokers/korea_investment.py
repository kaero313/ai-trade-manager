import logging
from typing import Any

from app.services.brokers.base import BaseBrokerClient

logger = logging.getLogger(__name__)


class KoreaInvestmentBroker(BaseBrokerClient):
    async def get_accounts(self) -> list[dict[str, Any]]:
        logger.warning("Not implemented")
        return []

    async def get_ticker(self, markets: list[str]) -> list[dict[str, Any]]:
        logger.warning("Not implemented")
        return []

    async def get_orders_open(
        self,
        market: str | None = None,
        states: list[str] | None = None,
        page: int | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> Any:
        logger.warning("Not implemented")
        return {}

    async def get_orders_closed(
        self,
        market: str | None = None,
        states: list[str] | None = None,
        page: int | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> Any:
        logger.warning("Not implemented")
        return {}

    async def create_order(
        self,
        market: str,
        side: str,
        ord_type: str,
        volume: str | None = None,
        price: str | None = None,
        identifier: str | None = None,
    ) -> Any:
        logger.warning("Not implemented")
        return {}

    async def cancel_order(
        self,
        uuid_: str | None = None,
        identifier: str | None = None,
    ) -> Any:
        logger.warning("Not implemented")
        return {}
