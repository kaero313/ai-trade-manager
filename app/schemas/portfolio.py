from pydantic import BaseModel, Field


class AssetItem(BaseModel):
    broker: str = Field(...)
    currency: str = Field(...)
    balance: float = Field(...)
    locked: float = Field(...)
    avg_buy_price: float = Field(...)
    current_price: float = Field(...)
    total_value: float = Field(...)
    pnl_percentage: float = Field(...)


class PortfolioSummary(BaseModel):
    total_net_worth: float = Field(...)
    total_pnl: float = Field(...)
    items: list[AssetItem] = Field(...)
