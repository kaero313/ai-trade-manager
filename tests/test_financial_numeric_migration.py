from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_HEAD_REVISION = "d5e8a1c4b7f2"
FINANCIAL_NUMERIC_REVISION = "b7e3f9a4c6d2"
CURRENT_HEAD_REVISION = "b7e3f9a4c6d2"

FINANCIAL_COLUMNS = (
    ("positions", "avg_entry_price"),
    ("positions", "quantity"),
    ("order_history", "price"),
    ("order_history", "qty"),
    ("portfolio_snapshots", "total_net_worth"),
    ("portfolio_snapshots", "total_pnl"),
)


def _run_alembic(
    *args: str,
    database_url: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if database_url is not None:
        url = make_url(database_url)
        env.update(
            {
                "POSTGRES_USER": url.username or "postgres",
                "POSTGRES_PASSWORD": url.password or "",
                "POSTGRES_HOST": url.host or "localhost",
                "POSTGRES_PORT": str(url.port or 5432),
                "POSTGRES_DB": url.database or "",
            }
        )
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=PROJECT_ROOT,
        env=env,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.mark.migration
def test_financial_numeric_revision_is_the_single_head() -> None:
    result = _run_alembic("heads")
    assert result.stdout.strip() == f"{CURRENT_HEAD_REVISION} (head)"


@pytest.mark.migration
def test_financial_numeric_upgrade_offline_sql_guards_duplicates_before_altering() -> None:
    result = _run_alembic(
        "upgrade",
        f"{PREVIOUS_HEAD_REVISION}:{FINANCIAL_NUMERIC_REVISION}",
        "--sql",
    )
    sql = result.stdout

    guard = sql.index("DO $atm_p2_001_upgrade$")
    assert "duplicate positions exist" in sql
    assert "Merge or delete the duplicate rows manually" in sql

    for table_name, column_name in FINANCIAL_COLUMNS:
        statement = (
            f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE NUMERIC(38, 18)"
        )
        assert statement in sql
        # 중복 preflight가 모든 타입 전환보다 먼저 실행되어야 합니다.
        assert guard < sql.index(statement)

    constraint = sql.index(
        "ALTER TABLE positions ADD CONSTRAINT uq_positions_asset_id_is_paper "
        "UNIQUE (asset_id, is_paper)"
    )
    assert guard < constraint


@pytest.mark.migration
def test_financial_numeric_downgrade_offline_sql_reverts_only_target_columns() -> None:
    result = _run_alembic(
        "downgrade",
        f"{FINANCIAL_NUMERIC_REVISION}:{PREVIOUS_HEAD_REVISION}",
        "--sql",
    )
    sql = result.stdout

    assert "ALTER TABLE positions DROP CONSTRAINT uq_positions_asset_id_is_paper" in sql
    for table_name, column_name in FINANCIAL_COLUMNS:
        assert f"ALTER TABLE {table_name} ALTER COLUMN {column_name} TYPE FLOAT" in sql

    # P0-001 주문 원장의 NUMERIC 컬럼은 건드리지 않습니다.
    assert "ALTER TABLE order_intents" not in sql


def _test_database_url() -> str:
    raw_url = str(os.getenv("TEST_DATABASE_URL") or "").strip()
    if not raw_url:
        if os.getenv("CI"):
            pytest.fail("CI PostgreSQL migration 테스트에는 TEST_DATABASE_URL이 필요합니다.")
        pytest.skip("TEST_DATABASE_URL이 없어 PostgreSQL migration 테스트를 건너뜁니다.")
    parsed = make_url(raw_url)
    if not parsed.drivername.startswith("postgresql"):
        pytest.fail("TEST_DATABASE_URL은 PostgreSQL 테스트 DB를 가리켜야 합니다.")
    if not (parsed.database or "").endswith("_test"):
        pytest.fail("운영 DB 오접속 방지를 위해 테스트 DB 이름은 _test로 끝나야 합니다.")
    return raw_url


async def _execute(database_url: str, statement: str) -> None:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


async def _fetch_one(database_url: str, statement: str):
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            return (await connection.execute(text(statement))).one()
    finally:
        await engine.dispose()


@pytest.mark.postgres
@pytest.mark.migration
@pytest.mark.asyncio
async def test_financial_numeric_migration_blocks_duplicates_then_roundtrips() -> None:
    source_url = make_url(_test_database_url())
    database_name = f"atm_p2_001_roundtrip_{uuid4().hex[:8]}_test"
    admin_url = source_url.set(database="postgres")
    target_url = source_url.set(database=database_name)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        target_url_text = target_url.render_as_string(hide_password=False)
        _run_alembic("upgrade", PREVIOUS_HEAD_REVISION, database_url=target_url_text)

        await _execute(
            target_url_text,
            """
            INSERT INTO assets (symbol, asset_type, base_currency, is_active)
            VALUES ('KRW-BTC', 'crypto', 'KRW', TRUE)
            """,
        )
        await _execute(
            target_url_text,
            """
            INSERT INTO positions (asset_id, avg_entry_price, quantity, status, is_paper)
            SELECT id, 100.0, 1.0, 'open', TRUE FROM assets WHERE symbol = 'KRW-BTC'
            """,
        )
        await _execute(
            target_url_text,
            """
            INSERT INTO positions (asset_id, avg_entry_price, quantity, status, is_paper)
            SELECT id, 200.0, 2.0, 'open', TRUE FROM assets WHERE symbol = 'KRW-BTC'
            """,
        )

        blocked = _run_alembic(
            "upgrade",
            FINANCIAL_NUMERIC_REVISION,
            database_url=target_url_text,
            check=False,
        )
        assert blocked.returncode != 0
        assert "duplicate positions exist" in (blocked.stdout + blocked.stderr)

        await _execute(
            target_url_text,
            """
            DELETE FROM positions
            WHERE id NOT IN (
                SELECT MIN(id) FROM positions GROUP BY asset_id, is_paper
            )
            """,
        )

        _run_alembic("upgrade", FINANCIAL_NUMERIC_REVISION, database_url=target_url_text)

        for table_name, column_name in FINANCIAL_COLUMNS:
            column_type = await _fetch_one(
                target_url_text,
                f"""
                SELECT data_type, numeric_precision, numeric_scale
                FROM information_schema.columns
                WHERE table_name = '{table_name}' AND column_name = '{column_name}'
                """,
            )
            assert column_type.data_type == "numeric"
            assert column_type.numeric_precision == 38
            assert column_type.numeric_scale == 18

        with pytest.raises(IntegrityError):
            await _execute(
                target_url_text,
                """
                INSERT INTO positions (asset_id, avg_entry_price, quantity, status, is_paper)
                SELECT id, 300.0, 3.0, 'open', TRUE FROM assets WHERE symbol = 'KRW-BTC'
                """,
            )

        _run_alembic("downgrade", PREVIOUS_HEAD_REVISION, database_url=target_url_text)

        reverted = await _fetch_one(
            target_url_text,
            """
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'positions' AND column_name = 'quantity'
            """,
        )
        assert reverted.data_type == "double precision"
    finally:
        try:
            async with admin_engine.connect() as connection:
                await connection.execute(
                    text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
                )
        finally:
            await admin_engine.dispose()
