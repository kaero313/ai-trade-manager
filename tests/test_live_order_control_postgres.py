import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.live_order_control_repository import (
    CONTROL_ACTION_ARMED,
    CONTROL_ACTION_BLOCKED,
    CONTROL_ACTION_LIQUIDATION_AUTHORIZED,
    CONTROL_ACTION_LIQUIDATION_REVOKED,
    CONTROL_SOURCE_REST,
    EMERGENCY_AUTHORIZATION_ACTIVE,
    EMERGENCY_AUTHORIZATION_REVOKED,
    LIVE_ORDER_MODE_ARMED,
    LIVE_ORDER_MODE_BLOCK_ALL,
    LIVE_ORDER_MODE_EXIT_ONLY,
    LiveOrderControlGenerationConflictError,
    LiveOrderControlIdempotencyConflictError,
    LiveOrderControlRepository,
    LiveOrderControlRequestSupersededError,
    LiveOrderControlUnavailableError,
    LiveOrderControlVersionConflictError,
    build_control_request_fingerprint,
)
from app.db.order_intent_repository import OrderIntentRepository
from app.db.repository import LIVE_ORDER_V2_ENABLED_KEY
from app.models.domain import (
    BotConfig,
    LiquidationOperation,
    LiveOrderControl,
    LiveOrderControlEvent,
    OrderIntent,
    SystemConfig,
    TradingModeControl,
    TradingModeControlEvent,
)

TRUNCATE_STATEMENT = text(
    "TRUNCATE TABLE order_history, order_intents, live_order_control_events, "
    "live_order_controls, liquidation_operations, trading_mode_control_events, "
    "trading_mode_controls, bot_configs, system_configs RESTART IDENTITY CASCADE"
)


def _test_database_url() -> str:
    raw_url = str(os.getenv("TEST_DATABASE_URL") or "").strip()
    if not raw_url:
        if os.getenv("CI"):
            pytest.fail("CI PostgreSQL 테스트에는 TEST_DATABASE_URL이 필요합니다.")
        pytest.skip("TEST_DATABASE_URL이 없어 PostgreSQL 통합 테스트를 건너뜁니다.")

    parsed = make_url(raw_url)
    if not parsed.drivername.startswith("postgresql"):
        pytest.fail("TEST_DATABASE_URL은 PostgreSQL 테스트 DB를 가리켜야 합니다.")
    if not (parsed.database or "").endswith("_test"):
        pytest.fail("운영 DB 오접속 방지를 위해 테스트 DB 이름은 _test로 끝나야 합니다.")
    return raw_url


async def _reset_fail_closed_state(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with engine.begin() as connection:
        await connection.execute(TRUNCATE_STATEMENT)

    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all(
            [
                SystemConfig(
                    config_key=LIVE_ORDER_V2_ENABLED_KEY,
                    config_value="true",
                    description="PostgreSQL 실주문 제어 테스트",
                ),
                SystemConfig(
                    config_key="trading_mode",
                    config_value="live",
                    description="PostgreSQL 실주문 제어 테스트 거래 모드 mirror",
                ),
                BotConfig(id=1, config_json={}, is_active=True),
            ]
        )
        control = LiveOrderControl(
            broker="UPBIT",
            account_scope="primary",
            reason_code="MIGRATION_INITIALIZED",
            reason_text="P0-002 migration fail-closed initialization",
            changed_source="SYSTEM",
            changed_actor_ref="alembic:a91f3e7c5b2d",
            blocked_at=now,
        )
        session.add(control)
        trading_mode_control = TradingModeControl(
            id=1,
            mode="live",
            version=2,
            reason_code="TEST_LIVE_ENABLED",
            reason_text="PostgreSQL 실주문 제어 테스트 live 모드",
            changed_source="REST",
            changed_actor_ref="pytest",
            changed_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(trading_mode_control)
        await session.flush()
        session.add_all(
            [
                LiveOrderControlEvent(
                    control_id=control.id,
                    generation=control.generation,
                    request_id=None,
                    request_fingerprint=None,
                    action="INITIALIZED",
                    from_mode=None,
                    to_mode=LIVE_ORDER_MODE_BLOCK_ALL,
                    reason_code=control.reason_code,
                    reason_text=control.reason_text,
                    source="SYSTEM",
                    actor_ref=control.changed_actor_ref,
                    liquidation_operation_id=None,
                    created_at=now,
                ),
                TradingModeControlEvent(
                    control_id=trading_mode_control.id,
                    version=1,
                    request_id=None,
                    request_fingerprint=None,
                    reauth_jti=None,
                    action="INITIALIZED",
                    from_mode=None,
                    to_mode="paper",
                    reason_code="TEST_INITIALIZED",
                    reason_text="PostgreSQL 실주문 제어 테스트 paper 초기화",
                    source="SYSTEM",
                    actor_ref="pytest",
                    legacy_raw_value="paper",
                    created_at=now,
                ),
                TradingModeControlEvent(
                    control_id=trading_mode_control.id,
                    version=2,
                    request_id="11111111-1111-4111-8111-111111111111",
                    request_fingerprint="a" * 64,
                    reauth_jti="22222222-2222-4222-8222-222222222222",
                    action="LIVE_ENABLED",
                    from_mode="paper",
                    to_mode="live",
                    reason_code=trading_mode_control.reason_code,
                    reason_text=trading_mode_control.reason_text,
                    source="REST",
                    actor_ref="pytest",
                    legacy_raw_value=None,
                    created_at=now,
                ),
            ]
        )
        await session.commit()


@pytest_asyncio.fixture
async def pg_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(_test_database_url(), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    await _reset_fail_closed_state(engine, session_factory)
    try:
        yield session_factory
    finally:
        async with engine.begin() as connection:
            await connection.execute(TRUNCATE_STATEMENT)
        await engine.dispose()


def _transition_values(
    *,
    action: str,
    target_mode: str,
    request_id: UUID,
    expected_generation: int | None,
    expected_version: int | None,
    active_liquidation_operation_id: int | None = None,
    event_liquidation_operation_id: int | None = None,
    reason_code: str,
    reason_text: str,
    confirmation: str | None = None,
) -> dict[str, object]:
    fingerprint = build_control_request_fingerprint(
        action=action,
        expected_generation=expected_generation,
        expected_version=expected_version,
        target_mode=target_mode,
        active_liquidation_operation_id=active_liquidation_operation_id,
        event_liquidation_operation_id=event_liquidation_operation_id,
        reason_code=reason_code,
        reason_text=reason_text,
        source=CONTROL_SOURCE_REST,
        actor_ref="admin:test",
        confirmation=confirmation,
    )
    return {
        "expected_generation": expected_generation,
        "expected_version": expected_version,
        "target_mode": target_mode,
        "active_liquidation_operation_id": active_liquidation_operation_id,
        "event_liquidation_operation_id": event_liquidation_operation_id,
        "action": action,
        "request_id": request_id,
        "request_fingerprint": fingerprint,
        "reason_code": reason_code,
        "reason_text": reason_text,
        "source": CONTROL_SOURCE_REST,
        "actor_ref": "admin:test",
    }


def _arm_values(
    request_id: UUID,
    *,
    expected_generation: int | None = 1,
    expected_version: int | None = 1,
    reason_text: str = "운영자가 실주문을 명시적으로 재승인했습니다.",
) -> dict[str, object]:
    return _transition_values(
        action=CONTROL_ACTION_ARMED,
        target_mode=LIVE_ORDER_MODE_ARMED,
        request_id=request_id,
        expected_generation=expected_generation,
        expected_version=expected_version,
        reason_code="OPERATOR_ARMED",
        reason_text=reason_text,
        confirmation="ENABLE_LIVE_ORDERS",
    )


def _block_values(
    request_id: UUID,
    *,
    expected_generation: int | None,
    expected_version: int | None = None,
    reason_code: str = "OPERATOR_BLOCKED",
    reason_text: str = "운영자가 신규 실주문을 즉시 차단했습니다.",
) -> dict[str, object]:
    return _transition_values(
        action=CONTROL_ACTION_BLOCKED,
        target_mode=LIVE_ORDER_MODE_BLOCK_ALL,
        request_id=request_id,
        expected_generation=expected_generation,
        expected_version=expected_version,
        reason_code=reason_code,
        reason_text=reason_text,
    )


async def _create_liquidation_operation(session: AsyncSession) -> LiquidationOperation:
    operation = LiquidationOperation(
        idempotency_key=str(uuid4()),
        status="PREPARING",
        request_fingerprint="e" * 64,
        target_snapshot=[],
    )
    session.add(operation)
    await session.flush()
    return operation


def _prepared_intent(*, generation: int, mode: str, suffix: str) -> OrderIntent:
    return OrderIntent(
        intent_key=suffix * 64,
        identifier=suffix * 32,
        request_fingerprint="f" * 64,
        source_type="TEST",
        source_ref=f"control-audit:{suffix}",
        execution_policy="GENERAL",
        broker="UPBIT",
        account_scope="primary",
        market="KRW-BTC",
        side="bid",
        ord_type="price",
        requested_price=Decimal("5000"),
        requested_volume=None,
        prepared_control_generation=generation,
        prepared_control_mode=mode,
    )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_fail_closed_seed_contract_is_block_all(pg_session_factory) -> None:
    async with pg_session_factory() as session:
        control = (await session.scalars(select(LiveOrderControl))).one()
        event = (await session.scalars(select(LiveOrderControlEvent))).one()

    assert control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert control.active_liquidation_operation_id is None
    assert control.generation == 1
    assert control.version == 1
    assert event.action == "INITIALIZED"
    assert event.to_mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert event.generation == control.generation
    assert event.request_id is None
    assert event.request_fingerprint is None


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_control_broker_account_scope_is_unique(pg_session_factory) -> None:
    async with pg_session_factory() as session:
        session.add(
            LiveOrderControl(
                broker="UPBIT",
                account_scope="primary",
                mode=LIVE_ORDER_MODE_BLOCK_ALL,
                generation=1,
                version=1,
                reason_code="DUPLICATE",
                reason_text="중복 제어 행",
                changed_source="SYSTEM",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "generation", "version", "source"),
    [
        ("INVALID", 1, 1, "SYSTEM"),
        (LIVE_ORDER_MODE_BLOCK_ALL, 0, 1, "SYSTEM"),
        (LIVE_ORDER_MODE_BLOCK_ALL, 1, 0, "SYSTEM"),
        (LIVE_ORDER_MODE_BLOCK_ALL, 1, 1, "UNTRUSTED"),
    ],
)
async def test_control_check_constraints_reject_invalid_values(
    pg_session_factory,
    mode: str,
    generation: int,
    version: int,
    source: str,
) -> None:
    async with pg_session_factory() as session:
        session.add(
            LiveOrderControl(
                broker="UPBIT",
                account_scope=f"invalid-{uuid4()}",
                mode=mode,
                generation=generation,
                version=version,
                reason_code="INVALID_TEST",
                reason_text="제약 위반 테스트",
                changed_source=source,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "attach_operation"),
    [
        (LIVE_ORDER_MODE_EXIT_ONLY, False),
        (LIVE_ORDER_MODE_ARMED, True),
        (LIVE_ORDER_MODE_BLOCK_ALL, True),
    ],
)
async def test_exit_only_requires_exactly_one_active_operation_shape(
    pg_session_factory,
    mode: str,
    attach_operation: bool,
) -> None:
    async with pg_session_factory() as session:
        operation = await _create_liquidation_operation(session)
        session.add(
            LiveOrderControl(
                broker="UPBIT",
                account_scope=f"shape-{uuid4()}",
                mode=mode,
                active_liquidation_operation_id=operation.id if attach_operation else None,
                generation=1,
                version=1,
                reason_code="INVALID_SHAPE",
                reason_text="EXIT_ONLY 제약 위반 테스트",
                changed_source="SYSTEM",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_status", ["ACTIVE", "REVOKED", "CLOSED"])
async def test_liquidation_authorization_coherence_rejects_incomplete_state(
    pg_session_factory,
    invalid_status: str,
) -> None:
    async with pg_session_factory() as session:
        operation = await _create_liquidation_operation(session)
        await session.flush()
        values: dict[str, object] = {"emergency_authorization_status": invalid_status}
        if invalid_status == "REVOKED":
            values.update(
                emergency_revoked_at=None,
                emergency_revocation_reason=None,
            )
        with pytest.raises(IntegrityError):
            await session.execute(
                update(LiquidationOperation)
                .where(LiquidationOperation.id == operation.id)
                .values(**values)
            )
            await session.commit()


@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_case",
    [
        "uuid_version",
        "fingerprint_hex",
        "request_pair",
        "unknown_action",
        "general_action_with_operation",
        "liquidation_action_without_operation",
    ],
)
async def test_event_uuid_fingerprint_and_action_constraints(
    pg_session_factory,
    invalid_case: str,
) -> None:
    async with pg_session_factory() as session:
        control = (await session.scalars(select(LiveOrderControl))).one()
        operation = await _create_liquidation_operation(session)
        values: dict[str, object] = {
            "control_id": control.id,
            "generation": 2,
            "request_id": str(uuid4()),
            "request_fingerprint": "a" * 64,
            "action": CONTROL_ACTION_ARMED,
            "from_mode": LIVE_ORDER_MODE_BLOCK_ALL,
            "to_mode": LIVE_ORDER_MODE_ARMED,
            "reason_code": "INVALID_EVENT",
            "reason_text": "감사 이벤트 제약 위반 테스트",
            "source": CONTROL_SOURCE_REST,
            "actor_ref": "admin:test",
            "liquidation_operation_id": None,
        }
        if invalid_case == "uuid_version":
            values["request_id"] = "11111111-1111-1111-8111-111111111111"
        elif invalid_case == "fingerprint_hex":
            values["request_fingerprint"] = "A" * 64
        elif invalid_case == "request_pair":
            values["request_fingerprint"] = None
        elif invalid_case == "unknown_action":
            values["action"] = "UNKNOWN"
        elif invalid_case == "general_action_with_operation":
            values["liquidation_operation_id"] = operation.id
        elif invalid_case == "liquidation_action_without_operation":
            values["action"] = CONTROL_ACTION_LIQUIDATION_AUTHORIZED
            values["to_mode"] = LIVE_ORDER_MODE_EXIT_ONLY

        session.add(LiveOrderControlEvent(**values))  # type: ignore[arg-type]
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_missing_control_fails_closed(pg_session_factory) -> None:
    async with pg_session_factory() as session:
        await session.execute(
            text("TRUNCATE TABLE live_order_control_events, live_order_controls CASCADE")
        )
        await session.commit()

    repository = LiveOrderControlRepository()
    async with pg_session_factory() as session:
        assert await repository.get_preparation_snapshot(session) is None
        gate = await repository.get_submission_gate_snapshot(session)
        assert gate.control is None
        assert not gate.general_submission_allowed
        assert not gate.emergency_submission_allowed(1)
        with pytest.raises(LiveOrderControlUnavailableError):
            await repository.transition_control(
                session,
                now=datetime.now(UTC),
                **_block_values(uuid4(), expected_generation=None),
            )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_submission_gate_combines_flag_bot_and_control(pg_session_factory) -> None:
    repository = LiveOrderControlRepository()
    arm_request_id = uuid4()

    async with pg_session_factory() as session:
        initial = await repository.get_submission_gate_snapshot(session)
        assert initial.rollout_enabled
        assert initial.bot_active
        assert initial.control is not None
        assert initial.control.mode == LIVE_ORDER_MODE_BLOCK_ALL
        assert not initial.general_submission_allowed

        arm_transition = await repository.transition_control(
            session,
            now=datetime.now(UTC),
            **_arm_values(arm_request_id),
        )
        await session.commit()

    async with pg_session_factory() as session:
        armed = await repository.get_submission_gate_snapshot(session)
        assert armed.general_submission_allowed
        assert armed.general_authorization_event_id == arm_transition.event.id

        bot = await session.get(BotConfig, 1)
        assert bot is not None
        bot.is_active = False
        await session.commit()

    async with pg_session_factory() as session:
        assert not (
            await repository.get_submission_gate_snapshot(session)
        ).general_submission_allowed
        bot = await session.get(BotConfig, 1)
        assert bot is not None
        bot.is_active = True
        await repository.disable_rollout_flag(session)
        await session.commit()

    async with pg_session_factory() as session:
        disabled = await repository.get_submission_gate_snapshot(session)
        assert not disabled.rollout_enabled
        assert not disabled.general_submission_allowed


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_submission_gate_allows_only_the_bound_exit_operation(
    pg_session_factory,
) -> None:
    repository = LiveOrderControlRepository()
    async with pg_session_factory() as session:
        operation = await _create_liquidation_operation(session)
        operation_id = operation.id
        authorized = await repository.transition_control(
            session,
            now=datetime.now(UTC),
            **_transition_values(
                action=CONTROL_ACTION_LIQUIDATION_AUTHORIZED,
                target_mode=LIVE_ORDER_MODE_EXIT_ONLY,
                request_id=UUID(operation.idempotency_key),
                expected_generation=1,
                expected_version=1,
                active_liquidation_operation_id=operation_id,
                event_liquidation_operation_id=operation_id,
                reason_code="LIQUIDATION_AUTHORIZED",
                reason_text="관리자가 전량청산을 명시적으로 승인했습니다.",
                confirmation="CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL",
            ),
        )
        operation.emergency_authorization_status = EMERGENCY_AUTHORIZATION_ACTIVE
        operation.emergency_authorized_at = datetime.now(UTC)
        operation.emergency_control_generation = authorized.control.generation
        operation.emergency_control_event_id = authorized.event.id
        operation.emergency_authorized_source = CONTROL_SOURCE_REST
        operation.emergency_revoked_at = None
        operation.emergency_revocation_reason = None
        operation.emergency_closed_at = None
        bot = await session.get(BotConfig, 1)
        assert bot is not None
        bot.is_active = False
        await session.commit()

    async with pg_session_factory() as session:
        gate = await repository.get_submission_gate_snapshot(session)

    assert gate.rollout_enabled
    assert not gate.bot_active
    assert gate.control is not None
    assert gate.control.mode == LIVE_ORDER_MODE_EXIT_ONLY
    assert not gate.general_submission_allowed
    assert gate.emergency_submission_allowed(operation_id)
    assert not gate.emergency_submission_allowed(operation_id + 1)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_general_block_cannot_silently_clear_active_liquidation(
    pg_session_factory,
) -> None:
    repository = LiveOrderControlRepository()
    async with pg_session_factory() as session:
        operation = await _create_liquidation_operation(session)
        operation_id = operation.id
        await repository.transition_control(
            session,
            now=datetime.now(UTC),
            **_transition_values(
                action=CONTROL_ACTION_LIQUIDATION_AUTHORIZED,
                target_mode=LIVE_ORDER_MODE_EXIT_ONLY,
                request_id=uuid4(),
                expected_generation=1,
                expected_version=1,
                active_liquidation_operation_id=operation_id,
                event_liquidation_operation_id=operation_id,
                reason_code="LIQUIDATION_AUTHORIZED",
                reason_text="관리자가 전량청산을 명시적으로 승인했습니다.",
            ),
        )
        await session.commit()

    async with pg_session_factory() as session:
        with pytest.raises(LiveOrderControlUnavailableError, match="폐기·종결"):
            await repository.transition_control(
                session,
                now=datetime.now(UTC),
                **_block_values(uuid4(), expected_generation=None),
            )
        await session.rollback()
        control = await repository.get_control(session)

    assert control is not None
    assert control.mode == LIVE_ORDER_MODE_EXIT_ONLY
    assert control.active_liquidation_operation_id == operation_id


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_intent_claim_persists_matching_control_authorization(
    pg_session_factory,
) -> None:
    control_repository = LiveOrderControlRepository()
    intent_repository = OrderIntentRepository()
    async with pg_session_factory() as session:
        armed = await control_repository.transition_control(
            session,
            now=datetime.now(UTC),
            **_arm_values(uuid4()),
        )
        intent = _prepared_intent(
            generation=armed.control.generation,
            mode=armed.control.mode,
            suffix="a",
        )
        session.add(intent)
        await session.commit()
        intent_id = intent.id

    async with pg_session_factory() as session:
        claimed = await intent_repository.claim_submission(
            session,
            intent_id,
            expected_version=0,
            now=datetime.now(UTC),
            control_generation=armed.control.generation,
            control_mode=armed.control.mode,
            control_event_id=armed.event.id,
        )
        await session.commit()

    assert claimed is not None
    assert claimed.submission_status == "SUBMITTING"
    assert claimed.post_attempt_count == 1
    assert claimed.control_generation == armed.control.generation
    assert claimed.control_mode == LIVE_ORDER_MODE_ARMED
    assert claimed.control_event_id == armed.event.id
    assert claimed.submission_authorized_at is not None


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_stale_prepared_intent_is_not_claimed_and_can_be_abandoned(
    pg_session_factory,
) -> None:
    control_repository = LiveOrderControlRepository()
    intent_repository = OrderIntentRepository()
    async with pg_session_factory() as session:
        intent = _prepared_intent(
            generation=1,
            mode=LIVE_ORDER_MODE_BLOCK_ALL,
            suffix="b",
        )
        session.add(intent)
        await session.flush()
        intent_id = intent.id
        armed = await control_repository.transition_control(
            session,
            now=datetime.now(UTC),
            **_arm_values(uuid4()),
        )
        await session.commit()

    async with pg_session_factory() as session:
        claimed = await intent_repository.claim_submission(
            session,
            intent_id,
            expected_version=0,
            now=datetime.now(UTC),
            control_generation=armed.control.generation,
            control_mode=armed.control.mode,
            control_event_id=armed.event.id,
        )
        assert claimed is None
        abandoned = await intent_repository.abandon_prepared(
            session,
            intent_id,
            expected_version=0,
            error_code="LIVE_ORDER_GATE_BLOCKED",
            error_message="준비 시점 이후 실주문 제어 generation이 변경되었습니다.",
            now=datetime.now(UTC),
        )
        await session.commit()

    assert abandoned is None
    async with pg_session_factory() as session:
        stale = await intent_repository.get_intent(session, intent_id)
    assert stale is not None
    assert stale.submission_status == "ABANDONED"
    assert stale.projection_status == "SKIPPED"
    assert stale.post_attempt_count == 0
    assert stale.last_error_code == "ORDER_GATE_GENERATION_CONFLICT"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_generation_and_version_cas_reject_stale_transitions(pg_session_factory) -> None:
    repository = LiveOrderControlRepository()
    async with pg_session_factory() as session:
        armed = await repository.transition_control(
            session,
            now=datetime.now(UTC),
            **_arm_values(uuid4()),
        )
        await session.commit()

    assert armed.control.generation == 2
    assert armed.control.version == 2

    async with pg_session_factory() as session:
        with pytest.raises(LiveOrderControlGenerationConflictError) as generation_error:
            await repository.transition_control(
                session,
                now=datetime.now(UTC),
                **_block_values(uuid4(), expected_generation=1, expected_version=2),
            )
        assert generation_error.value.actual_generation == 2

    async with pg_session_factory() as session:
        with pytest.raises(LiveOrderControlVersionConflictError) as version_error:
            await repository.transition_control(
                session,
                now=datetime.now(UTC),
                **_block_values(uuid4(), expected_generation=2, expected_version=1),
            )
        assert version_error.value.actual_version == 2


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_noop_block_version_change_rejects_waiting_stale_arm(
    pg_session_factory,
) -> None:
    repository = LiveOrderControlRepository()
    stale_arm = _arm_values(uuid4(), expected_generation=1, expected_version=1)

    async with pg_session_factory() as session:
        no_op_block = await repository.transition_control(
            session,
            now=datetime.now(UTC),
            **_block_values(uuid4(), expected_generation=None),
        )
        await session.commit()

    assert no_op_block.control.generation == 1
    assert no_op_block.control.version == 2

    async with pg_session_factory() as session:
        with pytest.raises(LiveOrderControlVersionConflictError):
            await repository.transition_control(
                session,
                now=datetime.now(UTC),
                **stale_arm,
            )
        await session.rollback()
        control = await repository.get_control(session)

    assert control is not None
    assert control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert control.generation == 1
    assert control.version == 2


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_expected_generation_none_is_restricted_to_block_all(pg_session_factory) -> None:
    repository = LiveOrderControlRepository()
    async with pg_session_factory() as session:
        with pytest.raises(ValueError, match="BLOCK_ALL"):
            await repository.transition_control(
                session,
                now=datetime.now(UTC),
                **_arm_values(uuid4(), expected_generation=None, expected_version=None),
            )

        await repository.transition_control(
            session,
            now=datetime.now(UTC),
            **_arm_values(uuid4()),
        )
        await session.commit()

    async with pg_session_factory() as session:
        blocked = await repository.transition_control(
            session,
            now=datetime.now(UTC),
            **_block_values(uuid4(), expected_generation=None),
        )
        await session.commit()

    assert blocked.control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert blocked.control.generation == 3
    assert blocked.control.version == 3


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_same_request_replays_single_event(pg_session_factory) -> None:
    repository = LiveOrderControlRepository()
    request_id = uuid4()
    values = _arm_values(request_id)

    async with pg_session_factory() as session:
        first = await repository.transition_control(session, now=datetime.now(UTC), **values)
        await session.commit()

    async with pg_session_factory() as session:
        replay = await repository.transition_control(session, now=datetime.now(UTC), **values)
        await session.commit()
        event_count = await session.scalar(
            select(func.count(LiveOrderControlEvent.id)).where(
                LiveOrderControlEvent.request_id == str(request_id)
            )
        )

    assert not first.replayed
    assert replay.replayed
    assert replay.event.id == first.event.id
    assert replay.control.generation == first.control.generation == 2
    assert event_count == 1


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_same_request_with_different_fingerprint_is_conflict(pg_session_factory) -> None:
    repository = LiveOrderControlRepository()
    request_id = uuid4()
    async with pg_session_factory() as session:
        await repository.transition_control(
            session,
            now=datetime.now(UTC),
            **_arm_values(request_id),
        )
        await session.commit()

    async with pg_session_factory() as session:
        with pytest.raises(LiveOrderControlIdempotencyConflictError):
            await repository.transition_control(
                session,
                now=datetime.now(UTC),
                **_arm_values(request_id, reason_text="같은 키에 다른 승인 사유를 사용했습니다."),
            )


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_superseded_old_arm_request_does_not_reopen_gate(pg_session_factory) -> None:
    repository = LiveOrderControlRepository()
    arm_request_id = uuid4()
    arm_values = _arm_values(arm_request_id)

    async with pg_session_factory() as session:
        await repository.transition_control(session, now=datetime.now(UTC), **arm_values)
        await session.commit()

    async with pg_session_factory() as session:
        await repository.transition_control(
            session,
            now=datetime.now(UTC),
            **_block_values(uuid4(), expected_generation=2, expected_version=2),
        )
        await session.commit()

    async with pg_session_factory() as session:
        with pytest.raises(LiveOrderControlRequestSupersededError):
            await repository.transition_control(session, now=datetime.now(UTC), **arm_values)
        control = await repository.get_control(session)

    assert control is not None
    assert control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert control.generation == 3


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_eight_sessions_produce_one_transition_winner_and_event(
    pg_session_factory,
) -> None:
    repository = LiveOrderControlRepository()
    request_id = uuid4()
    values = _arm_values(request_id)

    async def transition_once():
        async with pg_session_factory() as session:
            result = await repository.transition_control(
                session,
                now=datetime.now(UTC),
                **values,
            )
            await session.commit()
            return result

    results = await asyncio.gather(*(transition_once() for _ in range(8)))

    assert sum(not result.replayed for result in results) == 1
    assert sum(result.replayed for result in results) == 7
    assert {result.event.id for result in results} == {results[0].event.id}
    assert {result.control.generation for result in results} == {2}

    async with pg_session_factory() as session:
        event_count = await session.scalar(
            select(func.count(LiveOrderControlEvent.id)).where(
                LiveOrderControlEvent.request_id == str(request_id)
            )
        )
        control = await repository.get_control(session)

    assert event_count == 1
    assert control is not None
    assert control.mode == LIVE_ORDER_MODE_ARMED
    assert control.version == 2


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_historical_liquidation_authorization_replay_after_revoke_is_superseded(
    pg_session_factory,
) -> None:
    repository = LiveOrderControlRepository()
    authorization_request_id = uuid4()
    revocation_request_id = uuid4()

    async with pg_session_factory() as session:
        operation = await _create_liquidation_operation(session)
        operation_id = operation.id
        await session.commit()

    authorization_values = _transition_values(
        action=CONTROL_ACTION_LIQUIDATION_AUTHORIZED,
        target_mode=LIVE_ORDER_MODE_EXIT_ONLY,
        request_id=authorization_request_id,
        expected_generation=1,
        expected_version=1,
        active_liquidation_operation_id=operation_id,
        event_liquidation_operation_id=operation_id,
        reason_code="LIQUIDATION_AUTHORIZED",
        reason_text="관리자가 전량청산을 명시적으로 승인했습니다.",
        confirmation="CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL",
    )
    async with pg_session_factory() as session:
        authorized = await repository.transition_control(
            session,
            now=datetime.now(UTC),
            **authorization_values,
        )
        operation = await session.get(LiquidationOperation, operation_id)
        assert operation is not None
        operation.emergency_authorization_status = EMERGENCY_AUTHORIZATION_ACTIVE
        operation.emergency_authorized_at = datetime.now(UTC)
        operation.emergency_control_generation = authorized.control.generation
        operation.emergency_control_event_id = authorized.event.id
        operation.emergency_authorized_source = CONTROL_SOURCE_REST
        operation.emergency_revoked_at = None
        operation.emergency_revocation_reason = None
        operation.emergency_closed_at = None
        await session.commit()

    revocation_values = _transition_values(
        action=CONTROL_ACTION_LIQUIDATION_REVOKED,
        target_mode=LIVE_ORDER_MODE_BLOCK_ALL,
        request_id=revocation_request_id,
        expected_generation=2,
        expected_version=2,
        active_liquidation_operation_id=None,
        event_liquidation_operation_id=operation_id,
        reason_code="LIQUIDATION_REVOKED",
        reason_text="운영자가 청산 권한을 폐기하고 실주문을 차단했습니다.",
    )
    async with pg_session_factory() as session:
        revoked = await repository.transition_control(
            session,
            now=datetime.now(UTC),
            **revocation_values,
        )
        operation = await session.get(LiquidationOperation, operation_id)
        assert operation is not None
        operation.emergency_authorization_status = EMERGENCY_AUTHORIZATION_REVOKED
        operation.emergency_revoked_at = datetime.now(UTC)
        operation.emergency_revocation_reason = "OPERATOR_STOP"
        operation.emergency_closed_at = None
        await session.commit()

    async with pg_session_factory() as session:
        with pytest.raises(LiveOrderControlRequestSupersededError):
            await repository.transition_control(
                session,
                now=datetime.now(UTC),
                **authorization_values,
            )
        control = await repository.get_control(session)
        operation = await session.get(LiquidationOperation, operation_id)
        authorization_event_count = await session.scalar(
            select(func.count(LiveOrderControlEvent.id)).where(
                LiveOrderControlEvent.request_id == str(authorization_request_id)
            )
        )

    assert revoked.control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert revoked.control.active_liquidation_operation_id is None
    assert revoked.control.generation == 3
    assert control is not None
    assert control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert operation is not None
    assert operation.emergency_authorization_status == EMERGENCY_AUTHORIZATION_REVOKED
    assert operation.emergency_revocation_reason == "OPERATOR_STOP"
    assert authorization_event_count == 1
