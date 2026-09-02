from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_HEAD_REVISION = "f6b2c9d4e8a1"
RATE_LIMIT_REVISION = "b8d4e6f1a2c3"
CURRENT_HEAD_REVISION = "b7e3f9a4c6d2"


def _run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
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
def test_rate_limit_revision_has_the_expected_single_head() -> None:
    result = _run_alembic("heads")
    assert result.stdout.strip() == f"{CURRENT_HEAD_REVISION} (head)"


@pytest.mark.migration
def test_rate_limit_upgrade_offline_sql_contains_atomic_window_schema() -> None:
    result = _run_alembic(
        "upgrade",
        f"{PREVIOUS_HEAD_REVISION}:{RATE_LIMIT_REVISION}",
        "--sql",
    )
    sql = result.stdout

    for fragment in (
        "CREATE TABLE api_rate_limit_windows",
        "CONSTRAINT pk_api_rate_limit_windows PRIMARY KEY",
        "CONSTRAINT ck_api_rate_limit_windows_policy_key",
        "CONSTRAINT ck_api_rate_limit_windows_subject_hash_hex",
        "CONSTRAINT ck_api_rate_limit_windows_request_count",
        "CONSTRAINT ck_api_rate_limit_windows_rejected_count",
        "CREATE INDEX ix_api_rate_limit_windows_cleanup_due",
    ):
        assert fragment in sql

    assert "policy_key VARCHAR(48) NOT NULL" in sql
    assert "subject_hash VARCHAR(64) NOT NULL" in sql
    assert "window_started_at TIMESTAMP WITH TIME ZONE NOT NULL" in sql
    assert "request_count BIGINT DEFAULT 1 NOT NULL" in sql
    assert "rejected_count BIGINT DEFAULT 0 NOT NULL" in sql


@pytest.mark.migration
def test_rate_limit_downgrade_offline_sql_drops_only_rate_limit_schema() -> None:
    result = _run_alembic(
        "downgrade",
        f"{RATE_LIMIT_REVISION}:{PREVIOUS_HEAD_REVISION}",
        "--sql",
    )
    sql = result.stdout

    assert "DROP INDEX ix_api_rate_limit_windows_cleanup_due" in sql
    assert "DROP TABLE api_rate_limit_windows" in sql
    assert "DROP TABLE order_intents" not in sql
    assert "DROP TABLE liquidation_operations" not in sql
