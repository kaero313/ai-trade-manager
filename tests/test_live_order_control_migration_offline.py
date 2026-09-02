import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_REVISION = "e7b4c9a1d2f6"
CONTROL_REVISION = "a91f3e7c5b2d"


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
def test_control_upgrade_offline_sql_contains_fail_closed_ledger_contract() -> None:
    sql = _offline_sql("upgrade", f"{BASE_REVISION}:{CONTROL_REVISION}")

    required_fragments = (
        "CREATE TABLE live_order_controls",
        "CREATE TABLE live_order_control_events",
        "CONSTRAINT ck_live_order_controls_active_liquidation",
        "CONSTRAINT ck_live_order_control_events_liquidation_action",
        "CONSTRAINT ck_liquidation_operations_emergency_authorization_coherence",
        "CONSTRAINT ck_order_intents_submission_authorization_snapshot",
        "CONSTRAINT fk_live_order_controls_active_liquidation_operation_id",
        "CONSTRAINT fk_live_order_control_events_control_id",
        "CONSTRAINT fk_live_order_control_events_liquidation_operation_id",
        "CONSTRAINT fk_liquidation_operations_emergency_control_event_id",
        "CONSTRAINT fk_order_intents_control_event_id",
        "INSERT INTO live_order_controls",
        "INSERT INTO live_order_control_events",
    )
    for fragment in required_fragments:
        assert fragment in sql

    control_table = sql.index("CREATE TABLE live_order_controls")
    event_table = sql.index("CREATE TABLE live_order_control_events")
    control_seed = sql.index("INSERT INTO live_order_controls")
    event_seed = sql.index("INSERT INTO live_order_control_events")
    assert control_table < event_table < control_seed < event_seed

    control_seed_sql = sql[control_seed:event_seed]
    for fragment in ("'UPBIT'", "'primary'", "'BLOCK_ALL'", "'MIGRATION_INITIALIZED'"):
        assert fragment in control_seed_sql

    event_seed_sql = sql[event_seed:]
    for fragment in ("'INITIALIZED'", "'BLOCK_ALL'", "FROM live_order_controls"):
        assert fragment in event_seed_sql


@pytest.mark.migration
def test_control_downgrade_offline_sql_runs_preflight_before_first_drop() -> None:
    sql = _offline_sql("downgrade", f"{CONTROL_REVISION}:{BASE_REVISION}")

    preflight = sql.index("DO $atm_p0_002$")
    first_drop = sql.index(" DROP ")
    assert preflight < first_drop
    preflight_sql = sql[preflight:first_drop]

    required_guard_fragments = (
        "pg_try_advisory_xact_lock(5740495976316385210)",
        "config_key = 'live_order_v2_enabled'",
        "lower(btrim(config_value)) = 'false'",
        "mode <> 'BLOCK_ALL'",
        "active_liquidation_operation_id IS NOT NULL",
        "emergency_authorization_status = 'ACTIVE'",
        "submission_status IN ('PREPARED', 'SUBMITTING', 'UNKNOWN')",
        "submission_status = 'ACCEPTED'",
        "projection_status IN ('PENDING', 'ERROR')",
    )
    for fragment in required_guard_fragments:
        assert fragment in preflight_sql

    assert "DROP TABLE live_order_control_events" in sql[first_drop:]
    assert "DROP TABLE live_order_controls" in sql[first_drop:]


def _test_database_url() -> str:
    url = str(os.getenv("TEST_DATABASE_URL") or "").strip()
    if not url:
        if os.getenv("CI"):
            pytest.fail("CI PostgreSQL migration 테스트에는 TEST_DATABASE_URL이 필요합니다.")
        pytest.skip("TEST_DATABASE_URL이 없어 PostgreSQL migration 테스트를 건너뜁니다.")

    database_name = make_url(url).database or ""
    if not database_name.endswith("_test"):
        pytest.fail("운영 DB 오접속 방지를 위해 테스트 DB 이름은 _test로 끝나야 합니다.")
    return url


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


async def _assert_downgrade_blocked(
    database_url: str,
    expected_message: str,
) -> None:
    blocked = _run_alembic(
        "downgrade",
        BASE_REVISION,
        database_url=database_url,
        check=False,
    )
    assert blocked.returncode != 0
    assert expected_message in (blocked.stdout + blocked.stderr)
    persisted = await _fetch_one(
        database_url,
        """
        SELECT version_num,
               to_regclass('public.live_order_controls'),
               to_regclass('public.live_order_control_events')
        FROM alembic_version
        """,
    )
    assert tuple(persisted) == (
        CONTROL_REVISION,
        "live_order_controls",
        "live_order_control_events",
    )


@pytest.mark.postgres
@pytest.mark.migration
@pytest.mark.asyncio
async def test_control_migration_guarded_downgrade_and_reupgrade_on_postgres() -> None:
    source_url = make_url(_test_database_url())
    database_name = f"atm_p0_002_{uuid4().hex[:12]}_test"
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
            INSERT INTO liquidation_operations (
                idempotency_key,
                status,
                completed_at
            )
            VALUES
                ('11111111-1111-4111-8111-111111111111', 'PREPARING', NULL),
                ('22222222-2222-4222-8222-222222222222', 'COMPLETED', now())
            """,
        )
        _run_alembic("upgrade", CONTROL_REVISION, database_url=target_url_text)

        control = await _fetch_one(
            target_url_text,
            """
            SELECT control.mode,
                   control.active_liquidation_operation_id,
                   event.action,
                   event.to_mode
            FROM live_order_controls AS control
            JOIN live_order_control_events AS event
              ON event.control_id = control.id
            WHERE control.broker = 'UPBIT'
              AND control.account_scope = 'primary'
              AND event.action = 'INITIALIZED'
            """,
        )
        assert tuple(control) == ("BLOCK_ALL", None, "INITIALIZED", "BLOCK_ALL")

        migrated_operations = await _fetch_one(
            target_url_text,
            """
            SELECT
                count(*) FILTER (
                    WHERE status = 'PREPARING'
                      AND emergency_authorization_status = 'REVOKED'
                      AND emergency_revoked_at IS NOT NULL
                      AND emergency_revocation_reason = 'MIGRATION_NOT_AUTHORIZED'
                ),
                count(*) FILTER (
                    WHERE status = 'COMPLETED'
                      AND emergency_authorization_status = 'CLOSED'
                      AND emergency_closed_at IS NOT NULL
                      AND emergency_revoked_at IS NULL
                      AND emergency_revocation_reason IS NULL
                )
            FROM liquidation_operations
            """,
        )
        assert tuple(migrated_operations) == (1, 1)

        await _execute(
            target_url_text,
            """
            UPDATE system_configs
            SET config_value = 'true'
            WHERE config_key = 'live_order_v2_enabled'
            """,
        )
        await _assert_downgrade_blocked(
            target_url_text,
            "live_order_v2_enabled is not false",
        )

        await _execute(
            target_url_text,
            """
            UPDATE system_configs
            SET config_value = 'false'
            WHERE config_key = 'live_order_v2_enabled'
            """,
        )
        await _execute(
            target_url_text,
            """
            UPDATE live_order_controls
            SET mode = 'ARMED',
                active_liquidation_operation_id = NULL,
                generation = generation + 1,
                version = version + 1
            WHERE broker = 'UPBIT' AND account_scope = 'primary'
            """,
        )
        await _assert_downgrade_blocked(
            target_url_text,
            "controls are not BLOCK_ALL",
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
        await _execute(
            target_url_text,
            """
            INSERT INTO liquidation_operations (idempotency_key, status)
            VALUES ('33333333-3333-4333-8333-333333333333', 'IN_PROGRESS')
            """,
        )
        await _execute(
            target_url_text,
            """
            WITH operation AS (
                SELECT id
                FROM liquidation_operations
                WHERE idempotency_key = '33333333-3333-4333-8333-333333333333'
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
                       'downgrade ACTIVE authorization guard test',
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
        active_authorization = await _fetch_one(
            target_url_text,
            """
            SELECT status, emergency_authorization_status
            FROM liquidation_operations
            WHERE idempotency_key = '33333333-3333-4333-8333-333333333333'
            """,
        )
        assert tuple(active_authorization) == ("IN_PROGRESS", "ACTIVE")
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
        await _assert_downgrade_blocked(
            target_url_text,
            "active liquidation authorization exists",
        )

        await _execute(
            target_url_text,
            """
            UPDATE liquidation_operations
            SET emergency_authorization_status = 'REVOKED',
                emergency_revoked_at = now(),
                emergency_revocation_reason = 'MIGRATION_TEST_CLEANUP',
                emergency_closed_at = NULL
            WHERE emergency_authorization_status = 'ACTIVE'
            """,
        )
        await _execute(
            target_url_text,
            """
            INSERT INTO order_intents (
                intent_key,
                identifier,
                request_fingerprint,
                source_type,
                source_ref,
                execution_policy,
                broker,
                account_scope,
                market,
                side,
                ord_type,
                requested_price,
                requested_volume
            )
            VALUES (
                repeat('d', 64),
                repeat('d', 32),
                repeat('e', 64),
                'TEST',
                'migration-blocking-intent',
                'GENERAL',
                'UPBIT',
                'primary',
                'KRW-BTC',
                'bid',
                'price',
                5000,
                NULL
            )
            """,
        )
        await _assert_downgrade_blocked(
            target_url_text,
            "blocking order intent exists",
        )
        await _execute(target_url_text, "DELETE FROM order_intents")

        lock_engine = create_async_engine(target_url_text, pool_pre_ping=True)
        try:
            async with lock_engine.connect() as lock_connection:
                await lock_connection.execute(
                    text("SELECT pg_advisory_lock_shared(5740495976316385210)")
                )
                await lock_connection.commit()
                await _assert_downgrade_blocked(
                    target_url_text,
                    "advisory lock is busy",
                )
                await lock_connection.execute(
                    text("SELECT pg_advisory_unlock_shared(5740495976316385210)")
                )
                await lock_connection.commit()
        finally:
            await lock_engine.dispose()

        _run_alembic(
            "downgrade",
            BASE_REVISION,
            database_url=target_url_text,
        )
        revision_after_downgrade = await _fetch_one(
            target_url_text,
            "SELECT version_num FROM alembic_version",
        )
        assert revision_after_downgrade[0] == BASE_REVISION

        _run_alembic("upgrade", CONTROL_REVISION, database_url=target_url_text)
        revision_after_reupgrade = await _fetch_one(
            target_url_text,
            "SELECT version_num FROM alembic_version",
        )
        assert revision_after_reupgrade[0] == CONTROL_REVISION
    finally:
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )
        await admin_engine.dispose()
