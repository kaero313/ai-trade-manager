import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.schemas.portfolio import AssetItem, PortfolioSummary
from app.services.trading import ai_executor
from app.services.trading.live_order_execution import LiveOrderRequest, LiveOrderResult


class _TrackingDb:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class _FakeLiveOrderService:
    def __init__(self) -> None:
        self.requests: list[LiveOrderRequest] = []

    async def execute(self, request: LiveOrderRequest) -> LiveOrderResult:
        self.requests.append(request)
        return LiveOrderResult(
            intent_id=101,
            identifier="a" * 32,
            submission_status="ACCEPTED",
            exchange_uuid="upbit-order-101",
            exchange_state="wait",
            projection_status="PENDING",
            order_history_id=None,
            error_code=None,
            error_message=None,
        )


def _asset(
    currency: str,
    *,
    balance: float,
    current_price: float,
    total_value: float,
) -> AssetItem:
    return AssetItem(
        broker="UPBIT",
        currency=currency,
        balance=balance,
        locked=0,
        avg_buy_price=current_price,
        current_price=current_price,
        total_value=total_value,
        pnl_percentage=0,
    )


def _portfolio(*, total_net_worth: float = 100_000) -> PortfolioSummary:
    return PortfolioSummary(
        total_net_worth=total_net_worth,
        total_pnl=0,
        items=[
            _asset(
                "KRW",
                balance=total_net_worth,
                current_price=1,
                total_value=total_net_worth,
            ),
            _asset("BTC", balance=0, current_price=100_000_000, total_value=0),
        ],
    )


def _analysis(*, recommended_weight: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=101,
        confidence=90,
        recommended_weight=recommended_weight,
    )


def _patch_live_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    hard_cap_weight: float,
) -> _FakeLiveOrderService:
    service = _FakeLiveOrderService()

    async def load_max_allocation(_db) -> float:
        return 100.0

    async def load_hard_cap(_db) -> float:
        return hard_cap_weight

    async def ignore_notification(**_kwargs) -> None:
        return None

    monkeypatch.setattr(ai_executor, "_load_max_allocation_pct", load_max_allocation)
    monkeypatch.setattr(ai_executor, "_load_ai_max_buy_weight_pct", load_hard_cap)
    monkeypatch.setattr(
        ai_executor,
        "_build_live_order_execution_service",
        lambda: service,
    )
    monkeypatch.setattr(
        ai_executor,
        "_send_live_order_accepted_notification",
        ignore_notification,
    )
    return service


@pytest.mark.parametrize(
    (
        "primary_recommended_weight",
        "precheck_recommended_weight",
        "hard_cap_weight",
        "expected",
    ),
    [
        (10, 40, 30, 10),
        (40, 15, 30, 15),
        (40, 50, 30, 30),
        (-10, 40, 30, 0),
        (150, 120, 130, 100),
    ],
)
def test_effective_buy_weight_is_reduce_only_and_normalized(
    primary_recommended_weight: int,
    precheck_recommended_weight: int,
    hard_cap_weight: int,
    expected: int,
) -> None:
    assert (
        ai_executor._resolve_effective_buy_weight(
            primary_recommended_weight,
            precheck_recommended_weight,
            hard_cap_weight,
        )
        == expected
    )


@pytest.mark.parametrize(
    (
        "primary_recommended_weight",
        "precheck_recommended_weight",
        "hard_cap_weight",
        "expected_request_price",
    ),
    [
        (10, 40, 30, Decimal("9950")),
        (40, 15, 30, Decimal("14925")),
        (40, 50, 30, Decimal("29850")),
    ],
)
def test_live_buy_request_uses_lowest_approved_weight(
    monkeypatch: pytest.MonkeyPatch,
    primary_recommended_weight: int,
    precheck_recommended_weight: int,
    hard_cap_weight: int,
    expected_request_price: Decimal,
) -> None:
    service = _patch_live_dependencies(
        monkeypatch,
        hard_cap_weight=hard_cap_weight,
    )

    asyncio.run(
        ai_executor._execute_buy_trade(
            db=_TrackingDb(),
            symbol="KRW-BTC",
            analysis=_analysis(recommended_weight=precheck_recommended_weight),
            primary_recommended_weight=primary_recommended_weight,
            portfolio=_portfolio(),
            trading_mode="live",
        )
    )

    assert len(service.requests) == 1
    request = service.requests[0]
    assert request.price == expected_request_price
    assert request.price <= Decimal(primary_recommended_weight * 1_000)


def test_live_buy_does_not_raise_subminimum_target_to_minimum_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _patch_live_dependencies(monkeypatch, hard_cap_weight=100)

    actual = asyncio.run(
        ai_executor._execute_buy_trade(
            db=_TrackingDb(),
            symbol="KRW-BTC",
            analysis=_analysis(recommended_weight=40),
            primary_recommended_weight=4,
            portfolio=_portfolio(),
            trading_mode="live",
        )
    )

    assert actual is None
    assert service.requests == []


def test_live_buy_preserves_exact_minimum_order_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _patch_live_dependencies(monkeypatch, hard_cap_weight=100)

    asyncio.run(
        ai_executor._execute_buy_trade(
            db=_TrackingDb(),
            symbol="KRW-BTC",
            analysis=_analysis(recommended_weight=40),
            primary_recommended_weight=5,
            portfolio=_portfolio(),
            trading_mode="live",
        )
    )

    assert len(service.requests) == 1
    assert service.requests[0].price == Decimal("5000")


def test_live_buy_still_blocks_when_remaining_allocation_is_subminimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _patch_live_dependencies(monkeypatch, hard_cap_weight=100)
    portfolio = _portfolio()
    portfolio.items[1].total_value = 97_000

    actual = asyncio.run(
        ai_executor._execute_buy_trade(
            db=_TrackingDb(),
            symbol="KRW-BTC",
            analysis=_analysis(recommended_weight=40),
            primary_recommended_weight=40,
            portfolio=portfolio,
            trading_mode="live",
        )
    )

    assert actual is None
    assert service.requests == []


def test_live_buy_still_blocks_when_available_cash_is_subminimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _patch_live_dependencies(monkeypatch, hard_cap_weight=100)
    portfolio = _portfolio()
    portfolio.items[0].balance = 4_000

    actual = asyncio.run(
        ai_executor._execute_buy_trade(
            db=_TrackingDb(),
            symbol="KRW-BTC",
            analysis=_analysis(recommended_weight=40),
            primary_recommended_weight=40,
            portfolio=portfolio,
            trading_mode="live",
        )
    )

    assert actual is None
    assert service.requests == []


def test_paper_buy_keeps_existing_primary_analysis_weighting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _analysis(recommended_weight=20)
    cash_config = SimpleNamespace(config_value="100000", version=1)
    position = SimpleNamespace(quantity=0.0, avg_entry_price=0.0, status="closed")
    recorded_amounts: list[float] = []

    async def load_max_allocation(_db) -> float:
        return 100.0

    async def load_hard_cap(_db) -> float:
        return 30.0

    async def get_ticker(_markets) -> list[dict[str, float]]:
        return [{"trade_price": 100_000_000}]

    async def get_cash_config(_db):
        return cash_config

    async def get_asset(_db, _symbol):
        return SimpleNamespace(id=1)

    async def get_position(_db, _asset_id, _price, *, is_paper):
        assert is_paper is True
        return position

    async def record_history(**kwargs) -> bool:
        recorded_amounts.append(kwargs["fallback_price"] * kwargs["fallback_qty"])
        return True

    async def ignore_notification(**_kwargs) -> None:
        return None

    monkeypatch.setattr(ai_executor, "_load_max_allocation_pct", load_max_allocation)
    monkeypatch.setattr(ai_executor, "_load_ai_max_buy_weight_pct", load_hard_cap)
    monkeypatch.setattr(
        ai_executor.BrokerFactory,
        "get_broker",
        lambda _name: SimpleNamespace(get_ticker=get_ticker),
    )
    monkeypatch.setattr(ai_executor, "_get_or_create_paper_cash_config", get_cash_config)
    monkeypatch.setattr(ai_executor, "_get_or_create_asset", get_asset)
    monkeypatch.setattr(ai_executor, "_get_or_create_position", get_position)
    monkeypatch.setattr(ai_executor, "_record_paper_order_history", record_history)
    monkeypatch.setattr(ai_executor, "_send_trade_notification", ignore_notification)

    asyncio.run(
        ai_executor._execute_buy_trade(
            db=SimpleNamespace(),
            symbol="KRW-BTC",
            analysis=analysis,
            primary_recommended_weight=analysis.recommended_weight,
            portfolio=_portfolio(),
            trading_mode="paper",
        )
    )

    assert float(cash_config.config_value) == pytest.approx(80_100)
    assert recorded_amounts == [pytest.approx(19_890.05)]
    assert position.quantity > 0
