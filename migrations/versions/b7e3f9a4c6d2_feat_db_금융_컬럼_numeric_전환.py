"""feat(db): 금융 컬럼 Numeric 전환과 포지션 유일 제약

Revision ID: b7e3f9a4c6d2
Revises: d5e8a1c4b7f2
Create Date: 2026-07-23 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "b7e3f9a4c6d2"
down_revision: Union[str, Sequence[str], None] = "d5e8a1c4b7f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ATM-P2-001: 이진 부동소수점 저장 오차를 없애기 위해 금융 컬럼을 NUMERIC(38, 18)로 전환합니다.
FINANCIAL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("positions", "avg_entry_price"),
    ("positions", "quantity"),
    ("order_history", "price"),
    ("order_history", "qty"),
    ("portfolio_snapshots", "total_net_worth"),
    ("portfolio_snapshots", "total_pnl"),
)

POSITION_UNIQUE_CONSTRAINT = "uq_positions_asset_id_is_paper"

# 중복 포지션은 자동 병합하지 않고 운영자 정리를 요구합니다(fail-closed).
# DO 블록은 online 실행과 offline SQL 산출 모두에서 동일하게 동작합니다.
_DUPLICATE_POSITION_GUARD = """\
DO $atm_p2_001_upgrade$
DECLARE
    duplicate_position RECORD;
BEGIN
    SELECT asset_id, is_paper, COUNT(*) AS row_count
    INTO duplicate_position
    FROM positions
    GROUP BY asset_id, is_paper
    HAVING COUNT(*) > 1
    ORDER BY asset_id, is_paper
    LIMIT 1;

    IF FOUND THEN
        RAISE EXCEPTION USING MESSAGE = format(
            'ATM-P2-001 upgrade blocked: duplicate positions exist for '
            '(asset_id=%s, is_paper=%s) with %s rows. '
            'Merge or delete the duplicate rows manually and re-run the migration.',
            duplicate_position.asset_id,
            duplicate_position.is_paper,
            duplicate_position.row_count
        );
    END IF;
END
$atm_p2_001_upgrade$
"""


def upgrade() -> None:
    """중복 포지션 preflight 뒤 금융 컬럼을 NUMERIC으로 전환하고 유일 제약을 추가합니다."""
    if not context.is_offline_mode():
        bind = op.get_bind()
        if bind.dialect.name != "postgresql":
            raise RuntimeError("ATM-P2-001 upgrade preflight requires PostgreSQL")

    op.execute(sa.text(_DUPLICATE_POSITION_GUARD))

    for table_name, column_name in FINANCIAL_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.Float(),
            type_=sa.Numeric(38, 18),
            existing_nullable=False,
        )

    op.create_unique_constraint(
        POSITION_UNIQUE_CONSTRAINT,
        "positions",
        ["asset_id", "is_paper"],
    )


def downgrade() -> None:
    """유일 제약을 제거하고 금융 컬럼을 이전 Float 타입으로 되돌립니다."""
    op.drop_constraint(POSITION_UNIQUE_CONSTRAINT, "positions", type_="unique")

    for table_name, column_name in reversed(FINANCIAL_COLUMNS):
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.Numeric(38, 18),
            type_=sa.Float(),
            existing_nullable=False,
        )
