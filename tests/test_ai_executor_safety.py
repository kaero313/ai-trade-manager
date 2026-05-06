from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.api.routes.ai import _is_probable_legacy_quote_amount_buy
from app.services.trading.ai_executor import _apply_live_position_fill
from app.services.trading.ai_executor import _parse_bool_config
from app.services.trading.ai_executor import _resolve_order_price
from app.services.trading.ai_executor import _resolve_order_qty
from app.services.trading.ai_executor import _resolve_weighted_amount


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


def test_live_position_fill_updates_quantity_and_average_price() -> None:
    position = SimpleNamespace(avg_entry_price=100.0, quantity=2.0, status="open")

    _apply_live_position_fill(position, side="buy", price=200.0, qty=1.0)

    assert position.quantity == pytest.approx(3.0)
    assert position.avg_entry_price == pytest.approx(133.3333333333)
    assert position.status == "open"

    _apply_live_position_fill(position, side="sell", price=150.0, qty=2.5)

    assert position.quantity == pytest.approx(0.5)
    assert position.status == "open"

    _apply_live_position_fill(position, side="sell", price=150.0, qty=1.0)

    assert position.quantity == 0.0
    assert position.status == "closed"


def test_buy_weight_cap_uses_effective_weight() -> None:
    assert _resolve_weighted_amount(100_000, 40) == 40_000
    assert min(100, 40.0) == 40.0


def test_bool_config_defaults_to_live_buy_locked() -> None:
    assert _parse_bool_config("true", default=False) is True
    assert _parse_bool_config("false", default=True) is False
    assert _parse_bool_config(None, default=False) is False


def test_legacy_quote_amount_buy_is_excluded_only_before_cutoff() -> None:
    legacy_order = SimpleNamespace(
        side="buy",
        ai_analysis_log_id=1,
        executed_at=datetime(2026, 4, 28, 1, 0, tzinfo=UTC),
        price=10000.0,
        qty=1.0,
    )
    fixed_order = SimpleNamespace(
        side="buy",
        ai_analysis_log_id=1,
        executed_at=datetime(2026, 4, 30, 8, 0, tzinfo=UTC),
        price=10000.0,
        qty=1.0,
    )

    assert _is_probable_legacy_quote_amount_buy(legacy_order) is True
    assert _is_probable_legacy_quote_amount_buy(fixed_order) is False
