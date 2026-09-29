from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ChatSessionSurface(StrEnum):
    AI_BANKER = "ai_banker"
    PORTFOLIO = "portfolio"


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    asset_type: Mapped[str] = mapped_column(String, nullable=False)
    base_currency: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False, index=True)
    avg_entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class OrderHistory(Base):
    __tablename__ = "order_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"), nullable=False, index=True)
    ai_analysis_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_analysis_logs.id"),
        nullable=True,
        index=True,
    )
    side: Mapped[str] = mapped_column(String, nullable=False)
    order_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    broker: Mapped[str] = mapped_column(String, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class BotConfig(Base):
    __tablename__ = "bot_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SystemConfig(Base):
    __tablename__ = "system_configs"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_system_configs_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_key: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    config_value: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )


class ApiRateLimitWindow(Base):
    """다중 worker가 공유하는 API fixed-window 요청 제한 상태입니다."""

    __tablename__ = "api_rate_limit_windows"
    __table_args__ = (
        CheckConstraint(
            "length(trim(policy_key)) > 0",
            name="ck_api_rate_limit_windows_policy_key",
        ),
        CheckConstraint(
            "subject_hash ~ '^[0-9a-f]{64}$'",
            name="ck_api_rate_limit_windows_subject_hash_hex",
        ),
        CheckConstraint(
            "request_count BETWEEN 1 AND 9223372036854775807",
            name="ck_api_rate_limit_windows_request_count",
        ),
        CheckConstraint(
            "rejected_count BETWEEN 0 AND 9223372036854775807",
            name="ck_api_rate_limit_windows_rejected_count",
        ),
        Index(
            "ix_api_rate_limit_windows_cleanup_due",
            "window_started_at",
        ),
    )

    policy_key: Mapped[str] = mapped_column(String(48), primary_key=True)
    subject_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
    )
    request_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
        server_default="1",
    )
    rejected_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TradingModeControl(Base):
    __tablename__ = "trading_mode_controls"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_trading_mode_controls_singleton"),
        CheckConstraint("mode IN ('paper', 'live')", name="ck_trading_mode_controls_mode"),
        CheckConstraint("version >= 1", name="ck_trading_mode_controls_version"),
        CheckConstraint(
            "changed_source IN ('REST', 'SLACK', 'TELEGRAM', 'SYSTEM')",
            name="ck_trading_mode_controls_changed_source",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=False,
        default=1,
    )
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="paper",
        server_default="paper",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    changed_source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="SYSTEM",
        server_default="SYSTEM",
    )
    changed_actor_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TradingModeControlEvent(Base):
    __tablename__ = "trading_mode_control_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('INITIALIZED', 'LIVE_ENABLED', 'PAPER_CONFIRMED')",
            name="ck_trading_mode_control_events_action",
        ),
        CheckConstraint(
            "from_mode IS NULL OR from_mode IN ('paper', 'live')",
            name="ck_trading_mode_control_events_from_mode",
        ),
        CheckConstraint(
            "to_mode IN ('paper', 'live')",
            name="ck_trading_mode_control_events_to_mode",
        ),
        CheckConstraint(
            "source IN ('REST', 'SLACK', 'TELEGRAM', 'SYSTEM')",
            name="ck_trading_mode_control_events_source",
        ),
        CheckConstraint("version >= 1", name="ck_trading_mode_control_events_version"),
        CheckConstraint(
            "request_fingerprint IS NULL OR request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_trading_mode_control_events_request_fingerprint_hex",
        ),
        CheckConstraint(
            "request_id IS NULL OR request_id ~* "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_trading_mode_control_events_request_id_uuid4",
        ),
        CheckConstraint(
            "reauth_jti IS NULL OR reauth_jti ~* "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_trading_mode_control_events_reauth_jti_uuid4",
        ),
        CheckConstraint(
            "(request_id IS NULL AND request_fingerprint IS NULL) OR "
            "(request_id IS NOT NULL AND request_fingerprint IS NOT NULL)",
            name="ck_trading_mode_control_events_request_pair",
        ),
        CheckConstraint(
            "(action = 'INITIALIZED' AND from_mode IS NULL AND to_mode = 'paper' "
            "AND request_id IS NULL AND request_fingerprint IS NULL AND reauth_jti IS NULL) OR "
            "(action = 'LIVE_ENABLED' AND from_mode = 'paper' AND to_mode = 'live' "
            "AND request_id IS NOT NULL AND request_fingerprint IS NOT NULL "
            "AND reauth_jti IS NOT NULL) OR "
            "(action = 'PAPER_CONFIRMED' AND from_mode IN ('paper', 'live') "
            "AND to_mode = 'paper' AND request_id IS NOT NULL "
            "AND request_fingerprint IS NOT NULL AND reauth_jti IS NULL)",
            name="ck_trading_mode_control_events_transition",
        ),
        UniqueConstraint("request_id", name="uq_trading_mode_control_events_request_id"),
        UniqueConstraint("reauth_jti", name="uq_trading_mode_control_events_reauth_jti"),
        UniqueConstraint(
            "control_id",
            "version",
            name="uq_trading_mode_control_events_control_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    control_id: Mapped[int] = mapped_column(
        ForeignKey(
            "trading_mode_controls.id",
            name="fk_trading_mode_control_events_control_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reauth_jti: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    from_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    legacy_raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AIAnalysisLog(Base):
    __tablename__ = "ai_analysis_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_weight: Mapped[int] = mapped_column(Integer, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    accuracy_label: Mapped[str | None] = mapped_column(String, nullable=True)
    actual_price_diff_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


LIQUIDATION_ACTIVE_PREDICATE = "status IN ('PREPARING', 'IN_PROGRESS')"
LIQUIDATION_PHASES = (
    "'BLOCKING', 'DISCOVERING_ORDERS', 'CANCELING_ORDERS', "
    "'RECONCILING_CANCELED_ORDERS', 'SNAPSHOTTING_TARGETS', 'SUBMITTING', "
    "'WAITING_FILLS', 'VERIFYING', 'TERMINAL'"
)


class LiquidationOperation(Base):
    __tablename__ = "liquidation_operations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PREPARING', 'IN_PROGRESS', 'COMPLETED', 'PARTIAL', 'FAILED', 'NO_ASSETS')",
            name="ck_liquidation_operations_status",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_liquidation_operations_idempotency_key",
        ),
        CheckConstraint(
            "emergency_authorization_status IN ('ACTIVE', 'REVOKED', 'CLOSED')",
            name="ck_liquidation_operations_emergency_authorization_status",
        ),
        CheckConstraint(
            "emergency_control_generation IS NULL OR emergency_control_generation >= 1",
            name="ck_liquidation_operations_emergency_control_generation",
        ),
        CheckConstraint(
            "emergency_authorized_source IS NULL OR emergency_authorized_source IN "
            "('REST', 'SLACK', 'TELEGRAM', 'SYSTEM', 'AUTH_FAILURE')",
            name="ck_liquidation_operations_emergency_authorized_source",
        ),
        CheckConstraint(
            "(emergency_authorization_status = 'ACTIVE' AND "
            "emergency_authorized_at IS NOT NULL AND "
            "emergency_control_generation IS NOT NULL AND "
            "emergency_control_event_id IS NOT NULL AND "
            "emergency_authorized_source IS NOT NULL AND "
            "emergency_revoked_at IS NULL AND emergency_revocation_reason IS NULL AND "
            "emergency_closed_at IS NULL) OR "
            "(emergency_authorization_status = 'REVOKED' AND "
            "emergency_revoked_at IS NOT NULL AND "
            "emergency_revocation_reason IS NOT NULL AND "
            "length(trim(emergency_revocation_reason)) > 0 AND "
            "emergency_closed_at IS NULL) OR "
            "(emergency_authorization_status = 'CLOSED' AND "
            "emergency_closed_at IS NOT NULL AND emergency_revoked_at IS NULL AND "
            "emergency_revocation_reason IS NULL)",
            name="ck_liquidation_operations_emergency_authorization_coherence",
        ),
        CheckConstraint(
            "length(trim(broker)) > 0 AND length(trim(account_scope)) > 0",
            name="ck_liquidation_operations_account_scope",
        ),
        CheckConstraint(
            "contract_version IN (1, 2)",
            name="ck_liquidation_operations_contract_version",
        ),
        CheckConstraint(
            "request_fingerprint IS NULL OR request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_liquidation_operations_request_fingerprint_hex",
        ),
        CheckConstraint(
            "cancel_scope IN ('LEGACY_NONE', 'ACCOUNT_ALL')",
            name="ck_liquidation_operations_cancel_scope",
        ),
        CheckConstraint(
            f"phase IN ({LIQUIDATION_PHASES})",
            name="ck_liquidation_operations_phase",
        ),
        CheckConstraint(
            "verification_status IN ('LEGACY_UNVERIFIED', 'PENDING', 'VERIFIED', 'ERROR')",
            name="ck_liquidation_operations_verification_status",
        ),
        CheckConstraint("version >= 0", name="ck_liquidation_operations_version"),
        CheckConstraint("retry_count >= 0", name="ck_liquidation_operations_retry_count"),
        CheckConstraint(
            "(contract_version = 1 AND request_fingerprint IS NULL "
            "AND cancel_scope = 'LEGACY_NONE' AND phase = 'TERMINAL' "
            "AND verification_status = 'LEGACY_UNVERIFIED') OR "
            "(contract_version = 2 AND request_fingerprint IS NOT NULL "
            "AND cancel_scope = 'ACCOUNT_ALL' "
            "AND verification_status <> 'LEGACY_UNVERIFIED')",
            name="ck_liquidation_operations_contract_coherence",
        ),
        CheckConstraint(
            "(status IN ('PREPARING', 'IN_PROGRESS') AND phase <> 'TERMINAL') OR "
            "(status IN ('COMPLETED', 'PARTIAL', 'FAILED', 'NO_ASSETS') "
            "AND phase = 'TERMINAL')",
            name="ck_liquidation_operations_status_phase",
        ),
        Index(
            "uq_liquidation_operations_active_account",
            "broker",
            "account_scope",
            unique=True,
            postgresql_where=text(LIQUIDATION_ACTIVE_PREDICATE),
        ),
        Index(
            "ix_liquidation_operations_due",
            "status",
            "next_run_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="PREPARING",
        server_default="PREPARING",
    )
    broker: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="UPBIT",
        server_default="UPBIT",
    )
    account_scope: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="primary",
        server_default="primary",
    )
    contract_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=2,
        server_default="2",
    )
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_scope: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="ACCOUNT_ALL",
        server_default="ACCOUNT_ALL",
    )
    phase: Mapped[str] = mapped_column(
        String(48),
        nullable=False,
        default="BLOCKING",
        server_default="BLOCKING",
    )
    verification_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    target_snapshot: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    result_snapshot: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    initial_account_snapshot: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    initial_accounts_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    post_cancel_account_snapshot: Mapped[dict | list | None] = mapped_column(
        JSON, nullable=True
    )
    post_cancel_accounts_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    final_account_snapshot: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    final_accounts_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_summary: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    order_summary: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    remaining_summary: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    emergency_authorization_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="REVOKED",
        server_default="REVOKED",
    )
    emergency_authorized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    emergency_control_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emergency_control_event_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "live_order_control_events.id",
            name="fk_liquidation_operations_emergency_control_event_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    emergency_authorized_source: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    emergency_revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )
    emergency_revocation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        server_default="FAIL_CLOSED_NOT_AUTHORIZED",
    )
    emergency_closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class LiquidationOrderCancellation(Base):
    __tablename__ = "liquidation_order_cancellations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DISCOVERED', 'CANCELING', 'UNKNOWN', 'CONFIRMED', 'FAILED')",
            name="ck_liquidation_order_cancellations_status",
        ),
        CheckConstraint(
            "ownership IN ('MANAGED', 'EXTERNAL')",
            name="ck_liquidation_order_cancellations_ownership",
        ),
        CheckConstraint(
            "side IN ('bid', 'ask')",
            name="ck_liquidation_order_cancellations_side",
        ),
        CheckConstraint(
            "initial_exchange_state IN ('wait', 'watch')",
            name="ck_liquidation_order_cancellations_initial_state",
        ),
        CheckConstraint(
            "attempt_count BETWEEN 0 AND 3",
            name="ck_liquidation_order_cancellations_attempt_count",
        ),
        CheckConstraint(
            "reconcile_attempt_count >= 0",
            name="ck_liquidation_order_cancellations_reconcile_attempt_count",
        ),
        CheckConstraint(
            "version >= 0",
            name="ck_liquidation_order_cancellations_version",
        ),
        CheckConstraint(
            "executed_volume IS NULL OR executed_volume >= 0",
            name="ck_liquidation_order_cancellations_executed_volume",
        ),
        CheckConstraint(
            "remaining_volume IS NULL OR remaining_volume >= 0",
            name="ck_liquidation_order_cancellations_remaining_volume",
        ),
        CheckConstraint(
            "(ownership = 'MANAGED' AND order_intent_id IS NOT NULL) OR "
            "(ownership = 'EXTERNAL' AND order_intent_id IS NULL)",
            name="ck_liquidation_order_cancellations_ownership_intent",
        ),
        CheckConstraint(
            "status <> 'CANCELING' OR (attempt_count >= 1 AND canceling_at IS NOT NULL)",
            name="ck_liquidation_order_cancellations_canceling_state",
        ),
        CheckConstraint(
            "status NOT IN ('CONFIRMED', 'FAILED') OR resolved_at IS NOT NULL",
            name="ck_liquidation_order_cancellations_resolved_state",
        ),
        UniqueConstraint(
            "liquidation_operation_id",
            "exchange_uuid",
            name="uq_liquidation_order_cancellations_operation_uuid",
        ),
        Index(
            "ix_liquidation_order_cancellations_due",
            "status",
            "next_retry_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    liquidation_operation_id: Mapped[int] = mapped_column(
        ForeignKey(
            "liquidation_operations.id",
            name="fk_liquidation_order_cancellations_operation_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    exchange_uuid: Mapped[str] = mapped_column(String(64), nullable=False)
    identifier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    initial_exchange_state: Mapped[str] = mapped_column(String(16), nullable=False)
    ownership: Mapped[str] = mapped_column(String(16), nullable=False)
    order_intent_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "order_intents.id",
            name="fk_liquidation_order_cancellations_order_intent_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="DISCOVERED",
        server_default="DISCOVERED",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    reconcile_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        server_default=func.now(),
    )
    executed_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    remaining_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    canceling_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class LiquidationOperationEvent(Base):
    __tablename__ = "liquidation_operation_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('OPERATION_CREATED', 'PHASE_CHANGED', 'ORDER_DISCOVERED', "
            "'CANCEL_REQUESTED', 'CANCEL_RESOLVED', 'ACCOUNT_OBSERVED', "
            "'TARGET_SNAPSHOTTED', 'ORDER_SUBMITTED', 'ORDER_RESOLVED', "
            "'VERIFICATION_RECORDED', 'OPERATION_TERMINATED', 'ERROR_RECORDED')",
            name="ck_liquidation_operation_events_event_type",
        ),
        CheckConstraint(
            f"from_phase IS NULL OR from_phase IN ({LIQUIDATION_PHASES})",
            name="ck_liquidation_operation_events_from_phase",
        ),
        CheckConstraint(
            f"to_phase IS NULL OR to_phase IN ({LIQUIDATION_PHASES})",
            name="ck_liquidation_operation_events_to_phase",
        ),
        CheckConstraint(
            "source IN ('REST', 'SLACK', 'TELEGRAM', 'SYSTEM', 'AUTH_FAILURE', 'WORKER')",
            name="ck_liquidation_operation_events_source",
        ),
        CheckConstraint("sequence >= 1", name="ck_liquidation_operation_events_sequence"),
        CheckConstraint(
            "operation_version >= 0",
            name="ck_liquidation_operation_events_operation_version",
        ),
        UniqueConstraint(
            "liquidation_operation_id",
            "sequence",
            name="uq_liquidation_operation_events_operation_sequence",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    liquidation_operation_id: Mapped[int] = mapped_column(
        ForeignKey(
            "liquidation_operations.id",
            name="fk_liquidation_operation_events_operation_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    from_phase: Mapped[str | None] = mapped_column(String(48), nullable=True)
    to_phase: Mapped[str | None] = mapped_column(String(48), nullable=True)
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="SYSTEM", server_default="SYSTEM"
    )
    actor_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LiveOrderControl(Base):
    __tablename__ = "live_order_controls"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('ARMED', 'EXIT_ONLY', 'BLOCK_ALL')",
            name="ck_live_order_controls_mode",
        ),
        CheckConstraint(
            "changed_source IN ('REST', 'SLACK', 'TELEGRAM', 'SYSTEM', 'AUTH_FAILURE')",
            name="ck_live_order_controls_changed_source",
        ),
        CheckConstraint("generation >= 1", name="ck_live_order_controls_generation"),
        CheckConstraint("version >= 1", name="ck_live_order_controls_version"),
        CheckConstraint(
            "(mode = 'EXIT_ONLY' AND active_liquidation_operation_id IS NOT NULL) OR "
            "(mode IN ('ARMED', 'BLOCK_ALL') AND active_liquidation_operation_id IS NULL)",
            name="ck_live_order_controls_active_liquidation",
        ),
        UniqueConstraint(
            "broker",
            "account_scope",
            name="uq_live_order_controls_broker_account_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broker: Mapped[str] = mapped_column(String(32), nullable=False)
    account_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="BLOCK_ALL",
        server_default="BLOCK_ALL",
    )
    active_liquidation_operation_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "liquidation_operations.id",
            name="fk_live_order_controls_active_liquidation_operation_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    generation: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    changed_source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="SYSTEM",
        server_default="SYSTEM",
    )
    changed_actor_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    armed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class LiveOrderControlEvent(Base):
    __tablename__ = "live_order_control_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('INITIALIZED', 'ARMED', 'BLOCKED', 'LIQUIDATION_AUTHORIZED', "
            "'LIQUIDATION_REVOKED', 'LIQUIDATION_CLOSED')",
            name="ck_live_order_control_events_action",
        ),
        CheckConstraint(
            "from_mode IS NULL OR from_mode IN ('ARMED', 'EXIT_ONLY', 'BLOCK_ALL')",
            name="ck_live_order_control_events_from_mode",
        ),
        CheckConstraint(
            "to_mode IN ('ARMED', 'EXIT_ONLY', 'BLOCK_ALL')",
            name="ck_live_order_control_events_to_mode",
        ),
        CheckConstraint(
            "source IN ('REST', 'SLACK', 'TELEGRAM', 'SYSTEM', 'AUTH_FAILURE')",
            name="ck_live_order_control_events_source",
        ),
        CheckConstraint(
            "request_fingerprint IS NULL OR request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_live_order_control_events_request_fingerprint_hex",
        ),
        CheckConstraint(
            "request_id IS NULL OR request_id ~* "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_live_order_control_events_request_id_uuid4",
        ),
        CheckConstraint(
            "(request_id IS NULL AND request_fingerprint IS NULL) OR "
            "(request_id IS NOT NULL AND request_fingerprint IS NOT NULL)",
            name="ck_live_order_control_events_request_pair",
        ),
        CheckConstraint(
            "(action IN ('LIQUIDATION_AUTHORIZED', 'LIQUIDATION_REVOKED', "
            "'LIQUIDATION_CLOSED') AND liquidation_operation_id IS NOT NULL) OR "
            "(action IN ('INITIALIZED', 'ARMED', 'BLOCKED') AND "
            "liquidation_operation_id IS NULL)",
            name="ck_live_order_control_events_liquidation_action",
        ),
        CheckConstraint("generation >= 1", name="ck_live_order_control_events_generation"),
        UniqueConstraint("request_id", name="uq_live_order_control_events_request_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    control_id: Mapped[int] = mapped_column(
        ForeignKey(
            "live_order_controls.id",
            name="fk_live_order_control_events_control_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=False,
        index=True,
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    from_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    liquidation_operation_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "liquidation_operations.id",
            name="fk_live_order_control_events_liquidation_operation_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


ORDER_INTENT_BLOCKING_PREDICATE = """
submission_status IN ('PREPARED', 'SUBMITTING', 'UNKNOWN')
OR (
    submission_status = 'ACCEPTED'
    AND (
        exchange_state IS NULL
        OR exchange_state IN ('wait', 'watch')
        OR (
            exchange_state IN ('done', 'cancel')
            AND projection_status IN ('PENDING', 'ERROR')
        )
    )
)
"""


class OrderIntent(Base):
    __tablename__ = "order_intents"
    __table_args__ = (
        CheckConstraint(
            "submission_status IN ('PREPARED', 'SUBMITTING', 'ACCEPTED', 'REJECTED', "
            "'UNKNOWN', 'ABANDONED', 'NO_ORDER_CONFIRMED')",
            name="ck_order_intents_submission_status",
        ),
        CheckConstraint(
            "projection_status IN ('PENDING', 'APPLIED', 'ERROR', 'SKIPPED')",
            name="ck_order_intents_projection_status",
        ),
        CheckConstraint(
            "execution_policy IN ('GENERAL', 'EMERGENCY_EXIT')",
            name="ck_order_intents_execution_policy",
        ),
        CheckConstraint(
            "exchange_state IS NULL OR exchange_state IN ('wait', 'watch', 'done', 'cancel')",
            name="ck_order_intents_exchange_state",
        ),
        CheckConstraint("side IN ('bid', 'ask')", name="ck_order_intents_side"),
        CheckConstraint(
            "ord_type IN ('price', 'market', 'limit', 'best')",
            name="ck_order_intents_ord_type",
        ),
        CheckConstraint(
            "identifier ~ '^[0-9a-f]{32}$'",
            name="ck_order_intents_identifier_hex",
        ),
        CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_order_intents_request_fingerprint_hex",
        ),
        CheckConstraint(
            "requested_price IS NULL OR requested_price > 0",
            name="ck_order_intents_requested_price_positive",
        ),
        CheckConstraint(
            "requested_volume IS NULL OR requested_volume > 0",
            name="ck_order_intents_requested_volume_positive",
        ),
        CheckConstraint(
            "(ord_type = 'price' AND side = 'bid' AND requested_price IS NOT NULL "
            "AND requested_volume IS NULL) OR "
            "(ord_type = 'market' AND side = 'ask' AND requested_volume IS NOT NULL "
            "AND requested_price IS NULL) OR "
            "(ord_type = 'limit' AND requested_price IS NOT NULL "
            "AND requested_volume IS NOT NULL) OR "
            "(ord_type = 'best' AND ((side = 'bid' AND requested_price IS NOT NULL "
            "AND requested_volume IS NULL) OR (side = 'ask' AND requested_volume IS NOT NULL "
            "AND requested_price IS NULL)))",
            name="ck_order_intents_request_shape",
        ),
        CheckConstraint(
            "submission_status <> 'ACCEPTED' OR "
            "(exchange_uuid IS NOT NULL AND length(trim(exchange_uuid)) > 0)",
            name="ck_order_intents_accepted_uuid",
        ),
        CheckConstraint(
            "submission_status <> 'SUBMITTING' OR "
            "(submitted_at IS NOT NULL AND post_attempt_count = 1)",
            name="ck_order_intents_submitting_state",
        ),
        CheckConstraint(
            "post_attempt_count BETWEEN 0 AND 1",
            name="ck_order_intents_post_attempt_count",
        ),
        CheckConstraint(
            "reconcile_attempt_count >= 0",
            name="ck_order_intents_reconcile_attempt_count",
        ),
        CheckConstraint(
            "not_found_count >= 0",
            name="ck_order_intents_not_found_count",
        ),
        CheckConstraint("version >= 0", name="ck_order_intents_version"),
        CheckConstraint(
            "prepared_control_generation IS NULL OR prepared_control_generation >= 1",
            name="ck_order_intents_prepared_control_generation",
        ),
        CheckConstraint(
            "control_generation IS NULL OR control_generation >= 1",
            name="ck_order_intents_control_generation",
        ),
        CheckConstraint(
            "prepared_control_mode IS NULL OR "
            "prepared_control_mode IN ('ARMED', 'EXIT_ONLY', 'BLOCK_ALL')",
            name="ck_order_intents_prepared_control_mode",
        ),
        CheckConstraint(
            "control_mode IS NULL OR control_mode IN ('ARMED', 'EXIT_ONLY')",
            name="ck_order_intents_control_mode",
        ),
        CheckConstraint(
            "(prepared_control_generation IS NULL AND prepared_control_mode IS NULL) OR "
            "(prepared_control_generation IS NOT NULL AND prepared_control_mode IS NOT NULL)",
            name="ck_order_intents_prepared_control_snapshot",
        ),
        CheckConstraint(
            "(control_generation IS NULL AND control_mode IS NULL AND "
            "control_event_id IS NULL AND submission_authorized_at IS NULL) OR "
            "(control_generation IS NOT NULL AND control_mode IS NOT NULL AND "
            "control_event_id IS NOT NULL AND submission_authorized_at IS NOT NULL)",
            name="ck_order_intents_submission_authorization_snapshot",
        ),
        UniqueConstraint("intent_key", name="uq_order_intents_intent_key"),
        UniqueConstraint("identifier", name="uq_order_intents_identifier"),
        UniqueConstraint(
            "broker",
            "exchange_uuid",
            name="uq_order_intents_broker_exchange_uuid",
        ),
        Index(
            "uq_order_intents_blocking_market",
            "broker",
            "account_scope",
            "market",
            unique=True,
            postgresql_where=text(ORDER_INTENT_BLOCKING_PREDICATE),
        ),
        Index(
            "uq_order_intents_blocking_bid_account",
            "broker",
            "account_scope",
            unique=True,
            postgresql_where=text(f"side = 'bid' AND ({ORDER_INTENT_BLOCKING_PREDICATE})"),
        ),
        Index(
            "ix_order_intents_reconcile_due",
            "submission_status",
            "next_reconcile_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intent_key: Mapped[str] = mapped_column(String(64), nullable=False)
    identifier: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    ai_analysis_log_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "ai_analysis_logs.id",
            name="fk_order_intents_ai_analysis_log_id_ai_analysis_logs",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    liquidation_operation_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "liquidation_operations.id",
            name="fk_order_intents_liquidation_operation_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )
    order_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_policy: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="GENERAL",
        server_default="GENERAL",
    )
    broker: Mapped[str] = mapped_column(String(32), nullable=False)
    account_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    ord_type: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    requested_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    submission_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="PREPARED",
        server_default="PREPARED",
    )
    exchange_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exchange_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    executed_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    executed_funds: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    average_fill_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    remaining_volume: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    paid_fee: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    projection_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    post_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    reconcile_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    prepared_control_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prepared_control_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    control_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    control_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    control_event_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "live_order_control_events.id",
            name="fk_order_intents_control_event_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    submission_authorized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_reconcile_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reconcile_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    not_found_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    first_not_found_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_not_found_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unknown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    projected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    surface: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AIChatMessage(Base):
    __tablename__ = "ai_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    agent_name: Mapped[str | None] = mapped_column(String, nullable=True)
    is_tool_call: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("symbol", name="uq_favorites_symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    broker: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    total_net_worth: Mapped[float] = mapped_column(Float, nullable=False)
    total_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    snapshot_data: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
