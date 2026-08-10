"""feat(db): 전역 실주문 제어 원장 추가

Revision ID: a91f3e7c5b2d
Revises: e7b4c9a1d2f6
Create Date: 2026-07-10 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "a91f3e7c5b2d"
down_revision: Union[str, Sequence[str], None] = "e7b4c9a1d2f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DOWNGRADE_ADVISORY_LOCK_KEY = 5740495976316385210
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


def upgrade() -> None:
    """실주문 허가 상태와 append-only 감사 이벤트를 추가합니다."""
    _add_liquidation_authorization_columns()
    _add_order_intent_control_audit_columns()
    _create_live_order_control_tables()
    _create_control_foreign_keys()
    _replace_order_intent_liquidation_foreign_key(ondelete="RESTRICT")
    _backfill_liquidation_authorizations()
    _seed_fail_closed_control()


def _add_liquidation_authorization_columns() -> None:
    op.add_column(
        "liquidation_operations",
        sa.Column(
            "emergency_authorization_status",
            sa.String(length=16),
            server_default=sa.text("'REVOKED'"),
            nullable=False,
        ),
    )
    op.add_column(
        "liquidation_operations",
        sa.Column("emergency_authorized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "liquidation_operations",
        sa.Column("emergency_control_generation", sa.Integer(), nullable=True),
    )
    op.add_column(
        "liquidation_operations",
        sa.Column("emergency_control_event_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "liquidation_operations",
        sa.Column("emergency_authorized_source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "liquidation_operations",
        sa.Column(
            "emergency_revoked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.add_column(
        "liquidation_operations",
        sa.Column(
            "emergency_revocation_reason",
            sa.Text(),
            server_default=sa.text("'FAIL_CLOSED_NOT_AUTHORIZED'"),
            nullable=True,
        ),
    )
    op.add_column(
        "liquidation_operations",
        sa.Column("emergency_closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_liquidation_operations_emergency_authorization_status",
        "liquidation_operations",
        "emergency_authorization_status IN ('ACTIVE', 'REVOKED', 'CLOSED')",
    )
    op.create_check_constraint(
        "ck_liquidation_operations_emergency_control_generation",
        "liquidation_operations",
        "emergency_control_generation IS NULL OR emergency_control_generation >= 1",
    )
    op.create_check_constraint(
        "ck_liquidation_operations_emergency_authorized_source",
        "liquidation_operations",
        "emergency_authorized_source IS NULL OR emergency_authorized_source IN "
        "('REST', 'SLACK', 'TELEGRAM', 'SYSTEM', 'AUTH_FAILURE')",
    )
    op.create_check_constraint(
        "ck_liquidation_operations_emergency_authorization_coherence",
        "liquidation_operations",
        "(emergency_authorization_status = 'ACTIVE' AND "
        "emergency_authorized_at IS NOT NULL AND "
        "emergency_control_generation IS NOT NULL AND "
        "emergency_control_event_id IS NOT NULL AND "
        "emergency_authorized_source IS NOT NULL AND "
        "emergency_revoked_at IS NULL AND emergency_revocation_reason IS NULL AND "
        "emergency_closed_at IS NULL) OR "
        "(emergency_authorization_status = 'REVOKED' AND "
        "emergency_revoked_at IS NOT NULL AND "
        "emergency_revocation_reason IS NOT NULL AND "
        "length(trim(emergency_revocation_reason)) > 0 AND "
        "emergency_closed_at IS NULL) OR "
        "(emergency_authorization_status = 'CLOSED' AND "
        "emergency_closed_at IS NOT NULL AND emergency_revoked_at IS NULL AND "
        "emergency_revocation_reason IS NULL)",
    )
    op.create_index(
        "ix_liquidation_operations_emergency_control_event_id",
        "liquidation_operations",
        ["emergency_control_event_id"],
        unique=False,
    )


def _add_order_intent_control_audit_columns() -> None:
    op.add_column(
        "order_intents",
        sa.Column("prepared_control_generation", sa.Integer(), nullable=True),
    )
    op.add_column(
        "order_intents",
        sa.Column("prepared_control_mode", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "order_intents",
        sa.Column("control_generation", sa.Integer(), nullable=True),
    )
    op.add_column(
        "order_intents",
        sa.Column("control_mode", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "order_intents",
        sa.Column("control_event_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "order_intents",
        sa.Column("submission_authorized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_order_intents_prepared_control_generation",
        "order_intents",
        "prepared_control_generation IS NULL OR prepared_control_generation >= 1",
    )
    op.create_check_constraint(
        "ck_order_intents_control_generation",
        "order_intents",
        "control_generation IS NULL OR control_generation >= 1",
    )
    op.create_check_constraint(
        "ck_order_intents_prepared_control_mode",
        "order_intents",
        "prepared_control_mode IS NULL OR "
        "prepared_control_mode IN ('ARMED', 'EXIT_ONLY', 'BLOCK_ALL')",
    )
    op.create_check_constraint(
        "ck_order_intents_control_mode",
        "order_intents",
        "control_mode IS NULL OR control_mode IN ('ARMED', 'EXIT_ONLY')",
    )
    op.create_check_constraint(
        "ck_order_intents_prepared_control_snapshot",
        "order_intents",
        "(prepared_control_generation IS NULL AND prepared_control_mode IS NULL) OR "
        "(prepared_control_generation IS NOT NULL AND prepared_control_mode IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_order_intents_submission_authorization_snapshot",
        "order_intents",
        "(control_generation IS NULL AND control_mode IS NULL AND "
        "control_event_id IS NULL AND submission_authorized_at IS NULL) OR "
        "(control_generation IS NOT NULL AND control_mode IS NOT NULL AND "
        "control_event_id IS NOT NULL AND submission_authorized_at IS NOT NULL)",
    )
    op.create_index(
        "ix_order_intents_control_event_id",
        "order_intents",
        ["control_event_id"],
        unique=False,
    )


def _create_live_order_control_tables() -> None:
    op.create_table(
        "live_order_controls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("account_scope", sa.String(length=64), nullable=False),
        sa.Column(
            "mode",
            sa.String(length=16),
            server_default=sa.text("'BLOCK_ALL'"),
            nullable=False,
        ),
        sa.Column("active_liquidation_operation_id", sa.Integer(), nullable=True),
        sa.Column(
            "generation",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column(
            "changed_source",
            sa.String(length=32),
            server_default=sa.text("'SYSTEM'"),
            nullable=False,
        ),
        sa.Column("changed_actor_ref", sa.String(length=128), nullable=True),
        sa.Column("armed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
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
            "mode IN ('ARMED', 'EXIT_ONLY', 'BLOCK_ALL')",
            name="ck_live_order_controls_mode",
        ),
        sa.CheckConstraint(
            "changed_source IN ('REST', 'SLACK', 'TELEGRAM', 'SYSTEM', 'AUTH_FAILURE')",
            name="ck_live_order_controls_changed_source",
        ),
        sa.CheckConstraint("generation >= 1", name="ck_live_order_controls_generation"),
        sa.CheckConstraint("version >= 1", name="ck_live_order_controls_version"),
        sa.CheckConstraint(
            "(mode = 'EXIT_ONLY' AND active_liquidation_operation_id IS NOT NULL) OR "
            "(mode IN ('ARMED', 'BLOCK_ALL') AND active_liquidation_operation_id IS NULL)",
            name="ck_live_order_controls_active_liquidation",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "broker",
            "account_scope",
            name="uq_live_order_controls_broker_account_scope",
        ),
    )
    op.create_index(
        "ix_live_order_controls_active_liquidation_operation_id",
        "live_order_controls",
        ["active_liquidation_operation_id"],
        unique=False,
    )

    op.create_table(
        "live_order_control_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("control_id", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("from_mode", sa.String(length=16), nullable=True),
        sa.Column("to_mode", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("actor_ref", sa.String(length=128), nullable=True),
        sa.Column("liquidation_operation_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('INITIALIZED', 'ARMED', 'BLOCKED', 'LIQUIDATION_AUTHORIZED', "
            "'LIQUIDATION_REVOKED', 'LIQUIDATION_CLOSED')",
            name="ck_live_order_control_events_action",
        ),
        sa.CheckConstraint(
            "from_mode IS NULL OR from_mode IN ('ARMED', 'EXIT_ONLY', 'BLOCK_ALL')",
            name="ck_live_order_control_events_from_mode",
        ),
        sa.CheckConstraint(
            "to_mode IN ('ARMED', 'EXIT_ONLY', 'BLOCK_ALL')",
            name="ck_live_order_control_events_to_mode",
        ),
        sa.CheckConstraint(
            "source IN ('REST', 'SLACK', 'TELEGRAM', 'SYSTEM', 'AUTH_FAILURE')",
            name="ck_live_order_control_events_source",
        ),
        sa.CheckConstraint(
            "request_fingerprint IS NULL OR request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_live_order_control_events_request_fingerprint_hex",
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR request_id ~* "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_live_order_control_events_request_id_uuid4",
        ),
        sa.CheckConstraint(
            "(request_id IS NULL AND request_fingerprint IS NULL) OR "
            "(request_id IS NOT NULL AND request_fingerprint IS NOT NULL)",
            name="ck_live_order_control_events_request_pair",
        ),
        sa.CheckConstraint(
            "(action IN ('LIQUIDATION_AUTHORIZED', 'LIQUIDATION_REVOKED', "
            "'LIQUIDATION_CLOSED') AND liquidation_operation_id IS NOT NULL) OR "
            "(action IN ('INITIALIZED', 'ARMED', 'BLOCKED') AND "
            "liquidation_operation_id IS NULL)",
            name="ck_live_order_control_events_liquidation_action",
        ),
        sa.CheckConstraint("generation >= 1", name="ck_live_order_control_events_generation"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_live_order_control_events_request_id"),
    )
    op.create_index(
        "ix_live_order_control_events_control_id",
        "live_order_control_events",
        ["control_id"],
        unique=False,
    )
    op.create_index(
        "ix_live_order_control_events_liquidation_operation_id",
        "live_order_control_events",
        ["liquidation_operation_id"],
        unique=False,
    )


def _create_control_foreign_keys() -> None:
    # 순환 참조 대상 테이블을 모두 만든 뒤 named FK를 추가합니다.
    op.create_foreign_key(
        "fk_live_order_controls_active_liquidation_operation_id",
        "live_order_controls",
        "liquidation_operations",
        ["active_liquidation_operation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_live_order_control_events_control_id",
        "live_order_control_events",
        "live_order_controls",
        ["control_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_live_order_control_events_liquidation_operation_id",
        "live_order_control_events",
        "liquidation_operations",
        ["liquidation_operation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_liquidation_operations_emergency_control_event_id",
        "liquidation_operations",
        "live_order_control_events",
        ["emergency_control_event_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_order_intents_control_event_id",
        "order_intents",
        "live_order_control_events",
        ["control_event_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def _replace_order_intent_liquidation_foreign_key(*, ondelete: str) -> None:
    op.drop_constraint(
        "fk_order_intents_liquidation_operation_id",
        "order_intents",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_order_intents_liquidation_operation_id",
        "order_intents",
        "liquidation_operations",
        ["liquidation_operation_id"],
        ["id"],
        ondelete=ondelete,
    )


def _backfill_liquidation_authorizations() -> None:
    op.execute(
        sa.text(
            """
            UPDATE liquidation_operations
            SET emergency_authorization_status = CASE
                    WHEN status IN ('COMPLETED', 'PARTIAL', 'FAILED', 'NO_ASSETS')
                        THEN 'CLOSED'
                    ELSE 'REVOKED'
                END,
                emergency_closed_at = CASE
                    WHEN status IN ('COMPLETED', 'PARTIAL', 'FAILED', 'NO_ASSETS')
                        THEN COALESCE(completed_at, updated_at, created_at, now())
                    ELSE NULL
                END,
                emergency_revoked_at = CASE
                    WHEN status IN ('PREPARING', 'IN_PROGRESS') THEN now()
                    ELSE NULL
                END,
                emergency_revocation_reason = CASE
                    WHEN status IN ('PREPARING', 'IN_PROGRESS')
                        THEN 'MIGRATION_NOT_AUTHORIZED'
                    ELSE NULL
                END
            """
        )
    )


def _seed_fail_closed_control() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO live_order_controls (
                broker,
                account_scope,
                mode,
                active_liquidation_operation_id,
                generation,
                version,
                reason_code,
                reason_text,
                changed_source,
                changed_actor_ref,
                armed_at,
                blocked_at
            )
            VALUES (
                'UPBIT',
                'primary',
                'BLOCK_ALL',
                NULL,
                1,
                1,
                'MIGRATION_INITIALIZED',
                'P0-002 migration fail-closed initialization',
                'SYSTEM',
                'alembic:a91f3e7c5b2d',
                NULL,
                now()
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO live_order_control_events (
                control_id,
                generation,
                request_id,
                request_fingerprint,
                action,
                from_mode,
                to_mode,
                reason_code,
                reason_text,
                source,
                actor_ref,
                liquidation_operation_id
            )
            SELECT
                id,
                generation,
                NULL,
                NULL,
                'INITIALIZED',
                NULL,
                'BLOCK_ALL',
                reason_code,
                reason_text,
                changed_source,
                changed_actor_ref,
                NULL
            FROM live_order_controls
            WHERE broker = 'UPBIT' AND account_scope = 'primary'
            """
        )
    )


def downgrade() -> None:
    """안전 조건을 확인한 뒤 실주문 제어 원장을 제거합니다."""
    _require_safe_downgrade()
    _replace_order_intent_liquidation_foreign_key(ondelete="SET NULL")
    _drop_order_intent_control_audit_columns()
    _drop_liquidation_event_foreign_key()
    _drop_live_order_control_tables()
    _drop_liquidation_authorization_columns()


def _require_safe_downgrade() -> None:
    if context.is_offline_mode():
        _emit_offline_downgrade_preflight()
        return

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("ATM-P0-002 downgrade preflight requires PostgreSQL")

    lock_acquired = bind.execute(
        sa.text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
        {"lock_key": DOWNGRADE_ADVISORY_LOCK_KEY},
    ).scalar_one()
    if not lock_acquired:
        raise RuntimeError("ATM-P0-002 downgrade blocked: advisory lock is busy")

    flag_disabled = bind.execute(
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
    if not flag_disabled:
        raise RuntimeError("ATM-P0-002 downgrade blocked: live_order_v2_enabled is not false")

    controls_blocked = bind.execute(
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
    if not controls_blocked:
        raise RuntimeError("ATM-P0-002 downgrade blocked: controls are not BLOCK_ALL")

    active_authorization_absent = bind.execute(
        sa.text(
            """
            SELECT NOT EXISTS (
                SELECT 1
                FROM liquidation_operations
                WHERE emergency_authorization_status = 'ACTIVE'
            )
            """
        )
    ).scalar_one()
    if not active_authorization_absent:
        raise RuntimeError("ATM-P0-002 downgrade blocked: active liquidation authorization exists")

    blocking_intent_absent = bind.execute(
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
    if not blocking_intent_absent:
        raise RuntimeError("ATM-P0-002 downgrade blocked: blocking order intent exists")


def _emit_offline_downgrade_preflight() -> None:
    op.execute(
        sa.text(
            f"""
            DO $atm_p0_002$
            BEGIN
                IF NOT pg_try_advisory_xact_lock({DOWNGRADE_ADVISORY_LOCK_KEY}) THEN
                    RAISE EXCEPTION
                        'ATM-P0-002 downgrade blocked: advisory lock is busy';
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM system_configs
                    WHERE config_key = 'live_order_v2_enabled'
                      AND lower(btrim(config_value)) = 'false'
                ) THEN
                    RAISE EXCEPTION
                        'ATM-P0-002 downgrade blocked: live_order_v2_enabled is not false';
                END IF;

                IF NOT EXISTS (SELECT 1 FROM live_order_controls)
                   OR EXISTS (
                        SELECT 1
                        FROM live_order_controls
                        WHERE mode <> 'BLOCK_ALL'
                           OR active_liquidation_operation_id IS NOT NULL
                   ) THEN
                    RAISE EXCEPTION
                        'ATM-P0-002 downgrade blocked: controls are not BLOCK_ALL';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM liquidation_operations
                    WHERE emergency_authorization_status = 'ACTIVE'
                ) THEN
                    RAISE EXCEPTION
                        'ATM-P0-002 downgrade blocked: active liquidation authorization exists';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM order_intents
                    WHERE ({ORDER_INTENT_BLOCKING_PREDICATE})
                ) THEN
                    RAISE EXCEPTION
                        'ATM-P0-002 downgrade blocked: blocking order intent exists';
                END IF;
            END
            $atm_p0_002$;
            """
        )
    )


def _drop_order_intent_control_audit_columns() -> None:
    op.drop_constraint(
        "fk_order_intents_control_event_id",
        "order_intents",
        type_="foreignkey",
    )
    op.drop_index("ix_order_intents_control_event_id", table_name="order_intents")
    op.drop_constraint(
        "ck_order_intents_submission_authorization_snapshot",
        "order_intents",
        type_="check",
    )
    op.drop_constraint(
        "ck_order_intents_prepared_control_snapshot",
        "order_intents",
        type_="check",
    )
    op.drop_constraint("ck_order_intents_control_mode", "order_intents", type_="check")
    op.drop_constraint(
        "ck_order_intents_prepared_control_mode",
        "order_intents",
        type_="check",
    )
    op.drop_constraint(
        "ck_order_intents_control_generation",
        "order_intents",
        type_="check",
    )
    op.drop_constraint(
        "ck_order_intents_prepared_control_generation",
        "order_intents",
        type_="check",
    )
    op.drop_column("order_intents", "submission_authorized_at")
    op.drop_column("order_intents", "control_event_id")
    op.drop_column("order_intents", "control_mode")
    op.drop_column("order_intents", "control_generation")
    op.drop_column("order_intents", "prepared_control_mode")
    op.drop_column("order_intents", "prepared_control_generation")


def _drop_liquidation_event_foreign_key() -> None:
    op.drop_constraint(
        "ck_liquidation_operations_emergency_authorization_coherence",
        "liquidation_operations",
        type_="check",
    )
    op.drop_constraint(
        "fk_liquidation_operations_emergency_control_event_id",
        "liquidation_operations",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_liquidation_operations_emergency_control_event_id",
        table_name="liquidation_operations",
    )


def _drop_live_order_control_tables() -> None:
    op.drop_constraint(
        "fk_live_order_control_events_liquidation_operation_id",
        "live_order_control_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_live_order_control_events_control_id",
        "live_order_control_events",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_live_order_control_events_liquidation_operation_id",
        table_name="live_order_control_events",
    )
    op.drop_index(
        "ix_live_order_control_events_control_id",
        table_name="live_order_control_events",
    )
    op.drop_table("live_order_control_events")

    op.drop_constraint(
        "fk_live_order_controls_active_liquidation_operation_id",
        "live_order_controls",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_live_order_controls_active_liquidation_operation_id",
        table_name="live_order_controls",
    )
    op.drop_table("live_order_controls")


def _drop_liquidation_authorization_columns() -> None:
    op.drop_constraint(
        "ck_liquidation_operations_emergency_authorized_source",
        "liquidation_operations",
        type_="check",
    )
    op.drop_constraint(
        "ck_liquidation_operations_emergency_control_generation",
        "liquidation_operations",
        type_="check",
    )
    op.drop_constraint(
        "ck_liquidation_operations_emergency_authorization_status",
        "liquidation_operations",
        type_="check",
    )
    op.drop_column("liquidation_operations", "emergency_closed_at")
    op.drop_column("liquidation_operations", "emergency_revocation_reason")
    op.drop_column("liquidation_operations", "emergency_revoked_at")
    op.drop_column("liquidation_operations", "emergency_authorized_source")
    op.drop_column("liquidation_operations", "emergency_control_event_id")
    op.drop_column("liquidation_operations", "emergency_control_generation")
    op.drop_column("liquidation_operations", "emergency_authorized_at")
    op.drop_column("liquidation_operations", "emergency_authorization_status")
