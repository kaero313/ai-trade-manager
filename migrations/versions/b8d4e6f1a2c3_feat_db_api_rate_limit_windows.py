"""feat(db): API 요청 제한 공유 원장 추가

Revision ID: b8d4e6f1a2c3
Revises: f6b2c9d4e8a1
Create Date: 2026-07-13 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b8d4e6f1a2c3"
down_revision: Union[str, Sequence[str], None] = "f6b2c9d4e8a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_rate_limit_windows",
        sa.Column("policy_key", sa.String(length=48), nullable=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "request_count",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "rejected_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
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
        sa.CheckConstraint(
            "length(trim(policy_key)) > 0",
            name="ck_api_rate_limit_windows_policy_key",
        ),
        sa.CheckConstraint(
            "subject_hash ~ '^[0-9a-f]{64}$'",
            name="ck_api_rate_limit_windows_subject_hash_hex",
        ),
        sa.CheckConstraint(
            "request_count BETWEEN 1 AND 9223372036854775807",
            name="ck_api_rate_limit_windows_request_count",
        ),
        sa.CheckConstraint(
            "rejected_count BETWEEN 0 AND 9223372036854775807",
            name="ck_api_rate_limit_windows_rejected_count",
        ),
        sa.PrimaryKeyConstraint(
            "policy_key",
            "subject_hash",
            "window_started_at",
            name="pk_api_rate_limit_windows",
        ),
    )
    op.create_index(
        "ix_api_rate_limit_windows_cleanup_due",
        "api_rate_limit_windows",
        ["window_started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_api_rate_limit_windows_cleanup_due",
        table_name="api_rate_limit_windows",
    )
    op.drop_table("api_rate_limit_windows")
