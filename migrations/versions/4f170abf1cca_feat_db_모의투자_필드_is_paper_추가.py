"""feat(db): 모의투자 필드 is_paper 추가

Revision ID: 4f170abf1cca
Revises: 7c3f9f4d5a21
Create Date: 2026-04-05 21:03:07.937390

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f170abf1cca'
down_revision: Union[str, Sequence[str], None] = '7c3f9f4d5a21'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'order_history',
        sa.Column('is_paper', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'positions',
        sa.Column('is_paper', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('order_history', 'is_paper', server_default=None)
    op.alter_column('positions', 'is_paper', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('positions', 'is_paper')
    op.drop_column('order_history', 'is_paper')
