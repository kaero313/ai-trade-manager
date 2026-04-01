"""add ai analysis reference to order history

Revision ID: a4b9c2d6e8f1
Revises: 899de21aad12
Create Date: 2026-04-01 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a4b9c2d6e8f1"
down_revision: Union[str, Sequence[str], None] = "899de21aad12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("order_history", sa.Column("ai_analysis_log_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_order_history_ai_analysis_log_id"),
        "order_history",
        ["ai_analysis_log_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_order_history_ai_analysis_log_id_ai_analysis_logs"),
        "order_history",
        "ai_analysis_logs",
        ["ai_analysis_log_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_order_history_ai_analysis_log_id_ai_analysis_logs"),
        "order_history",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_order_history_ai_analysis_log_id"), table_name="order_history")
    op.drop_column("order_history", "ai_analysis_log_id")
