"""feat(db): 전량 청산 증거 원장 추가

Revision ID: f6b2c9d4e8a1
Revises: c4f8a2d7e1b3
Create Date: 2026-07-12 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "f6b2c9d4e8a1"
down_revision: Union[str, Sequence[str], None] = "c4f8a2d7e1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LIVE_ORDER_ADVISORY_LOCK_KEY = 5740495976316385210
ACTIVE_LIQUIDATION_PREDICATE = "status IN ('PREPARING', 'IN_PROGRESS')"
UNSAFE_LIQUIDATION_PREDICATE = (
    "emergency_authorization_status = 'ACTIVE' "
    f"OR ({ACTIVE_LIQUIDATION_PREDICATE})"
)
ORDER_INTENT_BLOCKING_PREDICATE = """
submission_status IN ('PREPARED', 'SUBMITTING', 'UNKNOWN')
OR (
    submission_status = 'ACCEPTED'
    AND (
        exchange_state IS NULL
        OR exchange_state IN ('wait', 'watch')
        OR (
            exchange_state IN ('done', 'cancel')
            AND projection_status IN ('PENDING', 'ERROR')
        )
    )
)
"""
LIQUIDATION_PHASES = (
    "'BLOCKING', 'DISCOVERING_ORDERS', 'CANCELING_ORDERS', "
    "'RECONCILING_CANCELED_ORDERS', 'SNAPSHOTTING_TARGETS', 'SUBMITTING', "
    "'WAITING_FILLS', 'VERIFYING', 'TERMINAL'"
)


def upgrade() -> None:
    """안전한 중지 상태에서 청산 v2 증거 원장을 추가합니다."""
    _require_safe_upgrade()
    _add_operation_columns()
    _backfill_legacy_operations()
    _add_operation_constraints_and_index()
    _create_cancellation_table()
    _create_operation_event_table()
    _create_hard_delete_guards()


def _require_safe_upgrade() -> None:
    if context.is_offline_mode():
        _emit_common_preflight(block_name="atm_p0_004_upgrade", operation="upgrade")
        return

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("ATM-P0-004 upgrade preflight requires PostgreSQL")
    _acquire_advisory_lock(bind, operation="upgrade")
    _require_rollout_disabled(bind, operation="upgrade")
    _require_gate_blocked(bind, operation="upgrade")
    _require_no_active_liquidation(bind, operation="upgrade")
    _require_no_blocking_intent(bind, operation="upgrade")


def _add_operation_columns() -> None:
    columns = (
        sa.Column(
            "broker",
            sa.String(length=32),
            server_default=sa.text("'UPBIT'"),
            nullable=False,
        ),
        sa.Column(
            "account_scope",
            sa.String(length=64),
            server_default=sa.text("'primary'"),
            nullable=False,
        ),
        sa.Column(
            "contract_version",
            sa.Integer(),
            server_default=sa.text("2"),
            nullable=False,
        ),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "cancel_scope",
            sa.String(length=24),
            server_default=sa.text("'ACCOUNT_ALL'"),
            nullable=False,
        ),
        sa.Column(
            "phase",
            sa.String(length=48),
            server_default=sa.text("'BLOCKING'"),
            nullable=False,
        ),
        sa.Column(
            "verification_status",
            sa.String(length=24),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "retry_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("initial_account_snapshot", sa.JSON(), nullable=True),
        sa.Column("initial_accounts_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("post_cancel_account_snapshot", sa.JSON(), nullable=True),
        sa.Column(
            "post_cancel_accounts_observed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("final_account_snapshot", sa.JSON(), nullable=True),
        sa.Column("final_accounts_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_summary", sa.JSON(), nullable=True),
        sa.Column("order_summary", sa.JSON(), nullable=True),
        sa.Column("remaining_summary", sa.JSON(), nullable=True),
    )
    for column in columns:
        op.add_column("liquidation_operations", column)


def _backfill_legacy_operations() -> None:
    op.execute(
        sa.text(
            """
            UPDATE liquidation_operations
            SET broker = 'UPBIT',
                account_scope = 'primary',
                contract_version = 1,
                request_fingerprint = NULL,
                cancel_scope = 'LEGACY_NONE',
                phase = 'TERMINAL',
                verification_status = 'LEGACY_UNVERIFIED',
                version = 0,
                lease_until = NULL,
                next_run_at = NULL,
                retry_count = 0
            """
        )
    )


def _add_operation_constraints_and_index() -> None:
    constraints = (
        (
            "length(trim(broker)) > 0 AND length(trim(account_scope)) > 0",
            "ck_liquidation_operations_account_scope",
        ),
        (
            "contract_version IN (1, 2)",
            "ck_liquidation_operations_contract_version",
        ),
        (
            "request_fingerprint IS NULL OR request_fingerprint ~ '^[0-9a-f]{64}$'",
            "ck_liquidation_operations_request_fingerprint_hex",
        ),
        (
            "cancel_scope IN ('LEGACY_NONE', 'ACCOUNT_ALL')",
            "ck_liquidation_operations_cancel_scope",
        ),
        (
            f"phase IN ({LIQUIDATION_PHASES})",
            "ck_liquidation_operations_phase",
        ),
        (
            "verification_status IN "
            "('LEGACY_UNVERIFIED', 'PENDING', 'VERIFIED', 'ERROR')",
            "ck_liquidation_operations_verification_status",
        ),
        ("version >= 0", "ck_liquidation_operations_version"),
        ("retry_count >= 0", "ck_liquidation_operations_retry_count"),
        (
            "(contract_version = 1 AND request_fingerprint IS NULL "
            "AND cancel_scope = 'LEGACY_NONE' AND phase = 'TERMINAL' "
            "AND verification_status = 'LEGACY_UNVERIFIED') OR "
            "(contract_version = 2 AND request_fingerprint IS NOT NULL "
            "AND cancel_scope = 'ACCOUNT_ALL' "
            "AND verification_status <> 'LEGACY_UNVERIFIED')",
            "ck_liquidation_operations_contract_coherence",
        ),
        (
            "(status IN ('PREPARING', 'IN_PROGRESS') AND phase <> 'TERMINAL') OR "
            "(status IN ('COMPLETED', 'PARTIAL', 'FAILED', 'NO_ASSETS') "
            "AND phase = 'TERMINAL')",
            "ck_liquidation_operations_status_phase",
        ),
    )
    for condition, name in constraints:
        op.create_check_constraint(name, "liquidation_operations", condition)

    op.create_index(
        "uq_liquidation_operations_active_account",
        "liquidation_operations",
        ["broker", "account_scope"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_LIQUIDATION_PREDICATE),
    )
    op.create_index(
        "ix_liquidation_operations_due",
        "liquidation_operations",
        ["status", "next_run_at"],
        unique=False,
    )


def _create_cancellation_table() -> None:
    op.create_table(
        "liquidation_order_cancellations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("liquidation_operation_id", sa.Integer(), nullable=False),
        sa.Column("exchange_uuid", sa.String(length=64), nullable=False),
        sa.Column("identifier", sa.String(length=64), nullable=True),
        sa.Column("market", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("initial_exchange_state", sa.String(length=16), nullable=False),
        sa.Column("ownership", sa.String(length=16), nullable=False),
        sa.Column("order_intent_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'DISCOVERED'"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "reconcile_attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("executed_volume", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("remaining_volume", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("canceling_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DISCOVERED', 'CANCELING', 'UNKNOWN', 'CONFIRMED', 'FAILED')",
            name="ck_liquidation_order_cancellations_status",
        ),
        sa.CheckConstraint(
            "ownership IN ('MANAGED', 'EXTERNAL')",
            name="ck_liquidation_order_cancellations_ownership",
        ),
        sa.CheckConstraint(
            "side IN ('bid', 'ask')",
            name="ck_liquidation_order_cancellations_side",
        ),
        sa.CheckConstraint(
            "initial_exchange_state IN ('wait', 'watch')",
            name="ck_liquidation_order_cancellations_initial_state",
        ),
        sa.CheckConstraint(
            "attempt_count BETWEEN 0 AND 3",
            name="ck_liquidation_order_cancellations_attempt_count",
        ),
        sa.CheckConstraint(
            "reconcile_attempt_count >= 0",
            name="ck_liquidation_order_cancellations_reconcile_attempt_count",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_liquidation_order_cancellations_version",
        ),
        sa.CheckConstraint(
            "executed_volume IS NULL OR executed_volume >= 0",
            name="ck_liquidation_order_cancellations_executed_volume",
        ),
        sa.CheckConstraint(
            "remaining_volume IS NULL OR remaining_volume >= 0",
            name="ck_liquidation_order_cancellations_remaining_volume",
        ),
        sa.CheckConstraint(
            "(ownership = 'MANAGED' AND order_intent_id IS NOT NULL) OR "
            "(ownership = 'EXTERNAL' AND order_intent_id IS NULL)",
            name="ck_liquidation_order_cancellations_ownership_intent",
        ),
        sa.CheckConstraint(
            "status <> 'CANCELING' OR (attempt_count >= 1 AND canceling_at IS NOT NULL)",
            name="ck_liquidation_order_cancellations_canceling_state",
        ),
        sa.CheckConstraint(
            "status NOT IN ('CONFIRMED', 'FAILED') OR resolved_at IS NOT NULL",
            name="ck_liquidation_order_cancellations_resolved_state",
        ),
        sa.ForeignKeyConstraint(
            ["liquidation_operation_id"],
            ["liquidation_operations.id"],
            name="fk_liquidation_order_cancellations_operation_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_intent_id"],
            ["order_intents.id"],
            name="fk_liquidation_order_cancellations_order_intent_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "liquidation_operation_id",
            "exchange_uuid",
            name="uq_liquidation_order_cancellations_operation_uuid",
        ),
    )
    op.create_index(
        "ix_liquidation_order_cancellations_liquidation_operation_id",
        "liquidation_order_cancellations",
        ["liquidation_operation_id"],
        unique=False,
    )
    op.create_index(
        "ix_liquidation_order_cancellations_order_intent_id",
        "liquidation_order_cancellations",
        ["order_intent_id"],
        unique=False,
    )
    op.create_index(
        "ix_liquidation_order_cancellations_due",
        "liquidation_order_cancellations",
        ["status", "next_retry_at"],
        unique=False,
    )


def _create_operation_event_table() -> None:
    op.create_table(
        "liquidation_operation_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("liquidation_operation_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("operation_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("from_phase", sa.String(length=48), nullable=True),
        sa.Column("to_phase", sa.String(length=48), nullable=True),
        sa.Column(
            "source",
            sa.String(length=32),
            server_default=sa.text("'SYSTEM'"),
            nullable=False,
        ),
        sa.Column("actor_ref", sa.String(length=128), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('OPERATION_CREATED', 'PHASE_CHANGED', 'ORDER_DISCOVERED', "
            "'CANCEL_REQUESTED', 'CANCEL_RESOLVED', 'ACCOUNT_OBSERVED', "
            "'TARGET_SNAPSHOTTED', 'ORDER_SUBMITTED', 'ORDER_RESOLVED', "
            "'VERIFICATION_RECORDED', 'OPERATION_TERMINATED', 'ERROR_RECORDED')",
            name="ck_liquidation_operation_events_event_type",
        ),
        sa.CheckConstraint(
            f"from_phase IS NULL OR from_phase IN ({LIQUIDATION_PHASES})",
            name="ck_liquidation_operation_events_from_phase",
        ),
        sa.CheckConstraint(
            f"to_phase IS NULL OR to_phase IN ({LIQUIDATION_PHASES})",
            name="ck_liquidation_operation_events_to_phase",
        ),
        sa.CheckConstraint(
            "source IN ('REST', 'SLACK', 'TELEGRAM', 'SYSTEM', 'AUTH_FAILURE', 'WORKER')",
            name="ck_liquidation_operation_events_source",
        ),
        sa.CheckConstraint(
            "sequence >= 1",
            name="ck_liquidation_operation_events_sequence",
        ),
        sa.CheckConstraint(
            "operation_version >= 0",
            name="ck_liquidation_operation_events_operation_version",
        ),
        sa.ForeignKeyConstraint(
            ["liquidation_operation_id"],
            ["liquidation_operations.id"],
            name="fk_liquidation_operation_events_operation_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "liquidation_operation_id",
            "sequence",
            name="uq_liquidation_operation_events_operation_sequence",
        ),
    )
    op.create_index(
        "ix_liquidation_operation_events_liquidation_operation_id",
        "liquidation_operation_events",
        ["liquidation_operation_id"],
        unique=False,
    )


def _create_hard_delete_guards() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION reject_liquidation_operation_event_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $atm_p0_004_append_only$
            BEGIN
                RAISE EXCEPTION 'liquidation_operation_events is append-only';
            END
            $atm_p0_004_append_only$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_liquidation_operation_events_append_only
            BEFORE UPDATE OR DELETE ON liquidation_operation_events
            FOR EACH ROW EXECUTE FUNCTION reject_liquidation_operation_event_mutation()
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION reject_liquidation_proof_record_delete()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $atm_p0_004_no_delete$
            BEGIN
                RAISE EXCEPTION 'liquidation proof records cannot be hard-deleted';
            END
            $atm_p0_004_no_delete$
            """
        )
    )
    for table_name in ("liquidation_operations", "liquidation_order_cancellations"):
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_{table_name}_no_delete
                BEFORE DELETE ON {table_name}
                FOR EACH ROW EXECUTE FUNCTION reject_liquidation_proof_record_delete()
                """
            )
        )


def downgrade() -> None:
    """v2/audit 데이터가 없을 때만 청산 v2 증거 원장을 제거합니다."""
    _require_safe_downgrade()

    op.execute(
        "DROP TRIGGER trg_liquidation_order_cancellations_no_delete "
        "ON liquidation_order_cancellations"
    )
    op.execute("DROP TRIGGER trg_liquidation_operations_no_delete ON liquidation_operations")
    op.execute("DROP FUNCTION reject_liquidation_proof_record_delete()")
    op.execute(
        "DROP TRIGGER trg_liquidation_operation_events_append_only "
        "ON liquidation_operation_events"
    )
    op.execute("DROP FUNCTION reject_liquidation_operation_event_mutation()")

    op.drop_index(
        "ix_liquidation_operation_events_liquidation_operation_id",
        table_name="liquidation_operation_events",
    )
    op.drop_table("liquidation_operation_events")
    op.drop_index(
        "ix_liquidation_order_cancellations_due",
        table_name="liquidation_order_cancellations",
    )
    op.drop_index(
        "ix_liquidation_order_cancellations_order_intent_id",
        table_name="liquidation_order_cancellations",
    )
    op.drop_index(
        "ix_liquidation_order_cancellations_liquidation_operation_id",
        table_name="liquidation_order_cancellations",
    )
    op.drop_table("liquidation_order_cancellations")

    op.drop_index(
        "ix_liquidation_operations_due",
        table_name="liquidation_operations",
    )
    op.drop_index(
        "uq_liquidation_operations_active_account",
        table_name="liquidation_operations",
    )
    for name in (
        "ck_liquidation_operations_status_phase",
        "ck_liquidation_operations_contract_coherence",
        "ck_liquidation_operations_retry_count",
        "ck_liquidation_operations_version",
        "ck_liquidation_operations_verification_status",
        "ck_liquidation_operations_phase",
        "ck_liquidation_operations_cancel_scope",
        "ck_liquidation_operations_request_fingerprint_hex",
        "ck_liquidation_operations_contract_version",
        "ck_liquidation_operations_account_scope",
    ):
        op.drop_constraint(name, "liquidation_operations", type_="check")

    for column_name in (
        "remaining_summary",
        "order_summary",
        "cancellation_summary",
        "final_accounts_observed_at",
        "final_account_snapshot",
        "post_cancel_accounts_observed_at",
        "post_cancel_account_snapshot",
        "initial_accounts_observed_at",
        "initial_account_snapshot",
        "retry_count",
        "next_run_at",
        "lease_until",
        "version",
        "verification_status",
        "phase",
        "cancel_scope",
        "request_fingerprint",
        "contract_version",
        "account_scope",
        "broker",
    ):
        op.drop_column("liquidation_operations", column_name)


def _require_safe_downgrade() -> None:
    if context.is_offline_mode():
        _emit_common_preflight(block_name="atm_p0_004_downgrade", operation="downgrade")
        _emit_downgrade_data_guard()
        return

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("ATM-P0-004 downgrade preflight requires PostgreSQL")
    _acquire_advisory_lock(bind, operation="downgrade")
    _require_rollout_disabled(bind, operation="downgrade")
    _require_gate_blocked(bind, operation="downgrade")
    _require_no_active_liquidation(bind, operation="downgrade")
    _require_no_blocking_intent(bind, operation="downgrade")
    _require_no_v2_or_audit_data(bind)


def _require_no_v2_or_audit_data(bind) -> None:
    safe = bind.execute(sa.text(_downgrade_data_guard_query())).scalar_one()
    if not safe:
        raise RuntimeError("ATM-P0-004 downgrade blocked: v2 or audit data exists")


def _downgrade_data_guard_query() -> str:
    return """
        SELECT NOT EXISTS (SELECT 1 FROM liquidation_order_cancellations)
           AND NOT EXISTS (SELECT 1 FROM liquidation_operation_events)
           AND NOT EXISTS (
                SELECT 1
                FROM liquidation_operations
                WHERE contract_version <> 1
                   OR broker <> 'UPBIT'
                   OR account_scope <> 'primary'
                   OR request_fingerprint IS NOT NULL
                   OR cancel_scope <> 'LEGACY_NONE'
                   OR phase <> 'TERMINAL'
                   OR verification_status <> 'LEGACY_UNVERIFIED'
                   OR version <> 0
                   OR lease_until IS NOT NULL
                   OR next_run_at IS NOT NULL
                   OR retry_count <> 0
                   OR initial_account_snapshot IS NOT NULL
                   OR initial_accounts_observed_at IS NOT NULL
                   OR post_cancel_account_snapshot IS NOT NULL
                   OR post_cancel_accounts_observed_at IS NOT NULL
                   OR final_account_snapshot IS NOT NULL
                   OR final_accounts_observed_at IS NOT NULL
                   OR cancellation_summary IS NOT NULL
                   OR order_summary IS NOT NULL
                   OR remaining_summary IS NOT NULL
           )
    """


def _emit_downgrade_data_guard() -> None:
    op.execute(
        sa.text(
            f"""
            DO $atm_p0_004_downgrade_data$
            BEGIN
                IF NOT ({_downgrade_data_guard_query()}) THEN
                    RAISE EXCEPTION
                        'ATM-P0-004 downgrade blocked: v2 or audit data exists';
                END IF;
            END
            $atm_p0_004_downgrade_data$;
            """
        )
    )


def _acquire_advisory_lock(bind, *, operation: str) -> None:
    acquired = bind.execute(
        sa.text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
        {"lock_key": LIVE_ORDER_ADVISORY_LOCK_KEY},
    ).scalar_one()
    if not acquired:
        raise RuntimeError(f"ATM-P0-004 {operation} blocked: advisory lock is busy")


def _require_rollout_disabled(bind, *, operation: str) -> None:
    disabled = bind.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM system_configs
                WHERE config_key = 'live_order_v2_enabled'
                  AND lower(btrim(config_value)) = 'false'
            )
            """
        )
    ).scalar_one()
    if not disabled:
        raise RuntimeError(
            f"ATM-P0-004 {operation} blocked: live_order_v2_enabled is not false"
        )


def _require_gate_blocked(bind, *, operation: str) -> None:
    blocked = bind.execute(
        sa.text(
            """
            SELECT EXISTS (SELECT 1 FROM live_order_controls)
               AND NOT EXISTS (
                    SELECT 1
                    FROM live_order_controls
                    WHERE mode <> 'BLOCK_ALL'
                       OR active_liquidation_operation_id IS NOT NULL
               )
            """
        )
    ).scalar_one()
    if not blocked:
        raise RuntimeError(f"ATM-P0-004 {operation} blocked: controls are not BLOCK_ALL")


def _require_no_active_liquidation(bind, *, operation: str) -> None:
    absent = bind.execute(
        sa.text(
            f"""
            SELECT NOT EXISTS (
                SELECT 1
                FROM liquidation_operations
                WHERE ({UNSAFE_LIQUIDATION_PREDICATE})
            )
            """
        )
    ).scalar_one()
    if not absent:
        raise RuntimeError(f"ATM-P0-004 {operation} blocked: active liquidation exists")


def _require_no_blocking_intent(bind, *, operation: str) -> None:
    absent = bind.execute(
        sa.text(
            f"""
            SELECT NOT EXISTS (
                SELECT 1
                FROM order_intents
                WHERE ({ORDER_INTENT_BLOCKING_PREDICATE})
            )
            """
        )
    ).scalar_one()
    if not absent:
        raise RuntimeError(f"ATM-P0-004 {operation} blocked: blocking order intent exists")


def _emit_common_preflight(*, block_name: str, operation: str) -> None:
    op.execute(
        sa.text(
            f"""
            DO ${block_name}$
            BEGIN
                IF NOT pg_try_advisory_xact_lock({LIVE_ORDER_ADVISORY_LOCK_KEY}) THEN
                    RAISE EXCEPTION
                        'ATM-P0-004 {operation} blocked: advisory lock is busy';
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM system_configs
                    WHERE config_key = 'live_order_v2_enabled'
                      AND lower(btrim(config_value)) = 'false'
                ) THEN
                    RAISE EXCEPTION
                        'ATM-P0-004 {operation} blocked: live_order_v2_enabled is not false';
                END IF;

                IF NOT EXISTS (SELECT 1 FROM live_order_controls)
                   OR EXISTS (
                        SELECT 1
                        FROM live_order_controls
                        WHERE mode <> 'BLOCK_ALL'
                           OR active_liquidation_operation_id IS NOT NULL
                   ) THEN
                    RAISE EXCEPTION
                        'ATM-P0-004 {operation} blocked: controls are not BLOCK_ALL';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM liquidation_operations
                    WHERE ({UNSAFE_LIQUIDATION_PREDICATE})
                ) THEN
                    RAISE EXCEPTION
                        'ATM-P0-004 {operation} blocked: active liquidation exists';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM order_intents
                    WHERE ({ORDER_INTENT_BLOCKING_PREDICATE})
                ) THEN
                    RAISE EXCEPTION
                        'ATM-P0-004 {operation} blocked: blocking order intent exists';
                END IF;
            END
            ${block_name}$;
            """
        )
    )
