from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.db.repository import AI_CALIBRATION_MIN_SUCCESS_RATE_KEY
from app.db.repository import AI_ENTRY_SHADOW_MODE_KEY
from app.db.repository import AI_MAX_CONCURRENT_POSITIONS_KEY
from app.db.repository import AI_PROVIDER_PRIORITY_KEY
from app.db.repository import AI_PROVIDER_SETTINGS_KEY
from app.db.repository import AI_PROVIDER_STATUS_KEY
from app.db.repository import AI_TRADE_TARGET_SYMBOLS_KEY
from app.db.repository import LIVE_BUY_ENABLED_KEY
from app.db.repository import LIVE_ORDER_V2_ENABLED_KEY
from app.db.repository import MAX_ALLOCATION_PCT_KEY
from app.services.system_config_service import SystemConfigConflictError
from app.services.system_config_service import SystemConfigMutation
from app.services.system_config_service import SystemConfigProtectedError
from app.services.system_config_service import SystemConfigValidationError
from app.services.system_config_service import mutate_internal_json_config
from app.services.system_config_service import normalize_public_config_value
from app.services.system_config_service import reset_ai_provider_status
from app.services.system_config_service import update_public_system_configs


_ROOT = Path(__file__).resolve().parents[1]
_APP_ROOT = _ROOT / "app"
_LEGACY_CONFIG_WRITERS = {"upsert_system_config", "bulk_upsert_system_configs"}


class _Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)

    def scalar_one_or_none(self) -> Any | None:
        if not self._rows:
            return None
        assert len(self._rows) == 1
        return self._rows[0]


class _FakeDb:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.committed = False
        self.rolled_back = False
        self.refreshed: list[Any] = []

    async def execute(self, _statement: object) -> _Result:
        return _Result(self.rows)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def refresh(self, row: Any) -> None:
        self.refreshed.append(row)


def _row(key: str, value: str, version: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=version,
        config_key=key,
        config_value=value,
        description=None,
        version=version,
    )


@pytest.mark.architecture
def test_application_cannot_bypass_central_system_config_writer() -> None:
    violations: list[str] = []
    for path in _APP_ROOT.rglob("*.py"):
        relative = path.relative_to(_ROOT).as_posix()
        if relative == "app/db/repository.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.db.repository":
                for alias in node.names:
                    if alias.name in _LEGACY_CONFIG_WRITERS:
                        violations.append(f"{relative}:{node.lineno}:{alias.name}")
            if isinstance(node, ast.Attribute) and node.attr in _LEGACY_CONFIG_WRITERS:
                violations.append(f"{relative}:{node.lineno}:{node.attr}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in _LEGACY_CONFIG_WRITERS
            ):
                violations.append(f"{relative}:{node.lineno}:dynamic-getattr")

    assert not violations, "중앙 SystemConfig writer 우회 참조:\n" + "\n".join(violations)


@pytest.mark.parametrize(
    ("config_key", "config_value"),
    [
        (MAX_ALLOCATION_PCT_KEY, "NaN"),
        (MAX_ALLOCATION_PCT_KEY, "Infinity"),
        (MAX_ALLOCATION_PCT_KEY, "1e-999999999"),
        (AI_MAX_CONCURRENT_POSITIONS_KEY, "0"),
        (AI_MAX_CONCURRENT_POSITIONS_KEY, "9" * 10_000),
        (AI_TRADE_TARGET_SYMBOLS_KEY, "[]"),
        (AI_TRADE_TARGET_SYMBOLS_KEY, '["KRW-BTC","krw-btc"]'),
        (AI_PROVIDER_PRIORITY_KEY, '["gemini"]'),
        (AI_PROVIDER_PRIORITY_KEY, '["gemini","gemini"]'),
        ("unknown_config", "1"),
    ],
)
def test_public_config_validation_rejects_invalid_values(
    config_key: str,
    config_value: str,
) -> None:
    with pytest.raises(SystemConfigValidationError):
        normalize_public_config_value(config_key, config_value)


def test_public_config_validation_canonicalizes_decimal_symbols_and_json() -> None:
    assert normalize_public_config_value(MAX_ALLOCATION_PCT_KEY, "030.500") == "30.5"
    assert normalize_public_config_value(AI_CALIBRATION_MIN_SUCCESS_RATE_KEY, "45.250") == "45.25"
    assert (
        normalize_public_config_value(AI_TRADE_TARGET_SYMBOLS_KEY, '["krw-btc","KRW-ETH"]')
        == '["KRW-BTC","KRW-ETH"]'
    )

    provider_settings = {
        "openai": {"enabled": True, "model": "gpt-5-nano"},
        "gemini": {"enabled": False, "model": "gemini-model"},
    }
    canonical = normalize_public_config_value(
        AI_PROVIDER_SETTINGS_KEY,
        json.dumps(provider_settings),
    )
    assert list(json.loads(canonical)) == ["gemini", "openai"]


@pytest.mark.parametrize(
    "settings",
    [
        {
            "gemini": {"enabled": True, "model": 123},
            "openai": {"enabled": True, "model": "gpt-5-nano"},
        },
        {
            "gemini": {"enabled": True, "model": "gemini-model"},
            "openai": {
                "enabled": True,
                "model": "gpt-5-nano",
                "models": {"trade_analysis": False},
            },
        },
    ],
)
def test_provider_models_require_actual_string_values(settings: dict[str, Any]) -> None:
    with pytest.raises(SystemConfigValidationError):
        normalize_public_config_value(AI_PROVIDER_SETTINGS_KEY, json.dumps(settings))


def test_protected_and_internal_keys_are_not_generic_public_mutations() -> None:
    with pytest.raises(SystemConfigProtectedError):
        normalize_public_config_value(LIVE_ORDER_V2_ENABLED_KEY, "true")
    with pytest.raises(SystemConfigValidationError):
        normalize_public_config_value(AI_PROVIDER_STATUS_KEY, "{}")
    with pytest.raises(SystemConfigValidationError):
        normalize_public_config_value(f" {MAX_ALLOCATION_PCT_KEY}", "20")


@pytest.mark.parametrize(
    ("config_key", "config_value"),
    [
        (None, "20"),
        (MAX_ALLOCATION_PCT_KEY, None),
        (123, "20"),
        (MAX_ALLOCATION_PCT_KEY, {"value": 20}),
    ],
)
def test_direct_service_requires_actual_string_key_and_value(
    config_key: Any,
    config_value: Any,
) -> None:
    with pytest.raises(SystemConfigValidationError):
        normalize_public_config_value(
            config_key,  # type: ignore[arg-type]
            config_value,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("expected_version", [True, False, 0, -1, 1.5, "1"])
def test_direct_service_rejects_non_positive_integer_expected_version(
    expected_version: Any,
) -> None:
    db = _FakeDb([_row(MAX_ALLOCATION_PCT_KEY, "30")])
    with pytest.raises(SystemConfigValidationError):
        asyncio.run(
            update_public_system_configs(
                db,  # type: ignore[arg-type]
                [
                    SystemConfigMutation(
                        MAX_ALLOCATION_PCT_KEY,
                        "25",
                        expected_version,  # type: ignore[arg-type]
                    )
                ],
            )
        )
    assert not db.committed


@pytest.mark.parametrize("expected_version", [True, 0, "1"])
def test_provider_reset_rejects_invalid_expected_version(expected_version: Any) -> None:
    db = _FakeDb([_row(AI_PROVIDER_STATUS_KEY, "{}")])
    with pytest.raises(SystemConfigValidationError):
        asyncio.run(
            reset_ai_provider_status(
                db,  # type: ignore[arg-type]
                expected_version=expected_version,  # type: ignore[arg-type]
            )
        )


def test_multi_key_stale_version_rolls_back_without_partial_mutation() -> None:
    allocation = _row(MAX_ALLOCATION_PCT_KEY, "30", version=2)
    positions = _row(AI_MAX_CONCURRENT_POSITIONS_KEY, "2", version=3)
    db = _FakeDb([allocation, positions])

    with pytest.raises(SystemConfigConflictError):
        asyncio.run(
            update_public_system_configs(
                db,  # type: ignore[arg-type]
                [
                    SystemConfigMutation(MAX_ALLOCATION_PCT_KEY, "25", 2),
                    SystemConfigMutation(AI_MAX_CONCURRENT_POSITIONS_KEY, "4", 2),
                ],
            )
        )

    assert allocation.config_value == "30"
    assert positions.config_value == "2"
    assert not db.committed
    assert db.rolled_back


def test_multi_key_cas_updates_values_and_versions_together() -> None:
    allocation = _row(MAX_ALLOCATION_PCT_KEY, "30", version=2)
    positions = _row(AI_MAX_CONCURRENT_POSITIONS_KEY, "2", version=3)
    db = _FakeDb([allocation, positions])

    result = asyncio.run(
        update_public_system_configs(
            db,  # type: ignore[arg-type]
            [
                SystemConfigMutation(MAX_ALLOCATION_PCT_KEY, "25.00", 2),
                SystemConfigMutation(AI_MAX_CONCURRENT_POSITIONS_KEY, "4", 3),
            ],
        )
    )

    assert [(row.config_key, row.config_value, row.version) for row in result] == [
        (AI_MAX_CONCURRENT_POSITIONS_KEY, "4", 4),
        (MAX_ALLOCATION_PCT_KEY, "25", 3),
    ]
    assert db.committed
    assert not db.rolled_back


def test_live_buy_and_shadow_mode_conflict_rolls_back() -> None:
    live_buy = _row(LIVE_BUY_ENABLED_KEY, "false")
    shadow = _row(AI_ENTRY_SHADOW_MODE_KEY, "true")
    db = _FakeDb([live_buy, shadow])

    with pytest.raises(SystemConfigValidationError):
        asyncio.run(
            update_public_system_configs(
                db,  # type: ignore[arg-type]
                [SystemConfigMutation(LIVE_BUY_ENABLED_KEY, "true", 1)],
            )
        )
    assert live_buy.config_value == "false"
    assert db.rolled_back


def test_provider_status_reset_and_internal_mutation_increment_version() -> None:
    status = _row(AI_PROVIDER_STATUS_KEY, '{"gemini":{"reason":"rate_limit"}}', version=4)
    db = _FakeDb([status])
    reset = asyncio.run(
        reset_ai_provider_status(db, expected_version=4)  # type: ignore[arg-type]
    )
    assert reset.config_value == "{}"
    assert reset.version == 5

    second_db = _FakeDb([status])
    mutated = asyncio.run(
        mutate_internal_json_config(
            second_db,  # type: ignore[arg-type]
            config_key=AI_PROVIDER_STATUS_KEY,
            mutator=lambda value: {**value, "openai": {"last_success_at": "now"}},
        )
    )
    assert json.loads(mutated.config_value) == {"openai": {"last_success_at": "now"}}
    assert mutated.version == 6
