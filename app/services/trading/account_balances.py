from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

MINIMUM_KRW_ORDER_VALUE = Decimal("5000")

TargetResultCode = Literal[
    "READY",
    "DUST_REMAINING",
    "LOCKED_REMAINING",
    "UNSUPPORTED_MARKET",
]


class AccountBalanceValidationError(ValueError):
    """거래소 계좌 잔고 응답을 신뢰할 수 없을 때 발생합니다."""


def decimal_string(value: Decimal) -> str:
    """지수 표기 없이 JSON 스냅샷에 저장할 Decimal 문자열을 반환합니다."""
    if value.is_zero():
        return "0"
    return format(value, "f")


def _required_nonnegative_decimal(
    row: Mapping[str, Any],
    field: str,
    *,
    currency: str,
) -> Decimal:
    if field not in row:
        raise AccountBalanceValidationError(f"{currency} 계좌에 {field} 값이 없습니다.")

    value = row[field]
    if value is None or isinstance(value, bool) or not str(value).strip():
        raise AccountBalanceValidationError(f"{currency} 계좌의 {field} 값이 비어 있습니다.")

    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AccountBalanceValidationError(
            f"{currency} 계좌의 {field} 값이 Decimal 형식이 아닙니다."
        ) from exc

    if not parsed.is_finite() or parsed < 0:
        raise AccountBalanceValidationError(
            f"{currency} 계좌의 {field} 값은 유한한 0 이상의 수여야 합니다."
        )
    return Decimal("0") if parsed.is_zero() else parsed


@dataclass(frozen=True, slots=True)
class AccountBalance:
    currency: str
    balance: Decimal
    locked: Decimal

    @property
    def available_volume(self) -> Decimal:
        """Upbit의 balance는 이미 주문 가능한 수량이므로 locked를 다시 차감하지 않습니다."""
        return self.balance

    def to_snapshot(self) -> dict[str, str]:
        return {
            "currency": self.currency,
            "balance": decimal_string(self.balance),
            "locked": decimal_string(self.locked),
        }


@dataclass(frozen=True, slots=True)
class LiquidationTargetCandidate:
    currency: str
    market: str
    balance: Decimal
    locked: Decimal
    requested_volume: Decimal
    ticker_price: Decimal | None
    estimated_value_krw: Decimal | None
    result_code: TargetResultCode

    @property
    def should_submit(self) -> bool:
        return self.result_code == "READY"

    def to_snapshot(self) -> dict[str, str | None]:
        return {
            "currency": self.currency,
            "market": self.market,
            "balance": decimal_string(self.balance),
            "locked": decimal_string(self.locked),
            "requested_volume": decimal_string(self.requested_volume),
            "ticker_price": (
                decimal_string(self.ticker_price) if self.ticker_price is not None else None
            ),
            "estimated_value_krw": (
                decimal_string(self.estimated_value_krw)
                if self.estimated_value_krw is not None
                else None
            ),
            "result_code": self.result_code,
        }


def parse_account_balances(rows: Iterable[Mapping[str, Any]]) -> tuple[AccountBalance, ...]:
    """Upbit 계좌 응답 전체를 검증하고 통화 순서로 정렬합니다."""
    balances: list[AccountBalance] = []
    seen_currencies: set[str] = set()

    for row in rows:
        if not isinstance(row, Mapping):
            raise AccountBalanceValidationError("계좌 잔고 항목은 객체여야 합니다.")

        raw_currency = row.get("currency")
        if not isinstance(raw_currency, str) or not raw_currency.strip():
            raise AccountBalanceValidationError("계좌 잔고의 currency 값이 필요합니다.")
        currency = raw_currency.strip()
        if currency != currency.upper():
            raise AccountBalanceValidationError(
                f"계좌 잔고의 currency는 대문자여야 합니다: {currency}"
            )
        if currency in seen_currencies:
            raise AccountBalanceValidationError(f"중복된 계좌 통화가 있습니다: {currency}")

        balance = _required_nonnegative_decimal(row, "balance", currency=currency)
        locked = _required_nonnegative_decimal(row, "locked", currency=currency)
        balances.append(AccountBalance(currency=currency, balance=balance, locked=locked))
        seen_currencies.add(currency)

    return tuple(sorted(balances, key=lambda item: item.currency))


def parse_non_krw_account_balances(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[AccountBalance, ...]:
    """전체 응답을 먼저 검증한 뒤 KRW를 제외한 자산만 반환합니다."""
    return tuple(item for item in parse_account_balances(rows) if item.currency != "KRW")


def build_liquidation_target_candidates(
    balances: Iterable[AccountBalance],
    *,
    active_krw_markets: Collection[str],
    ticker_prices: Mapping[str, Decimal],
    minimum_order_value: Decimal = MINIMUM_KRW_ORDER_VALUE,
) -> tuple[LiquidationTargetCandidate, ...]:
    """외부 호출 없이 검증된 잔고를 청산 주문 후보로 분류합니다."""
    if (
        not isinstance(minimum_order_value, Decimal)
        or not minimum_order_value.is_finite()
        or minimum_order_value <= 0
    ):
        raise AccountBalanceValidationError("최소 주문 금액은 0보다 큰 유한 Decimal이어야 합니다.")

    normalized_markets = {str(market).strip().upper() for market in active_krw_markets}
    candidates: list[LiquidationTargetCandidate] = []

    for account in balances:
        if account.currency == "KRW":
            continue
        if account.balance == 0 and account.locked == 0:
            continue

        market = f"KRW-{account.currency}"
        requested_volume = account.available_volume
        if requested_volume == 0 and account.locked > 0:
            candidates.append(
                LiquidationTargetCandidate(
                    currency=account.currency,
                    market=market,
                    balance=account.balance,
                    locked=account.locked,
                    requested_volume=requested_volume,
                    ticker_price=None,
                    estimated_value_krw=None,
                    result_code="LOCKED_REMAINING",
                )
            )
            continue

        if market not in normalized_markets:
            candidates.append(
                LiquidationTargetCandidate(
                    currency=account.currency,
                    market=market,
                    balance=account.balance,
                    locked=account.locked,
                    requested_volume=requested_volume,
                    ticker_price=None,
                    estimated_value_krw=None,
                    result_code="UNSUPPORTED_MARKET",
                )
            )
            continue

        ticker_price = ticker_prices.get(market)
        if (
            not isinstance(ticker_price, Decimal)
            or not ticker_price.is_finite()
            or ticker_price <= 0
        ):
            raise AccountBalanceValidationError(
                f"{market} 현재가는 0보다 큰 유한 Decimal이어야 합니다."
            )

        estimated_value = requested_volume * ticker_price
        result_code: TargetResultCode = (
            "DUST_REMAINING"
            if estimated_value < minimum_order_value
            else "READY"
        )
        candidates.append(
            LiquidationTargetCandidate(
                currency=account.currency,
                market=market,
                balance=account.balance,
                locked=account.locked,
                requested_volume=requested_volume,
                ticker_price=ticker_price,
                estimated_value_krw=estimated_value,
                result_code=result_code,
            )
        )

    return tuple(sorted(candidates, key=lambda item: item.market))
