from __future__ import annotations

from datetime import datetime
from typing import Any

from langchain_core.tools import tool
from sqlalchemy import desc, select

from app.db.repository import search_chat_history
from app.db.session import AsyncSessionLocal
from app.models.domain import AIAnalysisLog, Asset, OrderHistory, Position
from app.services.portfolio.aggregator import PortfolioService


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


def _truncate_text(value: str | None, limit: int = 300) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text or "-"
    return f"{text[:limit].rstrip()}..."


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
                f"심볼={asset.symbol} | "
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
                f"심볼={log.symbol} | "
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

    return [
        query_portfolio_summary,
        query_order_history,
        query_ai_analysis_logs,
        search_past_conversations,
    ]
