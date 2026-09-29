from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Final
from uuid import UUID

from sqlalchemy import and_, exists, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.repository import LIVE_ORDER_V2_ENABLED_KEY
from app.db.trading_mode_repository import TRADING_MODE_LIVE, TradingModeRepository
from app.models.domain import (
    BotConfig,
    LiquidationOperation,
    LiveOrderControl,
    LiveOrderControlEvent,
    OrderIntent,
    SystemConfig,
)

LIVE_ORDER_MODE_ARMED: Final = "ARMED"
LIVE_ORDER_MODE_EXIT_ONLY: Final = "EXIT_ONLY"
LIVE_ORDER_MODE_BLOCK_ALL: Final = "BLOCK_ALL"
LIVE_ORDER_CONTROL_MODES: Final = frozenset(
    {
        LIVE_ORDER_MODE_ARMED,
        LIVE_ORDER_MODE_EXIT_ONLY,
        LIVE_ORDER_MODE_BLOCK_ALL,
    }
)

EMERGENCY_AUTHORIZATION_ACTIVE: Final = "ACTIVE"
EMERGENCY_AUTHORIZATION_REVOKED: Final = "REVOKED"
EMERGENCY_AUTHORIZATION_CLOSED: Final = "CLOSED"
EMERGENCY_AUTHORIZATION_STATUSES: Final = frozenset(
    {
        EMERGENCY_AUTHORIZATION_ACTIVE,
        EMERGENCY_AUTHORIZATION_REVOKED,
        EMERGENCY_AUTHORIZATION_CLOSED,
    }
)

CONTROL_SOURCE_REST: Final = "REST"
CONTROL_SOURCE_SLACK: Final = "SLACK"
CONTROL_SOURCE_TELEGRAM: Final = "TELEGRAM"
CONTROL_SOURCE_SYSTEM: Final = "SYSTEM"
CONTROL_SOURCE_AUTH_FAILURE: Final = "AUTH_FAILURE"
LIVE_ORDER_CONTROL_SOURCES: Final = frozenset(
    {
        CONTROL_SOURCE_REST,
        CONTROL_SOURCE_SLACK,
        CONTROL_SOURCE_TELEGRAM,
        CONTROL_SOURCE_SYSTEM,
        CONTROL_SOURCE_AUTH_FAILURE,
    }
)

CONTROL_ACTION_INITIALIZED: Final = "INITIALIZED"
CONTROL_ACTION_ARMED: Final = "ARMED"
CONTROL_ACTION_BLOCKED: Final = "BLOCKED"
CONTROL_ACTION_LIQUIDATION_AUTHORIZED: Final = "LIQUIDATION_AUTHORIZED"
CONTROL_ACTION_LIQUIDATION_REVOKED: Final = "LIQUIDATION_REVOKED"
CONTROL_ACTION_LIQUIDATION_CLOSED: Final = "LIQUIDATION_CLOSED"
LIVE_ORDER_CONTROL_ACTIONS: Final = frozenset(
    {
        CONTROL_ACTION_INITIALIZED,
        CONTROL_ACTION_ARMED,
        CONTROL_ACTION_BLOCKED,
        CONTROL_ACTION_LIQUIDATION_AUTHORIZED,
        CONTROL_ACTION_LIQUIDATION_REVOKED,
        CONTROL_ACTION_LIQUIDATION_CLOSED,
    }
)

BLOCKING_SUBMISSION_STATUSES: Final = ("PREPARED", "SUBMITTING", "UNKNOWN")
OPEN_EXCHANGE_STATES: Final = ("wait", "watch")
TERMINAL_EXCHANGE_STATES: Final = ("done", "cancel")
_SHA256_HEX_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")


def _normalize_target_snapshot(
    value: object,
) -> tuple[tuple[str, str], ...] | None:
    if not isinstance(value, list):
        return None
    targets: list[tuple[str, str]] = []
    seen_markets: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            return None
        market = str(item.get("market") or "").strip().upper()
        raw_volume = item.get("volume")
        try:
            volume = Decimal(str(raw_volume))
        except (InvalidOperation, TypeError, ValueError):
            return None
        if not market or market in seen_markets or not volume.is_finite() or volume <= 0:
            return None
        seen_markets.add(market)
        targets.append((market, format(volume, "f")))
    return tuple(sorted(targets))


def _is_uuid4(value: object) -> bool:
    try:
        parsed = UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return False
    return parsed.version == 4


@dataclass(frozen=True, slots=True)
class LiveOrderControlRecord:
    id: int
    broker: str
    account_scope: str
    mode: str
    active_liquidation_operation_id: int | None
    generation: int
    version: int
    reason_code: str
    reason_text: str
    changed_source: str
    changed_actor_ref: str | None
    armed_at: datetime | None
    blocked_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LiveOrderControlEventRecord:
    id: int
    control_id: int
    generation: int
    request_id: str | None
    request_fingerprint: str | None
    action: str
    from_mode: str | None
    to_mode: str
    reason_code: str
    reason_text: str
    source: str
    actor_ref: str | None
    liquidation_operation_id: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LiveOrderPreparationSnapshot:
    mode: str
    generation: int


@dataclass(frozen=True, slots=True)
class EmergencyLiquidationAuthorizationRecord:
    operation_id: int
    operation_idempotency_key: str
    operation_status: str
    authorization_status: str
    control_generation: int | None
    control_event_id: int | None
    authorized_source: str | None
    event_control_id: int | None
    event_generation: int | None
    event_request_id: str | None
    event_request_fingerprint: str | None
    event_action: str | None
    event_to_mode: str | None
    event_source: str | None
    event_liquidation_operation_id: int | None
    target_snapshot: tuple[tuple[str, str], ...] | None = None

    def permits(
        self,
        *,
        control: LiveOrderControlRecord,
        liquidation_operation_id: int,
    ) -> bool:
        return (
            self.operation_id == liquidation_operation_id
            and _is_uuid4(self.operation_idempotency_key)
            and self.operation_status in {"PREPARING", "IN_PROGRESS"}
            and self.authorization_status == EMERGENCY_AUTHORIZATION_ACTIVE
            and self.control_generation == control.generation
            and self.control_event_id is not None
            and self.authorized_source in LIVE_ORDER_CONTROL_SOURCES
            and self.event_control_id == control.id
            and self.event_generation == control.generation
            and self.event_request_id == self.operation_idempotency_key
            and _is_uuid4(self.event_request_id)
            and self.event_request_fingerprint is not None
            and _SHA256_HEX_PATTERN.fullmatch(self.event_request_fingerprint) is not None
            and self.event_action == CONTROL_ACTION_LIQUIDATION_AUTHORIZED
            and self.event_to_mode == LIVE_ORDER_MODE_EXIT_ONLY
            and self.event_source == self.authorized_source
            and self.event_liquidation_operation_id == liquidation_operation_id
        )

    def permits_target(self, *, market: str, volume: Decimal | None) -> bool:
        if self.target_snapshot is None or volume is None:
            return False
        normalized_market = str(market or "").strip().upper()
        matches = [
            target_volume
            for target_market, target_volume in self.target_snapshot
            if target_market == normalized_market
        ]
        if len(matches) != 1:
            return False
        try:
            expected_volume = Decimal(matches[0])
        except (InvalidOperation, TypeError, ValueError):
            return False
        return volume.is_finite() and volume > 0 and expected_volume == volume


@dataclass(frozen=True, slots=True)
class LiveOrderSubmissionGateSnapshot:
    rollout_enabled: bool
    bot_active: bool
    control: LiveOrderControlRecord | None
    general_authorization_event_id: int | None = None
    emergency_authorization: EmergencyLiquidationAuthorizationRecord | None = None
    trading_mode: str = "paper"
    trading_mode_state_available: bool = False

    @property
    def trading_mode_live(self) -> bool:
        return self.trading_mode_state_available and self.trading_mode == TRADING_MODE_LIVE

    @property
    def general_submission_allowed(self) -> bool:
        return (
            self.trading_mode_live
            and self.rollout_enabled
            and self.bot_active
            and self.control is not None
            and self.control.mode == LIVE_ORDER_MODE_ARMED
            and self.control.generation >= 1
            and self.control.version >= 1
            and self.control.active_liquidation_operation_id is None
            and self.general_authorization_event_id is not None
        )

    def emergency_submission_allowed(self, liquidation_operation_id: int) -> bool:
        return (
            self.trading_mode_live
            and self.rollout_enabled
            and self.control is not None
            and self.control.mode == LIVE_ORDER_MODE_EXIT_ONLY
            and self.control.generation >= 1
            and self.control.version >= 1
            and self.control.active_liquidation_operation_id == liquidation_operation_id
            and self.emergency_authorization is not None
            and self.emergency_authorization.permits(
                control=self.control,
                liquidation_operation_id=liquidation_operation_id,
            )
        )


@dataclass(frozen=True, slots=True)
class LiveOrderControlTransitionResult:
    control: LiveOrderControlRecord
    event: LiveOrderControlEventRecord
    replayed: bool
    permission_scope_changed: bool


class LiveOrderControlTransitionError(RuntimeError):
    error_code = "ORDER_GATE_STATE_UNAVAILABLE"

    def __init__(
        self,
        message: str,
        *,
        control: LiveOrderControlRecord | None = None,
        event: LiveOrderControlEventRecord | None = None,
    ) -> None:
        super().__init__(message)
        self.control = control
        self.event = event


class LiveOrderControlUnavailableError(LiveOrderControlTransitionError):
    error_code = "ORDER_GATE_STATE_UNAVAILABLE"


class LiveOrderControlGenerationConflictError(LiveOrderControlTransitionError):
    error_code = "ORDER_GATE_GENERATION_CONFLICT"

    def __init__(
        self,
        *,
        expected_generation: int,
        control: LiveOrderControlRecord,
    ) -> None:
        super().__init__(
            "실주문 제어 generation이 요청 시점 이후 변경되었습니다.",
            control=control,
        )
        self.expected_generation = expected_generation
        self.actual_generation = control.generation


class LiveOrderControlVersionConflictError(LiveOrderControlTransitionError):
    error_code = "ORDER_GATE_GENERATION_CONFLICT"

    def __init__(
        self,
        *,
        expected_version: int,
        control: LiveOrderControlRecord,
    ) -> None:
        super().__init__(
            "실주문 제어 version이 요청 시점 이후 변경되었습니다.",
            control=control,
        )
        self.expected_version = expected_version
        self.actual_version = control.version


class LiveOrderControlIdempotencyConflictError(LiveOrderControlTransitionError):
    error_code = "ORDER_GATE_IDEMPOTENCY_CONFLICT"

    def __init__(
        self,
        *,
        control: LiveOrderControlRecord,
        event: LiveOrderControlEventRecord,
    ) -> None:
        super().__init__(
            "동일한 실주문 제어 요청 키에 다른 payload가 사용되었습니다.",
            control=control,
            event=event,
        )


class LiveOrderControlRequestSupersededError(LiveOrderControlTransitionError):
    error_code = "ORDER_GATE_REQUEST_SUPERSEDED"

    def __init__(
        self,
        *,
        control: LiveOrderControlRecord,
        event: LiveOrderControlEventRecord,
    ) -> None:
        super().__init__(
            "실주문 제어 요청 성공 이후 더 새로운 상태 전이가 적용되었습니다.",
            control=control,
            event=event,
        )


def _normalize_fingerprint_text(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.strip().split())


def build_control_request_fingerprint(
    *,
    action: str,
    expected_generation: int | None,
    expected_version: int | None = None,
    target_mode: str,
    active_liquidation_operation_id: int | None,
    event_liquidation_operation_id: int | None = None,
    reason_code: str,
    reason_text: str,
    source: str,
    actor_ref: str | None,
    confirmation: str | None = None,
) -> str:
    payload = {
        "action": action.strip().upper(),
        "active_liquidation_operation_id": active_liquidation_operation_id,
        "actor_ref": _normalize_fingerprint_text(actor_ref),
        "confirmation": _normalize_fingerprint_text(confirmation),
        "event_liquidation_operation_id": event_liquidation_operation_id,
        "expected_generation": expected_generation,
        "expected_version": expected_version,
        "reason_code": reason_code.strip().upper(),
        "reason_text": _normalize_fingerprint_text(reason_text),
        "source": source.strip().upper(),
        "target_mode": target_mode.strip().upper(),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _blocking_intent_predicate(*, include_prepared: bool):
    blocking_submission_statuses = (
        BLOCKING_SUBMISSION_STATUSES
        if include_prepared
        else tuple(status for status in BLOCKING_SUBMISSION_STATUSES if status != "PREPARED")
    )
    return or_(
        OrderIntent.submission_status.in_(blocking_submission_statuses),
        and_(
            OrderIntent.submission_status == "ACCEPTED",
            or_(
                OrderIntent.exchange_state.is_(None),
                OrderIntent.exchange_state.in_(OPEN_EXCHANGE_STATES),
                and_(
                    OrderIntent.exchange_state.in_(TERMINAL_EXCHANGE_STATES),
                    OrderIntent.projection_status.in_(("PENDING", "ERROR")),
                ),
            ),
        ),
    )


def _normalize_request_id(request_id: UUID | str) -> str:
    parsed = request_id if isinstance(request_id, UUID) else UUID(str(request_id))
    if parsed.version != 4:
        raise ValueError("실주문 제어 request_id는 UUID v4여야 합니다.")
    return str(parsed)


def _valid_permission_scope(
    *,
    mode: str,
    generation: int,
    version: int,
    active_liquidation_operation_id: int | None,
) -> bool:
    if mode not in LIVE_ORDER_CONTROL_MODES or generation < 1 or version < 1:
        return False
    if mode == LIVE_ORDER_MODE_EXIT_ONLY:
        return active_liquidation_operation_id is not None
    return active_liquidation_operation_id is None


def _validate_transition_shape(
    *,
    target_mode: str,
    active_liquidation_operation_id: int | None,
    event_liquidation_operation_id: int | None,
    action: str,
    source: str,
    request_id: UUID | str | None,
    request_fingerprint: str | None,
) -> tuple[str | None, str | None]:
    if target_mode not in LIVE_ORDER_CONTROL_MODES:
        raise ValueError(f"지원하지 않는 실주문 제어 mode입니다: {target_mode}")
    if action not in LIVE_ORDER_CONTROL_ACTIONS:
        raise ValueError(f"지원하지 않는 실주문 제어 action입니다: {action}")
    if source not in LIVE_ORDER_CONTROL_SOURCES:
        raise ValueError(f"지원하지 않는 실주문 제어 source입니다: {source}")
    expected_target_by_action = {
        CONTROL_ACTION_INITIALIZED: LIVE_ORDER_MODE_BLOCK_ALL,
        CONTROL_ACTION_ARMED: LIVE_ORDER_MODE_ARMED,
        CONTROL_ACTION_BLOCKED: LIVE_ORDER_MODE_BLOCK_ALL,
        CONTROL_ACTION_LIQUIDATION_AUTHORIZED: LIVE_ORDER_MODE_EXIT_ONLY,
        CONTROL_ACTION_LIQUIDATION_REVOKED: LIVE_ORDER_MODE_BLOCK_ALL,
        CONTROL_ACTION_LIQUIDATION_CLOSED: LIVE_ORDER_MODE_BLOCK_ALL,
    }
    if expected_target_by_action[action] != target_mode:
        raise ValueError(f"{action} action과 {target_mode} target mode가 일치하지 않습니다.")
    if target_mode == LIVE_ORDER_MODE_EXIT_ONLY:
        if active_liquidation_operation_id is None:
            raise ValueError("EXIT_ONLY 전이에는 청산 operation ID가 필요합니다.")
    elif active_liquidation_operation_id is not None:
        raise ValueError("EXIT_ONLY가 아닌 전이에는 활성 청산 operation을 지정할 수 없습니다.")
    if action == CONTROL_ACTION_LIQUIDATION_AUTHORIZED:
        if event_liquidation_operation_id != active_liquidation_operation_id:
            raise ValueError("청산 승인 event와 활성 제어 상태는 같은 operation을 가리켜야 합니다.")
    elif action in {
        CONTROL_ACTION_LIQUIDATION_REVOKED,
        CONTROL_ACTION_LIQUIDATION_CLOSED,
    }:
        if event_liquidation_operation_id is None:
            raise ValueError("청산 폐기·종결 event에는 대상 operation ID가 필요합니다.")
    elif event_liquidation_operation_id is not None:
        raise ValueError("청산 action이 아닌 event에는 청산 operation을 지정할 수 없습니다.")
    if (request_id is None) != (request_fingerprint is None):
        raise ValueError("request_id와 request_fingerprint는 함께 지정해야 합니다.")
    normalized_request_id = _normalize_request_id(request_id) if request_id is not None else None
    if request_fingerprint is not None and not _SHA256_HEX_PATTERN.fullmatch(request_fingerprint):
        raise ValueError("request_fingerprint는 소문자 SHA-256 hex여야 합니다.")
    return normalized_request_id, request_fingerprint


class LiveOrderControlRepository:
    async def get_control(
        self,
        db: AsyncSession,
        *,
        broker: str = "UPBIT",
        account_scope: str = "primary",
        for_update: bool = False,
    ) -> LiveOrderControlRecord | None:
        statement = select(LiveOrderControl).where(
            LiveOrderControl.broker == broker,
            LiveOrderControl.account_scope == account_scope,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await db.execute(statement)
        model = result.scalar_one_or_none()
        return self._control_to_record(model) if model is not None else None

    async def has_active_liquidation_operation(self, db: AsyncSession) -> bool:
        """Gate pointer 유무와 무관하게 살아 있는 청산 권한·operation을 탐지한다."""
        statement = select(
            exists().where(
                or_(
                    LiquidationOperation.status.in_({"PREPARING", "IN_PROGRESS"}),
                    LiquidationOperation.emergency_authorization_status
                    == EMERGENCY_AUTHORIZATION_ACTIVE,
                )
            )
        )
        return bool(await db.scalar(statement))

    async def get_event(
        self,
        db: AsyncSession,
        request_id: UUID | str,
    ) -> LiveOrderControlEventRecord | None:
        normalized_request_id = _normalize_request_id(request_id)
        result = await db.execute(
            select(LiveOrderControlEvent).where(
                LiveOrderControlEvent.request_id == normalized_request_id
            )
        )
        model = result.scalar_one_or_none()
        return self._event_to_record(model) if model is not None else None

    async def get_event_by_id(
        self,
        db: AsyncSession,
        event_id: int,
    ) -> LiveOrderControlEventRecord | None:
        result = await db.execute(
            select(LiveOrderControlEvent).where(LiveOrderControlEvent.id == event_id)
        )
        model = result.scalar_one_or_none()
        return self._event_to_record(model) if model is not None else None

    async def get_latest_event(
        self,
        db: AsyncSession,
        *,
        control_id: int,
    ) -> LiveOrderControlEventRecord | None:
        result = await db.execute(
            select(LiveOrderControlEvent)
            .where(LiveOrderControlEvent.control_id == control_id)
            .order_by(LiveOrderControlEvent.id.desc())
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return self._event_to_record(model) if model is not None else None

    async def get_rollout_flag(self, db: AsyncSession) -> bool:
        result = await db.execute(
            select(SystemConfig.config_value).where(
                SystemConfig.config_key == LIVE_ORDER_V2_ENABLED_KEY
            )
        )
        return result.scalar_one_or_none() == "true"

    async def disable_rollout_flag(self, db: AsyncSession) -> None:
        statement = (
            postgresql_insert(SystemConfig)
            .values(
                config_key=LIVE_ORDER_V2_ENABLED_KEY,
                config_value="false",
                description="멱등 실주문 실행 경계 활성화 여부",
            )
            .on_conflict_do_update(
                index_elements=[SystemConfig.config_key],
                set_={
                    "config_value": "false",
                    "version": SystemConfig.version + 1,
                },
            )
        )
        await db.execute(statement)
        await db.flush()

    async def has_blocking_intent(
        self,
        db: AsyncSession,
        *,
        broker: str = "UPBIT",
        account_scope: str = "primary",
        include_prepared: bool = True,
    ) -> bool:
        result = await db.execute(
            select(OrderIntent.id)
            .where(
                OrderIntent.broker == broker,
                OrderIntent.account_scope == account_scope,
                _blocking_intent_predicate(include_prepared=include_prepared),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def has_submitting_intent(
        self,
        db: AsyncSession,
        *,
        exclude_intent_id: int | None = None,
        broker: str = "UPBIT",
        account_scope: str = "primary",
    ) -> bool:
        statement = select(OrderIntent.id).where(
            OrderIntent.broker == broker,
            OrderIntent.account_scope == account_scope,
            OrderIntent.submission_status == "SUBMITTING",
            OrderIntent.post_attempt_count == 1,
        )
        if exclude_intent_id is not None:
            statement = statement.where(OrderIntent.id != exclude_intent_id)
        result = await db.execute(statement.limit(1))
        return result.scalar_one_or_none() is not None

    async def abandon_stale_prepared_intents(
        self,
        db: AsyncSession,
        *,
        target_generation: int,
        target_mode: str,
        now: datetime,
        broker: str = "UPBIT",
        account_scope: str = "primary",
    ) -> int:
        if target_generation < 1 or target_mode not in LIVE_ORDER_CONTROL_MODES:
            raise ValueError("유효한 목표 control generation과 mode가 필요합니다.")
        result = await db.execute(
            update(OrderIntent)
            .where(
                OrderIntent.broker == broker,
                OrderIntent.account_scope == account_scope,
                OrderIntent.submission_status == "PREPARED",
                OrderIntent.post_attempt_count == 0,
                or_(
                    OrderIntent.prepared_control_generation.is_(None),
                    OrderIntent.prepared_control_mode.is_(None),
                    OrderIntent.prepared_control_generation != target_generation,
                    OrderIntent.prepared_control_mode != target_mode,
                ),
            )
            .values(
                submission_status="ABANDONED",
                projection_status="SKIPPED",
                last_error_code="ORDER_GATE_GENERATION_CONFLICT",
                last_error_message=(
                    "실주문 제어 범위가 변경되어 과거 세대의 PREPARED 주문 의도를 종결했습니다."
                ),
                resolved_at=now,
                next_reconcile_at=None,
                reconcile_lease_until=None,
                version=OrderIntent.version + 1,
            )
        )
        await db.flush()
        return int(getattr(result, "rowcount", 0) or 0)

    async def get_preparation_snapshot(
        self,
        db: AsyncSession,
        *,
        broker: str = "UPBIT",
        account_scope: str = "primary",
    ) -> LiveOrderPreparationSnapshot | None:
        result = await db.execute(
            select(
                LiveOrderControl.mode,
                LiveOrderControl.generation,
                LiveOrderControl.version,
                LiveOrderControl.active_liquidation_operation_id,
            ).where(
                LiveOrderControl.broker == broker,
                LiveOrderControl.account_scope == account_scope,
            )
        )
        row = result.one_or_none()
        if row is None or not _valid_permission_scope(
            mode=row.mode,
            generation=row.generation,
            version=row.version,
            active_liquidation_operation_id=row.active_liquidation_operation_id,
        ):
            return None
        return LiveOrderPreparationSnapshot(mode=row.mode, generation=row.generation)

    async def get_submission_gate_snapshot(
        self,
        db: AsyncSession,
        *,
        broker: str = "UPBIT",
        account_scope: str = "primary",
    ) -> LiveOrderSubmissionGateSnapshot:
        anchor = select(literal(1).label("anchor")).subquery()
        rollout_value = (
            select(SystemConfig.config_value)
            .where(SystemConfig.config_key == LIVE_ORDER_V2_ENABLED_KEY)
            .scalar_subquery()
        )
        bot_active_value = select(BotConfig.is_active).where(BotConfig.id == 1).scalar_subquery()
        general_authorization_event = aliased(LiveOrderControlEvent)
        authorization_event = aliased(LiveOrderControlEvent)
        statement = (
            select(
                rollout_value,
                bot_active_value,
                LiveOrderControl,
                general_authorization_event,
                LiquidationOperation,
                authorization_event,
            )
            .select_from(anchor)
            .outerjoin(
                LiveOrderControl,
                and_(
                    LiveOrderControl.broker == broker,
                    LiveOrderControl.account_scope == account_scope,
                ),
            )
            .outerjoin(
                general_authorization_event,
                and_(
                    general_authorization_event.control_id == LiveOrderControl.id,
                    general_authorization_event.generation == LiveOrderControl.generation,
                    general_authorization_event.action == CONTROL_ACTION_ARMED,
                    general_authorization_event.to_mode == LIVE_ORDER_MODE_ARMED,
                    general_authorization_event.from_mode.is_not(None),
                    general_authorization_event.from_mode != LIVE_ORDER_MODE_ARMED,
                    general_authorization_event.request_id.is_not(None),
                    general_authorization_event.request_fingerprint.is_not(None),
                ),
            )
            .outerjoin(
                LiquidationOperation,
                LiquidationOperation.id == LiveOrderControl.active_liquidation_operation_id,
            )
            .outerjoin(
                authorization_event,
                authorization_event.id == LiquidationOperation.emergency_control_event_id,
            )
        )
        row = (await db.execute(statement)).one()
        trading_mode_status = await TradingModeRepository().status(db)
        control_model = row[2]
        general_event_model = row[3]
        operation_model = row[4]
        event_model = row[5]
        control = (
            self._control_to_record(control_model)
            if control_model is not None
            and _valid_permission_scope(
                mode=control_model.mode,
                generation=control_model.generation,
                version=control_model.version,
                active_liquidation_operation_id=(control_model.active_liquidation_operation_id),
            )
            else None
        )
        emergency_authorization = (
            EmergencyLiquidationAuthorizationRecord(
                operation_id=operation_model.id,
                operation_idempotency_key=operation_model.idempotency_key,
                operation_status=operation_model.status,
                authorization_status=operation_model.emergency_authorization_status,
                control_generation=operation_model.emergency_control_generation,
                control_event_id=operation_model.emergency_control_event_id,
                authorized_source=operation_model.emergency_authorized_source,
                event_control_id=event_model.control_id if event_model is not None else None,
                event_generation=event_model.generation if event_model is not None else None,
                event_request_id=event_model.request_id if event_model is not None else None,
                event_request_fingerprint=(
                    event_model.request_fingerprint if event_model is not None else None
                ),
                event_action=event_model.action if event_model is not None else None,
                event_to_mode=event_model.to_mode if event_model is not None else None,
                event_source=event_model.source if event_model is not None else None,
                event_liquidation_operation_id=(
                    event_model.liquidation_operation_id if event_model is not None else None
                ),
                target_snapshot=_normalize_target_snapshot(operation_model.target_snapshot),
            )
            if operation_model is not None
            else None
        )
        return LiveOrderSubmissionGateSnapshot(
            rollout_enabled=row[0] == "true",
            bot_active=row[1] is True,
            control=control,
            general_authorization_event_id=(
                general_event_model.id if general_event_model is not None else None
            ),
            emergency_authorization=emergency_authorization,
            trading_mode=trading_mode_status.mode,
            trading_mode_state_available=trading_mode_status.state_available,
        )

    async def transition_control(
        self,
        db: AsyncSession,
        *,
        expected_generation: int | None,
        expected_version: int | None = None,
        target_mode: str,
        active_liquidation_operation_id: int | None,
        event_liquidation_operation_id: int | None = None,
        action: str,
        request_id: UUID | str | None,
        request_fingerprint: str | None,
        reason_code: str,
        reason_text: str,
        source: str,
        actor_ref: str | None,
        now: datetime,
        broker: str = "UPBIT",
        account_scope: str = "primary",
    ) -> LiveOrderControlTransitionResult:
        normalized_request_id, normalized_fingerprint = _validate_transition_shape(
            target_mode=target_mode,
            active_liquidation_operation_id=active_liquidation_operation_id,
            event_liquidation_operation_id=event_liquidation_operation_id,
            action=action,
            source=source,
            request_id=request_id,
            request_fingerprint=request_fingerprint,
        )
        if expected_generation is not None and expected_generation < 1:
            raise ValueError("expected_generation은 1 이상이어야 합니다.")
        if expected_version is not None and expected_version < 1:
            raise ValueError("expected_version은 1 이상이어야 합니다.")
        if expected_generation is None and target_mode != LIVE_ORDER_MODE_BLOCK_ALL:
            raise ValueError("expected_generation 생략은 BLOCK_ALL 제한 전이에서만 허용됩니다.")
        if target_mode != LIVE_ORDER_MODE_BLOCK_ALL and expected_version is None:
            raise ValueError("허용 범위를 넓히는 전이에는 expected_version이 필요합니다.")
        if not reason_code.strip():
            raise ValueError("reason_code는 비어 있을 수 없습니다.")
        if not reason_text.strip():
            raise ValueError("reason_text는 비어 있을 수 없습니다.")
        if not source.strip():
            raise ValueError("source는 비어 있을 수 없습니다.")

        control_model = await self._get_control_model(
            db,
            broker=broker,
            account_scope=account_scope,
            for_update=True,
        )
        if control_model is None:
            raise LiveOrderControlUnavailableError(
                "실주문 제어 행이 없어 상태 전이를 거부했습니다."
            )
        control = self._control_to_record(control_model)

        if normalized_request_id is not None:
            existing_event = await self.get_event(db, normalized_request_id)
            if existing_event is not None:
                return self._resolve_existing_request(
                    control=control,
                    event=existing_event,
                    request_fingerprint=normalized_fingerprint,
                )

        if expected_generation is not None and control.generation != expected_generation:
            raise LiveOrderControlGenerationConflictError(
                expected_generation=expected_generation,
                control=control,
            )
        if expected_version is not None and control.version != expected_version:
            raise LiveOrderControlVersionConflictError(
                expected_version=expected_version,
                control=control,
            )
        if control.active_liquidation_operation_id is not None and action not in {
            CONTROL_ACTION_LIQUIDATION_REVOKED,
            CONTROL_ACTION_LIQUIDATION_CLOSED,
        }:
            raise LiveOrderControlUnavailableError(
                "활성 청산 권한은 명시적인 폐기·종결 전이로만 해제할 수 있습니다.",
                control=control,
            )
        if action in {
            CONTROL_ACTION_LIQUIDATION_REVOKED,
            CONTROL_ACTION_LIQUIDATION_CLOSED,
        } and (
            control.mode != LIVE_ORDER_MODE_EXIT_ONLY
            or control.active_liquidation_operation_id != event_liquidation_operation_id
        ):
            raise LiveOrderControlUnavailableError(
                "폐기·종결하려는 청산 operation이 현재 EXIT_ONLY 권한과 일치하지 않습니다.",
                control=control,
            )

        permission_scope_changed = (
            control.mode != target_mode
            or control.active_liquidation_operation_id != active_liquidation_operation_id
        )
        next_generation = control.generation + 1 if permission_scope_changed else control.generation
        await self.abandon_stale_prepared_intents(
            db,
            target_generation=next_generation,
            target_mode=target_mode,
            now=now,
            broker=broker,
            account_scope=account_scope,
        )
        event_model = LiveOrderControlEvent(
            control_id=control.id,
            generation=next_generation,
            request_id=normalized_request_id,
            request_fingerprint=normalized_fingerprint,
            action=action,
            from_mode=control.mode,
            to_mode=target_mode,
            reason_code=reason_code,
            reason_text=reason_text,
            source=source,
            actor_ref=actor_ref,
            liquidation_operation_id=event_liquidation_operation_id,
            created_at=now,
        )

        try:
            async with db.begin_nested():
                db.add(event_model)
                await db.flush()
        except IntegrityError as exc:
            if normalized_request_id is None:
                raise LiveOrderControlUnavailableError(
                    "실주문 제어 감사 event를 저장하지 못했습니다.",
                    control=control,
                ) from exc
            raced_event = await self.get_event(db, normalized_request_id)
            if raced_event is None:
                raise LiveOrderControlUnavailableError(
                    "동시 제어 요청의 감사 event를 다시 조회하지 못했습니다.",
                    control=control,
                ) from exc
            return self._resolve_existing_request(
                control=control,
                event=raced_event,
                request_fingerprint=normalized_fingerprint,
            )

        control_model.mode = target_mode
        control_model.active_liquidation_operation_id = active_liquidation_operation_id
        control_model.generation = next_generation
        control_model.version += 1
        control_model.reason_code = reason_code
        control_model.reason_text = reason_text
        control_model.changed_source = source
        control_model.changed_actor_ref = actor_ref
        control_model.updated_at = now
        if target_mode == LIVE_ORDER_MODE_ARMED:
            control_model.armed_at = now
        elif target_mode == LIVE_ORDER_MODE_BLOCK_ALL:
            control_model.blocked_at = now
        await db.flush()

        return LiveOrderControlTransitionResult(
            control=self._control_to_record(control_model),
            event=self._event_to_record(event_model),
            replayed=False,
            permission_scope_changed=permission_scope_changed,
        )

    async def _get_control_model(
        self,
        db: AsyncSession,
        *,
        broker: str,
        account_scope: str,
        for_update: bool,
    ) -> LiveOrderControl | None:
        statement = select(LiveOrderControl).where(
            LiveOrderControl.broker == broker,
            LiveOrderControl.account_scope == account_scope,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    def _resolve_existing_request(
        self,
        *,
        control: LiveOrderControlRecord,
        event: LiveOrderControlEventRecord,
        request_fingerprint: str | None,
    ) -> LiveOrderControlTransitionResult:
        if event.control_id != control.id or event.request_fingerprint != request_fingerprint:
            raise LiveOrderControlIdempotencyConflictError(
                control=control,
                event=event,
            )
        if event.generation != control.generation:
            raise LiveOrderControlRequestSupersededError(
                control=control,
                event=event,
            )
        if event.to_mode != control.mode:
            raise LiveOrderControlUnavailableError(
                "현재 제어 상태와 감사 event의 상태가 일치하지 않습니다.",
                control=control,
                event=event,
            )
        if control.mode == LIVE_ORDER_MODE_EXIT_ONLY:
            if event.liquidation_operation_id != control.active_liquidation_operation_id:
                raise LiveOrderControlUnavailableError(
                    "현재 EXIT_ONLY 권한과 감사 event의 청산 operation이 일치하지 않습니다.",
                    control=control,
                    event=event,
                )
        elif control.active_liquidation_operation_id is not None:
            raise LiveOrderControlUnavailableError(
                "현재 제어 mode와 활성 청산 operation 상태가 일치하지 않습니다.",
                control=control,
                event=event,
            )
        return LiveOrderControlTransitionResult(
            control=control,
            event=event,
            replayed=True,
            permission_scope_changed=False,
        )

    @staticmethod
    def _control_to_record(model: LiveOrderControl) -> LiveOrderControlRecord:
        return LiveOrderControlRecord(
            id=model.id,
            broker=model.broker,
            account_scope=model.account_scope,
            mode=model.mode,
            active_liquidation_operation_id=model.active_liquidation_operation_id,
            generation=model.generation,
            version=model.version,
            reason_code=model.reason_code,
            reason_text=model.reason_text,
            changed_source=model.changed_source,
            changed_actor_ref=model.changed_actor_ref,
            armed_at=model.armed_at,
            blocked_at=model.blocked_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _event_to_record(model: LiveOrderControlEvent) -> LiveOrderControlEventRecord:
        return LiveOrderControlEventRecord(
            id=model.id,
            control_id=model.control_id,
            generation=model.generation,
            request_id=model.request_id,
            request_fingerprint=model.request_fingerprint,
            action=model.action,
            from_mode=model.from_mode,
            to_mode=model.to_mode,
            reason_code=model.reason_code,
            reason_text=model.reason_text,
            source=model.source,
            actor_ref=model.actor_ref,
            liquidation_operation_id=model.liquidation_operation_id,
            created_at=model.created_at,
        )
