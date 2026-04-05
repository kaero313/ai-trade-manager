"""add order reason to order history

Revision ID: 7c3f9f4d5a21
Revises: 0bfff577b35d
Create Date: 2026-04-05 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7c3f9f4d5a21"
down_revision: str | None = "0bfff577b35d"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("order_history", sa.Column("order_reason", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("order_history", "order_reason")
