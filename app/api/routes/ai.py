from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.dependencies import require_admin_token
from app.db.session import get_db
from app.models.domain import AIAnalysisLog, Asset, OrderHistory, Position
from app.models.schemas import AIAnalysisLogItem
from app.models.schemas import AIManualCycleRequest
from app.models.schemas import AIManualCycleResponse
from app.models.schemas import AIPerformanceSummary
from app.models.schemas import AITradeRecord
from app.services.bot_service import get_live_order_gate_status
from app.services.ai.formatter import format_portfolio_for_llm
from app.services.ai.provider_router import AIProviderRouter
from app.services.ai.providers.base import AIProviderRateLimitError
from app.services.portfolio.aggregator import PortfolioService
from app.services.trading.ai_analyst import execute_ai_analysis
from app.services.trading.ai_executor import RiskCheckResult
from app.services.trading.ai_executor import evaluate_new_buy_risk_health
from app.services.trading.ai_executor import execute_ai_trade
from app.services.trading.analysis_lineage import AI_ANALYSIS_STAGE_BUY_PRECHECK
from app.services.trading.analysis_lineage import AI_ANALYSIS_STAGE_LEGACY
from app.services.trading.analysis_lineage import AI_ANALYSIS_STAGE_TRADE
from app.services.trading.live_order_execution import LiveOrderResult
from app.services.trading.paper import get_trading_mode

router = APIRouter()

LEGACY_QUOTE_AMOUNT_BUY_CUTOFF = datetime(2026, 4, 30, 7, 0, tzinfo=UTC)
LEGACY_QUOTE_AMOUNT_MIN_KRW = 5000.0
LEGACY_QUOTE_AMOUNT_MAX_KRW = 100000.0
LEGACY_QUOTE_AMOUNT_QTY_TOLERANCE = 0.001


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _normalize_order_side(side: str) -> str | None:
    normalized = str(side or "").strip().lower()
    if normalized in {"buy", "bid"}:
        return "BUY"
    if normalized in {"sell", "ask"}:
        return "SELL"
    return None


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_probable_legacy_quote_amount_buy(order: OrderHistory) -> bool:
    if _normalize_order_side(order.side) != "BUY":
        return False
    if order.ai_analysis_log_id is None:
        return False
    if _normalize_datetime(order.executed_at) >= LEGACY_QUOTE_AMOUNT_BUY_CUTOFF:
        return False
    return (
        LEGACY_QUOTE_AMOUNT_MIN_KRW <= order.price <= LEGACY_QUOTE_AMOUNT_MAX_KRW
        and abs(order.qty - 1.0) <= LEGACY_QUOTE_AMOUNT_QTY_TOLERANCE
    )


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


async def _load_latest_analysis_log(db: AsyncSession, symbol: str) -> AIAnalysisLog | None:
    result = await db.execute(
        select(AIAnalysisLog)
        .where(AIAnalysisLog.symbol == _normalize_symbol(symbol))
        .where(
            AIAnalysisLog.stage.in_(
                (AI_ANALYSIS_STAGE_TRADE, AI_ANALYSIS_STAGE_LEGACY)
            )
        )
        .order_by(
            case((AIAnalysisLog.stage == AI_ANALYSIS_STAGE_TRADE, 0), else_=1),
            desc(AIAnalysisLog.created_at),
            desc(AIAnalysisLog.id),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _load_latest_order_for_analysis(
    db: AsyncSession,
    analysis_id: int,
) -> OrderHistory | None:
    linked_analysis = aliased(AIAnalysisLog, name="order_linked_analysis")
    result = await db.execute(
        select(OrderHistory)
        .join(
            linked_analysis,
            linked_analysis.id == OrderHistory.ai_analysis_log_id,
        )
        .where(
            or_(
                linked_analysis.id == analysis_id,
                and_(
                    linked_analysis.stage == AI_ANALYSIS_STAGE_BUY_PRECHECK,
                    linked_analysis.parent_analysis_id == analysis_id,
                ),
            )
        )
        .order_by(desc(OrderHistory.executed_at), desc(OrderHistory.id))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _live_order_message(result: LiveOrderResult) -> str:
    if result.error_code == "BLOCKING_INTENT":
        return "기존 미확정 주문이 있어 신규 주문을 전송하지 않았습니다."
    if result.submission_status == "ACCEPTED":
        if result.order_history_id is not None:
            return "실주문 체결이 확정되어 거래 이력에 반영되었습니다."
        return "실주문이 접수되었으며 거래소 체결 상태를 확인 중입니다."
    if result.submission_status in {"PREPARED", "SUBMITTING", "UNKNOWN"}:
        return "실주문 상태를 확인 중입니다. 중복 주문은 전송하지 않습니다."
    if result.submission_status == "REJECTED":
        suffix = f" ({result.error_code})" if result.error_code else ""
        return f"실주문이 거절되었습니다{suffix}."
    return "실주문이 종결되었으며 신규 체결 이력은 없습니다."


@router.get("/analyze")
async def analyze_portfolio(provider: str = "auto", db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    portfolio = await PortfolioService(db).get_aggregated_portfolio()
    portfolio_str = format_portfolio_for_llm(portfolio)
    requested_provider = (provider or "auto").strip().lower()
    preferred_provider = requested_provider if requested_provider in {"gemini", "openai"} else None

    result = await AIProviderRouter(db).generate_report(
        portfolio_str,
        preferred_provider=preferred_provider,
        purpose="portfolio_briefing",
    )
    return {"provider": result.provider, "model": result.model, "report": result.value}


@router.get("/latest-analysis", response_model=AIAnalysisLogItem | None)
async def get_latest_analysis(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> AIAnalysisLogItem | None:
    normalized_symbol = _normalize_symbol(symbol)
    if not normalized_symbol:
        raise HTTPException(status_code=400, detail="symbol query parameter is required")

    latest_analysis = await _load_latest_analysis_log(db, normalized_symbol)
    if latest_analysis is None:
        return None

    return AIAnalysisLogItem.model_validate(latest_analysis)


@router.post("/manual-cycle", response_model=AIManualCycleResponse)
async def run_manual_ai_cycle(
    request: AIManualCycleRequest,
    db: AsyncSession = Depends(get_db),
    _admin: None = Depends(require_admin_token),
) -> AIManualCycleResponse:
    normalized_symbol = _normalize_symbol(request.symbol)
    if not normalized_symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    started_at = datetime.now(UTC)
    try:
        analysis_log = await execute_ai_analysis(db, normalized_symbol)
    except AIProviderRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if analysis_log.id is None or _normalize_symbol(analysis_log.symbol) != normalized_symbol:
        raise HTTPException(status_code=500, detail="AI analysis log was not created")

    if request.confirm_trade_execution is not True:
        return AIManualCycleResponse(
            symbol=normalized_symbol,
            analysis=AIAnalysisLogItem.model_validate(analysis_log),
            trade_evaluated=False,
            order_created=False,
            order_id=None,
            order_intent_id=None,
            order_side=None,
            submission_status=None,
            exchange_state=None,
            message="AI 분석 완료, 실주문 평가는 요청하지 않음",
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )

    try:
        trading_mode = await get_trading_mode(db)
    except Exception:
        return AIManualCycleResponse(
            symbol=normalized_symbol,
            analysis=AIAnalysisLogItem.model_validate(analysis_log),
            trade_evaluated=False,
            order_created=False,
            order_id=None,
            order_intent_id=None,
            order_side=None,
            submission_status=None,
            exchange_state=None,
            message="AI 분석 완료, 거래 모드 상태를 확인할 수 없어 주문 평가를 차단함",
            started_at=started_at,
            finished_at=datetime.now(UTC),
        )

    if trading_mode == "live":
        order_gate = await get_live_order_gate_status(db)
        if not order_gate.state_available or order_gate.mode != "ARMED":
            return AIManualCycleResponse(
                symbol=normalized_symbol,
                analysis=AIAnalysisLogItem.model_validate(analysis_log),
                trade_evaluated=False,
                order_created=False,
                order_id=None,
                order_intent_id=None,
                order_side=None,
                submission_status=None,
                exchange_state=None,
                message="AI 분석 완료, live 주문 Gate가 ARMED가 아니어서 주문 평가를 차단함",
                started_at=started_at,
                finished_at=datetime.now(UTC),
            )

    risk_check: RiskCheckResult | None = None
    if analysis_log.decision == "BUY":
        risk_check = await evaluate_new_buy_risk_health(db)

    try:
        trade_result = await execute_ai_trade(
            db,
            normalized_symbol,
            analysis_id=analysis_log.id,
            risk_check=risk_check,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    latest_order = await _load_latest_order_for_analysis(db, analysis_log.id)
    normalized_order_side = (
        _normalize_order_side(latest_order.side) if latest_order is not None else None
    )
    if trade_result is not None:
        order_created = trade_result.order_history_id is not None
        order_side = (
            analysis_log.decision
            if analysis_log.decision in {"BUY", "SELL"}
            else None
        )
        order_id = trade_result.order_history_id
        order_intent_id = trade_result.intent_id
        submission_status = trade_result.submission_status
        exchange_state = trade_result.exchange_state
        message = _live_order_message(trade_result)
    else:
        order_created = latest_order is not None and normalized_order_side is not None
        order_side = normalized_order_side if order_created else None
        order_id = latest_order.id if latest_order is not None else None
        order_intent_id = None
        submission_status = None
        exchange_state = None
        if risk_check is not None and not risk_check.allows_new_buy:
            message = (
                "분석 완료, 리스크 상태가 "
                f"{risk_check.status}이어서 신규 BUY를 차단함"
            )
        else:
            message = "신규 체결 있음" if order_created else "분석 완료, 신규 체결 없음"
    finished_at = datetime.now(UTC)

    return AIManualCycleResponse(
        symbol=normalized_symbol,
        analysis=AIAnalysisLogItem.model_validate(analysis_log),
        trade_evaluated=True,
        order_created=order_created,
        order_id=order_id,
        order_intent_id=order_intent_id,
        order_side=order_side,
        submission_status=submission_status,
        exchange_state=exchange_state,
        message=message,
        started_at=started_at,
        finished_at=finished_at,
    )


@router.get("/latest-analysis-batch", response_model=dict[str, AIAnalysisLogItem | None])
async def get_latest_analysis_batch(
    symbols: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, AIAnalysisLogItem | None]:
    normalized_symbols: list[str] = []
    seen_symbols: set[str] = set()

    for raw_symbol in str(symbols or "").split(","):
        normalized_symbol = _normalize_symbol(raw_symbol)
        if not normalized_symbol or normalized_symbol in seen_symbols:
            continue
        seen_symbols.add(normalized_symbol)
        normalized_symbols.append(normalized_symbol)

    if not normalized_symbols:
        raise HTTPException(status_code=400, detail="symbols query parameter is required")

    ranked_analyses = (
        select(
            AIAnalysisLog.id.label("id"),
            AIAnalysisLog.symbol.label("symbol"),
            AIAnalysisLog.stage.label("stage"),
            AIAnalysisLog.provider.label("provider"),
            AIAnalysisLog.model.label("model"),
            AIAnalysisLog.fallback_used.label("fallback_used"),
            AIAnalysisLog.parent_analysis_id.label("parent_analysis_id"),
            AIAnalysisLog.prompt_version.label("prompt_version"),
            AIAnalysisLog.context_sha256.label("context_sha256"),
            AIAnalysisLog.decision.label("decision"),
            AIAnalysisLog.confidence.label("confidence"),
            AIAnalysisLog.recommended_weight.label("recommended_weight"),
            AIAnalysisLog.reasoning.label("reasoning"),
            AIAnalysisLog.accuracy_label.label("accuracy_label"),
            AIAnalysisLog.actual_price_diff_pct.label("actual_price_diff_pct"),
            AIAnalysisLog.created_at.label("created_at"),
            func.row_number()
            .over(
                partition_by=AIAnalysisLog.symbol,
                order_by=(
                    case(
                        (AIAnalysisLog.stage == AI_ANALYSIS_STAGE_TRADE, 0),
                        else_=1,
                    ),
                    desc(AIAnalysisLog.created_at),
                    desc(AIAnalysisLog.id),
                ),
            )
            .label("row_number"),
        )
        .where(AIAnalysisLog.symbol.in_(normalized_symbols))
        .where(
            AIAnalysisLog.stage.in_(
                (AI_ANALYSIS_STAGE_TRADE, AI_ANALYSIS_STAGE_LEGACY)
            )
        )
        .subquery()
    )

    result = await db.execute(
        select(
            ranked_analyses.c.id,
            ranked_analyses.c.symbol,
            ranked_analyses.c.stage,
            ranked_analyses.c.provider,
            ranked_analyses.c.model,
            ranked_analyses.c.fallback_used,
            ranked_analyses.c.parent_analysis_id,
            ranked_analyses.c.prompt_version,
            ranked_analyses.c.context_sha256,
            ranked_analyses.c.decision,
            ranked_analyses.c.confidence,
            ranked_analyses.c.recommended_weight,
            ranked_analyses.c.reasoning,
            ranked_analyses.c.accuracy_label,
            ranked_analyses.c.actual_price_diff_pct,
            ranked_analyses.c.created_at,
        ).where(ranked_analyses.c.row_number == 1)
    )

    latest_by_symbol: dict[str, AIAnalysisLogItem | None] = {
        symbol: None for symbol in normalized_symbols
    }
    for row in result.all():
        symbol = str(row.symbol or "").strip().upper()
        if not symbol:
            continue
        latest_by_symbol[symbol] = AIAnalysisLogItem.model_validate(dict(row._mapping))

    return latest_by_symbol


@router.get("/performance", response_model=AIPerformanceSummary)
async def get_ai_performance_summary(
    db: AsyncSession = Depends(get_db),
) -> AIPerformanceSummary:
    linked_analysis = aliased(AIAnalysisLog, name="linked_analysis")
    primary_analysis = aliased(AIAnalysisLog, name="primary_analysis")
    primary_lineage_join = or_(
        and_(
            linked_analysis.stage == AI_ANALYSIS_STAGE_TRADE,
            primary_analysis.id == linked_analysis.id,
        ),
        and_(
            linked_analysis.stage == AI_ANALYSIS_STAGE_BUY_PRECHECK,
            primary_analysis.id == linked_analysis.parent_analysis_id,
        ),
    )
    history_stmt = (
        select(OrderHistory, Position, Asset, linked_analysis, primary_analysis)
        .join(Position, Position.id == OrderHistory.position_id)
        .join(Asset, Asset.id == Position.asset_id)
        .join(linked_analysis, linked_analysis.id == OrderHistory.ai_analysis_log_id)
        .outerjoin(
            primary_analysis,
            and_(
                primary_analysis.stage == AI_ANALYSIS_STAGE_TRADE,
                primary_lineage_join,
            ),
        )
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

    for order, position, _asset, _linked_analysis, analysis in history_result.all():
        if _is_probable_legacy_quote_amount_buy(order):
            continue

        normalized_side = _normalize_order_side(order.side)
        if normalized_side is None or order.price <= 0 or order.qty <= 0:
            continue

        if analysis is not None:
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
        select(OrderHistory, Position, Asset, linked_analysis, primary_analysis)
        .join(Position, Position.id == OrderHistory.position_id)
        .join(Asset, Asset.id == Position.asset_id)
        .join(linked_analysis, linked_analysis.id == OrderHistory.ai_analysis_log_id)
        .outerjoin(
            primary_analysis,
            and_(
                primary_analysis.stage == AI_ANALYSIS_STAGE_TRADE,
                primary_lineage_join,
            ),
        )
        .where(OrderHistory.ai_analysis_log_id.is_not(None))
        .order_by(desc(OrderHistory.executed_at), desc(OrderHistory.id))
        .limit(20)
    )
    recent_result = await db.execute(recent_stmt)

    recent_trades: list[AITradeRecord] = []
    for order, _position, asset, linked, primary in recent_result.all():
        if _is_probable_legacy_quote_amount_buy(order):
            continue

        analysis = primary
        if analysis is None and linked.stage == AI_ANALYSIS_STAGE_LEGACY:
            analysis = linked
        if analysis is None:
            continue
        trade_record = _build_recent_trade(order, asset, analysis)
        if trade_record is not None:
            recent_trades.append(trade_record)

    accuracy_stmt = select(AIAnalysisLog.accuracy_label).where(
        AIAnalysisLog.stage == AI_ANALYSIS_STAGE_TRADE,
        AIAnalysisLog.decision.in_(("BUY", "SELL")),
        AIAnalysisLog.accuracy_label.in_(("SUCCESS", "FAIL")),
    )
    accuracy_result = await db.execute(accuracy_stmt)
    accuracy_labels = list(accuracy_result.scalars().all())
    checked_count = len(accuracy_labels)
    success_count = sum(1 for label in accuracy_labels if label == "SUCCESS")

    total_trades = winning_trades + losing_trades
    win_rate = (winning_trades / total_trades) * 100.0 if total_trades > 0 else 0.0
    accuracy_rate = (success_count / checked_count) * 100.0 if checked_count > 0 else 0.0
    avg_confidence = (total_confidence / confidence_count) if confidence_count > 0 else 0.0

    return AIPerformanceSummary(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        accuracy_rate=accuracy_rate,
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
