import asyncio
import os
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, null, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.live_order_control_repository import (
    CONTROL_ACTION_ARMED,
    CONTROL_SOURCE_REST,
    LIVE_ORDER_MODE_ARMED,
    LIVE_ORDER_MODE_BLOCK_ALL,
    LiveOrderControlRepository,
    build_control_request_fingerprint,
)
from app.db.liquidation_repository import LiquidationRepository
from app.db.order_intent_repository import OrderIntentRepository
from app.db.repository import LIVE_ORDER_V2_ENABLED_KEY
from app.models.domain import (
    Asset,
    BotConfig,
    LiquidationOperation,
    LiquidationOrderCancellation,
    LiveOrderControl,
    LiveOrderControlEvent,
    OrderHistory,
    OrderIntent,
    Position,
    SystemConfig,
    TradingModeControl,
    TradingModeControlEvent,
)
from app.services.trading.liquidation import LiquidationCoordinator
from app.services.trading.liquidation_v2 import (
    LiquidationLeaseLostError,
    build_liquidation_request_fingerprint,
)
from app.services.trading.live_order_execution import (
    LiveOrderExecutionService,
    LiveOrderRequest,
)
from app.services.trading.live_order_control import (
    BlockLiveOrdersCommand,
    LiveOrderControlDrainPendingError,
    LiveOrderControlPolicyError,
    LiveOrderControlService,
)
from app.services.trading.live_order_submission_barrier import LiveOrderSubmissionBarrier
from app.services.trading.trading_mode_control import (
    EnablePaperTradingModeCommand,
    TradingModeControlService,
)

REQUESTED_PRICE = Decimal("5000.123456789012345678")
POSTGRES_TASK_TIMEOUT_SECONDS = 30


def _test_database_url() -> str:
    url = str(os.getenv("TEST_DATABASE_URL") or "").strip()
    if not url:
        if os.getenv("CI"):
            pytest.fail("CI PostgreSQL 테스트에는 TEST_DATABASE_URL이 필요합니다.")
        pytest.skip("TEST_DATABASE_URL이 없어 PostgreSQL 통합 테스트를 건너뜁니다.")

    database_name = url.rsplit("/", maxsplit=1)[-1].split("?", maxsplit=1)[0]
    if not database_name.endswith("_test"):
        pytest.fail("운영 DB 오접속 방지를 위해 테스트 DB 이름은 _test로 끝나야 합니다.")
    return url


@pytest_asyncio.fixture
async def pg_engine() -> AsyncEngine:
    engine = create_async_engine(_test_database_url(), pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def pg_session_factory(
    pg_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    truncate_statement = text(
        "TRUNCATE TABLE order_history, order_intents, live_order_control_events, "
        "live_order_controls, liquidation_operations, positions, assets, "
        "trading_mode_control_events, trading_mode_controls, bot_configs, "
        "system_configs RESTART IDENTITY CASCADE"
    )
    async with pg_engine.begin() as connection:
        await connection.execute(truncate_statement)
    async with session_factory() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                SystemConfig(
                    config_key=LIVE_ORDER_V2_ENABLED_KEY,
                    config_value="true",
                    description="PostgreSQL 통합 테스트용 실주문 게이트",
                ),
                SystemConfig(
                    config_key="trading_mode",
                    config_value="live",
                    description="PostgreSQL 통합 테스트용 거래 모드 mirror",
                ),
                BotConfig(id=1, config_json={}, is_active=True),
            ]
        )
        control = LiveOrderControl(
            broker="UPBIT",
            account_scope="primary",
            reason_code="TEST_INITIALIZED",
            reason_text="PostgreSQL 통합 테스트 fail-closed 초기화",
            changed_source="SYSTEM",
            changed_actor_ref="pytest",
            blocked_at=now,
        )
        session.add(control)
        trading_mode_control = TradingModeControl(
            id=1,
            mode="live",
            version=2,
            reason_code="TEST_LIVE_ENABLED",
            reason_text="PostgreSQL 주문 의도 테스트 live 모드",
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
                    actor_ref="pytest",
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
                    reason_text="PostgreSQL 주문 의도 테스트 paper 초기화",
                    source="SYSTEM",
                    actor_ref="pytest",
                    legacy_raw_value="paper",
                    created_at=now,
                ),
                TradingModeControlEvent(
                    control_id=trading_mode_control.id,
                    version=2,
                    request_id="33333333-3333-4333-8333-333333333333",
                    request_fingerprint="b" * 64,
                    reauth_jti="44444444-4444-4444-8444-444444444444",
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
        request_id = uuid4()
        reason_code = "TEST_ARMED"
        reason_text = "PostgreSQL 통합 테스트 일반 주문 승인"
        fingerprint = build_control_request_fingerprint(
            action=CONTROL_ACTION_ARMED,
            expected_generation=1,
            expected_version=1,
            target_mode=LIVE_ORDER_MODE_ARMED,
            active_liquidation_operation_id=None,
            reason_code=reason_code,
            reason_text=reason_text,
            source=CONTROL_SOURCE_REST,
            actor_ref="pytest",
            confirmation="ENABLE_LIVE_ORDERS",
        )
        await LiveOrderControlRepository().transition_control(
            session,
            expected_generation=1,
            expected_version=1,
            target_mode=LIVE_ORDER_MODE_ARMED,
            active_liquidation_operation_id=None,
            action=CONTROL_ACTION_ARMED,
            request_id=request_id,
            request_fingerprint=fingerprint,
            reason_code=reason_code,
            reason_text=reason_text,
            source=CONTROL_SOURCE_REST,
            actor_ref="pytest",
            now=now,
        )
        await session.commit()
    try:
        yield session_factory
    finally:
        async with pg_engine.begin() as connection:
            await connection.execute(truncate_statement)


def _intent(
    *,
    intent_key: str,
    identifier: str,
    market: str,
    side: str,
) -> OrderIntent:
    is_bid = side == "bid"
    return OrderIntent(
        intent_key=intent_key,
        identifier=identifier,
        request_fingerprint="f" * 64,
        source_type="TEST",
        source_ref=intent_key,
        execution_policy="GENERAL",
        broker="UPBIT",
        account_scope="primary",
        market=market,
        side=side,
        ord_type="price" if is_bid else "market",
        requested_price=Decimal("5000") if is_bid else None,
        requested_volume=None if is_bid else Decimal("0.01"),
    )


class _CountingFakeBroker:
    """실제 네트워크 없이 POST 호출 횟수를 직렬화해 기록한다."""

    def __init__(self) -> None:
        self.post_count = 0
        self.account_count = 0
        self._counter_lock = asyncio.Lock()
        self._order_created = asyncio.Event()
        self.post_started = asyncio.Event()
        self.allow_post_return = asyncio.Event()
        self.allow_post_return.set()
        self._orders: dict[str, dict[str, str | None]] = {}

    async def get_accounts(self) -> list[dict[str, str]]:
        self.account_count += 1
        await asyncio.sleep(0)
        return [{"currency": "BTC", "balance": "0.1", "locked": "0"}]

    async def create_order(
        self,
        market: str,
        side: str,
        ord_type: str,
        volume: str | None = None,
        price: str | None = None,
        identifier: str | None = None,
    ) -> dict[str, str | None]:
        assert identifier is not None
        payload = {
            "uuid": f"exchange-{identifier}",
            "identifier": identifier,
            "market": market,
            "side": side,
            "ord_type": ord_type,
            "price": price,
            "volume": volume,
            "state": "wait",
            "executed_volume": "0",
            "remaining_volume": volume,
            "paid_fee": "0",
        }
        async with self._counter_lock:
            self.post_count += 1
            self._orders[identifier] = payload
            self._order_created.set()
            self.post_started.set()

        await self.allow_post_return.wait()
        # 다른 실행자가 PREPARED -> SUBMITTING CAS를 경쟁할 시간을 확보한다.
        await asyncio.sleep(0.05)
        return payload

    async def get_order(
        self,
        uuid_: str | None = None,
        identifier: str | None = None,
    ) -> dict[str, str | None]:
        del uuid_
        assert identifier is not None
        await asyncio.wait_for(
            self._order_created.wait(),
            timeout=POSTGRES_TASK_TIMEOUT_SECONDS,
        )
        async with self._counter_lock:
            return dict(self._orders[identifier])


class _LiquidationV2FakeBroker(_CountingFakeBroker):
    def __init__(self) -> None:
        super().__init__()
        self.cancel_count = 0
        self._balance = Decimal("0.1")

    async def get_accounts(self) -> list[dict[str, str]]:
        self.account_count += 1
        return [
            {"currency": "KRW", "balance": "10000", "locked": "0"},
            {"currency": "BTC", "balance": format(self._balance, "f"), "locked": "0"},
        ]

    async def get_orders_open(self, **_kwargs):
        return []

    async def cancel_orders_by_ids(self, uuids: list[str]):
        self.cancel_count += 1
        return [{"uuid": uuid_, "state": "cancel"} for uuid_ in uuids]

    async def get_all_markets(self):
        return [{"market": "KRW-BTC"}]

    async def get_ticker(self, markets: list[str]):
        return [{"market": market, "trade_price": "100000000"} for market in markets]

    async def create_order(
        self,
        market: str,
        side: str,
        ord_type: str,
        volume: str | None = None,
        price: str | None = None,
        identifier: str | None = None,
    ) -> dict[str, object]:
        assert identifier is not None
        assert volume is not None
        self.post_count += 1
        self._balance = Decimal("0")
        payload: dict[str, object] = {
            "uuid": f"exchange-{identifier}",
            "identifier": identifier,
            "market": market,
            "side": side,
            "ord_type": ord_type,
            "price": price,
            "volume": volume,
            "state": "done",
            "executed_volume": volume,
            "remaining_volume": "0",
            "paid_fee": "0",
            "trades": [
                {
                    "price": "100000000",
                    "volume": volume,
                    "funds": str(Decimal(volume) * Decimal("100000000")),
                }
            ],
        }
        self._orders[identifier] = payload  # type: ignore[assignment]
        return payload

    async def get_order(self, uuid_: str | None = None, identifier: str | None = None):
        if identifier is not None:
            return dict(self._orders[identifier])
        for payload in self._orders.values():
            if payload.get("uuid") == uuid_:
                return dict(payload)
        raise AssertionError(f"unknown order: {uuid_}")


class _LiquidationV2CancelFakeBroker(_LiquidationV2FakeBroker):
    def __init__(self) -> None:
        super().__init__()
        self.manual_open = True
        self.call_order: list[str] = []

    async def get_orders_open(self, **_kwargs):
        if not self.manual_open:
            return []
        return [
            {
                "uuid": "manual-open-uuid",
                "identifier": None,
                "market": "KRW-BTC",
                "side": "ask",
                "state": "wait",
            }
        ]

    async def cancel_orders_by_ids(self, uuids: list[str]):
        assert uuids == ["manual-open-uuid"]
        self.call_order.append("cancel")
        self.cancel_count += 1
        self.manual_open = False
        return [{"uuid": "manual-open-uuid", "state": "cancel"}]

    async def create_order(self, *args, **kwargs):
        self.call_order.append("post")
        return await super().create_order(*args, **kwargs)

    async def get_order(self, uuid_: str | None = None, identifier: str | None = None):
        if uuid_ == "manual-open-uuid":
            return {
                "uuid": uuid_,
                "identifier": None,
                "market": "KRW-BTC",
                "side": "ask",
                "ord_type": "limit",
                "state": "cancel" if not self.manual_open else "wait",
                "price": "100000000",
                "volume": "0.1",
                "executed_volume": "0",
                "remaining_volume": "0.1",
                "paid_fee": "0",
            }
        return await super().get_order(uuid_=uuid_, identifier=identifier)


async def _start_liquidation_v2(
    coordinator: LiquidationCoordinator,
    idempotency_key: str,
):
    return await coordinator.execute(
        idempotency_key,
        scope="ACCOUNT_ALL",
        request_fingerprint=build_liquidation_request_fingerprint("ACCOUNT_ALL"),
    )


class _BlockingPreparationRepository(OrderIntentRepository):
    def __init__(self) -> None:
        self.prepared_written = asyncio.Event()
        self.allow_prepare_commit = asyncio.Event()

    async def create_or_get_intent(self, db, draft):
        result = await super().create_or_get_intent(db, draft)
        self.prepared_written.set()
        await self.allow_prepare_commit.wait()
        return result


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_blocking_bid_prevents_another_market_buy(pg_session_factory) -> None:
    async with pg_session_factory() as first_session:
        first_session.add(
            _intent(
                intent_key="a" * 64,
                identifier="1" * 32,
                market="KRW-BTC",
                side="bid",
            )
        )
        await first_session.commit()

    async with pg_session_factory() as second_session:
        second_session.add(
            _intent(
                intent_key="b" * 64,
                identifier="2" * 32,
                market="KRW-ETH",
                side="bid",
            )
        )
        with pytest.raises(IntegrityError):
            await second_session.commit()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_blocking_sell_allows_another_market_sell(pg_session_factory) -> None:
    async with pg_session_factory() as first_session:
        first_session.add(
            _intent(
                intent_key="c" * 64,
                identifier="3" * 32,
                market="KRW-BTC",
                side="ask",
            )
        )
        await first_session.commit()

    async with pg_session_factory() as second_session:
        second_session.add(
            _intent(
                intent_key="d" * 64,
                identifier="4" * 32,
                market="KRW-ETH",
                side="ask",
            )
        )
        await second_session.commit()

    async with pg_session_factory() as verification_session:
        count = await verification_session.scalar(text("SELECT count(*) FROM order_intents"))
        assert count == 2


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_blocking_sell_prevents_same_market_order(pg_session_factory) -> None:
    async with pg_session_factory() as first_session:
        first_session.add(
            _intent(
                intent_key="g" * 64,
                identifier="6" * 32,
                market="KRW-BTC",
                side="ask",
            )
        )
        await first_session.commit()

    async with pg_session_factory() as second_session:
        second_session.add(
            _intent(
                intent_key="h" * 64,
                identifier="7" * 32,
                market="KRW-BTC",
                side="ask",
            )
        )
        with pytest.raises(IntegrityError):
            await second_session.commit()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_same_request_from_eight_sessions_posts_once(
    pg_session_factory,
    pg_engine,
) -> None:
    broker = _CountingFakeBroker()
    request = LiveOrderRequest(
        source_type="AI",
        source_ref="analysis:postgres-concurrency:KRW-BTC:bid",
        market="KRW-BTC",
        side="bid",
        ord_type="price",
        price=REQUESTED_PRICE,
        reason="동시 실행 멱등성 검증",
    )
    services = [
        LiveOrderExecutionService(
            pg_session_factory,
            broker,
            LiveOrderSubmissionBarrier(pg_engine),
        )
        for _ in range(8)
    ]

    results = await asyncio.gather(*(service.execute(request) for service in services))

    assert broker.post_count == 1
    assert {result.intent_id for result in results} == {results[0].intent_id}
    assert results[0].intent_id is not None

    async with pg_session_factory() as verification_session:
        intents = list((await verification_session.scalars(select(OrderIntent))).all())

    assert len(intents) == 1
    intent = intents[0]
    assert intent.id == results[0].intent_id
    assert intent.post_attempt_count == 1
    assert intent.requested_price == REQUESTED_PRICE
    assert intent.requested_volume is None
    assert intent.submission_status == "ACCEPTED"
    assert intent.exchange_state == "wait"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_stop_cannot_miss_prepared_insert_or_return_before_submission_barrier(
    pg_session_factory,
    pg_engine,
) -> None:
    broker = _CountingFakeBroker()
    barrier = LiveOrderSubmissionBarrier(pg_engine)
    preparation_repository = _BlockingPreparationRepository()
    order_service = LiveOrderExecutionService(
        pg_session_factory,
        broker,
        barrier,
    )
    order_service._repository = preparation_repository
    control_service = LiveOrderControlService(barrier=barrier)
    request = LiveOrderRequest(
        source_type="AI",
        source_ref="analysis:prepare-stop-race:KRW-BTC:bid",
        market="KRW-BTC",
        side="bid",
        ord_type="price",
        price=REQUESTED_PRICE,
    )

    order_task = asyncio.create_task(order_service.execute(request))
    await asyncio.wait_for(
        preparation_repository.prepared_written.wait(),
        timeout=POSTGRES_TASK_TIMEOUT_SECONDS,
    )
    stop_task = asyncio.create_task(
        control_service.stop_bot(
            BlockLiveOrdersCommand(
                request_id=uuid4(),
                reason_code="TEST_STOP",
                reason_text="PostgreSQL 준비 주문과 정지 경합을 검증하는 운영 정지입니다.",
                source="REST",
                actor_ref="pytest",
            )
        )
    )
    await asyncio.sleep(0.1)
    assert stop_task.done() is False

    preparation_repository.allow_prepare_commit.set()
    order_result = await asyncio.wait_for(
        order_task,
        timeout=POSTGRES_TASK_TIMEOUT_SECONDS,
    )
    try:
        stop_result = await asyncio.wait_for(
            stop_task,
            timeout=POSTGRES_TASK_TIMEOUT_SECONDS,
        )
    except LiveOrderControlDrainPendingError:
        stop_result = await control_service.stop_bot(
            BlockLiveOrdersCommand(
                request_id=uuid4(),
                reason_code="TEST_STOP_RETRY",
                reason_text="SUBMITTING 해소를 확인한 뒤 운영 정지를 다시 확인합니다.",
                source="REST",
                actor_ref="pytest",
            )
        )

    assert stop_result.control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert order_result.submission_status in {"ABANDONED", "ACCEPTED"}
    assert broker.post_count <= 1

    blocked_result = await order_service.execute(
        LiveOrderRequest(
            source_type="AI",
            source_ref="analysis:after-stop:KRW-ETH:bid",
            market="KRW-ETH",
            side="bid",
            ord_type="price",
            price=REQUESTED_PRICE,
        )
    )
    assert blocked_result.error_code in {"BOT_INACTIVE", "LIVE_ORDER_GATE_BLOCKED"}
    assert broker.post_count <= 1

    async with pg_session_factory() as session:
        prepared_count = await session.scalar(
            select(func.count(OrderIntent.id)).where(
                OrderIntent.submission_status == "PREPARED"
            )
        )
    assert prepared_count == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_paper_mode_transition_linearizes_before_final_claim_and_blocks_later_posts(
    pg_session_factory,
    pg_engine,
) -> None:
    broker = _CountingFakeBroker()
    barrier = LiveOrderSubmissionBarrier(pg_engine)
    preparation_repository = _BlockingPreparationRepository()
    order_service = LiveOrderExecutionService(
        pg_session_factory,
        broker,
        barrier,
    )
    order_service._repository = preparation_repository
    mode_service = TradingModeControlService(pg_session_factory, barrier)
    request = LiveOrderRequest(
        source_type="AI",
        source_ref="analysis:prepare-paper-mode-race:KRW-BTC:bid",
        market="KRW-BTC",
        side="bid",
        ord_type="price",
        price=REQUESTED_PRICE,
    )

    order_task = asyncio.create_task(order_service.execute(request))
    await asyncio.wait_for(
        preparation_repository.prepared_written.wait(),
        timeout=POSTGRES_TASK_TIMEOUT_SECONDS,
    )
    paper_task = asyncio.create_task(
        mode_service.enable_paper(
            EnablePaperTradingModeCommand(
                request_id=uuid4(),
                expected_version=2,
                reason_text="최종 주문 claim과 paper 모드 전환의 선형화를 검증합니다.",
                actor_ref="pytest",
            )
        )
    )
    await asyncio.sleep(0.1)
    assert paper_task.done() is False

    preparation_repository.allow_prepare_commit.set()
    order_result = await asyncio.wait_for(
        order_task,
        timeout=POSTGRES_TASK_TIMEOUT_SECONDS,
    )
    paper_result = await asyncio.wait_for(
        paper_task,
        timeout=POSTGRES_TASK_TIMEOUT_SECONDS,
    )

    assert paper_result.control.mode == "paper"
    assert order_result.submission_status in {"ABANDONED", "ACCEPTED"}
    assert broker.post_count <= 1
    post_count_after_transition = broker.post_count

    blocked = await order_service.execute(
        LiveOrderRequest(
            source_type="AI",
            source_ref="analysis:after-paper-mode:KRW-ETH:bid",
            market="KRW-ETH",
            side="bid",
            ord_type="price",
            price=REQUESTED_PRICE,
        )
    )

    assert blocked.error_code in {
        "BOT_INACTIVE",
        "LIVE_ORDER_GATE_BLOCKED",
        "TRADING_MODE_LIVE_REQUIRED",
    }
    assert broker.post_count == post_count_after_transition


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_stop_waits_for_inflight_broker_post_and_blocks_all_later_posts(
    pg_session_factory,
    pg_engine,
) -> None:
    broker = _CountingFakeBroker()
    broker.allow_post_return.clear()
    barrier = LiveOrderSubmissionBarrier(pg_engine)
    order_service = LiveOrderExecutionService(
        pg_session_factory,
        broker,
        barrier,
    )
    control_service = LiveOrderControlService(barrier=barrier)

    order_task = asyncio.create_task(
        order_service.execute(
            LiveOrderRequest(
                source_type="AI",
                source_ref="analysis:inflight-post-stop:KRW-BTC:bid",
                market="KRW-BTC",
                side="bid",
                ord_type="price",
                price=REQUESTED_PRICE,
            )
        )
    )
    await asyncio.wait_for(
        broker.post_started.wait(),
        timeout=POSTGRES_TASK_TIMEOUT_SECONDS,
    )
    stop_task = asyncio.create_task(
        control_service.stop_bot(
            BlockLiveOrdersCommand(
                request_id=uuid4(),
                reason_code="TEST_INFLIGHT_POST_STOP",
                reason_text="거래소 POST 반환 전에는 운영 정지가 성공하지 않는지 검증합니다.",
                source="REST",
                actor_ref="pytest",
            )
        )
    )

    await asyncio.sleep(0.1)
    assert stop_task.done() is False
    assert broker.post_count == 1

    broker.allow_post_return.set()
    order_result = await asyncio.wait_for(
        order_task,
        timeout=POSTGRES_TASK_TIMEOUT_SECONDS,
    )
    try:
        stop_result = await asyncio.wait_for(
            stop_task,
            timeout=POSTGRES_TASK_TIMEOUT_SECONDS,
        )
    except LiveOrderControlDrainPendingError:
        stop_result = await control_service.stop_bot(
            BlockLiveOrdersCommand(
                request_id=uuid4(),
                reason_code="TEST_INFLIGHT_POST_STOP_RETRY",
                reason_text="거래소 POST 결과 저장 뒤 운영 정지 상태를 다시 확인합니다.",
                source="REST",
                actor_ref="pytest",
            )
        )

    assert order_result.submission_status == "ACCEPTED"
    assert stop_result.control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    post_count_after_stop = broker.post_count

    blocked_result = await order_service.execute(
        LiveOrderRequest(
            source_type="AI",
            source_ref="analysis:after-inflight-stop:KRW-ETH:bid",
            market="KRW-ETH",
            side="bid",
            ord_type="price",
            price=REQUESTED_PRICE,
        )
    )

    assert blocked_result.error_code in {"BOT_INACTIVE", "LIVE_ORDER_GATE_BLOCKED"}
    assert broker.post_count == post_count_after_stop == 1


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_stop_commits_block_but_requires_submitting_drain_before_success(
    pg_session_factory,
    pg_engine,
) -> None:
    intent = _intent(
        intent_key="d" * 64,
        identifier="4" * 32,
        market="KRW-BTC",
        side="bid",
    )
    intent.submission_status = "SUBMITTING"
    intent.post_attempt_count = 1
    intent.submitted_at = datetime.now(UTC)
    intent.prepared_control_generation = 2
    intent.prepared_control_mode = LIVE_ORDER_MODE_ARMED
    intent.control_generation = 2
    intent.control_mode = LIVE_ORDER_MODE_ARMED
    intent.control_event_id = 2
    intent.submission_authorized_at = datetime.now(UTC)
    async with pg_session_factory() as session:
        session.add(intent)
        await session.commit()
        intent_id = intent.id

    service = LiveOrderControlService(
        barrier=LiveOrderSubmissionBarrier(pg_engine),
    )
    with pytest.raises(LiveOrderControlDrainPendingError):
        await service.stop_bot(
            BlockLiveOrdersCommand(
                request_id=uuid4(),
                reason_code="TEST_DRAIN",
                reason_text="SUBMITTING 주문의 durable drain 확인 전에는 성공하지 않습니다.",
                source="REST",
                actor_ref="pytest",
            )
        )

    async with pg_session_factory() as session:
        control = await LiveOrderControlRepository().get_control(session)
        bot = await session.get(BotConfig, 1)
        assert control is not None
        assert control.mode == LIVE_ORDER_MODE_BLOCK_ALL
        assert bot is not None and bot.is_active is False
        await session.execute(
            update(OrderIntent)
            .where(OrderIntent.id == intent_id)
            .values(submission_status="UNKNOWN", unknown_at=datetime.now(UTC))
        )
        await session.commit()

    stopped = await service.stop_bot(
        BlockLiveOrdersCommand(
            request_id=uuid4(),
            reason_code="TEST_DRAIN_RETRY",
            reason_text="SUBMITTING 상태 해소 후 차단 완료 상태를 다시 확인합니다.",
            source="REST",
            actor_ref="pytest",
        )
    )
    assert stopped.control.mode == LIVE_ORDER_MODE_BLOCK_ALL


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_concurrent_terminal_projection_applies_fill_once(pg_session_factory) -> None:
    executed_volume = Decimal("0.125000000000000000")
    executed_funds = Decimal("12500.015625000000000000")
    average_fill_price = Decimal("100000.125000000000000000")
    now = datetime.now(UTC)

    terminal_intent = _intent(
        intent_key="e" * 64,
        identifier="5" * 32,
        market="KRW-BTC",
        side="bid",
    )
    terminal_intent.submission_status = "ACCEPTED"
    terminal_intent.exchange_uuid = "terminal-exchange-order"
    terminal_intent.exchange_state = "done"
    terminal_intent.executed_volume = executed_volume
    terminal_intent.executed_funds = executed_funds
    terminal_intent.average_fill_price = average_fill_price
    terminal_intent.remaining_volume = Decimal("0")
    terminal_intent.paid_fee = Decimal("6.250007812500000000")
    terminal_intent.projection_status = "PENDING"
    terminal_intent.post_attempt_count = 1
    terminal_intent.submitted_at = now
    terminal_intent.accepted_at = now
    terminal_intent.resolved_at = now

    async with pg_session_factory() as setup_session:
        setup_session.add(terminal_intent)
        await setup_session.commit()
        intent_id = terminal_intent.id

    async def project_once():
        async with pg_session_factory() as session:
            record = await OrderIntentRepository().project_terminal_fill(
                session,
                intent_id,
                now=datetime.now(UTC),
            )
            await session.commit()
            return record

    projected_records = await asyncio.gather(*(project_once() for _ in range(8)))
    repeated_record = await project_once()

    assert all(record.projection_status == "APPLIED" for record in projected_records)
    assert repeated_record.projection_status == "APPLIED"

    async with pg_session_factory() as verification_session:
        intent = await verification_session.get(OrderIntent, intent_id)
        histories = list(
            (
                await verification_session.scalars(
                    select(OrderHistory).where(OrderHistory.order_intent_id == intent_id)
                )
            ).all()
        )
        positions = list(
            (
                await verification_session.scalars(
                    select(Position)
                    .join(Asset, Position.asset_id == Asset.id)
                    .where(Asset.symbol == "KRW-BTC", Position.is_paper.is_(False))
                )
            ).all()
        )

    assert intent is not None
    assert intent.projection_status == "APPLIED"
    assert intent.executed_volume == executed_volume
    assert intent.executed_funds == executed_funds
    assert intent.average_fill_price == average_fill_price
    assert len(histories) == 1
    assert histories[0].qty == pytest.approx(float(executed_volume))
    assert histories[0].price == pytest.approx(float(average_fill_price))
    assert len(positions) == 1
    assert positions[0].quantity == pytest.approx(float(executed_volume))
    assert positions[0].avg_entry_price == pytest.approx(float(average_fill_price))


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_concurrent_liquidation_idempotency_key_reuses_operation(
    pg_session_factory,
    pg_engine,
) -> None:
    broker = _LiquidationV2FakeBroker()
    coordinators = [
        LiquidationCoordinator(
            pg_session_factory,
            broker,
            LiveOrderSubmissionBarrier(pg_engine),
        )
        for _ in range(8)
    ]
    idempotency_key = "11111111-1111-4111-8111-111111111111"

    results = await asyncio.gather(
        *(_start_liquidation_v2(coordinator, idempotency_key) for coordinator in coordinators)
    )

    assert {result.id for result in results} == {results[0].id}
    assert {result.phase for result in results} == {"DISCOVERING_ORDERS"}
    assert broker.post_count == 0
    async with pg_session_factory() as verification_session:
        operation_count = await verification_session.scalar(
            select(func.count(LiquidationOperation.id))
        )
        intent_count = await verification_session.scalar(
            select(func.count(OrderIntent.id))
        )
    assert operation_count == 1
    assert intent_count == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_liquidation_v2_worker_verifies_account_and_projects_once(
    pg_session_factory,
    pg_engine,
) -> None:
    broker = _LiquidationV2FakeBroker()
    coordinator = LiquidationCoordinator(
        pg_session_factory,
        broker,
        LiveOrderSubmissionBarrier(pg_engine),
    )

    started = await _start_liquidation_v2(
        coordinator,
        "12121212-1212-4212-8212-121212121212",
    )
    completed = await coordinator.refresh_operation(started.id)

    assert completed.status == "COMPLETED"
    assert completed.phase == "TERMINAL"
    assert completed.verification_status == "VERIFIED"
    assert completed.summary.attempted == 1
    assert completed.summary.succeeded == 1
    assert completed.summary.remaining == 0
    assert completed.items[0].requested_volume == Decimal("0.1")
    assert completed.items[0].final_balance == Decimal("0")
    assert broker.post_count == 1
    assert broker.cancel_count == 0

    async with pg_session_factory() as verification_session:
        history_count = await verification_session.scalar(
            select(func.count(OrderHistory.id))
        )
        position = await verification_session.scalar(select(Position))
        control = await verification_session.scalar(select(LiveOrderControl))
    assert history_count == 1
    assert position is not None
    assert position.quantity == pytest.approx(0)
    assert control is not None
    assert control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert control.active_liquidation_operation_id is None


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_liquidation_v2_cancels_manual_order_before_any_sell_post(
    pg_session_factory,
    pg_engine,
) -> None:
    broker = _LiquidationV2CancelFakeBroker()
    coordinator = LiquidationCoordinator(
        pg_session_factory,
        broker,
        LiveOrderSubmissionBarrier(pg_engine),
    )

    started = await _start_liquidation_v2(
        coordinator,
        "13131313-1313-4313-8313-131313131313",
    )
    completed = await coordinator.refresh_operation(started.id)
    # 취소 원장이 추가된 경로는 한 worker claim의 12단계 예산을 모두 사용할 수 있습니다.
    for _ in range(2):
        if completed.status in {"COMPLETED", "PARTIAL", "FAILED", "NO_ASSETS"}:
            break
        completed = await coordinator.refresh_operation(started.id)

    assert completed.status == "COMPLETED"
    assert completed.summary.discovered_orders == 1
    assert completed.summary.cancel_confirmed == 1
    assert completed.cancellations[0].ownership == "EXTERNAL"
    assert completed.cancellations[0].status == "CONFIRMED"
    assert broker.call_order == ["cancel", "post"]
    assert broker.cancel_count == 1
    assert broker.post_count == 1


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_paper_mode_liquidation_is_rejected_before_operation_creation(
    pg_session_factory,
    pg_engine,
) -> None:
    async with pg_session_factory() as setup_session, setup_session.begin():
        await setup_session.execute(
            update(TradingModeControl)
            .where(TradingModeControl.id == 1)
            .values(mode="paper")
        )
        await setup_session.execute(
            update(SystemConfig)
            .where(SystemConfig.config_key == "trading_mode")
            .values(config_value="paper")
        )

    broker = _LiquidationV2FakeBroker()
    coordinator = LiquidationCoordinator(
        pg_session_factory,
        broker,
        LiveOrderSubmissionBarrier(pg_engine),
    )

    with pytest.raises(LiveOrderControlPolicyError) as raised:
        await _start_liquidation_v2(
            coordinator,
            "77777777-7777-4777-8777-777777777777",
        )

    assert raised.value.error_code == "TRADING_MODE_LIVE_REQUIRED"
    async with pg_session_factory() as verification_session:
        operation_count = await verification_session.scalar(
            select(func.count(LiquidationOperation.id))
        )
    assert operation_count == 0
    assert broker.account_count == 0
    assert broker.post_count == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_stop_after_liquidation_authorization_fails_unsubmitted_targets(
    pg_session_factory,
    pg_engine,
) -> None:
    broker = _LiquidationV2FakeBroker()
    barrier = LiveOrderSubmissionBarrier(pg_engine)

    class _PausedCoordinator(LiquidationCoordinator):
        def __init__(self) -> None:
            super().__init__(pg_session_factory, broker, barrier)
            self.authorization_committed = asyncio.Event()
            self.allow_execute = asyncio.Event()

        async def _phase_submitting(self, operation):
            self.authorization_committed.set()
            await self.allow_execute.wait()
            return await super()._phase_submitting(operation)

    coordinator = _PausedCoordinator()
    operation_key = "66666666-6666-4666-8666-666666666666"
    started = await _start_liquidation_v2(coordinator, operation_key)
    execute_task = asyncio.create_task(coordinator.refresh_operation(started.id))
    try:
        # Windows Docker의 fsync 지연 중에도 실제 교착과 단순 I/O 지연을 구분할 수 있게 둡니다.
        await asyncio.wait_for(
            coordinator.authorization_committed.wait(),
            timeout=POSTGRES_TASK_TIMEOUT_SECONDS,
        )

        async with pg_session_factory() as lookup_session:
            operation_id = await lookup_session.scalar(
                select(LiquidationOperation.id).where(
                    LiquidationOperation.idempotency_key == operation_key
                )
            )
        assert operation_id is not None

        # stop 전에 저장된 PREPARING placeholder도 이후 revocation failure로 덮어써야 합니다.
        pre_stop = await coordinator.get_operation(operation_id)
        assert pre_stop.status == "IN_PROGRESS"
        assert pre_stop.phase == "SUBMITTING"

        stopped = await LiveOrderControlService(barrier=barrier).stop_bot(
            BlockLiveOrdersCommand(
                request_id=uuid4(),
                reason_code="TEST_STOP_AFTER_LIQUIDATION_AUTH",
                reason_text="청산 승인 직후 정지가 미제출 대상을 영구 실패로 종결하는지 확인합니다.",
                source="REST",
                actor_ref="pytest",
            )
        )
        coordinator.allow_execute.set()

        result = await asyncio.wait_for(
            execute_task,
            timeout=POSTGRES_TASK_TIMEOUT_SECONDS,
        )
        assert result.status == "FAILED"
        assert stopped.control.mode == LIVE_ORDER_MODE_BLOCK_ALL

        async with pg_session_factory() as verification_session:
            operation = await verification_session.get(LiquidationOperation, operation_id)

        assert operation is not None
        assert operation.status == "FAILED"
        assert operation.emergency_authorization_status == "REVOKED"
        assert operation.result_snapshot[0]["submission_status"] == "ABANDONED"
        assert operation.result_snapshot[0]["error_code"] == "EMERGENCY_AUTH_REVOKED"
        assert broker.post_count == 0
    finally:
        if not execute_task.done():
            coordinator.allow_execute.set()
            execute_task.cancel()
            with suppress(asyncio.CancelledError):
                await execute_task


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_concurrent_different_liquidations_bind_only_one_snapshot_and_exit_scope(
    pg_session_factory,
    pg_engine,
) -> None:
    broker = _LiquidationV2FakeBroker()
    coordinators = [
        LiquidationCoordinator(
            pg_session_factory,
            broker,
            LiveOrderSubmissionBarrier(pg_engine),
        )
        for _ in range(2)
    ]
    keys = [
        "33333333-3333-4333-8333-333333333333",
        "44444444-4444-4444-8444-444444444444",
    ]

    results = await asyncio.gather(
        *(
            _start_liquidation_v2(coordinator, key)
            for coordinator, key in zip(coordinators, keys)
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, BaseException) for result in results) == 1
    assert broker.account_count == 0
    assert broker.post_count == 0

    async with pg_session_factory() as verification_session:
        operations = list(
            (
                await verification_session.scalars(
                    select(LiquidationOperation).order_by(LiquidationOperation.id)
                )
            ).all()
        )
        control = await verification_session.scalar(select(LiveOrderControl))

    assert len(operations) == 1
    active = operations[0]
    assert active.status == "IN_PROGRESS"
    assert active.phase == "DISCOVERING_ORDERS"
    assert control is not None
    assert control.mode == LIVE_ORDER_MODE_BLOCK_ALL
    assert control.active_liquidation_operation_id is None
    errors = [
        result for result in results if isinstance(result, LiveOrderControlPolicyError)
    ]
    assert len(errors) == 1
    assert errors[0].error_code == "ACTIVE_LIQUIDATION_EXISTS"


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_terminal_liquidation_operation_does_not_regress(
    pg_session_factory,
    pg_engine,
) -> None:
    operation = LiquidationOperation(
        idempotency_key="22222222-2222-4222-8222-222222222222",
        status="COMPLETED",
        request_fingerprint="e" * 64,
        phase="TERMINAL",
        verification_status="VERIFIED",
        target_snapshot=[{"market": "KRW-BTC", "volume": "0.1"}],
        result_snapshot=[{"market": "KRW-BTC", "submission_status": "ACCEPTED"}],
        completed_at=datetime.now(UTC),
    )
    async with pg_session_factory() as setup_session:
        setup_session.add(operation)
        await setup_session.commit()
        operation_id = operation.id

    coordinator = LiquidationCoordinator(
        pg_session_factory,
        _CountingFakeBroker(),
        LiveOrderSubmissionBarrier(pg_engine),
    )
    await coordinator._save_result_item(
        operation_id,
        {
            "market": "KRW-BTC",
            "submission_status": "UNKNOWN",
            "error_code": "LATE_RESULT",
        },
    )

    async with pg_session_factory() as verification_session:
        persisted = await verification_session.get(LiquidationOperation, operation_id)
    assert persisted is not None
    assert persisted.status == "COMPLETED"
    assert persisted.completed_at is not None
    assert persisted.result_snapshot == [
        {"market": "KRW-BTC", "submission_status": "ACCEPTED"}
    ]


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_closed_liquidation_replay_is_read_only_after_gate_is_rearmed(
    pg_session_factory,
    pg_engine,
) -> None:
    now = datetime.now(UTC)
    operation = LiquidationOperation(
        idempotency_key="55555555-5555-4555-8555-555555555555",
        status="COMPLETED",
        request_fingerprint=build_liquidation_request_fingerprint("ACCOUNT_ALL"),
        phase="TERMINAL",
        verification_status="VERIFIED",
        target_snapshot=[{"market": "KRW-BTC", "volume": "0.1"}],
        result_snapshot=[{"market": "KRW-BTC", "submission_status": "ACCEPTED"}],
        completed_at=now,
        emergency_authorization_status="CLOSED",
        emergency_revoked_at=null(),
        emergency_revocation_reason=null(),
        emergency_closed_at=now,
    )
    async with pg_session_factory() as setup_session:
        setup_session.add(operation)
        await setup_session.commit()
        operation_id = operation.id
        event_count_before = await setup_session.scalar(
            select(func.count(LiveOrderControlEvent.id))
        )

    broker = _CountingFakeBroker()
    coordinator = LiquidationCoordinator(
        pg_session_factory,
        broker,
        LiveOrderSubmissionBarrier(pg_engine),
    )

    replay = await _start_liquidation_v2(coordinator, operation.idempotency_key)
    lookup = await coordinator.get_operation(operation_id)

    async with pg_session_factory() as verification_session:
        control = await verification_session.scalar(select(LiveOrderControl))
        event_count_after = await verification_session.scalar(
            select(func.count(LiveOrderControlEvent.id))
        )

    assert replay.status == "COMPLETED"
    assert lookup.status == "COMPLETED"
    assert control is not None
    assert control.mode == LIVE_ORDER_MODE_ARMED
    assert control.active_liquidation_operation_id is None
    assert event_count_after == event_count_before
    assert broker.account_count == 0
    assert broker.post_count == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_expired_operation_lease_prevents_stale_worker_state_write(
    pg_session_factory,
    pg_engine,
) -> None:
    now = datetime.now(UTC)
    operation = LiquidationOperation(
        idempotency_key=str(uuid4()),
        status="IN_PROGRESS",
        request_fingerprint=build_liquidation_request_fingerprint("ACCOUNT_ALL"),
        phase="DISCOVERING_ORDERS",
        verification_status="PENDING",
        next_run_at=now,
    )
    async with pg_session_factory() as setup_session:
        setup_session.add(operation)
        await setup_session.commit()
        operation_id = operation.id

    repository = LiquidationRepository()
    async with pg_session_factory() as first_claim_session:
        first_token = await repository.claim_operation(
            first_claim_session,
            operation_id,
            now=now,
            lease_for=timedelta(seconds=120),
        )
        await first_claim_session.commit()
    assert first_token is not None

    first_worker = LiquidationCoordinator(
        pg_session_factory,
        _CountingFakeBroker(),
        LiveOrderSubmissionBarrier(pg_engine),
    )
    first_worker._operation_lease_tokens[operation_id] = first_token

    second_claim_at = now + timedelta(seconds=1)
    async with pg_session_factory() as expiry_session:
        await expiry_session.execute(
            update(LiquidationOperation)
            .where(LiquidationOperation.id == operation_id)
            .values(lease_until=second_claim_at - timedelta(microseconds=1))
        )
        await expiry_session.commit()

    async with pg_session_factory() as second_claim_session:
        second_token = await repository.claim_operation(
            second_claim_session,
            operation_id,
            now=second_claim_at,
            lease_for=timedelta(seconds=120),
        )
        await second_claim_session.commit()
    assert second_token is not None
    assert second_token != first_token

    with pytest.raises(LiquidationLeaseLostError):
        await first_worker._transition_phase(operation_id, "CANCELING_ORDERS")
    await first_worker._release_operation_lease(operation_id)

    async with pg_session_factory() as verification_session:
        persisted = await verification_session.get(LiquidationOperation, operation_id)
    assert persisted is not None
    assert persisted.phase == "DISCOVERING_ORDERS"
    assert persisted.lease_until == second_token


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_expired_cancellation_claim_rejects_stale_resolution(
    pg_session_factory,
    pg_engine,
) -> None:
    now = datetime.now(UTC)
    operation = LiquidationOperation(
        idempotency_key=str(uuid4()),
        status="IN_PROGRESS",
        request_fingerprint=build_liquidation_request_fingerprint("ACCOUNT_ALL"),
        phase="CANCELING_ORDERS",
        verification_status="PENDING",
        lease_until=now + timedelta(minutes=5),
        next_run_at=None,
    )
    async with pg_session_factory() as setup_session:
        setup_session.add(operation)
        await setup_session.flush()
        cancellation = LiquidationOrderCancellation(
            liquidation_operation_id=operation.id,
            exchange_uuid="stale-cancel-uuid",
            market="KRW-BTC",
            side="ask",
            initial_exchange_state="wait",
            ownership="EXTERNAL",
            status="UNKNOWN",
            attempt_count=1,
            version=1,
            next_retry_at=now - timedelta(seconds=1),
            discovered_at=now,
            last_checked_at=now,
            created_at=now,
            updated_at=now,
        )
        setup_session.add(cancellation)
        await setup_session.commit()
        operation_id = operation.id
        cancellation_id = cancellation.id
        operation_token = operation.lease_until
    assert operation_token is not None

    repository = LiquidationRepository()
    async with pg_session_factory() as first_claim_session:
        first_claim = await repository.due_unknown_cancellations(
            first_claim_session,
            operation_id,
            now=now,
            lease_for=timedelta(seconds=90),
            limit=1,
        )
        first_version = first_claim[0].version
        first_reconcile_attempt_count = first_claim[0].reconcile_attempt_count
        await first_claim_session.commit()
    assert first_reconcile_attempt_count == 1

    second_claim_at = now + timedelta(seconds=1)
    async with pg_session_factory() as expiry_session:
        await expiry_session.execute(
            update(LiquidationOrderCancellation)
            .where(LiquidationOrderCancellation.id == cancellation_id)
            .values(
                lease_until=second_claim_at - timedelta(microseconds=1),
                next_retry_at=second_claim_at - timedelta(microseconds=1),
            )
        )
        await expiry_session.commit()

    async with pg_session_factory() as second_claim_session:
        second_claim = await repository.due_unknown_cancellations(
            second_claim_session,
            operation_id,
            now=second_claim_at,
            lease_for=timedelta(seconds=90),
            limit=1,
        )
        second_version = second_claim[0].version
        second_reconcile_attempt_count = second_claim[0].reconcile_attempt_count
        await second_claim_session.commit()
    assert second_version > first_version
    assert second_reconcile_attempt_count == 2

    stale_worker = LiquidationCoordinator(
        pg_session_factory,
        _CountingFakeBroker(),
        LiveOrderSubmissionBarrier(pg_engine),
    )
    stale_worker._operation_lease_tokens[operation_id] = operation_token
    await stale_worker._apply_cancel_resolution(
        cancellation_id,
        ("CONFIRMED", Decimal("0"), Decimal("0"), None, None),
        expected_version=first_version,
    )

    async with pg_session_factory() as verification_session:
        persisted = await verification_session.get(
            LiquidationOrderCancellation,
            cancellation_id,
        )
    assert persisted is not None
    assert persisted.status == "UNKNOWN"
    assert persisted.resolved_at is None
    assert persisted.version == second_version
    assert persisted.reconcile_attempt_count == 2


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_crash_after_cancel_claim_recovers_to_lookup_only_unknown(
    pg_session_factory,
    pg_engine,
) -> None:
    now = datetime.now(UTC)
    operation = LiquidationOperation(
        idempotency_key=str(uuid4()),
        status="IN_PROGRESS",
        request_fingerprint=build_liquidation_request_fingerprint("ACCOUNT_ALL"),
        phase="CANCELING_ORDERS",
        verification_status="PENDING",
        lease_until=now + timedelta(minutes=5),
        next_run_at=None,
    )
    async with pg_session_factory() as setup_session:
        setup_session.add(operation)
        await setup_session.flush()
        cancellation = LiquidationOrderCancellation(
            liquidation_operation_id=operation.id,
            exchange_uuid="crashed-cancel-uuid",
            market="KRW-BTC",
            side="ask",
            initial_exchange_state="watch",
            ownership="EXTERNAL",
            status="CANCELING",
            attempt_count=1,
            reconcile_attempt_count=0,
            version=2,
            lease_until=now - timedelta(seconds=1),
            canceling_at=now - timedelta(seconds=2),
            discovered_at=now - timedelta(seconds=3),
            last_checked_at=now - timedelta(seconds=2),
            created_at=now - timedelta(seconds=3),
            updated_at=now - timedelta(seconds=2),
        )
        setup_session.add(cancellation)
        await setup_session.commit()
        operation_id = operation.id
        cancellation_id = cancellation.id
        operation_token = operation.lease_until
    assert operation_token is not None

    broker = _LiquidationV2FakeBroker()
    coordinator = LiquidationCoordinator(
        pg_session_factory,
        broker,
        LiveOrderSubmissionBarrier(pg_engine),
    )
    coordinator._operation_lease_tokens[operation_id] = operation_token
    await coordinator._recover_stale_cancel_claims(operation_id)

    async with pg_session_factory() as verification_session:
        persisted = await verification_session.get(
            LiquidationOrderCancellation,
            cancellation_id,
        )
    assert persisted is not None
    assert persisted.status == "UNKNOWN"
    assert persisted.attempt_count == 1
    assert persisted.reconcile_attempt_count == 0
    assert persisted.lease_until is None
    assert persisted.next_retry_at is not None
    assert persisted.last_error_code == "CANCEL_RESPONSE_UNKNOWN"
    assert broker.cancel_count == 0


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_third_confirmed_open_lookup_exhausts_cancel_retries(
    pg_session_factory,
    pg_engine,
) -> None:
    now = datetime.now(UTC)
    operation = LiquidationOperation(
        idempotency_key=str(uuid4()),
        status="IN_PROGRESS",
        request_fingerprint=build_liquidation_request_fingerprint("ACCOUNT_ALL"),
        phase="CANCELING_ORDERS",
        verification_status="PENDING",
        lease_until=now + timedelta(minutes=5),
        next_run_at=None,
    )
    async with pg_session_factory() as setup_session:
        setup_session.add(operation)
        await setup_session.flush()
        cancellation = LiquidationOrderCancellation(
            liquidation_operation_id=operation.id,
            exchange_uuid="retry-exhausted-uuid",
            market="KRW-BTC",
            side="ask",
            initial_exchange_state="wait",
            ownership="EXTERNAL",
            status="CANCELING",
            attempt_count=3,
            reconcile_attempt_count=0,
            version=4,
            lease_until=now + timedelta(seconds=90),
            canceling_at=now,
            discovered_at=now - timedelta(minutes=1),
            last_checked_at=now,
            created_at=now - timedelta(minutes=1),
            updated_at=now,
        )
        setup_session.add(cancellation)
        await setup_session.commit()
        operation_id = operation.id
        cancellation_id = cancellation.id
        operation_token = operation.lease_until
        expected_version = cancellation.version
    assert operation_token is not None

    coordinator = LiquidationCoordinator(
        pg_session_factory,
        _LiquidationV2FakeBroker(),
        LiveOrderSubmissionBarrier(pg_engine),
    )
    coordinator._operation_lease_tokens[operation_id] = operation_token
    await coordinator._apply_cancel_resolution(
        cancellation_id,
        ("OPEN", Decimal("0"), Decimal("1"), None, None),
        expected_version=expected_version,
    )

    async with pg_session_factory() as verification_session:
        persisted = await verification_session.get(
            LiquidationOrderCancellation,
            cancellation_id,
        )
    assert persisted is not None
    assert persisted.status == "FAILED"
    assert persisted.attempt_count == 3
    assert persisted.resolved_at is not None
    assert persisted.next_retry_at is None
    assert persisted.last_error_code == "CANCEL_RETRY_EXHAUSTED"
