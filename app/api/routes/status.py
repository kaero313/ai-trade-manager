from collections.abc import Awaitable
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin_token, require_reentered_admin_token
from app.db.live_order_control_repository import (
    CONTROL_SOURCE_REST,
    LiveOrderControlTransitionError,
)
from app.db.trading_mode_repository import TradingModeTransitionError
from app.db.session import AsyncSessionLocal, engine, get_db
from app.models.schemas import (
    ArmLiveOrderGateRequest,
    AdminReauthRequest,
    AdminReauthResponse,
    BlockLiveOrderGateRequest,
    BotStatus,
    EnableLiveTradingModeRequest,
    EnablePaperTradingModeRequest,
    LiquidateAllRequest,
    LiquidationOperationResponse,
    LiveOrderGateStatus,
    TradingModeStatus,
)
from app.services.bot_service import (
    get_bot_status,
    get_live_order_gate_status,
    get_trading_mode_status,
    start_bot,
    stop_bot as legacy_stop_bot,
)
from app.services.brokers.factory import BrokerFactory
from app.services.trading.liquidation import LIQUIDATION_TERMINAL_STATUSES
from app.services.trading.liquidation import LiquidationCoordinator
from app.services.trading.liquidation_v2 import build_liquidation_request_fingerprint
from app.services.trading.live_order_control import (
    ArmLiveOrdersCommand,
    BlockLiveOrdersCommand,
    LiveOrderControlService,
    LiveOrderControlServiceError,
)
from app.services.trading.live_order_submission_barrier import (
    LiveOrderSubmissionBarrier,
    LiveOrderSubmissionBarrierError,
)
from app.services.trading.admin_reauth import (
    AdminReauthError,
    issue_admin_reauth_proof,
)
from app.services.trading.trading_mode_control import (
    EnableLiveTradingModeCommand,
    EnablePaperTradingModeCommand,
    TradingModeControlService,
    TradingModeControlServiceError,
)

router = APIRouter()

# 기존 직접 호출 테스트와 외부 import 호환용입니다. REST 정지/청산 경로에서는 호출하지 않습니다.
stop_bot = legacy_stop_bot

_CONFLICT_ERROR_CODES = frozenset(
    {
        "ORDER_GATE_GENERATION_CONFLICT",
        "ORDER_GATE_IDEMPOTENCY_CONFLICT",
        "ORDER_GATE_REQUEST_SUPERSEDED",
        "EMERGENCY_AUTH_REVOKED",
        "ACTIVE_LIQUIDATION_EXISTS",
        "LIQUIDATION_IDEMPOTENCY_CONFLICT",
    }
)
_LOCKED_ERROR_CODES = frozenset(
    {
        "LIVE_ORDER_V2_DISABLED",
        "LIVE_ORDER_GATE_BLOCKED",
        "BOT_INACTIVE",
        "EMERGENCY_AUTH_REQUIRED",
    }
)
_CONTROL_ERRORS = (
    LiveOrderControlServiceError,
    LiveOrderControlTransitionError,
    LiveOrderSubmissionBarrierError,
)
_TRADING_MODE_CONFLICT_ERRORS = frozenset(
    {
        "TRADING_MODE_VERSION_CONFLICT",
        "TRADING_MODE_GATE_CONFLICT",
        "TRADING_MODE_IDEMPOTENCY_CONFLICT",
        "TRADING_MODE_REQUEST_SUPERSEDED",
        "TRADING_MODE_REAUTH_CONFLICT",
    }
)
_TRADING_MODE_LOCKED_ERRORS = frozenset(
    {
        "LIVE_ORDER_V2_DISABLED",
        "BOT_ACTIVE",
        "LIVE_ORDER_GATE_BLOCKED",
        "ACTIVE_LIQUIDATION_EXISTS",
        "BLOCKING_ORDER_INTENT_EXISTS",
        "TRADING_MODE_STOP_INCOMPLETE",
    }
)
_TRADING_MODE_ERRORS = (
    AdminReauthError,
    TradingModeControlServiceError,
    TradingModeTransitionError,
    LiveOrderControlServiceError,
    LiveOrderControlTransitionError,
    LiveOrderSubmissionBarrierError,
)


@router.get("/status", response_model=BotStatus)
async def get_status(db: AsyncSession = Depends(get_db)) -> BotStatus:
    return await get_bot_status(db)


@router.post("/bot/start", response_model=BotStatus)
async def start_bot_endpoint(
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> BotStatus:
    await start_bot(db)
    return await get_bot_status(db)


@router.post("/admin/reauth", response_model=AdminReauthResponse)
async def reauthenticate_admin_endpoint(
    payload: AdminReauthRequest,
    admin_token: str = Depends(require_reentered_admin_token),
) -> AdminReauthResponse:
    try:
        proof = issue_admin_reauth_proof(
            admin_token,
            purpose=payload.purpose,
        )
    except AdminReauthError as exc:
        error_code = str(getattr(exc, "error_code", "ADMIN_REAUTH_INVALID"))
        http_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if error_code == "ADMIN_REAUTH_UNAVAILABLE"
            else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(
            status_code=http_status,
            detail={"error_code": error_code, "message": str(exc)},
        ) from exc
    return AdminReauthResponse(
        reauth_proof=proof.proof,
        expires_at=proof.expires_at,
    )


@router.get("/bot/trading-mode", response_model=TradingModeStatus)
async def get_trading_mode_endpoint(
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> TradingModeStatus:
    try:
        current = await get_trading_mode_status(
            db,
            suppress_repository_errors=False,
        )
    except Exception as exc:
        current = TradingModeStatus(
            unavailable_reason="TRADING_MODE_STATUS_QUERY_FAILED"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "TRADING_MODE_STATE_UNAVAILABLE",
                "message": "거래 모드 상태를 조회하지 못했습니다.",
                "trading_mode": current.model_dump(mode="json"),
            },
        ) from exc
    return current


@router.post("/bot/trading-mode/live", response_model=TradingModeStatus)
async def enable_live_trading_mode_endpoint(
    payload: EnableLiveTradingModeRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> TradingModeStatus:
    command = EnableLiveTradingModeCommand(
        request_id=_validate_idempotency_key(idempotency_key),
        expected_version=payload.expected_version,
        expected_gate_generation=payload.expected_gate_generation,
        expected_gate_version=payload.expected_gate_version,
        reason_text=payload.reason,
        confirmation=payload.confirmation,
        reauth_proof=payload.reauth_proof,
    )
    return await _execute_trading_mode_command(
        _trading_mode_control_service().enable_live(command),
        db,
    )


@router.post("/bot/trading-mode/paper", response_model=TradingModeStatus)
async def enable_paper_trading_mode_endpoint(
    payload: EnablePaperTradingModeRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> TradingModeStatus:
    command = EnablePaperTradingModeCommand(
        request_id=_validate_idempotency_key(idempotency_key),
        expected_version=payload.expected_version,
        reason_text=payload.reason,
    )
    return await _execute_trading_mode_command(
        _trading_mode_control_service().enable_paper(command),
        db,
    )


@router.post("/bot/stop", response_model=BotStatus)
async def stop_bot_endpoint(
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> BotStatus:
    command = BlockLiveOrdersCommand(
        request_id=uuid4(),
        reason_code="OPERATOR_STOP",
        reason_text="REST 관리자 요청으로 봇 런타임과 신규 실주문을 함께 정지했습니다.",
        source=CONTROL_SOURCE_REST,
        actor_ref="rest-admin",
    )
    await _execute_control_command(_live_order_control_service().stop_bot(command), db)
    return await get_bot_status(db)


@router.get("/bot/order-gate", response_model=LiveOrderGateStatus)
async def get_order_gate_endpoint(
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> LiveOrderGateStatus:
    try:
        return await get_live_order_gate_status(
            db,
            suppress_repository_errors=False,
        )
    except Exception as exc:
        gate = LiveOrderGateStatus()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "ORDER_GATE_STATE_UNAVAILABLE",
                "message": "실주문 제어 상태를 조회하지 못했습니다.",
                "order_gate": gate.model_dump(mode="json"),
            },
        ) from exc


@router.post("/bot/order-gate/arm", response_model=LiveOrderGateStatus)
async def arm_order_gate_endpoint(
    payload: ArmLiveOrderGateRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> LiveOrderGateStatus:
    command = ArmLiveOrdersCommand(
        request_id=_validate_idempotency_key(idempotency_key),
        expected_generation=payload.expected_generation,
        expected_version=payload.expected_version,
        reason_code="OPERATOR_ARM",
        reason_text=payload.reason,
        source=CONTROL_SOURCE_REST,
        actor_ref="rest-admin",
        confirmation=payload.confirmation,
    )
    return await _execute_control_command(
        _live_order_control_service().arm(command),
        db,
    )


@router.post("/bot/order-gate/block", response_model=LiveOrderGateStatus)
async def block_order_gate_endpoint(
    payload: BlockLiveOrderGateRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> LiveOrderGateStatus:
    command = BlockLiveOrdersCommand(
        request_id=_validate_idempotency_key(idempotency_key),
        reason_code="OPERATOR_BLOCK",
        reason_text=payload.reason,
        source=CONTROL_SOURCE_REST,
        actor_ref="rest-admin",
    )
    return await _execute_control_command(
        _live_order_control_service().block(command),
        db,
    )


def _live_order_control_service() -> LiveOrderControlService:
    return LiveOrderControlService(barrier=LiveOrderSubmissionBarrier(engine))


def _trading_mode_control_service() -> TradingModeControlService:
    barrier = LiveOrderSubmissionBarrier(engine)
    return TradingModeControlService(
        AsyncSessionLocal,
        barrier,
        live_order_control_service=LiveOrderControlService(barrier=barrier),
    )


def _control_error_status(error_code: str) -> int:
    if error_code in _CONFLICT_ERROR_CODES:
        return status.HTTP_409_CONFLICT
    if error_code in _LOCKED_ERROR_CODES:
        return status.HTTP_423_LOCKED
    return status.HTTP_503_SERVICE_UNAVAILABLE


async def _execute_control_command(
    operation: Awaitable[object],
    db: AsyncSession,
) -> LiveOrderGateStatus:
    try:
        await operation
    except _CONTROL_ERRORS as exc:
        gate = await get_live_order_gate_status(db)
        error_code = str(
            getattr(exc, "error_code", "ORDER_GATE_STATE_UNAVAILABLE")
        )
        raise HTTPException(
            status_code=_control_error_status(error_code),
            detail={
                "error_code": error_code,
                "message": str(exc),
                "order_gate": gate.model_dump(mode="json"),
            },
        ) from exc
    return await get_live_order_gate_status(db)


def _trading_mode_error_status(error_code: str) -> int:
    if error_code in _TRADING_MODE_CONFLICT_ERRORS:
        return status.HTTP_409_CONFLICT
    if error_code in _TRADING_MODE_LOCKED_ERRORS:
        return status.HTTP_423_LOCKED
    if error_code == "ADMIN_REAUTH_UNAVAILABLE":
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if error_code.startswith("ADMIN_REAUTH_"):
        return status.HTTP_403_FORBIDDEN
    if error_code in {
        "TRADING_MODE_IDEMPOTENCY_KEY_INVALID",
        "TRADING_MODE_REASON_INVALID",
        "TRADING_MODE_CONFIRMATION_INVALID",
    }:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_503_SERVICE_UNAVAILABLE


async def _execute_trading_mode_command(
    operation: Awaitable[object],
    db: AsyncSession,
) -> TradingModeStatus:
    try:
        await operation
    except _TRADING_MODE_ERRORS as exc:
        current = await get_trading_mode_status(db)
        gate = await get_live_order_gate_status(db)
        error_code = str(
            getattr(exc, "error_code", "TRADING_MODE_STATE_UNAVAILABLE")
        )
        raise HTTPException(
            status_code=_trading_mode_error_status(error_code),
            detail={
                "error_code": error_code,
                "message": str(exc),
                "trading_mode": current.model_dump(mode="json"),
                "order_gate": gate.model_dump(mode="json"),
            },
        ) from exc
    try:
        current = await get_trading_mode_status(
            db,
            suppress_repository_errors=False,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "TRADING_MODE_STATE_UNAVAILABLE",
                "message": "전환 후 거래 모드 상태를 확인하지 못했습니다.",
                "trading_mode": TradingModeStatus().model_dump(mode="json"),
            },
        ) from exc
    if not current.state_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "TRADING_MODE_STATE_UNAVAILABLE",
                "message": "전환 후 거래 모드 원장과 mirror 일치를 확인하지 못했습니다.",
                "trading_mode": current.model_dump(mode="json"),
            },
        )
    return current


def _liquidation_coordinator() -> LiquidationCoordinator:
    return LiquidationCoordinator(
        AsyncSessionLocal,
        BrokerFactory.get_broker("UPBIT"),
        LiveOrderSubmissionBarrier(engine),
    )


def _validate_idempotency_key(raw_value: str) -> str:
    try:
        parsed = UUID(str(raw_value).strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key는 UUID v4 형식이어야 합니다.",
        ) from exc
    if parsed.version != 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key는 UUID v4 형식이어야 합니다.",
        )
    return str(parsed)


@router.post("/bot/liquidate", response_model=LiquidationOperationResponse)
async def liquidate_all_endpoint(
    payload: LiquidateAllRequest,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> LiquidationOperationResponse:
    normalized_key = _validate_idempotency_key(idempotency_key)
    coordinator = _liquidation_coordinator()
    try:
        result = await coordinator.execute(
            normalized_key,
            scope=payload.scope,
            request_fingerprint=build_liquidation_request_fingerprint(payload.scope),
        )
    except _CONTROL_ERRORS as exc:
        gate = await get_live_order_gate_status(db)
        error_code = str(
            getattr(exc, "error_code", "ORDER_GATE_STATE_UNAVAILABLE")
        )
        detail: dict[str, object] = {
            "error_code": error_code,
            "message": str(exc),
            "order_gate": gate.model_dump(mode="json"),
        }
        active_operation_id = gate.active_liquidation_operation_id
        if active_operation_id is not None:
            try:
                active_operation = await coordinator.get_operation(
                    active_operation_id
                )
            except Exception:
                active_operation = None
        else:
            get_active = getattr(coordinator, "get_active_operation", None)
            try:
                active_operation = await get_active() if callable(get_active) else None
            except Exception:
                active_operation = None
        if active_operation is not None:
            detail["active_liquidation_operation"] = active_operation.model_dump(
                mode="json"
            )
        raise HTTPException(
            status_code=_control_error_status(error_code),
            detail=detail,
        ) from exc
    response.status_code = (
        status.HTTP_200_OK
        if result.status in LIQUIDATION_TERMINAL_STATUSES
        else status.HTTP_202_ACCEPTED
    )
    if result.status not in LIQUIDATION_TERMINAL_STATUSES:
        from app.core.scheduler import trigger_live_order_reconciliation_now

        trigger_live_order_reconciliation_now()
    return result


@router.get(
    "/bot/liquidations/{operation_id}",
    response_model=LiquidationOperationResponse,
)
async def get_liquidation_operation(
    operation_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> LiquidationOperationResponse:
    try:
        return await _liquidation_coordinator().get_operation(operation_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except _CONTROL_ERRORS as exc:
        gate = await get_live_order_gate_status(db)
        error_code = str(
            getattr(exc, "error_code", "ORDER_GATE_STATE_UNAVAILABLE")
        )
        raise HTTPException(
            status_code=_control_error_status(error_code),
            detail={
                "error_code": error_code,
                "message": str(exc),
                "order_gate": gate.model_dump(mode="json"),
            },
        ) from exc
