
import pytest

from app.services.trading.ai_executor import _resolve_order_price
from app.services.trading.ai_executor import _resolve_order_qty


def test_quote_amount_bid_uses_trade_vwap_not_order_amount() -> None:
    order_result = {
        "side": "bid",
        "ord_type": "price",
        "price": "10000",
        "executed_volume": "0.0001",
        "trades": [
            {"price": "100000000", "volume": "0.00005", "funds": "5000"},
            {"price": "100500000", "volume": "0.00005", "funds": "5025"},
        ],
    }

    assert _resolve_order_price(order_result, 112_000_000, side="buy") == pytest.approx(
        100_250_000
    )
    assert _resolve_order_qty(order_result, 0) == pytest.approx(0.0001)


def test_quote_amount_bid_without_trade_ignores_requested_krw_price() -> None:
    order_result = {
        "side": "bid",
        "ord_type": "price",
        "price": "10000",
    }

    assert _resolve_order_price(order_result, 112_000_000, side="buy") == 112_000_000
