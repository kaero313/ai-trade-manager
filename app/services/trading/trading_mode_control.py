from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.live_order_control_repository import (
    CONTROL_SOURCE_REST,
    LIVE_ORDER_MODE_BLOCK_ALL,
    LiveOrderControlRepository,
)
from app.db.trading_mode_repository import (
    TRADING_MODE_ACTION_LIVE_ENABLED,
    TRADING_MODE_ACTION_PAPER_CONFIRMED,
    TRADING_MODE_LIVE,
    TRADING_MODE_PAPER,
    TRADING_MODE_SOURCE_REST,
    TradingModeRepository,
    TradingModeStatusRecord,
    TradingModeTransitionError,
    TradingModeTransitionResult,
    build_trading_mode_request_fingerprint,
)
from app.models.schemas import TradingModeStatus
from app.services.trading.admin_reauth import (
    ADMIN_REAUTH_PURPOSE_ENABLE_LIVE_TRADING,
    AdminReauthClaims,
    AdminReauthError,
    verify_admin_reauth_proof,
)
from app.services.trading.live_order_control import (
    BlockLiveOrdersCommand,
    LiveOrderControlService,
    LiveOrderControlServiceError,
)
from app.services.trading.live_order_submission_barrier import (
    LiveOrderSubmissionBarrierError,
    LiveOrderSubmissionBarrierProtocol,
)

ENABLE_LIVE_TRADING_CONFIRMATION = "ENABLE_LIVE_TRADING"
_FAIL_CLOSED_REASON = "거래 모드 제어 원장과 mirror를 확인할 수 없어 paper로 표시합니다."
_ResultT = TypeVar("_ResultT")


class TradingModeControlServiceError(RuntimeError):
    error_code = "TRADING_MODE_STATE_UNAVAILABLE"

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code


class TradingModeControlPolicyError(TradingModeControlServiceError):
    """현재 운영 상태가 요청한 거래 모드 전환을 허용하지 않음."""


@dataclass(frozen=True, slots=True)
class EnableLiveTradingModeCommand:
    request_id: UUID | str
    expected_version: int
    expected_gate_generation: int
    expected_gate_version: int
    reason_text: str
    confirmation: str
    reauth_proof: str
    source: str = TRADING_MODE_SOURCE_REST
    actor_ref: str | None = "rest-admin"


@dataclass(frozen=True, slots=True)
class EnablePaperTradingModeCommand:
    request_id: UUID | str
    expected_version: int
    reason_text: str
    source: str = TRADING_MODE_SOURCE_REST
    actor_ref: str | None = "rest-admin"


def _require_uuid4(value: UUID | str) -> UUID:
    try:
        parsed = UUID(str(value).strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise TradingModeControlPolicyError(
            "Idempotency-Key는 UUID v4 형식이어야 합니다.",
            error_code="TRADING_MODE_IDEMPOTENCY_KEY_INVALID",
        ) from exc
    if parsed.version != 4:
        raise TradingModeControlPolicyError(
            "Idempotency-Key는 UUID v4 형식이어야 합니다.",
            error_code="TRADING_MODE_IDEMPOTENCY_KEY_INVALID",
        )
    return parsed


def _require_reason(value: str) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if len(normalized) < 10:
        raise TradingModeControlPolicyError(
            "거래 모드 전환 사유는 공백을 제외하고 10자 이상이어야 합니다.",
            error_code="TRADING_MODE_REASON_INVALID",
        )
    return normalized


def _live_request_fingerprint(
    *,
    base_fingerprint: str,
    expected_gate_generation: int,
    expected_gate_version: int,
) -> str:
    canonical = json.dumps(
        {
            "base_fingerprint": base_fingerprint,
            "expected_gate_generation": expected_gate_generation,
            "expected_gate_version": expected_gate_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _paper_stop_request_id(request_id: UUID) -> UUID:
    digest = bytearray(
        hashlib.sha256(
            f"ai-trade-manager:trading-mode:paper-stop:{request_id}".encode("utf-8")
        ).digest()[:16]
    )
    digest[6] = (digest[6] & 0x0F) | 0x40
    digest[8] = (digest[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(digest))


def to_trading_mode_status(status: TradingModeStatusRecord) -> TradingModeStatus:
    control = status.control
    if status.state_available and control is not None:
        return TradingModeStatus(
            mode=status.mode,
            version=control.version,
            reason_code=control.reason_code,
            reason=control.reason_text,
            source=control.changed_source,
            actor_ref=control.changed_actor_ref,
            changed_at=control.changed_at,
            state_available=True,
            unavailable_reason=None,
            mirror_consistent=status.mirror_consistent,
        )

    return TradingModeStatus(
        mode=TRADING_MODE_PAPER,
        version=control.version if control is not None else 0,
        reason_code="TRADING_MODE_STATE_UNAVAILABLE",
        reason=_FAIL_CLOSED_REASON,
        source=control.changed_source if control is not None else "SYSTEM",
        actor_ref=control.changed_actor_ref if control is not None else None,
        changed_at=control.changed_at if control is not None else None,
        state_available=False,
        unavailable_reason=status.unavailable_reason,
        mirror_consistent=False,
    )


class TradingModeControlService:
    """거래 모드 전환을 실주문 제출 배리어와 동일한 직렬화 경계에서 처리한다."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        barrier: LiveOrderSubmissionBarrierProtocol,
        *,
        repository: TradingModeRepository | None = None,
        live_order_repository: LiveOrderControlRepository | None = None,
        live_order_control_service: LiveOrderControlService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._barrier = barrier
        self._repository = repository or TradingModeRepository()
        self._live_order_repository = live_order_repository or LiveOrderControlRepository()
        self._live_order_control_service = live_order_control_service or LiveOrderControlService(
            barrier=barrier
        )
        self._clock = clock or (lambda: datetime.now(UTC))

    async def status(self, db: AsyncSession) -> TradingModeStatus:
        try:
            return to_trading_mode_status(await self._repository.status(db))
        except Exception:
            return TradingModeStatus(
                unavailable_reason="TRADING_MODE_STATUS_QUERY_FAILED"
            )

    async def enable_live(
        self,
        command: EnableLiveTradingModeCommand,
    ) -> TradingModeTransitionResult:
        request_id = _require_uuid4(command.request_id)
        reason_text = _require_reason(command.reason_text)
        if command.confirmation != ENABLE_LIVE_TRADING_CONFIRMATION:
            raise TradingModeControlPolicyError(
                f"live 전환 확인 문구는 {ENABLE_LIVE_TRADING_CONFIRMATION}여야 합니다.",
                error_code="TRADING_MODE_CONFIRMATION_INVALID",
            )
        if (
            command.expected_version < 1
            or command.expected_gate_generation < 1
            or command.expected_gate_version < 1
        ):
            raise TradingModeControlPolicyError(
                "live 전환에는 양수 expected mode/Gate snapshot이 필요합니다.",
                error_code="TRADING_MODE_VERSION_CONFLICT",
            )

        claims = verify_admin_reauth_proof(
            command.reauth_proof,
            expected_purpose=ADMIN_REAUTH_PURPOSE_ENABLE_LIVE_TRADING,
            allow_expired=True,
            now=self._clock(),
        )
        base_fingerprint = build_trading_mode_request_fingerprint(
            action=TRADING_MODE_ACTION_LIVE_ENABLED,
            expected_version=command.expected_version,
            target_mode=TRADING_MODE_LIVE,
            reason_code="OPERATOR_ENABLE_LIVE",
            reason_text=reason_text,
            source=command.source,
            actor_ref=command.actor_ref,
            confirmation=command.confirmation,
            reauth_jti=claims.jti,
        )
        fingerprint = _live_request_fingerprint(
            base_fingerprint=base_fingerprint,
            expected_gate_generation=command.expected_gate_generation,
            expected_gate_version=command.expected_gate_version,
        )

        async def operation(db: AsyncSession) -> TradingModeTransitionResult:
            existing = await self._repository.get_event(db, request_id)
            if existing is None:
                self._require_unexpired_reauth(claims)
                await self._assert_live_preconditions(db, command)
                # 배리어 획득과 여러 precondition 쿼리 중 TTL이 끝날 수 있으므로
                # 실제 control/mirror mutation 직전에 다시 검증한다.
                self._require_unexpired_reauth(claims)
            return await self._repository.transition(
                db,
                request_id=request_id,
                request_fingerprint=fingerprint,
                expected_version=command.expected_version,
                target_mode=TRADING_MODE_LIVE,
                action=TRADING_MODE_ACTION_LIVE_ENABLED,
                reason_code="OPERATOR_ENABLE_LIVE",
                reason_text=reason_text,
                source=command.source,
                actor_ref=command.actor_ref,
                reauth_jti=claims.jti,
            )

        return await self._run_exclusive(operation)

    async def enable_paper(
        self,
        command: EnablePaperTradingModeCommand,
    ) -> TradingModeTransitionResult:
        request_id = _require_uuid4(command.request_id)
        reason_text = _require_reason(command.reason_text)
        if command.expected_version < 1:
            raise TradingModeControlPolicyError(
                "paper 전환에는 양수 expected_version이 필요합니다.",
                error_code="TRADING_MODE_VERSION_CONFLICT",
            )
        fingerprint = build_trading_mode_request_fingerprint(
            action=TRADING_MODE_ACTION_PAPER_CONFIRMED,
            expected_version=command.expected_version,
            target_mode=TRADING_MODE_PAPER,
            reason_code="OPERATOR_ENABLE_PAPER",
            reason_text=reason_text,
            source=command.source,
            actor_ref=command.actor_ref,
            confirmation=None,
            reauth_jti=None,
        )

        async with self._session_factory() as db:
            existing = await self._repository.get_event(db, request_id)
            await db.commit()
        if existing is None:
            await self._live_order_control_service.stop_bot(
                BlockLiveOrdersCommand(
                    request_id=_paper_stop_request_id(request_id),
                    reason_code="TRADING_MODE_PAPER",
                    reason_text=reason_text,
                    source=CONTROL_SOURCE_REST,
                    actor_ref=command.actor_ref,
                )
            )

        async def operation(db: AsyncSession) -> TradingModeTransitionResult:
            if existing is None:
                gate = await self._live_order_repository.get_submission_gate_snapshot(db)
                if (
                    gate.bot_active
                    or gate.control is None
                    or gate.control.mode != LIVE_ORDER_MODE_BLOCK_ALL
                ):
                    raise TradingModeControlPolicyError(
                        "paper 전환 전 런타임 정지와 Gate BLOCK_ALL을 확인할 수 없습니다.",
                        error_code="TRADING_MODE_STOP_INCOMPLETE",
                    )
            return await self._repository.transition(
                db,
                request_id=request_id,
                request_fingerprint=fingerprint,
                expected_version=command.expected_version,
                target_mode=TRADING_MODE_PAPER,
                action=TRADING_MODE_ACTION_PAPER_CONFIRMED,
                reason_code="OPERATOR_ENABLE_PAPER",
                reason_text=reason_text,
                source=command.source,
                actor_ref=command.actor_ref,
                reauth_jti=None,
            )

        return await self._run_exclusive(operation)

    async def _assert_live_preconditions(
        self,
        db: AsyncSession,
        command: EnableLiveTradingModeCommand,
    ) -> None:
        mode_status = await self._repository.status(db, for_update=True)
        if (
            not mode_status.state_available
            or mode_status.control is None
            or mode_status.mode != TRADING_MODE_PAPER
        ):
            raise TradingModeControlPolicyError(
                "정상적인 paper 상태에서만 live로 전환할 수 있습니다.",
                error_code="TRADING_MODE_STATE_UNAVAILABLE",
            )
        gate = await self._live_order_repository.get_submission_gate_snapshot(db)
        if not gate.rollout_enabled:
            raise TradingModeControlPolicyError(
                "실주문 v2 rollout이 비활성화되어 live로 전환할 수 없습니다.",
                error_code="LIVE_ORDER_V2_DISABLED",
            )
        if gate.bot_active:
            raise TradingModeControlPolicyError(
                "봇 런타임을 정지한 뒤 live로 전환해야 합니다.",
                error_code="BOT_ACTIVE",
            )
        control = gate.control
        if control is None:
            raise TradingModeControlPolicyError(
                "실주문 Gate 상태를 확인할 수 없습니다.",
                error_code="ORDER_GATE_STATE_UNAVAILABLE",
            )
        if (
            control.generation != command.expected_gate_generation
            or control.version != command.expected_gate_version
        ):
            raise TradingModeControlPolicyError(
                "실주문 Gate snapshot이 요청 시점 이후 변경되었습니다.",
                error_code="TRADING_MODE_GATE_CONFLICT",
            )
        if control.mode != LIVE_ORDER_MODE_BLOCK_ALL:
            raise TradingModeControlPolicyError(
                "Gate가 BLOCK_ALL일 때만 live로 전환할 수 있습니다.",
                error_code="LIVE_ORDER_GATE_BLOCKED",
            )
        if control.active_liquidation_operation_id is not None:
            raise TradingModeControlPolicyError(
                "활성 청산 operation이 있어 live로 전환할 수 없습니다.",
                error_code="ACTIVE_LIQUIDATION_EXISTS",
            )
        if await self._live_order_repository.has_active_liquidation_operation(db):
            raise TradingModeControlPolicyError(
                "미종결 또는 활성 권한 청산 operation이 있어 live로 전환할 수 없습니다.",
                error_code="ACTIVE_LIQUIDATION_EXISTS",
            )
        if await self._live_order_repository.has_blocking_intent(
            db,
            include_prepared=True,
        ):
            raise TradingModeControlPolicyError(
                "미해결 주문 intent가 있어 live로 전환할 수 없습니다.",
                error_code="BLOCKING_ORDER_INTENT_EXISTS",
            )

    def _require_unexpired_reauth(self, claims: AdminReauthClaims) -> None:
        current = self._clock().astimezone(UTC)
        if claims.expired or current >= claims.expires_at:
            raise AdminReauthError(
                "관리자 재인증 proof가 만료되었습니다.",
                error_code="ADMIN_REAUTH_EXPIRED",
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
            AdminReauthError,
            TradingModeControlServiceError,
            TradingModeTransitionError,
            LiveOrderControlServiceError,
            LiveOrderSubmissionBarrierError,
        ):
            raise
        except Exception as exc:
            raise TradingModeControlServiceError(
                "거래 모드 전환 경계를 처리하지 못했습니다."
            ) from exc
