"""feat(db): AI 분석 감사 계보 추가

Revision ID: c7a1e9d4f2b6
Revises: b8d4e6f1a2c3
Create Date: 2026-07-14 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c7a1e9d4f2b6"
down_revision: Union[str, Sequence[str], None] = "b8d4e6f1a2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_analysis_logs",
        sa.Column("stage", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ai_analysis_logs",
        sa.Column("provider", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "ai_analysis_logs",
        sa.Column("model", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "ai_analysis_logs",
        sa.Column("fallback_used", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "ai_analysis_logs",
        sa.Column("parent_analysis_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ai_analysis_logs",
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ai_analysis_logs",
        sa.Column("context_sha256", sa.String(length=64), nullable=True),
    )

    # 기존 행의 provider/model을 임의 추정하지 않고 명시적인 legacy 값으로 보존합니다.
    op.execute(
        sa.text(
            """
            UPDATE ai_analysis_logs
            SET stage = 'LEGACY_UNKNOWN',
                provider = 'LEGACY_UNKNOWN',
                model = 'LEGACY_UNKNOWN',
                prompt_version = 'LEGACY_UNKNOWN'
            """
        )
    )

    op.alter_column("ai_analysis_logs", "stage", nullable=False)
    op.alter_column("ai_analysis_logs", "provider", nullable=False)
    op.alter_column("ai_analysis_logs", "model", nullable=False)
    op.alter_column("ai_analysis_logs", "prompt_version", nullable=False)

    op.create_check_constraint(
        "ck_ai_analysis_logs_stage",
        "ai_analysis_logs",
        "stage IN ('TRADE_ANALYSIS', 'BUY_PRECHECK', 'LEGACY_UNKNOWN')",
    )
    op.create_check_constraint(
        "ck_ai_analysis_logs_provider_not_blank",
        "ai_analysis_logs",
        "length(trim(provider)) > 0",
    )
    op.create_check_constraint(
        "ck_ai_analysis_logs_model_not_blank",
        "ai_analysis_logs",
        "length(trim(model)) > 0",
    )
    op.create_check_constraint(
        "ck_ai_analysis_logs_prompt_version_not_blank",
        "ai_analysis_logs",
        "length(trim(prompt_version)) > 0",
    )
    op.create_check_constraint(
        "ck_ai_analysis_logs_context_sha256_hex",
        "ai_analysis_logs",
        "context_sha256 IS NULL OR context_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.create_foreign_key(
        "fk_ai_analysis_logs_parent_analysis_id",
        "ai_analysis_logs",
        "ai_analysis_logs",
        ["parent_analysis_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_ai_analysis_logs_parent_analysis_id",
        "ai_analysis_logs",
        ["parent_analysis_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_analysis_logs_symbol_stage_created_at",
        "ai_analysis_logs",
        ["symbol", "stage", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_analysis_logs_symbol_stage_created_at",
        table_name="ai_analysis_logs",
    )
    op.drop_index(
        "ix_ai_analysis_logs_parent_analysis_id",
        table_name="ai_analysis_logs",
    )
    op.drop_constraint(
        "fk_ai_analysis_logs_parent_analysis_id",
        "ai_analysis_logs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_ai_analysis_logs_context_sha256_hex",
        "ai_analysis_logs",
        type_="check",
    )
    op.drop_constraint(
        "ck_ai_analysis_logs_prompt_version_not_blank",
        "ai_analysis_logs",
        type_="check",
    )
    op.drop_constraint(
        "ck_ai_analysis_logs_model_not_blank",
        "ai_analysis_logs",
        type_="check",
    )
    op.drop_constraint(
        "ck_ai_analysis_logs_provider_not_blank",
        "ai_analysis_logs",
        type_="check",
    )
    op.drop_constraint(
        "ck_ai_analysis_logs_stage",
        "ai_analysis_logs",
        type_="check",
    )
    op.drop_column("ai_analysis_logs", "context_sha256")
    op.drop_column("ai_analysis_logs", "prompt_version")
    op.drop_column("ai_analysis_logs", "parent_analysis_id")
    op.drop_column("ai_analysis_logs", "fallback_used")
    op.drop_column("ai_analysis_logs", "model")
    op.drop_column("ai_analysis_logs", "provider")
    op.drop_column("ai_analysis_logs", "stage")
