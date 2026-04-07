from __future__ import annotations

from datetime import datetime
from typing import Any

from langchain_core.tools import tool
from sqlalchemy import desc, select

from app.db.repository import search_chat_history
from app.db.session import AsyncSessionLocal
from app.models.domain import AIAnalysisLog, Asset, OrderHistory, Position
from app.services.brokers.factory import BrokerFactory
from app.services.indicators import IndicatorCalculator
from app.services.market.sentiment_fetcher import get_cached_market_sentiment
from app.services.market.sentiment_fetcher import get_or_refresh_market_sentiment
from app.services.portfolio.aggregator import PortfolioService

indicator_calculator = IndicatorCalculator()


def _normalize_symbol(symbol: str | None) -> str | None:
    normalized = str(symbol or "").strip().upper()
    return normalized or None


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.isoformat()


def _format_number(value: float | int | None, digits: int = 4) -> str:
    if value is None:
        return "-"
    number = float(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.{digits}f}"


def _format_krw(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.0f} KRW"


def _format_percent(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.{digits}f}%"


def _truncate_text(value: str | None, limit: int = 300) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text or "-"
    return f"{text[:limit].rstrip()}..."


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_candle_time(raw_time: Any) -> str | None:
    text = str(raw_time or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return parsed.isoformat()


def _normalize_candles(raw_candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in reversed(raw_candles):
        if not isinstance(row, dict):
            continue
        normalized.append(
            {
                "timestamp": _normalize_candle_time(row.get("candle_date_time_utc")),
                "open": _to_float(row.get("opening_price")),
                "high": _to_float(row.get("high_price")),
                "low": _to_float(row.get("low_price")),
                "close": _to_float(row.get("trade_price")),
                "volume": _to_float(row.get("candle_acc_trade_volume")),
            }
        )
    return normalized


def build_chat_tools(session_id: str) -> list[Any]:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise ValueError("session_id is required to build chat tools.")

    @tool
    async def query_portfolio_summary() -> str:
        """현재 포트폴리오 요약 정보를 조회합니다."""
        try:
            async with AsyncSessionLocal() as db:
                portfolio = await PortfolioService(db).get_aggregated_portfolio()
        except Exception as exc:
            return f"포트폴리오 조회 중 오류가 발생했습니다: {exc}"

        lines = [
            "[현재 포트폴리오 요약]",
            f"- 총 순자산: {_format_krw(portfolio.total_net_worth)}",
            f"- 총 평가손익: {_format_krw(portfolio.total_pnl)}",
        ]

        if portfolio.error:
            lines.append(f"- 포트폴리오 에러 코드: {portfolio.error}")

        krw_item = next((item for item in portfolio.items if item.currency.upper() == "KRW"), None)
        lines.append(f"- KRW 잔고: {_format_krw(krw_item.total_value if krw_item else 0.0)}")

        coin_items = [item for item in portfolio.items if item.currency.upper() != "KRW"]
        if not coin_items:
            lines.append("- 보유 코인: 없음")
            return "\n".join(lines)

        lines.append("- 보유 코인 리스트:")
        for item in coin_items:
            lines.append(
                "  "
                f"* {item.currency} | 수량={_format_number(item.balance, 8)} | 현재가={_format_krw(item.current_price)} | "
                f"평가금액={_format_krw(item.total_value)} | 수익률={float(item.pnl_percentage):.2f}%"
            )

        return "\n".join(lines)

    @tool
    async def query_order_history(symbol: str | None = None, limit: int = 10) -> str:
        """최근 주문 내역을 조회합니다."""
        normalized_symbol = _normalize_symbol(symbol)
        resolved_limit = max(1, min(int(limit or 10), 50))

        try:
            async with AsyncSessionLocal() as db:
                stmt = (
                    select(OrderHistory, Position, Asset)
                    .join(Position, Position.id == OrderHistory.position_id)
                    .join(Asset, Asset.id == Position.asset_id)
                    .order_by(desc(OrderHistory.executed_at), desc(OrderHistory.id))
                    .limit(resolved_limit)
                )
                if normalized_symbol is not None:
                    stmt = stmt.where(Asset.symbol == normalized_symbol)

                result = await db.execute(stmt)
                rows = result.all()
        except Exception as exc:
            return f"주문 내역 조회 중 오류가 발생했습니다: {exc}"

        if not rows:
            if normalized_symbol is not None:
                return f"{normalized_symbol}에 대한 최근 주문 내역이 없습니다."
            return "최근 주문 내역이 없습니다."

        lines = ["[최근 주문 내역]"]
        for order, position, asset in rows:
            lines.append(
                "- "
                f"{_format_datetime(order.executed_at)} | "
                f"종목={asset.symbol} | "
                f"side={order.side} | "
                f"price={_format_krw(order.price)} | "
                f"qty={_format_number(order.qty, 8)} | "
                f"broker={order.broker} | "
                f"is_paper={order.is_paper} | "
                f"order_reason={order.order_reason or '-'} | "
                f"position_status={position.status}"
            )

        return "\n".join(lines)

    @tool
    async def query_ai_analysis_logs(symbol: str | None = None, limit: int = 5) -> str:
        """과거 AI 분석 로그와 reasoning을 조회합니다."""
        normalized_symbol = _normalize_symbol(symbol)
        resolved_limit = max(1, min(int(limit or 5), 20))

        try:
            async with AsyncSessionLocal() as db:
                stmt = (
                    select(AIAnalysisLog)
                    .order_by(desc(AIAnalysisLog.created_at), desc(AIAnalysisLog.id))
                    .limit(resolved_limit)
                )
                if normalized_symbol is not None:
                    stmt = stmt.where(AIAnalysisLog.symbol == normalized_symbol)

                result = await db.execute(stmt)
                logs = list(result.scalars().all())
        except Exception as exc:
            return f"AI 분석 로그 조회 중 오류가 발생했습니다: {exc}"

        if not logs:
            if normalized_symbol is not None:
                return f"{normalized_symbol}에 대한 AI 분석 로그가 없습니다."
            return "AI 분석 로그가 없습니다."

        lines = ["[과거 AI 분석 로그]"]
        for log in logs:
            lines.append(
                "- "
                f"{_format_datetime(log.created_at)} | "
                f"종목={log.symbol} | "
                f"결정={log.decision} | "
                f"확신도={log.confidence} | "
                f"추천비중={log.recommended_weight}% | "
                f"reasoning={_truncate_text(log.reasoning, 300)}"
            )

        return "\n".join(lines)

    @tool
    async def search_past_conversations(keyword: str) -> str:
        """현재 세션의 과거 대화 내역에서 키워드를 검색합니다."""
        normalized_keyword = str(keyword or "").strip()
        if not normalized_keyword:
            return "검색할 키워드를 입력해 주세요."

        try:
            async with AsyncSessionLocal() as db:
                rows = await search_chat_history(db, normalized_session_id, normalized_keyword)
        except Exception as exc:
            return f"과거 대화 검색 중 오류가 발생했습니다: {exc}"

        if not rows:
            return f"현재 세션에서 '{normalized_keyword}' 키워드와 일치하는 과거 대화가 없습니다."

        lines = [f"[과거 대화 검색 결과: {normalized_keyword}]"]
        for row in rows:
            lines.append(
                "- "
                f"{_format_datetime(row.created_at)} | "
                f"role={row.role} | "
                f"agent={row.agent_name or '-'} | "
                f"is_tool_call={row.is_tool_call} | "
                f"content={_truncate_text(row.content, 300)}"
            )

        return "\n".join(lines)

    @tool
    async def get_realtime_ticker(symbol: str) -> str:
        """업비트 현재가, 24시간 등락률, 거래대금을 조회합니다."""
        normalized_symbol = _normalize_symbol(symbol)
        if normalized_symbol is None:
            return "조회할 심볼을 입력해 주세요."

        try:
            broker = BrokerFactory.get_broker("UPBIT")
            rows = await broker.get_ticker([normalized_symbol])
        except Exception as exc:
            return f"{normalized_symbol} 실시간 시세 조회 중 오류가 발생했습니다: {exc}"

        if not rows:
            return f"{normalized_symbol} 시세 데이터를 찾지 못했습니다."

        row = rows[0] if isinstance(rows[0], dict) else {}
        current_price = _to_float(row.get("trade_price"))
        signed_change_rate = _to_float(row.get("signed_change_rate"))
        acc_trade_price_24h = _to_float(row.get("acc_trade_price_24h"))
        change_rate_pct = signed_change_rate * 100 if signed_change_rate is not None else None

        lines = [
            f"[실시간 시세: {normalized_symbol}]",
            f"- 현재가: {_format_krw(current_price)}",
            f"- 24시간 등락률: {_format_percent(change_rate_pct, 2)}",
            f"- 24시간 거래대금: {_format_krw(acc_trade_price_24h)}",
        ]
        return "\n".join(lines)

    @tool
    async def get_technical_indicators(symbol: str, timeframe: str = "15m") -> str:
        """업비트 캔들 기반 RSI, 볼린저밴드, 이동평균 요약을 조회합니다."""
        normalized_symbol = _normalize_symbol(symbol)
        normalized_timeframe = str(timeframe or "15m").strip().lower() or "15m"
        if normalized_symbol is None:
            return "조회할 심볼을 입력해 주세요."

        try:
            broker = BrokerFactory.get_broker("UPBIT")
            raw_candles = await broker.get_candles(
                market=normalized_symbol,
                timeframe=normalized_timeframe,
                count=200,
            )
            normalized_candles = _normalize_candles(raw_candles)
            enriched_candles = indicator_calculator.calculate_from_candles(normalized_candles)
        except Exception as exc:
            return f"{normalized_symbol} 기술 지표 조회 중 오류가 발생했습니다: {exc}"

        if not enriched_candles:
            return f"{normalized_symbol} 기술 지표 계산에 필요한 캔들 데이터가 없습니다."

        latest = enriched_candles[-1]
        lines = [
            f"[기술 지표 요약: {normalized_symbol} / {normalized_timeframe}]",
            f"- 기준 시각: {latest.get('timestamp') or '-'}",
            f"- 종가: {_format_krw(latest.get('close'))}",
            f"- RSI(14): {_format_number(latest.get('rsi_14'), 2)}",
            (
                "- Bollinger Bands(20,2): "
                f"상단={_format_krw(latest.get('bb_upper_20_2'))}, "
                f"중앙={_format_krw(latest.get('bb_middle_20_2'))}, "
                f"하단={_format_krw(latest.get('bb_lower_20_2'))}"
            ),
            (
                "- SMA: "
                f"5={_format_krw(latest.get('sma_5'))}, "
                f"20={_format_krw(latest.get('sma_20'))}, "
                f"60={_format_krw(latest.get('sma_60'))}"
            ),
            (
                "- EMA: "
                f"50={_format_krw(latest.get('ema_50'))}, "
                f"200={_format_krw(latest.get('ema_200'))}"
            ),
            f"- 거래량: {_format_number(latest.get('volume'), 4)}",
        ]
        return "\n".join(lines)

    @tool
    async def get_market_sentiment() -> str:
        """현재 공포/탐욕 지수 기반 시장 심리를 조회합니다."""
        try:
            async with AsyncSessionLocal() as db:
                snapshot = await get_cached_market_sentiment(db)
                if snapshot is None:
                    snapshot = await get_or_refresh_market_sentiment(db)
        except Exception as exc:
            return f"시장 심리 지수 조회 중 오류가 발생했습니다: {exc}"

        if snapshot is None:
            return "현재 시장 심리 지수를 확인할 수 없습니다."

        lines = [
            "[시장 심리 지수]",
            f"- 점수: {snapshot.score}",
            f"- 분류: {snapshot.classification}",
            f"- 갱신 시각: {_format_datetime(snapshot.updated_at)}",
        ]
        return "\n".join(lines)

    return [
        query_portfolio_summary,
        query_order_history,
        query_ai_analysis_logs,
        search_past_conversations,
        get_realtime_ticker,
        get_technical_indicators,
        get_market_sentiment,
    ]
