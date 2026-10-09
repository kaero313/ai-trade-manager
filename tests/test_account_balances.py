from decimal import Decimal

import pytest

from app.schemas.portfolio import AssetItem
from app.services.trading.account_balances import (
    AccountBalanceValidationError,
    build_liquidation_target_candidates,
    parse_account_balances,
    parse_non_krw_account_balances,
)
from app.services.trading.ai_executor import _available_amount


def _asset_item(*, balance: float, locked: float) -> AssetItem:
    return AssetItem(
        broker="UPBIT",
        currency="BTC",
        balance=balance,
        locked=locked,
        avg_buy_price=0,
        current_price=0,
        total_value=0,
        pnl_percentage=0,
    )


def test_account_balances_are_strict_decimals_and_snapshot_strings() -> None:
    balances = parse_account_balances(
        [
            {"currency": "KRW", "balance": "1E+4", "locked": "0"},
            {"currency": "BTC", "balance": "0.10000000", "locked": "1E-8"},
        ]
    )

    assert [item.currency for item in balances] == ["BTC", "KRW"]
    assert balances[0].available_volume == Decimal("0.10000000")
    assert balances[0].to_snapshot() == {
        "currency": "BTC",
        "balance": "0.10000000",
        "locked": "0.00000001",
    }
    assert balances[1].to_snapshot()["balance"] == "10000"


def test_non_krw_filter_still_validates_the_full_account_response() -> None:
    with pytest.raises(AccountBalanceValidationError, match="KRW.*locked"):
        parse_non_krw_account_balances(
            [
                {"currency": "BTC", "balance": "1", "locked": "0"},
                {"currency": "KRW", "balance": "10000"},
            ]
        )


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"balance": "1", "locked": "0"}, "currency"),
        ({"currency": "btc", "balance": "1", "locked": "0"}, "대문자"),
        ({"currency": "BTC", "locked": "0"}, "balance"),
        ({"currency": "BTC", "balance": "NaN", "locked": "0"}, "유한"),
        ({"currency": "BTC", "balance": "1", "locked": "Infinity"}, "유한"),
        ({"currency": "BTC", "balance": "-1", "locked": "0"}, "0 이상의"),
        ({"currency": "BTC", "balance": "1", "locked": -1}, "0 이상의"),
    ],
)
def test_invalid_account_values_are_rejected(row: dict[str, object], message: str) -> None:
    with pytest.raises(AccountBalanceValidationError, match=message):
        parse_account_balances([row])


def test_duplicate_currency_is_rejected() -> None:
    row = {"currency": "BTC", "balance": "1", "locked": "0"}

    with pytest.raises(AccountBalanceValidationError, match="중복.*BTC"):
        parse_account_balances([row, row])


def test_target_uses_balance_without_subtracting_locked() -> None:
    balances = parse_non_krw_account_balances(
        [{"currency": "BTC", "balance": "10", "locked": "3"}]
    )

    targets = build_liquidation_target_candidates(
        balances,
        active_krw_markets={"KRW-BTC"},
        ticker_prices={"KRW-BTC": Decimal("1000")},
    )

    assert len(targets) == 1
    target = targets[0]
    assert target.should_submit is True
    assert target.requested_volume == Decimal("10")
    assert target.estimated_value_krw == Decimal("10000")
    assert target.to_snapshot() == {
        "currency": "BTC",
        "market": "KRW-BTC",
        "balance": "10",
        "locked": "3",
        "requested_volume": "10",
        "ticker_price": "1000",
        "estimated_value_krw": "10000",
        "result_code": "READY",
    }


def test_targets_classify_dust_unsupported_and_locked_assets() -> None:
    balances = parse_non_krw_account_balances(
        [
            {"currency": "BTC", "balance": "0.00001", "locked": "0"},
            {"currency": "ETH", "balance": "2", "locked": "0"},
            {"currency": "XRP", "balance": "0", "locked": "3"},
            {"currency": "ZERO", "balance": "0", "locked": "0"},
        ]
    )

    targets = build_liquidation_target_candidates(
        balances,
        active_krw_markets={"KRW-BTC", "KRW-XRP"},
        ticker_prices={"KRW-BTC": Decimal("100000000")},
    )

    assert [(item.currency, item.result_code) for item in targets] == [
        ("BTC", "DUST_REMAINING"),
        ("ETH", "UNSUPPORTED_MARKET"),
        ("XRP", "LOCKED_REMAINING"),
    ]
    assert targets[0].estimated_value_krw == Decimal("1000.00000")
    assert targets[1].estimated_value_krw is None
    assert targets[2].requested_volume == 0


@pytest.mark.parametrize("ticker", [None, Decimal("0"), Decimal("NaN"), "1000"])
def test_active_market_requires_positive_finite_decimal_ticker(ticker: object) -> None:
    balances = parse_non_krw_account_balances(
        [{"currency": "BTC", "balance": "1", "locked": "0"}]
    )

    with pytest.raises(AccountBalanceValidationError, match="현재가"):
        build_liquidation_target_candidates(
            balances,
            active_krw_markets={"KRW-BTC"},
            ticker_prices={"KRW-BTC": ticker},  # type: ignore[dict-item]
        )


def test_ai_executor_available_amount_uses_balance_itself() -> None:
    assert _available_amount(_asset_item(balance=10, locked=3)) == 10
    assert _available_amount(_asset_item(balance=-1, locked=3)) == 0
    assert _available_amount(None) == 0
