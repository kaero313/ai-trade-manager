from datetime import UTC, datetime
from uuid import uuid1, uuid4

import pytest

from app.db.trading_mode_repository import (
    TRADING_MODE_ACTION_LIVE_ENABLED,
    TRADING_MODE_LIVE,
    TRADING_MODE_PAPER,
    TradingModeControlEventRecord,
    TradingModeControlRecord,
    TradingModeIdempotencyConflictError,
    TradingModeRepository,
    TradingModeRequestSupersededError,
    build_trading_mode_request_fingerprint,
)
from app.models.domain import SystemConfig, TradingModeControl


def _fingerprint(**overrides: object) -> str:
    values: dict[str, object] = {
        "action": TRADING_MODE_ACTION_LIVE_ENABLED,
        "expected_version": 1,
        "target_mode": TRADING_MODE_LIVE,
        "reason_code": "OPERATOR_LIVE_ENABLED",
        "reason_text": "운영자가 실거래 모드를 명시적으로 승인했습니다.",
        "source": "REST",
        "actor_ref": "admin:42",
        "confirmation": "ENABLE_LIVE_TRADING",
        "reauth_jti": "11111111-1111-4111-8111-111111111111",
    }
    values.update(overrides)
    return build_trading_mode_request_fingerprint(**values)  # type: ignore[arg-type]


def _control(*, mode: str = TRADING_MODE_LIVE, version: int = 2) -> TradingModeControlRecord:
    now = datetime.now(UTC)
    return TradingModeControlRecord(
        id=1,
        mode=mode,
        version=version,
        reason_code="TEST",
        reason_text="거래 모드 repository 테스트",
        changed_source="SYSTEM",
        changed_actor_ref="pytest",
        changed_at=now,
        created_at=now,
        updated_at=now,
    )


def _event(
    *,
    request_id: str,
    request_fingerprint: str,
    version: int = 2,
) -> TradingModeControlEventRecord:
    return TradingModeControlEventRecord(
        id=7,
        control_id=1,
        version=version,
        request_id=request_id,
        request_fingerprint=request_fingerprint,
        reauth_jti="11111111-1111-4111-8111-111111111111",
        action=TRADING_MODE_ACTION_LIVE_ENABLED,
        from_mode=TRADING_MODE_PAPER,
        to_mode=TRADING_MODE_LIVE,
        reason_code="TEST",
        reason_text="거래 모드 repository 테스트",
        source="REST",
        actor_ref="admin:42",
        legacy_raw_value=None,
        created_at=datetime.now(UTC),
    )


class _ScalarSession:
    def __init__(self, *values: object) -> None:
        self.values = list(values)

    async def scalar(self, _statement):
        return self.values.pop(0)


def test_trading_mode_request_fingerprint_is_canonical_and_complete() -> None:
    canonical = _fingerprint()
    equivalent = _fingerprint(
        action=" live_enabled ",
        target_mode=" LIVE ",
        reason_code=" operator_live_enabled ",
        reason_text=" 운영자가  실거래 모드를 명시적으로 승인했습니다. ",
        source=" rest ",
        actor_ref=" admin:42 ",
        confirmation=" ENABLE_LIVE_TRADING ",
    )

    assert equivalent == canonical
    assert len(canonical) == 64
    assert canonical == canonical.lower()
    assert _fingerprint(expected_version=2) != canonical
    assert _fingerprint(reauth_jti="22222222-2222-4222-8222-222222222222") != canonical


def test_trading_mode_singleton_primary_key_matches_migration_contract() -> None:
    column = TradingModeControl.__table__.c.id

    assert column.autoincrement is False
    assert column.server_default is None


@pytest.mark.asyncio
async def test_get_event_rejects_non_uuid4_before_query() -> None:
    repository = TradingModeRepository()
    session = _ScalarSession()

    with pytest.raises(ValueError, match="UUID v4"):
        await repository.get_event(session, uuid1())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_status_is_available_only_for_exact_control_mirror_match() -> None:
    now = datetime.now(UTC)
    control = TradingModeControl(
        id=1,
        mode=TRADING_MODE_PAPER,
        version=1,
        reason_code="TEST",
        reason_text="strict 상태 테스트",
        changed_source="SYSTEM",
        changed_actor_ref="pytest",
        changed_at=now,
        created_at=now,
        updated_at=now,
    )
    repository = TradingModeRepository()

    available = await repository.status(
        _ScalarSession(
            control,
            SystemConfig(config_key="trading_mode", config_value="paper"),
        )  # type: ignore[arg-type]
    )
    invalid = await repository.status(
        _ScalarSession(
            control,
            SystemConfig(config_key="trading_mode", config_value=" PAPER "),
        )  # type: ignore[arg-type]
    )
    missing = await repository.status(
        _ScalarSession(control, None)  # type: ignore[arg-type]
    )

    assert available.state_available
    assert available.mode == TRADING_MODE_PAPER
    assert available.mirror_consistent
    assert not invalid.state_available
    assert invalid.mode == TRADING_MODE_PAPER
    assert invalid.unavailable_reason == "TRADING_MODE_MIRROR_INVALID"
    assert not missing.state_available
    assert missing.unavailable_reason == "TRADING_MODE_MIRROR_MISSING"


def test_existing_request_replays_only_at_same_current_version() -> None:
    repository = TradingModeRepository()
    request_id = str(uuid4())
    fingerprint = _fingerprint()
    event = _event(request_id=request_id, request_fingerprint=fingerprint)

    replay = repository._resolve_existing_request(
        control=_control(),
        event=event,
        request_fingerprint=fingerprint,
    )
    assert replay.replayed

    with pytest.raises(TradingModeIdempotencyConflictError):
        repository._resolve_existing_request(
            control=_control(),
            event=event,
            request_fingerprint="f" * 64,
        )
    with pytest.raises(TradingModeRequestSupersededError):
        repository._resolve_existing_request(
            control=_control(version=3),
            event=event,
            request_fingerprint=fingerprint,
        )
