import logging
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.ai.provider_router import AIProviderRouter
from app.services.backtesting.analyzer import analyze_backtest_result
from app.services.backtesting.engine import AIPolicyBacktestEngine

logger = logging.getLogger(__name__)
router = APIRouter()


class BacktestStrategyRequest(BaseModel):
    ema_fast: int = Field(default=12, ge=2, le=250)
    ema_slow: int = Field(default=26, ge=3, le=400)
    rsi_period: int = Field(default=14, ge=2, le=100)
    rsi_min: int = Field(default=45, ge=1, le=99)
    trailing_stop_pct: float = Field(default=0.03, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_ema_order(self) -> "BacktestStrategyRequest":
        if self.ema_fast >= self.ema_slow:
            raise ValueError("ema_fast must be smaller than ema_slow")
        return self


class BacktestPolicyRequest(BaseModel):
    min_confidence: int = Field(default=85, ge=0, le=100)
    max_allocation_pct: float = Field(default=30.0, ge=0.0, le=100.0)
    take_profit_pct: float = Field(default=5.0, ge=0.0, le=1000.0)
    stop_loss_pct: float = Field(default=-3.0, ge=-100.0, le=0.0)
    cooldown_minutes: int = Field(default=60, ge=0, le=24 * 60)


class BacktestRunRequest(BaseModel):
    market: str = Field(..., examples=["KRW-BTC"])
    start_date: datetime
    end_date: datetime
    timeframe: str = "60m"
    initial_balance: float = 1_000_000.0
    strategy: BacktestStrategyRequest = Field(default_factory=BacktestStrategyRequest)
    policy: BacktestPolicyRequest = Field(default_factory=BacktestPolicyRequest)


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
    sma_5: float | None = None
    sma_20: float | None = None
    sma_60: float | None = None
    ema_50: float | None = None
    ema_200: float | None = None
    bb_upper_20_2: float | None = None
    bb_middle_20_2: float | None = None
    bb_lower_20_2: float | None = None
    rsi_14: float | None = None


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
    reason: str | None = None
    confidence: int | None = None
    recommended_weight: int | None = None


class BacktestEquityPointResponse(BaseModel):
    time: int
    equity: float
    pnl_pct: float


class BacktestDrawdownPointResponse(BaseModel):
    time: int
    drawdown_pct: float


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


class BacktestAiBriefingResponse(BaseModel):
    content: str
    provider: str | None = None
    model: str | None = None
    fallback: bool = False


class BacktestRunResponse(BaseModel):
    summary: BacktestSummaryResponse
    candles: list[BacktestCandleResponse]
    markers: list[BacktestMarkerResponse]
    trades: list[BacktestTradeResponse]
    equity_curve: list[BacktestEquityPointResponse]
    drawdown_curve: list[BacktestDrawdownPointResponse]
    meta: BacktestMetaResponse
    ai_briefing: BacktestAiBriefingResponse


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalize_briefing_text(report: str) -> str:
    lines = []
    for raw_line in str(report or "").splitlines():
        line = raw_line.strip().lstrip("#").strip()
        if line:
            lines.append(line)
    normalized = "\n".join(lines).strip()
    return normalized[:1_200] if normalized else _build_local_ai_briefing({})


def _build_backtest_ai_prompt(analyzed: dict[str, Any]) -> str:
    summary = _as_dict(analyzed.get("summary"))
    meta = _as_dict(analyzed.get("meta"))
    trades = _as_list(analyzed.get("trades"))
    policy = _as_dict(analyzed.get("policy"))
    strategy = _as_dict(analyzed.get("strategy"))
    recent_trades = trades[-5:]
    trade_lines = [
        (
            f"- {trade.get('timestamp')}: {str(trade.get('side')).upper()} "
            f"{_format_number(trade.get('qty'), 8)} @ "
            f"{_format_number(trade.get('price'), 0)} "
            f"reason={trade.get('reason') or '-'} confidence={trade.get('confidence') or '-'}"
        )
        for trade in recent_trades
        if isinstance(trade, dict)
    ]
    trades_text = "\n".join(trade_lines) if trade_lines else "- 거래 없음"

    return (
        "다음은 AI 매매 정책 백테스트 결과입니다. 투자 조언이 아니라 전략 검증 의견으로 "
        "짧고 실무적으로 요약하세요. 반드시 한국어로 작성하고 4문장 이내로 답하세요.\n\n"
        f"# 대상\n- 시장: {meta.get('market')}\n"
        f"- 기간: {meta.get('start_date')} ~ {meta.get('end_date')}\n"
        f"- 타임프레임: {meta.get('timeframe')}\n\n"
        "# 성과\n"
        f"- 총 수익률: {_format_number(summary.get('total_return_pct'), 2)}%\n"
        f"- 최대 낙폭: {_format_number(summary.get('max_drawdown_pct'), 2)}%\n"
        f"- 승률: {_format_number(summary.get('win_rate'), 2)}%\n"
        f"- 거래 수: {summary.get('number_of_trades')}\n"
        f"- 최종 자산: {_format_number(meta.get('final_balance'), 0)} KRW\n\n"
        f"# 전략\n- {strategy}\n\n"
        f"# 정책\n- {policy}\n\n"
        f"# 최근 거래\n{trades_text}"
    )


def _build_local_ai_briefing(analyzed: dict[str, Any]) -> str:
    summary = _as_dict(analyzed.get("summary"))
    meta = _as_dict(analyzed.get("meta"))
    total_return = _to_float(summary.get("total_return_pct"))
    max_drawdown = _to_float(summary.get("max_drawdown_pct"))
    trade_count = int(summary.get("number_of_trades") or 0)

    if total_return > 0 and max_drawdown <= 10:
        verdict = "수익성과 낙폭이 비교적 균형적입니다."
    elif total_return > 0:
        verdict = "수익은 났지만 낙폭 관리가 핵심 리스크입니다."
    else:
        verdict = "현재 파라미터에서는 방어적 재조정이 필요합니다."

    if trade_count == 0:
        action = "신호가 거의 발생하지 않았으므로 최소 신뢰도나 RSI 기준을 낮춰 재검증하세요."
    elif max_drawdown > 15:
        action = "손절선과 최대 비중을 낮춰 낙폭을 먼저 줄이는 편이 좋습니다."
    else:
        action = "기간을 넓히고 다른 종목에서도 같은 정책이 유지되는지 비교하세요."

    return (
        f"{meta.get('market') or '선택 종목'} 백테스트 결과 총 수익률은 "
        f"{total_return:+.2f}%, 최대 낙폭은 {max_drawdown:.2f}%입니다. "
        f"{verdict} {action}"
    )


async def _build_ai_briefing(
    db: AsyncSession,
    analyzed: dict[str, Any],
) -> BacktestAiBriefingResponse:
    try:
        result = await AIProviderRouter(db).generate_report(_build_backtest_ai_prompt(analyzed))
        return BacktestAiBriefingResponse(
            content=_normalize_briefing_text(result.value),
            provider=result.provider,
            model=result.model,
            fallback=False,
        )
    except Exception as exc:
        logger.warning("Backtest AI briefing failed. Using local fallback: %s", exc, exc_info=True)
        return BacktestAiBriefingResponse(
            content=_build_local_ai_briefing(analyzed),
            fallback=True,
        )


def _format_number(value: Any, digits: int) -> str:
    number = _to_float(value)
    return f"{number:,.{digits}f}"


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@router.post("/run", response_model=BacktestRunResponse)
async def run_backtest(
    payload: BacktestRunRequest,
    db: AsyncSession = Depends(get_db),
) -> BacktestRunResponse:
    engine = AIPolicyBacktestEngine()

    try:
        result = await engine.run(
            market=payload.market,
            start_date=payload.start_date,
            end_date=payload.end_date,
            timeframe=payload.timeframe,
            initial_balance=payload.initial_balance,
            strategy=payload.strategy.model_dump(),
            policy=payload.policy.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.exception("AI policy backtest upstream request failed.")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("AI policy backtest failed.")
        raise HTTPException(status_code=500, detail="백테스트 실행 중 오류가 발생했습니다.") from exc

    analyzed = analyze_backtest_result(result)
    ai_briefing = await _build_ai_briefing(db, analyzed)

    return BacktestRunResponse(
        summary=BacktestSummaryResponse(**_as_dict(analyzed.get("summary"))),
        candles=[BacktestCandleResponse(**item) for item in _as_list(analyzed.get("candles"))],
        markers=[BacktestMarkerResponse(**item) for item in _as_list(analyzed.get("markers"))],
        trades=[BacktestTradeResponse(**item) for item in _as_list(analyzed.get("trades"))],
        equity_curve=[
            BacktestEquityPointResponse(**item)
            for item in _as_list(analyzed.get("equity_curve"))
        ],
        drawdown_curve=[
            BacktestDrawdownPointResponse(**item)
            for item in _as_list(analyzed.get("drawdown_curve"))
        ],
        meta=BacktestMetaResponse(**_as_dict(analyzed.get("meta"))),
        ai_briefing=ai_briefing,
    )
