import logging
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.backtesting.analyzer import analyze_backtest_result
from app.services.backtesting.engine import BacktestEngine

logger = logging.getLogger(__name__)
router = APIRouter()


class BacktestRunRequest(BaseModel):
    market: str = Field(..., examples=["KRW-DOGE"])
    start_date: datetime
    end_date: datetime
    timeframe: str = "60m"
    initial_balance: float = 1_000_000.0
    grid_upper_bound: float | None = None
    grid_lower_bound: float | None = None
    grid_upper: float | None = None
    grid_lower: float | None = None
    grid_order_krw: float = 10_000.0
    grid_sell_pct: float = 100.0
    grid_cooldown_seconds: int = 60

    def resolved_upper_bound(self) -> float:
        if self.grid_upper_bound is not None:
            return float(self.grid_upper_bound)
        if self.grid_upper is not None:
            return float(self.grid_upper)
        return 100_000_000.0

    def resolved_lower_bound(self) -> float:
        if self.grid_lower_bound is not None:
            return float(self.grid_lower_bound)
        if self.grid_lower is not None:
            return float(self.grid_lower)
        return 80_000_000.0


class BacktestSummaryResponse(BaseModel):
    total_return_pct: float
    max_drawdown_pct: float
    win_rate: float
    number_of_trades: int


class BacktestCandleResponse(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class BacktestMarkerResponse(BaseModel):
    time: int
    position: str
    shape: str
    color: str
    text: str
    side: str
    price: float
    qty: float


class BacktestTradeResponse(BaseModel):
    index: int
    timestamp: str
    side: str
    price: float
    qty: float
    fee: float
    krw_balance: float
    coin_balance: float


class BacktestMetaResponse(BaseModel):
    market: str
    timeframe: str
    start_date: str
    end_date: str
    bars_processed: int
    last_timestamp: str
    initial_balance: float
    final_balance: float
    position_qty: float


class BacktestRunResponse(BaseModel):
    summary: BacktestSummaryResponse
    candles: list[BacktestCandleResponse]
    markers: list[BacktestMarkerResponse]
    trades: list[BacktestTradeResponse]
    meta: BacktestMetaResponse


@router.post("/run", response_model=BacktestRunResponse)
async def run_backtest(payload: BacktestRunRequest) -> BacktestRunResponse:
    engine = BacktestEngine()
    try:
        result = await engine.run(
            market=payload.market,
            start_date=payload.start_date,
            end_date=payload.end_date,
            timeframe=payload.timeframe,
            initial_balance=payload.initial_balance,
            grid_upper_bound=payload.resolved_upper_bound(),
            grid_lower_bound=payload.resolved_lower_bound(),
            grid_order_krw=payload.grid_order_krw,
            grid_sell_pct=payload.grid_sell_pct,
            grid_cooldown_seconds=payload.grid_cooldown_seconds,
        )
        analyzed = analyze_backtest_result(result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"백테스트 데이터 조회 실패: {exc}") from exc
    except Exception as exc:
        logger.exception("백테스트 실행 중 예외가 발생했습니다.")
        raise HTTPException(status_code=500, detail="백테스트 실행 중 서버 오류가 발생했습니다.") from exc

    return BacktestRunResponse(
        summary=BacktestSummaryResponse(**_as_dict(analyzed.get("summary"))),
        candles=[BacktestCandleResponse(**item) for item in _as_list(analyzed.get("candles"))],
        markers=[BacktestMarkerResponse(**item) for item in _as_list(analyzed.get("markers"))],
        trades=[BacktestTradeResponse(**item) for item in _as_list(analyzed.get("trades"))],
        meta=BacktestMetaResponse(**_as_dict(analyzed.get("meta"))),
    )


def _as_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}
