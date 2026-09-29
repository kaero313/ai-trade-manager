from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid1, uuid4

import pytest

from app.db.live_order_control_repository import (
    LIVE_ORDER_MODE_ARMED,
    LIVE_ORDER_MODE_BLOCK_ALL,
    LIVE_ORDER_MODE_EXIT_ONLY,
    EmergencyLiquidationAuthorizationRecord,
    LiveOrderControlRecord,
    LiveOrderSubmissionGateSnapshot,
    _normalize_request_id,
    _normalize_target_snapshot,
    build_control_request_fingerprint,
)


def _fingerprint(**overrides: object) -> str:
    values: dict[str, object] = {
        "action": "ARMED",
        "expected_generation": 1,
        "expected_version": 1,
        "target_mode": "ARMED",
        "active_liquidation_operation_id": None,
        "event_liquidation_operation_id": None,
        "reason_code": "OPERATOR_ARMED",
        "reason_text": "운영자가 실주문을 명시적으로 재승인했습니다.",
        "source": "REST",
        "actor_ref": "admin:42",
        "confirmation": "ENABLE_LIVE_ORDERS",
    }
    values.update(overrides)
    return build_control_request_fingerprint(**values)  # type: ignore[arg-type]


def _control(
    *,
    mode: str,
    active_liquidation_operation_id: int | None = None,
) -> LiveOrderControlRecord:
    now = datetime.now(UTC)
    return LiveOrderControlRecord(
        id=1,
        broker="UPBIT",
        account_scope="primary",
        mode=mode,
        active_liquidation_operation_id=active_liquidation_operation_id,
        generation=3,
        version=4,
        reason_code="TEST",
        reason_text="테스트 제어 상태",
        changed_source="SYSTEM",
        changed_actor_ref="pytest",
        armed_at=now if mode == LIVE_ORDER_MODE_ARMED else None,
        blocked_at=now if mode == LIVE_ORDER_MODE_BLOCK_ALL else None,
        created_at=now,
        updated_at=now,
    )


def test_control_request_fingerprint_is_canonical_and_deterministic() -> None:
    canonical = _fingerprint()
    normalized_equivalent = _fingerprint(
        action="  armed  ",
        target_mode=" armed ",
        reason_code=" operator_armed ",
        reason_text="  운영자가   실주문을 명시적으로   재승인했습니다. ",
        source=" rest ",
        actor_ref=" admin:42 ",
        confirmation=" ENABLE_LIVE_ORDERS ",
    )

    assert normalized_equivalent == canonical
    assert len(canonical) == 64
    assert canonical == canonical.lower()
    assert set(canonical) <= set("0123456789abcdef")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_generation", 2),
        ("expected_version", 2),
        ("target_mode", "BLOCK_ALL"),
        ("active_liquidation_operation_id", 17),
        ("event_liquidation_operation_id", 17),
        ("reason_text", "다른 승인 사유입니다."),
        ("actor_ref", "admin:99"),
        ("confirmation", "DIFFERENT_CONFIRMATION"),
    ],
)
def test_control_request_fingerprint_covers_security_relevant_payload(
    field: str,
    value: object,
) -> None:
    assert _fingerprint(**{field: value}) != _fingerprint()


def test_control_request_id_accepts_only_uuid_v4() -> None:
    request_id = uuid4()

    assert _normalize_request_id(request_id) == str(request_id)
    assert _normalize_request_id(str(request_id).upper()) == str(request_id)
    with pytest.raises(ValueError, match="UUID v4"):
        _normalize_request_id(uuid1())
    with pytest.raises(ValueError):
        _normalize_request_id("not-a-uuid")


def test_general_submission_requires_flag_bot_and_armed_control() -> None:
    armed = _control(mode=LIVE_ORDER_MODE_ARMED)

    assert LiveOrderSubmissionGateSnapshot(
        True,
        True,
        armed,
        general_authorization_event_id=5,
        trading_mode="live",
        trading_mode_state_available=True,
    ).general_submission_allowed
    assert not LiveOrderSubmissionGateSnapshot(
        False,
        True,
        armed,
        general_authorization_event_id=5,
    ).general_submission_allowed
    assert not LiveOrderSubmissionGateSnapshot(
        True,
        False,
        armed,
        general_authorization_event_id=5,
    ).general_submission_allowed
    assert not LiveOrderSubmissionGateSnapshot(True, True, armed).general_submission_allowed
    assert not LiveOrderSubmissionGateSnapshot(True, True, None).general_submission_allowed
    assert not LiveOrderSubmissionGateSnapshot(
        True,
        True,
        _control(mode=LIVE_ORDER_MODE_BLOCK_ALL),
    ).general_submission_allowed


def test_emergency_submission_is_scoped_to_one_exit_only_operation() -> None:
    control = _control(
        mode=LIVE_ORDER_MODE_EXIT_ONLY,
        active_liquidation_operation_id=31,
    )
    authorization = EmergencyLiquidationAuthorizationRecord(
        operation_id=31,
        operation_idempotency_key="11111111-1111-4111-8111-111111111111",
        operation_status="IN_PROGRESS",
        authorization_status="ACTIVE",
        control_generation=control.generation,
        control_event_id=7,
        authorized_source="REST",
        event_control_id=control.id,
        event_generation=control.generation,
        event_request_id="11111111-1111-4111-8111-111111111111",
        event_request_fingerprint="f" * 64,
        event_action="LIQUIDATION_AUTHORIZED",
        event_to_mode=LIVE_ORDER_MODE_EXIT_ONLY,
        event_source="REST",
        event_liquidation_operation_id=31,
        target_snapshot=(("KRW-BTC", "0.125"),),
    )
    exit_only = LiveOrderSubmissionGateSnapshot(
        rollout_enabled=True,
        bot_active=False,
        control=control,
        emergency_authorization=authorization,
        trading_mode="live",
        trading_mode_state_available=True,
    )

    assert exit_only.emergency_submission_allowed(31)
    assert authorization.permits_target(market="krw-btc", volume=Decimal("0.1250"))
    assert not authorization.permits_target(market="KRW-ETH", volume=Decimal("0.125"))
    assert not authorization.permits_target(market="KRW-BTC", volume=Decimal("0.124"))
    assert not replace(authorization, event_request_id=None).permits(
        control=control,
        liquidation_operation_id=31,
    )
    assert not replace(authorization, event_source="SYSTEM").permits(
        control=control,
        liquidation_operation_id=31,
    )
    assert not exit_only.emergency_submission_allowed(32)
    assert not exit_only.general_submission_allowed
    assert not LiveOrderSubmissionGateSnapshot(
        rollout_enabled=True,
        bot_active=False,
        control=control,
    ).emergency_submission_allowed(31)
    assert not LiveOrderSubmissionGateSnapshot(
        rollout_enabled=False,
        bot_active=True,
        control=exit_only.control,
        emergency_authorization=authorization,
    ).emergency_submission_allowed(31)
    assert not LiveOrderSubmissionGateSnapshot(
        rollout_enabled=True,
        bot_active=True,
        control=None,
    ).emergency_submission_allowed(31)


def test_liquidation_target_snapshot_requires_unique_positive_decimal_targets() -> None:
    assert _normalize_target_snapshot(
        [
            {"market": "krw-eth", "volume": "2.500"},
            {"market": "KRW-BTC", "volume": "0.1"},
        ]
    ) == (("KRW-BTC", "0.1"), ("KRW-ETH", "2.500"))
    assert _normalize_target_snapshot(None) is None
    assert _normalize_target_snapshot([{"market": "KRW-BTC", "volume": "0"}]) is None
    assert (
        _normalize_target_snapshot(
            [
                {"market": "KRW-BTC", "volume": "0.1"},
                {"market": "krw-btc", "volume": "0.2"},
            ]
        )
        is None
    )
