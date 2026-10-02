from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Iterable, Mapping

from sqlalchemy import func, or_, select

from app.db.liquidation_repository import LiquidationRepository
from app.models.domain import (
    Asset,
    LiquidationOperation,
    LiquidationOrderCancellation,
    OrderIntent,
    Position,
)
from app.models.schemas import (
    LiquidationCancellationItem,
    LiquidationIntentItem,
    LiquidationOperationResponse,
    LiquidationOperationSummary,
)
from app.services.brokers.upbit import UpbitAPIError
from app.services.trading.account_balances import (
    AccountBalance,
    AccountBalanceValidationError,
    build_liquidation_target_candidates,
    decimal_string,
    parse_account_balances,
    parse_non_krw_account_balances,
)
from app.services.trading.live_order_control import (
    AuthFailureBlockCommand,
    LiveOrderControlDrainPendingError,
    LiveOrderControlPolicyError,
    PrepareEmergencyLiquidationCommand,
)
from app.services.trading.live_order_execution import (
    ACCOUNT_SCOPE,
    AUTHORIZATION_ERROR_NAMES,
    BROKER_NAME,
    LiveOrderRequest,
)

logger = logging.getLogger(__name__)

ACCOUNT_ALL_SCOPE = "ACCOUNT_ALL"
LIQUIDATION_CONTRACT_VERSION = 2
OPERATION_LEASE = timedelta(seconds=120)
CANCELLATION_LEASE = timedelta(seconds=90)
POSITION_EPSILON = Decimal("0.000000000001")
RETRY_DELAYS_SECONDS = (15, 30, 60, 120, 300, 600, 900)
ACTIVE_STATUSES = ("PREPARING", "IN_PROGRESS")
TERMINAL_STATUSES = ("COMPLETED", "PARTIAL", "FAILED", "NO_ASSETS")
TERMINAL_ORDER_STATES = {"done", "cancel"}
OPEN_ORDER_STATES = {"wait", "watch"}
TERMINAL_PROJECTIONS = {"APPLIED", "SKIPPED"}
TERMINAL_SUBMISSION_FAILURES = {"REJECTED", "ABANDONED", "NO_ORDER_CONFIRMED"}


class LiquidationLeaseLostError(RuntimeError):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def build_liquidation_request_fingerprint(scope: str) -> str:
    normalized = str(scope or "").strip().upper()
    payload = json.dumps(
        {"contract_version": LIQUIDATION_CONTRACT_VERSION, "scope": normalized},
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _retry_at(attempt_count: int, *, now: datetime | None = None) -> datetime:
    index = min(max(int(attempt_count), 1) - 1, len(RETRY_DELAYS_SECONDS) - 1)
    return (now or utcnow()) + timedelta(seconds=RETRY_DELAYS_SECONDS[index])


def _safe_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool) or not str(value).strip():
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


def _safe_error(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, UpbitAPIError):
        code = str(exc.error_name or f"UPBIT_HTTP_{exc.status_code}").strip().upper()
        message = str(exc.message or exc.detail or exc)[:1000]
        return code or f"UPBIT_HTTP_{exc.status_code}", message
    return exc.__class__.__name__.upper(), str(exc)[:1000]


def _is_auth_failure(exc: BaseException) -> bool:
    if not isinstance(exc, UpbitAPIError):
        return False
    error_name = str(exc.error_name or "").strip().lower()
    return exc.status_code in {401, 403, 418} or error_name in AUTHORIZATION_ERROR_NAMES


def _snapshot_map(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, list):
        return {}
    result: dict[str, dict[str, str]] = {}
    for raw in value:
        if not isinstance(raw, dict):
            continue
        currency = str(raw.get("currency") or "").strip().upper()
        if currency:
            result[currency] = dict(raw)
    return result


class LiquidationV2CoordinatorMixin:
    """P0-002 제어 수명주기 위에 복구 가능한 계정 전체 청산을 추가합니다."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._liquidation_repository = LiquidationRepository()
        self._legacy_execution = False
        self._operation_lease_tokens: dict[int, datetime] = {}

    async def execute(
        self,
        idempotency_key: str,
        *,
        scope: str | None = None,
        request_fingerprint: str | None = None,
    ) -> LiquidationOperationResponse:
        # 과거 내부 테스트 harness만 기존 계약을 사용합니다. 활성 REST는 scope를 필수 전달합니다.
        if scope is None:
            self._legacy_execution = True
            try:
                return await super().execute(idempotency_key)
            finally:
                self._legacy_execution = False

        normalized_scope = str(scope).strip().upper()
        expected_fingerprint = build_liquidation_request_fingerprint(normalized_scope)
        if normalized_scope != ACCOUNT_ALL_SCOPE:
            raise ValueError("청산 범위는 ACCOUNT_ALL이어야 합니다.")
        if request_fingerprint != expected_fingerprint:
            raise ValueError("청산 요청 fingerprint가 일치하지 않습니다.")

        operation = await self._create_or_get_v2_operation(
            idempotency_key,
            request_fingerprint=expected_fingerprint,
        )
        if operation.status not in TERMINAL_STATUSES:
            await self._ensure_v2_blocked(operation.id)
        return await self._read_operation_response(operation.id)

    async def get_operation(self, operation_id: int) -> LiquidationOperationResponse:
        if getattr(self, "_legacy_execution", False):
            return await super().get_operation(operation_id)
        return await self._read_operation_response(operation_id)

    async def get_active_operation(self) -> LiquidationOperationResponse | None:
        async with self._session_factory() as db:
            operation = await self._liquidation_repository.find_active(
                db,
                broker=BROKER_NAME,
                account_scope=ACCOUNT_SCOPE,
            )
            operation_id = operation.id if operation is not None else None
            await db.commit()
        if operation_id is None:
            return None
        return await self._read_operation_response(operation_id)

    async def refresh_operation(self, operation_id: int) -> LiquidationOperationResponse:
        if getattr(self, "_legacy_execution", False) or not hasattr(
            self, "_liquidation_repository"
        ):
            return await super().refresh_operation(operation_id)
        async with self._session_factory() as db:
            operation = await self._liquidation_repository.get_operation(db, operation_id)
            await db.commit()
        if operation is None:
            raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation_id}")
        if operation.contract_version == 1:
            return await self._read_operation_response(operation_id)
        if operation.status in TERMINAL_STATUSES:
            return await self._read_operation_response(operation_id)

        async with self._session_factory() as db:
            lease_token = await self._liquidation_repository.claim_operation(
                db,
                operation_id,
                now=utcnow(),
                lease_for=OPERATION_LEASE,
            )
            await db.commit()
        if lease_token is not None:
            self._operation_lease_tokens[operation_id] = lease_token
            await self._advance_claimed_operation(operation_id)
        return await self._read_operation_response(operation_id)

    async def refresh_in_progress_operations(self, limit: int = 100) -> int:
        refreshed = 0
        for _ in range(max(1, limit)):
            async with self._session_factory() as db:
                claims = await self._liquidation_repository.claim_due_operations(
                    db,
                    now=utcnow(),
                    lease_for=OPERATION_LEASE,
                    limit=1,
                )
                await db.commit()
            if not claims:
                break
            operation_id, lease_token = claims[0]
            self._operation_lease_tokens[operation_id] = lease_token
            try:
                await self._advance_claimed_operation(operation_id)
            except Exception:
                logger.exception("전량청산 worker 처리 실패: operation_id=%s", operation_id)
            refreshed += 1
        return refreshed

    async def _create_or_get_v2_operation(
        self,
        idempotency_key: str,
        *,
        request_fingerprint: str,
    ) -> LiquidationOperation:
        async with self._submission_barrier.exclusive() as lease:
            async with lease.transaction() as db:
                existing = await self._liquidation_repository.find_by_key(
                    db,
                    idempotency_key,
                    for_update=True,
                )
                if existing is not None:
                    if (
                        existing.contract_version != LIQUIDATION_CONTRACT_VERSION
                        or existing.cancel_scope != ACCOUNT_ALL_SCOPE
                        or existing.request_fingerprint != request_fingerprint
                    ):
                        raise LiveOrderControlPolicyError(
                            "같은 Idempotency-Key에 다른 청산 요청이 연결되어 있습니다.",
                            error_code="LIQUIDATION_IDEMPOTENCY_CONFLICT",
                        )
                    return existing

                active = await self._liquidation_repository.find_active(
                    db,
                    broker=BROKER_NAME,
                    account_scope=ACCOUNT_SCOPE,
                )
                if active is not None:
                    raise LiveOrderControlPolicyError(
                        "다른 계정 전체 청산 작업이 이미 진행 중입니다.",
                        error_code="ACTIVE_LIQUIDATION_EXISTS",
                    )
                if await self._control_state_store.get_trading_mode(db) != "live":
                    raise LiveOrderControlPolicyError(
                        "정상적인 live 거래 모드에서만 Upbit 전량청산을 생성할 수 있습니다.",
                        error_code="TRADING_MODE_LIVE_REQUIRED",
                    )

                now = utcnow()
                operation = LiquidationOperation(
                    idempotency_key=idempotency_key,
                    status="PREPARING",
                    broker=BROKER_NAME,
                    account_scope=ACCOUNT_SCOPE,
                    contract_version=LIQUIDATION_CONTRACT_VERSION,
                    request_fingerprint=request_fingerprint,
                    cancel_scope=ACCOUNT_ALL_SCOPE,
                    phase="BLOCKING",
                    verification_status="PENDING",
                    version=0,
                    retry_count=0,
                    next_run_at=now,
                    target_snapshot=None,
                    result_snapshot=[],
                    cancellation_summary={
                        "discovered_orders": 0,
                        "cancel_confirmed": 0,
                        "cancel_unknown": 0,
                        "discovery_rounds": 0,
                        "external_fill_detected": False,
                    },
                    order_summary={"attempted": 0, "succeeded": 0, "failed": 0},
                    remaining_summary={"remaining": 0, "assets": []},
                )
                db.add(operation)
                await db.flush()
                await self._liquidation_repository.append_event(
                    db,
                    operation,
                    event_type="OPERATION_CREATED",
                    source="REST",
                    actor_ref="admin-api",
                    to_phase="BLOCKING",
                    details={"cancel_scope": ACCOUNT_ALL_SCOPE},
                    now=now,
                )
                _, drain_pending = (
                    await self._control_service.prepare_liquidation_in_transaction(
                        db,
                        PrepareEmergencyLiquidationCommand(
                            request_id=self._stable_operation_uuid(
                                "liquidation-v2-block", operation
                            ),
                            operation_id=operation.id,
                            reason_code="EMERGENCY_LIQUIDATION_PREPARE",
                            reason_text=(
                                "계정 전체 주문을 취소하고 잔고를 검증하기 전에 "
                                "신규 실주문을 차단합니다."
                            ),
                            source="REST",
                            actor_ref="liquidation-coordinator",
                        ),
                    )
                )
                if drain_pending:
                    operation.next_run_at = now + timedelta(seconds=15)
                else:
                    operation.status = "IN_PROGRESS"
                    operation.phase = "DISCOVERING_ORDERS"
                    operation.next_run_at = now
                    operation.version += 1
                    await self._liquidation_repository.append_event(
                        db,
                        operation,
                        event_type="PHASE_CHANGED",
                        source="REST",
                        from_phase="BLOCKING",
                        to_phase="DISCOVERING_ORDERS",
                        now=now,
                    )
                return operation

    async def _ensure_v2_blocked(self, operation_id: int) -> None:
        operation = await self._get_v2_operation(operation_id)
        if operation.phase != "BLOCKING" or operation.status in TERMINAL_STATUSES:
            return
        command = PrepareEmergencyLiquidationCommand(
            request_id=self._stable_operation_uuid("liquidation-v2-block", operation),
            operation_id=operation.id,
            reason_code="EMERGENCY_LIQUIDATION_PREPARE",
            reason_text="계정 전체 주문을 취소하고 잔고를 검증하기 전에 신규 실주문을 차단합니다.",
            source="REST",
            actor_ref="liquidation-coordinator",
        )
        try:
            await self._control_service.prepare_liquidation(command)
        except LiveOrderControlDrainPendingError:
            await self._schedule_operation(operation.id, delay_seconds=15)
            return
        except Exception as exc:
            await self._terminate_operation(
                operation.id,
                status="FAILED",
                verification_status="ERROR",
                error_code=_safe_error(exc)[0],
                error_message=_safe_error(exc)[1],
            )
            raise
        await self._transition_phase(operation.id, "DISCOVERING_ORDERS")

    async def _advance_claimed_operation(self, operation_id: int) -> None:
        try:
            try:
                for _ in range(12):
                    operation = await self._get_v2_operation(operation_id)
                    self._assert_operation_lease(operation)
                    if operation.status in TERMINAL_STATUSES:
                        return
                    handler = {
                        "BLOCKING": self._phase_blocking,
                        "DISCOVERING_ORDERS": self._phase_discovering_orders,
                        "CANCELING_ORDERS": self._phase_canceling_orders,
                        "RECONCILING_CANCELED_ORDERS": self._phase_reconciling_canceled_orders,
                        "SNAPSHOTTING_TARGETS": self._phase_snapshotting_targets,
                        "SUBMITTING": self._phase_submitting,
                        "WAITING_FILLS": self._phase_waiting_fills,
                        "VERIFYING": self._phase_verifying,
                    }.get(operation.phase)
                    if handler is None:
                        raise RuntimeError(
                            f"지원하지 않는 청산 phase입니다: {operation.phase}"
                        )
                    should_continue = await handler(operation)
                    if not should_continue:
                        return
            except LiquidationLeaseLostError:
                logger.warning(
                    "청산 operation lease가 교체되어 stale worker를 중단합니다: operation_id=%s",
                    operation_id,
                )
            except Exception as exc:
                logger.exception(
                    "청산 operation phase 처리 실패: operation_id=%s",
                    operation_id,
                )
                if _is_auth_failure(exc):
                    await self._trip_auth_failure(operation_id, exc)
                    code, message = _safe_error(exc)
                    await self._terminate_operation(
                        operation_id,
                        status="FAILED",
                        verification_status="ERROR",
                        error_code=code,
                        error_message=message,
                    )
                else:
                    await self._record_transient_error(operation_id, exc)
        finally:
            await self._release_operation_lease(operation_id)
            self._operation_lease_tokens.pop(operation_id, None)

    def _assert_operation_lease(self, operation: LiquidationOperation) -> None:
        token = self._operation_lease_tokens.get(operation.id)
        if token is not None and operation.lease_until != token:
            raise LiquidationLeaseLostError(
                f"operation {operation.id} lease owner가 변경되었습니다."
            )

    async def _phase_blocking(self, operation: LiquidationOperation) -> bool:
        previous = operation.phase
        await self._ensure_v2_blocked(operation.id)
        latest = await self._get_v2_operation(operation.id)
        return latest.phase != previous and latest.status not in TERMINAL_STATUSES

    async def _phase_discovering_orders(self, operation: LiquidationOperation) -> bool:
        accounts_payload = await self._broker.get_accounts()
        balances = self._parse_accounts_payload(accounts_payload)
        open_orders = await self._list_all_open_orders()
        discovered = await self._normalize_discovered_orders(open_orders)
        now = utcnow()

        async with self._session_factory() as db:
            current = await self._liquidation_repository.get_operation(
                db, operation.id, for_update=True
            )
            if current is None or current.phase != "DISCOVERING_ORDERS":
                await db.commit()
                return False
            self._assert_operation_lease(current)
            if current.initial_account_snapshot is None:
                current.initial_account_snapshot = [item.to_snapshot() for item in balances]
                current.initial_accounts_observed_at = now
                current.version += 1
                await self._liquidation_repository.append_event(
                    db,
                    current,
                    event_type="ACCOUNT_OBSERVED",
                    source="WORKER",
                    details={"stage": "initial", "asset_count": len(balances)},
                    now=now,
                )
            added = await self._liquidation_repository.discover_cancellations(
                db,
                current.id,
                discovered,
                now=now,
            )
            summary = dict(current.cancellation_summary or {})
            summary["discovered_orders"] = int(summary.get("discovered_orders", 0)) + added
            summary["discovery_rounds"] = max(int(summary.get("discovery_rounds", 0)), 1)
            current.cancellation_summary = summary
            current.version += 1
            await self._liquidation_repository.append_event(
                db,
                current,
                event_type="ORDER_DISCOVERED",
                source="WORKER",
                details={"count": len(discovered), "new_count": added},
                now=now,
            )
            await db.commit()

        await self._transition_phase(
            operation.id,
            "CANCELING_ORDERS" if discovered else "RECONCILING_CANCELED_ORDERS",
        )
        return True

    async def _phase_canceling_orders(self, operation: LiquidationOperation) -> bool:
        await self._recover_stale_cancel_claims(operation.id)
        unknown_rows = await self._due_unknown_rows(operation.id)
        if unknown_rows:
            resolutions = await asyncio.gather(
                *(
                    self._lookup_cancel_resolution(
                        uuid_, expected_market=market, expected_side=side
                    )
                    for _, uuid_, market, side, _ in unknown_rows
                )
            )
            for (cancellation_id, _, _, _, expected_version), resolution in zip(
                unknown_rows, resolutions, strict=True
            ):
                await self._apply_cancel_resolution(
                    cancellation_id,
                    resolution,
                    expected_version=expected_version,
                )
                if resolution[0] == "AUTH_FAILED":
                    await self._trip_auth_failure(
                        operation.id,
                        UpbitAPIError(
                            401,
                            resolution[4] or "Upbit 인증 오류",
                            error_name=resolution[3],
                        ),
                    )
                    await self._terminate_operation(
                        operation.id,
                        status="FAILED",
                        verification_status="ERROR",
                        error_code=resolution[3] or "UPBIT_AUTH_FAILURE",
                        error_message=resolution[4] or "Upbit 인증 오류가 발생했습니다.",
                    )
                    return False
            return True

        now = utcnow()
        async with self._session_factory() as db:
            current = await self._liquidation_repository.get_operation(
                db, operation.id, for_update=True
            )
            if current is None:
                await db.commit()
                return False
            self._assert_operation_lease(current)
            batch = await self._liquidation_repository.claim_cancel_batch(
                db,
                operation.id,
                now=now,
                lease_for=CANCELLATION_LEASE,
                limit=20,
            )
            if batch:
                await self._liquidation_repository.append_event(
                    db,
                    current,
                    event_type="CANCEL_REQUESTED",
                    source="WORKER",
                    details={"uuids": [row.exchange_uuid for row in batch]},
                    now=now,
                )
            await db.commit()

        if batch:
            delete_error: BaseException | None = None
            try:
                await self._broker.cancel_orders_by_ids(
                    [row.exchange_uuid for row in batch]
                )
            except Exception as exc:  # 취소 응답 유실도 UUID 조회로만 판정합니다.
                delete_error = exc
                if _is_auth_failure(exc):
                    await self._trip_auth_failure(operation.id, exc)

            resolutions = await asyncio.gather(
                *(
                    self._lookup_cancel_resolution(
                        row.exchange_uuid,
                        expected_market=row.market,
                        expected_side=row.side,
                    )
                    for row in batch
                )
            )
            for row, resolution in zip(batch, resolutions, strict=True):
                if resolution[0] == "UNKNOWN" and delete_error is not None:
                    code, message = _safe_error(delete_error)
                    resolution = ("UNKNOWN", None, None, code, message)
                await self._apply_cancel_resolution(
                    row.id,
                    resolution,
                    expected_version=row.version,
                )
                if resolution[0] == "AUTH_FAILED":
                    delete_error = delete_error or UpbitAPIError(
                        401,
                        resolution[4] or "Upbit 인증 오류",
                        error_name=resolution[3],
                    )
            if delete_error is not None and _is_auth_failure(delete_error):
                await self._terminate_operation(
                    operation.id,
                    status="FAILED",
                    verification_status="ERROR",
                    error_code=_safe_error(delete_error)[0],
                    error_message=_safe_error(delete_error)[1],
                )
                return False
            return True

        states = await self._cancellation_state_counts(operation.id)
        if states.get("FAILED", 0):
            await self._terminate_operation(
                operation.id,
                status="FAILED",
                verification_status="ERROR",
                error_code="CANCEL_RETRY_EXHAUSTED",
                error_message="미체결 주문 취소를 확인하지 못했습니다.",
            )
            return False
        pending = sum(states.get(key, 0) for key in ("DISCOVERED", "CANCELING", "UNKNOWN"))
        if pending:
            await self._schedule_operation(operation.id, delay_seconds=15)
            return False
        await self._transition_phase(operation.id, "RECONCILING_CANCELED_ORDERS")
        return True

    async def _phase_reconciling_canceled_orders(
        self, operation: LiquidationOperation
    ) -> bool:
        has_frozen_targets = operation.target_snapshot is not None
        async with self._session_factory() as db:
            managed = await self._liquidation_repository.list_cancellations(
                db,
                operation.id,
                statuses=("CONFIRMED",),
            )
            intent_ids = sorted(
                {row.order_intent_id for row in managed if row.order_intent_id is not None}
            )
            await db.commit()
        for intent_id in intent_ids:
            await self._order_service.reconcile_intent(intent_id)

        async with self._session_factory() as db:
            blocking = await self._control_repository.has_blocking_intent(
                db,
                broker=BROKER_NAME,
                account_scope=ACCOUNT_SCOPE,
                include_prepared=True,
            )
            await db.commit()
        if blocking:
            await self._schedule_operation(operation.id, delay_seconds=15)
            return False

        open_orders = await self._list_all_open_orders()
        if open_orders:
            if not await self._persist_additional_discovery(operation.id, open_orders):
                return False
            await self._transition_phase(operation.id, "CANCELING_ORDERS")
            return True

        # 최초 대상 스냅샷 뒤 발견된 주문은 취소·원장 투영까지만 수행합니다.
        # 기존 청산 target을 SUBMITTING으로 되돌리거나 2차 매도를 만들지 않습니다.
        if has_frozen_targets:
            await self._transition_phase(operation.id, "VERIFYING")
            return True

        # 최초 취소 후 계좌 스냅샷 커밋 직후 종료된 경우 기존 증거를 재사용해
        # 대상 고정 단계부터 이어갑니다.
        if operation.post_cancel_account_snapshot is not None:
            await self._transition_phase(operation.id, "SNAPSHOTTING_TARGETS")
            return True

        balances = self._parse_accounts_payload(await self._broker.get_accounts())
        now = utcnow()
        async with self._session_factory() as db:
            current = await self._liquidation_repository.get_operation(
                db, operation.id, for_update=True
            )
            if current is None or current.phase != "RECONCILING_CANCELED_ORDERS":
                await db.commit()
                return False
            self._assert_operation_lease(current)
            current.post_cancel_account_snapshot = [item.to_snapshot() for item in balances]
            current.post_cancel_accounts_observed_at = now
            current.version += 1
            await self._liquidation_repository.append_event(
                db,
                current,
                event_type="ACCOUNT_OBSERVED",
                source="WORKER",
                details={"stage": "post_cancel", "asset_count": len(balances)},
                now=now,
            )
            await db.commit()
        await self._transition_phase(operation.id, "SNAPSHOTTING_TARGETS")
        return True

    async def _phase_snapshotting_targets(self, operation: LiquidationOperation) -> bool:
        if operation.target_snapshot is not None:
            targets = (
                operation.target_snapshot
                if isinstance(operation.target_snapshot, list)
                else []
            )
            if not targets:
                await self._transition_phase(operation.id, "VERIFYING")
                return True
            try:
                await self._ensure_liquidation_authorized(operation)
            except LiveOrderControlPolicyError as exc:
                await self._terminate_operation(
                    operation.id,
                    status="FAILED",
                    verification_status="ERROR",
                    error_code=str(
                        getattr(exc, "error_code", "EMERGENCY_AUTH_REVOKED")
                    ),
                    error_message=str(exc),
                )
                return False
            await self._transition_phase(operation.id, "SUBMITTING")
            return True

        balances = parse_non_krw_account_balances(
            operation.post_cancel_account_snapshot or []
        )
        active_markets = await self._active_krw_markets()
        requested_markets = sorted(
            f"KRW-{item.currency}"
            for item in balances
            if item.balance > 0 and f"KRW-{item.currency}" in active_markets
        )
        ticker_prices = await self._ticker_prices(requested_markets)
        candidates = build_liquidation_target_candidates(
            balances,
            active_krw_markets=active_markets,
            ticker_prices=ticker_prices,
        )
        initial = _snapshot_map(operation.initial_account_snapshot)
        targets: list[dict[str, str]] = []
        items: list[dict[str, Any]] = []
        for candidate in candidates:
            initial_item = initial.get(candidate.currency, {})
            item = {
                "currency": candidate.currency,
                "market": candidate.market,
                "requested_volume": decimal_string(candidate.requested_volume),
                "initial_balance": initial_item.get("balance", "0"),
                "initial_locked": initial_item.get("locked", "0"),
                "post_cancel_balance": decimal_string(candidate.balance),
                "post_cancel_locked": decimal_string(candidate.locked),
                "estimated_value_krw": (
                    decimal_string(candidate.estimated_value_krw)
                    if candidate.estimated_value_krw is not None
                    else None
                ),
                "result_code": None if candidate.should_submit else candidate.result_code,
            }
            items.append(item)
            if candidate.should_submit:
                targets.append(
                    {
                        "market": candidate.market,
                        "volume": decimal_string(candidate.requested_volume),
                    }
                )

        now = utcnow()
        async with self._session_factory() as db:
            current = await self._liquidation_repository.get_operation(
                db, operation.id, for_update=True
            )
            if current is None or current.phase != "SNAPSHOTTING_TARGETS":
                await db.commit()
                return False
            self._assert_operation_lease(current)
            if current.target_snapshot is None:
                current.target_snapshot = targets
                current.result_snapshot = items
                current.version += 1
                await self._liquidation_repository.append_event(
                    db,
                    current,
                    event_type="TARGET_SNAPSHOTTED",
                    source="WORKER",
                    details={"target_count": len(targets), "candidate_count": len(items)},
                    now=now,
                )
            await db.commit()

        if not targets:
            await self._transition_phase(operation.id, "VERIFYING")
            return True
        try:
            await self._ensure_liquidation_authorized(
                await self._get_v2_operation(operation.id)
            )
        except LiveOrderControlPolicyError as exc:
            await self._terminate_operation(
                operation.id,
                status="FAILED",
                verification_status="ERROR",
                error_code=str(getattr(exc, "error_code", "EMERGENCY_AUTH_REVOKED")),
                error_message=str(exc),
            )
            return False
        await self._transition_phase(operation.id, "SUBMITTING")
        return True

    async def _phase_submitting(self, operation: LiquidationOperation) -> bool:
        targets = operation.target_snapshot if isinstance(operation.target_snapshot, list) else []
        try:
            await self._ensure_liquidation_authorized(operation)
        except LiveOrderControlPolicyError as exc:
            error_code = str(
                getattr(exc, "error_code", "EMERGENCY_AUTH_REVOKED")
            )
            for target in targets:
                await self._merge_result_item(
                    operation.id,
                    str(target.get("market") or "UNKNOWN"),
                    {
                        "submission_status": "ABANDONED",
                        "projection_status": "SKIPPED",
                        "result_code": "ORDER_FAILED",
                        "error_code": error_code,
                        "error_message": str(exc),
                    },
                )
            await self._terminate_operation(
                operation.id,
                status="FAILED",
                verification_status="ERROR",
                error_code=error_code,
                error_message=str(exc),
            )
            return False
        for target in targets:
            self._assert_operation_lease(
                await self._get_v2_operation(operation.id)
            )
            market = str(target.get("market") or "")
            volume = _safe_decimal(target.get("volume"))
            if not market or volume is None or volume <= 0:
                await self._merge_result_item(
                    operation.id,
                    market or "UNKNOWN",
                    {"error_code": "INVALID_TARGET", "result_code": "ORDER_FAILED"},
                )
                continue
            try:
                result = await self._order_service.execute(
                    LiveOrderRequest(
                        source_type="EMERGENCY_LIQUIDATION",
                        source_ref=f"liquidation:{operation.id}:{market}",
                        market=market,
                        side="ask",
                        ord_type="market",
                        price=None,
                        volume=volume,
                        execution_policy="EMERGENCY_EXIT",
                        liquidation_operation_id=operation.id,
                        reason="EMERGENCY_EXIT",
                    )
                )
                update = {
                    "intent_id": result.intent_id,
                    "identifier": result.identifier,
                    "exchange_uuid": result.exchange_uuid,
                    "submission_status": result.submission_status,
                    "exchange_state": result.exchange_state,
                    "projection_status": result.projection_status,
                    "executed_volume": None,
                    "remaining_volume": None,
                    "error_code": result.error_code,
                    "error_message": result.error_message,
                    "result_code": (
                        "ORDER_FAILED"
                        if result.submission_status in TERMINAL_SUBMISSION_FAILURES
                        else None
                    ),
                }
            except Exception as exc:
                code, message = _safe_error(exc)
                update = {
                    "error_code": code,
                    "error_message": message,
                    "result_code": "ORDER_FAILED",
                }
            await self._merge_result_item(operation.id, market, update)
        await self._transition_phase(operation.id, "WAITING_FILLS")
        return True

    async def _phase_waiting_fills(self, operation: LiquidationOperation) -> bool:
        async with self._session_factory() as db:
            result = await db.execute(
                select(OrderIntent)
                .where(OrderIntent.liquidation_operation_id == operation.id)
                .order_by(OrderIntent.id.asc())
            )
            intents = list(result.scalars().all())
            await db.commit()
        for intent in intents:
            if self._intent_is_active(intent):
                await self._order_service.reconcile_intent(intent.id)

        async with self._session_factory() as db:
            result = await db.execute(
                select(OrderIntent)
                .where(OrderIntent.liquidation_operation_id == operation.id)
                .order_by(OrderIntent.id.asc())
            )
            latest = list(result.scalars().all())
            await db.commit()
        for intent in latest:
            await self._merge_result_item(
                operation.id,
                intent.market,
                self._intent_result_update(intent),
            )
        if any(self._intent_is_active(intent) for intent in latest):
            await self._schedule_operation(operation.id, delay_seconds=15)
            return False
        await self._transition_phase(operation.id, "VERIFYING")
        return True

    async def _phase_verifying(self, operation: LiquidationOperation) -> bool:
        open_orders = await self._list_all_open_orders()
        if open_orders:
            if not await self._persist_additional_discovery(operation.id, open_orders):
                return False
            await self._transition_phase(operation.id, "CANCELING_ORDERS")
            return True

        final_balances = self._parse_accounts_payload(await self._broker.get_accounts())
        final_snapshot = [item.to_snapshot() for item in final_balances]
        positions = await self._live_position_quantities()
        cancellations = await self._get_cancellations(operation.id)
        final_open_orders = await self._list_all_open_orders()
        if final_open_orders:
            if not await self._persist_additional_discovery(
                operation.id, final_open_orders
            ):
                return False
            await self._transition_phase(operation.id, "CANCELING_ORDERS")
            return True
        items, order_summary, remaining_summary, status = self._build_verified_result(
            operation,
            final_balances,
            positions,
            cancellations,
        )
        now = utcnow()
        async with self._session_factory() as db:
            current = await self._liquidation_repository.get_operation(
                db, operation.id, for_update=True
            )
            if current is None or current.phase != "VERIFYING":
                await db.commit()
                return False
            self._assert_operation_lease(current)
            current.final_account_snapshot = final_snapshot
            current.final_accounts_observed_at = now
            current.result_snapshot = items
            current.order_summary = order_summary
            current.remaining_summary = remaining_summary
            current.verification_status = "VERIFIED"
            current.version += 1
            await self._liquidation_repository.append_event(
                db,
                current,
                event_type="ACCOUNT_OBSERVED",
                source="WORKER",
                details={"stage": "final", "asset_count": len(final_balances)},
                now=now,
            )
            await self._liquidation_repository.append_event(
                db,
                current,
                event_type="VERIFICATION_RECORDED",
                source="WORKER",
                details={"status": status, **remaining_summary},
                now=now,
            )
            await db.commit()
        await self._terminate_operation(
            operation.id,
            status=status,
            verification_status="VERIFIED",
            error_code=None,
            error_message=None,
        )
        return False

    async def _read_operation_response(
        self, operation_id: int
    ) -> LiquidationOperationResponse:
        async with self._session_factory() as db:
            operation = await self._liquidation_repository.get_operation(db, operation_id)
            if operation is None:
                raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation_id}")
            cancellations = await self._liquidation_repository.list_cancellations(
                db, operation_id
            ) if operation.contract_version == 2 else []
            response = self._response_from_models(operation, cancellations)
            await db.commit()
            return response

    @staticmethod
    def _response_from_models(
        operation: LiquidationOperation,
        cancellations: Iterable[LiquidationOrderCancellation],
    ) -> LiquidationOperationResponse:
        raw_items = operation.result_snapshot if isinstance(operation.result_snapshot, list) else []
        items: list[LiquidationIntentItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict) or not str(raw.get("market") or "").strip():
                continue
            items.append(
                LiquidationIntentItem(
                    market=str(raw.get("market")),
                    currency=raw.get("currency"),
                    intent_id=raw.get("intent_id"),
                    identifier=raw.get("identifier"),
                    exchange_uuid=raw.get("exchange_uuid"),
                    submission_status=raw.get("submission_status"),
                    exchange_state=raw.get("exchange_state"),
                    projection_status=raw.get("projection_status"),
                    executed_volume=raw.get("executed_volume"),
                    remaining_volume=raw.get("remaining_volume"),
                    requested_volume=raw.get("requested_volume"),
                    initial_balance=raw.get("initial_balance"),
                    initial_locked=raw.get("initial_locked"),
                    post_cancel_balance=raw.get("post_cancel_balance"),
                    post_cancel_locked=raw.get("post_cancel_locked"),
                    final_balance=raw.get("final_balance"),
                    final_locked=raw.get("final_locked"),
                    estimated_value_krw=raw.get("estimated_value_krw"),
                    result_code=raw.get("result_code"),
                    error_code=raw.get("error_code"),
                    error_message=raw.get("error_message"),
                )
            )
        cancellation_items = [
            LiquidationCancellationItem(
                exchange_uuid=row.exchange_uuid,
                identifier=row.identifier,
                market=row.market,
                side=row.side,
                ownership=row.ownership,
                status=row.status,
                attempt_count=row.attempt_count,
                executed_volume=row.executed_volume,
                remaining_volume=row.remaining_volume,
                error_code=row.last_error_code,
                error_message=row.last_error_message,
            )
            for row in cancellations
        ]
        cancellation_summary = dict(operation.cancellation_summary or {})
        order_summary = dict(operation.order_summary or {})
        remaining_summary = dict(operation.remaining_summary or {})
        summary = LiquidationOperationSummary(
            discovered_orders=int(cancellation_summary.get("discovered_orders", 0)),
            cancel_confirmed=int(cancellation_summary.get("cancel_confirmed", 0)),
            cancel_unknown=int(cancellation_summary.get("cancel_unknown", 0)),
            attempted=int(order_summary.get("attempted", 0)),
            succeeded=int(order_summary.get("succeeded", 0)),
            failed=int(order_summary.get("failed", 0)),
            remaining=int(remaining_summary.get("remaining", 0)),
        )
        return LiquidationOperationResponse(
            id=operation.id,
            idempotency_key=operation.idempotency_key,
            contract_version=operation.contract_version,
            cancel_scope=operation.cancel_scope,
            phase=operation.phase,
            verification_status=operation.verification_status,
            status=operation.status,
            summary=summary,
            cancellations=cancellation_items,
            items=items,
            initial_accounts_observed_at=operation.initial_accounts_observed_at,
            post_cancel_accounts_observed_at=operation.post_cancel_accounts_observed_at,
            final_accounts_observed_at=operation.final_accounts_observed_at,
            created_at=operation.created_at,
            updated_at=operation.updated_at,
            completed_at=operation.completed_at,
        )

    async def _transition_phase(self, operation_id: int, to_phase: str) -> None:
        now = utcnow()
        async with self._session_factory() as db:
            operation = await self._liquidation_repository.get_operation(
                db, operation_id, for_update=True
            )
            if operation is None or operation.status in TERMINAL_STATUSES:
                await db.commit()
                return
            self._assert_operation_lease(operation)
            if operation.phase == to_phase:
                await db.commit()
                return
            from_phase = operation.phase
            operation.phase = to_phase
            operation.status = "IN_PROGRESS"
            operation.verification_status = "PENDING"
            operation.next_run_at = now
            operation.retry_count = 0
            operation.version += 1
            await self._liquidation_repository.append_event(
                db,
                operation,
                event_type="PHASE_CHANGED",
                source="WORKER",
                from_phase=from_phase,
                to_phase=to_phase,
                now=now,
            )
            await db.commit()

    async def _schedule_operation(self, operation_id: int, *, delay_seconds: int) -> None:
        async with self._session_factory() as db:
            operation = await self._liquidation_repository.get_operation(
                db, operation_id, for_update=True
            )
            if operation is not None and operation.status in ACTIVE_STATUSES:
                self._assert_operation_lease(operation)
                operation.next_run_at = utcnow() + timedelta(seconds=delay_seconds)
                operation.lease_until = None
                operation.version += 1
            await db.commit()

    async def _release_operation_lease(self, operation_id: int) -> None:
        try:
            async with self._session_factory() as db:
                operation = await self._liquidation_repository.get_operation(
                    db, operation_id, for_update=True
                )
                if operation is not None and operation.status in ACTIVE_STATUSES:
                    token = self._operation_lease_tokens.get(operation_id)
                    if token is None or operation.lease_until == token:
                        operation.lease_until = None
                        operation.next_run_at = operation.next_run_at or utcnow()
                        operation.version += 1
                await db.commit()
        except Exception:
            logger.exception("청산 operation lease 해제 실패: operation_id=%s", operation_id)

    async def _record_transient_error(
        self, operation_id: int, exc: BaseException
    ) -> None:
        code, message = _safe_error(exc)
        now = utcnow()
        try:
            async with self._session_factory() as db:
                operation = await self._liquidation_repository.get_operation(
                    db, operation_id, for_update=True
                )
                if operation is None or operation.status in TERMINAL_STATUSES:
                    await db.commit()
                    return
                self._assert_operation_lease(operation)
                operation.retry_count += 1
                operation.verification_status = "ERROR"
                operation.error_summary = f"{code}: {message}"[:2000]
                operation.lease_until = None
                operation.next_run_at = _retry_at(operation.retry_count, now=now)
                operation.version += 1
                await self._liquidation_repository.append_event(
                    db,
                    operation,
                    event_type="ERROR_RECORDED",
                    source="WORKER",
                    error_code=code,
                    error_message=message,
                    now=now,
                )
                await db.commit()
        except Exception:
            logger.critical(
                "청산 transient 오류를 DB에 기록하지 못했습니다: operation_id=%s",
                operation_id,
                exc_info=True,
            )

    async def _terminate_operation(
        self,
        operation_id: int,
        *,
        status: str,
        verification_status: str,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        now = utcnow()
        async with self._submission_barrier.exclusive() as lease:
            async with lease.transaction() as db:
                operation = await self._liquidation_repository.get_operation(
                    db, operation_id, for_update=True
                )
                if operation is None:
                    raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation_id}")
                if operation.status in TERMINAL_STATUSES:
                    await self._finalize_terminal_in_transaction(db, operation)
                    return
                self._assert_operation_lease(operation)
                from_phase = operation.phase
                operation.status = status
                operation.phase = "TERMINAL"
                operation.verification_status = verification_status
                operation.completed_at = now
                operation.lease_until = None
                operation.next_run_at = None
                operation.error_summary = (
                    f"{error_code}: {error_message}"[:2000]
                    if error_code and error_message
                    else operation.error_summary
                )
                operation.version += 1
                await self._liquidation_repository.append_event(
                    db,
                    operation,
                    event_type="OPERATION_TERMINATED",
                    source="WORKER",
                    from_phase=from_phase,
                    to_phase="TERMINAL",
                    details={"status": status, "verification_status": verification_status},
                    error_code=error_code,
                    error_message=error_message,
                    now=now,
                )
                await self._finalize_terminal_in_transaction(db, operation)

    async def _get_v2_operation(self, operation_id: int) -> LiquidationOperation:
        async with self._session_factory() as db:
            operation = await self._liquidation_repository.get_operation(db, operation_id)
            await db.commit()
        if operation is None:
            raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation_id}")
        return operation

    @staticmethod
    def _stable_operation_uuid(scope: str, operation: LiquidationOperation):
        from app.services.trading.liquidation import _stable_uuid4

        return _stable_uuid4(scope, operation.idempotency_key)

    @staticmethod
    def _parse_accounts_payload(payload: object) -> tuple[AccountBalance, ...]:
        if not isinstance(payload, list):
            raise AccountBalanceValidationError("Upbit 계좌 응답은 배열이어야 합니다.")
        return parse_account_balances(payload)

    async def _list_all_open_orders(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = await self._broker.get_orders_open(
                states=["wait", "watch"],
                page=page,
                limit=100,
                order_by="asc",
            )
            if not isinstance(payload, list):
                raise ValueError("Upbit 미체결 주문 응답은 배열이어야 합니다.")
            if any(not isinstance(item, dict) for item in payload):
                raise ValueError("Upbit 미체결 주문 항목은 객체여야 합니다.")
            rows.extend(payload)
            if len(payload) < 100:
                break
            page += 1
            if page > 10000:
                raise RuntimeError("미체결 주문 페이지 수가 안전 한도를 초과했습니다.")
        return rows

    async def _normalize_discovered_orders(
        self, rows: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            exchange_uuid = str(row.get("uuid") or "").strip()
            market = str(row.get("market") or "").strip().upper()
            side = str(row.get("side") or "").strip().lower()
            state = str(row.get("state") or "").strip().lower()
            identifier = str(row.get("identifier") or "").strip() or None
            if (
                not exchange_uuid
                or len(exchange_uuid) > 64
                or not market
                or market.count("-") != 1
                or any(not part for part in market.split("-", 1))
                or side not in {"bid", "ask"}
                or state not in OPEN_ORDER_STATES
                or (identifier is not None and len(identifier) > 64)
                or exchange_uuid in seen
            ):
                raise ValueError("미체결 주문 응답의 식별자·market·side·state가 유효하지 않습니다.")
            seen.add(exchange_uuid)
            normalized.append(
                {
                    "exchange_uuid": exchange_uuid,
                    "identifier": identifier,
                    "market": market,
                    "side": side,
                    "initial_exchange_state": state,
                }
            )

        if not normalized:
            return []
        uuids = [row["exchange_uuid"] for row in normalized]
        identifiers = [row["identifier"] for row in normalized if row["identifier"]]
        async with self._session_factory() as db:
            predicates = [OrderIntent.exchange_uuid.in_(uuids)]
            if identifiers:
                predicates.append(OrderIntent.identifier.in_(identifiers))
            result = await db.execute(select(OrderIntent).where(or_(*predicates)))
            intents = list(result.scalars().all())
            await db.commit()
        by_uuid: dict[str, OrderIntent] = {}
        by_identifier: dict[str, OrderIntent] = {}
        for intent in intents:
            if intent.exchange_uuid:
                previous = by_uuid.get(intent.exchange_uuid)
                if previous is not None and previous.id != intent.id:
                    raise ValueError("같은 Upbit UUID에 여러 OrderIntent가 연결되어 있습니다.")
                by_uuid[intent.exchange_uuid] = intent
            previous_identifier = by_identifier.get(intent.identifier)
            if previous_identifier is not None and previous_identifier.id != intent.id:
                raise ValueError("같은 identifier에 여러 OrderIntent가 연결되어 있습니다.")
            by_identifier[intent.identifier] = intent
        for row in normalized:
            uuid_intent = by_uuid.get(row["exchange_uuid"])
            identifier_intent = (
                by_identifier.get(row["identifier"]) if row["identifier"] else None
            )
            mismatch_reasons: list[str] = []
            if (
                uuid_intent is not None
                and identifier_intent is not None
                and uuid_intent.id != identifier_intent.id
            ):
                mismatch_reasons.append("UUID와 identifier가 서로 다른 intent를 가리킵니다.")
            intent = uuid_intent or identifier_intent
            if (
                uuid_intent is not None
                and row["identifier"] is not None
                and uuid_intent.identifier != row["identifier"]
            ):
                mismatch_reasons.append("UUID에 연결된 identifier가 다릅니다.")
            if (
                identifier_intent is not None
                and identifier_intent.exchange_uuid is not None
                and identifier_intent.exchange_uuid != row["exchange_uuid"]
            ):
                mismatch_reasons.append("identifier에 연결된 UUID가 다릅니다.")
            if intent is not None and (
                intent.broker != BROKER_NAME
                or intent.account_scope != ACCOUNT_SCOPE
                or intent.market != row["market"]
                or intent.side != row["side"]
                or intent.submission_status not in {"SUBMITTING", "UNKNOWN", "ACCEPTED"}
                or (
                    intent.submission_status == "ACCEPTED"
                    and intent.exchange_state is not None
                    and intent.exchange_state not in OPEN_ORDER_STATES
                )
            ):
                mismatch_reasons.append("broker·account·market·side·상태가 다릅니다.")
            if mismatch_reasons:
                logger.critical(
                    "미체결 주문과 OrderIntent 연결 불일치: intent_id=%s uuid=%s market=%s reasons=%s",
                    intent.id if intent is not None else None,
                    row["exchange_uuid"],
                    row["market"],
                    " ".join(mismatch_reasons),
                )
                row["ownership"] = "EXTERNAL"
                row["order_intent_id"] = None
                row["last_error_code"] = "ORDER_INTENT_LINK_MISMATCH"
                row["last_error_message"] = " ".join(mismatch_reasons)
            else:
                row["ownership"] = "MANAGED" if intent is not None else "EXTERNAL"
                row["order_intent_id"] = intent.id if intent is not None else None
        return normalized

    async def _recover_stale_cancel_claims(self, operation_id: int) -> None:
        now = utcnow()
        async with self._session_factory() as db:
            operation = await self._liquidation_repository.get_operation(
                db, operation_id, for_update=True
            )
            if operation is None:
                await db.commit()
                return
            self._assert_operation_lease(operation)
            result = await db.execute(
                select(LiquidationOrderCancellation)
                .where(
                    LiquidationOrderCancellation.liquidation_operation_id == operation_id,
                    LiquidationOrderCancellation.status == "CANCELING",
                    LiquidationOrderCancellation.lease_until <= now,
                )
                .with_for_update(skip_locked=True)
            )
            rows = list(result.scalars().all())
            for row in rows:
                link_mismatch = row.last_error_code == "ORDER_INTENT_LINK_MISMATCH"
                row.status = "UNKNOWN"
                row.lease_until = None
                row.next_retry_at = now
                if not link_mismatch:
                    row.last_error_code = "CANCEL_RESPONSE_UNKNOWN"
                    row.last_error_message = "취소 호출 뒤 프로세스가 종료되어 조회로 복구합니다."
                row.version += 1
                row.updated_at = now
            await db.commit()

    async def _due_unknown_rows(
        self, operation_id: int
    ) -> list[tuple[int, str, str, str, int]]:
        async with self._session_factory() as db:
            operation = await self._liquidation_repository.get_operation(
                db, operation_id, for_update=True
            )
            if operation is None:
                await db.commit()
                return []
            self._assert_operation_lease(operation)
            rows = await self._liquidation_repository.due_unknown_cancellations(
                db,
                operation_id,
                now=utcnow(),
                lease_for=CANCELLATION_LEASE,
                limit=20,
            )
            result = [
                (row.id, row.exchange_uuid, row.market, row.side, row.version)
                for row in rows
            ]
            await db.commit()
            return result

    async def _lookup_cancel_resolution(
        self,
        exchange_uuid: str,
        *,
        expected_market: str,
        expected_side: str,
    ) -> tuple[str, Decimal | None, Decimal | None, str | None, str | None]:
        try:
            payload = await self._broker.get_order(uuid_=exchange_uuid)
        except Exception as exc:
            code, message = _safe_error(exc)
            if _is_auth_failure(exc):
                return "AUTH_FAILED", None, None, code, message
            return "UNKNOWN", None, None, code, message
        if not isinstance(payload, dict):
            return "UNKNOWN", None, None, "INVALID_LOOKUP_RESPONSE", "주문 조회 응답이 객체가 아닙니다."
        response_uuid = str(payload.get("uuid") or "").strip()
        response_market = str(payload.get("market") or "").strip().upper()
        response_side = str(payload.get("side") or "").strip().lower()
        if (
            response_uuid != exchange_uuid
            or response_market != expected_market
            or response_side != expected_side
        ):
            return (
                "UNKNOWN",
                None,
                None,
                "CANCEL_LOOKUP_MISMATCH",
                "주문 조회 응답의 UUID·market·side가 취소 원장과 일치하지 않습니다.",
            )
        state = str(payload.get("state") or "").strip().lower()
        executed = _safe_decimal(payload.get("executed_volume"))
        remaining = _safe_decimal(payload.get("remaining_volume"))
        if executed is None or remaining is None:
            return "UNKNOWN", None, None, "INVALID_ORDER_VOLUME", "주문 체결·잔여 수량이 유효하지 않습니다."
        if state in TERMINAL_ORDER_STATES:
            return "CONFIRMED", executed, remaining, None, None
        if state in OPEN_ORDER_STATES:
            return "OPEN", executed, remaining, None, None
        return "UNKNOWN", executed, remaining, "UNKNOWN_ORDER_STATE", f"알 수 없는 주문 상태: {state}"

    async def _apply_cancel_resolution(
        self,
        cancellation_id: int,
        resolution: tuple[str, Decimal | None, Decimal | None, str | None, str | None],
        *,
        expected_version: int,
    ) -> None:
        outcome, executed, remaining, error_code, error_message = resolution
        now = utcnow()
        async with self._session_factory() as db:
            operation_id = await db.scalar(
                select(LiquidationOrderCancellation.liquidation_operation_id).where(
                    LiquidationOrderCancellation.id == cancellation_id
                )
            )
            if operation_id is None:
                await db.commit()
                return
            operation = await self._liquidation_repository.get_operation(
                db, operation_id, for_update=True
            )
            if operation is None:
                await db.commit()
                return
            self._assert_operation_lease(operation)
            row = (
                await db.execute(
                    select(LiquidationOrderCancellation)
                    .where(LiquidationOrderCancellation.id == cancellation_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                row is None
                or row.status in {"CONFIRMED", "FAILED"}
                or row.version != expected_version
            ):
                await db.commit()
                return
            link_mismatch = row.last_error_code == "ORDER_INTENT_LINK_MISMATCH"
            if outcome == "CONFIRMED":
                row.status = "CONFIRMED"
                row.resolved_at = now
                row.next_retry_at = None
                if not link_mismatch:
                    row.last_error_code = None
                    row.last_error_message = None
            elif outcome == "OPEN":
                if row.attempt_count >= 3:
                    row.status = "FAILED"
                    row.resolved_at = now
                    if not link_mismatch:
                        row.last_error_code = "CANCEL_RETRY_EXHAUSTED"
                        row.last_error_message = "세 번의 확인된 취소 시도 후에도 주문이 열려 있습니다."
                    row.next_retry_at = None
                else:
                    row.status = "DISCOVERED"
                    row.next_retry_at = _retry_at(row.attempt_count, now=now)
                    if not link_mismatch:
                        row.last_error_code = "ORDER_STILL_OPEN"
                        row.last_error_message = "조회 결과 주문이 아직 wait/watch 상태입니다."
            else:
                row.status = "UNKNOWN"
                # 취소 직후 수행한 첫 UUID 조회도 reconciliation 시도에 포함한다.
                # 이후 due claim이 값을 선증가하므로 15초, 30초, 1분 순으로
                # 지연이 진행되고 15분에서 상한이 고정된다.
                row.reconcile_attempt_count = max(row.reconcile_attempt_count, 1)
                row.next_retry_at = _retry_at(
                    row.reconcile_attempt_count,
                    now=now,
                )
                if not link_mismatch:
                    row.last_error_code = error_code or "CANCEL_STATE_UNKNOWN"
                    row.last_error_message = (
                        error_message or "취소 결과를 확인할 수 없습니다."
                    )[:2000]
            row.executed_volume = executed
            row.remaining_volume = remaining
            row.lease_until = None
            row.last_checked_at = now
            row.version += 1
            row.updated_at = now

            await self._refresh_cancellation_summary(db, operation)
            await self._liquidation_repository.append_event(
                db,
                operation,
                event_type="CANCEL_RESOLVED",
                source="WORKER",
                details={"uuid": row.exchange_uuid, "status": row.status},
                error_code=row.last_error_code,
                error_message=row.last_error_message,
                now=now,
            )
            await db.commit()

    async def _refresh_cancellation_summary(
        self, db, operation: LiquidationOperation
    ) -> None:
        rows = await self._liquidation_repository.list_cancellations(db, operation.id)
        summary = dict(operation.cancellation_summary or {})
        summary["discovered_orders"] = len(rows)
        summary["cancel_confirmed"] = sum(row.status == "CONFIRMED" for row in rows)
        summary["cancel_unknown"] = sum(
            row.status in {"DISCOVERED", "CANCELING", "UNKNOWN"} for row in rows
        )
        summary["external_fill_detected"] = any(
            row.ownership == "EXTERNAL" and Decimal(row.executed_volume or 0) > 0
            for row in rows
        )
        operation.cancellation_summary = summary
        operation.version += 1

    async def _cancellation_state_counts(self, operation_id: int) -> dict[str, int]:
        async with self._session_factory() as db:
            result = await db.execute(
                select(LiquidationOrderCancellation.status, func.count())
                .where(LiquidationOrderCancellation.liquidation_operation_id == operation_id)
                .group_by(LiquidationOrderCancellation.status)
            )
            counts = {str(status): int(count) for status, count in result.all()}
            await db.commit()
            return counts

    async def _persist_additional_discovery(
        self, operation_id: int, rows: list[dict[str, Any]]
    ) -> bool:
        discovered = await self._normalize_discovered_orders(rows)
        now = utcnow()
        async with self._session_factory() as db:
            operation = await self._liquidation_repository.get_operation(
                db, operation_id, for_update=True
            )
            if operation is None:
                raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation_id}")
            self._assert_operation_lease(operation)
            summary = dict(operation.cancellation_summary or {})
            rounds = int(summary.get("discovery_rounds", 0)) + 1
            summary["discovery_rounds"] = rounds
            operation.cancellation_summary = summary
            added = await self._liquidation_repository.discover_cancellations(
                db, operation_id, discovered, now=now
            )
            summary["discovered_orders"] = int(summary.get("discovered_orders", 0)) + added
            operation.cancellation_summary = summary
            operation.version += 1
            await self._liquidation_repository.append_event(
                db,
                operation,
                event_type="ORDER_DISCOVERED",
                source="WORKER",
                details={"count": len(discovered), "new_count": added, "round": rounds},
                now=now,
            )
            await db.commit()
        if rounds <= 4:
            return True
        await self._terminate_operation(
            operation_id,
            status="PARTIAL" if operation.target_snapshot else "FAILED",
            verification_status="ERROR",
            error_code="OPEN_ORDER_REAPPEARED",
            error_message="추가 취소 발견 라운드 한도를 초과했습니다.",
        )
        return False

    async def _active_krw_markets(self) -> set[str]:
        payload = await self._broker.get_all_markets()
        if not isinstance(payload, list):
            raise ValueError("Upbit 마켓 응답은 배열이어야 합니다.")
        result: set[str] = set()
        for raw in payload:
            if not isinstance(raw, dict):
                raise ValueError("Upbit 마켓 항목은 객체여야 합니다.")
            market = str(raw.get("market") or "").strip().upper()
            if market.startswith("KRW-"):
                result.add(market)
        return result

    async def _ticker_prices(self, markets: list[str]) -> dict[str, Decimal]:
        if not markets:
            return {}
        prices: dict[str, Decimal] = {}
        market_set = set(markets)
        for offset in range(0, len(markets), 100):
            payload = await self._broker.get_ticker(markets[offset : offset + 100])
            if not isinstance(payload, list):
                raise ValueError("Upbit 현재가 응답은 배열이어야 합니다.")
            for raw in payload:
                if not isinstance(raw, dict):
                    raise ValueError("Upbit 현재가 항목은 객체여야 합니다.")
                market = str(raw.get("market") or "").strip().upper()
                price = _safe_decimal(raw.get("trade_price"))
                if (
                    market in prices
                    or market not in market_set
                    or price is None
                    or price <= 0
                ):
                    raise ValueError(
                        "Upbit 현재가 응답의 market 또는 가격이 유효하지 않습니다."
                    )
                prices[market] = price
        if set(prices) != set(markets):
            raise ValueError("청산 대상 일부의 현재가를 확인하지 못했습니다.")
        return prices

    async def _merge_result_item(
        self, operation_id: int, market: str, update: Mapping[str, Any]
    ) -> None:
        now = utcnow()
        async with self._session_factory() as db:
            operation = await self._liquidation_repository.get_operation(
                db, operation_id, for_update=True
            )
            if operation is None or operation.status in TERMINAL_STATUSES:
                await db.commit()
                return
            self._assert_operation_lease(operation)
            raw_items = operation.result_snapshot if isinstance(operation.result_snapshot, list) else []
            items = {
                str(item.get("market")): dict(item)
                for item in raw_items
                if isinstance(item, dict) and item.get("market")
            }
            item = items.get(market, {"market": market, "currency": market.split("-", 1)[-1]})
            item.update(dict(update))
            items[market] = item
            operation.result_snapshot = [items[key] for key in sorted(items)]
            operation.version += 1
            await self._liquidation_repository.append_event(
                db,
                operation,
                event_type="ORDER_SUBMITTED",
                source="WORKER",
                details={"market": market, "intent_id": item.get("intent_id")},
                error_code=item.get("error_code"),
                error_message=item.get("error_message"),
                now=now,
            )
            await db.commit()

    @staticmethod
    def _intent_is_active(intent: OrderIntent) -> bool:
        if intent.submission_status in TERMINAL_SUBMISSION_FAILURES:
            return False
        if intent.submission_status in {"PREPARED", "SUBMITTING", "UNKNOWN"}:
            return True
        if intent.submission_status != "ACCEPTED":
            return True
        if intent.exchange_state not in TERMINAL_ORDER_STATES:
            return True
        return intent.projection_status not in TERMINAL_PROJECTIONS

    @staticmethod
    def _intent_result_update(intent: OrderIntent) -> dict[str, Any]:
        failed = intent.submission_status in TERMINAL_SUBMISSION_FAILURES
        unresolved_remaining = (
            intent.submission_status == "ACCEPTED"
            and intent.exchange_state in TERMINAL_ORDER_STATES
            and intent.projection_status == "APPLIED"
            and (
                intent.remaining_volume is None
                or Decimal(intent.remaining_volume) > 0
            )
        )
        return {
            "intent_id": intent.id,
            "identifier": intent.identifier,
            "exchange_uuid": intent.exchange_uuid,
            "submission_status": intent.submission_status,
            "exchange_state": intent.exchange_state,
            "projection_status": intent.projection_status,
            "executed_volume": (
                decimal_string(Decimal(intent.executed_volume))
                if intent.executed_volume is not None
                else None
            ),
            "remaining_volume": (
                decimal_string(Decimal(intent.remaining_volume))
                if intent.remaining_volume is not None
                else None
            ),
            "error_code": (
                intent.last_error_code
                or ("REMAINING_VOLUME_UNRESOLVED" if unresolved_remaining else None)
            ),
            "error_message": (
                intent.last_error_message
                or (
                    "종결 주문의 잔여 수량이 0으로 확인되지 않았습니다."
                    if unresolved_remaining
                    else None
                )
            ),
            "result_code": (
                "ORDER_FAILED"
                if failed
                else "VERIFY_FAILED"
                if unresolved_remaining
                else None
            ),
        }

    async def _live_position_quantities(self) -> dict[str, Decimal]:
        async with self._session_factory() as db:
            result = await db.execute(
                select(Asset.symbol, func.sum(Position.quantity))
                .join(Position, Position.asset_id == Asset.id)
                .where(Position.is_paper.is_(False))
                .group_by(Asset.symbol)
            )
            positions = {
                str(symbol).upper(): Decimal(str(quantity or 0))
                for symbol, quantity in result.all()
            }
            await db.commit()
            return positions

    async def _get_cancellations(
        self, operation_id: int
    ) -> list[LiquidationOrderCancellation]:
        async with self._session_factory() as db:
            rows = await self._liquidation_repository.list_cancellations(db, operation_id)
            await db.commit()
            return rows

    def _build_verified_result(
        self,
        operation: LiquidationOperation,
        final_balances: tuple[AccountBalance, ...],
        positions: Mapping[str, Decimal],
        cancellations: Iterable[LiquidationOrderCancellation],
    ) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, Any], str]:
        cancellation_rows = list(cancellations)
        initial = _snapshot_map(operation.initial_account_snapshot)
        post = _snapshot_map(operation.post_cancel_account_snapshot)
        final = {item.currency: item.to_snapshot() for item in final_balances if item.currency != "KRW"}
        raw_items = operation.result_snapshot if isinstance(operation.result_snapshot, list) else []
        items_by_currency: dict[str, dict[str, Any]] = {}
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            currency = str(raw.get("currency") or str(raw.get("market") or "").split("-")[-1]).upper()
            if currency:
                items_by_currency[currency] = dict(raw)
        position_by_currency: dict[str, Decimal] = {}
        unmapped_positions: dict[str, Decimal] = {}
        for position_market, quantity in positions.items():
            if "-" not in position_market:
                if abs(quantity) > POSITION_EPSILON:
                    unmapped_positions[position_market] = quantity
                continue
            currency = position_market.split("-", 1)[1]
            if not currency or currency == "KRW":
                if abs(quantity) > POSITION_EPSILON:
                    unmapped_positions[position_market] = quantity
                continue
            position_by_currency[currency] = (
                position_by_currency.get(currency, Decimal("0")) + quantity
            )
        position_currencies = set(position_by_currency)
        cancellation_markets = {
            row.market
            for row in cancellation_rows
            if row.ownership == "EXTERNAL" and Decimal(row.executed_volume or 0) > 0
        }
        cancellation_mismatch_markets = {
            row.market
            for row in cancellation_rows
            if getattr(row, "last_error_code", None) == "ORDER_INTENT_LINK_MISMATCH"
        }
        cancellation_evidence_markets = (
            cancellation_markets | cancellation_mismatch_markets
        )
        cancellation_currencies = {
            market.split("-", 1)[1]
            for market in cancellation_evidence_markets
            if "-" in market and market.split("-", 1)[1]
        }
        currencies = (
            set(initial)
            | set(post)
            | set(final)
            | set(items_by_currency)
            | position_currencies
            | cancellation_currencies
        )
        currencies.discard("KRW")
        external_fill_currencies = cancellation_currencies
        items: list[dict[str, Any]] = []
        for currency in sorted(currencies):
            market = f"KRW-{currency}"
            item = items_by_currency.get(currency, {"currency": currency, "market": market})
            initial_item = initial.get(currency, {"balance": "0", "locked": "0"})
            post_item = post.get(currency, {"balance": "0", "locked": "0"})
            final_item = final.get(currency, {"balance": "0", "locked": "0"})
            final_balance = Decimal(str(final_item.get("balance", "0")))
            final_locked = Decimal(str(final_item.get("locked", "0")))
            position_qty = position_by_currency.get(currency, Decimal("0"))
            terminal_projection = (
                item.get("submission_status") == "ACCEPTED"
                and item.get("exchange_state") in TERMINAL_ORDER_STATES
                and item.get("projection_status") == "APPLIED"
            )
            remaining_volume = _safe_decimal(item.get("remaining_volume"))
            item.update(
                {
                    "currency": currency,
                    "market": market,
                    "initial_balance": initial_item.get("balance", "0"),
                    "initial_locked": initial_item.get("locked", "0"),
                    "post_cancel_balance": post_item.get("balance", "0"),
                    "post_cancel_locked": post_item.get("locked", "0"),
                    "final_balance": decimal_string(final_balance),
                    "final_locked": decimal_string(final_locked),
                }
            )
            ledger_mismatch = abs(position_qty - (final_balance + final_locked)) > POSITION_EPSILON
            if currency in external_fill_currencies or ledger_mismatch:
                item["result_code"] = "LEDGER_MISMATCH"
                item["error_code"] = "LEDGER_MISMATCH"
            elif final_balance > 0 or final_locked > 0:
                if final_locked > 0:
                    item["result_code"] = "LOCKED_REMAINING"
                elif item.get("result_code") not in {"DUST_REMAINING", "UNSUPPORTED_MARKET"}:
                    item["result_code"] = "ORDER_FAILED"
            elif terminal_projection and (
                remaining_volume is None or remaining_volume > 0
            ):
                item["result_code"] = "VERIFY_FAILED"
                item["error_code"] = "REMAINING_VOLUME_UNRESOLVED"
                item["error_message"] = "종결 주문의 잔여 수량이 0으로 확인되지 않았습니다."
            elif (
                terminal_projection
                and remaining_volume == 0
                and Decimal(str(item.get("executed_volume") or "0")) > 0
            ):
                item["result_code"] = "LIQUIDATED"
                item["error_code"] = None
            elif Decimal(str(post_item.get("balance", "0"))) > 0:
                item["result_code"] = item.get("result_code") or "ORDER_FAILED"
            elif final_balance == 0 and final_locked == 0 and abs(position_qty) <= POSITION_EPSILON:
                # 실제 보유도 내부 원장도 없던 통화는 응답에서 제외합니다.
                if Decimal(str(initial_item.get("balance", "0"))) == 0 and Decimal(
                    str(initial_item.get("locked", "0"))
                ) == 0:
                    continue
            items.append(item)

        # 거래소가 예상하지 못한 market 형식을 반환했더라도 외부 체결 증거를
        # 버리지 않습니다. 수량·대금 자동 보정 없이 operation 전체를 PARTIAL로 닫습니다.
        for market in sorted(cancellation_evidence_markets):
            if "-" in market and market.split("-", 1)[1]:
                continue
            items.append(
                {
                    "currency": None,
                    "market": market,
                    "result_code": "LEDGER_MISMATCH",
                    "error_code": "LEDGER_MISMATCH",
                }
            )

        for position_market, quantity in sorted(unmapped_positions.items()):
            items.append(
                {
                    "currency": None,
                    "market": position_market,
                    "final_balance": "0",
                    "final_locked": "0",
                    "position_quantity": decimal_string(quantity),
                    "result_code": "LEDGER_MISMATCH",
                    "error_code": "LEDGER_MISMATCH",
                }
            )

        succeeded = sum(item.get("result_code") == "LIQUIDATED" for item in items)
        remaining = sum(item.get("result_code") != "LIQUIDATED" for item in items)
        failed = sum(item.get("result_code") in {"ORDER_FAILED", "VERIFY_FAILED"} for item in items)
        attempted = sum(bool(item.get("intent_id")) for item in items)
        order_summary = {
            "attempted": attempted,
            "succeeded": succeeded,
            "failed": failed,
        }
        remaining_assets = [
            {
                "currency": item.get("currency"),
                "result_code": item.get("result_code"),
                "balance": item.get("final_balance", "0"),
                "locked": item.get("final_locked", "0"),
            }
            for item in items
            if item.get("result_code") != "LIQUIDATED"
        ]
        remaining_summary = {"remaining": remaining, "assets": remaining_assets}
        if not items:
            status = "NO_ASSETS"
        elif remaining == 0 and succeeded == len(items):
            status = "COMPLETED"
        else:
            status = "PARTIAL"
        return items, order_summary, remaining_summary, status

    async def _trip_auth_failure(
        self, operation_id: int | None, exc: BaseException
    ) -> None:
        operation_key = str(operation_id or 0)
        request_id = self._stable_auth_failure_uuid(operation_key)
        code, message = _safe_error(exc)
        try:
            await self._control_service.trip_on_auth_failure(
                AuthFailureBlockCommand(
                    request_id=request_id,
                    reason_code="UPBIT_AUTH_FAILURE",
                    reason_text=f"Upbit 취소·조회 인증 오류로 실주문 기능을 차단합니다: {code}",
                    actor_ref="liquidation-coordinator",
                )
            )
        except Exception:
            logger.exception("Upbit 인증 실패 차단 전환에 실패해 rollout flag를 직접 끕니다.")
            async with self._session_factory() as db:
                await self._control_repository.disable_rollout_flag(db)
                await db.commit()
        finally:
            logger.critical("Upbit 전량청산 인증 실패: %s %s", code, message)

    @staticmethod
    def _stable_auth_failure_uuid(operation_key: str):
        from app.services.trading.liquidation import _stable_uuid4

        return _stable_uuid4("liquidation-cancel-auth-failure", operation_key)
