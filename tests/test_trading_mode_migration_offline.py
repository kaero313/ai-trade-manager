import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_REVISION = "a91f3e7c5b2d"
TRADING_MODE_REVISION = "c4f8a2d7e1b3"
CURRENT_HEAD_REVISION = "b7e3f9a4c6d2"


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


def _offline_sql(*args: str) -> str:
    result = _run_alembic(*args, "--sql")
    return result.stdout


@pytest.mark.migration
def test_trading_mode_upgrade_offline_sql_is_fail_closed_and_append_only() -> None:
    sql = _offline_sql("upgrade", f"{BASE_REVISION}:{TRADING_MODE_REVISION}")

    preflight = sql.index("DO $atm_p0_003_upgrade$")
    control_table = sql.index("CREATE TABLE trading_mode_controls")
    event_table = sql.index("CREATE TABLE trading_mode_control_events")
    control_seed = sql.index("INSERT INTO trading_mode_controls")
    event_seed = sql.index("INSERT INTO trading_mode_control_events")
    mirror_write = sql.index("INSERT INTO system_configs", event_seed)
    assert preflight < control_table < event_table < control_seed < event_seed < mirror_write

    preflight_sql = sql[preflight:control_table]
    for fragment in (
        "pg_try_advisory_xact_lock(5740495976316385210)",
        "config_key = 'live_order_v2_enabled'",
        "mode <> 'BLOCK_ALL'",
        "emergency_authorization_status = 'ACTIVE'",
        "status IN ('PREPARING', 'IN_PROGRESS')",
        "submission_status IN ('PREPARED', 'SUBMITTING', 'UNKNOWN')",
    ):
        assert fragment in preflight_sql

    for fragment in (
        "CONSTRAINT ck_trading_mode_controls_singleton",
        "CONSTRAINT ck_trading_mode_control_events_request_pair",
        "CONSTRAINT ck_trading_mode_control_events_transition",
        "CONSTRAINT uq_trading_mode_control_events_request_id",
        "CONSTRAINT uq_trading_mode_control_events_reauth_jti",
        "CONSTRAINT uq_trading_mode_control_events_control_version",
        "legacy_raw_value",
        "CREATE TRIGGER trg_trading_mode_control_events_append_only",
        "SET config_value = 'paper'",
        "UPDATE bot_configs SET is_active = false",
        "ALTER COLUMN is_active SET DEFAULT false",
    ):
        assert fragment in sql

    initial_event_sql = sql[event_seed:mirror_write]
    assert "'INITIALIZED'" in initial_event_sql
    assert "'paper'" in initial_event_sql
    assert "WHERE config_key = 'trading_mode'" in initial_event_sql


@pytest.mark.migration
def test_trading_mode_downgrade_requires_safe_state_and_never_restores_live() -> None:
    sql = _offline_sql("downgrade", f"{TRADING_MODE_REVISION}:{BASE_REVISION}")

    preflight = sql.index("DO $atm_p0_003_downgrade$")
    first_drop = sql.index("DROP TRIGGER")
    assert preflight < first_drop
    preflight_sql = sql[preflight:first_drop]
    for fragment in (
        "live_order_v2_enabled",
        "mode <> 'BLOCK_ALL'",
        "active liquidation exists",
        "blocking order intent exists",
        "id = 1 AND mode = 'paper'",
        "config_key = 'trading_mode' AND config_value = 'paper'",
        "SELECT 1 FROM bot_configs WHERE is_active",
    ):
        assert fragment in preflight_sql

    assert "SET config_value = 'paper'" in sql[preflight:]
    assert "UPDATE bot_configs SET is_active = false" in sql[preflight:]
    assert "SET config_value = 'live'" not in sql
    assert "DROP TABLE trading_mode_control_events" in sql[first_drop:]
    assert "DROP TABLE trading_mode_controls" in sql[first_drop:]


@pytest.mark.migration
def test_trading_mode_revision_is_followed_by_the_single_current_head() -> None:
    result = _run_alembic("heads")
    assert result.stdout.strip() == f"{CURRENT_HEAD_REVISION} (head)"


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
async def test_trading_mode_migration_downgrades_legacy_live_and_missing_to_paper() -> None:
    source_url = make_url(_test_database_url())
    database_name = f"atm_p0_003_{uuid4().hex[:12]}_test"
    admin_url = source_url.set(database="postgres")
    target_url = source_url.set(database=database_name)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        target_url_text = target_url.render_as_string(hide_password=False)
        _run_alembic("upgrade", BASE_REVISION, database_url=target_url_text)
        await _execute(
            target_url_text,
            """
            INSERT INTO system_configs (config_key, config_value, description)
            VALUES ('trading_mode', 'live', 'legacy migration test')
            ON CONFLICT (config_key) DO UPDATE SET config_value = EXCLUDED.config_value
            """,
        )
        await _execute(
            target_url_text,
            "INSERT INTO bot_configs (config_json, is_active) VALUES ('{}', true)",
        )

        await _execute(
            target_url_text,
            """
            UPDATE system_configs
            SET config_value = 'true'
            WHERE config_key = 'live_order_v2_enabled'
            """,
        )
        blocked = _run_alembic(
            "upgrade",
            TRADING_MODE_REVISION,
            database_url=target_url_text,
            check=False,
        )
        assert blocked.returncode != 0
        assert "live_order_v2_enabled is not false" in (blocked.stdout + blocked.stderr)
        assert (
            await _fetch_one(
                target_url_text,
                "SELECT version_num, to_regclass('public.trading_mode_controls') "
                "FROM alembic_version",
            )
        ) == (BASE_REVISION, None)

        await _execute(
            target_url_text,
            """
            UPDATE system_configs
            SET config_value = 'false'
            WHERE config_key = 'live_order_v2_enabled'
            """,
        )
        _run_alembic("upgrade", TRADING_MODE_REVISION, database_url=target_url_text)
        migrated = await _fetch_one(
            target_url_text,
            """
            SELECT control.mode,
                   control.version,
                   event.action,
                   event.legacy_raw_value,
                   mirror.config_value,
                   NOT bot.is_active
            FROM trading_mode_controls AS control
            JOIN trading_mode_control_events AS event
              ON event.control_id = control.id AND event.version = control.version
            JOIN system_configs AS mirror ON mirror.config_key = 'trading_mode'
            JOIN bot_configs AS bot ON true
            WHERE control.id = 1
            """,
        )
        assert tuple(migrated) == (
            "paper",
            1,
            "INITIALIZED",
            "live",
            "paper",
            True,
        )

        await _execute(
            target_url_text,
            """
            INSERT INTO liquidation_operations (idempotency_key, status, completed_at)
            VALUES ('44444444-4444-4444-8444-444444444444', 'COMPLETED', now())
            """,
        )
        await _execute(
            target_url_text,
            """
            WITH operation AS (
                SELECT id
                FROM liquidation_operations
                WHERE idempotency_key = '44444444-4444-4444-8444-444444444444'
            ), authorized_control AS (
                UPDATE live_order_controls
                SET mode = 'EXIT_ONLY',
                    active_liquidation_operation_id = operation.id,
                    generation = generation + 1,
                    version = version + 1
                FROM operation
                WHERE broker = 'UPBIT' AND account_scope = 'primary'
                RETURNING live_order_controls.id,
                          live_order_controls.generation,
                          operation.id AS operation_id
            ), authorization_event AS (
                INSERT INTO live_order_control_events (
                    control_id,
                    generation,
                    action,
                    from_mode,
                    to_mode,
                    reason_code,
                    reason_text,
                    source,
                    actor_ref,
                    liquidation_operation_id
                )
                SELECT id,
                       generation,
                       'LIQUIDATION_AUTHORIZED',
                       'BLOCK_ALL',
                       'EXIT_ONLY',
                       'MIGRATION_TEST_AUTHORIZED',
                       'terminal ACTIVE authorization downgrade guard test',
                       'SYSTEM',
                       'pytest',
                       operation_id
                FROM authorized_control
                RETURNING id, liquidation_operation_id
            )
            UPDATE liquidation_operations AS operation
            SET emergency_authorization_status = 'ACTIVE',
                emergency_authorized_at = now(),
                emergency_control_generation = control.generation,
                emergency_control_event_id = event.id,
                emergency_authorized_source = 'SYSTEM',
                emergency_revoked_at = NULL,
                emergency_revocation_reason = NULL,
                emergency_closed_at = NULL
            FROM authorization_event AS event,
                 live_order_controls AS control
            WHERE operation.id = event.liquidation_operation_id
              AND control.broker = 'UPBIT'
              AND control.account_scope = 'primary'
            """,
        )
        await _execute(
            target_url_text,
            """
            UPDATE live_order_controls
            SET mode = 'BLOCK_ALL',
                active_liquidation_operation_id = NULL,
                generation = generation + 1,
                version = version + 1
            WHERE broker = 'UPBIT' AND account_scope = 'primary'
            """,
        )
        active_terminal = await _fetch_one(
            target_url_text,
            """
            SELECT status, emergency_authorization_status
            FROM liquidation_operations
            WHERE idempotency_key = '44444444-4444-4444-8444-444444444444'
            """,
        )
        assert tuple(active_terminal) == ("COMPLETED", "ACTIVE")

        blocked = _run_alembic(
            "downgrade",
            BASE_REVISION,
            database_url=target_url_text,
            check=False,
        )
        assert blocked.returncode != 0
        assert "active liquidation exists" in (blocked.stdout + blocked.stderr)
        assert (
            await _fetch_one(target_url_text, "SELECT version_num FROM alembic_version")
        )[0] == TRADING_MODE_REVISION

        await _execute(
            target_url_text,
            """
            UPDATE liquidation_operations
            SET emergency_authorization_status = 'REVOKED',
                emergency_revoked_at = now(),
                emergency_revocation_reason = 'MIGRATION_TEST_CLEANUP',
                emergency_closed_at = NULL
            WHERE idempotency_key = '44444444-4444-4444-8444-444444444444'
            """,
        )

        _run_alembic("downgrade", BASE_REVISION, database_url=target_url_text)
        downgraded = await _fetch_one(
            target_url_text,
            """
            SELECT mirror.config_value,
                   NOT bot.is_active,
                   to_regclass('public.trading_mode_controls')
            FROM system_configs AS mirror
            JOIN bot_configs AS bot ON true
            WHERE mirror.config_key = 'trading_mode'
            """,
        )
        assert tuple(downgraded) == ("paper", True, None)

        await _execute(
            target_url_text,
            "DELETE FROM system_configs WHERE config_key = 'trading_mode'",
        )
        _run_alembic("upgrade", TRADING_MODE_REVISION, database_url=target_url_text)
        remigrated = await _fetch_one(
            target_url_text,
            """
            SELECT control.mode, event.legacy_raw_value, mirror.config_value
            FROM trading_mode_controls AS control
            JOIN trading_mode_control_events AS event ON event.control_id = control.id
            JOIN system_configs AS mirror ON mirror.config_key = 'trading_mode'
            WHERE control.id = 1 AND event.action = 'INITIALIZED'
            """,
        )
        assert tuple(remigrated) == ("paper", None, "paper")
    finally:
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )
        await admin_engine.dispose()
