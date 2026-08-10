"""feat(db): 거래 모드 제어 원장 추가

Revision ID: c4f8a2d7e1b3
Revises: a91f3e7c5b2d
Create Date: 2026-07-11 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "c4f8a2d7e1b3"
down_revision: Union[str, Sequence[str], None] = "a91f3e7c5b2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LIVE_ORDER_ADVISORY_LOCK_KEY = 5740495976316385210
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
ACTIVE_LIQUIDATION_PREDICATE = """
emergency_authorization_status = 'ACTIVE'
OR status IN ('PREPARING', 'IN_PROGRESS')
"""


def upgrade() -> None:
    """안전 preflight 뒤 거래 모드를 paper로 강등하고 제어 원장을 추가합니다."""
    _require_safe_upgrade()
    _create_trading_mode_tables()
    _seed_fail_closed_trading_mode()
    _create_append_only_guard()
    _set_legacy_state_fail_closed()


def _require_safe_upgrade() -> None:
    if context.is_offline_mode():
        _emit_preflight(block_name="atm_p0_003_upgrade", require_trading_mode=False)
        return

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("ATM-P0-003 upgrade preflight requires PostgreSQL")
    _acquire_advisory_lock(bind, operation="upgrade")
    _require_rollout_disabled(bind, operation="upgrade")
    _require_gate_blocked(bind, operation="upgrade")
    _require_no_active_liquidation(bind, operation="upgrade")
    _require_no_blocking_intent(bind, operation="upgrade")


def _create_trading_mode_tables() -> None:
    op.create_table(
        "trading_mode_controls",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column(
            "mode",
            sa.String(length=16),
            server_default=sa.text("'paper'"),
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
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.CheckConstraint("id = 1", name="ck_trading_mode_controls_singleton"),
        sa.CheckConstraint(
            "mode IN ('paper', 'live')",
            name="ck_trading_mode_controls_mode",
        ),
        sa.CheckConstraint("version >= 1", name="ck_trading_mode_controls_version"),
        sa.CheckConstraint(
            "changed_source IN ('REST', 'SLACK', 'TELEGRAM', 'SYSTEM')",
            name="ck_trading_mode_controls_changed_source",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "trading_mode_control_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("control_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("reauth_jti", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("from_mode", sa.String(length=16), nullable=True),
        sa.Column("to_mode", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("actor_ref", sa.String(length=128), nullable=True),
        sa.Column("legacy_raw_value", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('INITIALIZED', 'LIVE_ENABLED', 'PAPER_CONFIRMED')",
            name="ck_trading_mode_control_events_action",
        ),
        sa.CheckConstraint(
            "from_mode IS NULL OR from_mode IN ('paper', 'live')",
            name="ck_trading_mode_control_events_from_mode",
        ),
        sa.CheckConstraint(
            "to_mode IN ('paper', 'live')",
            name="ck_trading_mode_control_events_to_mode",
        ),
        sa.CheckConstraint(
            "source IN ('REST', 'SLACK', 'TELEGRAM', 'SYSTEM')",
            name="ck_trading_mode_control_events_source",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_trading_mode_control_events_version",
        ),
        sa.CheckConstraint(
            "request_fingerprint IS NULL OR request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_trading_mode_control_events_request_fingerprint_hex",
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR request_id ~* "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_trading_mode_control_events_request_id_uuid4",
        ),
        sa.CheckConstraint(
            "reauth_jti IS NULL OR reauth_jti ~* "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_trading_mode_control_events_reauth_jti_uuid4",
        ),
        sa.CheckConstraint(
            "(request_id IS NULL AND request_fingerprint IS NULL) OR "
            "(request_id IS NOT NULL AND request_fingerprint IS NOT NULL)",
            name="ck_trading_mode_control_events_request_pair",
        ),
        sa.CheckConstraint(
            "(action = 'INITIALIZED' AND from_mode IS NULL AND to_mode = 'paper' "
            "AND request_id IS NULL AND request_fingerprint IS NULL AND reauth_jti IS NULL) OR "
            "(action = 'LIVE_ENABLED' AND from_mode = 'paper' AND to_mode = 'live' "
            "AND request_id IS NOT NULL AND request_fingerprint IS NOT NULL "
            "AND reauth_jti IS NOT NULL) OR "
            "(action = 'PAPER_CONFIRMED' AND from_mode IN ('paper', 'live') "
            "AND to_mode = 'paper' AND request_id IS NOT NULL "
            "AND request_fingerprint IS NOT NULL AND reauth_jti IS NULL)",
            name="ck_trading_mode_control_events_transition",
        ),
        sa.ForeignKeyConstraint(
            ["control_id"],
            ["trading_mode_controls.id"],
            name="fk_trading_mode_control_events_control_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "request_id",
            name="uq_trading_mode_control_events_request_id",
        ),
        sa.UniqueConstraint(
            "reauth_jti",
            name="uq_trading_mode_control_events_reauth_jti",
        ),
        sa.UniqueConstraint(
            "control_id",
            "version",
            name="uq_trading_mode_control_events_control_version",
        ),
    )
    op.create_index(
        "ix_trading_mode_control_events_control_id",
        "trading_mode_control_events",
        ["control_id"],
        unique=False,
    )


def _seed_fail_closed_trading_mode() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO trading_mode_controls (
                id,
                mode,
                version,
                reason_code,
                reason_text,
                changed_source,
                changed_actor_ref,
                changed_at
            )
            VALUES (
                1,
                'paper',
                1,
                'MIGRATION_FAIL_CLOSED',
                'P0-003 migration forced every legacy trading mode to paper',
                'SYSTEM',
                'alembic:c4f8a2d7e1b3',
                now()
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO trading_mode_control_events (
                control_id,
                version,
                request_id,
                request_fingerprint,
                reauth_jti,
                action,
                from_mode,
                to_mode,
                reason_code,
                reason_text,
                source,
                actor_ref,
                legacy_raw_value
            )
            SELECT
                control.id,
                control.version,
                NULL,
                NULL,
                NULL,
                'INITIALIZED',
                NULL,
                'paper',
                control.reason_code,
                control.reason_text,
                control.changed_source,
                control.changed_actor_ref,
                (
                    SELECT config_value
                    FROM system_configs
                    WHERE config_key = 'trading_mode'
                )
            FROM trading_mode_controls AS control
            WHERE control.id = 1
            """
        )
    )


def _create_append_only_guard() -> None:
    op.execute(
        sa.text(
            """
            CREATE FUNCTION reject_trading_mode_control_event_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $atm_p0_003_append_only$
            BEGIN
                RAISE EXCEPTION 'trading_mode_control_events is append-only';
            END
            $atm_p0_003_append_only$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_trading_mode_control_events_append_only
            BEFORE UPDATE OR DELETE ON trading_mode_control_events
            FOR EACH ROW EXECUTE FUNCTION reject_trading_mode_control_event_mutation()
            """
        )
    )


def _set_legacy_state_fail_closed() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO system_configs (config_key, config_value, description)
            VALUES (
                'trading_mode',
                'paper',
                '거래 실행 모드 legacy mirror(paper/live)'
            )
            ON CONFLICT (config_key) DO UPDATE
            SET config_value = 'paper',
                description = EXCLUDED.description
            """
        )
    )
    op.execute(sa.text("UPDATE bot_configs SET is_active = false WHERE is_active IS DISTINCT FROM false"))
    op.alter_column(
        "bot_configs",
        "is_active",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.text("false"),
    )


def downgrade() -> None:
    """모든 안전 상태를 확인하고 live를 복원하지 않은 채 신규 원장만 제거합니다."""
    _require_safe_downgrade()
    _set_legacy_state_fail_closed()
    op.execute("DROP TRIGGER trg_trading_mode_control_events_append_only ON trading_mode_control_events")
    op.execute("DROP FUNCTION reject_trading_mode_control_event_mutation()")
    op.drop_index(
        "ix_trading_mode_control_events_control_id",
        table_name="trading_mode_control_events",
    )
    op.drop_table("trading_mode_control_events")
    op.drop_table("trading_mode_controls")


def _require_safe_downgrade() -> None:
    if context.is_offline_mode():
        _emit_preflight(block_name="atm_p0_003_downgrade", require_trading_mode=True)
        return

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("ATM-P0-003 downgrade preflight requires PostgreSQL")
    _acquire_advisory_lock(bind, operation="downgrade")
    _require_rollout_disabled(bind, operation="downgrade")
    _require_gate_blocked(bind, operation="downgrade")
    _require_no_active_liquidation(bind, operation="downgrade")
    _require_no_blocking_intent(bind, operation="downgrade")

    trading_mode_safe = bind.execute(
        sa.text(
            """
            SELECT EXISTS (
                       SELECT 1
                       FROM trading_mode_controls
                       WHERE id = 1 AND mode = 'paper'
                   )
               AND NOT EXISTS (
                       SELECT 1
                       FROM trading_mode_controls
                       WHERE id <> 1 OR mode <> 'paper'
                   )
               AND EXISTS (
                       SELECT 1
                       FROM system_configs
                       WHERE config_key = 'trading_mode' AND config_value = 'paper'
                   )
            """
        )
    ).scalar_one()
    if not trading_mode_safe:
        raise RuntimeError("ATM-P0-003 downgrade blocked: trading mode is not paper-consistent")

    all_bots_inactive = bind.execute(
        sa.text("SELECT NOT EXISTS (SELECT 1 FROM bot_configs WHERE is_active)")
    ).scalar_one()
    if not all_bots_inactive:
        raise RuntimeError("ATM-P0-003 downgrade blocked: active bot config exists")


def _acquire_advisory_lock(bind, *, operation: str) -> None:
    acquired = bind.execute(
        sa.text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
        {"lock_key": LIVE_ORDER_ADVISORY_LOCK_KEY},
    ).scalar_one()
    if not acquired:
        raise RuntimeError(f"ATM-P0-003 {operation} blocked: advisory lock is busy")


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
            f"ATM-P0-003 {operation} blocked: live_order_v2_enabled is not false"
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
        raise RuntimeError(f"ATM-P0-003 {operation} blocked: controls are not BLOCK_ALL")


def _require_no_active_liquidation(bind, *, operation: str) -> None:
    absent = bind.execute(
        sa.text(
            f"""
            SELECT NOT EXISTS (
                SELECT 1
                FROM liquidation_operations
                WHERE ({ACTIVE_LIQUIDATION_PREDICATE})
            )
            """
        )
    ).scalar_one()
    if not absent:
        raise RuntimeError(f"ATM-P0-003 {operation} blocked: active liquidation exists")


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
        raise RuntimeError(f"ATM-P0-003 {operation} blocked: blocking order intent exists")


def _emit_preflight(*, block_name: str, require_trading_mode: bool) -> None:
    trading_mode_guard = ""
    if require_trading_mode:
        trading_mode_guard = """
                IF NOT EXISTS (
                    SELECT 1
                    FROM trading_mode_controls
                    WHERE id = 1 AND mode = 'paper'
                ) OR EXISTS (
                    SELECT 1
                    FROM trading_mode_controls
                    WHERE id <> 1 OR mode <> 'paper'
                ) OR NOT EXISTS (
                    SELECT 1
                    FROM system_configs
                    WHERE config_key = 'trading_mode' AND config_value = 'paper'
                ) THEN
                    RAISE EXCEPTION
                        'ATM-P0-003 downgrade blocked: trading mode is not paper-consistent';
                END IF;

                IF EXISTS (SELECT 1 FROM bot_configs WHERE is_active) THEN
                    RAISE EXCEPTION
                        'ATM-P0-003 downgrade blocked: active bot config exists';
                END IF;
        """

    operation = "downgrade" if require_trading_mode else "upgrade"
    op.execute(
        sa.text(
            f"""
            DO ${block_name}$
            BEGIN
                IF NOT pg_try_advisory_xact_lock({LIVE_ORDER_ADVISORY_LOCK_KEY}) THEN
                    RAISE EXCEPTION
                        'ATM-P0-003 {operation} blocked: advisory lock is busy';
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM system_configs
                    WHERE config_key = 'live_order_v2_enabled'
                      AND lower(btrim(config_value)) = 'false'
                ) THEN
                    RAISE EXCEPTION
                        'ATM-P0-003 {operation} blocked: live_order_v2_enabled is not false';
                END IF;

                IF NOT EXISTS (SELECT 1 FROM live_order_controls)
                   OR EXISTS (
                        SELECT 1
                        FROM live_order_controls
                        WHERE mode <> 'BLOCK_ALL'
                           OR active_liquidation_operation_id IS NOT NULL
                   ) THEN
                    RAISE EXCEPTION
                        'ATM-P0-003 {operation} blocked: controls are not BLOCK_ALL';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM liquidation_operations
                    WHERE ({ACTIVE_LIQUIDATION_PREDICATE})
                ) THEN
                    RAISE EXCEPTION
                        'ATM-P0-003 {operation} blocked: active liquidation exists';
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM order_intents
                    WHERE ({ORDER_INTENT_BLOCKING_PREDICATE})
                ) THEN
                    RAISE EXCEPTION
                        'ATM-P0-003 {operation} blocked: blocking order intent exists';
                END IF;
                {trading_mode_guard}
            END
            ${block_name}$;
            """
        )
    )
