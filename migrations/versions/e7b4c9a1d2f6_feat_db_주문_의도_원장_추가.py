"""feat(db): 주문 의도 원장 추가

Revision ID: e7b4c9a1d2f6
Revises: d3a9f7c1b2e4
Create Date: 2026-07-10 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e7b4c9a1d2f6"
down_revision: Union[str, Sequence[str], None] = "d3a9f7c1b2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    """주문 제출 전후 상태를 보존하는 원장을 추가합니다."""
    op.create_table(
        "liquidation_operations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("idempotency_key", sa.String(length=36), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'PREPARING'"),
            nullable=False,
        ),
        sa.Column("target_snapshot", sa.JSON(), nullable=True),
        sa.Column("result_snapshot", sa.JSON(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
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
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('PREPARING', 'IN_PROGRESS', 'COMPLETED', 'PARTIAL', 'FAILED', 'NO_ASSETS')",
            name="ck_liquidation_operations_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_liquidation_operations_idempotency_key",
        ),
    )

    op.create_table(
        "order_intents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("intent_key", sa.String(length=64), nullable=False),
        sa.Column("identifier", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=128), nullable=False),
        sa.Column("ai_analysis_log_id", sa.Integer(), nullable=True),
        sa.Column("liquidation_operation_id", sa.Integer(), nullable=True),
        sa.Column("order_reason", sa.String(length=64), nullable=True),
        sa.Column(
            "execution_policy",
            sa.String(length=16),
            server_default=sa.text("'GENERAL'"),
            nullable=False,
        ),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("account_scope", sa.String(length=64), nullable=False),
        sa.Column("market", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("ord_type", sa.String(length=16), nullable=False),
        sa.Column("requested_price", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("requested_volume", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column(
            "submission_status",
            sa.String(length=24),
            server_default=sa.text("'PREPARED'"),
            nullable=False,
        ),
        sa.Column("exchange_uuid", sa.String(length=64), nullable=True),
        sa.Column("exchange_state", sa.String(length=16), nullable=True),
        sa.Column("executed_volume", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("executed_funds", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("average_fill_price", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("remaining_volume", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column("paid_fee", sa.Numeric(precision=38, scale=18), nullable=True),
        sa.Column(
            "projection_status",
            sa.String(length=16),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column(
            "post_attempt_count",
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
        sa.Column("next_reconcile_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconcile_lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column(
            "not_found_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("first_not_found_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_not_found_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unknown_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("projected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=64), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "submission_status IN ('PREPARED', 'SUBMITTING', 'ACCEPTED', 'REJECTED', "
            "'UNKNOWN', 'ABANDONED', 'NO_ORDER_CONFIRMED')",
            name="ck_order_intents_submission_status",
        ),
        sa.CheckConstraint(
            "projection_status IN ('PENDING', 'APPLIED', 'ERROR', 'SKIPPED')",
            name="ck_order_intents_projection_status",
        ),
        sa.CheckConstraint(
            "execution_policy IN ('GENERAL', 'EMERGENCY_EXIT')",
            name="ck_order_intents_execution_policy",
        ),
        sa.CheckConstraint(
            "exchange_state IS NULL OR exchange_state IN ('wait', 'watch', 'done', 'cancel')",
            name="ck_order_intents_exchange_state",
        ),
        sa.CheckConstraint("side IN ('bid', 'ask')", name="ck_order_intents_side"),
        sa.CheckConstraint(
            "ord_type IN ('price', 'market', 'limit', 'best')",
            name="ck_order_intents_ord_type",
        ),
        sa.CheckConstraint(
            "identifier ~ '^[0-9a-f]{32}$'",
            name="ck_order_intents_identifier_hex",
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_order_intents_request_fingerprint_hex",
        ),
        sa.CheckConstraint(
            "requested_price IS NULL OR requested_price > 0",
            name="ck_order_intents_requested_price_positive",
        ),
        sa.CheckConstraint(
            "requested_volume IS NULL OR requested_volume > 0",
            name="ck_order_intents_requested_volume_positive",
        ),
        sa.CheckConstraint(
            "(ord_type = 'price' AND side = 'bid' AND requested_price IS NOT NULL "
            "AND requested_volume IS NULL) OR "
            "(ord_type = 'market' AND side = 'ask' AND requested_volume IS NOT NULL "
            "AND requested_price IS NULL) OR "
            "(ord_type = 'limit' AND requested_price IS NOT NULL "
            "AND requested_volume IS NOT NULL) OR "
            "(ord_type = 'best' AND ((side = 'bid' AND requested_price IS NOT NULL "
            "AND requested_volume IS NULL) OR (side = 'ask' AND requested_volume IS NOT NULL "
            "AND requested_price IS NULL)))",
            name="ck_order_intents_request_shape",
        ),
        sa.CheckConstraint(
            "submission_status <> 'ACCEPTED' OR "
            "(exchange_uuid IS NOT NULL AND length(trim(exchange_uuid)) > 0)",
            name="ck_order_intents_accepted_uuid",
        ),
        sa.CheckConstraint(
            "submission_status <> 'SUBMITTING' OR "
            "(submitted_at IS NOT NULL AND post_attempt_count = 1)",
            name="ck_order_intents_submitting_state",
        ),
        sa.CheckConstraint(
            "post_attempt_count BETWEEN 0 AND 1",
            name="ck_order_intents_post_attempt_count",
        ),
        sa.CheckConstraint(
            "reconcile_attempt_count >= 0",
            name="ck_order_intents_reconcile_attempt_count",
        ),
        sa.CheckConstraint(
            "not_found_count >= 0",
            name="ck_order_intents_not_found_count",
        ),
        sa.CheckConstraint("version >= 0", name="ck_order_intents_version"),
        sa.ForeignKeyConstraint(
            ["ai_analysis_log_id"],
            ["ai_analysis_logs.id"],
            name="fk_order_intents_ai_analysis_log_id_ai_analysis_logs",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["liquidation_operation_id"],
            ["liquidation_operations.id"],
            name="fk_order_intents_liquidation_operation_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("intent_key", name="uq_order_intents_intent_key"),
        sa.UniqueConstraint("identifier", name="uq_order_intents_identifier"),
        sa.UniqueConstraint(
            "broker",
            "exchange_uuid",
            name="uq_order_intents_broker_exchange_uuid",
        ),
    )
    op.create_index(
        op.f("ix_order_intents_ai_analysis_log_id"),
        "order_intents",
        ["ai_analysis_log_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_intents_liquidation_operation_id"),
        "order_intents",
        ["liquidation_operation_id"],
        unique=False,
    )
    op.create_index(
        "ix_order_intents_reconcile_due",
        "order_intents",
        ["submission_status", "next_reconcile_at"],
        unique=False,
    )
    op.create_index(
        "uq_order_intents_blocking_market",
        "order_intents",
        ["broker", "account_scope", "market"],
        unique=True,
        postgresql_where=sa.text(ORDER_INTENT_BLOCKING_PREDICATE),
    )
    op.create_index(
        "uq_order_intents_blocking_bid_account",
        "order_intents",
        ["broker", "account_scope"],
        unique=True,
        postgresql_where=sa.text(f"side = 'bid' AND ({ORDER_INTENT_BLOCKING_PREDICATE})"),
    )

    op.add_column(
        "order_history",
        sa.Column("order_intent_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_order_history_order_intent_id_order_intents",
        "order_history",
        "order_intents",
        ["order_intent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_order_history_order_intent_id",
        "order_history",
        ["order_intent_id"],
    )
    op.execute(
        sa.text(
            """
            INSERT INTO system_configs (config_key, config_value, description)
            VALUES (
                'live_order_v2_enabled',
                'false',
                '멱등 실주문 실행 경계 활성화 여부'
            )
            ON CONFLICT (config_key) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    """주문 의도 원장과 연결 필드를 제거합니다."""
    op.drop_constraint(
        "uq_order_history_order_intent_id",
        "order_history",
        type_="unique",
    )
    op.drop_constraint(
        "fk_order_history_order_intent_id_order_intents",
        "order_history",
        type_="foreignkey",
    )
    op.drop_column("order_history", "order_intent_id")

    op.drop_index("uq_order_intents_blocking_bid_account", table_name="order_intents")
    op.drop_index("uq_order_intents_blocking_market", table_name="order_intents")
    op.drop_index("ix_order_intents_reconcile_due", table_name="order_intents")
    op.drop_index(
        op.f("ix_order_intents_liquidation_operation_id"),
        table_name="order_intents",
    )
    op.drop_index(
        op.f("ix_order_intents_ai_analysis_log_id"),
        table_name="order_intents",
    )
    op.drop_table("order_intents")
    op.drop_table("liquidation_operations")
