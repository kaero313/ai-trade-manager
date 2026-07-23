from typing import Any

from app.services.brokers.base import BaseBrokerClient

_NOT_IMPLEMENTED_MESSAGE = (
    "KoreaInvestmentBroker는 아직 구현되지 않았습니다. "
    "빈 응답으로 위장하지 않도록 모든 호출을 fail-closed로 거부합니다."
)


class KoreaInvestmentBroker(BaseBrokerClient):
    """미구현 placeholder. 실수로 선택되어도 조용히 빈 데이터를 반환하지 않는다."""

    async def get_accounts(self) -> list[dict[str, Any]]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    async def get_ticker(self, markets: list[str]) -> list[dict[str, Any]]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    async def get_all_markets(self) -> list[dict[str, Any]]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    async def get_candles(
        self,
        market: str,
        timeframe: str,
        count: int,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    async def get_orders_open(
        self,
        market: str | None = None,
        states: list[str] | None = None,
        page: int | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> Any:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    async def get_orders_closed(
        self,
        market: str | None = None,
        states: list[str] | None = None,
        page: int | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> Any:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    async def create_order(
        self,
        market: str,
        side: str,
        ord_type: str,
        volume: str | None = None,
        price: str | None = None,
        identifier: str | None = None,
    ) -> Any:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)

    async def cancel_order(
        self,
        uuid_: str | None = None,
        identifier: str | None = None,
    ) -> Any:
        raise NotImplementedError(_NOT_IMPLEMENTED_MESSAGE)
