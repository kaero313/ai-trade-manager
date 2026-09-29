from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import TRADING_MODE_KEY
from app.models.domain import (
    SystemConfig,
    TradingModeControl,
    TradingModeControlEvent,
)

TRADING_MODE_CONTROL_ID: Final = 1
TRADING_MODE_PAPER: Final = "paper"
TRADING_MODE_LIVE: Final = "live"
TRADING_MODES: Final = frozenset({TRADING_MODE_PAPER, TRADING_MODE_LIVE})

TRADING_MODE_ACTION_INITIALIZED: Final = "INITIALIZED"
TRADING_MODE_ACTION_LIVE_ENABLED: Final = "LIVE_ENABLED"
TRADING_MODE_ACTION_PAPER_CONFIRMED: Final = "PAPER_CONFIRMED"
TRADING_MODE_ACTIONS: Final = frozenset(
    {
        TRADING_MODE_ACTION_INITIALIZED,
        TRADING_MODE_ACTION_LIVE_ENABLED,
        TRADING_MODE_ACTION_PAPER_CONFIRMED,
    }
)

TRADING_MODE_SOURCE_REST: Final = "REST"
TRADING_MODE_SOURCE_SLACK: Final = "SLACK"
TRADING_MODE_SOURCE_TELEGRAM: Final = "TELEGRAM"
TRADING_MODE_SOURCE_SYSTEM: Final = "SYSTEM"
TRADING_MODE_SOURCES: Final = frozenset(
    {
        TRADING_MODE_SOURCE_REST,
        TRADING_MODE_SOURCE_SLACK,
        TRADING_MODE_SOURCE_TELEGRAM,
        TRADING_MODE_SOURCE_SYSTEM,
    }
)

_SHA256_HEX_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class TradingModeControlRecord:
    id: int
    mode: str
    version: int
    reason_code: str
    reason_text: str
    changed_source: str
    changed_actor_ref: str | None
    changed_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TradingModeControlEventRecord:
    id: int
    control_id: int
    version: int
    request_id: str | None
    request_fingerprint: str | None
    reauth_jti: str | None
    action: str
    from_mode: str | None
    to_mode: str
    reason_code: str
    reason_text: str
    source: str
    actor_ref: str | None
    legacy_raw_value: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TradingModeStatusRecord:
    mode: str
    state_available: bool
    control: TradingModeControlRecord | None
    mirror_value: str | None
    unavailable_reason: str | None = None

    @property
    def mirror_consistent(self) -> bool:
        return (
            self.state_available
            and self.control is not None
            and self.mirror_value == self.control.mode
        )


@dataclass(frozen=True, slots=True)
class TradingModeTransitionResult:
    control: TradingModeControlRecord
    event: TradingModeControlEventRecord
    replayed: bool


class TradingModeTransitionError(RuntimeError):
    error_code = "TRADING_MODE_STATE_UNAVAILABLE"

    def __init__(
        self,
        message: str,
        *,
        control: TradingModeControlRecord | None = None,
        event: TradingModeControlEventRecord | None = None,
    ) -> None:
        super().__init__(message)
        self.control = control
        self.event = event


class TradingModeStateUnavailableError(TradingModeTransitionError):
    error_code = "TRADING_MODE_STATE_UNAVAILABLE"


class TradingModeVersionConflictError(TradingModeTransitionError):
    error_code = "TRADING_MODE_VERSION_CONFLICT"

    def __init__(self, *, expected_version: int, control: TradingModeControlRecord) -> None:
        super().__init__(
            "거래 모드 version이 요청 시점 이후 변경되었습니다.",
            control=control,
        )
        self.expected_version = expected_version
        self.actual_version = control.version


class TradingModeIdempotencyConflictError(TradingModeTransitionError):
    error_code = "TRADING_MODE_IDEMPOTENCY_CONFLICT"

    def __init__(
        self,
        *,
        control: TradingModeControlRecord,
        event: TradingModeControlEventRecord,
    ) -> None:
        super().__init__(
            "동일한 거래 모드 요청 키에 다른 payload가 사용되었습니다.",
            control=control,
            event=event,
        )


class TradingModeRequestSupersededError(TradingModeTransitionError):
    error_code = "TRADING_MODE_REQUEST_SUPERSEDED"

    def __init__(
        self,
        *,
        control: TradingModeControlRecord,
        event: TradingModeControlEventRecord,
    ) -> None:
        super().__init__(
            "거래 모드 요청 성공 이후 더 새로운 상태 전이가 적용되었습니다.",
            control=control,
            event=event,
        )


class TradingModeReauthConflictError(TradingModeTransitionError):
    error_code = "TRADING_MODE_REAUTH_CONFLICT"

    def __init__(
        self,
        *,
        control: TradingModeControlRecord,
        event: TradingModeControlEventRecord,
    ) -> None:
        super().__init__(
            "이미 사용된 관리자 재인증 증명은 다시 사용할 수 없습니다.",
            control=control,
            event=event,
        )


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


def _normalize_uuid4(value: UUID | str, *, field_name: str) -> str:
    try:
        parsed = UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name}는 UUID v4 형식이어야 합니다.") from exc
    if parsed.version != 4:
        raise ValueError(f"{field_name}는 UUID v4 형식이어야 합니다.")
    return str(parsed)


def build_trading_mode_request_fingerprint(
    *,
    action: str,
    expected_version: int,
    target_mode: str,
    reason_code: str,
    reason_text: str,
    source: str,
    actor_ref: str | None,
    confirmation: str | None = None,
    reauth_jti: str | None = None,
) -> str:
    """보안 관련 전환 payload를 정규화한 SHA-256 fingerprint를 생성합니다."""
    payload = {
        "action": action.strip().upper(),
        "actor_ref": _normalize_optional_text(actor_ref),
        "confirmation": _normalize_optional_text(confirmation),
        "expected_version": expected_version,
        "reason_code": reason_code.strip().upper(),
        "reason_text": _normalize_optional_text(reason_text),
        "reauth_jti": _normalize_optional_text(reauth_jti),
        "source": source.strip().upper(),
        "target_mode": target_mode.strip().lower(),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TradingModeRepository:
    """거래 모드 SSOT와 legacy mirror를 한 트랜잭션에서 관리합니다."""

    async def get_control(
        self,
        db: AsyncSession,
        *,
        for_update: bool = False,
    ) -> TradingModeControlRecord | None:
        statement = select(TradingModeControl).where(
            TradingModeControl.id == TRADING_MODE_CONTROL_ID
        )
        if for_update:
            statement = statement.with_for_update()
        model = await db.scalar(statement)
        return self._control_to_record(model) if model is not None else None

    async def get_event(
        self,
        db: AsyncSession,
        request_id: UUID | str,
    ) -> TradingModeControlEventRecord | None:
        normalized_request_id = _normalize_uuid4(request_id, field_name="request_id")
        model = await db.scalar(
            select(TradingModeControlEvent).where(
                TradingModeControlEvent.request_id == normalized_request_id
            )
        )
        return self._event_to_record(model) if model is not None else None

    async def get_latest_event(
        self,
        db: AsyncSession,
        control_id: int = TRADING_MODE_CONTROL_ID,
    ) -> TradingModeControlEventRecord | None:
        model = await db.scalar(
            select(TradingModeControlEvent)
            .where(TradingModeControlEvent.control_id == control_id)
            .order_by(TradingModeControlEvent.version.desc())
            .limit(1)
        )
        return self._event_to_record(model) if model is not None else None

    async def status(
        self,
        db: AsyncSession,
        *,
        for_update: bool = False,
    ) -> TradingModeStatusRecord:
        control_statement = select(TradingModeControl).where(
            TradingModeControl.id == TRADING_MODE_CONTROL_ID
        )
        mirror_statement = select(SystemConfig).where(
            SystemConfig.config_key == TRADING_MODE_KEY
        )
        if for_update:
            control_statement = control_statement.with_for_update()
            mirror_statement = mirror_statement.with_for_update()

        control_model = await db.scalar(control_statement)
        mirror_model = await db.scalar(mirror_statement)
        control = (
            self._control_to_record(control_model) if control_model is not None else None
        )
        mirror_value = mirror_model.config_value if mirror_model is not None else None

        if control is None:
            return TradingModeStatusRecord(
                mode=TRADING_MODE_PAPER,
                state_available=False,
                control=None,
                mirror_value=mirror_value,
                unavailable_reason="TRADING_MODE_CONTROL_MISSING",
            )
        if control.mode not in TRADING_MODES:
            return TradingModeStatusRecord(
                mode=TRADING_MODE_PAPER,
                state_available=False,
                control=control,
                mirror_value=mirror_value,
                unavailable_reason="TRADING_MODE_CONTROL_INVALID",
            )
        if mirror_model is None:
            return TradingModeStatusRecord(
                mode=TRADING_MODE_PAPER,
                state_available=False,
                control=control,
                mirror_value=None,
                unavailable_reason="TRADING_MODE_MIRROR_MISSING",
            )
        if mirror_value not in TRADING_MODES:
            return TradingModeStatusRecord(
                mode=TRADING_MODE_PAPER,
                state_available=False,
                control=control,
                mirror_value=mirror_value,
                unavailable_reason="TRADING_MODE_MIRROR_INVALID",
            )
        if mirror_value != control.mode:
            return TradingModeStatusRecord(
                mode=TRADING_MODE_PAPER,
                state_available=False,
                control=control,
                mirror_value=mirror_value,
                unavailable_reason="TRADING_MODE_MIRROR_MISMATCH",
            )
        return TradingModeStatusRecord(
            mode=control.mode,
            state_available=True,
            control=control,
            mirror_value=mirror_value,
        )

    async def transition(
        self,
        db: AsyncSession,
        *,
        request_id: UUID | str,
        request_fingerprint: str,
        expected_version: int,
        target_mode: str,
        action: str,
        reason_code: str,
        reason_text: str,
        source: str,
        actor_ref: str | None,
        reauth_jti: UUID | str | None = None,
    ) -> TradingModeTransitionResult:
        """row lock과 CAS 아래 control·mirror·event를 원자적으로 전환합니다.

        이 메서드는 commit하지 않습니다. 호출자가 소유한 ``AsyncSession.begin()`` 경계에서
        호출해야 control, mirror, 감사 event가 하나의 트랜잭션으로 확정됩니다.
        """
        normalized_request_id = _normalize_uuid4(request_id, field_name="request_id")
        normalized_fingerprint = request_fingerprint.strip().lower()
        if _SHA256_HEX_PATTERN.fullmatch(normalized_fingerprint) is None:
            raise ValueError("request_fingerprint는 SHA-256 소문자 hex여야 합니다.")
        if expected_version < 1:
            raise ValueError("expected_version은 1 이상이어야 합니다.")

        normalized_mode = target_mode.strip().lower()
        normalized_action = action.strip().upper()
        normalized_source = source.strip().upper()
        normalized_reason_code = reason_code.strip().upper()
        normalized_reason_text = reason_text.strip()
        normalized_actor_ref = _normalize_optional_text(actor_ref)
        normalized_reauth_jti = (
            _normalize_uuid4(reauth_jti, field_name="reauth_jti")
            if reauth_jti is not None
            else None
        )
        self._validate_transition_shape(
            target_mode=normalized_mode,
            action=normalized_action,
            source=normalized_source,
            reason_code=normalized_reason_code,
            reason_text=normalized_reason_text,
            reauth_jti=normalized_reauth_jti,
        )

        status = await self.status(db, for_update=True)
        mirror_repair_allowed = (
            normalized_mode == TRADING_MODE_PAPER
            and status.control is not None
            and status.control.mode in TRADING_MODES
            and status.unavailable_reason
            in {
                "TRADING_MODE_MIRROR_MISSING",
                "TRADING_MODE_MIRROR_INVALID",
                "TRADING_MODE_MIRROR_MISMATCH",
            }
        )
        if (
            (not status.state_available and not mirror_repair_allowed)
            or status.control is None
        ):
            raise TradingModeStateUnavailableError(
                "거래 모드 SSOT와 legacy mirror가 일치하지 않습니다.",
                control=status.control,
            )
        control = status.control

        existing_event = await self.get_event(db, normalized_request_id)
        if existing_event is not None:
            replay = self._resolve_existing_request(
                control=control,
                event=existing_event,
                request_fingerprint=normalized_fingerprint,
            )
            if mirror_repair_allowed:
                await self._set_mirror(
                    db,
                    previous_value=status.mirror_value,
                    target_mode=TRADING_MODE_PAPER,
                )
            return replay

        if expected_version != control.version:
            raise TradingModeVersionConflictError(
                expected_version=expected_version,
                control=control,
            )
        self._validate_current_transition(
            control=control,
            target_mode=normalized_mode,
            action=normalized_action,
        )

        if normalized_reauth_jti is not None:
            used_reauth = await db.scalar(
                select(TradingModeControlEvent).where(
                    TradingModeControlEvent.reauth_jti == normalized_reauth_jti
                )
            )
            if used_reauth is not None:
                raise TradingModeReauthConflictError(
                    control=control,
                    event=self._event_to_record(used_reauth),
                )

        next_version = control.version + 1
        updated_model = await db.scalar(
            update(TradingModeControl)
            .where(
                TradingModeControl.id == control.id,
                TradingModeControl.version == control.version,
            )
            .values(
                mode=normalized_mode,
                version=next_version,
                reason_code=normalized_reason_code,
                reason_text=normalized_reason_text,
                changed_source=normalized_source,
                changed_actor_ref=normalized_actor_ref,
                changed_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            .returning(TradingModeControl)
        )
        if updated_model is None:
            raise TradingModeVersionConflictError(
                expected_version=expected_version,
                control=control,
            )

        await self._set_mirror(
            db,
            previous_value=status.mirror_value,
            target_mode=normalized_mode,
        )

        event_model = TradingModeControlEvent(
            control_id=control.id,
            version=next_version,
            request_id=normalized_request_id,
            request_fingerprint=normalized_fingerprint,
            reauth_jti=normalized_reauth_jti,
            action=normalized_action,
            from_mode=control.mode,
            to_mode=normalized_mode,
            reason_code=normalized_reason_code,
            reason_text=normalized_reason_text,
            source=normalized_source,
            actor_ref=normalized_actor_ref,
            legacy_raw_value=None,
        )
        db.add(event_model)
        await db.flush()
        await db.refresh(event_model)

        return TradingModeTransitionResult(
            control=self._control_to_record(updated_model),
            event=self._event_to_record(event_model),
            replayed=False,
        )

    async def _set_mirror(
        self,
        db: AsyncSession,
        *,
        previous_value: str | None,
        target_mode: str,
    ) -> None:
        if previous_value is None:
            statement = postgresql_insert(SystemConfig).values(
                config_key=TRADING_MODE_KEY,
                config_value=target_mode,
                description="거래 실행 모드 legacy mirror(paper/live)",
            )
            await db.execute(
                statement.on_conflict_do_update(
                    index_elements=[SystemConfig.config_key],
                    set_={
                        "config_value": target_mode,
                        "version": SystemConfig.version + 1,
                    },
                )
            )
            return

        mirror_result = await db.execute(
            update(SystemConfig)
            .where(
                SystemConfig.config_key == TRADING_MODE_KEY,
                SystemConfig.config_value == previous_value,
            )
            .values(
                config_value=target_mode,
                version=SystemConfig.version + 1,
            )
        )
        if mirror_result.rowcount != 1:
            raise TradingModeStateUnavailableError(
                "거래 모드 legacy mirror CAS에 실패했습니다."
            )

    @staticmethod
    def _validate_transition_shape(
        *,
        target_mode: str,
        action: str,
        source: str,
        reason_code: str,
        reason_text: str,
        reauth_jti: str | None,
    ) -> None:
        if target_mode not in TRADING_MODES:
            raise ValueError("target_mode는 paper 또는 live여야 합니다.")
        if action not in TRADING_MODE_ACTIONS - {TRADING_MODE_ACTION_INITIALIZED}:
            raise ValueError("운영 전환 action이 유효하지 않습니다.")
        if source not in TRADING_MODE_SOURCES:
            raise ValueError("거래 모드 전환 source가 유효하지 않습니다.")
        if not reason_code or not reason_text:
            raise ValueError("거래 모드 전환 사유는 비어 있을 수 없습니다.")
        if target_mode == TRADING_MODE_LIVE:
            if action != TRADING_MODE_ACTION_LIVE_ENABLED or reauth_jti is None:
                raise ValueError("live 전환에는 LIVE_ENABLED action과 reauth_jti가 필요합니다.")
        elif action != TRADING_MODE_ACTION_PAPER_CONFIRMED or reauth_jti is not None:
            raise ValueError("paper 전환에는 PAPER_CONFIRMED action만 사용할 수 있습니다.")

    @staticmethod
    def _validate_current_transition(
        *,
        control: TradingModeControlRecord,
        target_mode: str,
        action: str,
    ) -> None:
        if target_mode == TRADING_MODE_LIVE and control.mode != TRADING_MODE_PAPER:
            raise TradingModeStateUnavailableError(
                "live 전환은 정상적인 paper 상태에서만 허용됩니다.",
                control=control,
            )
        if target_mode == TRADING_MODE_LIVE and action != TRADING_MODE_ACTION_LIVE_ENABLED:
            raise TradingModeStateUnavailableError(
                "live 전환 action이 현재 상태와 일치하지 않습니다.",
                control=control,
            )
        if target_mode == TRADING_MODE_PAPER and action != TRADING_MODE_ACTION_PAPER_CONFIRMED:
            raise TradingModeStateUnavailableError(
                "paper 전환 action이 현재 상태와 일치하지 않습니다.",
                control=control,
            )

    @staticmethod
    def _resolve_existing_request(
        *,
        control: TradingModeControlRecord,
        event: TradingModeControlEventRecord,
        request_fingerprint: str,
    ) -> TradingModeTransitionResult:
        if event.control_id != control.id or event.request_fingerprint != request_fingerprint:
            raise TradingModeIdempotencyConflictError(control=control, event=event)
        if event.version != control.version or event.to_mode != control.mode:
            raise TradingModeRequestSupersededError(control=control, event=event)
        return TradingModeTransitionResult(
            control=control,
            event=event,
            replayed=True,
        )

    @staticmethod
    def _control_to_record(model: TradingModeControl) -> TradingModeControlRecord:
        return TradingModeControlRecord(
            id=model.id,
            mode=model.mode,
            version=model.version,
            reason_code=model.reason_code,
            reason_text=model.reason_text,
            changed_source=model.changed_source,
            changed_actor_ref=model.changed_actor_ref,
            changed_at=model.changed_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _event_to_record(model: TradingModeControlEvent) -> TradingModeControlEventRecord:
        return TradingModeControlEventRecord(
            id=model.id,
            control_id=model.control_id,
            version=model.version,
            request_id=model.request_id,
            request_fingerprint=model.request_fingerprint,
            reauth_jti=model.reauth_jti,
            action=model.action,
            from_mode=model.from_mode,
            to_mode=model.to_mode,
            reason_code=model.reason_code,
            reason_text=model.reason_text,
            source=model.source,
            actor_ref=model.actor_ref,
            legacy_raw_value=model.legacy_raw_value,
            created_at=model.created_at,
        )
