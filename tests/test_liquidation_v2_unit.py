from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.brokers.upbit import UpbitAPIError
from app.services.trading.account_balances import parse_account_balances
from app.services.trading.liquidation_v2 import (
    LiquidationLeaseLostError,
    LiquidationV2CoordinatorMixin,
    _retry_at,
    build_liquidation_request_fingerprint,
)


def _operation(*, items=None, initial=None, post=None):
    return SimpleNamespace(
        result_snapshot=items or [],
        initial_account_snapshot=initial or [],
        post_cancel_account_snapshot=post or [],
        target_snapshot=[],
    )


def _account(currency: str, balance: str, locked: str = "0") -> dict[str, str]:
    return {"currency": currency, "balance": balance, "locked": locked}


def test_liquidation_request_fingerprint_is_stable_and_scope_bound() -> None:
    first = build_liquidation_request_fingerprint("ACCOUNT_ALL")
    assert first == build_liquidation_request_fingerprint("ACCOUNT_ALL")
    assert len(first) == 64
    assert first != build_liquidation_request_fingerprint("APPLICATION_ONLY")


def test_cancellation_reconcile_backoff_progresses_and_caps_at_15_minutes() -> None:
    now = datetime(2026, 7, 12, tzinfo=UTC)

    delays = [
        int((_retry_at(attempt_count, now=now) - now).total_seconds())
        for attempt_count in range(1, 10)
    ]

    assert delays == [15, 30, 60, 120, 300, 600, 900, 900, 900]


def test_stale_operation_lease_is_rejected_before_state_write() -> None:
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    coordinator._operation_lease_tokens = {7: "owner-a"}
    operation = SimpleNamespace(id=7, lease_until="owner-b")

    with pytest.raises(LiquidationLeaseLostError):
        coordinator._assert_operation_lease(operation)


@pytest.mark.asyncio
async def test_discovery_auth_failure_trips_gate_and_terminates_operation() -> None:
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    operation = SimpleNamespace(
        id=7,
        status="IN_PROGRESS",
        phase="DISCOVERING_ORDERS",
        lease_until="owner-a",
    )
    coordinator._operation_lease_tokens = {7: "owner-a"}
    coordinator._get_v2_operation = AsyncMock(return_value=operation)
    coordinator._phase_discovering_orders = AsyncMock(
        side_effect=UpbitAPIError(
            401,
            "Access key가 유효하지 않습니다.",
            error_name="invalid_access_key",
        )
    )
    coordinator._trip_auth_failure = AsyncMock()
    coordinator._terminate_operation = AsyncMock()
    coordinator._release_operation_lease = AsyncMock()

    await coordinator._advance_claimed_operation(operation.id)

    coordinator._trip_auth_failure.assert_awaited_once()
    coordinator._terminate_operation.assert_awaited_once_with(
        operation.id,
        status="FAILED",
        verification_status="ERROR",
        error_code="INVALID_ACCESS_KEY",
        error_message="Access key가 유효하지 않습니다.",
    )
    coordinator._release_operation_lease.assert_awaited_once_with(operation.id)


@pytest.mark.asyncio
async def test_open_order_discovery_reads_every_page_before_returning() -> None:
    first_page = [
        {"uuid": f"uuid-{index}", "market": "KRW-BTC", "side": "ask", "state": "wait"}
        for index in range(100)
    ]
    second_page = [
        {"uuid": "uuid-last", "market": "KRW-ETH", "side": "bid", "state": "watch"}
    ]

    class _Broker:
        def __init__(self) -> None:
            self.pages: list[int] = []

        async def get_orders_open(self, **kwargs):
            self.pages.append(kwargs["page"])
            return first_page if kwargs["page"] == 1 else second_page

    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    coordinator._broker = _Broker()

    result = await coordinator._list_all_open_orders()

    assert len(result) == 101
    assert coordinator._broker.pages == [1, 2]


@pytest.mark.asyncio
async def test_terminal_intent_seen_open_is_canceled_as_mismatch_evidence() -> None:
    intent = SimpleNamespace(
        id=11,
        exchange_uuid="exchange-uuid",
        identifier="a" * 32,
        broker="UPBIT",
        account_scope="primary",
        market="KRW-BTC",
        side="ask",
        submission_status="NO_ORDER_CONFIRMED",
        exchange_state=None,
    )

    class _Result:
        def scalars(self):
            return self

        def all(self):
            return [intent]

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, _statement):
            return _Result()

        async def commit(self) -> None:
            return None

    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    coordinator._session_factory = _Session
    normalized = await coordinator._normalize_discovered_orders(
        [
            {
                "uuid": "exchange-uuid",
                "identifier": "a" * 32,
                "market": "KRW-BTC",
                "side": "ask",
                "state": "wait",
            }
        ]
    )

    assert normalized[0]["ownership"] == "EXTERNAL"
    assert normalized[0]["order_intent_id"] is None
    assert normalized[0]["last_error_code"] == "ORDER_INTENT_LINK_MISMATCH"

    cancellation = SimpleNamespace(
        ownership="EXTERNAL",
        market="KRW-BTC",
        executed_volume=Decimal("0"),
        last_error_code=normalized[0]["last_error_code"],
    )
    items, _, remaining, status = coordinator._build_verified_result(
        _operation(),
        parse_account_balances([_account("KRW", "10000")]),
        {},
        [cancellation],
    )

    assert status == "PARTIAL"
    assert items[0]["result_code"] == "LEDGER_MISMATCH"
    assert remaining["remaining"] == 1


@pytest.mark.parametrize("status_code", [401, 403, 418])
@pytest.mark.asyncio
async def test_cancel_lookup_auth_errors_are_fail_closed(status_code: int) -> None:
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    coordinator._broker = SimpleNamespace(
        get_order=AsyncMock(
            side_effect=UpbitAPIError(
                status_code,
                "취소 주문 조회 인증 실패",
                error_name="out_of_scope",
            )
        )
    )

    result = await coordinator._lookup_cancel_resolution(
        "exchange-uuid",
        expected_market="KRW-BTC",
        expected_side="ask",
    )

    assert result[0] == "AUTH_FAILED"
    assert result[3] == "OUT_OF_SCOPE"


@pytest.mark.parametrize("status_code", [429, 500])
@pytest.mark.asyncio
async def test_cancel_lookup_transient_errors_remain_unknown(status_code: int) -> None:
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    coordinator._broker = SimpleNamespace(
        get_order=AsyncMock(
            side_effect=UpbitAPIError(status_code, "일시적 주문 조회 실패")
        )
    )

    result = await coordinator._lookup_cancel_resolution(
        "exchange-uuid",
        expected_market="KRW-BTC",
        expected_side="ask",
    )

    assert result[0] == "UNKNOWN"


@pytest.mark.asyncio
async def test_cancel_timeout_still_resolves_twenty_claimed_uuids_by_lookup() -> None:
    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def commit(self) -> None:
            return None

    operation = SimpleNamespace(id=7, lease_until="owner-a")
    batch = [
        SimpleNamespace(
            id=index + 1,
            exchange_uuid=f"uuid-{index}",
            market="KRW-BTC",
            side="ask",
            version=2,
        )
        for index in range(20)
    ]
    repository = SimpleNamespace(
        get_operation=AsyncMock(return_value=operation),
        claim_cancel_batch=AsyncMock(return_value=batch),
        append_event=AsyncMock(),
    )
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    coordinator._operation_lease_tokens = {7: "owner-a"}
    coordinator._session_factory = _Session
    coordinator._liquidation_repository = repository
    coordinator._recover_stale_cancel_claims = AsyncMock()
    coordinator._due_unknown_rows = AsyncMock(return_value=[])
    coordinator._broker = SimpleNamespace(
        cancel_orders_by_ids=AsyncMock(side_effect=TimeoutError("응답 유실"))
    )
    coordinator._lookup_cancel_resolution = AsyncMock(
        return_value=("CONFIRMED", Decimal("0"), Decimal("0"), None, None)
    )
    coordinator._apply_cancel_resolution = AsyncMock()

    should_continue = await coordinator._phase_canceling_orders(operation)

    assert should_continue is True
    repository.claim_cancel_batch.assert_awaited_once()
    assert repository.claim_cancel_batch.await_args.kwargs["limit"] == 20
    coordinator._broker.cancel_orders_by_ids.assert_awaited_once_with(
        [row.exchange_uuid for row in batch]
    )
    assert coordinator._lookup_cancel_resolution.await_count == 20
    assert coordinator._apply_cancel_resolution.await_count == 20


@pytest.mark.asyncio
async def test_unknown_cancel_state_performs_lookup_only_without_delete() -> None:
    operation = SimpleNamespace(id=7)
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    coordinator._recover_stale_cancel_claims = AsyncMock()
    coordinator._due_unknown_rows = AsyncMock(
        return_value=[(1, "exchange-uuid", "KRW-BTC", "ask", 3)]
    )
    coordinator._lookup_cancel_resolution = AsyncMock(
        return_value=("UNKNOWN", None, None, "UPBIT_HTTP_500", "조회 실패")
    )
    coordinator._apply_cancel_resolution = AsyncMock()
    coordinator._broker = SimpleNamespace(cancel_orders_by_ids=AsyncMock())

    should_continue = await coordinator._phase_canceling_orders(operation)

    assert should_continue is True
    coordinator._lookup_cancel_resolution.assert_awaited_once()
    coordinator._apply_cancel_resolution.assert_awaited_once_with(
        1,
        ("UNKNOWN", None, None, "UPBIT_HTTP_500", "조회 실패"),
        expected_version=3,
    )
    coordinator._broker.cancel_orders_by_ids.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_cancel_auth_lookup_trips_gate_and_fails_operation() -> None:
    operation = SimpleNamespace(id=7)
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    coordinator._recover_stale_cancel_claims = AsyncMock()
    coordinator._due_unknown_rows = AsyncMock(
        return_value=[(1, "exchange-uuid", "KRW-BTC", "ask", 3)]
    )
    coordinator._lookup_cancel_resolution = AsyncMock(
        return_value=(
            "AUTH_FAILED",
            None,
            None,
            "OUT_OF_SCOPE",
            "주문 조회 권한이 없습니다.",
        )
    )
    coordinator._apply_cancel_resolution = AsyncMock()
    coordinator._trip_auth_failure = AsyncMock()
    coordinator._terminate_operation = AsyncMock()

    should_continue = await coordinator._phase_canceling_orders(operation)

    assert should_continue is False
    coordinator._trip_auth_failure.assert_awaited_once()
    coordinator._terminate_operation.assert_awaited_once_with(
        operation.id,
        status="FAILED",
        verification_status="ERROR",
        error_code="OUT_OF_SCOPE",
        error_message="주문 조회 권한이 없습니다.",
    )


@pytest.mark.asyncio
async def test_cancel_reconciliation_never_resubmits_and_recovers_snapshot_crash() -> None:
    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def commit(self) -> None:
            return None

    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    coordinator._session_factory = _Session
    coordinator._liquidation_repository = SimpleNamespace(
        list_cancellations=AsyncMock(
            return_value=[SimpleNamespace(order_intent_id=99)]
        )
    )
    coordinator._order_service = SimpleNamespace(reconcile_intent=AsyncMock())
    coordinator._control_repository = SimpleNamespace(
        has_blocking_intent=AsyncMock(return_value=False)
    )
    coordinator._list_all_open_orders = AsyncMock(return_value=[])
    coordinator._transition_phase = AsyncMock()
    coordinator._broker = SimpleNamespace(get_accounts=AsyncMock())
    operation = SimpleNamespace(
        id=7,
        target_snapshot=[{"market": "KRW-BTC", "volume": "1"}],
        post_cancel_account_snapshot=[_account("BTC", "1")],
    )

    should_continue = await coordinator._phase_reconciling_canceled_orders(operation)

    assert should_continue is True
    coordinator._order_service.reconcile_intent.assert_awaited_once_with(99)
    coordinator._control_repository.has_blocking_intent.assert_awaited_once()
    coordinator._list_all_open_orders.assert_awaited_once()
    coordinator._transition_phase.assert_awaited_once_with(7, "VERIFYING")
    coordinator._broker.get_accounts.assert_not_awaited()

    # 최초 계좌 스냅샷 커밋 뒤 phase 전환 전에 종료된 경우에는 target만 이어서 고정합니다.
    operation.target_snapshot = None
    coordinator._order_service.reconcile_intent.reset_mock()
    coordinator._control_repository.has_blocking_intent.reset_mock()
    coordinator._list_all_open_orders.reset_mock()
    coordinator._transition_phase.reset_mock()

    should_continue = await coordinator._phase_reconciling_canceled_orders(operation)

    assert should_continue is True
    coordinator._order_service.reconcile_intent.assert_awaited_once_with(99)
    coordinator._transition_phase.assert_awaited_once_with(7, "SNAPSHOTTING_TARGETS")
    coordinator._broker.get_accounts.assert_not_awaited()


def test_verified_completion_requires_zero_exchange_and_position_balance() -> None:
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    operation = _operation(
        initial=[_account("BTC", "1")],
        post=[_account("BTC", "1")],
        items=[
            {
                "currency": "BTC",
                "market": "KRW-BTC",
                "intent_id": 1,
                "submission_status": "ACCEPTED",
                "exchange_state": "done",
                "projection_status": "APPLIED",
                "executed_volume": "1",
                "remaining_volume": "0",
            }
        ],
    )

    items, summary, remaining, status = coordinator._build_verified_result(
        operation,
        parse_account_balances([_account("BTC", "0")]),
        {"KRW-BTC": Decimal("0")},
        [],
    )

    assert status == "COMPLETED"
    assert items[0]["result_code"] == "LIQUIDATED"
    assert summary == {"attempted": 1, "succeeded": 1, "failed": 0}
    assert remaining == {"remaining": 0, "assets": []}


def test_locked_balance_prevents_verified_success() -> None:
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    operation = _operation(
        initial=[_account("BTC", "1", "0.2")],
        post=[_account("BTC", "1", "0.2")],
        items=[{"currency": "BTC", "market": "KRW-BTC", "intent_id": 1}],
    )

    items, _, remaining, status = coordinator._build_verified_result(
        operation,
        parse_account_balances([_account("BTC", "0", "0.2")]),
        {"KRW-BTC": Decimal("0.2")},
        [],
    )

    assert status == "PARTIAL"
    assert items[0]["result_code"] == "LOCKED_REMAINING"
    assert remaining["remaining"] == 1


def test_terminal_partial_fill_with_remaining_volume_is_not_liquidated() -> None:
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    operation = _operation(
        initial=[_account("BTC", "2")],
        post=[_account("BTC", "2")],
        items=[
            {
                "currency": "BTC",
                "market": "KRW-BTC",
                "intent_id": 1,
                "submission_status": "ACCEPTED",
                "exchange_state": "cancel",
                "projection_status": "APPLIED",
                "executed_volume": "1",
                "remaining_volume": "1",
            }
        ],
    )

    items, _, remaining, status = coordinator._build_verified_result(
        operation,
        parse_account_balances([_account("BTC", "0")]),
        {"KRW-BTC": Decimal("0")},
        [],
    )

    assert status == "PARTIAL"
    assert items[0]["result_code"] == "VERIFY_FAILED"
    assert items[0]["error_code"] == "REMAINING_VOLUME_UNRESOLVED"
    assert remaining["remaining"] == 1


def test_external_partial_fill_is_not_synthesized_as_success() -> None:
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    operation = _operation(
        initial=[_account("BTC", "1")],
        post=[_account("BTC", "0")],
        items=[{"currency": "BTC", "market": "KRW-BTC"}],
    )
    cancellation = SimpleNamespace(
        ownership="EXTERNAL",
        market="KRW-BTC",
        executed_volume=Decimal("1"),
    )

    items, _, _, status = coordinator._build_verified_result(
        operation,
        parse_account_balances([_account("BTC", "0")]),
        {"KRW-BTC": Decimal("0")},
        [cancellation],
    )

    assert status == "PARTIAL"
    assert items[0]["result_code"] == "LEDGER_MISMATCH"


def test_non_krw_market_external_fill_also_blocks_verified_success() -> None:
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)
    operation = _operation(
        initial=[_account("ETH", "1")],
        post=[_account("ETH", "1")],
        items=[
            {
                "currency": "ETH",
                "market": "KRW-ETH",
                "intent_id": 1,
                "submission_status": "ACCEPTED",
                "exchange_state": "done",
                "projection_status": "APPLIED",
                "executed_volume": "1",
                "remaining_volume": "0",
            }
        ],
    )
    cancellation = SimpleNamespace(
        ownership="EXTERNAL",
        market="BTC-ETH",
        executed_volume=Decimal("0.25"),
    )

    items, _, remaining, status = coordinator._build_verified_result(
        operation,
        parse_account_balances([_account("ETH", "0")]),
        {"KRW-ETH": Decimal("0")},
        [cancellation],
    )

    assert status == "PARTIAL"
    assert items[0]["result_code"] == "LEDGER_MISMATCH"
    assert remaining["remaining"] == 1


def test_verified_empty_account_is_no_assets() -> None:
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)

    items, summary, remaining, status = coordinator._build_verified_result(
        _operation(),
        parse_account_balances([_account("KRW", "10000")]),
        {},
        [],
    )

    assert items == []
    assert summary == {"attempted": 0, "succeeded": 0, "failed": 0}
    assert remaining == {"remaining": 0, "assets": []}
    assert status == "NO_ASSETS"


def test_position_without_exchange_asset_is_ledger_mismatch_not_no_assets() -> None:
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)

    items, _, remaining, status = coordinator._build_verified_result(
        _operation(),
        parse_account_balances([_account("KRW", "10000")]),
        {"KRW-BTC": Decimal("0.1")},
        [],
    )

    assert status == "PARTIAL"
    assert items[0]["result_code"] == "LEDGER_MISMATCH"
    assert remaining["remaining"] == 1


def test_non_krw_position_without_exchange_asset_also_blocks_success() -> None:
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)

    items, _, remaining, status = coordinator._build_verified_result(
        _operation(),
        parse_account_balances([_account("KRW", "10000")]),
        {"BTC-ETH": Decimal("0.25")},
        [],
    )

    assert status == "PARTIAL"
    assert items[0]["market"] == "KRW-ETH"
    assert items[0]["result_code"] == "LEDGER_MISMATCH"
    assert remaining["remaining"] == 1


def test_unmapped_position_symbol_is_preserved_as_mismatch_evidence() -> None:
    coordinator = object.__new__(LiquidationV2CoordinatorMixin)

    items, _, remaining, status = coordinator._build_verified_result(
        _operation(),
        parse_account_balances([_account("KRW", "10000")]),
        {"MALFORMED": Decimal("1")},
        [],
    )

    assert status == "PARTIAL"
    assert items[0]["market"] == "MALFORMED"
    assert items[0]["result_code"] == "LEDGER_MISMATCH"
    assert remaining["remaining"] == 1
