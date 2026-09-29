import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.domain import (
    LiquidationOperation,
    LiquidationOperationEvent,
    LiquidationOrderCancellation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_REVISION = "c4f8a2d7e1b3"
LIQUIDATION_PROOF_REVISION = "f6b2c9d4e8a1"
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
    return _run_alembic(*args, "--sql").stdout


@pytest.mark.migration
def test_liquidation_proof_upgrade_sql_is_fail_closed_and_auditable() -> None:
    sql = _offline_sql(
        "upgrade",
        f"{BASE_REVISION}:{LIQUIDATION_PROOF_REVISION}",
    )

    preflight = sql.index("DO $atm_p0_004_upgrade$")
    first_column = sql.index("ADD COLUMN broker")
    legacy_backfill = sql.index("UPDATE liquidation_operations")
    active_index = sql.index("CREATE UNIQUE INDEX uq_liquidation_operations_active_account")
    cancellation_table = sql.index("CREATE TABLE liquidation_order_cancellations")
    event_table = sql.index("CREATE TABLE liquidation_operation_events")
    append_only = sql.index("CREATE TRIGGER trg_liquidation_operation_events_append_only")
    assert (
        preflight
        < first_column
        < legacy_backfill
        < active_index
        < cancellation_table
        < event_table
        < append_only
    )

    preflight_sql = sql[preflight:first_column]
    for fragment in (
        "pg_try_advisory_xact_lock(5740495976316385210)",
        "live_order_v2_enabled",
        "mode <> 'BLOCK_ALL'",
        "emergency_authorization_status = 'ACTIVE'",
        "status IN ('PREPARING', 'IN_PROGRESS')",
        "submission_status IN ('PREPARED', 'SUBMITTING', 'UNKNOWN')",
    ):
        assert fragment in preflight_sql

    for fragment in (
        "contract_version INTEGER DEFAULT 2 NOT NULL",
        "request_fingerprint VARCHAR(64)",
        "SET broker = 'UPBIT'",
        "contract_version = 1",
        "cancel_scope = 'LEGACY_NONE'",
        "verification_status = 'LEGACY_UNVERIFIED'",
        "WHERE status IN ('PREPARING', 'IN_PROGRESS')",
        "NUMERIC(38, 18)",
        "ON DELETE RESTRICT",
        "CONSTRAINT uq_liquidation_order_cancellations_operation_uuid",
        "reconcile_attempt_count INTEGER DEFAULT 0 NOT NULL",
        "ck_liquidation_order_cancellations_reconcile_attempt_count",
        "CONSTRAINT uq_liquidation_operation_events_operation_sequence",
        "CREATE TRIGGER trg_liquidation_operations_no_delete",
        "CREATE TRIGGER trg_liquidation_order_cancellations_no_delete",
    ):
        assert fragment in sql


@pytest.mark.migration
def test_liquidation_proof_downgrade_sql_rejects_v2_and_audit_data_before_drop() -> None:
    sql = _offline_sql(
        "downgrade",
        f"{LIQUIDATION_PROOF_REVISION}:{BASE_REVISION}",
    )

    common_preflight = sql.index("DO $atm_p0_004_downgrade$")
    data_guard = sql.index("DO $atm_p0_004_downgrade_data$")
    first_drop = sql.index("DROP TRIGGER")
    assert common_preflight < data_guard < first_drop

    guarded_sql = sql[common_preflight:first_drop]
    for fragment in (
        "active liquidation exists",
        "emergency_authorization_status = 'ACTIVE'",
        "blocking order intent exists",
        "SELECT 1 FROM liquidation_order_cancellations",
        "SELECT 1 FROM liquidation_operation_events",
        "contract_version <> 1",
        "v2 or audit data exists",
    ):
        assert fragment in guarded_sql

    assert "DROP TABLE liquidation_operation_events" in sql[first_drop:]
    assert "DROP TABLE liquidation_order_cancellations" in sql[first_drop:]
    assert "DROP COLUMN contract_version" in sql[first_drop:]


@pytest.mark.migration
def test_liquidation_proof_models_match_migration_contract() -> None:
    operation_table = LiquidationOperation.__table__
    active_index = next(
        index
        for index in operation_table.indexes
        if index.name == "uq_liquidation_operations_active_account"
    )
    assert active_index.unique is True
    assert [column.name for column in active_index.columns] == ["broker", "account_scope"]
    assert "PREPARING" in str(active_index.dialect_options["postgresql"]["where"])

    cancellation_table = LiquidationOrderCancellation.__table__
    cancellation_fks = {foreign_key.name: foreign_key for foreign_key in cancellation_table.foreign_key_constraints}
    assert cancellation_fks["fk_liquidation_order_cancellations_operation_id"].ondelete == "RESTRICT"
    assert cancellation_fks["fk_liquidation_order_cancellations_order_intent_id"].ondelete == "RESTRICT"
    assert cancellation_table.c.executed_volume.type.precision == 38
    assert cancellation_table.c.executed_volume.type.scale == 18
    assert cancellation_table.c.reconcile_attempt_count.nullable is False
    assert cancellation_table.c.reconcile_attempt_count.server_default.arg == "0"
    assert {
        constraint.name for constraint in cancellation_table.constraints
    } >= {
        "ck_liquidation_order_cancellations_reconcile_attempt_count",
    }

    event_table = LiquidationOperationEvent.__table__
    event_fk = next(iter(event_table.foreign_key_constraints))
    assert event_fk.ondelete == "RESTRICT"
    assert {
        constraint.name for constraint in event_table.constraints
    } >= {
        "ck_liquidation_operation_events_event_type",
        "uq_liquidation_operation_events_operation_sequence",
    }


@pytest.mark.migration
def test_liquidation_proof_revision_is_the_single_head() -> None:
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
async def test_liquidation_proof_migration_rejects_active_then_roundtrips_legacy() -> None:
    source_url = make_url(_test_database_url())
    database_name = f"atm_p0_004_roundtrip_{uuid4().hex[:8]}_test"
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
            INSERT INTO liquidation_operations (idempotency_key, status)
            VALUES ('11111111-1111-4111-8111-111111111111', 'IN_PROGRESS')
            """,
        )

        blocked = _run_alembic(
            "upgrade",
            LIQUIDATION_PROOF_REVISION,
            database_url=target_url_text,
            check=False,
        )
        assert blocked.returncode != 0
        assert "active liquidation exists" in (blocked.stdout + blocked.stderr)

        await _execute(
            target_url_text,
            """
            UPDATE liquidation_operations
            SET status = 'FAILED', completed_at = now()
            WHERE idempotency_key = '11111111-1111-4111-8111-111111111111'
            """,
        )

        await _execute(
            target_url_text,
            """
            WITH target_operation AS (
                SELECT id
                FROM liquidation_operations
                WHERE idempotency_key = '11111111-1111-4111-8111-111111111111'
            ), authorization_event AS (
                INSERT INTO live_order_control_events (
                    control_id, generation, action, from_mode, to_mode,
                    reason_code, reason_text, source, liquidation_operation_id
                )
                SELECT control.id, control.generation, 'LIQUIDATION_AUTHORIZED',
                       control.mode, 'EXIT_ONLY', 'TEST_AUTHORIZED',
                       'migration preflight test', 'SYSTEM', operation.id
                FROM live_order_controls AS control
                CROSS JOIN target_operation AS operation
                WHERE control.broker = 'UPBIT' AND control.account_scope = 'primary'
                RETURNING id, generation
            )
            UPDATE liquidation_operations
            SET emergency_authorization_status = 'ACTIVE',
                emergency_authorized_at = now(),
                emergency_control_generation = authorization_event.generation,
                emergency_control_event_id = authorization_event.id,
                emergency_authorized_source = 'SYSTEM',
                emergency_revoked_at = NULL,
                emergency_revocation_reason = NULL,
                emergency_closed_at = NULL
            FROM authorization_event
            WHERE idempotency_key = '11111111-1111-4111-8111-111111111111'
            """,
        )
        blocked_by_authorization = _run_alembic(
            "upgrade",
            LIQUIDATION_PROOF_REVISION,
            database_url=target_url_text,
            check=False,
        )
        assert blocked_by_authorization.returncode != 0
        assert "active liquidation exists" in (
            blocked_by_authorization.stdout + blocked_by_authorization.stderr
        )

        await _execute(
            target_url_text,
            """
            UPDATE liquidation_operations
            SET emergency_authorization_status = 'REVOKED',
                emergency_revoked_at = now(),
                emergency_revocation_reason = 'MIGRATION_TEST_REVOKED'
            WHERE idempotency_key = '11111111-1111-4111-8111-111111111111'
            """,
        )
        _run_alembic("upgrade", LIQUIDATION_PROOF_REVISION, database_url=target_url_text)
        migrated = await _fetch_one(
            target_url_text,
            """
            SELECT contract_version, broker, account_scope, cancel_scope, phase,
                   verification_status, next_run_at
            FROM liquidation_operations
            WHERE idempotency_key = '11111111-1111-4111-8111-111111111111'
            """,
        )
        assert tuple(migrated) == (
            1,
            "UPBIT",
            "primary",
            "LEGACY_NONE",
            "TERMINAL",
            "LEGACY_UNVERIFIED",
            None,
        )

        await _execute(
            target_url_text,
            """
            UPDATE liquidation_operations
            SET emergency_authorization_status = 'ACTIVE',
                emergency_revoked_at = NULL,
                emergency_revocation_reason = NULL
            WHERE idempotency_key = '11111111-1111-4111-8111-111111111111'
            """,
        )
        blocked_downgrade = _run_alembic(
            "downgrade",
            BASE_REVISION,
            database_url=target_url_text,
            check=False,
        )
        assert blocked_downgrade.returncode != 0
        assert "active liquidation exists" in (
            blocked_downgrade.stdout + blocked_downgrade.stderr
        )
        await _execute(
            target_url_text,
            """
            UPDATE liquidation_operations
            SET emergency_authorization_status = 'REVOKED',
                emergency_revoked_at = now(),
                emergency_revocation_reason = 'MIGRATION_TEST_REVOKED'
            WHERE idempotency_key = '11111111-1111-4111-8111-111111111111'
            """,
        )
        _run_alembic("downgrade", BASE_REVISION, database_url=target_url_text)
        downgraded = await _fetch_one(
            target_url_text,
            """
            SELECT version_num,
                   to_regclass('public.liquidation_order_cancellations'),
                   to_regclass('public.liquidation_operation_events')
            FROM alembic_version
            """,
        )
        assert tuple(downgraded) == (BASE_REVISION, None, None)
        _run_alembic("upgrade", LIQUIDATION_PROOF_REVISION, database_url=target_url_text)
    finally:
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )
        await admin_engine.dispose()


@pytest.mark.postgres
@pytest.mark.migration
@pytest.mark.asyncio
async def test_liquidation_proof_v2_guards_indexes_and_append_only_events() -> None:
    source_url = make_url(_test_database_url())
    database_name = f"atm_p0_004_contract_{uuid4().hex[:8]}_test"
    admin_url = source_url.set(database="postgres")
    target_url = source_url.set(database=database_name)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))

        target_url_text = target_url.render_as_string(hide_password=False)
        _run_alembic("upgrade", LIQUIDATION_PROOF_REVISION, database_url=target_url_text)
        await _execute(
            target_url_text,
            """
            INSERT INTO liquidation_operations (
                idempotency_key, status, contract_version, request_fingerprint,
                cancel_scope, phase, verification_status, completed_at
            ) VALUES (
                '22222222-2222-4222-8222-222222222222', 'FAILED', 2,
                repeat('a', 64), 'ACCOUNT_ALL', 'TERMINAL', 'ERROR', now()
            )
            """,
        )
        operation_id = (
            await _fetch_one(
                target_url_text,
                """
                SELECT id FROM liquidation_operations
                WHERE idempotency_key = '22222222-2222-4222-8222-222222222222'
                """,
            )
        )[0]
        await _execute(
            target_url_text,
            f"""
            INSERT INTO liquidation_operation_events (
                liquidation_operation_id, sequence, operation_version, event_type,
                to_phase, source
            ) VALUES ({operation_id}, 1, 0, 'OPERATION_TERMINATED', 'TERMINAL', 'SYSTEM')
            """,
        )
        with pytest.raises(DBAPIError):
            await _execute(
                target_url_text,
                f"UPDATE liquidation_operation_events SET source = 'WORKER' "
                f"WHERE liquidation_operation_id = {operation_id}",
            )

        blocked = _run_alembic(
            "downgrade",
            BASE_REVISION,
            database_url=target_url_text,
            check=False,
        )
        assert blocked.returncode != 0
        assert "v2 or audit data exists" in (blocked.stdout + blocked.stderr)

        await _execute(
            target_url_text,
            """
            INSERT INTO liquidation_operations (
                idempotency_key, status, contract_version, request_fingerprint,
                cancel_scope, phase, verification_status
            ) VALUES (
                '33333333-3333-4333-8333-333333333333', 'PREPARING', 2,
                repeat('b', 64), 'ACCOUNT_ALL', 'BLOCKING', 'PENDING'
            )
            """,
        )
        with pytest.raises(IntegrityError):
            await _execute(
                target_url_text,
                """
                INSERT INTO liquidation_operations (
                    idempotency_key, status, contract_version, request_fingerprint,
                    cancel_scope, phase, verification_status
                ) VALUES (
                    '44444444-4444-4444-8444-444444444444', 'IN_PROGRESS', 2,
                    repeat('c', 64), 'ACCOUNT_ALL', 'DISCOVERING_ORDERS', 'PENDING'
                )
                """,
            )
    finally:
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
            )
        await admin_engine.dispose()
