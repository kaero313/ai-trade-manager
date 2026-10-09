from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError

from app.api.routes import status as status_route
from app.models.schemas import (
    ArmLiveOrderGateRequest,
    BotStatus,
    LiquidateAllRequest,
    LiquidationOperationResponse,
    LiveOrderGateStatus,
)
from app.services import bot_service
from app.services.trading.live_order_control import LiveOrderControlServiceError


NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)


def _gate(
    *,
    mode: str = "BLOCK_ALL",
    active_liquidation_operation_id: int | None = None,
) -> LiveOrderGateStatus:
    return LiveOrderGateStatus(
        mode=mode,
        generation=3,
        version=7,
        reason_code="OPERATOR_BLOCK",
        reason="운영자가 신규 실주문을 명시적으로 차단했습니다.",
        source="REST",
        changed_at=NOW,
        active_liquidation_operation_id=active_liquidation_operation_id,
        rollout_enabled=True,
        state_available=True,
    )


def test_liquidation_request_requires_typed_confirmation() -> None:
    with pytest.raises(ValidationError):
        LiquidateAllRequest(
            scope="ACCOUNT_ALL",
            confirmation="LIQUIDATE_ALL",  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_start_endpoint_only_starts_runtime_and_never_arms(monkeypatch) -> None:
    called = {"start": 0}

    async def fake_start(_db):
        called["start"] += 1

    async def fake_status(_db):
        return BotStatus(running=True, live_order_mode="BLOCK_ALL")

    def forbidden_control_service():
        raise AssertionError("start endpoint는 order gate 서비스에 접근하면 안 됩니다.")

    monkeypatch.setattr(status_route, "start_bot", fake_start)
    monkeypatch.setattr(status_route, "get_bot_status", fake_status)
    monkeypatch.setattr(
        status_route,
        "_live_order_control_service",
        forbidden_control_service,
    )

    result = await status_route.start_bot_endpoint(db=object(), _admin=None)

    assert called["start"] == 1
    assert result.running is True
    assert result.live_order_mode == "BLOCK_ALL"


@pytest.mark.asyncio
async def test_stop_endpoint_uses_control_service_and_not_legacy_stop(monkeypatch) -> None:
    commands = []

    class _ControlService:
        async def stop_bot(self, command):
            commands.append(command)

    async def forbidden_legacy_stop(_db):
        raise AssertionError("REST stop은 legacy stop_bot을 호출하면 안 됩니다.")

    async def fake_gate(_db):
        return _gate()

    async def fake_status(_db):
        return BotStatus(
            running=False,
            live_order_mode="BLOCK_ALL",
            live_order_generation=3,
            live_order_version=7,
        )

    monkeypatch.setattr(
        status_route,
        "_live_order_control_service",
        lambda: _ControlService(),
    )
    monkeypatch.setattr(status_route, "stop_bot", forbidden_legacy_stop)
    monkeypatch.setattr(status_route, "get_live_order_gate_status", fake_gate)
    monkeypatch.setattr(status_route, "get_bot_status", fake_status)

    result = await status_route.stop_bot_endpoint(db=object(), _admin=None)

    assert result.running is False
    assert len(commands) == 1
    assert commands[0].source == "REST"
    assert commands[0].actor_ref == "rest-admin"
    assert commands[0].reason_code == "OPERATOR_STOP"


def test_arm_request_requires_exact_confirmation_and_substantive_reason() -> None:
    with pytest.raises(ValidationError):
        ArmLiveOrderGateRequest(
            expected_generation=1,
            expected_version=1,
            reason="운영자가 충분히 검토한 재무장 사유입니다.",
            confirmation="enable_live_orders",
        )

    with pytest.raises(ValidationError):
        ArmLiveOrderGateRequest(
            expected_generation=1,
            expected_version=1,
            reason=" " * 20,
            confirmation="ENABLE_LIVE_ORDERS",
        )


@pytest.mark.asyncio
async def test_arm_endpoint_maps_conflict_and_returns_current_gate(monkeypatch) -> None:
    class _ControlService:
        async def arm(self, _command):
            raise LiveOrderControlServiceError(
                "generation이 변경되었습니다.",
                error_code="ORDER_GATE_GENERATION_CONFLICT",
            )

    async def fake_gate(_db):
        return _gate()

    monkeypatch.setattr(
        status_route,
        "_live_order_control_service",
        lambda: _ControlService(),
    )
    monkeypatch.setattr(status_route, "get_live_order_gate_status", fake_gate)

    payload = ArmLiveOrderGateRequest(
        expected_generation=3,
        expected_version=7,
        reason="운영자가 주문 상태와 배포 상태를 모두 확인했습니다.",
        confirmation="ENABLE_LIVE_ORDERS",
    )
    with pytest.raises(HTTPException) as exc_info:
        await status_route.arm_order_gate_endpoint(
            payload=payload,
            idempotency_key=str(uuid4()),
            db=object(),
            _admin=None,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "ORDER_GATE_GENERATION_CONFLICT"
    assert exc_info.value.detail["order_gate"]["mode"] == "BLOCK_ALL"


@pytest.mark.parametrize(
    ("error_code", "expected_status"),
    [
        ("LIVE_ORDER_GATE_BLOCKED", 423),
        ("EMERGENCY_AUTH_REVOKED", 409),
        ("ORDER_GATE_BARRIER_TIMEOUT", 503),
        ("ORDER_GATE_DRAIN_PENDING", 503),
        ("ORDER_GATE_STATE_UNAVAILABLE", 503),
    ],
)
def test_control_error_status_is_stable(error_code: str, expected_status: int) -> None:
    assert status_route._control_error_status(error_code) == expected_status


@pytest.mark.asyncio
async def test_order_gate_get_maps_repository_failure_to_503(monkeypatch) -> None:
    async def failed_gate(_db, *, suppress_repository_errors: bool):
        assert suppress_repository_errors is False
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(status_route, "get_live_order_gate_status", failed_gate)

    with pytest.raises(HTTPException) as exc_info:
        await status_route.get_order_gate_endpoint(db=object(), _admin=None)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error_code"] == "ORDER_GATE_STATE_UNAVAILABLE"
    assert exc_info.value.detail["order_gate"]["mode"] == "BLOCK_ALL"


@pytest.mark.asyncio
async def test_bot_status_is_fail_closed_when_control_row_is_missing(monkeypatch) -> None:
    class _Repository:
        async def get_rollout_flag(self, _db) -> bool:
            return True

        async def get_control(self, _db):
            return None

    class _Db:
        async def refresh(self, _model) -> None:
            return None

    async def fake_get_config(_db):
        return SimpleNamespace(
            is_active=True,
            config_json={"runtime_status": {"latest_action": "분석 중"}},
            runtime_last_heartbeat=None,
            runtime_last_error=None,
            runtime_latest_action="분석 중",
            runtime_updated_at=None,
        )

    monkeypatch.setattr(bot_service, "get_or_create_bot_config", fake_get_config)
    monkeypatch.setattr(bot_service, "LiveOrderControlRepository", _Repository)

    result = await bot_service.get_bot_status(_Db())

    assert result.running is True
    assert result.live_order_mode == "BLOCK_ALL"
    assert result.live_order_generation == 0
    assert result.live_order_state_available is False
    assert result.live_order_reason_code == "ORDER_GATE_STATE_UNAVAILABLE"
    assert result.live_order_rollout_enabled is True


@pytest.mark.asyncio
async def test_liquidate_endpoint_does_not_call_legacy_stop(monkeypatch) -> None:
    operation = LiquidationOperationResponse(
        id=9,
        idempotency_key=str(uuid4()),
        status="IN_PROGRESS",
        items=[],
        created_at=NOW,
        updated_at=NOW,
    )
    legacy_stop_called = False

    class _Coordinator:
        async def execute(self, idempotency_key: str, **_kwargs):
            assert idempotency_key == operation.idempotency_key
            return operation

    async def fake_legacy_stop(_db):
        nonlocal legacy_stop_called
        legacy_stop_called = True

    monkeypatch.setattr(status_route, "_liquidation_coordinator", lambda: _Coordinator())
    monkeypatch.setattr(status_route, "stop_bot", fake_legacy_stop)
    response = Response()

    result = await status_route.liquidate_all_endpoint(
        payload=LiquidateAllRequest(
            scope="ACCOUNT_ALL",
            confirmation="CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL",
        ),
        response=response,
        idempotency_key=operation.idempotency_key,
        db=object(),
        _admin=None,
    )

    assert result.id == operation.id
    assert response.status_code == 202
    assert legacy_stop_called is False


@pytest.mark.asyncio
async def test_liquidation_get_endpoint_reads_persisted_operation_only(monkeypatch) -> None:
    operation = LiquidationOperationResponse(
        id=19,
        idempotency_key=str(uuid4()),
        status="IN_PROGRESS",
        phase="VERIFYING",
        verification_status="PENDING",
        items=[],
        created_at=NOW,
        updated_at=NOW,
    )

    class _Coordinator:
        async def get_operation(self, operation_id: int):
            assert operation_id == operation.id
            return operation

        async def refresh_operation(self, _operation_id: int):
            raise AssertionError("GET은 worker를 실행하면 안 됩니다.")

    monkeypatch.setattr(status_route, "_liquidation_coordinator", lambda: _Coordinator())

    result = await status_route.get_liquidation_operation(
        operation.id,
        db=object(),
        _admin=None,
    )

    assert result is operation


@pytest.mark.asyncio
async def test_liquidate_endpoint_maps_revoked_operation_to_conflict(monkeypatch) -> None:
    class _Coordinator:
        async def execute(self, _idempotency_key: str, **_kwargs):
            raise LiveOrderControlServiceError(
                "폐기된 청산 operation입니다.",
                error_code="EMERGENCY_AUTH_REVOKED",
            )

    async def fake_gate(_db):
        return _gate()

    monkeypatch.setattr(status_route, "_liquidation_coordinator", lambda: _Coordinator())
    monkeypatch.setattr(status_route, "get_live_order_gate_status", fake_gate)

    with pytest.raises(HTTPException) as exc_info:
        await status_route.liquidate_all_endpoint(
            payload=LiquidateAllRequest(
                scope="ACCOUNT_ALL",
                confirmation="CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL",
            ),
            response=Response(),
            idempotency_key=str(uuid4()),
            db=object(),
            _admin=None,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "EMERGENCY_AUTH_REVOKED"


@pytest.mark.asyncio
async def test_liquidate_conflict_includes_active_operation_status(monkeypatch) -> None:
    operation = LiquidationOperationResponse(
        id=77,
        idempotency_key=str(uuid4()),
        status="IN_PROGRESS",
        items=[],
        created_at=NOW,
        updated_at=NOW,
        completed_at=None,
    )

    class _Coordinator:
        async def execute(self, _idempotency_key: str, **_kwargs):
            raise LiveOrderControlServiceError(
                "다른 청산 operation이 진행 중입니다.",
                error_code="ORDER_GATE_GENERATION_CONFLICT",
            )

        async def get_operation(self, operation_id: int):
            assert operation_id == operation.id
            return operation

    async def fake_gate(_db):
        return _gate(
            mode="EXIT_ONLY",
            active_liquidation_operation_id=operation.id,
        )

    monkeypatch.setattr(status_route, "_liquidation_coordinator", lambda: _Coordinator())
    monkeypatch.setattr(status_route, "get_live_order_gate_status", fake_gate)

    with pytest.raises(HTTPException) as exc_info:
        await status_route.liquidate_all_endpoint(
            payload=LiquidateAllRequest(
                scope="ACCOUNT_ALL",
                confirmation="CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL",
            ),
            response=Response(),
            idempotency_key=str(uuid4()),
            db=object(),
            _admin=None,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["active_liquidation_operation"]["id"] == operation.id
