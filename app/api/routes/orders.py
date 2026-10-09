from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin_token
from app.db.session import AsyncSessionLocal, engine, get_db
from app.models.domain import Asset, OrderHistory, OrderIntent, Position
from app.models.schemas import OrderIntentStatusItem, ResolveNoOrderRequest
from app.services.brokers.factory import BrokerFactory
from app.services.brokers.upbit import UpbitAPIError
from app.services.trading.live_order_execution import LiveOrderExecutionService
from app.services.trading.live_order_submission_barrier import LiveOrderSubmissionBarrier

router = APIRouter()
MAX_DISPLAY_PNL_ABS_PERCENTAGE = 50.0
NO_ORDER_RESOLUTION_LEASE = timedelta(seconds=90)


class OrderHistoryResponse(BaseModel):
    id: int
    position_id: int
    symbol: str
    side: str
    price: float
    qty: float
    trade_amount_krw: float
    pnl_percentage: float | None = None
    broker: str
    executed_at: datetime


def _to_float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_side(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"ask", "sell"}:
        return "sell"
    if normalized in {"bid", "buy"}:
        return "buy"
    return normalized


def _calculate_trade_amount_krw(order: OrderHistory) -> float:
    return max(_to_float(order.price), 0.0) * max(_to_float(order.qty), 0.0)


def _calculate_pnl_percentage(order: OrderHistory, position: Position) -> float | None:
    if _normalize_side(order.side) != "sell":
        return None

    avg_entry_price = max(_to_float(position.avg_entry_price), 0.0)
    executed_price = max(_to_float(order.price), 0.0)
    if avg_entry_price <= 0 or executed_price <= 0:
        return None
    pnl_percentage = ((executed_price - avg_entry_price) / avg_entry_price) * 100
    if abs(pnl_percentage) > MAX_DISPLAY_PNL_ABS_PERCENTAGE:
        return None
    return pnl_percentage


def _order_intent_status_item(intent: OrderIntent) -> OrderIntentStatusItem:
    return OrderIntentStatusItem.model_validate(intent)


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _validate_no_order_resolution(intent: OrderIntent, now: datetime) -> None:
    if intent.submission_status != "UNKNOWN":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="UNKNOWN 상태의 주문 의도만 미생성으로 종결할 수 있습니다.",
        )
    if intent.unknown_at is None or _normalize_utc(intent.unknown_at) > now - timedelta(
        minutes=15
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="UNKNOWN 상태가 된 후 15분이 지나야 합니다.",
        )
    if intent.not_found_count < 5:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="identifier 조회의 404 응답이 최소 5회 필요합니다.",
        )
    if intent.first_not_found_at is None or intent.last_not_found_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="404 조회 시각 감사 기록이 부족합니다.",
        )
    not_found_span = _normalize_utc(intent.last_not_found_at) - _normalize_utc(
        intent.first_not_found_at
    )
    if not_found_span < timedelta(minutes=10):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="404 조회 기록이 10분 이상에 걸쳐 있어야 합니다.",
        )


def _live_order_service() -> LiveOrderExecutionService:
    return LiveOrderExecutionService(
        AsyncSessionLocal,
        BrokerFactory.get_broker("UPBIT"),
        LiveOrderSubmissionBarrier(engine),
    )


async def _release_no_order_resolution_lease(
    db: AsyncSession,
    intent_id: int,
    *,
    expected_version: int,
) -> None:
    async with db.begin():
        result = await db.execute(
            select(OrderIntent)
            .where(OrderIntent.id == intent_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        intent = result.scalar_one_or_none()
        if (
            intent is not None
            and intent.submission_status == "UNKNOWN"
            and intent.version == expected_version
        ):
            intent.reconcile_lease_until = None
            intent.version += 1
            await db.flush()


@router.get("/intents", response_model=list[OrderIntentStatusItem])
async def list_order_intents(
    unresolved_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> list[OrderIntentStatusItem]:
    statement = select(OrderIntent)
    if unresolved_only:
        statement = statement.where(
            OrderIntent.submission_status.in_(("PREPARED", "SUBMITTING", "UNKNOWN", "ACCEPTED")),
            OrderIntent.projection_status.in_(("PENDING", "ERROR")),
        )
    result = await db.execute(
        statement.order_by(desc(OrderIntent.created_at), desc(OrderIntent.id)).limit(limit)
    )
    return [_order_intent_status_item(intent) for intent in result.scalars().all()]


@router.post("/intents/{intent_id}/reconcile", response_model=OrderIntentStatusItem)
async def reconcile_order_intent(
    intent_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> OrderIntentStatusItem:
    result = await _live_order_service().reconcile_intent(intent_id)
    if result.error_code == "INTENT_NOT_FOUND":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문 의도를 찾을 수 없습니다.",
        )
    db.expire_all()
    query_result = await db.execute(select(OrderIntent).where(OrderIntent.id == intent_id))
    intent = query_result.scalar_one_or_none()
    if intent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문 의도를 찾을 수 없습니다.",
        )
    return _order_intent_status_item(intent)


@router.post("/intents/{intent_id}/resolve-no-order", response_model=OrderIntentStatusItem)
async def resolve_order_intent_as_not_created(
    intent_id: int,
    request: ResolveNoOrderRequest,
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> OrderIntentStatusItem:
    initial_result = await db.execute(select(OrderIntent).where(OrderIntent.id == intent_id))
    initial_intent = initial_result.scalar_one_or_none()
    if initial_intent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="주문 의도를 찾을 수 없습니다.",
        )
    now = datetime.now(UTC)
    _validate_no_order_resolution(initial_intent, now)
    await db.rollback()

    async with db.begin():
        lease_result = await db.execute(
            select(OrderIntent)
            .where(OrderIntent.id == intent_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        leased_intent = lease_result.scalar_one_or_none()
        if leased_intent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="주문 의도를 찾을 수 없습니다.",
            )
        now = datetime.now(UTC)
        _validate_no_order_resolution(leased_intent, now)
        if (
            leased_intent.reconcile_lease_until is not None
            and _normalize_utc(leased_intent.reconcile_lease_until) > now
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="주문 상태 재조정이 진행 중입니다. 완료 후 다시 시도해 주세요.",
            )
        leased_intent.reconcile_lease_until = now + NO_ORDER_RESOLUTION_LEASE
        leased_intent.version += 1
        resolution_version = leased_intent.version
        identifier = leased_intent.identifier
        await db.flush()

    broker = BrokerFactory.get_broker("UPBIT")
    try:
        await broker.get_order(identifier=identifier)
    except UpbitAPIError as exc:
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            await _release_no_order_resolution_lease(
                db,
                intent_id,
                expected_version=resolution_version,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Upbit의 최신 주문 상태를 확인하지 못했습니다.",
            ) from exc
    except Exception as exc:
        await _release_no_order_resolution_lease(
            db,
            intent_id,
            expected_version=resolution_version,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upbit의 최신 주문 상태를 확인하지 못했습니다.",
        ) from exc
    else:
        await _release_no_order_resolution_lease(
            db,
            intent_id,
            expected_version=resolution_version,
        )
        await _live_order_service().reconcile_intent(intent_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upbit에서 주문이 확인되어 미생성으로 종결할 수 없습니다.",
        )

    async with db.begin():
        locked_result = await db.execute(
            select(OrderIntent)
            .where(OrderIntent.id == intent_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        intent = locked_result.scalar_one_or_none()
        if intent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="주문 의도를 찾을 수 없습니다.",
            )
        now = datetime.now(UTC)
        if intent.version != resolution_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="주문 상태가 변경되어 미생성 종결을 중단했습니다.",
            )
        _validate_no_order_resolution(intent, now)
        intent.not_found_count += 1
        intent.first_not_found_at = intent.first_not_found_at or now
        intent.last_not_found_at = now
        intent.submission_status = "NO_ORDER_CONFIRMED"
        intent.projection_status = "SKIPPED"
        intent.next_reconcile_at = None
        intent.reconcile_lease_until = None
        intent.last_checked_at = now
        intent.resolved_at = now
        intent.resolved_by = "admin-token"
        intent.resolution_note = request.resolution_note
        intent.last_error_code = "NO_ORDER_CONFIRMED"
        intent.last_error_message = request.resolution_note
        intent.version += 1
        await db.flush()
        response = _order_intent_status_item(intent)
    return response


@router.get("/", response_model=list[OrderHistoryResponse])
async def list_orders(db: AsyncSession = Depends(get_db)) -> list[OrderHistoryResponse]:
    stmt = (
        select(OrderHistory, Position, Asset)
        .join(Position, Position.id == OrderHistory.position_id)
        .join(Asset, Asset.id == Position.asset_id)
        .order_by(desc(OrderHistory.executed_at), desc(OrderHistory.id))
        .limit(50)
    )
    result = await db.execute(stmt)

    orders: list[OrderHistoryResponse] = []
    for order, position, asset in result.all():
        orders.append(
            OrderHistoryResponse(
                id=order.id,
                position_id=position.id,
                symbol=asset.symbol,
                side=order.side,
                price=order.price,
                qty=order.qty,
                trade_amount_krw=_calculate_trade_amount_krw(order),
                pnl_percentage=_calculate_pnl_percentage(order, position),
                broker=order.broker,
                executed_at=order.executed_at,
            )
        )
    return orders
