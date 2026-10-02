from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    LiquidationOperation,
    LiquidationOperationEvent,
    LiquidationOrderCancellation,
)


ACTIVE_LIQUIDATION_STATUSES = ("PREPARING", "IN_PROGRESS")


class LiquidationRepository:
    async def get_operation(
        self,
        db: AsyncSession,
        operation_id: int,
        *,
        for_update: bool = False,
    ) -> LiquidationOperation | None:
        statement = select(LiquidationOperation).where(
            LiquidationOperation.id == operation_id
        )
        if for_update:
            statement = statement.with_for_update()
        return (await db.execute(statement)).scalar_one_or_none()

    async def find_by_key(
        self,
        db: AsyncSession,
        idempotency_key: str,
        *,
        for_update: bool = False,
    ) -> LiquidationOperation | None:
        statement = select(LiquidationOperation).where(
            LiquidationOperation.idempotency_key == idempotency_key
        )
        if for_update:
            statement = statement.with_for_update()
        return (await db.execute(statement)).scalar_one_or_none()

    async def find_active(
        self,
        db: AsyncSession,
        *,
        broker: str,
        account_scope: str,
    ) -> LiquidationOperation | None:
        result = await db.execute(
            select(LiquidationOperation)
            .where(
                LiquidationOperation.broker == broker,
                LiquidationOperation.account_scope == account_scope,
                LiquidationOperation.status.in_(ACTIVE_LIQUIDATION_STATUSES),
            )
            .order_by(LiquidationOperation.id.asc())
            .with_for_update()
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def claim_due_operations(
        self,
        db: AsyncSession,
        *,
        now: datetime,
        lease_for: timedelta,
        limit: int,
    ) -> list[tuple[int, datetime]]:
        result = await db.execute(
            select(LiquidationOperation)
            .where(
                LiquidationOperation.contract_version == 2,
                LiquidationOperation.status.in_(ACTIVE_LIQUIDATION_STATUSES),
                or_(
                    LiquidationOperation.next_run_at.is_(None),
                    LiquidationOperation.next_run_at <= now,
                ),
                or_(
                    LiquidationOperation.lease_until.is_(None),
                    LiquidationOperation.lease_until <= now,
                ),
            )
            .order_by(
                LiquidationOperation.next_run_at.asc().nullsfirst(),
                LiquidationOperation.id.asc(),
            )
            .with_for_update(skip_locked=True)
            .limit(max(1, limit))
        )
        operations = list(result.scalars().all())
        claimed: list[tuple[int, datetime]] = []
        for operation in operations:
            lease_until = now + lease_for
            operation.lease_until = lease_until
            operation.next_run_at = None
            operation.version += 1
            claimed.append((operation.id, lease_until))
        await db.flush()
        return claimed

    async def claim_operation(
        self,
        db: AsyncSession,
        operation_id: int,
        *,
        now: datetime,
        lease_for: timedelta,
    ) -> datetime | None:
        operation = await self.get_operation(db, operation_id, for_update=True)
        if operation is None or operation.status not in ACTIVE_LIQUIDATION_STATUSES:
            return None
        if operation.lease_until is not None and operation.lease_until > now:
            return None
        lease_until = now + lease_for
        operation.lease_until = lease_until
        operation.next_run_at = None
        operation.version += 1
        await db.flush()
        return lease_until

    async def append_event(
        self,
        db: AsyncSession,
        operation: LiquidationOperation,
        *,
        event_type: str,
        source: str = "SYSTEM",
        actor_ref: str | None = "liquidation-coordinator",
        from_phase: str | None = None,
        to_phase: str | None = None,
        details: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        now: datetime | None = None,
    ) -> LiquidationOperationEvent:
        sequence = (
            await db.scalar(
                select(func.coalesce(func.max(LiquidationOperationEvent.sequence), 0)).where(
                    LiquidationOperationEvent.liquidation_operation_id == operation.id
                )
            )
        ) or 0
        event = LiquidationOperationEvent(
            liquidation_operation_id=operation.id,
            sequence=int(sequence) + 1,
            operation_version=operation.version,
            event_type=event_type,
            from_phase=from_phase,
            to_phase=to_phase,
            source=source,
            actor_ref=actor_ref,
            details=details,
            error_code=error_code,
            error_message=(error_message[:2000] if error_message else None),
            created_at=now or datetime.now(UTC),
        )
        db.add(event)
        await db.flush()
        return event

    async def discover_cancellations(
        self,
        db: AsyncSession,
        operation_id: int,
        rows: Iterable[dict[str, Any]],
        *,
        now: datetime,
    ) -> int:
        existing_result = await db.execute(
            select(LiquidationOrderCancellation.exchange_uuid).where(
                LiquidationOrderCancellation.liquidation_operation_id == operation_id
            )
        )
        existing = set(existing_result.scalars().all())
        added = 0
        for row in rows:
            exchange_uuid = str(row["exchange_uuid"])
            if exchange_uuid in existing:
                continue
            db.add(
                LiquidationOrderCancellation(
                    liquidation_operation_id=operation_id,
                    exchange_uuid=exchange_uuid,
                    identifier=row.get("identifier"),
                    market=row.get("market"),
                    side=row.get("side"),
                    initial_exchange_state=row.get("initial_exchange_state"),
                    ownership=row.get("ownership", "EXTERNAL"),
                    order_intent_id=row.get("order_intent_id"),
                    status="DISCOVERED",
                    attempt_count=0,
                    reconcile_attempt_count=0,
                    version=1,
                    last_error_code=row.get("last_error_code"),
                    last_error_message=(
                        str(row["last_error_message"])[:2000]
                        if row.get("last_error_message")
                        else None
                    ),
                    discovered_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            existing.add(exchange_uuid)
            added += 1
        await db.flush()
        return added

    async def list_cancellations(
        self,
        db: AsyncSession,
        operation_id: int,
        *,
        statuses: tuple[str, ...] | None = None,
        for_update: bool = False,
    ) -> list[LiquidationOrderCancellation]:
        statement = select(LiquidationOrderCancellation).where(
            LiquidationOrderCancellation.liquidation_operation_id == operation_id
        )
        if statuses:
            statement = statement.where(LiquidationOrderCancellation.status.in_(statuses))
        statement = statement.order_by(LiquidationOrderCancellation.id.asc())
        if for_update:
            statement = statement.with_for_update()
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def claim_cancel_batch(
        self,
        db: AsyncSession,
        operation_id: int,
        *,
        now: datetime,
        lease_for: timedelta,
        limit: int = 20,
    ) -> list[LiquidationOrderCancellation]:
        result = await db.execute(
            select(LiquidationOrderCancellation)
            .where(
                LiquidationOrderCancellation.liquidation_operation_id == operation_id,
                LiquidationOrderCancellation.status == "DISCOVERED",
                LiquidationOrderCancellation.attempt_count < 3,
                or_(
                    LiquidationOrderCancellation.next_retry_at.is_(None),
                    LiquidationOrderCancellation.next_retry_at <= now,
                ),
                or_(
                    LiquidationOrderCancellation.lease_until.is_(None),
                    LiquidationOrderCancellation.lease_until <= now,
                ),
            )
            .order_by(LiquidationOrderCancellation.id.asc())
            .with_for_update(skip_locked=True)
            .limit(min(20, max(1, limit)))
        )
        rows = list(result.scalars().all())
        for row in rows:
            row.status = "CANCELING"
            row.attempt_count += 1
            row.reconcile_attempt_count = 0
            row.lease_until = now + lease_for
            row.canceling_at = now
            row.last_checked_at = now
            row.version += 1
            row.updated_at = now
        await db.flush()
        return rows

    async def due_unknown_cancellations(
        self,
        db: AsyncSession,
        operation_id: int,
        *,
        now: datetime,
        lease_for: timedelta,
        limit: int = 20,
    ) -> list[LiquidationOrderCancellation]:
        result = await db.execute(
            select(LiquidationOrderCancellation)
            .where(
                LiquidationOrderCancellation.liquidation_operation_id == operation_id,
                LiquidationOrderCancellation.status == "UNKNOWN",
                or_(
                    LiquidationOrderCancellation.next_retry_at.is_(None),
                    LiquidationOrderCancellation.next_retry_at <= now,
                ),
                or_(
                    LiquidationOrderCancellation.lease_until.is_(None),
                    LiquidationOrderCancellation.lease_until <= now,
                ),
            )
            .order_by(LiquidationOrderCancellation.id.asc())
            .with_for_update(skip_locked=True)
            .limit(max(1, limit))
        )
        rows = list(result.scalars().all())
        for row in rows:
            row.reconcile_attempt_count += 1
            row.lease_until = now + lease_for
            row.last_checked_at = now
            row.version += 1
            row.updated_at = now
        await db.flush()
        return rows
