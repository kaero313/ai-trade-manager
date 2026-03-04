from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FavoriteCreateRequest(BaseModel):
    symbol: str = Field(..., min_length=1)
    broker: str = Field(..., min_length=1)


class FavoriteResponse(BaseModel):
    id: int
    symbol: str
    broker: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
