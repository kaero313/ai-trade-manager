from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import make_url, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_HEAD_REVISION = "c7a1e9d4f2b6"
CONFIG_RUNTIME_VERSION_REVISION = "d5e8a1c4b7f2"
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
def test_config_runtime_version_revision_has_expected_parent_and_is_single_head() -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(CONFIG_RUNTIME_VERSION_REVISION)

    assert revision is not None
    assert revision.down_revision == PREVIOUS_HEAD_REVISION
    assert scripts.get_heads() == [CURRENT_HEAD_REVISION]
    assert (
        _run_alembic("heads").stdout.strip()
        == f"{CURRENT_HEAD_REVISION} (head)"
    )


@pytest.mark.migration
def test_config_runtime_version_upgrade_offline_sql_preserves_other_metadata() -> None:
    sql = _run_alembic(
        "upgrade",
        f"{PREVIOUS_HEAD_REVISION}:{CONFIG_RUNTIME_VERSION_REVISION}",
        "--sql",
    ).stdout

    for fragment in (
        "ALTER TABLE bot_configs ADD COLUMN config_version INTEGER DEFAULT 1 NOT NULL",
        "ADD COLUMN runtime_last_heartbeat TIMESTAMP WITH TIME ZONE",
        "ADD COLUMN runtime_last_error TEXT",
        "ADD COLUMN runtime_latest_action TEXT",
        "ADD COLUMN runtime_updated_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE system_configs ADD COLUMN version INTEGER DEFAULT 1 NOT NULL",
        "pg_input_is_valid(",
        "CONSTRAINT ck_bot_configs_config_version CHECK (config_version >= 1)",
        "CONSTRAINT ck_system_configs_version CHECK (version >= 1)",
    ):
        assert fragment in sql

    backfill = sql[sql.index("UPDATE bot_configs") : sql.index(
        "ALTER TABLE bot_configs ADD CONSTRAINT"
    )]
    assert "#- '{metadata,runtime_status}'" in backfill
    assert "#> '{metadata,runtime_status}'" in backfill
    assert "-> 'metadata'" in backfill
    assert "= '{}'::jsonb" in backfill
    assert "config_json = '{}'" not in backfill
    assert "config_json::jsonb - 'owner'" not in backfill


@pytest.mark.migration
def test_config_runtime_version_downgrade_offline_sql_reconstructs_runtime_json() -> None:
    sql = _run_alembic(
        "downgrade",
        f"{CONFIG_RUNTIME_VERSION_REVISION}:{PREVIOUS_HEAD_REVISION}",
        "--sql",
    ).stdout

    for fragment in (
        "DROP CONSTRAINT ck_system_configs_version",
        "DROP CONSTRAINT ck_bot_configs_config_version",
        "jsonb_set(",
        "'{metadata}'",
        "THEN config_json::jsonb -> 'metadata'",
        "'runtime_status'",
        "'last_heartbeat', runtime_last_heartbeat",
        "'last_error', runtime_last_error",
        "'latest_action', runtime_latest_action",
        "'updated_at', runtime_updated_at",
        "ALTER TABLE system_configs DROP COLUMN version",
        "ALTER TABLE bot_configs DROP COLUMN config_version",
    ):
        assert fragment in sql

    assert "DROP TABLE bot_configs" not in sql
    assert "DROP TABLE system_configs" not in sql


def _test_database_url() -> str:
    raw_url = str(os.getenv("TEST_DATABASE_URL") or "").strip()
    if not raw_url:
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
async def test_config_runtime_version_postgres_backfill_constraints_and_roundtrip() -> None:
    source_url = make_url(_test_database_url())
    database_name = f"atm_p1_config_{uuid4().hex[:10]}_test"
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
            INSERT INTO bot_configs (id, config_json, is_active)
            VALUES
                (
                    1,
                    '{
                        "symbols": ["KRW-BTC"],
                        "metadata": {
                            "owner": "operator",
                            "runtime_status": {
                                "last_heartbeat": "2026-07-15T01:02:03+00:00",
                                "last_error": "legacy error",
                                "latest_action": "legacy action",
                                "updated_at": "2026-07-15T01:03:04+00:00"
                            }
                        }
                    }'::json,
                    false
                ),
                (
                    2,
                    '{
                        "symbols": ["KRW-ETH"],
                        "metadata": {
                            "owner": "malformed-owner",
                            "note": "keep-me",
                            "runtime_status": {
                                "last_heartbeat": "not-a-timestamp",
                                "last_error": null,
                                "latest_action": "malformed action",
                                "updated_at": "still-not-a-timestamp"
                            }
                        }
                    }'::json,
                    true
                )
            """,
        )
        await _execute(
            target_url_text,
            """
            INSERT INTO system_configs (config_key, config_value, description)
            VALUES ('legacy_config', 'value', 'legacy row')
            """,
        )

        _run_alembic(
            "upgrade",
            CONFIG_RUNTIME_VERSION_REVISION,
            database_url=target_url_text,
        )

        valid = await _fetch_one(
            target_url_text,
            """
            SELECT config_version,
                   runtime_last_heartbeat,
                   runtime_last_error,
                   runtime_latest_action,
                   runtime_updated_at,
                   config_json::jsonb #>> '{metadata,owner}',
                   config_json::jsonb #> '{metadata,runtime_status}' IS NULL
            FROM bot_configs
            WHERE id = 1
            """,
        )
        assert valid[0] == 1
        assert valid[1].isoformat() == "2026-07-15T01:02:03+00:00"
        assert valid[2:4] == ("legacy error", "legacy action")
        assert valid[4].isoformat() == "2026-07-15T01:03:04+00:00"
        assert valid[5:] == ("operator", True)

        malformed = await _fetch_one(
            target_url_text,
            """
            SELECT config_version,
                   runtime_last_heartbeat,
                   runtime_updated_at,
                   runtime_latest_action,
                   config_json::jsonb #>> '{metadata,owner}',
                   config_json::jsonb #>> '{metadata,note}',
                   config_json::jsonb #> '{metadata,runtime_status}' IS NULL
            FROM bot_configs
            WHERE id = 2
            """,
        )
        assert tuple(malformed) == (
            1,
            None,
            None,
            "malformed action",
            "malformed-owner",
            "keep-me",
            True,
        )

        system_version = await _fetch_one(
            target_url_text,
            "SELECT version FROM system_configs WHERE config_key = 'legacy_config'",
        )
        assert system_version[0] == 1

        await _execute(
            target_url_text,
            """
            INSERT INTO bot_configs (id, config_json, is_active)
            VALUES (3, '{}', false)
            """,
        )
        await _execute(
            target_url_text,
            """
            INSERT INTO system_configs (config_key, config_value)
            VALUES ('default_version', 'value')
            """,
        )
        defaults = await _fetch_one(
            target_url_text,
            """
            SELECT
                (SELECT config_version FROM bot_configs WHERE id = 3),
                (SELECT version FROM system_configs WHERE config_key = 'default_version')
            """,
        )
        assert tuple(defaults) == (1, 1)

        with pytest.raises(IntegrityError):
            await _execute(
                target_url_text,
                "UPDATE bot_configs SET config_version = 0 WHERE id = 1",
            )
        with pytest.raises(IntegrityError):
            await _execute(
                target_url_text,
                "UPDATE system_configs SET version = 0 WHERE config_key = 'legacy_config'",
            )

        _run_alembic(
            "downgrade",
            PREVIOUS_HEAD_REVISION,
            database_url=target_url_text,
        )
        downgraded = await _fetch_one(
            target_url_text,
            """
            SELECT config_json::jsonb #>> '{metadata,owner}',
                   config_json::jsonb #>> '{metadata,runtime_status,last_heartbeat}',
                   config_json::jsonb #>> '{metadata,runtime_status,last_error}',
                   config_json::jsonb #>> '{metadata,runtime_status,latest_action}',
                   config_json::jsonb #>> '{metadata,runtime_status,updated_at}'
            FROM bot_configs
            WHERE id = 1
            """,
        )
        assert downgraded[0] == "operator"
        assert datetime.fromisoformat(downgraded[1]).isoformat() == (
            "2026-07-15T01:02:03+00:00"
        )
        assert downgraded[2:4] == ("legacy error", "legacy action")
        assert datetime.fromisoformat(downgraded[4]).isoformat() == (
            "2026-07-15T01:03:04+00:00"
        )

        malformed_downgraded = await _fetch_one(
            target_url_text,
            """
            SELECT config_json::jsonb #>> '{metadata,owner}',
                   config_json::jsonb #>> '{metadata,note}',
                   config_json::jsonb #>> '{metadata,runtime_status,last_heartbeat}',
                   config_json::jsonb #>> '{metadata,runtime_status,updated_at}'
            FROM bot_configs
            WHERE id = 2
            """,
        )
        assert tuple(malformed_downgraded) == (
            "malformed-owner",
            "keep-me",
            None,
            None,
        )

        _run_alembic(
            "upgrade",
            CONFIG_RUNTIME_VERSION_REVISION,
            database_url=target_url_text,
        )
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
