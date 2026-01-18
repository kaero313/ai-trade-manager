import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class UpbitClient:
    def __init__(self, base_url: str = "https://api.upbit.com") -> None:
        self.base_url = base_url

    async def get_markets(self) -> list[dict[str, Any]]:
        url = f"{self.base_url}/v1/market/all"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params={"isDetails": "false"})
            resp.raise_for_status()
            return resp.json()

    async def get_candles_1h(self, market: str, count: int = 200) -> list[dict[str, Any]]:
        url = f"{self.base_url}/v1/candles/minutes/60"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params={"market": market, "count": count})
            resp.raise_for_status()
            return resp.json()


upbit_client = UpbitClient()
