from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import settings
from app.db.live_order_control_repository import (
    LIVE_ORDER_MODE_BLOCK_ALL,
    LiveOrderControlRecord,
    LiveOrderSubmissionGateSnapshot,
)
from app.db.trading_mode_repository import (
    TRADING_MODE_ACTION_LIVE_ENABLED,
    TRADING_MODE_ACTION_PAPER_CONFIRMED,
    TRADING_MODE_LIVE,
    TRADING_MODE_PAPER,
    TradingModeControlEventRecord,
    TradingModeControlRecord,
    TradingModeStatusRecord,
    TradingModeStateUnavailableError,
    TradingModeTransitionResult,
)
from app.services.trading.admin_reauth import (
    AdminReauthError,
    issue_admin_reauth_proof,
    verify_admin_reauth_proof,
)
from app.services.trading import paper as paper_service
from app.services.trading.trading_mode_control import (
    EnableLiveTradingModeCommand,
    EnablePaperTradingModeCommand,
    TradingModeControlPolicyError,
    TradingModeControlService,
    to_trading_mode_status,
)


def _mode_control(*, mode: str = TRADING_MODE_PAPER, version: int = 1):
    now = datetime.now(UTC)
    return TradingModeControlRecord(
        id=1,
        mode=mode,
        version=version,
        reason_code="TEST_MODE",
        reason_text="테스트 거래 모드 상태",
        changed_source="SYSTEM",
        changed_actor_ref="pytest",
        changed_at=now,
        created_at=now,
        updated_at=now,
    )


def _mode_event(
    *,
    request_id: str,
    fingerprint: str = "f" * 64,
    mode: str = TRADING_MODE_LIVE,
    version: int = 2,
    reauth_jti: str | None = None,
):
    return TradingModeControlEventRecord(
        id=11,
        control_id=1,
        version=version,
        request_id=request_id,
        request_fingerprint=fingerprint,
        reauth_jti=reauth_jti,
        action=(
            TRADING_MODE_ACTION_LIVE_ENABLED
            if mode == TRADING_MODE_LIVE
            else TRADING_MODE_ACTION_PAPER_CONFIRMED
        ),
        from_mode=TRADING_MODE_PAPER,
        to_mode=mode,
        reason_code="TEST_MODE",
        reason_text="테스트 거래 모드 전환 사유",
        source="REST",
        actor_ref="rest-admin",
        legacy_raw_value=None,
        created_at=datetime.now(UTC),
    )


def _gate_control() -> LiveOrderControlRecord:
    now = datetime.now(UTC)
    return LiveOrderControlRecord(
        id=1,
        broker="UPBIT",
        account_scope="primary",
        mode=LIVE_ORDER_MODE_BLOCK_ALL,
        active_liquidation_operation_id=None,
        generation=3,
        version=5,
        reason_code="TEST_BLOCK",
        reason_text="테스트 전역 차단",
        changed_source="SYSTEM",
        changed_actor_ref="pytest",
        armed_at=None,
        blocked_at=now,
        created_at=now,
        updated_at=now,
    )


class _Session:
    async def commit(self) -> None:
        return None


class _SessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return _Session()

    async def __aexit__(self, *_args):
        return False


class _Lease:
    @asynccontextmanager
    async def transaction(self):
        yield _Session()


class _Barrier:
    @asynccontextmanager
    async def exclusive(self):
        yield _Lease()


class _ModeRepository:
    def __init__(
        self,
        *,
        status: TradingModeStatusRecord,
        existing_event: TradingModeControlEventRecord | None = None,
    ) -> None:
        self.current_status = status
        self.existing_event = existing_event
        self.transition_calls: list[dict] = []

    async def status(self, _db, *, for_update: bool = False):
        _ = for_update
        return self.current_status

    async def get_event(self, _db, _request_id):
        return self.existing_event

    async def transition(self, _db, **kwargs):
        self.transition_calls.append(kwargs)
        control = _mode_control(
            mode=kwargs["target_mode"],
            version=self.current_status.control.version + 1,
        )
        event = _mode_event(
            request_id=str(kwargs["request_id"]),
            fingerprint=kwargs["request_fingerprint"],
            mode=kwargs["target_mode"],
            version=control.version,
            reauth_jti=kwargs["reauth_jti"],
        )
        return TradingModeTransitionResult(control=control, event=event, replayed=False)


class _LiveOrderRepository:
    def __init__(
        self,
        gate: LiveOrderSubmissionGateSnapshot,
        *,
        blocking: bool = False,
        active_liquidation: bool = False,
    ):
        self.gate = gate
        self.blocking = blocking
        self.active_liquidation = active_liquidation

    async def get_submission_gate_snapshot(self, _db):
        return self.gate

    async def has_blocking_intent(self, _db, *, include_prepared: bool):
        assert include_prepared is True
        return self.blocking

    async def has_active_liquidation_operation(self, _db):
        return self.active_liquidation


class _LiveOrderControlService:
    def __init__(self) -> None:
        self.stop_commands = []

    async def stop_bot(self, command):
        self.stop_commands.append(command)
        return SimpleNamespace()


def _available_status(*, mode: str = TRADING_MODE_PAPER, version: int = 1):
    control = _mode_control(mode=mode, version=version)
    return TradingModeStatusRecord(
        mode=mode,
        state_available=True,
        control=control,
        mirror_value=mode,
    )


def _blocked_gate(*, rollout_enabled: bool = True, bot_active: bool = False):
    return LiveOrderSubmissionGateSnapshot(
        rollout_enabled=rollout_enabled,
        bot_active=bot_active,
        control=_gate_control(),
        trading_mode=TRADING_MODE_PAPER,
        trading_mode_state_available=True,
    )


def _service(
    mode_repository: _ModeRepository,
    *,
    gate: LiveOrderSubmissionGateSnapshot | None = None,
    blocking: bool = False,
    active_liquidation: bool = False,
    clock=None,
):
    live_control = _LiveOrderControlService()
    service = TradingModeControlService(
        _SessionFactory(),
        _Barrier(),
        repository=mode_repository,
        live_order_repository=_LiveOrderRepository(
            gate or _blocked_gate(),
            blocking=blocking,
            active_liquidation=active_liquidation,
        ),
        live_order_control_service=live_control,
        clock=clock,
    )
    return service, live_control


def test_unavailable_status_is_effective_paper() -> None:
    status = to_trading_mode_status(
        TradingModeStatusRecord(
            mode=TRADING_MODE_PAPER,
            state_available=False,
            control=_mode_control(mode=TRADING_MODE_LIVE, version=7),
            mirror_value="paper",
            unavailable_reason="TRADING_MODE_MIRROR_MISMATCH",
        )
    )

    assert status.mode == "paper"
    assert status.version == 7
    assert status.state_available is False
    assert status.mirror_consistent is False


def test_enable_live_keeps_runtime_and_gate_blocked(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "fresh-admin-token")
    monkeypatch.setattr(
        settings,
        "admin_reauth_signing_secret",
        "9M5yG2!qR7#vX4@kL8$pN6^tB3&zC1*wH0+sD",
    )
    proof = issue_admin_reauth_proof(
        "fresh-admin-token",
        purpose="ENABLE_LIVE_TRADING",
    )
    repository = _ModeRepository(status=_available_status())
    gate = _blocked_gate()
    service, live_control = _service(repository, gate=gate)

    result = asyncio.run(
        service.enable_live(
            EnableLiveTradingModeCommand(
                request_id=uuid4(),
                expected_version=1,
                expected_gate_generation=gate.control.generation,
                expected_gate_version=gate.control.version,
                reason_text="운영자 검증을 마치고 live 모드를 활성화합니다.",
                confirmation="ENABLE_LIVE_TRADING",
                reauth_proof=proof.proof,
            )
        )
    )

    assert result.control.mode == "live"
    assert repository.transition_calls[0]["reauth_jti"] == proof.jti
    assert live_control.stop_commands == []
    assert gate.bot_active is False
    assert gate.control.mode == "BLOCK_ALL"


def test_enable_live_rejects_active_runtime_before_transition(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "fresh-admin-token")
    monkeypatch.setattr(
        settings,
        "admin_reauth_signing_secret",
        "9M5yG2!qR7#vX4@kL8$pN6^tB3&zC1*wH0+sD",
    )
    proof = issue_admin_reauth_proof(
        "fresh-admin-token",
        purpose="ENABLE_LIVE_TRADING",
    )
    repository = _ModeRepository(status=_available_status())
    gate = _blocked_gate(bot_active=True)
    service, _ = _service(repository, gate=gate)

    with pytest.raises(TradingModeControlPolicyError) as exc_info:
        asyncio.run(
            service.enable_live(
                EnableLiveTradingModeCommand(
                    request_id=uuid4(),
                    expected_version=1,
                    expected_gate_generation=gate.control.generation,
                    expected_gate_version=gate.control.version,
                    reason_text="런타임 활성 상태의 live 전환을 차단합니다.",
                    confirmation="ENABLE_LIVE_TRADING",
                    reauth_proof=proof.proof,
                )
            )
        )

    assert exc_info.value.error_code == "BOT_ACTIVE"
    assert repository.transition_calls == []


@pytest.mark.parametrize("orphan_kind", ["PREPARING", "ACTIVE_AUTHORIZATION"])
def test_enable_live_rejects_orphan_liquidation_without_gate_pointer(
    monkeypatch,
    orphan_kind: str,
) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "fresh-admin-token")
    monkeypatch.setattr(
        settings,
        "admin_reauth_signing_secret",
        "9M5yG2!qR7#vX4@kL8$pN6^tB3&zC1*wH0+sD",
    )
    proof = issue_admin_reauth_proof(
        "fresh-admin-token",
        purpose="ENABLE_LIVE_TRADING",
    )
    repository = _ModeRepository(status=_available_status())
    gate = _blocked_gate()
    assert gate.control.active_liquidation_operation_id is None
    service, _ = _service(
        repository,
        gate=gate,
        active_liquidation=True,
    )

    with pytest.raises(TradingModeControlPolicyError) as exc_info:
        asyncio.run(
            service.enable_live(
                EnableLiveTradingModeCommand(
                    request_id=uuid4(),
                    expected_version=1,
                    expected_gate_generation=gate.control.generation,
                    expected_gate_version=gate.control.version,
                    reason_text=f"orphan {orphan_kind} 청산 operation을 확인합니다.",
                    confirmation="ENABLE_LIVE_TRADING",
                    reauth_proof=proof.proof,
                )
            )
        )

    assert exc_info.value.error_code == "ACTIVE_LIQUIDATION_EXISTS"
    assert repository.transition_calls == []


def test_new_live_request_rejects_expired_reauth_but_replay_can_continue(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "fresh-admin-token")
    monkeypatch.setattr(
        settings,
        "admin_reauth_signing_secret",
        "9M5yG2!qR7#vX4@kL8$pN6^tB3&zC1*wH0+sD",
    )
    issued_at = datetime.now(UTC) - timedelta(minutes=10)
    proof = issue_admin_reauth_proof(
        "fresh-admin-token",
        purpose="ENABLE_LIVE_TRADING",
        now=issued_at,
    )
    command = EnableLiveTradingModeCommand(
        request_id=uuid4(),
        expected_version=1,
        expected_gate_generation=3,
        expected_gate_version=5,
        reason_text="만료된 재인증 proof는 신규 전환에 사용할 수 없습니다.",
        confirmation="ENABLE_LIVE_TRADING",
        reauth_proof=proof.proof,
    )
    repository = _ModeRepository(status=_available_status())
    service, _ = _service(repository)

    with pytest.raises(AdminReauthError) as exc_info:
        asyncio.run(service.enable_live(command))
    assert getattr(exc_info.value, "error_code", None) == "ADMIN_REAUTH_EXPIRED"

    repository.existing_event = _mode_event(
        request_id=str(command.request_id),
        reauth_jti=proof.jti,
    )
    asyncio.run(service.enable_live(command))
    assert len(repository.transition_calls) == 1


def test_live_reauth_is_rechecked_after_waiting_for_exclusive_barrier(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "fresh-admin-token")
    monkeypatch.setattr(
        settings,
        "admin_reauth_signing_secret",
        "9M5yG2!qR7#vX4@kL8$pN6^tB3&zC1*wH0+sD",
    )
    issued_at = datetime.now(UTC)
    proof = issue_admin_reauth_proof(
        "fresh-admin-token",
        purpose="ENABLE_LIVE_TRADING",
        now=issued_at,
    )
    current_time = [issued_at + timedelta(minutes=4, seconds=59)]

    class _ExpiringBarrier:
        @asynccontextmanager
        async def exclusive(self):
            current_time[0] = issued_at + timedelta(minutes=4, seconds=59, milliseconds=500)
            yield _Lease()

    class _SlowLiveOrderRepository(_LiveOrderRepository):
        async def get_submission_gate_snapshot(self, _db):
            current_time[0] = issued_at + timedelta(minutes=5, seconds=1)
            return self.gate

    repository = _ModeRepository(status=_available_status())
    live_control = _LiveOrderControlService()
    gate = _blocked_gate()
    service = TradingModeControlService(
        _SessionFactory(),
        _ExpiringBarrier(),  # type: ignore[arg-type]
        repository=repository,  # type: ignore[arg-type]
        live_order_repository=_SlowLiveOrderRepository(gate),  # type: ignore[arg-type]
        live_order_control_service=live_control,  # type: ignore[arg-type]
        clock=lambda: current_time[0],
    )

    with pytest.raises(AdminReauthError) as raised:
        asyncio.run(
            service.enable_live(
                EnableLiveTradingModeCommand(
                    request_id=uuid4(),
                    expected_version=1,
                    expected_gate_generation=gate.control.generation,
                    expected_gate_version=gate.control.version,
                    reason_text="배리어 대기 중 만료된 재인증 proof를 차단합니다.",
                    confirmation="ENABLE_LIVE_TRADING",
                    reauth_proof=proof.proof,
                )
            )
        )

    assert raised.value.error_code == "ADMIN_REAUTH_EXPIRED"
    assert repository.transition_calls == []


def test_enable_paper_stops_first_and_does_not_require_reauth() -> None:
    repository = _ModeRepository(status=_available_status(mode=TRADING_MODE_LIVE, version=4))
    service, live_control = _service(repository)

    result = asyncio.run(
        service.enable_paper(
            EnablePaperTradingModeCommand(
                request_id=uuid4(),
                expected_version=4,
                reason_text="운영자 요청으로 런타임과 실주문을 안전하게 정지합니다.",
            )
        )
    )

    assert result.control.mode == "paper"
    assert len(live_control.stop_commands) == 1
    assert live_control.stop_commands[0].request_id.version == 4
    assert repository.transition_calls[0]["reauth_jti"] is None


def test_strict_mode_reader_rejects_mirror_mismatch(monkeypatch) -> None:
    repository = _ModeRepository(
        status=TradingModeStatusRecord(
            mode=TRADING_MODE_PAPER,
            state_available=False,
            control=_mode_control(mode=TRADING_MODE_LIVE),
            mirror_value=TRADING_MODE_PAPER,
            unavailable_reason="TRADING_MODE_MIRROR_MISMATCH",
        )
    )
    monkeypatch.setattr(
        paper_service,
        "TradingModeRepository",
        lambda: repository,
    )

    with pytest.raises(TradingModeStateUnavailableError):
        asyncio.run(paper_service.get_trading_mode(_Session()))


def test_default_mode_normalization_is_paper() -> None:
    assert paper_service.DEFAULT_TRADING_MODE == "paper"
    assert paper_service._normalize_trading_mode(None) == "paper"
    assert paper_service._normalize_trading_mode("typo-live") == "paper"


def test_reauth_signature_uses_independent_server_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "first-admin-token")
    monkeypatch.setattr(
        settings,
        "admin_reauth_signing_secret",
        "9M5yG2!qR7#vX4@kL8$pN6^tB3&zC1*wH0+sD",
    )
    proof = issue_admin_reauth_proof(
        "first-admin-token",
        purpose="ENABLE_LIVE_TRADING",
    )

    monkeypatch.setattr(settings, "admin_api_token", "rotated-admin-token")
    claims = verify_admin_reauth_proof(
        proof.proof,
        expected_purpose="ENABLE_LIVE_TRADING",
    )

    assert claims.jti == proof.jti


def test_reauth_rejects_weak_or_reused_signing_secret(monkeypatch) -> None:
    admin_token = "same-secret-0123456789-ABCDEFGH!@#$"
    monkeypatch.setattr(settings, "admin_api_token", admin_token)
    monkeypatch.setattr(settings, "admin_reauth_signing_secret", admin_token)

    with pytest.raises(AdminReauthError) as exc_info:
        issue_admin_reauth_proof(
            admin_token,
            purpose="ENABLE_LIVE_TRADING",
        )

    assert exc_info.value.error_code == "ADMIN_REAUTH_UNAVAILABLE"
