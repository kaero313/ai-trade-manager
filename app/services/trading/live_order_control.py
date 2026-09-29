"""전역 실주문 제어 상태의 운영 정책과 원자적 전이를 조율한다."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.live_order_control_repository import (
    CONTROL_ACTION_ARMED,
    CONTROL_ACTION_BLOCKED,
    CONTROL_ACTION_LIQUIDATION_AUTHORIZED,
    CONTROL_ACTION_LIQUIDATION_CLOSED,
    CONTROL_ACTION_LIQUIDATION_REVOKED,
    CONTROL_SOURCE_AUTH_FAILURE,
    EMERGENCY_AUTHORIZATION_ACTIVE,
    EMERGENCY_AUTHORIZATION_CLOSED,
    EMERGENCY_AUTHORIZATION_REVOKED,
    LIVE_ORDER_CONTROL_SOURCES,
    LIVE_ORDER_MODE_ARMED,
    LIVE_ORDER_MODE_BLOCK_ALL,
    LIVE_ORDER_MODE_EXIT_ONLY,
    LiveOrderControlEventRecord,
    LiveOrderControlRecord,
    LiveOrderControlRepository,
    LiveOrderControlRequestSupersededError,
    LiveOrderControlTransitionError,
    LiveOrderControlTransitionResult,
    build_control_request_fingerprint,
)
from app.db.trading_mode_repository import TRADING_MODE_LIVE, TradingModeRepository
from app.models.domain import BotConfig, LiquidationOperation
from app.models.schemas import BotConfig as BotConfigSchema
from app.services.trading.live_order_submission_barrier import (
    LiveOrderSubmissionBarrierError,
    LiveOrderSubmissionBarrierProtocol,
)

ARM_CONFIRMATION = "ENABLE_LIVE_ORDERS"
INITIAL_EMERGENCY_REVOCATION_REASON = "FAIL_CLOSED_NOT_AUTHORIZED"
ACTIVE_LIQUIDATION_STATUSES = frozenset({"PREPARING", "IN_PROGRESS"})
TERMINAL_LIQUIDATION_STATUSES = frozenset(
    {"COMPLETED", "PARTIAL", "FAILED", "NO_ASSETS"}
)


class LiveOrderControlServiceError(RuntimeError):
    """API와 메시지 채널에서 안정적으로 매핑할 수 있는 제어 서비스 오류."""

    error_code = "ORDER_GATE_STATE_UNAVAILABLE"

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code


class LiveOrderControlPolicyError(LiveOrderControlServiceError):
    """현재 정책 또는 운영 상태가 요청한 권한 확대를 허용하지 않음."""


class LiveOrderControlStateUnavailableError(LiveOrderControlServiceError):
    """DB 상태를 일관되게 판정하거나 갱신할 수 없음."""


class LiveOrderControlDrainPendingError(LiveOrderControlServiceError):
    """차단은 commit됐지만 SUBMITTING 주문의 POST 종료를 확인하지 못함."""

    error_code = "ORDER_GATE_DRAIN_PENDING"


@dataclass(frozen=True, slots=True)
class ArmLiveOrdersCommand:
    request_id: UUID | str
    expected_generation: int
    expected_version: int
    reason_code: str
    reason_text: str
    source: str
    actor_ref: str | None
    confirmation: str


@dataclass(frozen=True, slots=True)
class BlockLiveOrdersCommand:
    request_id: UUID | str
    reason_code: str
    reason_text: str
    source: str
    actor_ref: str | None


@dataclass(frozen=True, slots=True)
class AuthorizeEmergencyLiquidationCommand:
    request_id: UUID | str
    operation_id: int
    expected_generation: int
    expected_version: int
    reason_code: str
    reason_text: str
    source: str
    actor_ref: str | None


@dataclass(frozen=True, slots=True)
class CloseEmergencyLiquidationCommand:
    request_id: UUID | str
    operation_id: int
    reason_code: str
    reason_text: str
    source: str
    actor_ref: str | None


@dataclass(frozen=True, slots=True)
class AuthFailureBlockCommand:
    request_id: UUID | str
    reason_code: str
    reason_text: str
    actor_ref: str | None = None
    completed_post_intent_id: int | None = None


@dataclass(frozen=True, slots=True)
class PrepareEmergencyLiquidationCommand:
    request_id: UUID | str
    operation_id: int
    reason_code: str
    reason_text: str
    source: str
    actor_ref: str | None


@dataclass(frozen=True, slots=True)
class LiquidationAuthorizationCloseResult:
    control: LiveOrderControlRecord
    transition: LiveOrderControlTransitionResult | None
    operation_id: int
    authorization_status: str
    skipped_due_to_revocation: bool


class LiveOrderControlStateStoreProtocol(Protocol):
    async def get_bot_active(self, db: AsyncSession) -> bool: ...

    async def set_bot_active(self, db: AsyncSession, *, is_active: bool) -> None: ...

    async def get_trading_mode(self, db: AsyncSession) -> str | None: ...

    async def get_liquidation_operation_for_update(
        self,
        db: AsyncSession,
        operation_id: int,
    ) -> LiquidationOperation | None: ...


class SqlAlchemyLiveOrderControlStateStore:
    """제어 서비스가 repository 밖에서 필요로 하는 최소 운영 상태 저장소."""

    async def get_bot_active(self, db: AsyncSession) -> bool:
        result = await db.execute(select(BotConfig.is_active).where(BotConfig.id == 1))
        return result.scalar_one_or_none() is True

    async def set_bot_active(self, db: AsyncSession, *, is_active: bool) -> None:
        statement = (
            postgresql_insert(BotConfig)
            .values(
                id=1,
                config_json=BotConfigSchema().model_dump(),
                is_active=is_active,
            )
            .on_conflict_do_update(
                index_elements=[BotConfig.id],
                set_={"is_active": is_active},
            )
        )
        await db.execute(statement)
        await db.flush()

    async def get_trading_mode(self, db: AsyncSession) -> str | None:
        status = await TradingModeRepository().status(db)
        if not status.state_available or status.control is None:
            return None
        return status.mode

    async def get_liquidation_operation_for_update(
        self,
        db: AsyncSession,
        operation_id: int,
    ) -> LiquidationOperation | None:
        result = await db.execute(
            select(LiquidationOperation)
            .where(LiquidationOperation.id == operation_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()


_ResultT = TypeVar("_ResultT")
_Clock = Callable[[], datetime]


class LiveOrderControlService:
    """실주문 권한 확대·축소를 exclusive 제출 배리어 아래 직렬화한다."""

    def __init__(
        self,
        *,
        barrier: LiveOrderSubmissionBarrierProtocol,
        repository: LiveOrderControlRepository | None = None,
        state_store: LiveOrderControlStateStoreProtocol | None = None,
        clock: _Clock | None = None,
    ) -> None:
        self._barrier = barrier
        self._repository = repository or LiveOrderControlRepository()
        self._state_store = state_store or SqlAlchemyLiveOrderControlStateStore()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def arm(
        self,
        command: ArmLiveOrdersCommand,
    ) -> LiveOrderControlTransitionResult:
        request_id = _require_uuid4(command.request_id)
        reason_code = _require_reason_code(command.reason_code)
        reason_text = _require_operator_reason(command.reason_text)
        source = _require_source(command.source)
        actor_ref = _normalize_actor_ref(command.actor_ref)
        if command.confirmation != ARM_CONFIRMATION:
            raise LiveOrderControlPolicyError(
                f"재무장 확인 문구는 {ARM_CONFIRMATION}여야 합니다.",
                error_code="LIVE_ORDER_GATE_BLOCKED",
            )
        if command.expected_generation < 1 or command.expected_version < 1:
            raise LiveOrderControlPolicyError(
                "재무장에는 양수 expected_generation과 expected_version이 필요합니다.",
                error_code="ORDER_GATE_GENERATION_CONFLICT",
            )

        fingerprint = build_control_request_fingerprint(
            action=CONTROL_ACTION_ARMED,
            expected_generation=command.expected_generation,
            expected_version=command.expected_version,
            target_mode=LIVE_ORDER_MODE_ARMED,
            active_liquidation_operation_id=None,
            reason_code=reason_code,
            reason_text=reason_text,
            source=source,
            actor_ref=actor_ref,
            confirmation=command.confirmation,
        )

        async def operation(db: AsyncSession) -> LiveOrderControlTransitionResult:
            existing_event = await self._repository.get_event(db, request_id)
            if existing_event is None:
                await self._assert_arm_preconditions(db)
            return await self._repository.transition_control(
                db,
                expected_generation=command.expected_generation,
                expected_version=command.expected_version,
                target_mode=LIVE_ORDER_MODE_ARMED,
                active_liquidation_operation_id=None,
                action=CONTROL_ACTION_ARMED,
                request_id=request_id,
                request_fingerprint=fingerprint,
                reason_code=reason_code,
                reason_text=reason_text,
                source=source,
                actor_ref=actor_ref,
                now=self._now(),
            )

        return await self._run_exclusive(operation)

    async def block(
        self,
        command: BlockLiveOrdersCommand,
    ) -> LiveOrderControlTransitionResult:
        """봇 런타임은 유지한 채 신규 실주문 권한만 즉시 제거한다."""
        return await self._block(
            command,
            stop_bot=False,
            disable_rollout=False,
            fingerprint_scope="BLOCK_LIVE_ORDERS",
        )

    async def stop_bot(
        self,
        command: BlockLiveOrdersCommand,
    ) -> LiveOrderControlTransitionResult:
        """봇 런타임 정지와 BLOCK_ALL을 하나의 DB 트랜잭션에 커밋한다."""
        return await self._block(
            command,
            stop_bot=True,
            disable_rollout=False,
            fingerprint_scope="STOP_BOT_AND_BLOCK",
        )

    async def trip_on_auth_failure(
        self,
        command: AuthFailureBlockCommand,
    ) -> LiveOrderControlTransitionResult:
        """인증·권한·IP·418 오류에서 rollout과 주문 권한을 함께 차단한다."""
        block_command = BlockLiveOrdersCommand(
            request_id=command.request_id,
            reason_code=command.reason_code,
            reason_text=command.reason_text,
            source=CONTROL_SOURCE_AUTH_FAILURE,
            actor_ref=command.actor_ref,
        )
        if (
            command.completed_post_intent_id is not None
            and command.completed_post_intent_id < 1
        ):
            raise LiveOrderControlPolicyError(
                "완료된 POST intent ID는 양수여야 합니다.",
                error_code="ORDER_GATE_STATE_UNAVAILABLE",
            )
        return await self._block(
            block_command,
            stop_bot=False,
            disable_rollout=True,
            operator_reason_required=False,
            fingerprint_scope="AUTH_FAILURE_BLOCK",
            drain_excluded_intent_id=command.completed_post_intent_id,
        )

    async def prepare_liquidation(
        self,
        command: PrepareEmergencyLiquidationCommand,
    ) -> LiveOrderControlTransitionResult:
        """대상 스냅샷 조회 전에 일반 주문을 drain하고 BLOCK_ALL을 확정한다."""
        async def operation(
            db: AsyncSession,
        ) -> tuple[LiveOrderControlTransitionResult, bool]:
            return await self.prepare_liquidation_in_transaction(db, command)

        transition, drain_pending = await self._run_exclusive(operation)
        if drain_pending:
            raise LiveOrderControlDrainPendingError(
                "청산 준비 차단은 적용됐지만 SUBMITTING 주문의 POST 종료를 아직 확인하지 못했습니다."
            )
        return transition

    async def prepare_liquidation_in_transaction(
        self,
        db: AsyncSession,
        command: PrepareEmergencyLiquidationCommand,
    ) -> tuple[LiveOrderControlTransitionResult, bool]:
        """호출자가 보유한 exclusive lease 트랜잭션에서 청산을 준비합니다."""
        request_id = _require_uuid4(command.request_id)
        reason_code = _require_reason_code(command.reason_code)
        reason_text = _require_operator_reason(command.reason_text)
        source = _require_source(command.source)
        actor_ref = _normalize_actor_ref(command.actor_ref)
        if command.operation_id < 1:
            raise LiveOrderControlPolicyError(
                "청산 operation ID는 양수여야 합니다.",
                error_code="EMERGENCY_AUTH_REQUIRED",
            )
        if await self._state_store.get_trading_mode(db) != TRADING_MODE_LIVE:
            raise LiveOrderControlPolicyError(
                "정상적인 live 거래 모드에서만 Upbit 전량청산을 준비할 수 있습니다.",
                error_code="TRADING_MODE_LIVE_REQUIRED",
            )

        fingerprint = build_control_request_fingerprint(
            action=CONTROL_ACTION_BLOCKED,
            expected_generation=None,
            target_mode=LIVE_ORDER_MODE_BLOCK_ALL,
            active_liquidation_operation_id=None,
            reason_code=reason_code,
            reason_text=reason_text,
            source=source,
            actor_ref=actor_ref,
            confirmation=f"PREPARE_LIQUIDATION:{command.operation_id}",
        )

        liquidation = await self._require_liquidation_operation(
            db,
            command.operation_id,
        )
        if liquidation.status not in ACTIVE_LIQUIDATION_STATUSES:
            raise LiveOrderControlPolicyError(
                "종결된 청산 operation은 대상 스냅샷을 다시 준비할 수 없습니다.",
                error_code="EMERGENCY_AUTH_REVOKED",
            )
        if (
            liquidation.emergency_authorization_status
            != EMERGENCY_AUTHORIZATION_REVOKED
            or liquidation.emergency_revocation_reason
            != INITIAL_EMERGENCY_REVOCATION_REASON
        ):
            raise LiveOrderControlPolicyError(
                "이미 승인·폐기된 청산 operation은 준비 단계로 되돌릴 수 없습니다.",
                error_code="EMERGENCY_AUTH_REVOKED",
            )

        control = await self._repository.get_control(db, for_update=True)
        if control is None:
            raise LiveOrderControlStateUnavailableError(
                "전역 실주문 제어 행을 찾을 수 없습니다."
            )
        existing_event = await self._repository.get_event(db, request_id)
        if existing_event is not None:
            latest_event = await self._repository.get_latest_event(
                db,
                control_id=control.id,
            )
            if latest_event is None or latest_event.id != existing_event.id:
                raise LiveOrderControlRequestSupersededError(
                    control=control,
                    event=existing_event,
                )
        if existing_event is None:
            if not await self._repository.get_rollout_flag(db):
                raise LiveOrderControlPolicyError(
                    "실주문 v2 rollout이 비활성화되어 비상청산을 준비할 수 없습니다.",
                    error_code="LIVE_ORDER_V2_DISABLED",
                )
            if control.active_liquidation_operation_id is not None:
                raise LiveOrderControlPolicyError(
                    "다른 전량청산 operation이 이미 EXIT_ONLY 권한을 사용 중입니다.",
                    error_code="ORDER_GATE_GENERATION_CONFLICT",
                )
            if control.mode == LIVE_ORDER_MODE_EXIT_ONLY:
                raise LiveOrderControlStateUnavailableError(
                    "EXIT_ONLY 제어 상태와 활성 청산 operation 연결이 일치하지 않습니다."
                )

        await self._state_store.set_bot_active(db, is_active=False)
        transition = await self._repository.transition_control(
            db,
            expected_generation=None,
            target_mode=LIVE_ORDER_MODE_BLOCK_ALL,
            active_liquidation_operation_id=None,
            action=CONTROL_ACTION_BLOCKED,
            request_id=request_id,
            request_fingerprint=fingerprint,
            reason_code=reason_code,
            reason_text=reason_text,
            source=source,
            actor_ref=actor_ref,
            now=self._now(),
        )
        drain_pending = await self._repository.has_submitting_intent(db)
        return transition, drain_pending

    async def authorize_liquidation(
        self,
        command: AuthorizeEmergencyLiquidationCommand,
    ) -> LiveOrderControlTransitionResult:
        async def operation(db: AsyncSession) -> LiveOrderControlTransitionResult:
            return await self.authorize_liquidation_in_transaction(db, command)

        return await self._run_exclusive(operation)

    async def authorize_liquidation_in_transaction(
        self,
        db: AsyncSession,
        command: AuthorizeEmergencyLiquidationCommand,
    ) -> LiveOrderControlTransitionResult:
        """호출자가 보유한 exclusive lease 트랜잭션에서 청산을 승인합니다."""
        request_id = _require_uuid4(command.request_id)
        reason_code = _require_reason_code(command.reason_code)
        reason_text = _require_operator_reason(command.reason_text)
        source = _require_source(command.source)
        actor_ref = _normalize_actor_ref(command.actor_ref)
        if command.operation_id < 1:
            raise LiveOrderControlPolicyError(
                "청산 operation ID는 양수여야 합니다.",
                error_code="EMERGENCY_AUTH_REQUIRED",
            )
        if await self._state_store.get_trading_mode(db) != TRADING_MODE_LIVE:
            raise LiveOrderControlPolicyError(
                "정상적인 live 거래 모드에서만 Upbit 전량청산을 승인할 수 있습니다.",
                error_code="TRADING_MODE_LIVE_REQUIRED",
            )
        if command.expected_generation < 1 or command.expected_version < 1:
            raise LiveOrderControlPolicyError(
                "청산 승인에는 양수 expected_generation과 expected_version이 필요합니다.",
                error_code="ORDER_GATE_GENERATION_CONFLICT",
            )

        fingerprint = build_control_request_fingerprint(
            action=CONTROL_ACTION_LIQUIDATION_AUTHORIZED,
            expected_generation=command.expected_generation,
            expected_version=command.expected_version,
            target_mode=LIVE_ORDER_MODE_EXIT_ONLY,
            active_liquidation_operation_id=command.operation_id,
            event_liquidation_operation_id=command.operation_id,
            reason_code=reason_code,
            reason_text=reason_text,
            source=source,
            actor_ref=actor_ref,
        )

        liquidation = await self._require_liquidation_operation(db, command.operation_id)
        self._assert_operation_request_key(liquidation, request_id)
        existing_event = await self._repository.get_event(db, request_id)
        if existing_event is not None:
            transition = await self._repository.transition_control(
                db,
                expected_generation=command.expected_generation,
                expected_version=command.expected_version,
                target_mode=LIVE_ORDER_MODE_EXIT_ONLY,
                active_liquidation_operation_id=command.operation_id,
                event_liquidation_operation_id=command.operation_id,
                action=CONTROL_ACTION_LIQUIDATION_AUTHORIZED,
                request_id=request_id,
                request_fingerprint=fingerprint,
                reason_code=reason_code,
                reason_text=reason_text,
                source=source,
                actor_ref=actor_ref,
                now=self._now(),
            )
            _assert_replayed_active_authorization(liquidation, transition)
            await self._state_store.set_bot_active(db, is_active=False)
            return transition

        if not await self._repository.get_rollout_flag(db):
            raise LiveOrderControlPolicyError(
                "실주문 v2 rollout이 비활성화되어 비상 청산도 승인할 수 없습니다.",
                error_code="LIVE_ORDER_V2_DISABLED",
            )
        if liquidation.status not in ACTIVE_LIQUIDATION_STATUSES:
            raise LiveOrderControlPolicyError(
                "종결된 청산 operation에는 새 EXIT_ONLY 권한을 부여할 수 없습니다.",
                error_code="EMERGENCY_AUTH_REVOKED",
            )
        if not _has_valid_liquidation_targets(liquidation.target_snapshot):
            raise LiveOrderControlPolicyError(
                "유효한 불변 청산 대상 스냅샷이 없어 EXIT_ONLY를 승인할 수 없습니다.",
                error_code="EMERGENCY_AUTH_REQUIRED",
            )
        if liquidation.emergency_authorization_status != EMERGENCY_AUTHORIZATION_REVOKED:
            raise LiveOrderControlPolicyError(
                "청산 operation의 기존 authorization 상태가 신규 승인을 허용하지 않습니다.",
                error_code="EMERGENCY_AUTH_REQUIRED",
            )
        if (
            liquidation.emergency_revocation_reason
            != INITIAL_EMERGENCY_REVOCATION_REASON
        ):
            raise LiveOrderControlPolicyError(
                "이미 명시적으로 폐기된 청산 operation은 다시 승인할 수 없습니다.",
                error_code="EMERGENCY_AUTH_REVOKED",
            )

        await self._state_store.set_bot_active(db, is_active=False)
        transition = await self._repository.transition_control(
            db,
            expected_generation=command.expected_generation,
            expected_version=command.expected_version,
            target_mode=LIVE_ORDER_MODE_EXIT_ONLY,
            active_liquidation_operation_id=command.operation_id,
            event_liquidation_operation_id=command.operation_id,
            action=CONTROL_ACTION_LIQUIDATION_AUTHORIZED,
            request_id=request_id,
            request_fingerprint=fingerprint,
            reason_code=reason_code,
            reason_text=reason_text,
            source=source,
            actor_ref=actor_ref,
            now=self._now(),
        )
        now = self._now()
        liquidation.emergency_authorization_status = EMERGENCY_AUTHORIZATION_ACTIVE
        liquidation.emergency_authorized_at = now
        liquidation.emergency_control_generation = transition.control.generation
        liquidation.emergency_control_event_id = transition.event.id
        liquidation.emergency_authorized_source = source
        liquidation.emergency_revoked_at = None
        liquidation.emergency_revocation_reason = None
        liquidation.emergency_closed_at = None
        await db.flush()
        return transition

    async def close_liquidation(
        self,
        command: CloseEmergencyLiquidationCommand,
    ) -> LiquidationAuthorizationCloseResult:
        """종결된 operation 권한을 닫고 gate를 BLOCK_ALL로 되돌린다."""
        async def operation(db: AsyncSession) -> LiquidationAuthorizationCloseResult:
            return await self.close_liquidation_in_transaction(db, command)

        return await self._run_exclusive(operation)

    async def close_liquidation_in_transaction(
        self,
        db: AsyncSession,
        command: CloseEmergencyLiquidationCommand,
    ) -> LiquidationAuthorizationCloseResult:
        """호출자가 보유한 exclusive lease 트랜잭션에서 청산 권한을 닫습니다."""
        request_id = _require_uuid4(command.request_id)
        reason_code = _require_reason_code(command.reason_code)
        reason_text = _require_nonempty_reason(command.reason_text)
        source = _require_source(command.source)
        actor_ref = _normalize_actor_ref(command.actor_ref)
        if command.operation_id < 1:
            raise LiveOrderControlPolicyError(
                "청산 operation ID는 양수여야 합니다.",
                error_code="EMERGENCY_AUTH_REQUIRED",
            )

        fingerprint = build_control_request_fingerprint(
            action=CONTROL_ACTION_LIQUIDATION_CLOSED,
            expected_generation=None,
            target_mode=LIVE_ORDER_MODE_BLOCK_ALL,
            active_liquidation_operation_id=None,
            event_liquidation_operation_id=command.operation_id,
            reason_code=reason_code,
            reason_text=reason_text,
            source=source,
            actor_ref=actor_ref,
        )

        liquidation = await self._require_liquidation_operation(db, command.operation_id)
        existing_event = await self._repository.get_event(db, request_id)
        if existing_event is not None:
            transition = await self._repository.transition_control(
                db,
                expected_generation=None,
                target_mode=LIVE_ORDER_MODE_BLOCK_ALL,
                active_liquidation_operation_id=None,
                event_liquidation_operation_id=command.operation_id,
                action=CONTROL_ACTION_LIQUIDATION_CLOSED,
                request_id=request_id,
                request_fingerprint=fingerprint,
                reason_code=reason_code,
                reason_text=reason_text,
                source=source,
                actor_ref=actor_ref,
                now=self._now(),
            )
            if liquidation.emergency_authorization_status != EMERGENCY_AUTHORIZATION_CLOSED:
                raise LiveOrderControlStateUnavailableError(
                    "청산 종결 event와 operation authorization 상태가 일치하지 않습니다."
                )
            return LiquidationAuthorizationCloseResult(
                control=transition.control,
                transition=transition,
                operation_id=command.operation_id,
                authorization_status=EMERGENCY_AUTHORIZATION_CLOSED,
                skipped_due_to_revocation=False,
            )

        if liquidation.status not in TERMINAL_LIQUIDATION_STATUSES:
            raise LiveOrderControlPolicyError(
                "아직 진행 중인 청산 operation의 authorization은 닫을 수 없습니다.",
                error_code="EMERGENCY_AUTH_REQUIRED",
            )
        if liquidation.emergency_authorization_status in {
            EMERGENCY_AUTHORIZATION_REVOKED,
            EMERGENCY_AUTHORIZATION_CLOSED,
        }:
            control = await self._repository.get_control(db, for_update=True)
            if control is None or control.mode != LIVE_ORDER_MODE_BLOCK_ALL:
                raise LiveOrderControlStateUnavailableError(
                    "폐기·종결된 청산 authorization과 BLOCK_ALL 상태가 일치하지 않습니다."
                )
            return LiquidationAuthorizationCloseResult(
                control=control,
                transition=None,
                operation_id=command.operation_id,
                authorization_status=liquidation.emergency_authorization_status,
                skipped_due_to_revocation=(
                    liquidation.emergency_authorization_status
                    == EMERGENCY_AUTHORIZATION_REVOKED
                ),
            )
        if liquidation.emergency_authorization_status != EMERGENCY_AUTHORIZATION_ACTIVE:
            raise LiveOrderControlStateUnavailableError(
                "해석할 수 없는 청산 authorization 상태입니다."
            )

        transition = await self._repository.transition_control(
            db,
            expected_generation=None,
            target_mode=LIVE_ORDER_MODE_BLOCK_ALL,
            active_liquidation_operation_id=None,
            event_liquidation_operation_id=command.operation_id,
            action=CONTROL_ACTION_LIQUIDATION_CLOSED,
            request_id=request_id,
            request_fingerprint=fingerprint,
            reason_code=reason_code,
            reason_text=reason_text,
            source=source,
            actor_ref=actor_ref,
            now=self._now(),
        )
        liquidation.emergency_authorization_status = EMERGENCY_AUTHORIZATION_CLOSED
        liquidation.emergency_closed_at = self._now()
        liquidation.emergency_revoked_at = None
        liquidation.emergency_revocation_reason = None
        await db.flush()
        return LiquidationAuthorizationCloseResult(
            control=transition.control,
            transition=transition,
            operation_id=command.operation_id,
            authorization_status=EMERGENCY_AUTHORIZATION_CLOSED,
            skipped_due_to_revocation=False,
        )

    async def _block(
        self,
        command: BlockLiveOrdersCommand,
        *,
        stop_bot: bool,
        disable_rollout: bool,
        operator_reason_required: bool = True,
        fingerprint_scope: str,
        drain_excluded_intent_id: int | None = None,
    ) -> LiveOrderControlTransitionResult:
        request_id = _require_uuid4(command.request_id)
        reason_code = _require_reason_code(command.reason_code)
        reason_text = (
            _require_operator_reason(command.reason_text)
            if operator_reason_required
            else _require_nonempty_reason(command.reason_text)
        )
        source = _require_source(command.source)
        actor_ref = _normalize_actor_ref(command.actor_ref)

        async def operation(
            db: AsyncSession,
        ) -> tuple[LiveOrderControlTransitionResult, bool]:
            existing_event = await self._repository.get_event(db, request_id)
            if existing_event is not None and _is_block_event(existing_event):
                action = existing_event.action
                event_operation_id = existing_event.liquidation_operation_id
            else:
                control = await self._repository.get_control(db, for_update=True)
                if control is None:
                    raise LiveOrderControlStateUnavailableError(
                        "전역 실주문 제어 행을 찾을 수 없습니다."
                    )
                action, event_operation_id = await self._resolve_block_action(db, control)

            fingerprint = build_control_request_fingerprint(
                action=action,
                expected_generation=None,
                target_mode=LIVE_ORDER_MODE_BLOCK_ALL,
                active_liquidation_operation_id=None,
                event_liquidation_operation_id=event_operation_id,
                reason_code=reason_code,
                reason_text=reason_text,
                source=source,
                actor_ref=actor_ref,
                confirmation=fingerprint_scope,
            )
            if stop_bot:
                await self._state_store.set_bot_active(db, is_active=False)
            if disable_rollout:
                await self._repository.disable_rollout_flag(db)

            transition = await self._repository.transition_control(
                db,
                expected_generation=None,
                target_mode=LIVE_ORDER_MODE_BLOCK_ALL,
                active_liquidation_operation_id=None,
                event_liquidation_operation_id=event_operation_id,
                action=action,
                request_id=request_id,
                request_fingerprint=fingerprint,
                reason_code=reason_code,
                reason_text=reason_text,
                source=source,
                actor_ref=actor_ref,
                now=self._now(),
            )
            if (
                action == CONTROL_ACTION_LIQUIDATION_REVOKED
                and event_operation_id is not None
            ):
                await self._revoke_operation_if_active(
                    db,
                    operation_id=event_operation_id,
                    reason=reason_text,
                )
            drain_pending = await self._repository.has_submitting_intent(
                db,
                exclude_intent_id=drain_excluded_intent_id,
            )
            return transition, drain_pending

        transition, drain_pending = await self._run_exclusive(operation)
        if drain_pending:
            raise LiveOrderControlDrainPendingError(
                "전역 차단은 적용됐지만 SUBMITTING 주문의 POST 종료를 아직 확인하지 못했습니다."
            )
        return transition

    async def _resolve_block_action(
        self,
        db: AsyncSession,
        control: LiveOrderControlRecord,
    ) -> tuple[str, int | None]:
        operation_id = control.active_liquidation_operation_id
        if control.mode != LIVE_ORDER_MODE_EXIT_ONLY or operation_id is None:
            return CONTROL_ACTION_BLOCKED, None
        liquidation = await self._require_liquidation_operation(db, operation_id)
        if liquidation.emergency_authorization_status == EMERGENCY_AUTHORIZATION_CLOSED:
            return CONTROL_ACTION_LIQUIDATION_CLOSED, operation_id
        return CONTROL_ACTION_LIQUIDATION_REVOKED, operation_id

    async def _revoke_operation_if_active(
        self,
        db: AsyncSession,
        *,
        operation_id: int,
        reason: str,
    ) -> None:
        liquidation = await self._require_liquidation_operation(db, operation_id)
        if liquidation.emergency_authorization_status != EMERGENCY_AUTHORIZATION_ACTIVE:
            return
        liquidation.emergency_authorization_status = EMERGENCY_AUTHORIZATION_REVOKED
        liquidation.emergency_revoked_at = self._now()
        liquidation.emergency_revocation_reason = reason
        liquidation.emergency_closed_at = None
        await db.flush()

    async def _assert_arm_preconditions(self, db: AsyncSession) -> None:
        if not await self._repository.get_rollout_flag(db):
            raise LiveOrderControlPolicyError(
                "실주문 v2 rollout이 비활성화되어 있습니다.",
                error_code="LIVE_ORDER_V2_DISABLED",
            )
        if not await self._state_store.get_bot_active(db):
            raise LiveOrderControlPolicyError(
                "봇 런타임이 정지된 상태에서는 실주문을 재무장할 수 없습니다.",
                error_code="BOT_INACTIVE",
            )
        if await self._state_store.get_trading_mode(db) != TRADING_MODE_LIVE:
            raise LiveOrderControlPolicyError(
                "trading_mode=live일 때만 실주문을 재무장할 수 있습니다.",
                error_code="LIVE_ORDER_GATE_BLOCKED",
            )
        if await self._repository.has_blocking_intent(db, include_prepared=False):
            raise LiveOrderControlPolicyError(
                "미해결 주문 intent가 있어 실주문을 재무장할 수 없습니다.",
                error_code="LIVE_ORDER_GATE_BLOCKED",
            )

    async def _require_liquidation_operation(
        self,
        db: AsyncSession,
        operation_id: int,
    ) -> LiquidationOperation:
        liquidation = await self._state_store.get_liquidation_operation_for_update(
            db,
            operation_id,
        )
        if liquidation is None:
            raise LiveOrderControlPolicyError(
                "청산 operation을 찾을 수 없습니다.",
                error_code="EMERGENCY_AUTH_REQUIRED",
            )
        return liquidation

    @staticmethod
    def _assert_operation_request_key(
        liquidation: LiquidationOperation,
        request_id: UUID,
    ) -> None:
        try:
            operation_request_id = _require_uuid4(liquidation.idempotency_key)
        except LiveOrderControlServiceError as exc:
            raise LiveOrderControlStateUnavailableError(
                "청산 operation의 idempotency key가 올바른 UUID v4가 아닙니다."
            ) from exc
        if operation_request_id != request_id:
            raise LiveOrderControlPolicyError(
                "청산 operation과 제어 요청의 idempotency key가 일치하지 않습니다.",
                error_code="ORDER_GATE_IDEMPOTENCY_CONFLICT",
            )

    async def _run_exclusive(
        self,
        operation: Callable[[AsyncSession], Awaitable[_ResultT]],
    ) -> _ResultT:
        try:
            async with self._barrier.exclusive() as lease:
                async with lease.transaction() as db:
                    return await operation(db)
        except asyncio.CancelledError:
            raise
        except (
            LiveOrderControlServiceError,
            LiveOrderControlTransitionError,
            LiveOrderSubmissionBarrierError,
        ):
            raise
        except Exception as exc:
            raise LiveOrderControlStateUnavailableError(
                "전역 실주문 제어 상태를 원자적으로 갱신하지 못했습니다."
            ) from exc

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise LiveOrderControlStateUnavailableError(
                "제어 감사 시각은 timezone-aware datetime이어야 합니다."
            )
        return value


def _require_uuid4(value: UUID | str) -> UUID:
    try:
        parsed = value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise LiveOrderControlPolicyError(
            "제어 request_id는 UUID v4여야 합니다.",
            error_code="ORDER_GATE_IDEMPOTENCY_CONFLICT",
        ) from exc
    if parsed.version != 4:
        raise LiveOrderControlPolicyError(
            "제어 request_id는 UUID v4여야 합니다.",
            error_code="ORDER_GATE_IDEMPOTENCY_CONFLICT",
        )
    return parsed


def _require_reason_code(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if not normalized:
        raise LiveOrderControlPolicyError(
            "제어 사유 코드는 비어 있을 수 없습니다.",
            error_code="LIVE_ORDER_GATE_BLOCKED",
        )
    return normalized


def _require_operator_reason(value: str) -> str:
    normalized = _require_nonempty_reason(value)
    if len(normalized) < 10:
        raise LiveOrderControlPolicyError(
            "운영자 제어 사유는 10자 이상이어야 합니다.",
            error_code="LIVE_ORDER_GATE_BLOCKED",
        )
    return normalized


def _require_nonempty_reason(value: str) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized:
        raise LiveOrderControlPolicyError(
            "제어 사유는 비어 있을 수 없습니다.",
            error_code="LIVE_ORDER_GATE_BLOCKED",
        )
    return normalized


def _require_source(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in LIVE_ORDER_CONTROL_SOURCES:
        raise LiveOrderControlPolicyError(
            "지원하지 않는 제어 요청 source입니다.",
            error_code="LIVE_ORDER_GATE_BLOCKED",
        )
    return normalized


def _normalize_actor_ref(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


def _has_valid_liquidation_targets(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return False
    seen_markets: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return False
        market = str(item.get("market") or "").strip().upper()
        try:
            volume = Decimal(str(item.get("volume")))
        except (InvalidOperation, TypeError, ValueError):
            return False
        if not market or market in seen_markets or not volume.is_finite() or volume <= 0:
            return False
        seen_markets.add(market)
    return True


def _is_block_event(event: LiveOrderControlEventRecord) -> bool:
    return event.to_mode == LIVE_ORDER_MODE_BLOCK_ALL and event.action in {
        CONTROL_ACTION_BLOCKED,
        CONTROL_ACTION_LIQUIDATION_REVOKED,
        CONTROL_ACTION_LIQUIDATION_CLOSED,
    }


def _assert_replayed_active_authorization(
    liquidation: LiquidationOperation,
    transition: LiveOrderControlTransitionResult,
) -> None:
    if not (
        transition.replayed
        and liquidation.status in ACTIVE_LIQUIDATION_STATUSES
        and liquidation.emergency_authorization_status == EMERGENCY_AUTHORIZATION_ACTIVE
        and liquidation.emergency_control_generation == transition.control.generation
        and liquidation.emergency_control_event_id == transition.event.id
        and transition.control.mode == LIVE_ORDER_MODE_EXIT_ONLY
        and transition.control.active_liquidation_operation_id == liquidation.id
        and _has_valid_liquidation_targets(liquidation.target_snapshot)
    ):
        raise LiveOrderControlStateUnavailableError(
            "재생된 청산 승인 event와 operation authorization 상태가 일치하지 않습니다."
        )
