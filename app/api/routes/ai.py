from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.domain import AIAnalysisLog, Asset, OrderHistory, Position
from app.models.schemas import AIAnalysisLogItem, AIPerformanceSummary, AITradeRecord
from app.services.ai.analyzer import AIAnalyzerFactory
from app.services.ai.formatter import format_portfolio_for_llm
from app.services.portfolio.aggregator import PortfolioService
from app.services.trading.ai_analyst import execute_ai_analysis

router = APIRouter()


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _normalize_order_side(side: str) -> str | None:
    normalized = str(side or "").strip().lower()
    if normalized in {"buy", "bid"}:
        return "BUY"
    if normalized in {"sell", "ask"}:
        return "SELL"
    return None


def _build_recent_trade(order: OrderHistory, asset: Asset, analysis: AIAnalysisLog) -> AITradeRecord | None:
    normalized_side = _normalize_order_side(order.side)
    if normalized_side is None:
        return None

    return AITradeRecord(
        symbol=asset.symbol,
        side=normalized_side,
        price=order.price,
        qty=order.qty,
        confidence=analysis.confidence,
        decision=analysis.decision,
        executed_at=order.executed_at,
    )


@router.get("/analyze")
async def analyze_portfolio(provider: str = "openai", db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    portfolio = await PortfolioService(db).get_aggregated_portfolio()
    portfolio_str = format_portfolio_for_llm(portfolio)
    resolved_provider = (provider or "openai").strip().lower()
    if resolved_provider not in {"openai", "gemini"}:
        resolved_provider = "openai"

    analyzer = AIAnalyzerFactory.get_analyzer(resolved_provider)
    report = await analyzer.generate_report(portfolio_str)
    return {"provider": resolved_provider, "report": report}


@router.get("/latest-analysis", response_model=AIAnalysisLogItem | None)
async def get_latest_analysis(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> AIAnalysisLogItem | None:
    normalized_symbol = _normalize_symbol(symbol)
    if not normalized_symbol:
        raise HTTPException(status_code=400, detail="symbol query parameter is required")

    result = await db.execute(
        select(AIAnalysisLog)
        .where(AIAnalysisLog.symbol == normalized_symbol)
        .order_by(desc(AIAnalysisLog.created_at), desc(AIAnalysisLog.id))
        .limit(1)
    )
    latest_analysis = result.scalar_one_or_none()
    if latest_analysis is None:
        return None

    return AIAnalysisLogItem.model_validate(latest_analysis)


@router.get("/performance", response_model=AIPerformanceSummary)
async def get_ai_performance_summary(
    db: AsyncSession = Depends(get_db),
) -> AIPerformanceSummary:
    history_stmt = (
        select(OrderHistory, Position, Asset, AIAnalysisLog)
        .join(Position, Position.id == OrderHistory.position_id)
        .join(Asset, Asset.id == Position.asset_id)
        .join(AIAnalysisLog, AIAnalysisLog.id == OrderHistory.ai_analysis_log_id)
        .where(OrderHistory.ai_analysis_log_id.is_not(None))
        .order_by(Position.id.asc(), OrderHistory.executed_at.asc(), OrderHistory.id.asc())
    )
    history_result = await db.execute(history_stmt)

    total_realized_pnl_krw = 0.0
    winning_trades = 0
    losing_trades = 0
    total_confidence = 0.0
    confidence_count = 0
    position_states: dict[int, dict[str, float]] = {}

    for order, position, _asset, analysis in history_result.all():
        normalized_side = _normalize_order_side(order.side)
        if normalized_side is None or order.price <= 0 or order.qty <= 0:
            continue

        total_confidence += float(analysis.confidence)
        confidence_count += 1

        state = position_states.setdefault(
            position.id,
            {
                "open_qty": 0.0,
                "open_cost": 0.0,
            },
        )

        if normalized_side == "BUY":
            state["open_qty"] += order.qty
            state["open_cost"] += order.qty * order.price
            continue

        if state["open_qty"] <= 0:
            continue

        matched_qty = min(order.qty, state["open_qty"])
        if matched_qty <= 0:
            continue

        avg_cost = state["open_cost"] / state["open_qty"] if state["open_qty"] > 0 else 0.0
        realized_cost = avg_cost * matched_qty
        realized_proceeds = matched_qty * order.price
        realized_pnl = realized_proceeds - realized_cost

        total_realized_pnl_krw += realized_pnl
        if realized_pnl > 0:
            winning_trades += 1
        else:
            losing_trades += 1

        state["open_qty"] -= matched_qty
        state["open_cost"] -= realized_cost
        if state["open_qty"] <= 1e-12:
            state["open_qty"] = 0.0
            state["open_cost"] = 0.0

    recent_stmt = (
        select(OrderHistory, Position, Asset, AIAnalysisLog)
        .join(Position, Position.id == OrderHistory.position_id)
        .join(Asset, Asset.id == Position.asset_id)
        .join(AIAnalysisLog, AIAnalysisLog.id == OrderHistory.ai_analysis_log_id)
        .where(OrderHistory.ai_analysis_log_id.is_not(None))
        .order_by(desc(OrderHistory.executed_at), desc(OrderHistory.id))
        .limit(20)
    )
    recent_result = await db.execute(recent_stmt)

    recent_trades: list[AITradeRecord] = []
    for order, _position, asset, analysis in recent_result.all():
        trade_record = _build_recent_trade(order, asset, analysis)
        if trade_record is not None:
            recent_trades.append(trade_record)

    total_trades = winning_trades + losing_trades
    win_rate = (winning_trades / total_trades) * 100.0 if total_trades > 0 else 0.0
    avg_confidence = (total_confidence / confidence_count) if confidence_count > 0 else 0.0

    return AIPerformanceSummary(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        total_realized_pnl_krw=total_realized_pnl_krw,
        avg_confidence=avg_confidence,
        recent_trades=recent_trades,
    )


@router.get("/test-analysis")
async def trigger_ai_analysis_now(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | int]:
    normalized_symbol = symbol.upper().strip()
    try:
        result = await execute_ai_analysis(db, normalized_symbol)
        return {
            "symbol": normalized_symbol,
            "decision": result.decision,
            "confidence": result.confidence,
            "recommended_weight": result.recommended_weight,
            "reasoning": result.reasoning,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
