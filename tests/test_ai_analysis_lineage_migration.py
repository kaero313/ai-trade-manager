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

from app.models.domain import AIAnalysisLog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_HEAD_REVISION = "b8d4e6f1a2c3"
AI_ANALYSIS_LINEAGE_REVISION = "c7a1e9d4f2b6"
CURRENT_HEAD_REVISION = "b7e3f9a4c6d2"


def _run_alembic(
    *args: str,
    database_url: str | None = None,
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
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.mark.migration
def test_ai_analysis_lineage_revision_is_the_single_head() -> None:
    result = _run_alembic("heads")
    assert result.stdout.strip() == f"{CURRENT_HEAD_REVISION} (head)"


@pytest.mark.migration
def test_ai_analysis_lineage_upgrade_backfills_legacy_before_not_null() -> None:
    sql = _run_alembic(
        "upgrade",
        f"{PREVIOUS_HEAD_REVISION}:{AI_ANALYSIS_LINEAGE_REVISION}",
        "--sql",
    ).stdout

    backfill_position = sql.index("UPDATE ai_analysis_logs")
    not_null_position = sql.index("ALTER COLUMN stage SET NOT NULL")
    assert backfill_position < not_null_position

    for fragment in (
        "ADD COLUMN stage VARCHAR(32)",
        "ADD COLUMN provider VARCHAR(32)",
        "ADD COLUMN model VARCHAR(128)",
        "ADD COLUMN fallback_used BOOLEAN",
        "ADD COLUMN parent_analysis_id INTEGER",
        "ADD COLUMN prompt_version VARCHAR(64)",
        "ADD COLUMN context_sha256 VARCHAR(64)",
        "stage = 'LEGACY_UNKNOWN'",
        "provider = 'LEGACY_UNKNOWN'",
        "model = 'LEGACY_UNKNOWN'",
        "prompt_version = 'LEGACY_UNKNOWN'",
        "CONSTRAINT ck_ai_analysis_logs_stage",
        "CONSTRAINT ck_ai_analysis_logs_context_sha256_hex",
        "CONSTRAINT fk_ai_analysis_logs_parent_analysis_id",
        "ON DELETE RESTRICT",
        "CREATE INDEX ix_ai_analysis_logs_parent_analysis_id",
        "CREATE INDEX ix_ai_analysis_logs_symbol_stage_created_at",
    ):
        assert fragment in sql

    # nullable 감사 값은 legacy 행에 임의로 채우지 않습니다.
    update_sql = sql[backfill_position:not_null_position]
    assert "fallback_used =" not in update_sql
    assert "parent_analysis_id =" not in update_sql
    assert "context_sha256 =" not in update_sql


@pytest.mark.migration
def test_ai_analysis_lineage_downgrade_drops_only_lineage_schema() -> None:
    sql = _run_alembic(
        "downgrade",
        f"{AI_ANALYSIS_LINEAGE_REVISION}:{PREVIOUS_HEAD_REVISION}",
        "--sql",
    ).stdout

    for column in (
        "context_sha256",
        "prompt_version",
        "parent_analysis_id",
        "fallback_used",
        "model",
        "provider",
        "stage",
    ):
        assert f"DROP COLUMN {column}" in sql

    assert "DROP TABLE ai_analysis_logs" not in sql
    assert "DROP TABLE order_history" not in sql


@pytest.mark.migration
def test_ai_analysis_lineage_model_matches_migration_contract() -> None:
    table = AIAnalysisLog.__table__

    assert table.c.stage.type.length == 32
    assert table.c.stage.nullable is False
    assert table.c.provider.type.length == 32
    assert table.c.provider.nullable is False
    assert table.c.model.type.length == 128
    assert table.c.model.nullable is False
    assert table.c.fallback_used.nullable is True
    assert table.c.prompt_version.type.length == 64
    assert table.c.prompt_version.nullable is False
    assert table.c.context_sha256.type.length == 64
    assert table.c.context_sha256.nullable is True

    parent_fk = next(
        constraint
        for constraint in table.foreign_key_constraints
        if constraint.name == "fk_ai_analysis_logs_parent_analysis_id"
    )
    assert parent_fk.referred_table is table
    assert parent_fk.ondelete == "RESTRICT"

    constraint_names = {constraint.name for constraint in table.constraints}
    assert constraint_names >= {
        "ck_ai_analysis_logs_stage",
        "ck_ai_analysis_logs_provider_not_blank",
        "ck_ai_analysis_logs_model_not_blank",
        "ck_ai_analysis_logs_prompt_version_not_blank",
        "ck_ai_analysis_logs_context_sha256_hex",
    }

    indexes = {index.name: index for index in table.indexes}
    assert [
        column.name
        for column in indexes["ix_ai_analysis_logs_symbol_stage_created_at"].columns
    ] == ["symbol", "stage", "created_at"]
    assert [
        column.name for column in indexes["ix_ai_analysis_logs_parent_analysis_id"].columns
    ] == ["parent_analysis_id"]


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
async def test_ai_analysis_lineage_migration_backfill_constraints_and_roundtrip() -> None:
    source_url = make_url(_test_database_url())
    database_name = f"atm_p1_008_{uuid4().hex[:12]}_test"
    admin_url = source_url.set(database="postgres")
    target_url = source_url.set(database=database_name)
    target_url_text = target_url.render_as_string(hide_password=False)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        _run_alembic("upgrade", PREVIOUS_HEAD_REVISION, database_url=target_url_text)
        await _execute(
            target_url_text,
            """
            INSERT INTO ai_analysis_logs
                (symbol, decision, confidence, recommended_weight, reasoning)
            VALUES ('KRW-BTC', 'BUY', 80, 10, 'legacy row')
            """,
        )
        _run_alembic("upgrade", AI_ANALYSIS_LINEAGE_REVISION, database_url=target_url_text)

        legacy = await _fetch_one(
            target_url_text,
            """
            SELECT stage, provider, model, fallback_used, parent_analysis_id,
                   prompt_version, context_sha256
            FROM ai_analysis_logs
            WHERE reasoning = 'legacy row'
            """,
        )
        assert tuple(legacy) == (
            "LEGACY_UNKNOWN",
            "LEGACY_UNKNOWN",
            "LEGACY_UNKNOWN",
            None,
            None,
            "LEGACY_UNKNOWN",
            None,
        )

        await _execute(
            target_url_text,
            """
            INSERT INTO ai_analysis_logs
                (symbol, decision, confidence, recommended_weight, reasoning,
                 stage, provider, model, fallback_used, prompt_version, context_sha256)
            VALUES
                ('KRW-ETH', 'BUY', 90, 12, 'primary row', 'TRADE_ANALYSIS',
                 'openai', 'gpt-test', false, 'trade_analysis.v1', repeat('a', 64))
            """,
        )
        await _execute(
            target_url_text,
            """
            INSERT INTO ai_analysis_logs
                (symbol, decision, confidence, recommended_weight, reasoning,
                 stage, provider, model, fallback_used, parent_analysis_id,
                 prompt_version, context_sha256)
            SELECT 'KRW-ETH', 'HOLD', 60, 0, 'precheck row', 'BUY_PRECHECK',
                   'openai', 'gpt-test', false, id, 'buy_precheck.v1', repeat('b', 64)
            FROM ai_analysis_logs WHERE reasoning = 'primary row'
            """,
        )

        with pytest.raises(IntegrityError):
            await _execute(
                target_url_text,
                """
                INSERT INTO ai_analysis_logs
                    (symbol, decision, confidence, recommended_weight, reasoning,
                     stage, provider, model, prompt_version)
                VALUES ('KRW-XRP', 'HOLD', 0, 0, 'bad stage', 'UNKNOWN',
                        'SYSTEM', 'DETERMINISTIC_HOLD', 'trade_analysis.v1')
                """,
            )
        with pytest.raises(IntegrityError):
            await _execute(
                target_url_text,
                """
                UPDATE ai_analysis_logs
                SET context_sha256 = 'ABC'
                WHERE reasoning = 'primary row'
                """,
            )
        with pytest.raises(IntegrityError):
            await _execute(
                target_url_text,
                "DELETE FROM ai_analysis_logs WHERE reasoning = 'primary row'",
            )

        _run_alembic("downgrade", PREVIOUS_HEAD_REVISION, database_url=target_url_text)
        columns_after_downgrade = await _fetch_one(
            target_url_text,
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name = 'ai_analysis_logs'
              AND column_name IN ('stage', 'provider', 'model', 'fallback_used',
                                  'parent_analysis_id', 'prompt_version', 'context_sha256')
            """,
        )
        assert columns_after_downgrade[0] == 0
        _run_alembic("upgrade", AI_ANALYSIS_LINEAGE_REVISION, database_url=target_url_text)
    finally:
        await admin_engine.dispose()
        cleanup_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with cleanup_engine.connect() as connection:
                await connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": database_name},
                )
                await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        finally:
            await cleanup_engine.dispose()
