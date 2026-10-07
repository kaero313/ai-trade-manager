import asyncio

import httpx
import pytest

from app.services.brokers.upbit import UpbitBroker


def test_create_order_rejects_blank_identifier_before_request(monkeypatch) -> None:
    broker = UpbitBroker()
    request_called = False

    async def fake_request(*_args, **_kwargs):
        nonlocal request_called
        request_called = True
        return {}

    monkeypatch.setattr(broker, "_request", fake_request)

    with pytest.raises(ValueError, match="identifier is required"):
        asyncio.run(
            broker.create_order(
                market="KRW-BTC",
                side="bid",
                ord_type="price",
                price="10000",
                identifier="   ",
            )
        )

    assert request_called is False


def test_create_order_posts_only_once_when_timeout_occurs(monkeypatch) -> None:
    broker = UpbitBroker()
    request_count = 0

    async def fake_request(*_args, **_kwargs):
        nonlocal request_count
        request_count += 1
        raise httpx.ReadTimeout("응답 시간 초과")

    monkeypatch.setattr(broker, "_request", fake_request)

    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(
            broker.create_order(
                market="KRW-BTC",
                side="bid",
                ord_type="price",
                price="10000",
                identifier="abc123",
            )
        )

    assert request_count == 1


def test_create_order_normalizes_identifier_and_returns_raw_response(monkeypatch) -> None:
    broker = UpbitBroker()
    captured: dict = {}
    expected = {"uuid": "order-1", "identifier": "abc123", "state": "wait"}

    async def fake_request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return expected

    monkeypatch.setattr(broker, "_request", fake_request)

    result = asyncio.run(
        broker.create_order(
            market="KRW-BTC",
            side="bid",
            ord_type="price",
            price="10000",
            identifier="  abc123  ",
        )
    )

    assert result is expected
    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/orders"
    assert captured["json"]["identifier"] == "abc123"


def test_get_order_performs_single_raw_request(monkeypatch) -> None:
    broker = UpbitBroker()
    request_count = 0

    async def fake_request(*_args, **_kwargs):
        nonlocal request_count
        request_count += 1
        raise httpx.ConnectError("연결 실패")

    monkeypatch.setattr(broker, "_request", fake_request)

    with pytest.raises(httpx.ConnectError):
        asyncio.run(broker.get_order(identifier="abc123"))

    assert request_count == 1
