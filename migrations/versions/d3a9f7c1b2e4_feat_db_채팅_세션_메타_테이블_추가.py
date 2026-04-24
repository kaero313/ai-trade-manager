"""feat(db): 채팅 세션 메타 테이블 추가

Revision ID: d3a9f7c1b2e4
Revises: 6267c3024d91
Create Date: 2026-04-24 16:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d3a9f7c1b2e4"
down_revision: Union[str, Sequence[str], None] = "6267c3024d91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chat_sessions",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("surface", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(op.f("ix_chat_sessions_surface"), "chat_sessions", ["surface"], unique=False)

    op.execute(
        """
        INSERT INTO chat_sessions (session_id, surface)
        SELECT DISTINCT session_id, 'ai_banker'
        FROM ai_chat_messages
        """
    )

    op.create_foreign_key(
        "fk_ai_chat_messages_session_id_chat_sessions",
        "ai_chat_messages",
        "chat_sessions",
        ["session_id"],
        ["session_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_ai_chat_messages_session_id_chat_sessions",
        "ai_chat_messages",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_chat_sessions_surface"), table_name="chat_sessions")
    op.drop_table("chat_sessions")
