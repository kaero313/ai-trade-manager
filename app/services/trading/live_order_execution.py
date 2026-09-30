from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.live_order_control_repository import (
    EMERGENCY_AUTHORIZATION_REVOKED,
    LIVE_ORDER_MODE_ARMED,
    LIVE_ORDER_MODE_BLOCK_ALL,
    LIVE_ORDER_MODE_EXIT_ONLY,
    LiveOrderControlRepository,
    LiveOrderSubmissionGateSnapshot,
)
from app.db.order_intent_repository import (
    CreateOrGetIntentResult,
    NewOrderIntent,
    OrderIntentPayloadMismatchError,
    OrderIntentRecord,
    OrderIntentRepository,
    reconciliation_backoff,
)
from app.services.brokers.base import BaseBrokerClient
from app.services.brokers.upbit import UpbitAPIError
from app.services.slack_bot import slack_bot
from app.services.trading.live_order_control import (
    AuthFailureBlockCommand,
    LiveOrderControlService,
)
from app.services.trading.live_order_submission_barrier import (
    LiveOrderSubmissionBarrierError,
    LiveOrderSubmissionBarrierProtocol,
)

logger = logging.getLogger(__name__)

BROKER_NAME = "UPBIT"
ACCOUNT_SCOPE = "primary"
TERMINAL_EXCHANGE_STATES = {"done", "cancel"}
KNOWN_EXCHANGE_STATES = {"wait", "watch", "done", "cancel"}
KNOWN_REJECT_ERROR_NAMES = {
    "create_ask_error",
    "create_bid_error",
    "insufficient_funds_ask",
    "insufficient_funds_bid",
    "under_min_total_ask",
    "under_min_total_bid",
    "validation_error",
    "invalid_parameter",
    "invaild_parameter",
    "invalid_query_payload",
    "jwt_verification",
    "expired_access_key",
    "nonce_used",
    "no_authorization_ip",
    "no_authorization_token",
    "out_of_scope",
}
DUPLICATE_IDENTIFIER_ERROR_NAMES = {
    "duplicated_identifier",
    "identifier_already_in_use",
}
AUTHORIZATION_ERROR_NAMES = {
    "jwt_verification",
    "expired_access_key",
    "nonce_used",
    "no_authorization_ip",
    "no_authorization_token",
    "out_of_scope",
}
RECONCILIATION_DELAYS_SECONDS = (0.0, 0.5, 1.5)
RECONCILIATION_LEASE = timedelta(seconds=90)
SUBMISSION_RECOVERY_GRACE = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class LiveOrderRequest:
    source_type: str
    source_ref: str
    market: str
    side: str
    ord_type: str
    price: Decimal | None = None
    volume: Decimal | None = None
    ai_analysis_log_id: int | None = None
    liquidation_operation_id: int | None = None
    reason: str | None = None
    execution_policy: str = "GENERAL"

    def __post_init__(self) -> None:
        source_type = str(self.source_type or "").strip().upper()
        source_ref = str(self.source_ref or "").strip()
        market = str(self.market or "").strip().upper()
        side = str(self.side or "").strip().lower()
        ord_type = str(self.ord_type or "").strip().lower()
        execution_policy = str(self.execution_policy or "").strip().upper()
        reason = str(self.reason).strip() if self.reason is not None else None

        if not source_type or not source_ref or not market:
            raise ValueError("source_type, source_ref, market은 필수입니다.")
        if len(source_ref) > 128:
            raise ValueError("source_ref는 128자를 초과할 수 없습니다.")
        if side not in {"bid", "ask"}:
            raise ValueError("side는 bid 또는 ask여야 합니다.")
        if ord_type not in {"price", "market", "limit"}:
            raise ValueError("ord_type은 price, market, limit 중 하나여야 합니다.")
        if execution_policy not in {"GENERAL", "EMERGENCY_EXIT"}:
            raise ValueError("지원하지 않는 execution_policy입니다.")
        if execution_policy == "EMERGENCY_EXIT":
            if (
                source_type != "EMERGENCY_LIQUIDATION"
                or self.liquidation_operation_id is None
                or self.liquidation_operation_id < 1
            ):
                raise ValueError(
                    "비상청산 주문에는 양수 liquidation_operation_id와 전용 출처가 필요합니다."
                )
            expected_source_ref = (
                f"liquidation:{self.liquidation_operation_id}:{market}"
            )
            if source_ref != expected_source_ref:
                raise ValueError(
                    "비상청산 source_ref는 operation ID와 market에서 정규화되어야 합니다."
                )
        self._validate_decimal("price", self.price)
        self._validate_decimal("volume", self.volume)
        if ord_type == "price" and not (
            side == "bid" and self.price is not None and self.volume is None
        ):
            raise ValueError("시장가 매수는 bid/price와 price만 사용해야 합니다.")
        if ord_type == "market" and not (
            side == "ask" and self.volume is not None and self.price is None
        ):
            raise ValueError("시장가 매도는 ask/market과 volume만 사용해야 합니다.")
        if ord_type == "limit" and (self.price is None or self.volume is None):
            raise ValueError("지정가 주문에는 price와 volume이 모두 필요합니다.")

        object.__setattr__(self, "source_type", source_type)
        object.__setattr__(self, "source_ref", source_ref)
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "ord_type", ord_type)
        object.__setattr__(self, "execution_policy", execution_policy)
        object.__setattr__(self, "reason", reason or None)

    @staticmethod
    def _validate_decimal(field_name: str, value: Decimal | None) -> None:
        if value is None:
            return
        if not isinstance(value, Decimal):
            raise TypeError(f"{field_name}는 Decimal이어야 합니다.")
        if not value.is_finite() or value <= 0:
            raise ValueError(f"{field_name}는 0보다 큰 유한값이어야 합니다.")


@dataclass(frozen=True, slots=True)
class LiveOrderResult:
    intent_id: int | None
    identifier: str | None
    submission_status: str
    exchange_uuid: str | None
    exchange_state: str | None
    projection_status: str
    order_history_id: int | None
    error_code: str | None
    error_message: str | None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class _OrderSnapshot:
    exchange_uuid: str | None
    identifier: str | None
    market: str | None
    side: str | None
    ord_type: str | None
    requested_price: Decimal | None
    requested_volume: Decimal | None
    exchange_state: str | None
    executed_volume: Decimal | None
    executed_funds: Decimal | None
    average_fill_price: Decimal | None
    remaining_volume: Decimal | None
    paid_fee: Decimal | None


@dataclass(frozen=True, slots=True)
class _SubmissionAuthorization:
    allowed: bool
    error_code: str | None
    error_message: str | None
    control_generation: int | None = None
    control_mode: str | None = None
    control_event_id: int | None = None
    abandon_prepared: bool = False


@dataclass(frozen=True, slots=True)
class _BrokerPostOutcome:
    payload: object | None = None
    error: Exception | None = None


def _canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = format(value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _sha256_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _deterministic_uuid4(seed: str) -> UUID:
    raw = bytearray(hashlib.sha256(seed.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(raw))


def build_intent_key(request: LiveOrderRequest) -> str:
    source_ref = request.source_ref
    if request.execution_policy == "EMERGENCY_EXIT":
        source_ref = f"liquidation:{request.liquidation_operation_id}:{request.market}"
    return _sha256_payload(
        {
            "account_scope": ACCOUNT_SCOPE,
            "broker": BROKER_NAME,
            "market": request.market,
            "ord_type": request.ord_type,
            "side": request.side,
            "source_ref": source_ref,
            "source_type": request.source_type,
            "version": 1,
        }
    )


def build_request_fingerprint(request: LiveOrderRequest) -> str:
    return _sha256_payload(
        {
            "ai_analysis_log_id": request.ai_analysis_log_id,
            "execution_policy": request.execution_policy,
            "liquidation_operation_id": request.liquidation_operation_id,
            "market": request.market,
            "ord_type": request.ord_type,
            "price": _canonical_decimal(request.price),
            "reason": request.reason,
            "side": request.side,
            "source_ref": request.source_ref,
            "source_type": request.source_type,
            "version": 1,
            "volume": _canonical_decimal(request.volume),
        }
    )


class LiveOrderExecutionService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        broker: BaseBrokerClient,
        submission_barrier: LiveOrderSubmissionBarrierProtocol,
    ) -> None:
        self._session_factory = session_factory
        self._broker = broker
        self._submission_barrier = submission_barrier
        self._repository = OrderIntentRepository()
        self._control_repository = LiveOrderControlRepository()
        self._control_service = LiveOrderControlService(barrier=submission_barrier)
        self._sleep = asyncio.sleep

    async def execute(self, request: LiveOrderRequest) -> LiveOrderResult:
        intent_key = build_intent_key(request)
        request_fingerprint = build_request_fingerprint(request)

        async with self._session_factory() as db:
            existing = await self._repository.find_intent_by_key(db, intent_key)
            await db.commit()
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                await self._critical_alert(
                    f"주문 의도 payload 충돌: intent_id={existing.id}"
                )
                return self._result(
                    existing,
                    status_override="UNKNOWN",
                    error_code="INTENT_PAYLOAD_MISMATCH",
                    error_message="동일 주문 의도에 서로 다른 요청이 전달됐습니다.",
                )
            return self._with_replayed(await self._resume_existing(existing), True)

        prepared = await self._prepare_new_intent(
            request=request,
            intent_key=intent_key,
            request_fingerprint=request_fingerprint,
        )
        if isinstance(prepared, LiveOrderResult):
            return prepared
        created = prepared

        if created.blocking_intent:
            return self._result(
                created.record,
                error_code="BLOCKING_INTENT",
                error_message="동일 계정 또는 마켓의 선행 주문 의도가 처리 중입니다.",
                replayed=True,
            )
        return self._with_replayed(
            await self._resume_existing(created.record),
            not created.created,
        )

    async def _prepare_new_intent(
        self,
        *,
        request: LiveOrderRequest,
        intent_key: str,
        request_fingerprint: str,
    ) -> CreateOrGetIntentResult | LiveOrderResult:
        created: CreateOrGetIntentResult | None = None
        denial: LiveOrderResult | None = None
        try:
            async with self._submission_barrier.shared() as lease:
                pending_created: CreateOrGetIntentResult | None = None
                async with lease.transaction() as db:
                    gate = await self._control_repository.get_submission_gate_snapshot(db)
                    authorization = self._evaluate_submission_authorization(
                        gate=gate,
                        source_type=request.source_type,
                        execution_policy=request.execution_policy,
                        market=request.market,
                        side=request.side,
                        ord_type=request.ord_type,
                        volume=request.volume,
                        liquidation_operation_id=request.liquidation_operation_id,
                    )
                    if not authorization.allowed:
                        denial = LiveOrderResult(
                            intent_id=None,
                            identifier=None,
                            submission_status="REJECTED",
                            exchange_uuid=None,
                            exchange_state=None,
                            projection_status="SKIPPED",
                            order_history_id=None,
                            error_code=authorization.error_code,
                            error_message=authorization.error_message,
                            replayed=False,
                        )
                    else:
                        if (
                            authorization.control_generation is None
                            or authorization.control_mode is None
                            or authorization.control_event_id is None
                        ):
                            raise RuntimeError(
                                "허용된 주문 준비 게이트의 control 감사값이 없습니다."
                            )
                        draft = NewOrderIntent(
                            intent_key=intent_key,
                            identifier=uuid4().hex,
                            request_fingerprint=request_fingerprint,
                            source_type=request.source_type,
                            source_ref=request.source_ref,
                            market=request.market,
                            side=request.side,
                            ord_type=request.ord_type,
                            requested_price=request.price,
                            requested_volume=request.volume,
                            execution_policy=request.execution_policy,
                            ai_analysis_log_id=request.ai_analysis_log_id,
                            liquidation_operation_id=request.liquidation_operation_id,
                            order_reason=request.reason,
                            prepared_control_generation=(
                                authorization.control_generation
                            ),
                            prepared_control_mode=authorization.control_mode,
                        )
                        pending_created = await self._repository.create_or_get_intent(
                            db,
                            draft,
                        )
                created = pending_created
        except OrderIntentPayloadMismatchError as exc:
            await self._critical_alert(
                f"주문 의도 INSERT payload 충돌: intent_id={exc.record.id}"
            )
            return self._result(
                exc.record,
                status_override="UNKNOWN",
                error_code="INTENT_PAYLOAD_MISMATCH",
                error_message=str(exc),
            )
        except LiveOrderSubmissionBarrierError as exc:
            await self._critical_alert(
                "주문 준비 배리어 오류: "
                f"phase={getattr(exc, 'phase', 'acquire')} error={type(exc).__name__}"
            )
            if denial is not None:
                return denial
            persisted = await self._find_intent_after_preparation_failure(intent_key)
            if persisted is not None:
                return self._result(
                    persisted,
                    error_code=getattr(
                        exc,
                        "error_code",
                        "ORDER_GATE_STATE_UNAVAILABLE",
                    ),
                    error_message=(
                        "주문 준비는 저장되었지만 제출 배리어 상태를 확인할 수 없어 POST하지 않았습니다."
                    ),
                )
            return LiveOrderResult(
                intent_id=None,
                identifier=None,
                submission_status="REJECTED",
                exchange_uuid=None,
                exchange_state=None,
                projection_status="SKIPPED",
                order_history_id=None,
                error_code=getattr(exc, "error_code", "ORDER_GATE_STATE_UNAVAILABLE"),
                error_message="주문 준비 경계를 확인할 수 없어 POST하지 않았습니다.",
                replayed=False,
            )
        except Exception as exc:
            await self._critical_alert(
                f"주문 준비 트랜잭션 실패: error={type(exc).__name__}"
            )
            persisted = await self._find_intent_after_preparation_failure(intent_key)
            if persisted is not None:
                return self._result(
                    persisted,
                    error_code="ORDER_GATE_STATE_UNAVAILABLE",
                    error_message=(
                        "주문 준비 상태 확인에 실패하여 저장된 intent를 제출하지 않았습니다."
                    ),
                )
            return LiveOrderResult(
                intent_id=None,
                identifier=None,
                submission_status="REJECTED",
                exchange_uuid=None,
                exchange_state=None,
                projection_status="SKIPPED",
                order_history_id=None,
                error_code="ORDER_GATE_STATE_UNAVAILABLE",
                error_message="주문 준비 상태를 저장할 수 없어 POST하지 않았습니다.",
                replayed=False,
            )

        if denial is not None:
            return denial
        if created is None:
            await self._critical_alert("주문 준비 트랜잭션이 결과 없이 종료되었습니다.")
            return LiveOrderResult(
                intent_id=None,
                identifier=None,
                submission_status="REJECTED",
                exchange_uuid=None,
                exchange_state=None,
                projection_status="SKIPPED",
                order_history_id=None,
                error_code="ORDER_GATE_STATE_UNAVAILABLE",
                error_message="주문 준비 결과를 확인할 수 없어 POST하지 않았습니다.",
                replayed=False,
            )
        return created

    async def _find_intent_after_preparation_failure(
        self,
        intent_key: str,
    ) -> OrderIntentRecord | None:
        try:
            async with self._session_factory() as db:
                record = await self._repository.find_intent_by_key(db, intent_key)
                await db.commit()
                return record
        except Exception as exc:
            await self._critical_alert(
                f"주문 준비 실패 후 intent 조회 실패: error={type(exc).__name__}"
            )
            return None

    async def reconcile_intent(self, intent_id: int) -> LiveOrderResult:
        async with self._session_factory() as db:
            current = await self._repository.get_intent(db, intent_id)
            await db.commit()
        if current is None:
            return LiveOrderResult(
                intent_id=intent_id,
                identifier=None,
                submission_status="UNKNOWN",
                exchange_uuid=None,
                exchange_state=None,
                projection_status="ERROR",
                order_history_id=None,
                error_code="INTENT_NOT_FOUND",
                error_message="주문 의도를 찾을 수 없습니다.",
                replayed=True,
            )
        if current.submission_status == "ACCEPTED" and current.exchange_state in (
            TERMINAL_EXCHANGE_STATES
        ):
            if current.projection_status == "PENDING":
                return await self._project_terminal(current)
            if current.projection_status in {"APPLIED", "SKIPPED"}:
                return self._result(current)
        if current.submission_status not in {"SUBMITTING", "UNKNOWN", "ACCEPTED"}:
            return self._result(current)

        now = datetime.now(UTC)
        if current.submission_status == "SUBMITTING" and current.submitted_at is not None:
            submitted_at = current.submitted_at
            if submitted_at.tzinfo is None:
                submitted_at = submitted_at.replace(tzinfo=UTC)
            if submitted_at > now - SUBMISSION_RECOVERY_GRACE:
                return self._result(current)
        async with self._session_factory() as db:
            claimed = await self._repository.claim_reconciliation(
                db,
                intent_id,
                now=now,
                lease_for=RECONCILIATION_LEASE,
            )
            await db.commit()
        if claimed is None:
            async with self._session_factory() as db:
                latest = await self._repository.get_intent(db, intent_id)
                await db.commit()
            return self._result(latest or current)
        return await self._reconcile_claimed(claimed)

    async def reconcile_due(self, limit: int = 20) -> list[LiveOrderResult]:
        now = datetime.now(UTC)
        async with self._session_factory() as db:
            claimed = await self._repository.claim_due_reconciliation(
                db,
                now=now,
                lease_for=RECONCILIATION_LEASE,
                submitting_stale_after=SUBMISSION_RECOVERY_GRACE,
                limit=limit,
            )
            await db.commit()
        results: list[LiveOrderResult] = []
        for record in claimed:
            if (
                record.submission_status == "ACCEPTED"
                and record.exchange_state in TERMINAL_EXCHANGE_STATES
                and record.projection_status == "PENDING"
            ):
                results.append(await self._project_terminal(record))
            else:
                results.append(await self._reconcile_claimed(record))
        return results

    async def _resume_existing(self, record: OrderIntentRecord) -> LiveOrderResult:
        if record.submission_status == "PREPARED":
            return await self._submit_prepared_once(record)
        if record.submission_status in {"SUBMITTING", "UNKNOWN"}:
            return await self.reconcile_intent(record.id)
        if record.submission_status == "ACCEPTED":
            if record.exchange_state in TERMINAL_EXCHANGE_STATES:
                return await self._project_terminal(record)
            return await self.reconcile_intent(record.id)
        return self._result(record)

    async def _submit_prepared_once(self, record: OrderIntentRecord) -> LiveOrderResult:
        claimed: OrderIntentRecord | None = None
        outcome: _BrokerPostOutcome | None = None
        denied_record: OrderIntentRecord | None = None
        denied_code: str | None = None
        denied_message: str | None = None

        try:
            async with self._submission_barrier.shared() as lease:
                pending_claim: OrderIntentRecord | None = None
                pending_denied: OrderIntentRecord | None = None
                async with lease.transaction() as db:
                    gate = await self._control_repository.get_submission_gate_snapshot(db)
                    authorization = self._evaluate_submission_authorization(
                        gate=gate,
                        source_type=record.source_type,
                        execution_policy=record.execution_policy,
                        market=record.market,
                        side=record.side,
                        ord_type=record.ord_type,
                        volume=record.requested_volume,
                        liquidation_operation_id=record.liquidation_operation_id,
                    )
                    if authorization.allowed and (
                        record.prepared_control_generation
                        != authorization.control_generation
                        or record.prepared_control_mode != authorization.control_mode
                    ):
                        authorization = _SubmissionAuthorization(
                            allowed=False,
                            error_code="ORDER_GATE_GENERATION_CONFLICT",
                            error_message=(
                                "주문 준비 시점과 최종 승인 시점의 실주문 제어 세대가 다릅니다."
                            ),
                            abandon_prepared=True,
                        )

                    if not authorization.allowed:
                        denied_code = authorization.error_code
                        denied_message = authorization.error_message
                        if authorization.abandon_prepared:
                            pending_denied = await self._repository.abandon_prepared(
                                db,
                                record.id,
                                expected_version=record.version,
                                error_code=denied_code or "LIVE_ORDER_GATE_BLOCKED",
                                error_message=denied_message
                                or "실주문 제어 정책이 신규 주문 제출을 차단했습니다.",
                                now=datetime.now(UTC),
                            )
                    else:
                        if (
                            authorization.control_generation is None
                            or authorization.control_mode is None
                            or authorization.control_event_id is None
                        ):
                            raise RuntimeError("허용된 주문 게이트의 control 감사값이 없습니다.")
                        pending_claim = await self._repository.claim_submission(
                            db,
                            record.id,
                            expected_version=record.version,
                            now=datetime.now(UTC),
                            control_generation=authorization.control_generation,
                            control_mode=authorization.control_mode,
                            control_event_id=authorization.control_event_id,
                        )

                denied_record = pending_denied
                claimed = pending_claim
                if claimed is not None:
                    await lease.assert_no_transaction()
                    try:
                        payload = await self._broker.create_order(
                            market=claimed.market,
                            side=claimed.side,
                            ord_type=claimed.ord_type,
                            price=_canonical_decimal(claimed.requested_price),
                            volume=_canonical_decimal(claimed.requested_volume),
                            identifier=claimed.identifier,
                        )
                    except Exception as exc:
                        outcome = _BrokerPostOutcome(error=exc)
                    else:
                        outcome = _BrokerPostOutcome(payload=payload)
        except LiveOrderSubmissionBarrierError as exc:
            await self._critical_alert(
                "실주문 제출 배리어 오류: "
                f"intent_id={record.id} phase={getattr(exc, 'phase', 'acquire')} "
                f"error={type(exc).__name__}"
            )
            if claimed is None:
                return self._result(
                    record,
                    error_code=getattr(exc, "error_code", "ORDER_GATE_STATE_UNAVAILABLE"),
                    error_message="실주문 제출 경계를 확인할 수 없어 주문을 전송하지 않았습니다.",
                )
            if outcome is None:
                return await self._unknown_then_reconcile(
                    claimed,
                    error_code="ORDER_GATE_STATE_UNAVAILABLE",
                    error_message=(
                        "제출 claim 이후 배리어 상태를 확인할 수 없어 identifier로만 복구합니다."
                    ),
                )
            # release 실패여도 POST 결과는 이미 확정되었으므로 재POST 없이 그대로 저장한다.
        except Exception as exc:
            await self._critical_alert(
                f"실주문 최종 게이트 처리 실패: intent_id={record.id} error={type(exc).__name__}"
            )
            if claimed is None:
                return self._result(
                    record,
                    error_code="ORDER_GATE_STATE_UNAVAILABLE",
                    error_message="실주문 제어 상태를 확인할 수 없어 주문을 전송하지 않았습니다.",
                )
            if outcome is None:
                return await self._unknown_then_reconcile(
                    claimed,
                    error_code="ORDER_GATE_STATE_UNAVAILABLE",
                    error_message=(
                        "제출 claim 이후 내부 상태를 확인할 수 없어 identifier로만 복구합니다."
                    ),
                )
            raise

        if denied_code is not None:
            if denied_record is None:
                async with self._session_factory() as db:
                    latest = await self._repository.get_intent(db, record.id)
                    await db.commit()
                denied_record = latest or record
            return self._result(
                denied_record,
                error_code=denied_code,
                error_message=denied_message,
            )
        if claimed is None:
            async with self._session_factory() as db:
                latest = await self._repository.get_intent(db, record.id)
                await db.commit()
            return self._result(latest or record)
        if outcome is None:
            return await self._unknown_then_reconcile(
                claimed,
                error_code="ORDER_GATE_STATE_UNAVAILABLE",
                error_message="제출 결과가 없어 identifier로만 복구합니다.",
            )
        return await self._handle_post_outcome(claimed, outcome)

    async def _handle_post_outcome(
        self,
        record: OrderIntentRecord,
        outcome: _BrokerPostOutcome,
    ) -> LiveOrderResult:
        if outcome.error is not None:
            exc = outcome.error
            if isinstance(exc, UpbitAPIError):
                error_name = str(exc.error_name or "").strip().lower()
                if error_name in DUPLICATE_IDENTIFIER_ERROR_NAMES:
                    return await self._unknown_then_reconcile(
                        record,
                        error_code="DUPLICATE_IDENTIFIER",
                        error_message=self._safe_error_message(exc),
                    )
                if exc.status_code in {401, 403, 418, 429} or (
                    exc.status_code == 400 and error_name in KNOWN_REJECT_ERROR_NAMES
                ):
                    return await self._reject(
                        record,
                        error_code=error_name.upper() or f"UPBIT_HTTP_{exc.status_code}",
                        error_message=self._safe_error_message(exc),
                        disable_gate=(
                            exc.status_code in {401, 403, 418}
                            or error_name in AUTHORIZATION_ERROR_NAMES
                        ),
                    )
                return await self._unknown_then_reconcile(
                    record,
                    error_code=error_name.upper() or f"UPBIT_HTTP_{exc.status_code}",
                    error_message=self._safe_error_message(exc),
                )
            return await self._unknown_then_reconcile(
                record,
                error_code=exc.__class__.__name__.upper(),
                error_message=self._safe_error_message(exc),
            )

        payload = outcome.payload
        if not isinstance(payload, dict):
            return await self._unknown_then_reconcile(
                record,
                error_code="INVALID_CREATE_RESPONSE",
                error_message="주문 생성 응답이 객체가 아닙니다.",
            )
        snapshot = self._snapshot(payload)
        mismatch = self._payload_mismatch(record, snapshot, require_identifier=False)
        if snapshot.exchange_uuid is None or mismatch is not None:
            return await self._unknown_then_reconcile(
                record,
                error_code="CREATE_RESPONSE_MISMATCH" if mismatch else "CREATE_UUID_MISSING",
                error_message=mismatch or "주문 생성 응답에 UUID가 없습니다.",
            )
        return await self._accept(record, snapshot, follow_up=True)

    async def _reconcile_claimed(self, record: OrderIntentRecord) -> LiveOrderResult:
        last_error_code = "ORDER_NOT_FOUND"
        last_error_message = "identifier로 주문을 확인하지 못했습니다."
        not_found_count = 0
        for delay in RECONCILIATION_DELAYS_SECONDS:
            if delay > 0:
                await self._sleep(delay)
            try:
                payload = await self._broker.get_order(identifier=record.identifier)
            except UpbitAPIError as exc:
                if exc.status_code == 404:
                    not_found_count += 1
                    last_error_code = "ORDER_NOT_FOUND"
                    last_error_message = "identifier로 주문을 확인하지 못했습니다."
                    continue
                last_error_code = str(exc.error_name or f"UPBIT_HTTP_{exc.status_code}").upper()
                last_error_message = self._safe_error_message(exc)
                error_name = str(exc.error_name or "").strip().lower()
                if (
                    exc.status_code in {401, 403, 418}
                    or error_name in AUTHORIZATION_ERROR_NAMES
                ):
                    await self._disable_submission_gate(record)
                if exc.status_code in {400, 401, 403, 418}:
                    break
                continue
            except (httpx.RequestError, ValueError) as exc:
                last_error_code = exc.__class__.__name__.upper()
                last_error_message = self._safe_error_message(exc)
                continue
            except Exception as exc:
                last_error_code = exc.__class__.__name__.upper()
                last_error_message = self._safe_error_message(exc)
                continue

            if not isinstance(payload, dict):
                last_error_code = "INVALID_LOOKUP_RESPONSE"
                last_error_message = "주문 조회 응답이 객체가 아닙니다."
                continue
            snapshot = self._snapshot(payload)
            mismatch = self._payload_mismatch(record, snapshot, require_identifier=True)
            if mismatch is not None or snapshot.exchange_uuid is None:
                return await self._mark_reconciliation_conflict(
                    record,
                    mismatch or "주문 조회 응답에 UUID가 없습니다.",
                )
            return await self._accept(record, snapshot)

        now = datetime.now(UTC)
        async with self._session_factory() as db:
            unknown = await self._repository.mark_unknown(
                db,
                record.id,
                error_code=last_error_code,
                error_message=last_error_message,
                now=now,
                next_reconcile_at=now
                + reconciliation_backoff(record.reconcile_attempt_count),
                not_found_count=not_found_count,
                expected_version=record.version,
            )
            await db.commit()
        return self._result(unknown)

    async def _unknown_then_reconcile(
        self,
        record: OrderIntentRecord,
        *,
        error_code: str,
        error_message: str | None,
    ) -> LiveOrderResult:
        now = datetime.now(UTC)
        async with self._session_factory() as db:
            await self._repository.mark_unknown(
                db,
                record.id,
                error_code=error_code,
                error_message=error_message,
                now=now,
                next_reconcile_at=now,
                expected_version=record.version,
            )
            await db.commit()
        return await self.reconcile_intent(record.id)

    async def _reject(
        self,
        record: OrderIntentRecord,
        *,
        error_code: str,
        error_message: str | None,
        disable_gate: bool = False,
    ) -> LiveOrderResult:
        if disable_gate:
            await self._disable_submission_gate(record)
        async with self._session_factory() as db:
            rejected = await self._repository.mark_rejected(
                db,
                record.id,
                error_code=error_code,
                error_message=error_message,
                now=datetime.now(UTC),
                expected_version=record.version,
            )
            await db.commit()
        return self._result(rejected)

    async def _accept(
        self,
        record: OrderIntentRecord,
        snapshot: _OrderSnapshot,
        *,
        follow_up: bool = False,
    ) -> LiveOrderResult:
        if snapshot.exchange_uuid is None:
            return await self._unknown_then_reconcile(
                record,
                error_code="EXCHANGE_UUID_MISSING",
                error_message="거래소 UUID가 없습니다.",
            )
        async with self._session_factory() as db:
            accepted = await self._repository.mark_accepted(
                db,
                record.id,
                exchange_uuid=snapshot.exchange_uuid,
                exchange_state=snapshot.exchange_state,
                executed_volume=snapshot.executed_volume,
                executed_funds=snapshot.executed_funds,
                average_fill_price=snapshot.average_fill_price,
                remaining_volume=snapshot.remaining_volume,
                paid_fee=snapshot.paid_fee,
                now=datetime.now(UTC),
                reconcile_after=reconciliation_backoff(record.reconcile_attempt_count),
                expected_version=record.version,
            )
            await db.commit()
        if accepted.exchange_state in TERMINAL_EXCHANGE_STATES:
            return await self._project_terminal(accepted)
        if follow_up:
            return await self._follow_up_accepted_once(accepted)
        return self._result(accepted)

    async def _follow_up_accepted_once(
        self,
        record: OrderIntentRecord,
    ) -> LiveOrderResult:
        try:
            payload = await self._broker.get_order(identifier=record.identifier)
        except UpbitAPIError as exc:
            error_name = str(exc.error_name or "").strip().lower()
            if (
                exc.status_code in {401, 403, 418}
                or error_name in AUTHORIZATION_ERROR_NAMES
            ):
                await self._disable_submission_gate(record)
            logger.warning(
                "접수 직후 주문 조회 실패: intent_id=%s error=%s",
                record.id,
                exc,
            )
            return await self._record_accepted_lookup_failure(
                record,
                error_code=str(exc.error_name or f"UPBIT_HTTP_{exc.status_code}").upper(),
                error_message=self._safe_error_message(exc),
            )
        except Exception as exc:
            logger.warning(
                "접수 직후 주문 조회 실패: intent_id=%s error=%s",
                record.id,
                exc,
            )
            return await self._record_accepted_lookup_failure(
                record,
                error_code=exc.__class__.__name__.upper(),
                error_message=self._safe_error_message(exc),
            )
        if not isinstance(payload, dict):
            return await self._record_accepted_lookup_failure(
                record,
                error_code="INVALID_LOOKUP_RESPONSE",
                error_message="주문 조회 응답이 객체가 아닙니다.",
            )
        snapshot = self._snapshot(payload)
        mismatch = self._payload_mismatch(record, snapshot, require_identifier=True)
        if mismatch is not None or snapshot.exchange_uuid is None:
            return await self._mark_reconciliation_conflict(
                record,
                mismatch or "주문 조회 응답에 UUID가 없습니다.",
            )
        return await self._accept(record, snapshot)

    async def _record_accepted_lookup_failure(
        self,
        record: OrderIntentRecord,
        *,
        error_code: str,
        error_message: str | None,
    ) -> LiveOrderResult:
        now = datetime.now(UTC)
        async with self._session_factory() as db:
            updated = await self._repository.mark_unknown(
                db,
                record.id,
                error_code=error_code,
                error_message=error_message,
                now=now,
                next_reconcile_at=now
                + reconciliation_backoff(record.reconcile_attempt_count),
                expected_version=record.version,
            )
            await db.commit()
        return self._result(updated)

    async def _project_terminal(self, record: OrderIntentRecord) -> LiveOrderResult:
        try:
            async with self._session_factory() as db:
                projected = await self._repository.project_terminal_fill(
                    db,
                    record.id,
                    now=datetime.now(UTC),
                )
                await db.commit()
            return self._result(projected)
        except Exception as exc:
            logger.exception("주문 체결 원장 반영 실패: intent_id=%s", record.id)
            async with self._session_factory() as db:
                failed = await self._repository.mark_projection_error(
                    db,
                    record.id,
                    error_code="PROJECTION_FAILED",
                    error_message=self._safe_error_message(exc) or "원장 반영 실패",
                    now=datetime.now(UTC),
                    expected_version=record.version,
                )
                await db.commit()
            return self._result(failed)

    async def _mark_reconciliation_conflict(
        self,
        record: OrderIntentRecord,
        message: str,
    ) -> LiveOrderResult:
        await self._critical_alert(
            f"거래소 주문 payload 충돌: intent_id={record.id} message={message}"
        )
        async with self._session_factory() as db:
            conflict = await self._repository.mark_reconciliation_conflict(
                db,
                record.id,
                error_message=message,
                now=datetime.now(UTC),
                expected_version=record.version,
            )
            await db.commit()
        return self._result(conflict)

    @staticmethod
    def _evaluate_submission_authorization(
        *,
        gate: LiveOrderSubmissionGateSnapshot,
        source_type: str,
        execution_policy: str,
        market: str,
        side: str,
        ord_type: str,
        volume: Decimal | None,
        liquidation_operation_id: int | None,
    ) -> _SubmissionAuthorization:
        if not gate.trading_mode_state_available:
            return _SubmissionAuthorization(
                allowed=False,
                error_code="TRADING_MODE_STATE_UNAVAILABLE",
                error_message="거래 모드 제어 원장과 mirror를 확인할 수 없습니다.",
                abandon_prepared=True,
            )
        if not gate.trading_mode_live:
            return _SubmissionAuthorization(
                allowed=False,
                error_code="TRADING_MODE_LIVE_REQUIRED",
                error_message="정상적인 live 거래 모드에서만 Upbit 주문을 제출할 수 있습니다.",
                abandon_prepared=True,
            )
        if not gate.rollout_enabled:
            return _SubmissionAuthorization(
                allowed=False,
                error_code="LIVE_ORDER_V2_DISABLED",
                error_message="실주문 V2 배포 기능 플래그가 비활성화되어 있습니다.",
                abandon_prepared=True,
            )
        if gate.control is None:
            return _SubmissionAuthorization(
                allowed=False,
                error_code="ORDER_GATE_STATE_UNAVAILABLE",
                error_message="실주문 제어 원장을 확인할 수 없습니다.",
            )

        control = gate.control
        if execution_policy == "GENERAL":
            if not gate.bot_active:
                return _SubmissionAuthorization(
                    allowed=False,
                    error_code="BOT_INACTIVE",
                    error_message="봇이 정지되어 일반 실주문을 제출할 수 없습니다.",
                    abandon_prepared=True,
                )
            if control.mode != LIVE_ORDER_MODE_ARMED:
                return _SubmissionAuthorization(
                    allowed=False,
                    error_code="LIVE_ORDER_GATE_BLOCKED",
                    error_message="전역 실주문 제어가 일반 신규 주문을 차단하고 있습니다.",
                    abandon_prepared=True,
                )
            if not gate.general_submission_allowed:
                return _SubmissionAuthorization(
                    allowed=False,
                    error_code="ORDER_GATE_STATE_UNAVAILABLE",
                    error_message="현재 ARMED 상태의 승인 감사 이벤트를 확인할 수 없습니다.",
                )
            return _SubmissionAuthorization(
                allowed=True,
                error_code=None,
                error_message=None,
                control_generation=control.generation,
                control_mode=control.mode,
                control_event_id=gate.general_authorization_event_id,
            )

        if (
            execution_policy != "EMERGENCY_EXIT"
            or source_type != "EMERGENCY_LIQUIDATION"
            or side != "ask"
            or ord_type != "market"
            or liquidation_operation_id is None
            or volume is None
        ):
            return _SubmissionAuthorization(
                allowed=False,
                error_code="EMERGENCY_AUTH_REQUIRED",
                error_message="비상청산 주문 형식 또는 출처가 승인 범위와 일치하지 않습니다.",
                abandon_prepared=True,
            )
        if control.mode == LIVE_ORDER_MODE_BLOCK_ALL:
            return _SubmissionAuthorization(
                allowed=False,
                error_code="LIVE_ORDER_GATE_BLOCKED",
                error_message="전역 실주문 제어가 비상청산을 포함한 신규 주문을 차단하고 있습니다.",
                abandon_prepared=True,
            )
        if control.mode != LIVE_ORDER_MODE_EXIT_ONLY:
            return _SubmissionAuthorization(
                allowed=False,
                error_code="EMERGENCY_AUTH_REQUIRED",
                error_message="해당 비상청산 operation에 EXIT_ONLY 권한이 연결되지 않았습니다.",
                abandon_prepared=True,
            )
        authorization = gate.emergency_authorization
        if (
            authorization is not None
            and authorization.authorization_status == EMERGENCY_AUTHORIZATION_REVOKED
        ):
            return _SubmissionAuthorization(
                allowed=False,
                error_code="EMERGENCY_AUTH_REVOKED",
                error_message="비상청산 operation 권한이 폐기되었습니다.",
                abandon_prepared=True,
            )
        if not gate.emergency_submission_allowed(liquidation_operation_id):
            return _SubmissionAuthorization(
                allowed=False,
                error_code="EMERGENCY_AUTH_REQUIRED",
                error_message="비상청산 operation 권한을 검증할 수 없습니다.",
                abandon_prepared=True,
            )
        if authorization is None or not authorization.permits_target(
            market=market,
            volume=volume,
        ):
            return _SubmissionAuthorization(
                allowed=False,
                error_code="EMERGENCY_AUTH_REQUIRED",
                error_message="비상청산 마켓 또는 수량이 불변 대상 스냅샷과 다릅니다.",
                abandon_prepared=True,
            )
        return _SubmissionAuthorization(
            allowed=True,
            error_code=None,
            error_message=None,
            control_generation=control.generation,
            control_mode=control.mode,
            control_event_id=authorization.control_event_id,
        )

    async def _disable_submission_gate(self, record: OrderIntentRecord) -> None:
        trip_task = asyncio.create_task(self._disable_submission_gate_once(record))
        cancellation: asyncio.CancelledError | None = None
        while not trip_task.done():
            try:
                await asyncio.shield(trip_task)
            except asyncio.CancelledError as exc:
                cancellation = cancellation or exc
        trip_task.result()
        if cancellation is not None:
            raise cancellation

    async def _disable_submission_gate_once(self, record: OrderIntentRecord) -> None:
        request_id = await self._auth_failure_request_id(record)
        try:
            await self._control_service.trip_on_auth_failure(
                AuthFailureBlockCommand(
                    request_id=request_id,
                    reason_code="UPBIT_AUTH_FAILURE",
                    reason_text="Upbit 인증·권한 오류로 실주문 기능과 전역 주문 권한을 차단합니다.",
                    actor_ref="live-order-execution",
                    completed_post_intent_id=record.id,
                )
            )
            return
        except Exception as exc:
            await self._critical_alert(
                "Upbit 인증 오류 전역 차단 실패; rollout 비활성화 fallback 실행: "
                f"error={type(exc).__name__}"
            )

        async with self._session_factory() as db:
            await self._repository.disable_live_order_v2(db)
            await db.commit()

    async def _auth_failure_request_id(self, record: OrderIntentRecord) -> UUID:
        target_generation = (
            record.control_generation
            or record.prepared_control_generation
            or 0
        )
        try:
            async with self._session_factory() as db:
                control = await self._control_repository.get_control(db)
                await db.commit()
            if control is not None:
                scope_changes = (
                    control.mode != LIVE_ORDER_MODE_BLOCK_ALL
                    or control.active_liquidation_operation_id is not None
                )
                target_generation = control.generation + int(scope_changes)
        except Exception as exc:
            await self._critical_alert(
                "인증 오류 차단 request ID용 control 조회 실패: "
                f"error={type(exc).__name__}"
            )
        return _deterministic_uuid4(
            f"{BROKER_NAME}:{ACCOUNT_SCOPE}:AUTH_FAILURE:{target_generation}"
        )

    @staticmethod
    async def _critical_alert(message: str) -> None:
        logger.critical(message)
        if not slack_bot.enabled:
            return
        try:
            await asyncio.to_thread(
                slack_bot.send_message,
                f"🚨 [실주문 치명 경보] {message}",
            )
        except Exception:
            logger.exception("실주문 치명 경보 Slack 전송 실패")

    @staticmethod
    def _payload_mismatch(
        record: OrderIntentRecord,
        snapshot: _OrderSnapshot,
        *,
        require_identifier: bool,
    ) -> str | None:
        if (
            record.exchange_uuid is not None
            and snapshot.exchange_uuid is not None
            and snapshot.exchange_uuid != record.exchange_uuid
        ):
            return "거래소 UUID가 기존 주문 의도와 일치하지 않습니다."
        if require_identifier and snapshot.identifier != record.identifier:
            return "identifier가 주문 의도와 일치하지 않습니다."
        if snapshot.identifier is not None and snapshot.identifier != record.identifier:
            return "identifier가 주문 의도와 일치하지 않습니다."
        comparisons = (
            ("market", snapshot.market, record.market),
            ("side", snapshot.side, record.side),
            ("ord_type", snapshot.ord_type, record.ord_type),
            ("price", snapshot.requested_price, record.requested_price),
            ("volume", snapshot.requested_volume, record.requested_volume),
        )
        for field_name, actual, expected in comparisons:
            if actual != expected:
                return f"{field_name} 값이 주문 의도와 일치하지 않습니다."
        if snapshot.exchange_state is not None and snapshot.exchange_state not in (
            KNOWN_EXCHANGE_STATES
        ):
            return "지원하지 않는 거래소 주문 상태입니다."
        return None

    @classmethod
    def _snapshot(cls, payload: dict[str, Any]) -> _OrderSnapshot:
        trades = payload.get("trades")
        trade_volume = Decimal("0")
        trade_funds = Decimal("0")
        if isinstance(trades, list):
            for trade in trades:
                if not isinstance(trade, dict):
                    continue
                volume = cls._decimal(trade.get("volume")) or Decimal("0")
                funds = cls._decimal(trade.get("funds")) or Decimal("0")
                if funds <= 0:
                    price = cls._decimal(trade.get("price")) or Decimal("0")
                    funds = price * volume
                if volume > 0 and funds > 0:
                    trade_volume += volume
                    trade_funds += funds

        executed_volume = cls._decimal(payload.get("executed_volume"))
        executed_funds = cls._decimal(
            payload.get("executed_funds", payload.get("executed_fund"))
        )
        if trade_volume > 0:
            executed_volume = executed_volume or trade_volume
            executed_funds = executed_funds or trade_funds
        average_fill_price = None
        if trade_volume > 0 and trade_funds > 0:
            average_fill_price = trade_funds / trade_volume
        elif executed_volume is not None and executed_volume > 0 and executed_funds is not None:
            average_fill_price = executed_funds / executed_volume

        return _OrderSnapshot(
            exchange_uuid=cls._text(payload.get("uuid")),
            identifier=cls._text(payload.get("identifier")),
            market=cls._upper_text(payload.get("market")),
            side=cls._lower_text(payload.get("side")),
            ord_type=cls._lower_text(payload.get("ord_type")),
            requested_price=cls._decimal(payload.get("price")),
            requested_volume=cls._decimal(payload.get("volume")),
            exchange_state=cls._lower_text(payload.get("state")),
            executed_volume=executed_volume,
            executed_funds=executed_funds,
            average_fill_price=average_fill_price,
            remaining_volume=cls._decimal(payload.get("remaining_volume")),
            paid_fee=cls._decimal(payload.get("paid_fee")),
        )

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value is None or str(value).strip() == "":
            return None
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return parsed if parsed.is_finite() else None

    @staticmethod
    def _text(value: Any) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @classmethod
    def _upper_text(cls, value: Any) -> str | None:
        normalized = cls._text(value)
        return normalized.upper() if normalized is not None else None

    @classmethod
    def _lower_text(cls, value: Any) -> str | None:
        normalized = cls._text(value)
        return normalized.lower() if normalized is not None else None

    @staticmethod
    def _safe_error_message(exc: Exception) -> str | None:
        if isinstance(exc, UpbitAPIError):
            message = str(exc.message or exc.error_name or "").strip()
        else:
            message = str(exc).strip()
        return message[:500] if message else None

    @staticmethod
    def _result(
        record: OrderIntentRecord,
        *,
        status_override: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        replayed: bool = True,
    ) -> LiveOrderResult:
        return LiveOrderResult(
            intent_id=record.id,
            identifier=record.identifier,
            submission_status=status_override or record.submission_status,
            exchange_uuid=record.exchange_uuid,
            exchange_state=record.exchange_state,
            projection_status=record.projection_status,
            order_history_id=record.order_history_id,
            error_code=error_code if error_code is not None else record.last_error_code,
            error_message=(
                error_message if error_message is not None else record.last_error_message
            ),
            replayed=replayed,
        )

    @staticmethod
    def _with_replayed(result: LiveOrderResult, replayed: bool) -> LiveOrderResult:
        return LiveOrderResult(
            intent_id=result.intent_id,
            identifier=result.identifier,
            submission_status=result.submission_status,
            exchange_uuid=result.exchange_uuid,
            exchange_state=result.exchange_state,
            projection_status=result.projection_status,
            order_history_id=result.order_history_id,
            error_code=result.error_code,
            error_message=result.error_message,
            replayed=replayed,
        )
