from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.domain import ChatSessionSurface


class StrategyParams(BaseModel):
    ema_fast: int = 12
    ema_slow: int = 26
    rsi: int = 14
    rsi_min: int = 50
    trailing_stop_pct: float = 0.03


class RiskParams(BaseModel):
    max_capital_pct: float = 0.10
    max_daily_loss_pct: float = 0.05
    position_size_pct: float = 0.20
    max_concurrent_positions: int = 3
    cooldown_minutes: int = 60


class ScheduleParams(BaseModel):
    enabled: bool = True
    start_hour: int | None = None
    end_hour: int | None = None


class BotConfig(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["KRW-BTC"])
    allocation_pct_per_symbol: list[float] = Field(default_factory=lambda: [1.0])
    strategy: StrategyParams = StrategyParams()
    risk: RiskParams = RiskParams()
    schedule: ScheduleParams = ScheduleParams()
    trade_mode: str = "ai"


class LiveOrderGateStatus(BaseModel):
    mode: Literal["ARMED", "EXIT_ONLY", "BLOCK_ALL"] = "BLOCK_ALL"
    generation: int = Field(default=0, ge=0)
    version: int = Field(default=0, ge=0)
    reason_code: str = "ORDER_GATE_STATE_UNAVAILABLE"
    reason: str = "실주문 제어 상태를 확인할 수 없어 안전하게 차단했습니다."
    source: str = "SYSTEM"
    changed_at: datetime | None = None
    active_liquidation_operation_id: int | None = Field(default=None, ge=1)
    rollout_enabled: bool = False
    state_available: bool = False

    model_config = ConfigDict(extra="forbid")


class BotStatus(BaseModel):
    running: bool
    last_heartbeat: str | None = None
    last_error: str | None = None
    latest_action: str | None = None
    live_order_mode: Literal["ARMED", "EXIT_ONLY", "BLOCK_ALL"] = "BLOCK_ALL"
    live_order_generation: int = Field(default=0, ge=0)
    live_order_version: int = Field(default=0, ge=0)
    live_order_reason_code: str = "ORDER_GATE_STATE_UNAVAILABLE"
    live_order_reason: str = "실주문 제어 상태를 확인할 수 없어 안전하게 차단했습니다."
    live_order_source: str = "SYSTEM"
    live_order_changed_at: datetime | None = None
    live_order_active_liquidation_operation_id: int | None = Field(default=None, ge=1)
    live_order_liquidation_status: str | None = None
    live_order_liquidation_phase: str | None = None
    live_order_liquidation_remaining: int | None = Field(default=None, ge=0)
    live_order_rollout_enabled: bool = False
    live_order_state_available: bool = False
    trading_mode: Literal["paper", "live"] = "paper"
    trading_mode_version: int = Field(default=0, ge=0)
    trading_mode_reason_code: str = "TRADING_MODE_STATE_UNAVAILABLE"
    trading_mode_reason: str = "거래 모드 상태를 확인할 수 없어 paper로 표시합니다."
    trading_mode_source: str = "SYSTEM"
    trading_mode_actor_ref: str | None = None
    trading_mode_changed_at: datetime | None = None
    trading_mode_state_available: bool = False
    trading_mode_unavailable_reason: str | None = None
    trading_mode_mirror_consistent: bool = False

    model_config = ConfigDict(extra="forbid")


class ArmLiveOrderGateRequest(BaseModel):
    expected_generation: int = Field(..., ge=1)
    expected_version: int = Field(..., ge=1)
    reason: str = Field(..., min_length=10, max_length=1000)
    confirmation: Literal["ENABLE_LIVE_ORDERS"]

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if len(normalized) < 10:
            raise ValueError("실주문 제어 사유는 공백을 제외하고 10자 이상이어야 합니다.")
        return normalized

    model_config = ConfigDict(extra="forbid")


class BlockLiveOrderGateRequest(BaseModel):
    reason: str = Field(..., min_length=10, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if len(normalized) < 10:
            raise ValueError("실주문 제어 사유는 공백을 제외하고 10자 이상이어야 합니다.")
        return normalized

    model_config = ConfigDict(extra="forbid")


class TradingModeStatus(BaseModel):
    mode: Literal["paper", "live"] = "paper"
    version: int = Field(default=0, ge=0)
    reason_code: str = "TRADING_MODE_STATE_UNAVAILABLE"
    reason: str = "거래 모드 상태를 확인할 수 없어 paper로 표시합니다."
    source: str = "SYSTEM"
    actor_ref: str | None = None
    changed_at: datetime | None = None
    state_available: bool = False
    unavailable_reason: str | None = None
    mirror_consistent: bool = False

    model_config = ConfigDict(extra="forbid")


class EnableLiveTradingModeRequest(BaseModel):
    expected_version: int = Field(..., ge=1)
    expected_gate_generation: int = Field(..., ge=1)
    expected_gate_version: int = Field(..., ge=1)
    reason: str = Field(..., min_length=10, max_length=1000)
    confirmation: Literal["ENABLE_LIVE_TRADING"]
    reauth_proof: str = Field(..., min_length=1, max_length=4096)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if len(normalized) < 10:
            raise ValueError("거래 모드 전환 사유는 공백을 제외하고 10자 이상이어야 합니다.")
        return normalized

    model_config = ConfigDict(extra="forbid")


class EnablePaperTradingModeRequest(BaseModel):
    expected_version: int = Field(..., ge=1)
    reason: str = Field(..., min_length=10, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if len(normalized) < 10:
            raise ValueError("거래 모드 전환 사유는 공백을 제외하고 10자 이상이어야 합니다.")
        return normalized

    model_config = ConfigDict(extra="forbid")


class AdminReauthRequest(BaseModel):
    purpose: Literal["ENABLE_LIVE_TRADING"]

    model_config = ConfigDict(extra="forbid")


class AdminReauthResponse(BaseModel):
    reauth_proof: str
    expires_at: datetime

    model_config = ConfigDict(extra="forbid")


class LiquidateAllRequest(BaseModel):
    scope: Literal["ACCOUNT_ALL"]
    confirmation: Literal["CANCEL_OPEN_ORDERS_AND_LIQUIDATE_ALL"]

    model_config = ConfigDict(extra="forbid")


class AIAnalysisResponse(BaseModel):
    decision: Literal["BUY", "SELL", "HOLD"]
    confidence: int = Field(..., ge=0, le=100)
    recommended_weight: int = Field(..., ge=0, le=100)
    reasoning: str


class AIAnalysisLogItem(BaseModel):
    id: int
    symbol: str
    decision: Literal["BUY", "SELL", "HOLD"]
    confidence: int
    recommended_weight: int
    reasoning: str
    accuracy_label: str | None = None
    actual_price_diff_pct: float | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AIManualCycleRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    confirm_trade_execution: bool = False


class AIManualCycleResponse(BaseModel):
    symbol: str
    analysis: AIAnalysisLogItem
    trade_evaluated: bool
    order_created: bool
    order_id: int | None = None
    order_intent_id: int | None = None
    order_side: Literal["BUY", "SELL"] | None = None
    submission_status: str | None = None
    exchange_state: str | None = None
    message: str
    started_at: datetime
    finished_at: datetime

    model_config = ConfigDict(extra="forbid")


class OrderIntentStatusItem(BaseModel):
    id: int
    intent_key: str
    identifier: str
    source_type: str
    source_ref: str
    market: str
    side: str
    ord_type: str
    requested_price: Decimal | None = None
    requested_volume: Decimal | None = None
    submission_status: str
    exchange_uuid: str | None = None
    exchange_state: str | None = None
    projection_status: str
    executed_volume: Decimal | None = None
    average_fill_price: Decimal | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    reconcile_attempt_count: int
    not_found_count: int
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None = None
    unknown_at: datetime | None = None
    last_checked_at: datetime | None = None
    first_not_found_at: datetime | None = None
    last_not_found_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ResolveNoOrderRequest(BaseModel):
    exchange_ui_verified: Literal[True]
    resolution_note: str = Field(..., min_length=10, max_length=1000)

    @field_validator("resolution_note")
    @classmethod
    def validate_resolution_note(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 10:
            raise ValueError("확인 사유는 공백을 제외하고 10자 이상이어야 합니다.")
        return normalized


class LiquidationIntentItem(BaseModel):
    market: str
    currency: str | None = None
    intent_id: int | None = None
    identifier: str | None = None
    exchange_uuid: str | None = None
    submission_status: str | None = None
    exchange_state: str | None = None
    projection_status: str | None = None
    executed_volume: Decimal | None = None
    remaining_volume: Decimal | None = None
    requested_volume: Decimal | None = None
    initial_balance: Decimal | None = None
    initial_locked: Decimal | None = None
    post_cancel_balance: Decimal | None = None
    post_cancel_locked: Decimal | None = None
    final_balance: Decimal | None = None
    final_locked: Decimal | None = None
    estimated_value_krw: Decimal | None = None
    result_code: Literal[
        "LIQUIDATED",
        "DUST_REMAINING",
        "LOCKED_REMAINING",
        "UNSUPPORTED_MARKET",
        "ORDER_FAILED",
        "VERIFY_FAILED",
        "LEDGER_MISMATCH",
    ] | None = None
    error_code: str | None = None
    error_message: str | None = None

    model_config = ConfigDict(extra="forbid")


class LiquidationOperationSummary(BaseModel):
    discovered_orders: int = Field(default=0, ge=0)
    cancel_confirmed: int = Field(default=0, ge=0)
    cancel_unknown: int = Field(default=0, ge=0)
    attempted: int = Field(default=0, ge=0)
    succeeded: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    remaining: int = Field(default=0, ge=0)

    model_config = ConfigDict(extra="forbid")


class LiquidationCancellationItem(BaseModel):
    exchange_uuid: str
    identifier: str | None = None
    market: str | None = None
    side: str | None = None
    ownership: Literal["MANAGED", "EXTERNAL"]
    status: Literal["DISCOVERED", "CANCELING", "UNKNOWN", "CONFIRMED", "FAILED"]
    attempt_count: int = Field(default=0, ge=0)
    executed_volume: Decimal | None = None
    remaining_volume: Decimal | None = None
    error_code: str | None = None
    error_message: str | None = None

    model_config = ConfigDict(extra="forbid")


class LiquidationOperationResponse(BaseModel):
    id: int
    idempotency_key: str
    contract_version: int = Field(default=1, ge=1)
    cancel_scope: Literal["ACCOUNT_ALL", "LEGACY_NONE"] = "LEGACY_NONE"
    phase: Literal[
        "BLOCKING",
        "DISCOVERING_ORDERS",
        "CANCELING_ORDERS",
        "RECONCILING_CANCELED_ORDERS",
        "SNAPSHOTTING_TARGETS",
        "SUBMITTING",
        "WAITING_FILLS",
        "VERIFYING",
        "TERMINAL",
    ] = "TERMINAL"
    verification_status: Literal[
        "PENDING",
        "VERIFIED",
        "ERROR",
        "LEGACY_UNVERIFIED",
    ] = "LEGACY_UNVERIFIED"
    status: Literal[
        "PREPARING",
        "IN_PROGRESS",
        "COMPLETED",
        "PARTIAL",
        "FAILED",
        "NO_ASSETS",
    ]
    summary: LiquidationOperationSummary = Field(default_factory=LiquidationOperationSummary)
    cancellations: list[LiquidationCancellationItem] = Field(default_factory=list)
    items: list[LiquidationIntentItem] = Field(default_factory=list)
    initial_accounts_observed_at: datetime | None = None
    post_cancel_accounts_observed_at: datetime | None = None
    final_accounts_observed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class AITradeRecord(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    price: float = Field(..., gt=0)
    qty: float = Field(..., gt=0)
    confidence: int = Field(..., ge=0, le=100)
    decision: Literal["BUY", "SELL", "HOLD"]
    executed_at: datetime

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class AIPerformanceSummary(BaseModel):
    total_trades: int = Field(..., ge=0)
    winning_trades: int = Field(..., ge=0)
    losing_trades: int = Field(..., ge=0)
    win_rate: float = Field(..., ge=0, le=100)
    accuracy_rate: float = Field(..., ge=0, le=100)
    total_realized_pnl_krw: float
    avg_confidence: float = Field(..., ge=0, le=100)
    recent_trades: list[AITradeRecord] = Field(default_factory=list, max_length=20)

    model_config = ConfigDict(extra="forbid")


class MarketSentimentSnapshot(BaseModel):
    score: int = Field(..., ge=0, le=100)
    classification: str = Field(...)
    updated_at: datetime = Field(...)


class SystemConfigItem(BaseModel):
    id: int = Field(...)
    config_key: str = Field(...)
    config_value: str = Field(...)
    description: str | None = Field(default=None)
    version: int = Field(..., ge=1)

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class SystemConfigUpdateItem(BaseModel):
    config_key: str = Field(..., min_length=1)
    config_value: str = Field(...)
    expected_version: int = Field(..., ge=1, strict=True)

    model_config = ConfigDict(extra="forbid")


class AIProviderStatusResetRequest(BaseModel):
    expected_version: int = Field(..., ge=1, strict=True)

    model_config = ConfigDict(extra="forbid")


class AIProviderRuntimeStatusItem(BaseModel):
    provider: Literal["gemini", "openai"]
    rank: int = Field(..., ge=1)
    enabled: bool
    model: str
    models: dict[str, str] = Field(default_factory=dict)
    api_key_configured: bool
    status: Literal[
        "active",
        "fallback_ready",
        "ready",
        "blocked",
        "disabled",
        "missing_key",
        "error",
    ]
    is_candidate: bool
    skip_reason: str | None = None
    blocked_until: str | None = None
    reason: str | None = None
    last_error_at: str | None = None
    last_error: str | None = None
    last_success_at: str | None = None


class AIProviderRuntimeStatusResponse(BaseModel):
    generated_at: str
    active_provider: Literal["gemini", "openai"] | None = None
    providers: list[AIProviderRuntimeStatusItem]


class ChatSessionCreateRequest(BaseModel):
    surface: ChatSessionSurface = ChatSessionSurface.AI_BANKER


class ChatSessionCreateResponse(BaseModel):
    session_id: str = Field(..., min_length=1)


class ChatSessionItem(BaseModel):
    session_id: str = Field(..., min_length=1)
    created_at: datetime
    content_preview: str = Field(default="")


class ChatMessageCreateRequest(BaseModel):
    content: str = Field(..., min_length=1)


class ChatMessageItem(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    agent_name: str | None = None
    is_tool_call: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatApproveRequest(BaseModel):
    config_key: str = Field(..., min_length=1)
    config_value: str = Field(...)
    expected_version: int = Field(..., ge=1, strict=True)

    model_config = ConfigDict(extra="forbid")


class ReviewerDecision(BaseModel):
    is_passed: bool = Field(..., description="통과 여부")
    feedback: str = Field(..., description="반려 시 개선을 위한 상세 피드백 또는 통과 시 'OK'")


class PortfolioSnapshotItem(BaseModel):
    id: int
    total_net_worth: float
    total_pnl: float
    snapshot_data: list[dict]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PortfolioSnapshotListResponse(BaseModel):
    snapshots: list[PortfolioSnapshotItem]
