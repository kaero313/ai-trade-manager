import asyncio

import httpx
import pytest

from app.services.brokers.upbit import UpbitBroker, _build_query_string


def test_cancel_orders_by_ids_serializes_uuids_array(monkeypatch) -> None:
    broker = UpbitBroker()
    captured: dict = {}
    expected = [{"uuid": "order-1", "state": "cancel"}]

    async def fake_request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return expected

    monkeypatch.setattr(broker, "_request", fake_request)

    result = asyncio.run(broker.cancel_orders_by_ids([" order-1 ", "order-2"]))

    assert result is expected
    assert captured == {
        "method": "DELETE",
        "path": "/v1/orders/uuids",
        "params": {"uuids[]": ["order-1", "order-2"]},
        "auth": True,
    }
    assert _build_query_string(captured["params"]) == "uuids[]=order-1&uuids[]=order-2"


def test_cancel_orders_by_ids_accepts_twenty_items(monkeypatch) -> None:
    broker = UpbitBroker()
    requested_uuids = [f"order-{index}" for index in range(20)]
    captured: dict = {}

    async def fake_request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return []

    monkeypatch.setattr(broker, "_request", fake_request)

    asyncio.run(broker.cancel_orders_by_ids(requested_uuids))

    assert captured["params"] == {"uuids[]": requested_uuids}


@pytest.mark.parametrize(
    ("uuids", "message"),
    [
        ([], "between 1 and 20"),
        ([f"order-{index}" for index in range(21)], "between 1 and 20"),
        (["order-1", "   "], "blank"),
        (["order-1", " order-1 "], "duplicates"),
    ],
)
def test_cancel_orders_by_ids_rejects_invalid_input_before_request(
    monkeypatch,
    uuids: list[str],
    message: str,
) -> None:
    broker = UpbitBroker()
    request_called = False

    async def fake_request(*_args, **_kwargs):
        nonlocal request_called
        request_called = True
        return []

    monkeypatch.setattr(broker, "_request", fake_request)

    with pytest.raises(ValueError, match=message):
        asyncio.run(broker.cancel_orders_by_ids(uuids))

    assert request_called is False


@pytest.mark.parametrize(
    "cancel",
    [
        lambda broker: broker.cancel_order(uuid_="order-1"),
        lambda broker: broker.cancel_orders_by_ids(["order-1", "order-2"]),
    ],
)
def test_order_cancellation_performs_single_request_on_timeout(monkeypatch, cancel) -> None:
    broker = UpbitBroker()
    request_count = 0

    async def fake_request(*_args, **_kwargs):
        nonlocal request_count
        request_count += 1
        raise httpx.ReadTimeout("응답 시간 초과")

    monkeypatch.setattr(broker, "_request", fake_request)

    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(cancel(broker))

    assert request_count == 1
