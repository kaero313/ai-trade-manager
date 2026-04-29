from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class BotStatus(BaseModel):
    running: bool
    last_heartbeat: str | None = None
    last_error: str | None = None
    latest_action: str | None = None


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


class SystemConfigUpdateItem(BaseModel):
    config_key: str = Field(..., min_length=1)
    config_value: str = Field(...)


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
