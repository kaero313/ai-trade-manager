from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.live_order_control_repository import (
    LIVE_ORDER_MODE_BLOCK_ALL,
    LiveOrderControlRepository,
)
from app.db.repository import get_or_create_bot_config
from app.db.session import engine
from app.db.trading_mode_repository import TradingModeRepository
from app.models.domain import BotConfig as BotConfigORM
from app.models.domain import LiquidationOperation
from app.models.schemas import BotConfig as BotConfigSchema
from app.models.schemas import BotStatus, LiveOrderGateStatus, TradingModeStatus
from app.services.trading.live_order_submission_barrier import (
    LiveOrderSubmissionBarrier,
    LiveOrderSubmissionBarrierProtocol,
)
from app.services.trading.trading_mode_control import to_trading_mode_status

_UNSET = object()
DEFAULT_IDLE_ACTION = "AI 엔진 대기 중..."
DEFAULT_START_ACTION = "AI 엔진 시작됨"
_FAIL_CLOSED_REASON = "실주문 제어 상태를 확인할 수 없어 안전하게 차단했습니다."


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_runtime_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise TypeError("런타임 시각은 datetime 또는 ISO-8601 문자열이어야 합니다.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _runtime_datetime_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _normalize_runtime_status(
    bot_config: BotConfigORM,
    *,
    is_running: bool,
) -> dict[str, Any]:
    latest_action = str(bot_config.runtime_latest_action or "").strip()
    if not latest_action:
        latest_action = DEFAULT_IDLE_ACTION if not is_running else DEFAULT_START_ACTION
    return {
        "last_heartbeat": _runtime_datetime_to_iso(bot_config.runtime_last_heartbeat),
        "last_error": bot_config.runtime_last_error,
        "latest_action": latest_action,
        "updated_at": _runtime_datetime_to_iso(bot_config.runtime_updated_at),
    }


async def update_bot_runtime_status(
    db: AsyncSession,
    *,
    last_heartbeat: str | None | object = _UNSET,
    last_error: str | None | object = _UNSET,
    latest_action: str | None | object = _UNSET,
    updated_at: str | None | object = _UNSET,
) -> BotConfigORM:
    bot_config = await get_or_create_bot_config(db)
    if last_heartbeat is not _UNSET:
        bot_config.runtime_last_heartbeat = _coerce_runtime_datetime(last_heartbeat)
    if last_error is not _UNSET:
        bot_config.runtime_last_error = None if last_error is None else str(last_error)
    if latest_action is not _UNSET:
        bot_config.runtime_latest_action = (
            None if latest_action is None else str(latest_action)
        )
    bot_config.runtime_updated_at = _coerce_runtime_datetime(
        updated_at if updated_at is not _UNSET else _utc_now()
    )
    await db.commit()
    await db.refresh(bot_config)
    return bot_config


def _fail_closed_order_gate() -> LiveOrderGateStatus:
    return LiveOrderGateStatus(
        mode=LIVE_ORDER_MODE_BLOCK_ALL,
        generation=0,
        version=0,
        reason_code="ORDER_GATE_STATE_UNAVAILABLE",
        reason=_FAIL_CLOSED_REASON,
        source="SYSTEM",
        changed_at=None,
        active_liquidation_operation_id=None,
        rollout_enabled=False,
        state_available=False,
    )


async def get_live_order_gate_status(
    db: AsyncSession,
    *,
    repository: LiveOrderControlRepository | None = None,
    suppress_repository_errors: bool = True,
) -> LiveOrderGateStatus:
    control_repository = repository or LiveOrderControlRepository()
    try:
        rollout_enabled = await control_repository.get_rollout_flag(db)
        control = await control_repository.get_control(db)
    except Exception:
        if not suppress_repository_errors:
            raise
        return _fail_closed_order_gate()

    if control is None:
        gate = _fail_closed_order_gate()
        return gate.model_copy(update={"rollout_enabled": rollout_enabled})

    return LiveOrderGateStatus(
        mode=control.mode,
        generation=control.generation,
        version=control.version,
        reason_code=control.reason_code,
        reason=control.reason_text,
        source=control.changed_source,
        changed_at=control.updated_at,
        active_liquidation_operation_id=control.active_liquidation_operation_id,
        rollout_enabled=rollout_enabled,
        state_available=True,
    )


async def get_trading_mode_status(
    db: AsyncSession,
    *,
    repository: TradingModeRepository | None = None,
    suppress_repository_errors: bool = True,
) -> TradingModeStatus:
    control_repository = repository or TradingModeRepository()
    try:
        return to_trading_mode_status(await control_repository.status(db))
    except Exception:
        if not suppress_repository_errors:
            raise
        return TradingModeStatus(
            unavailable_reason="TRADING_MODE_STATUS_QUERY_FAILED"
        )


def _to_bot_status(
    bot_config: BotConfigORM,
    order_gate: LiveOrderGateStatus,
    trading_mode: TradingModeStatus,
) -> BotStatus:
    is_running = bool(bot_config.is_active)
    runtime_status = _normalize_runtime_status(bot_config, is_running=is_running)
    return BotStatus(
        running=is_running,
        last_heartbeat=runtime_status.get("last_heartbeat"),
        last_error=runtime_status.get("last_error"),
        latest_action=str(runtime_status.get("latest_action") or DEFAULT_IDLE_ACTION),
        live_order_mode=order_gate.mode,
        live_order_generation=order_gate.generation,
        live_order_version=order_gate.version,
        live_order_reason_code=order_gate.reason_code,
        live_order_reason=order_gate.reason,
        live_order_source=order_gate.source,
        live_order_changed_at=order_gate.changed_at,
        live_order_active_liquidation_operation_id=(
            order_gate.active_liquidation_operation_id
        ),
        live_order_rollout_enabled=order_gate.rollout_enabled,
        live_order_state_available=order_gate.state_available,
        trading_mode=trading_mode.mode,
        trading_mode_version=trading_mode.version,
        trading_mode_reason_code=trading_mode.reason_code,
        trading_mode_reason=trading_mode.reason,
        trading_mode_source=trading_mode.source,
        trading_mode_actor_ref=trading_mode.actor_ref,
        trading_mode_changed_at=trading_mode.changed_at,
        trading_mode_state_available=trading_mode.state_available,
        trading_mode_unavailable_reason=trading_mode.unavailable_reason,
        trading_mode_mirror_consistent=trading_mode.mirror_consistent,
    )


async def get_bot_status(db: AsyncSession) -> BotStatus:
    bot_config = await get_or_create_bot_config(db)
    await db.refresh(bot_config)
    order_gate = await get_live_order_gate_status(db)
    trading_mode = await get_trading_mode_status(db)
    status = _to_bot_status(bot_config, order_gate, trading_mode)
    operation = None
    if order_gate.active_liquidation_operation_id is not None:
        operation = await db.get(
            LiquidationOperation,
            order_gate.active_liquidation_operation_id,
        )
    if operation is None:
        scalar = getattr(db, "scalar", None)
        if callable(scalar):
            operation = await scalar(
                select(LiquidationOperation)
                .where(
                    LiquidationOperation.broker == "UPBIT",
                    LiquidationOperation.account_scope == "primary",
                    LiquidationOperation.status.in_(("PREPARING", "IN_PROGRESS")),
                )
                .order_by(LiquidationOperation.id.asc())
                .limit(1)
            )
    if operation is None:
        return status
    remaining_summary = (
        operation.remaining_summary
        if isinstance(operation.remaining_summary, dict)
        else {}
    )
    return status.model_copy(
        update={
            "live_order_active_liquidation_operation_id": operation.id,
            "live_order_liquidation_status": operation.status,
            "live_order_liquidation_phase": operation.phase,
            "live_order_liquidation_remaining": int(
                remaining_summary.get("remaining", 0)
            ),
        }
    )


async def start_bot(
    db: AsyncSession,
    *,
    barrier: LiveOrderSubmissionBarrierProtocol | None = None,
) -> BotStatus:
    """live 전환과 같은 exclusive 제출 배리어에서 런타임 시작을 선형화한다."""
    submission_barrier = barrier or LiveOrderSubmissionBarrier(engine)
    async with submission_barrier.exclusive() as lease:
        async with lease.transaction() as control_db:
            bot_config = await control_db.get(BotConfigORM, 1, with_for_update=True)
            if bot_config is None:
                bot_config = BotConfigORM(
                    id=1,
                    config_json=BotConfigSchema().model_dump(),
                    is_active=False,
                )
                control_db.add(bot_config)
                await control_db.flush()

            bot_config.runtime_last_error = None
            bot_config.runtime_latest_action = DEFAULT_START_ACTION
            bot_config.runtime_updated_at = _utc_now()
            bot_config.is_active = True
            await control_db.flush()

    in_transaction = getattr(db, "in_transaction", None)
    if callable(in_transaction) and in_transaction():
        await db.rollback()
    return await get_bot_status(db)


async def stop_bot(db: AsyncSession) -> BotStatus:
    await get_or_create_bot_config(db)
    await db.execute(
        update(BotConfigORM)
        .where(BotConfigORM.id == 1)
        .values(
            is_active=False,
            runtime_latest_action=DEFAULT_IDLE_ACTION,
            runtime_updated_at=_utc_now(),
        )
    )
    await db.commit()
    bot_config = await db.get(BotConfigORM, 1)
    if bot_config is None:  # pragma: no cover - 바로 앞에서 singleton을 보장합니다.
        raise RuntimeError("봇 설정 singleton을 찾을 수 없습니다.")
    await db.refresh(bot_config)
    order_gate = await get_live_order_gate_status(db)
    trading_mode = await get_trading_mode_status(db)
    return _to_bot_status(bot_config, order_gate, trading_mode)
