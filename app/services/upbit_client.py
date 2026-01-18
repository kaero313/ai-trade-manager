import hashlib
import logging
import uuid
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import settings

logger = logging.getLogger(__name__)


class UpbitAPIError(Exception):
    def __init__(
        self,
        status_code: int,
        detail: Any,
        error_name: str | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.error_name = error_name
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status_code": self.status_code}
        if self.error_name:
            payload["error_name"] = self.error_name
        if self.message:
            payload["message"] = self.message
        payload["detail"] = self.detail
        return payload


def _normalize_params(params: dict[str, Any] | list[tuple[str, Any]] | None) -> list[tuple[str, Any]]:
    if params is None:
        return []
    if isinstance(params, list):
        return params

    items: list[tuple[str, Any]] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            list_key = key if key.endswith("[]") else f"{key}[]"
            for item in value:
                items.append((list_key, item))
        else:
            items.append((key, value))
    return items


def _build_query_string(params: dict[str, Any] | list[tuple[str, Any]] | None) -> str:
    items = _normalize_params(params)
    if not items:
        return ""
    return urlencode(items, doseq=True)


def _parse_remaining_req(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    parts = [part.strip() for part in value.split(";") if part.strip()]
    parsed: dict[str, str] = {}
    for part in parts:
        if "=" not in part:
            continue
        key, val = part.split("=", 1)
        parsed[key.strip()] = val.strip()
    return parsed or None


class UpbitClient:
    def __init__(
        self,
        base_url: str = "https://api.upbit.com",
        access_key: str | None = None,
        secret_key: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key
        self.timeout = timeout
        self.last_remaining: dict[str, str] | None = None

    def _make_jwt(self, query_string: str | None = None) -> str:
        if not self.access_key or not self.secret_key:
            raise ValueError("Upbit access/secret key not configured")

        payload: dict[str, Any] = {
            "access_key": self.access_key,
            "nonce": str(uuid.uuid4()),
        }

        if query_string:
            query_hash = hashlib.sha512(query_string.encode("utf-8")).hexdigest()
            payload["query_hash"] = query_hash
            payload["query_hash_alg"] = "SHA512"

        token = jwt.encode(payload, self.secret_key, algorithm="HS512")
        return token.decode("utf-8") if isinstance(token, bytes) else token

    def _auth_headers(self, query_string: str | None = None) -> dict[str, str]:
        token = self._make_jwt(query_string)
        return {"Authorization": f"Bearer {token}"}

    def _update_remaining(self, headers: httpx.Headers) -> None:
        remaining = _parse_remaining_req(headers.get("Remaining-Req"))
        if remaining:
            self.last_remaining = remaining

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        json: dict[str, Any] | None = None,
        auth: bool = False,
    ) -> Any:
        if params is not None and json is not None:
            raise ValueError("Use either params or json, not both")

        json_payload = None
        if json is not None:
            json_payload = {key: value for key, value in json.items() if value is not None}

        query_params = params if params is not None else json_payload
        query_string = _build_query_string(query_params)
        headers: dict[str, str] = {
            "Accept": "application/json",
        }
        if json_payload is not None:
            headers["Content-Type"] = "application/json"
        if auth:
            headers.update(self._auth_headers(query_string))

        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.request(
                method,
                url,
                params=_normalize_params(params) if params is not None else None,
                json=json_payload,
                headers=headers,
            )
            self._update_remaining(resp.headers)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail: Any
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text
                error_name = None
                message = None
                if isinstance(detail, dict) and "error" in detail:
                    error = detail.get("error") or {}
                    if isinstance(error, dict):
                        error_name = error.get("name")
                        message = error.get("message")
                logger.error("Upbit API error: %s", detail)
                raise UpbitAPIError(
                    status_code=resp.status_code,
                    detail=detail,
                    error_name=error_name,
                    message=message,
                ) from exc
            return resp.json()

    async def get_markets(self) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/v1/market/all",
            params={"isDetails": "false"},
            auth=False,
        )

    async def get_candles_1h(self, market: str, count: int = 200) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/v1/candles/minutes/60",
            params={"market": market, "count": count},
            auth=False,
        )

    async def get_accounts(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/v1/accounts", auth=True)

    async def get_order(self, uuid_: str | None = None, identifier: str | None = None) -> Any:
        if not uuid_ and not identifier:
            raise ValueError("uuid_ or identifier is required")
        params = {"uuid": uuid_, "identifier": identifier}
        return await self._request("GET", "/v1/order", params=params, auth=True)

    async def get_orders_open(
        self,
        market: str | None = None,
        states: list[str] | None = None,
        page: int | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> Any:
        params = {
            "market": market,
            "states": states,
            "page": page,
            "limit": limit,
            "order_by": order_by,
        }
        return await self._request("GET", "/v1/orders/open", params=params, auth=True)

    async def get_orders_closed(
        self,
        market: str | None = None,
        states: list[str] | None = None,
        page: int | None = None,
        limit: int | None = None,
        order_by: str | None = None,
    ) -> Any:
        params = {
            "market": market,
            "states": states,
            "page": page,
            "limit": limit,
            "order_by": order_by,
        }
        return await self._request("GET", "/v1/orders/closed", params=params, auth=True)

    async def get_orders_by_uuids(
        self,
        uuids: list[str],
        states: list[str] | None = None,
        order_by: str | None = None,
    ) -> Any:
        params = {
            "uuids": uuids,
            "states": states,
            "order_by": order_by,
        }
        return await self._request("GET", "/v1/orders/uuids", params=params, auth=True)

    async def create_order(
        self,
        market: str,
        side: str,
        ord_type: str,
        volume: str | None = None,
        price: str | None = None,
        identifier: str | None = None,
    ) -> Any:
        payload = {
            "market": market,
            "side": side,
            "ord_type": ord_type,
            "volume": volume,
            "price": price,
            "identifier": identifier,
        }
        return await self._request("POST", "/v1/orders", json=payload, auth=True)

    async def cancel_order(self, uuid_: str | None = None, identifier: str | None = None) -> Any:
        if not uuid_ and not identifier:
            raise ValueError("uuid_ or identifier is required")
        params = {"uuid": uuid_, "identifier": identifier}
        return await self._request("DELETE", "/v1/order", params=params, auth=True)


upbit_client = UpbitClient(
    base_url=settings.upbit_base_url,
    access_key=settings.upbit_access_key,
    secret_key=settings.upbit_secret_key,
    timeout=settings.upbit_timeout,
)
