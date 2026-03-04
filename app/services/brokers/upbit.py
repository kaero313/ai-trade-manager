import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlencode

import httpx
import jwt
from tenacity import RetryCallState, retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.services.brokers.base import BaseBrokerClient

logger = logging.getLogger(__name__)
UPBIT_MINUTE_CANDLE_UNITS = {1, 3, 5, 10, 15, 30, 60, 240}


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


def _error_text(exc: UpbitAPIError) -> str:
    parts = [
        str(exc.error_name or ""),
        str(exc.message or ""),
        str(exc.detail or ""),
    ]
    return " ".join(parts).lower()


def is_critical_upbit_error(exc: UpbitAPIError) -> bool:
    if exc.status_code in {401, 403}:
        return True

    text = _error_text(exc)
    auth_keywords = (
        "invalid_access_key",
        "expired_access_key",
        "jwt",
        "signature",
        "api key",
        "access key",
        "인증",
        "권한",
    )
    balance_keywords = (
        "insufficient",
        "insufficient_funds",
        "under_min_total",
        "잔고",
        "부족",
    )

    return any(keyword in text for keyword in (*auth_keywords, *balance_keywords))


def format_upbit_critical_message(exc: UpbitAPIError) -> str:
    text = _error_text(exc)

    auth_keywords = (
        "invalid_access_key",
        "expired_access_key",
        "jwt",
        "signature",
        "api key",
        "access key",
        "인증",
        "권한",
    )
    if exc.status_code in {401, 403} or any(keyword in text for keyword in auth_keywords):
        return "업비트 API 키 또는 권한 설정이 올바르지 않습니다."

    balance_keywords = ("insufficient", "insufficient_funds", "잔고", "부족", "under_min_total")
    if any(keyword in text for keyword in balance_keywords):
        return "업비트 잔고가 부족합니다."

    detail_message = exc.message or str(exc.detail or "")
    if detail_message:
        return f"업비트 치명적 오류: {detail_message}"
    return f"업비트 치명적 오류가 발생했습니다. (status={exc.status_code})"


def _is_retryable_api_exception(exc: BaseException) -> bool:
    if isinstance(exc, httpx.RequestError):
        return True

    if isinstance(exc, UpbitAPIError):
        return exc.status_code == 429 or 500 <= exc.status_code < 600

    return False


def _is_retryable_order_exception(exc: BaseException) -> bool:
    return isinstance(exc, httpx.TimeoutException)


def _log_retry_warning(retry_state: RetryCallState) -> None:
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    if exception is None:
        return

    function_name = retry_state.fn.__name__ if retry_state.fn else "unknown"
    next_sleep = retry_state.next_action.sleep if retry_state.next_action else None
    if next_sleep is None:
        logger.warning(
            "Upbit API 재시도 예정: fn=%s attempt=%s error=%s",
            function_name,
            retry_state.attempt_number,
            exception,
        )
        return

    logger.warning(
        "Upbit API 재시도 예정: fn=%s attempt=%s error=%s next_wait=%.1fs",
        function_name,
        retry_state.attempt_number,
        exception,
        next_sleep,
    )


def _normalize_params(params: dict[str, Any] | list[tuple[str, Any]] | None) -> list[tuple[str, Any]]:
    if params is None:
        return []
    if isinstance(params, list):
        return [item for item in params if len(item) == 2 and item[1] is not None]

    items: list[tuple[str, Any]] = []
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            list_key = key if key.endswith("[]") else f"{key}[]"
            for item in value:
                if item is None:
                    continue
                items.append((list_key, item))
        else:
            items.append((key, value))
    return items


def _build_query_string(params: dict[str, Any] | list[tuple[str, Any]] | None) -> str:
    items = _normalize_params(params)
    if not items:
        return ""
    # Upbit query_hash expects non-percent-encoded query form (e.g. states[]=wait).
    return unquote(urlencode(items, doseq=True))


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


class UpbitBroker(BaseBrokerClient):
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

    @staticmethod
    def _resolve_candle_path(timeframe: str) -> str:
        normalized = str(timeframe or "").strip().lower()
        if normalized in {"day", "days"}:
            return "/v1/candles/days"
        if normalized in {"week", "weeks"}:
            return "/v1/candles/weeks"
        if normalized in {"month", "months"}:
            return "/v1/candles/months"

        minute_match = re.fullmatch(r"(\d+)m", normalized)
        if minute_match:
            unit = int(minute_match.group(1))
            if unit not in UPBIT_MINUTE_CANDLE_UNITS:
                raise ValueError(
                    f"Unsupported minute timeframe: {timeframe}. "
                    f"Supported units: {sorted(UPBIT_MINUTE_CANDLE_UNITS)}"
                )
            return f"/v1/candles/minutes/{unit}"

        raise ValueError(f"Unsupported timeframe: {timeframe}")

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

        normalized_params = _normalize_params(params) if params is not None else None
        query_params_for_hash = normalized_params if normalized_params is not None else json_payload
        query_string = _build_query_string(query_params_for_hash)
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
                params=normalized_params,
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

    @retry(
        retry=retry_if_exception(_is_retryable_api_exception),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(5),
        before_sleep=_log_retry_warning,
        reraise=True,
    )
    async def get_all_markets(self) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            "/v1/market/all",
            params={"isDetails": "false"},
            auth=False,
        )

    @retry(
        retry=retry_if_exception(_is_retryable_api_exception),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(5),
        before_sleep=_log_retry_warning,
        reraise=True,
    )
    async def get_candles(
        self,
        market: str,
        timeframe: str,
        count: int,
    ) -> list[dict[str, Any]]:
        market_symbol = str(market or "").strip().upper()
        if not market_symbol:
            raise ValueError("market is required")
        if count < 1 or count > 200:
            raise ValueError("count must be between 1 and 200")

        candle_path = self._resolve_candle_path(timeframe)
        return await self._request(
            "GET",
            candle_path,
            params={"market": market_symbol, "count": count},
            auth=False,
        )

    async def get_markets(self) -> list[dict[str, Any]]:
        return await self.get_all_markets()

    async def get_candles_1h(self, market: str, count: int = 200) -> list[dict[str, Any]]:
        return await self.get_candles(market=market, timeframe="60m", count=count)

    @retry(
        retry=retry_if_exception(_is_retryable_api_exception),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(5),
        before_sleep=_log_retry_warning,
        reraise=True,
    )
    async def get_ticker(self, markets: list[str]) -> list[dict[str, Any]]:
        joined = ",".join(markets)
        return await self._request(
            "GET",
            "/v1/ticker",
            params={"markets": joined},
            auth=False,
        )

    @retry(
        retry=retry_if_exception(_is_retryable_api_exception),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(5),
        before_sleep=_log_retry_warning,
        reraise=True,
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

    @retry(
        retry=retry_if_exception(_is_retryable_order_exception),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(5),
        before_sleep=_log_retry_warning,
        reraise=True,
    )
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

    @retry(
        retry=retry_if_exception(_is_retryable_api_exception),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(5),
        before_sleep=_log_retry_warning,
        reraise=True,
    )
    async def cancel_order(self, uuid_: str | None = None, identifier: str | None = None) -> Any:
        if not uuid_ and not identifier:
            raise ValueError("uuid_ or identifier is required")
        params = {"uuid": uuid_, "identifier": identifier}
        return await self._request("DELETE", "/v1/order", params=params, auth=True)


upbit_broker = UpbitBroker(
    base_url=settings.upbit_base_url,
    access_key=settings.upbit_access_key,
    secret_key=settings.upbit_secret_key,
    timeout=settings.upbit_timeout,
)
