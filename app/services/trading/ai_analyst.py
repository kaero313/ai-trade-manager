import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import AIAnalysisLog
from app.models.schemas import AIAnalysisResponse
from app.schemas.portfolio import AssetItem
from app.schemas.portfolio import PortfolioSummary
from app.services.ai.analyzer import AIAnalyzerFactory
from app.services.ai.providers.gemini import GeminiAnalyzer
from app.services.brokers.factory import BrokerFactory
from app.services.indicators import IndicatorCalculator
from app.services.market.sentiment_fetcher import get_cached_market_sentiment
from app.services.market.sentiment_fetcher import get_or_refresh_market_sentiment
from app.services.portfolio.aggregator import PortfolioService
from app.services.rag.opensearch_client import INDEX_NAME
from app.services.rag.opensearch_client import get_opensearch_client

logger = logging.getLogger(__name__)

TECHNICAL_TIMEFRAME = "60m"
TECHNICAL_CANDLE_COUNT = 200
NEWS_RESULT_LIMIT = 3
NEWS_SUMMARY_MAX_CHARS = 180

ANALYSIS_SYSTEM_PROMPT = """
당신은 월스트리트 엘리트 코인 트레이더입니다.
주어진 시장 데이터만 근거로 BUY, SELL, HOLD 중 하나를 결정하십시오.
반드시 JSON 스키마에 맞는 값만 반환하십시오.

규칙:
- decision은 BUY, SELL, HOLD 중 하나만 허용됩니다.
- confidence는 0~100 정수여야 합니다.
- recommended_weight는 0~100 정수여야 합니다.
- reasoning은 1~3문장으로 짧고 구체적으로 작성하십시오.
- 제공되지 않은 정보는 추측하지 마십시오.
- 데이터가 부족하거나 근거가 충돌하면 HOLD를 선택하고 confidence를 낮게 유지하십시오.
""".strip()

broker = BrokerFactory.get_broker("UPBIT")
indicator_calculator = IndicatorCalculator()


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _extract_currency(symbol: str) -> str:
    normalized_symbol = _normalize_symbol(symbol)
    if "-" not in normalized_symbol:
        return normalized_symbol
    return normalized_symbol.split("-", 1)[1]


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _truncate_text(text: str, max_chars: int = NEWS_SUMMARY_MAX_CHARS) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 3].rstrip()}..."


def _format_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        target = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return target.astimezone(UTC).isoformat()

    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text

    target = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return target.astimezone(UTC).isoformat()


def _format_number(value: Any, *, digits: int = 2) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return f"{number:.{digits}f}"


def _format_percentage(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return f"{number:+.2f}%"


def _extract_market_names(market_row: dict[str, Any] | None, symbol: str) -> list[str]:
    currency = _extract_currency(symbol)
    candidates = [
        currency,
        str(market_row.get("korean_name") or "").strip() if isinstance(market_row, dict) else "",
        str(market_row.get("english_name") or "").strip() if isinstance(market_row, dict) else "",
    ]

    deduped: list[str] = []
    for item in candidates:
        normalized = item.strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _build_market_news_query(terms: Sequence[str], size: int) -> dict[str, Any]:
    should_clauses = [
        {
            "multi_match": {
                "query": term,
                "fields": ["title^3", "content"],
                "type": "best_fields",
            }
        }
        for term in terms
        if term
    ]

    if should_clauses:
        query: dict[str, Any] = {
            "bool": {
                "should": should_clauses,
                "minimum_should_match": 1,
            }
        }
        sort: list[Any] = ["_score", {"published_at": {"order": "desc"}}]
    else:
        query = {"match_all": {}}
        sort = [{"published_at": {"order": "desc"}}]

    return {
        "size": size,
        "_source": ["title", "content", "source", "link", "published_at"],
        "query": query,
        "sort": sort,
    }


async def _resolve_market_metadata(symbol: str) -> dict[str, Any] | None:
    normalized_symbol = _normalize_symbol(symbol)
    if not normalized_symbol:
        return None

    markets = await broker.get_all_markets()
    for row in markets:
        if not isinstance(row, dict):
            continue
        market = _normalize_symbol(row.get("market"))
        if market == normalized_symbol:
            return row
    return None


def _normalize_news_hit(hit: dict[str, Any]) -> dict[str, Any]:
    source = hit.get("_source")
    if not isinstance(source, dict):
        source = {}

    title = str(source.get("title") or "").strip()
    content = str(source.get("content") or "").strip()
    return {
        "title": title or "제목 없음",
        "summary": _truncate_text(content or title),
        "source": str(source.get("source") or "").strip() or None,
        "published_at": _format_datetime(source.get("published_at")),
        "link": str(source.get("link") or "").strip() or None,
    }


async def _search_news_documents(symbol: str, market_row: dict[str, Any] | None) -> dict[str, Any]:
    terms = _extract_market_names(market_row, symbol)
    client = get_opensearch_client()

    try:
        response = await client.search(
            index=INDEX_NAME,
            body=_build_market_news_query(terms, NEWS_RESULT_LIMIT),
        )
        hits = response.get("hits", {}).get("hits", [])
        if not isinstance(hits, list):
            hits = []

        normalized_hits = [
            _normalize_news_hit(hit)
            for hit in hits
            if isinstance(hit, dict)
        ]
        if normalized_hits:
            return {"items": normalized_hits[:NEWS_RESULT_LIMIT], "error": None}

        fallback_response = await client.search(
            index=INDEX_NAME,
            body=_build_market_news_query([], NEWS_RESULT_LIMIT),
        )
        fallback_hits = fallback_response.get("hits", {}).get("hits", [])
        if not isinstance(fallback_hits, list):
            fallback_hits = []
        return {
            "items": [
                _normalize_news_hit(hit)
                for hit in fallback_hits
                if isinstance(hit, dict)
            ][:NEWS_RESULT_LIMIT],
            "error": None,
        }
    except Exception as exc:
        logger.warning("AI 뉴스 컨텍스트 조회 실패: %s", exc, exc_info=True)
        return {"items": [], "error": "NEWS_SEARCH_FAILED"}


def _find_portfolio_item(portfolio: PortfolioSummary, symbol: str) -> AssetItem | None:
    currency = _extract_currency(symbol)
    for item in portfolio.items:
        if item.currency.upper() == currency:
            return item
    return None


def _build_portfolio_context(portfolio: PortfolioSummary, symbol: str) -> dict[str, Any]:
    currency = _extract_currency(symbol)
    target_item = _find_portfolio_item(portfolio, symbol)
    if target_item is None:
        return {
            "held": False,
            "currency": currency,
            "balance": 0.0,
            "locked": 0.0,
            "avg_buy_price": None,
            "current_price": None,
            "total_value": 0.0,
            "pnl_percentage": None,
            "portfolio_error": portfolio.error,
        }

    return {
        "held": True,
        "currency": target_item.currency,
        "balance": target_item.balance,
        "locked": target_item.locked,
        "avg_buy_price": target_item.avg_buy_price,
        "current_price": target_item.current_price,
        "total_value": target_item.total_value,
        "pnl_percentage": target_item.pnl_percentage,
        "portfolio_error": portfolio.error,
    }


def _normalize_candle_time(raw_time: Any) -> str | None:
    text = str(raw_time or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text

    target = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return target.astimezone(UTC).isoformat()


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


def _calculate_gap_percentage(close: Any, indicator_value: Any) -> float | None:
    close_price = _to_float(close)
    indicator_price = _to_float(indicator_value)
    if close_price is None or indicator_price in (None, 0):
        return None
    return ((close_price - indicator_price) / indicator_price) * 100


def _compress_technical_snapshot(enriched_candles: list[dict[str, Any]]) -> dict[str, Any]:
    if not enriched_candles:
        return {
            "timeframe": TECHNICAL_TIMEFRAME,
            "latest_candle_at": None,
            "close": None,
            "volume": None,
            "sma_20": None,
            "sma_60": None,
            "ema_50": None,
            "ema_200": None,
            "bb_upper_20_2": None,
            "bb_lower_20_2": None,
            "rsi_14": None,
            "price_vs_sma20_pct": None,
            "price_vs_ema50_pct": None,
        }

    latest = enriched_candles[-1]
    close_price = _to_float(latest.get("close"))
    sma_20 = _to_float(latest.get("sma_20"))
    ema_50 = _to_float(latest.get("ema_50"))

    return {
        "timeframe": TECHNICAL_TIMEFRAME,
        "latest_candle_at": _format_datetime(latest.get("timestamp")),
        "close": close_price,
        "volume": _to_float(latest.get("volume")),
        "sma_20": sma_20,
        "sma_60": _to_float(latest.get("sma_60")),
        "ema_50": ema_50,
        "ema_200": _to_float(latest.get("ema_200")),
        "bb_upper_20_2": _to_float(latest.get("bb_upper_20_2")),
        "bb_lower_20_2": _to_float(latest.get("bb_lower_20_2")),
        "rsi_14": _to_float(latest.get("rsi_14")),
        "price_vs_sma20_pct": _calculate_gap_percentage(close_price, sma_20),
        "price_vs_ema50_pct": _calculate_gap_percentage(close_price, ema_50),
    }


async def _build_sentiment_context(db: AsyncSession) -> dict[str, Any]:
    snapshot = await get_cached_market_sentiment(db)
    if snapshot is None:
        snapshot = await get_or_refresh_market_sentiment(db)

    return {
        "score": snapshot.score,
        "classification": snapshot.classification,
        "updated_at": snapshot.updated_at.isoformat(),
        "error": None,
    }


def _build_empty_context(symbol: str) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    return {
        "symbol": normalized_symbol,
        "portfolio": {
            "held": False,
            "currency": _extract_currency(normalized_symbol),
            "balance": 0.0,
            "locked": 0.0,
            "avg_buy_price": None,
            "current_price": None,
            "total_value": 0.0,
            "pnl_percentage": None,
            "portfolio_error": "NOT_LOADED",
        },
        "technical": {
            **_compress_technical_snapshot([]),
            "error": "NOT_LOADED",
        },
        "news": {
            "items": [],
            "error": "NOT_LOADED",
        },
        "sentiment": {
            "score": None,
            "classification": None,
            "updated_at": None,
            "error": "NOT_LOADED",
        },
    }


async def gather_market_context(db: AsyncSession, symbol: str) -> dict[str, Any]:
    normalized_symbol = _normalize_symbol(symbol)
    context = _build_empty_context(normalized_symbol)
    market_row: dict[str, Any] | None = None

    try:
        portfolio = await PortfolioService(db).get_aggregated_portfolio()
        context["portfolio"] = _build_portfolio_context(portfolio, normalized_symbol)
    except Exception as exc:
        logger.warning("AI 포트폴리오 컨텍스트 생성 실패: %s", exc, exc_info=True)
        context["portfolio"]["portfolio_error"] = "PORTFOLIO_CONTEXT_FAILED"

    try:
        market_row = await _resolve_market_metadata(normalized_symbol)
    except Exception as exc:
        logger.warning("AI 시장 메타데이터 조회 실패: %s", exc, exc_info=True)

    try:
        raw_candles = await broker.get_candles(
            market=normalized_symbol,
            timeframe=TECHNICAL_TIMEFRAME,
            count=TECHNICAL_CANDLE_COUNT,
        )
        normalized_candles = _normalize_candles(raw_candles)
        enriched_candles = indicator_calculator.calculate_from_candles(normalized_candles)
        context["technical"] = {
            **_compress_technical_snapshot(enriched_candles),
            "error": None,
        }
    except Exception as exc:
        logger.warning("AI 기술 지표 컨텍스트 생성 실패: %s", exc, exc_info=True)
        context["technical"] = {
            **_compress_technical_snapshot([]),
            "error": "TECHNICAL_CONTEXT_FAILED",
        }

    context["news"] = await _search_news_documents(normalized_symbol, market_row)

    try:
        context["sentiment"] = await _build_sentiment_context(db)
    except Exception as exc:
        logger.warning("AI 심리 지표 컨텍스트 생성 실패: %s", exc, exc_info=True)
        context["sentiment"] = {
            "score": None,
            "classification": None,
            "updated_at": None,
            "error": "SENTIMENT_CONTEXT_FAILED",
        }

    return context


def format_market_context_for_llm(context: dict[str, Any]) -> str:
    portfolio = context.get("portfolio") or {}
    technical = context.get("technical") or {}
    news = context.get("news") or {}
    sentiment = context.get("sentiment") or {}

    lines = [
        f"# Symbol\n- {context.get('symbol') or '-'}",
        "# Portfolio",
        f"- 보유 여부: {'보유 중' if portfolio.get('held') else '미보유'}",
        f"- 자산 코드: {portfolio.get('currency') or '-'}",
        f"- 잔고: {_format_number(portfolio.get('balance'), digits=8)}",
        f"- 주문 잠금 수량: {_format_number(portfolio.get('locked'), digits=8)}",
        f"- 평단가: {_format_number(portfolio.get('avg_buy_price'))}",
        f"- 현재가: {_format_number(portfolio.get('current_price'))}",
        f"- 평가금액: {_format_number(portfolio.get('total_value'))}",
        f"- 수익률: {_format_percentage(portfolio.get('pnl_percentage'))}",
        f"- 포트폴리오 오류: {portfolio.get('portfolio_error') or '-'}",
        "# Technical",
        f"- 타임프레임: {technical.get('timeframe') or '-'}",
        f"- 최신 캔들 시각: {technical.get('latest_candle_at') or '-'}",
        f"- 종가: {_format_number(technical.get('close'))}",
        f"- 거래량: {_format_number(technical.get('volume'))}",
        f"- SMA20: {_format_number(technical.get('sma_20'))}",
        f"- SMA60: {_format_number(technical.get('sma_60'))}",
        f"- EMA50: {_format_number(technical.get('ema_50'))}",
        f"- EMA200: {_format_number(technical.get('ema_200'))}",
        f"- BB 상단: {_format_number(technical.get('bb_upper_20_2'))}",
        f"- BB 하단: {_format_number(technical.get('bb_lower_20_2'))}",
        f"- RSI14: {_format_number(technical.get('rsi_14'))}",
        f"- 종가 vs SMA20: {_format_percentage(technical.get('price_vs_sma20_pct'))}",
        f"- 종가 vs EMA50: {_format_percentage(technical.get('price_vs_ema50_pct'))}",
        f"- 기술 지표 오류: {technical.get('error') or '-'}",
        "# News",
    ]

    news_items = news.get("items")
    if isinstance(news_items, list) and news_items:
        for item in news_items[:NEWS_RESULT_LIMIT]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip() or "제목 없음"
            summary = str(item.get("summary") or "").strip() or "요약 없음"
            source = str(item.get("source") or "").strip() or "-"
            published_at = str(item.get("published_at") or "").strip() or "-"
            lines.append(f"- {title} | {summary} | 출처={source} | 시각={published_at}")
    else:
        lines.append("- 뉴스 데이터 없음")
    lines.append(f"- 뉴스 오류: {news.get('error') or '-'}")

    lines.extend(
        [
            "# Sentiment",
            f"- 점수: {sentiment.get('score') if sentiment.get('score') is not None else '-'}",
            f"- 분류: {sentiment.get('classification') or '-'}",
            f"- 업데이트 시각: {sentiment.get('updated_at') or '-'}",
            f"- 심리 지표 오류: {sentiment.get('error') or '-'}",
        ]
    )

    return "\n".join(lines)


def _build_analysis_user_prompt(symbol: str, context_text: str) -> str:
    return (
        f"대상 종목: {symbol}\n\n"
        "아래 시장 컨텍스트를 보고 포지션을 결정하십시오.\n"
        "반드시 BUY, SELL, HOLD 중 하나만 선택하고, 확신도와 추천 비중을 정수로 제시하십시오.\n\n"
        f"{context_text}"
    )


def _build_fallback_analysis() -> AIAnalysisResponse:
    return AIAnalysisResponse(
        decision="HOLD",
        confidence=0,
        recommended_weight=0,
        reasoning="AI 분석 실패로 보수적으로 HOLD를 반환했습니다.",
    )


def _get_gemini_analyzer() -> GeminiAnalyzer:
    analyzer = AIAnalyzerFactory.get_analyzer("gemini")
    if not isinstance(analyzer, GeminiAnalyzer):
        raise RuntimeError("Gemini 분석기 초기화에 실패했습니다.")
    return analyzer


async def _persist_ai_analysis_log(
    db: AsyncSession,
    symbol: str,
    analysis: AIAnalysisResponse,
) -> None:
    try:
        db.add(
            AIAnalysisLog(
                symbol=_normalize_symbol(symbol),
                decision=analysis.decision,
                confidence=analysis.confidence,
                recommended_weight=analysis.recommended_weight,
                reasoning=analysis.reasoning,
            )
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("AI 분석 로그 저장 실패: %s", exc, exc_info=True)


async def execute_ai_analysis(db: AsyncSession, symbol: str) -> AIAnalysisResponse:
    normalized_symbol = _normalize_symbol(symbol)
    context = await gather_market_context(db, normalized_symbol)
    context_text = format_market_context_for_llm(context)

    try:
        analyzer = _get_gemini_analyzer()
        analysis = await analyzer.generate_structured_analysis(
            system_prompt=ANALYSIS_SYSTEM_PROMPT,
            user_prompt=_build_analysis_user_prompt(normalized_symbol, context_text),
            response_model=AIAnalysisResponse,
        )
    except Exception as exc:
        logger.error("AI 구조화 분석 실패: symbol=%s error=%s", normalized_symbol, exc, exc_info=True)
        analysis = _build_fallback_analysis()

    await _persist_ai_analysis_log(db, normalized_symbol, analysis)
    return analysis
