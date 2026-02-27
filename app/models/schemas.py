from pydantic import BaseModel, Field


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


class GridParams(BaseModel):
    target_coin: str = "BTC"
    grid_upper_bound: float = 100000000.0
    grid_lower_bound: float = 80000000.0
    grid_order_krw: float = 10000.0
    grid_sell_pct: float = 100.0
    grid_cooldown_seconds: int = 60
    trade_mode: str = "grid"


class BotConfig(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["KRW-BTC"])
    allocation_pct_per_symbol: list[float] = Field(default_factory=lambda: [1.0])
    strategy: StrategyParams = StrategyParams()
    risk: RiskParams = RiskParams()
    schedule: ScheduleParams = ScheduleParams()
    grid: GridParams = Field(default_factory=GridParams)


class BotStatus(BaseModel):
    running: bool
    last_heartbeat: str | None = None
    last_error: str | None = None
