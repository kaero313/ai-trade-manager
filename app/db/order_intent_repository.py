from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import LIVE_ORDER_V2_ENABLED_KEY
from app.models.domain import Asset, OrderHistory, OrderIntent, Position, SystemConfig

BLOCKING_SUBMISSION_STATUSES = ("PREPARED", "SUBMITTING", "UNKNOWN")
TERMINAL_EXCHANGE_STATES = ("done", "cancel")
OPEN_EXCHANGE_STATES = ("wait", "watch")
RECONCILABLE_SUBMISSION_STATUSES = ("SUBMITTING", "UNKNOWN", "ACCEPTED")
RECONCILIATION_BACKOFF_SECONDS = (15, 30, 60, 120, 300, 600)


def reconciliation_backoff(reconcile_attempt_count: int) -> timedelta:
    index = max(int(reconcile_attempt_count), 1) - 1
    if index < len(RECONCILIATION_BACKOFF_SECONDS):
        return timedelta(seconds=RECONCILIATION_BACKOFF_SECONDS[index])
    return timedelta(seconds=900)


@dataclass(frozen=True, slots=True)
class NewOrderIntent:
    intent_key: str
    identifier: str
    request_fingerprint: str
    source_type: str
    source_ref: str
    market: str
    side: str
    ord_type: str
    requested_price: Decimal | None
    requested_volume: Decimal | None
    execution_policy: str
    ai_analysis_log_id: int | None
    liquidation_operation_id: int | None
    order_reason: str | None
    prepared_control_generation: int
    prepared_control_mode: str
    broker: str = "UPBIT"
    account_scope: str = "primary"


@dataclass(frozen=True, slots=True)
class OrderIntentRecord:
    id: int
    intent_key: str
    identifier: str
    request_fingerprint: str
    source_type: str
    source_ref: str
    market: str
    side: str
    ord_type: str
    requested_price: Decimal | None
    requested_volume: Decimal | None
    execution_policy: str
    ai_analysis_log_id: int | None
    liquidation_operation_id: int | None
    order_reason: str | None
    broker: str
    account_scope: str
    submission_status: str
    exchange_uuid: str | None
    exchange_state: str | None
    executed_volume: Decimal | None
    executed_funds: Decimal | None
    average_fill_price: Decimal | None
    remaining_volume: Decimal | None
    paid_fee: Decimal | None
    projection_status: str
    post_attempt_count: int
    reconcile_attempt_count: int
    version: int
    next_reconcile_at: datetime | None
    reconcile_lease_until: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    not_found_count: int
    first_not_found_at: datetime | None
    last_not_found_at: datetime | None
    created_at: datetime
    submitted_at: datetime | None
    accepted_at: datetime | None
    unknown_at: datetime | None
    last_checked_at: datetime | None
    resolved_at: datetime | None
    order_history_id: int | None
    prepared_control_generation: int | None = None
    prepared_control_mode: str | None = None
    control_generation: int | None = None
    control_mode: str | None = None
    control_event_id: int | None = None
    submission_authorized_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CreateOrGetIntentResult:
    record: OrderIntentRecord
    created: bool
    blocking_intent: bool


class OrderIntentPayloadMismatchError(RuntimeError):
    def __init__(self, record: OrderIntentRecord) -> None:
        super().__init__("동일 주문 의도의 요청 payload가 기존 요청과 다릅니다.")
        self.record = record


def _blocking_predicate():
    return or_(
        OrderIntent.submission_status.in_(BLOCKING_SUBMISSION_STATUSES),
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


class OrderIntentRepository:
    async def find_intent_by_key(
        self,
        db: AsyncSession,
        intent_key: str,
    ) -> OrderIntentRecord | None:
        result = await db.execute(select(OrderIntent).where(OrderIntent.intent_key == intent_key))
        model = result.scalar_one_or_none()
        return await self._to_record(db, model) if model is not None else None

    async def create_or_get_intent(
        self,
        db: AsyncSession,
        draft: NewOrderIntent,
    ) -> CreateOrGetIntentResult:
        values = {
            "intent_key": draft.intent_key,
            "identifier": draft.identifier,
            "request_fingerprint": draft.request_fingerprint,
            "source_type": draft.source_type,
            "source_ref": draft.source_ref,
            "ai_analysis_log_id": draft.ai_analysis_log_id,
            "liquidation_operation_id": draft.liquidation_operation_id,
            "order_reason": draft.order_reason,
            "execution_policy": draft.execution_policy,
            "broker": draft.broker,
            "account_scope": draft.account_scope,
            "market": draft.market,
            "side": draft.side,
            "ord_type": draft.ord_type,
            "requested_price": draft.requested_price,
            "requested_volume": draft.requested_volume,
            "submission_status": "PREPARED",
            "projection_status": "PENDING",
            "prepared_control_generation": draft.prepared_control_generation,
            "prepared_control_mode": draft.prepared_control_mode,
        }
        insert_statement = (
            postgresql_insert(OrderIntent)
            .values(**values)
            .on_conflict_do_nothing()
            .returning(OrderIntent.id)
        )
        inserted_id = (await db.execute(insert_statement)).scalar_one_or_none()
        await db.flush()

        if inserted_id is not None:
            model = await self._get_model(db, inserted_id)
            if model is None:
                raise RuntimeError("생성한 주문 의도를 다시 조회하지 못했습니다.")
            return CreateOrGetIntentResult(
                record=await self._to_record(db, model),
                created=True,
                blocking_intent=False,
            )

        same_intent_result = await db.execute(
            select(OrderIntent).where(OrderIntent.intent_key == draft.intent_key)
        )
        same_intent = same_intent_result.scalar_one_or_none()
        if same_intent is not None:
            record = await self._to_record(db, same_intent)
            if record.request_fingerprint != draft.request_fingerprint:
                raise OrderIntentPayloadMismatchError(record)
            return CreateOrGetIntentResult(
                record=record,
                created=False,
                blocking_intent=False,
            )

        blocking_conditions = [
            OrderIntent.broker == draft.broker,
            OrderIntent.account_scope == draft.account_scope,
            _blocking_predicate(),
            or_(
                OrderIntent.market == draft.market,
                and_(draft.side == "bid", OrderIntent.side == "bid"),
            ),
        ]
        blocking_result = await db.execute(
            select(OrderIntent)
            .where(*blocking_conditions)
            .order_by(OrderIntent.created_at.asc(), OrderIntent.id.asc())
            .limit(1)
        )
        blocking_intent = blocking_result.scalar_one_or_none()
        if blocking_intent is None:
            raise RuntimeError("주문 의도 INSERT 충돌의 원인을 확인하지 못했습니다.")
        return CreateOrGetIntentResult(
            record=await self._to_record(db, blocking_intent),
            created=False,
            blocking_intent=True,
        )

    async def get_intent(
        self,
        db: AsyncSession,
        intent_id: int,
        *,
        for_update: bool = False,
    ) -> OrderIntentRecord | None:
        statement = select(OrderIntent).where(OrderIntent.id == intent_id)
        if for_update:
            statement = statement.with_for_update()
        result = await db.execute(statement)
        model = result.scalar_one_or_none()
        return await self._to_record(db, model) if model is not None else None

    async def is_live_order_v2_enabled(self, db: AsyncSession) -> bool:
        result = await db.execute(
            select(SystemConfig.config_value).where(
                SystemConfig.config_key == LIVE_ORDER_V2_ENABLED_KEY
            )
        )
        return result.scalar_one_or_none() == "true"

    async def disable_live_order_v2(self, db: AsyncSession) -> None:
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

    async def claim_submission(
        self,
        db: AsyncSession,
        intent_id: int,
        *,
        expected_version: int,
        now: datetime,
        control_generation: int,
        control_mode: str,
        control_event_id: int,
    ) -> OrderIntentRecord | None:
        if control_generation < 1:
            raise ValueError("제출 승인 control generation은 1 이상이어야 합니다.")
        if control_mode not in {"ARMED", "EXIT_ONLY"}:
            raise ValueError("제출 승인 control mode가 허용 상태가 아닙니다.")
        if control_event_id < 1:
            raise ValueError("제출 승인 control event ID는 1 이상이어야 합니다.")
        statement = (
            update(OrderIntent)
            .where(
                OrderIntent.id == intent_id,
                OrderIntent.submission_status == "PREPARED",
                OrderIntent.post_attempt_count == 0,
                OrderIntent.version == expected_version,
                OrderIntent.prepared_control_generation == control_generation,
                OrderIntent.prepared_control_mode == control_mode,
            )
            .values(
                submission_status="SUBMITTING",
                post_attempt_count=1,
                submitted_at=now,
                last_error_code=None,
                last_error_message=None,
                version=OrderIntent.version + 1,
                control_generation=control_generation,
                control_mode=control_mode,
                control_event_id=control_event_id,
                submission_authorized_at=now,
            )
            .returning(OrderIntent.id)
        )
        claimed_id = (await db.execute(statement)).scalar_one_or_none()
        await db.flush()
        if claimed_id is None:
            return None
        model = await self._get_model(db, claimed_id)
        return await self._to_record(db, model) if model is not None else None

    async def abandon_prepared(
        self,
        db: AsyncSession,
        intent_id: int,
        *,
        expected_version: int,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> OrderIntentRecord | None:
        statement = (
            update(OrderIntent)
            .where(
                OrderIntent.id == intent_id,
                OrderIntent.submission_status == "PREPARED",
                OrderIntent.post_attempt_count == 0,
                OrderIntent.version == expected_version,
            )
            .values(
                submission_status="ABANDONED",
                projection_status="SKIPPED",
                last_error_code=error_code,
                last_error_message=error_message,
                resolved_at=now,
                next_reconcile_at=None,
                reconcile_lease_until=None,
                version=OrderIntent.version + 1,
            )
            .returning(OrderIntent.id)
        )
        abandoned_id = (await db.execute(statement)).scalar_one_or_none()
        await db.flush()
        if abandoned_id is None:
            return None
        model = await self._get_model(db, abandoned_id)
        return await self._to_record(db, model) if model is not None else None

    async def mark_accepted(
        self,
        db: AsyncSession,
        intent_id: int,
        *,
        exchange_uuid: str,
        exchange_state: str | None,
        executed_volume: Decimal | None,
        executed_funds: Decimal | None,
        average_fill_price: Decimal | None,
        remaining_volume: Decimal | None,
        paid_fee: Decimal | None,
        now: datetime,
        reconcile_after: timedelta,
        expected_version: int | None = None,
    ) -> OrderIntentRecord:
        model = await self._locked_model(db, intent_id)
        if expected_version is not None and model.version != expected_version:
            return await self._to_record(db, model)
        if model.submission_status not in {"SUBMITTING", "UNKNOWN", "ACCEPTED"}:
            return await self._to_record(db, model)
        if (
            model.submission_status == "ACCEPTED"
            and model.exchange_uuid is not None
            and model.exchange_uuid != exchange_uuid
        ):
            model.projection_status = "ERROR"
            model.last_error_code = "EXCHANGE_UUID_CONFLICT"
            model.last_error_message = "기존 거래소 UUID와 조회된 UUID가 일치하지 않습니다."
            model.next_reconcile_at = None
            model.reconcile_lease_until = None
            model.version += 1
            await db.flush()
            return await self._to_record(db, model)
        model.submission_status = "ACCEPTED"
        model.exchange_uuid = exchange_uuid
        model.exchange_state = exchange_state
        model.executed_volume = executed_volume
        model.executed_funds = executed_funds
        model.average_fill_price = average_fill_price
        model.remaining_volume = remaining_volume
        model.paid_fee = paid_fee
        model.accepted_at = model.accepted_at or now
        model.last_checked_at = now
        model.reconcile_lease_until = None
        model.last_error_code = None
        model.last_error_message = None
        model.version += 1
        if exchange_state in TERMINAL_EXCHANGE_STATES:
            model.resolved_at = now
            model.next_reconcile_at = now
        else:
            model.next_reconcile_at = now + reconcile_after
        await db.flush()
        return await self._to_record(db, model)

    async def mark_rejected(
        self,
        db: AsyncSession,
        intent_id: int,
        *,
        error_code: str,
        error_message: str | None,
        now: datetime,
        expected_version: int | None = None,
    ) -> OrderIntentRecord:
        model = await self._locked_model(db, intent_id)
        if expected_version is not None and model.version != expected_version:
            return await self._to_record(db, model)
        if model.submission_status != "SUBMITTING":
            return await self._to_record(db, model)
        model.submission_status = "REJECTED"
        model.projection_status = "SKIPPED"
        model.last_error_code = error_code
        model.last_error_message = error_message
        model.reconcile_lease_until = None
        model.next_reconcile_at = None
        model.resolved_at = now
        model.version += 1
        await db.flush()
        return await self._to_record(db, model)

    async def mark_unknown(
        self,
        db: AsyncSession,
        intent_id: int,
        *,
        error_code: str,
        error_message: str | None,
        now: datetime,
        next_reconcile_at: datetime,
        not_found_count: int = 0,
        expected_version: int | None = None,
    ) -> OrderIntentRecord:
        model = await self._locked_model(db, intent_id)
        if expected_version is not None and model.version != expected_version:
            return await self._to_record(db, model)
        if model.submission_status not in RECONCILABLE_SUBMISSION_STATUSES:
            return await self._to_record(db, model)
        if model.submission_status != "ACCEPTED":
            model.submission_status = "UNKNOWN"
            model.unknown_at = model.unknown_at or now
        model.last_error_code = error_code
        model.last_error_message = error_message
        model.last_checked_at = now
        model.next_reconcile_at = next_reconcile_at
        model.reconcile_lease_until = None
        if not_found_count > 0:
            model.not_found_count += not_found_count
            model.first_not_found_at = model.first_not_found_at or now
            model.last_not_found_at = now
        model.version += 1
        await db.flush()
        return await self._to_record(db, model)

    async def mark_reconciliation_conflict(
        self,
        db: AsyncSession,
        intent_id: int,
        *,
        error_message: str,
        now: datetime,
        expected_version: int | None = None,
    ) -> OrderIntentRecord:
        model = await self._locked_model(db, intent_id)
        if expected_version is not None and model.version != expected_version:
            return await self._to_record(db, model)
        if model.submission_status not in RECONCILABLE_SUBMISSION_STATUSES:
            return await self._to_record(db, model)
        model.submission_status = "UNKNOWN"
        model.unknown_at = model.unknown_at or now
        model.projection_status = "ERROR"
        model.last_error_code = "RECONCILIATION_CONFLICT"
        model.last_error_message = error_message
        model.last_checked_at = now
        model.next_reconcile_at = None
        model.reconcile_lease_until = None
        model.version += 1
        await db.flush()
        return await self._to_record(db, model)

    async def claim_reconciliation(
        self,
        db: AsyncSession,
        intent_id: int,
        *,
        now: datetime,
        lease_for: timedelta,
    ) -> OrderIntentRecord | None:
        model = await self._locked_model(db, intent_id, required=False)
        if model is None or model.submission_status not in RECONCILABLE_SUBMISSION_STATUSES:
            return None
        if model.reconcile_lease_until is not None and model.reconcile_lease_until > now:
            return None
        if model.submission_status == "SUBMITTING":
            model.submission_status = "UNKNOWN"
        model.reconcile_attempt_count += 1
        model.reconcile_lease_until = now + lease_for
        model.last_checked_at = now
        model.version += 1
        await db.flush()
        return await self._to_record(db, model)

    async def claim_due_reconciliation(
        self,
        db: AsyncSession,
        *,
        now: datetime,
        lease_for: timedelta,
        submitting_stale_after: timedelta,
        limit: int,
    ) -> list[OrderIntentRecord]:
        due_predicate = or_(
            OrderIntent.next_reconcile_at <= now,
            and_(
                OrderIntent.submission_status == "SUBMITTING",
                OrderIntent.submitted_at <= now - submitting_stale_after,
            ),
        )
        result = await db.execute(
            select(OrderIntent)
            .where(
                OrderIntent.submission_status.in_(RECONCILABLE_SUBMISSION_STATUSES),
                due_predicate,
                or_(
                    OrderIntent.reconcile_lease_until.is_(None),
                    OrderIntent.reconcile_lease_until <= now,
                ),
            )
            .order_by(OrderIntent.next_reconcile_at.asc().nullsfirst(), OrderIntent.id.asc())
            .with_for_update(skip_locked=True)
            .limit(max(1, limit))
        )
        models = list(result.scalars().all())
        records: list[OrderIntentRecord] = []
        for model in models:
            if model.submission_status == "SUBMITTING":
                model.submission_status = "UNKNOWN"
            model.reconcile_attempt_count += 1
            model.reconcile_lease_until = now + lease_for
            model.last_checked_at = now
            model.version += 1
        await db.flush()
        for model in models:
            records.append(await self._to_record(db, model))
        return records

    async def project_terminal_fill(
        self,
        db: AsyncSession,
        intent_id: int,
        *,
        now: datetime,
    ) -> OrderIntentRecord:
        model = await self._locked_model(db, intent_id)
        if (
            model.submission_status != "ACCEPTED"
            or model.exchange_state not in TERMINAL_EXCHANGE_STATES
            or model.projection_status in ("APPLIED", "SKIPPED")
        ):
            return await self._to_record(db, model)

        history_result = await db.execute(
            select(OrderHistory).where(OrderHistory.order_intent_id == intent_id)
        )
        existing_history = history_result.scalar_one_or_none()
        if existing_history is not None:
            model.projection_status = "APPLIED"
            model.projected_at = model.projected_at or now
            model.last_error_code = None
            model.last_error_message = None
            model.next_reconcile_at = None
            model.reconcile_lease_until = None
            model.version += 1
            await db.flush()
            return await self._to_record(db, model)

        executed_volume = Decimal(model.executed_volume or 0)
        average_fill_price = Decimal(model.average_fill_price or 0)
        if executed_volume <= 0:
            model.projection_status = "SKIPPED"
            model.projected_at = now
            model.next_reconcile_at = None
            model.reconcile_lease_until = None
            model.version += 1
            await db.flush()
            return await self._to_record(db, model)
        if average_fill_price <= 0:
            model.projection_status = "ERROR"
            model.last_error_code = "FILL_PRICE_UNAVAILABLE"
            model.last_error_message = "실제 체결 VWAP을 확인할 수 없습니다."
            model.next_reconcile_at = now + reconciliation_backoff(model.reconcile_attempt_count)
            model.reconcile_lease_until = None
            model.version += 1
            await db.flush()
            return await self._to_record(db, model)

        asset_insert = (
            postgresql_insert(Asset)
            .values(
                symbol=model.market,
                asset_type="crypto",
                base_currency=model.market.split("-", 1)[0],
                is_active=True,
            )
            .on_conflict_do_nothing(index_elements=[Asset.symbol])
        )
        await db.execute(asset_insert)
        asset_result = await db.execute(select(Asset).where(Asset.symbol == model.market))
        asset = asset_result.scalar_one()

        position_result = await db.execute(
            select(Position)
            .where(Position.asset_id == asset.id, Position.is_paper.is_(False))
            .order_by(Position.id.asc())
            .with_for_update()
        )
        position = position_result.scalars().first()
        if position is None:
            position = Position(
                asset_id=asset.id,
                avg_entry_price=float(average_fill_price),
                quantity=0.0,
                status="open",
                is_paper=False,
            )
            db.add(position)
            await db.flush()

        fill_qty = float(executed_volume)
        fill_price = float(average_fill_price)
        current_qty = max(float(position.quantity or 0), 0.0)
        if model.side == "bid":
            executed_funds = Decimal(model.executed_funds or 0)
            fill_cost = float(executed_funds) if executed_funds > 0 else fill_price * fill_qty
            new_qty = current_qty + fill_qty
            previous_cost = current_qty * max(float(position.avg_entry_price or 0), 0.0)
            position.avg_entry_price = (previous_cost + fill_cost) / new_qty
            position.quantity = new_qty
            position.status = "open"
            history_side = "buy"
        else:
            position.quantity = max(current_qty - fill_qty, 0.0)
            position.status = "closed" if position.quantity <= 1e-12 else "open"
            history_side = "sell"

        history = OrderHistory(
            position_id=position.id,
            order_intent_id=model.id,
            ai_analysis_log_id=model.ai_analysis_log_id,
            side=history_side,
            order_reason=model.order_reason,
            is_paper=False,
            price=fill_price,
            qty=fill_qty,
            broker=model.broker,
            executed_at=now,
        )
        db.add(history)
        await db.flush()
        model.projection_status = "APPLIED"
        model.projected_at = now
        model.last_error_code = None
        model.last_error_message = None
        model.next_reconcile_at = None
        model.reconcile_lease_until = None
        model.version += 1
        await db.flush()
        return await self._to_record(db, model)

    async def mark_projection_error(
        self,
        db: AsyncSession,
        intent_id: int,
        *,
        error_code: str,
        error_message: str,
        now: datetime,
        expected_version: int | None = None,
    ) -> OrderIntentRecord:
        model = await self._locked_model(db, intent_id)
        if expected_version is not None and model.version != expected_version:
            return await self._to_record(db, model)
        if (
            model.submission_status != "ACCEPTED"
            or model.exchange_state not in TERMINAL_EXCHANGE_STATES
            or model.projection_status in {"APPLIED", "SKIPPED"}
        ):
            return await self._to_record(db, model)
        model.projection_status = "ERROR"
        model.last_error_code = error_code
        model.last_error_message = error_message
        model.next_reconcile_at = now + reconciliation_backoff(model.reconcile_attempt_count)
        model.reconcile_lease_until = None
        model.version += 1
        await db.flush()
        return await self._to_record(db, model)

    async def _get_model(self, db: AsyncSession, intent_id: int) -> OrderIntent | None:
        result = await db.execute(select(OrderIntent).where(OrderIntent.id == intent_id))
        return result.scalar_one_or_none()

    async def _locked_model(
        self,
        db: AsyncSession,
        intent_id: int,
        *,
        required: bool = True,
    ) -> OrderIntent | None:
        result = await db.execute(
            select(OrderIntent).where(OrderIntent.id == intent_id).with_for_update()
        )
        model = result.scalar_one_or_none()
        if model is None and required:
            raise LookupError(f"주문 의도를 찾을 수 없습니다: {intent_id}")
        return model

    async def _to_record(
        self,
        db: AsyncSession,
        model: OrderIntent,
    ) -> OrderIntentRecord:
        history_result = await db.execute(
            select(OrderHistory.id).where(OrderHistory.order_intent_id == model.id)
        )
        order_history_id = history_result.scalar_one_or_none()
        return OrderIntentRecord(
            id=model.id,
            intent_key=model.intent_key,
            identifier=model.identifier,
            request_fingerprint=model.request_fingerprint,
            source_type=model.source_type,
            source_ref=model.source_ref,
            market=model.market,
            side=model.side,
            ord_type=model.ord_type,
            requested_price=model.requested_price,
            requested_volume=model.requested_volume,
            execution_policy=model.execution_policy,
            ai_analysis_log_id=model.ai_analysis_log_id,
            liquidation_operation_id=model.liquidation_operation_id,
            order_reason=model.order_reason,
            broker=model.broker,
            account_scope=model.account_scope,
            submission_status=model.submission_status,
            exchange_uuid=model.exchange_uuid,
            exchange_state=model.exchange_state,
            executed_volume=model.executed_volume,
            executed_funds=model.executed_funds,
            average_fill_price=model.average_fill_price,
            remaining_volume=model.remaining_volume,
            paid_fee=model.paid_fee,
            projection_status=model.projection_status,
            post_attempt_count=model.post_attempt_count,
            reconcile_attempt_count=model.reconcile_attempt_count,
            version=model.version,
            next_reconcile_at=model.next_reconcile_at,
            reconcile_lease_until=model.reconcile_lease_until,
            last_error_code=model.last_error_code,
            last_error_message=model.last_error_message,
            not_found_count=model.not_found_count,
            first_not_found_at=model.first_not_found_at,
            last_not_found_at=model.last_not_found_at,
            created_at=model.created_at,
            submitted_at=model.submitted_at,
            accepted_at=model.accepted_at,
            unknown_at=model.unknown_at,
            last_checked_at=model.last_checked_at,
            resolved_at=model.resolved_at,
            order_history_id=order_history_id,
            prepared_control_generation=model.prepared_control_generation,
            prepared_control_mode=model.prepared_control_mode,
            control_generation=model.control_generation,
            control_mode=model.control_mode,
            control_event_id=model.control_event_id,
            submission_authorized_at=model.submission_authorized_at,
        )
