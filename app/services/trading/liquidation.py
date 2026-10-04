from __future__ import annotations

import logging
from hashlib import sha256
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.live_order_control_repository import (
    CONTROL_ACTION_BLOCKED,
    CONTROL_SOURCE_REST,
    CONTROL_SOURCE_SYSTEM,
    EMERGENCY_AUTHORIZATION_ACTIVE,
    EMERGENCY_AUTHORIZATION_CLOSED,
    EMERGENCY_AUTHORIZATION_REVOKED,
    LIVE_ORDER_MODE_BLOCK_ALL,
    LIVE_ORDER_MODE_EXIT_ONLY,
    LiveOrderControlRequestSupersededError,
    LiveOrderControlRepository,
    LiveOrderControlTransitionError,
    build_control_request_fingerprint,
)
from app.db.trading_mode_repository import TRADING_MODE_LIVE
from app.models.domain import LiquidationOperation, OrderIntent
from app.models.schemas import LiquidationIntentItem, LiquidationOperationResponse
from app.services.brokers.base import BaseBrokerClient
from app.services.trading.account_balances import parse_non_krw_account_balances
from app.services.trading.live_order_execution import LiveOrderExecutionService
from app.services.trading.live_order_execution import LiveOrderRequest
from app.services.trading.live_order_execution import LiveOrderResult
from app.services.trading.live_order_control import (
    INITIAL_EMERGENCY_REVOCATION_REASON,
    AuthorizeEmergencyLiquidationCommand,
    CloseEmergencyLiquidationCommand,
    LiveOrderControlDrainPendingError,
    LiveOrderControlPolicyError,
    LiveOrderControlService,
    LiveOrderControlStateUnavailableError,
    PrepareEmergencyLiquidationCommand,
    SqlAlchemyLiveOrderControlStateStore,
)
from app.services.trading.live_order_submission_barrier import (
    LiveOrderSubmissionBarrierProtocol,
)

logger = logging.getLogger(__name__)

LIQUIDATION_ACTIVE_STATUSES = ("PREPARING", "IN_PROGRESS")
LIQUIDATION_TERMINAL_STATUSES = ("COMPLETED", "PARTIAL", "FAILED", "NO_ASSETS")
ORDER_TERMINAL_STATES = ("done", "cancel")
ORDER_FAILURE_STATUSES = ("REJECTED", "ABANDONED", "NO_ORDER_CONFIRMED")
LIQUIDATION_FAILURE_ERROR_CODES = {
    "BLOCKING_INTENT",
    "NO_EXECUTED_VOLUME",
    "REMAINING_VOLUME_UNKNOWN",
    "REMAINING_VOLUME",
}

LIQUIDATION_CONTROL_ACTOR = "liquidation-coordinator"
LIQUIDATION_PREPARE_REASON = (
    "전량청산 대상 스냅샷을 확정하기 전에 일반 실주문을 차단합니다."
)
LIQUIDATION_AUTHORIZE_REASON = "관리자가 요청한 전량청산 주문 범위만 임시로 허용합니다."


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _stable_uuid4(scope: str, idempotency_key: str) -> UUID:
    """동일 청산 단계가 재실행돼도 같은 UUID v4 감사 키를 반환합니다."""
    raw = bytearray(
        sha256(f"{scope}:{idempotency_key}".encode("utf-8")).digest()[:16]
    )
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def _as_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _decimal_string(value: Decimal) -> str:
    return format(value, "f")


def _account_decimal(value: object) -> Decimal | None:
    if value is None or not str(value).strip():
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _build_target_snapshot(accounts: list[dict[str, Any]]) -> list[dict[str, str]]:
    targets = [
        {
            "market": f"KRW-{account.currency}",
            "volume": _decimal_string(account.available_volume),
        }
        for account in parse_non_krw_account_balances(accounts)
        if account.available_volume > 0
    ]
    targets.sort(key=lambda item: item["market"])
    return targets


def _normalized_targets(value: object) -> tuple[tuple[str, str], ...] | None:
    if not isinstance(value, list):
        return None
    targets: list[tuple[str, str]] = []
    seen_markets: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return None
        market = str(item.get("market") or "").strip().upper()
        volume = _account_decimal(item.get("volume"))
        if (
            not market
            or market in seen_markets
            or volume is None
            or volume <= 0
        ):
            return None
        seen_markets.add(market)
        targets.append((market, format(volume, "f")))
    return tuple(sorted(targets))


def _result_snapshot_item(market: str, result: LiveOrderResult) -> dict[str, Any]:
    return {
        "market": market,
        "intent_id": result.intent_id,
        "identifier": result.identifier,
        "exchange_uuid": result.exchange_uuid,
        "submission_status": result.submission_status,
        "exchange_state": result.exchange_state,
        "projection_status": result.projection_status,
        "order_history_id": result.order_history_id,
        "error_code": result.error_code,
        "error_message": result.error_message,
    }


def _intent_snapshot_item(intent: OrderIntent) -> dict[str, Any]:
    error_code = intent.last_error_code
    error_message = intent.last_error_message
    if intent.exchange_state in ORDER_TERMINAL_STATES:
        if intent.projection_status == "SKIPPED" and not error_code:
            error_code = "NO_EXECUTED_VOLUME"
            error_message = "종결 주문의 실제 체결량이 0입니다."
        elif intent.projection_status == "APPLIED" and not error_code:
            if intent.remaining_volume is None:
                error_code = "REMAINING_VOLUME_UNKNOWN"
                error_message = "종결 주문의 잔여 수량을 확인할 수 없습니다."
            elif Decimal(intent.remaining_volume) > 0:
                error_code = "REMAINING_VOLUME"
                error_message = "종결 주문에 미체결 잔여 수량이 있습니다."
    return {
        "market": intent.market,
        "intent_id": intent.id,
        "identifier": intent.identifier,
        "exchange_uuid": intent.exchange_uuid,
        "submission_status": intent.submission_status,
        "exchange_state": intent.exchange_state,
        "projection_status": intent.projection_status,
        "executed_volume": (
            _decimal_string(Decimal(intent.executed_volume))
            if intent.executed_volume is not None
            else None
        ),
        "remaining_volume": (
            _decimal_string(Decimal(intent.remaining_volume))
            if intent.remaining_volume is not None
            else None
        ),
        "error_code": error_code,
        "error_message": error_message,
    }


def _classify_operation_status(items: list[dict[str, Any]]) -> str:
    if not items:
        return "NO_ASSETS"

    successful = 0
    failed = 0
    processing = 0
    for item in items:
        submission_status = str(item.get("submission_status") or "")
        exchange_state = str(item.get("exchange_state") or "")
        projection_status = str(item.get("projection_status") or "")

        if (
            submission_status in ORDER_FAILURE_STATUSES
            or (not item.get("intent_id") and item.get("error_code"))
            or item.get("error_code") in LIQUIDATION_FAILURE_ERROR_CODES
        ):
            failed += 1
            continue
        if submission_status == "ACCEPTED" and exchange_state in ORDER_TERMINAL_STATES:
            executed_volume = _account_decimal(item.get("executed_volume"))
            remaining_volume = _account_decimal(item.get("remaining_volume"))
            if (
                projection_status == "APPLIED"
                and executed_volume is not None
                and executed_volume > 0
                and remaining_volume is not None
                and remaining_volume <= 0
            ):
                successful += 1
            elif projection_status in {"APPLIED", "SKIPPED"}:
                failed += 1
            else:
                processing += 1
            continue
        processing += 1

    if processing:
        return "IN_PROGRESS"
    if successful == len(items):
        return "COMPLETED"
    if successful and failed:
        return "PARTIAL"
    return "FAILED"


def liquidation_operation_response(
    operation: LiquidationOperation,
) -> LiquidationOperationResponse:
    raw_items = operation.result_snapshot if isinstance(operation.result_snapshot, list) else []
    items = [
        LiquidationIntentItem(
            market=str(item.get("market") or ""),
            intent_id=item.get("intent_id"),
            identifier=item.get("identifier"),
            exchange_uuid=item.get("exchange_uuid"),
            submission_status=item.get("submission_status"),
            exchange_state=item.get("exchange_state"),
            projection_status=item.get("projection_status"),
            executed_volume=item.get("executed_volume"),
            remaining_volume=item.get("remaining_volume"),
            error_code=item.get("error_code"),
        )
        for item in raw_items
        if isinstance(item, dict) and str(item.get("market") or "").strip()
    ]
    return LiquidationOperationResponse(
        id=operation.id,
        idempotency_key=operation.idempotency_key,
        status=operation.status,
        items=items,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
        completed_at=operation.completed_at,
    )


class LiquidationCoordinator:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        broker: BaseBrokerClient,
        submission_barrier: LiveOrderSubmissionBarrierProtocol,
    ) -> None:
        self._session_factory = session_factory
        self._broker = broker
        self._submission_barrier = submission_barrier
        self._control_repository = LiveOrderControlRepository()
        self._control_state_store = SqlAlchemyLiveOrderControlStateStore()
        self._control_service = LiveOrderControlService(barrier=submission_barrier)
        self._order_service = LiveOrderExecutionService(
            session_factory,
            broker,
            submission_barrier,
        )

    async def execute(self, idempotency_key: str) -> LiquidationOperationResponse:
        operation = await self._create_or_get_operation(idempotency_key)
        if (
            operation.emergency_authorization_status
            == EMERGENCY_AUTHORIZATION_REVOKED
            and operation.emergency_revocation_reason
            != INITIAL_EMERGENCY_REVOCATION_REASON
        ):
            raise LiveOrderControlPolicyError(
                "명시적으로 폐기된 청산 작업은 같은 키로 다시 승인할 수 없습니다.",
                error_code="EMERGENCY_AUTH_REVOKED",
            )
        if operation.status in LIQUIDATION_TERMINAL_STATUSES:
            if self._requires_terminal_finalization(operation):
                await self._close_terminal_operation(operation.id)
            return liquidation_operation_response(operation)

        is_initial_authorization = (
            operation.emergency_authorization_status
            == EMERGENCY_AUTHORIZATION_REVOKED
            and operation.emergency_revocation_reason
            == INITIAL_EMERGENCY_REVOCATION_REASON
        )
        if is_initial_authorization:
            targets = await self._prepare_snapshot_and_authorize(operation)
        else:
            targets = await self._ensure_target_snapshot(operation.id)
        if not targets:
            return await self.get_operation(operation.id)

        operation = await self._get_operation_model(operation.id)
        if operation.status in LIQUIDATION_TERMINAL_STATUSES:
            if self._requires_terminal_finalization(operation):
                await self._close_terminal_operation(operation.id)
            return liquidation_operation_response(operation)
        try:
            await self._ensure_liquidation_authorized(operation)
        except LiveOrderControlPolicyError as exc:
            if exc.error_code == "EMERGENCY_AUTH_REVOKED":
                try:
                    await self.refresh_operation(operation.id)
                except Exception:
                    logger.exception(
                        "폐기된 청산 operation 결과 종결 실패: operation_id=%s",
                        operation.id,
                    )
            raise

        for target in targets:
            market = target["market"]
            volume = _as_decimal(target["volume"])
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
                item = _result_snapshot_item(market, result)
            except Exception as exc:
                logger.exception(
                    "전량청산 주문 실행 실패: operation_id=%s market=%s",
                    operation.id,
                    market,
                )
                item = {
                    "market": market,
                    "intent_id": None,
                    "identifier": None,
                    "exchange_uuid": None,
                    "submission_status": None,
                    "exchange_state": None,
                    "projection_status": None,
                    "error_code": type(exc).__name__,
                    "error_message": str(exc)[:1000],
                }
            await self._save_result_item(operation.id, item)

        return await self.refresh_operation(operation.id)

    async def get_operation(self, operation_id: int) -> LiquidationOperationResponse:
        async with self._session_factory() as db:
            operation = await db.get(LiquidationOperation, operation_id)
            if operation is None:
                raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation_id}")
            should_refresh = operation.status in LIQUIDATION_ACTIVE_STATUSES
        if should_refresh:
            return await self.refresh_operation(operation_id)
        if (
            operation.status in LIQUIDATION_TERMINAL_STATUSES
            and self._requires_terminal_finalization(operation)
        ):
            await self._close_terminal_operation(operation_id)
        return liquidation_operation_response(operation)

    async def refresh_operation(self, operation_id: int) -> LiquidationOperationResponse:
        return await self._refresh_operation_state(operation_id)

    async def _refresh_operation_state(
        self,
        operation_id: int,
    ) -> LiquidationOperationResponse:
        async with self._submission_barrier.exclusive() as lease:
            async with lease.transaction() as db:
                operation = await db.get(
                    LiquidationOperation,
                    operation_id,
                    with_for_update=True,
                )
                if operation is None:
                    raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation_id}")
                if operation.status in LIQUIDATION_TERMINAL_STATUSES:
                    await self._finalize_terminal_in_transaction(db, operation)
                    return liquidation_operation_response(operation)
                if operation.target_snapshot is None:
                    return liquidation_operation_response(operation)

                intent_result = await db.execute(
                    select(OrderIntent)
                    .where(OrderIntent.liquidation_operation_id == operation_id)
                    .order_by(OrderIntent.market.asc(), OrderIntent.id.asc())
                )
                intents = list(intent_result.scalars().all())
                intent_markets = {intent.market for intent in intents}
                existing_items = (
                    operation.result_snapshot
                    if isinstance(operation.result_snapshot, list)
                    else []
                )
                items_by_market = {
                    str(item.get("market")): dict(item)
                    for item in existing_items
                    if isinstance(item, dict) and item.get("market")
                }
                for intent in intents:
                    items_by_market[intent.market] = _intent_snapshot_item(intent)

                target_items = (
                    operation.target_snapshot
                    if isinstance(operation.target_snapshot, list)
                    else []
                )
                authorization_revoked = (
                    operation.emergency_authorization_status
                    == EMERGENCY_AUTHORIZATION_REVOKED
                    and operation.emergency_revocation_reason
                    != INITIAL_EMERGENCY_REVOCATION_REASON
                )
                for target in target_items:
                    if not isinstance(target, dict):
                        continue
                    market = str(target.get("market") or "")
                    if not market:
                        continue
                    if authorization_revoked and market not in intent_markets:
                        items_by_market[market] = {
                            "market": market,
                            "intent_id": None,
                            "submission_status": "ABANDONED",
                            "projection_status": "SKIPPED",
                            "error_code": "EMERGENCY_AUTH_REVOKED",
                            "error_message": (
                                "청산 권한이 폐기되어 이 대상의 신규 주문을 제출하지 않았습니다."
                            ),
                        }
                    elif market not in items_by_market:
                        items_by_market[market] = {
                            "market": market,
                            "intent_id": None,
                            "submission_status": "PREPARING",
                        }

                items = [items_by_market[key] for key in sorted(items_by_market)]
                operation.result_snapshot = items
                operation.status = _classify_operation_status(items)
                operation.error_summary = self._build_error_summary(items)
                if operation.status in LIQUIDATION_TERMINAL_STATUSES:
                    operation.completed_at = operation.completed_at or _utcnow()
                    await self._finalize_terminal_in_transaction(db, operation)
                else:
                    operation.completed_at = None
                await db.flush()
                return liquidation_operation_response(operation)

    async def refresh_in_progress_operations(self, limit: int = 100) -> int:
        async with self._session_factory() as db:
            result = await db.execute(
                select(LiquidationOperation.id)
                .where(
                    or_(
                        LiquidationOperation.status.in_(LIQUIDATION_ACTIVE_STATUSES),
                        and_(
                            LiquidationOperation.status.in_(
                                LIQUIDATION_TERMINAL_STATUSES
                            ),
                            LiquidationOperation.emergency_authorization_status
                            == EMERGENCY_AUTHORIZATION_ACTIVE,
                        ),
                        and_(
                            LiquidationOperation.status.in_(
                                LIQUIDATION_TERMINAL_STATUSES
                            ),
                            LiquidationOperation.emergency_authorization_status
                            == EMERGENCY_AUTHORIZATION_REVOKED,
                            LiquidationOperation.emergency_revocation_reason
                            == INITIAL_EMERGENCY_REVOCATION_REASON,
                        ),
                    )
                )
                .order_by(LiquidationOperation.created_at.asc(), LiquidationOperation.id.asc())
                .limit(max(1, limit))
            )
            operation_ids = list(result.scalars().all())

        refreshed = 0
        for operation_id in operation_ids:
            await self.refresh_operation(operation_id)
            refreshed += 1
        return refreshed

    async def _create_or_get_operation(self, idempotency_key: str) -> LiquidationOperation:
        async with self._submission_barrier.exclusive() as lease:
            async with lease.transaction() as db:
                existing = await db.scalar(
                    select(LiquidationOperation)
                    .where(LiquidationOperation.idempotency_key == idempotency_key)
                    .with_for_update()
                )
                if existing is not None:
                    return existing

                if (
                    await self._control_state_store.get_trading_mode(db)
                    != TRADING_MODE_LIVE
                ):
                    raise LiveOrderControlPolicyError(
                        "정상적인 live 거래 모드에서만 Upbit 전량청산을 생성할 수 있습니다.",
                        error_code="TRADING_MODE_LIVE_REQUIRED",
                    )

                inserted_id = (
                    await db.execute(
                        postgresql_insert(LiquidationOperation)
                        .values(idempotency_key=idempotency_key, status="PREPARING")
                        .on_conflict_do_nothing(index_elements=["idempotency_key"])
                        .returning(LiquidationOperation.id)
                    )
                ).scalar_one_or_none()
                if inserted_id is not None:
                    operation = await db.get(LiquidationOperation, inserted_id)
                else:
                    result = await db.execute(
                        select(LiquidationOperation).where(
                            LiquidationOperation.idempotency_key == idempotency_key
                        )
                    )
                    operation = result.scalar_one_or_none()
                if operation is None:
                    raise RuntimeError("전량청산 작업을 생성하거나 조회하지 못했습니다.")
                return operation

    async def _get_operation_model(self, operation_id: int) -> LiquidationOperation:
        async with self._session_factory() as db:
            operation = await db.get(LiquidationOperation, operation_id)
            if operation is None:
                raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation_id}")
            return operation

    async def _ensure_liquidation_authorized(
        self,
        operation: LiquidationOperation,
    ) -> None:
        async with self._session_factory() as db:
            current = await db.get(LiquidationOperation, operation.id)
            gate = await self._control_repository.get_submission_gate_snapshot(db)
            await db.commit()

        if current is None:
            raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation.id}")
        if current.status not in LIQUIDATION_ACTIVE_STATUSES:
            raise LiveOrderControlPolicyError(
                "종결된 청산 작업에는 신규 주문 권한을 부여할 수 없습니다.",
                error_code="EMERGENCY_AUTH_REVOKED",
            )

        if current.emergency_authorization_status == EMERGENCY_AUTHORIZATION_ACTIVE:
            authorization = gate.emergency_authorization
            expected_targets = _normalized_targets(current.target_snapshot)
            if (
                not expected_targets
                or not gate.emergency_submission_allowed(current.id)
                or authorization is None
                or authorization.target_snapshot != expected_targets
            ):
                raise LiveOrderControlStateUnavailableError(
                    "활성 청산 권한과 현재 EXIT_ONLY 제어 상태가 일치하지 않습니다."
                )
            return

        if current.emergency_authorization_status == EMERGENCY_AUTHORIZATION_CLOSED:
            raise LiveOrderControlStateUnavailableError(
                "진행 중 청산 작업의 권한이 이미 CLOSED 상태입니다."
            )
        if current.emergency_authorization_status != EMERGENCY_AUTHORIZATION_REVOKED:
            raise LiveOrderControlStateUnavailableError(
                "해석할 수 없는 청산 권한 상태입니다."
            )
        if (
            current.emergency_revocation_reason
            != INITIAL_EMERGENCY_REVOCATION_REASON
        ):
            raise LiveOrderControlPolicyError(
                "명시적으로 폐기된 청산 작업은 같은 키로 다시 승인할 수 없습니다.",
                error_code="EMERGENCY_AUTH_REVOKED",
            )

        control = gate.control
        if control is None:
            raise LiveOrderControlStateUnavailableError(
                "전역 실주문 제어 상태를 확인할 수 없습니다."
            )
        if (
            control.active_liquidation_operation_id is not None
            and control.active_liquidation_operation_id != current.id
        ):
            raise LiveOrderControlPolicyError(
                "다른 전량청산 작업이 이미 EXIT_ONLY 권한을 사용 중입니다.",
                error_code="ORDER_GATE_GENERATION_CONFLICT",
            )
        if (
            control.mode == LIVE_ORDER_MODE_EXIT_ONLY
            or control.active_liquidation_operation_id is not None
        ):
            raise LiveOrderControlStateUnavailableError(
                "청산 작업의 초기 권한 상태와 EXIT_ONLY 제어 상태가 일치하지 않습니다."
            )

        await self._control_service.authorize_liquidation(
            AuthorizeEmergencyLiquidationCommand(
                request_id=current.idempotency_key,
                operation_id=current.id,
                expected_generation=control.generation,
                expected_version=control.version,
                reason_code="EMERGENCY_LIQUIDATION",
                reason_text=LIQUIDATION_AUTHORIZE_REASON,
                source=CONTROL_SOURCE_REST,
                actor_ref=LIQUIDATION_CONTROL_ACTOR,
            )
        )

    async def _prepare_snapshot_and_authorize(
        self,
        operation: LiquidationOperation,
    ) -> list[dict[str, str]]:
        """하나의 exclusive lease에서 차단·스냅샷·EXIT_ONLY 승인을 직렬화합니다."""
        prepare_command = PrepareEmergencyLiquidationCommand(
            request_id=_stable_uuid4(
                "liquidation-prepare",
                operation.idempotency_key,
            ),
            operation_id=operation.id,
            reason_code="EMERGENCY_LIQUIDATION_PREPARE",
            reason_text=LIQUIDATION_PREPARE_REASON,
            source=CONTROL_SOURCE_REST,
            actor_ref=LIQUIDATION_CONTROL_ACTOR,
        )

        async with self._submission_barrier.exclusive() as lease:
            existing_targets: list[dict[str, str]] | None = None
            rejection: Exception | None = None
            drain_pending = False
            async with lease.transaction() as db:
                current = (
                    await self._control_state_store.get_liquidation_operation_for_update(
                        db,
                        operation.id,
                    )
                )
                if current is None:
                    raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation.id}")
                if current.status in LIQUIDATION_TERMINAL_STATUSES:
                    await self._finalize_terminal_in_transaction(db, current)
                    return (
                        current.target_snapshot
                        if isinstance(current.target_snapshot, list)
                        else []
                    )
                if current.emergency_authorization_status == EMERGENCY_AUTHORIZATION_ACTIVE:
                    if not isinstance(current.target_snapshot, list):
                        raise LiveOrderControlStateUnavailableError(
                            "활성 청산 권한에 불변 대상 스냅샷이 없습니다."
                        )
                    return current.target_snapshot

                control = await self._control_repository.get_control(db, for_update=True)
                if (
                    control is not None
                    and control.active_liquidation_operation_id is not None
                    and control.active_liquidation_operation_id != current.id
                ):
                    message = "다른 전량청산 작업이 이미 EXIT_ONLY 권한을 사용 중입니다."
                    self._mark_rejected_liquidation(
                        current,
                        reason="CONCURRENT_LIQUIDATION_REJECTED",
                        error_summary=message,
                    )
                    await db.flush()
                    rejection = LiveOrderControlPolicyError(
                        message,
                        error_code="ORDER_GATE_GENERATION_CONFLICT",
                    )
                elif (
                    await self._control_state_store.get_trading_mode(db)
                    != TRADING_MODE_LIVE
                ):
                    message = (
                        "정상적인 live 거래 모드가 아니므로 전량청산 준비를 종결했습니다."
                    )
                    self._mark_rejected_liquidation(
                        current,
                        reason="TRADING_MODE_LIVE_REQUIRED",
                        error_summary=message,
                    )
                    await db.flush()
                    rejection = LiveOrderControlPolicyError(
                        message,
                        error_code="TRADING_MODE_LIVE_REQUIRED",
                    )
                else:
                    try:
                        _, drain_pending = (
                            await self._control_service.prepare_liquidation_in_transaction(
                                db,
                                prepare_command,
                            )
                        )
                    except LiveOrderControlRequestSupersededError as exc:
                        self._mark_rejected_liquidation(
                            current,
                            reason="LIQUIDATION_PREPARE_SUPERSEDED",
                            error_summary=str(exc),
                        )
                        await db.flush()
                        rejection = exc
                    except (
                        LiveOrderControlPolicyError,
                        LiveOrderControlStateUnavailableError,
                        LiveOrderControlTransitionError,
                    ) as exc:
                        error_code = str(
                            getattr(exc, "error_code", type(exc).__name__)
                        )
                        self._mark_rejected_liquidation(
                            current,
                            reason=error_code,
                            error_summary=str(exc),
                        )
                        await db.flush()
                        rejection = exc
                    if isinstance(current.target_snapshot, list):
                        existing_targets = current.target_snapshot

            if rejection is not None:
                raise rejection

            if drain_pending:
                raise LiveOrderControlDrainPendingError(
                    "청산 준비 차단은 적용됐지만 SUBMITTING 주문의 POST 종료를 아직 확인하지 못했습니다."
                )

            account_error: Exception | None = None
            targets = existing_targets
            if targets is None:
                try:
                    targets = _build_target_snapshot(await self._broker.get_accounts())
                except Exception as exc:  # 계정 조회 실패도 같은 terminal finalizer로 처리
                    account_error = exc
                    targets = []

            async with lease.transaction() as db:
                current = (
                    await self._control_state_store.get_liquidation_operation_for_update(
                        db,
                        operation.id,
                    )
                )
                if current is None:
                    raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation.id}")
                if current.status in LIQUIDATION_TERMINAL_STATUSES:
                    await self._finalize_terminal_in_transaction(db, current)
                    return (
                        current.target_snapshot
                        if isinstance(current.target_snapshot, list)
                        else []
                    )

                if not isinstance(current.target_snapshot, list):
                    current.target_snapshot = targets
                    current.result_snapshot = []
                else:
                    targets = current.target_snapshot

                if account_error is not None:
                    current.status = "FAILED"
                    current.error_summary = str(account_error)[:2000]
                    current.completed_at = _utcnow()
                    await self._finalize_terminal_in_transaction(db, current)
                    return []
                if not targets:
                    current.status = "NO_ASSETS"
                    current.completed_at = _utcnow()
                    await self._finalize_terminal_in_transaction(db, current)
                    return []

                current.status = "IN_PROGRESS"
                control = await self._control_repository.get_control(db, for_update=True)
                if control is None:
                    raise LiveOrderControlStateUnavailableError(
                        "전역 실주문 제어 상태를 확인할 수 없습니다."
                    )
                await self._control_service.authorize_liquidation_in_transaction(
                    db,
                    AuthorizeEmergencyLiquidationCommand(
                        request_id=current.idempotency_key,
                        operation_id=current.id,
                        expected_generation=control.generation,
                        expected_version=control.version,
                        reason_code="EMERGENCY_LIQUIDATION",
                        reason_text=LIQUIDATION_AUTHORIZE_REASON,
                        source=CONTROL_SOURCE_REST,
                        actor_ref=LIQUIDATION_CONTROL_ACTOR,
                    ),
                )
                return targets

    async def _close_terminal_operation(self, operation_id: int) -> None:
        async with self._submission_barrier.exclusive() as lease:
            async with lease.transaction() as db:
                operation = (
                    await self._control_state_store.get_liquidation_operation_for_update(
                        db,
                        operation_id,
                    )
                )
                if operation is None:
                    raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation_id}")
                await self._finalize_terminal_in_transaction(db, operation)

    async def _block_initial_terminal_operation(self, operation_id: int) -> bool:
        """미승인 종결 작업만 조건부 BLOCK_ALL로 전환합니다."""
        async with self._submission_barrier.exclusive() as lease:
            async with lease.transaction() as db:
                operation = (
                    await self._control_state_store.get_liquidation_operation_for_update(
                        db,
                        operation_id,
                    )
                )
                if operation is None:
                    raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation_id}")
                return await self._block_initial_terminal_operation_in_transaction(
                    db,
                    operation,
                )

    async def _finalize_terminal_in_transaction(
        self,
        db: AsyncSession,
        operation: LiquidationOperation,
    ) -> None:
        """operation 결과와 authorization/control 종결을 같은 트랜잭션에 묶습니다."""
        if operation.status not in LIQUIDATION_TERMINAL_STATUSES:
            return
        if operation.emergency_authorization_status == EMERGENCY_AUTHORIZATION_CLOSED:
            return
        if operation.emergency_authorization_status == EMERGENCY_AUTHORIZATION_REVOKED:
            if (
                operation.emergency_revocation_reason
                == INITIAL_EMERGENCY_REVOCATION_REASON
            ):
                await self._block_initial_terminal_operation_in_transaction(db, operation)
            return
        await self._control_service.close_liquidation_in_transaction(
            db,
            CloseEmergencyLiquidationCommand(
                request_id=_stable_uuid4(
                    "liquidation-close",
                    operation.idempotency_key,
                ),
                operation_id=operation.id,
                reason_code=f"LIQUIDATION_{operation.status}",
                reason_text=(
                    f"전량청산 작업이 {operation.status} 상태로 종결되어 신규 실주문을 차단합니다."
                ),
                source=CONTROL_SOURCE_SYSTEM,
                actor_ref=LIQUIDATION_CONTROL_ACTOR,
            ),
        )

    @staticmethod
    def _mark_rejected_liquidation(
        operation: LiquidationOperation,
        *,
        reason: str,
        error_summary: str,
    ) -> None:
        now = _utcnow()
        operation.status = "FAILED"
        operation.error_summary = error_summary[:2000]
        operation.completed_at = now
        operation.emergency_authorization_status = EMERGENCY_AUTHORIZATION_REVOKED
        operation.emergency_revoked_at = now
        operation.emergency_revocation_reason = reason
        operation.emergency_closed_at = None

    @staticmethod
    def _requires_terminal_finalization(operation: LiquidationOperation) -> bool:
        if operation.emergency_authorization_status == EMERGENCY_AUTHORIZATION_ACTIVE:
            return True
        return (
            operation.emergency_authorization_status
            == EMERGENCY_AUTHORIZATION_REVOKED
            and operation.emergency_revocation_reason
            == INITIAL_EMERGENCY_REVOCATION_REASON
        )

    async def _block_initial_terminal_operation_in_transaction(
        self,
        db: AsyncSession,
        operation: LiquidationOperation,
    ) -> bool:
        """호출자가 보유한 exclusive 트랜잭션에서 미승인 종결을 차단합니다."""
        request_id = _stable_uuid4(
            "liquidation-initial-terminal-block",
            operation.idempotency_key,
        )
        reason_code = "LIQUIDATION_TERMINATED_BEFORE_AUTHORIZATION"
        reason_text = "청산 주문 권한 부여 전에 작업이 종결되어 신규 실주문을 차단합니다."
        fingerprint = build_control_request_fingerprint(
            action=CONTROL_ACTION_BLOCKED,
            expected_generation=None,
            target_mode=LIVE_ORDER_MODE_BLOCK_ALL,
            active_liquidation_operation_id=None,
            reason_code=reason_code,
            reason_text=reason_text,
            source=CONTROL_SOURCE_SYSTEM,
            actor_ref=LIQUIDATION_CONTROL_ACTOR,
            confirmation="LIQUIDATION_INITIAL_TERMINAL_BLOCK",
        )
        if operation.status not in LIQUIDATION_TERMINAL_STATUSES:
            return False
        if (
            operation.emergency_authorization_status
            != EMERGENCY_AUTHORIZATION_REVOKED
            or operation.emergency_revocation_reason
            != INITIAL_EMERGENCY_REVOCATION_REASON
        ):
            return True

        control = await self._control_repository.get_control(db, for_update=True)
        if control is None:
            raise LiveOrderControlStateUnavailableError(
                "전역 실주문 제어 상태를 확인할 수 없습니다."
            )
        if control.active_liquidation_operation_id is not None:
            if control.active_liquidation_operation_id != operation.id:
                raise LiveOrderControlPolicyError(
                    "다른 전량청산 작업이 이미 EXIT_ONLY 권한을 사용 중입니다.",
                    error_code="ORDER_GATE_GENERATION_CONFLICT",
                )
            raise LiveOrderControlStateUnavailableError(
                "미승인 청산 작업이 EXIT_ONLY 제어에 연결된 비정상 상태입니다."
            )

        try:
            await self._control_repository.transition_control(
                db,
                expected_generation=None,
                target_mode=LIVE_ORDER_MODE_BLOCK_ALL,
                active_liquidation_operation_id=None,
                action=CONTROL_ACTION_BLOCKED,
                request_id=request_id,
                request_fingerprint=fingerprint,
                reason_code=reason_code,
                reason_text=reason_text,
                source=CONTROL_SOURCE_SYSTEM,
                actor_ref=LIQUIDATION_CONTROL_ACTOR,
                now=_utcnow(),
            )
        except LiveOrderControlRequestSupersededError:
            return False
        await self._control_state_store.set_bot_active(db, is_active=False)
        self._mark_initial_terminal_authorization_closed(operation)
        return True

    @staticmethod
    def _mark_initial_terminal_authorization_closed(
        operation: LiquidationOperation,
    ) -> None:
        operation.emergency_authorization_status = EMERGENCY_AUTHORIZATION_CLOSED
        operation.emergency_closed_at = _utcnow()
        operation.emergency_revoked_at = None
        operation.emergency_revocation_reason = None

    async def _ensure_target_snapshot(self, operation_id: int) -> list[dict[str, str]]:
        async with self._session_factory() as db:
            operation = await db.get(LiquidationOperation, operation_id)
            if operation is None:
                raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation_id}")
            if isinstance(operation.target_snapshot, list):
                return operation.target_snapshot
        raise LiveOrderControlStateUnavailableError(
            "승인되었거나 재개된 청산 operation에 불변 대상 스냅샷이 없습니다."
        )

    async def _save_result_item(self, operation_id: int, item: dict[str, Any]) -> None:
        async with self._session_factory() as db:
            async with db.begin():
                operation = await db.get(
                    LiquidationOperation,
                    operation_id,
                    with_for_update=True,
                )
                if operation is None:
                    raise LookupError(f"전량청산 작업을 찾을 수 없습니다: {operation_id}")
                if operation.status in LIQUIDATION_TERMINAL_STATUSES:
                    return
                existing_items = (
                    operation.result_snapshot
                    if isinstance(operation.result_snapshot, list)
                    else []
                )
                items_by_market = {
                    str(existing.get("market")): dict(existing)
                    for existing in existing_items
                    if isinstance(existing, dict) and existing.get("market")
                }
                items_by_market[str(item["market"])] = item
                operation.result_snapshot = [
                    items_by_market[key] for key in sorted(items_by_market)
                ]
                operation.status = "IN_PROGRESS"

    @staticmethod
    def _build_error_summary(items: list[dict[str, Any]]) -> str | None:
        errors = [
            f"{item.get('market')}: {item.get('error_code')}"
            for item in items
            if item.get("error_code")
        ]
        return "; ".join(errors)[:2000] if errors else None


# P0-002의 제어 수명주기를 그대로 상속하고 활성 REST 경로만 P0-004 상태기계로 교체합니다.
_LegacyLiquidationCoordinator = LiquidationCoordinator
from app.services.trading.liquidation_v2 import (  # noqa: E402
    LiquidationV2CoordinatorMixin,
)


class LiquidationCoordinator(  # type: ignore[no-redef]
    LiquidationV2CoordinatorMixin,
    _LegacyLiquidationCoordinator,
):
    pass
