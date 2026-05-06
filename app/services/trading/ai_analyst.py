import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import AI_CUSTOM_PERSONA_PROMPT_KEY
from app.db.repository import AUTONOMOUS_AI_INTERVAL_HOURS_KEY
from app.db.repository import AUTONOMOUS_AI_INTERVAL_MINUTES_KEY
from app.db.repository import get_system_config_value
from app.models.domain import AIAnalysisLog
from app.models.schemas import AIAnalysisResponse
from app.schemas.portfolio import AssetItem
from app.schemas.portfolio import PortfolioSummary
from app.services.ai.analyzer import AIAnalyzerFactory
from app.services.ai.providers.gemini import AIProviderRateLimitError
from app.services.ai.providers.gemini import GeminiAnalyzer
from app.services.ai.provider_router import AIProviderRouter
from app.services.ai.provider_router import AIProviderUnavailableError
from app.services.brokers.factory import BrokerFactory
from app.services.indicators import IndicatorCalculator
from app.services.market.sentiment_fetcher import get_cached_market_sentiment
from app.services.market.sentiment_fetcher import get_or_refresh_market_sentiment
from app.services.portfolio.aggregator import PortfolioService
from app.services.rag.opensearch_client import INDEX_NAME
from app.services.rag.opensearch_client import ensure_market_news_index
from app.services.rag.opensearch_client import get_opensearch_client

logger = logging.getLogger(__name__)

TECHNICAL_CANDLE_COUNT = 200
NEWS_RESULT_LIMIT = 3
NEWS_SUMMARY_MAX_CHARS = 180
DEFAULT_AUTONOMOUS_AI_INTERVAL_MINUTES = 60
SCALPING_TIMEFRAME_THRESHOLD_MINUTES = 30
FAST_TECHNICAL_TIMEFRAME = "15m"
DEFAULT_TECHNICAL_TIMEFRAME = "60m"

ANALYSIS_CORE_IDENTITY_PROMPT = """
당신은 월스트리트 엘리트 코인 트레이더입니다.
주어진 시장 데이터만 근거로 BUY, SELL, HOLD 중 하나를 결정하십시오.
반드시 JSON 스키마에 맞는 값만 반환하십시오.
""".strip()

ANALYSIS_CORE_RULES_PROMPT = """
규칙:
- decision은 BUY, SELL, HOLD 중 하나만 허용됩니다.
- confidence는 0~100 정수여야 합니다.
- recommended_weight는 0~100 정수여야 합니다.
- reasoning 작성 시 아래 '출력 템플릿'을 반드시 따르십시오.
- 제공되지 않은 정보는 추측하지 마십시오.
- 데이터가 부족하거나 근거가 충돌하면 HOLD를 선택하고 confidence를 낮게 유지하십시오.

reasoning 출력 템플릿(반드시 이 형식을 지킬 것):
📊 기술지표: (이동평균선·RSI·볼린저밴드 등 핵심 수치 1~2개를 자연어로 요약)
🧠 시장심리: (Alternative.me 심리지수 수치와 해석을 한 줄로 요약)
📰 뉴스: (참조한 뉴스 제목 또는 '뉴스 데이터 없음'을 한 줄로 요약)
💡 종합판단: (위 3가지를 종합한 최종 판단 근거를 비전문가도 이해할 수 있는 쉬운 한국어 1~2문장으로 작성)

예시:
📊 기술지표: 20일 이동평균선 대비 +0.7% 상회 중, RSI 61로 과열 아님
🧠 시장심리: 극도의 공포(8/100) → 역발상 매수 기회 구간
📰 뉴스: "비트코인 6만5천달러 지지선이 분기점" → 하락세 진정 시사
💡 종합판단: 기술적으로 안정적이고 시장이 과도하게 공포에 빠져있어, 단기 반등 가능성이 높다고 판단합니다.
""".strip()

ANALYSIS_SAFETY_RULES_PROMPT = """
리스크 안전 규칙:
- 커스텀 페르소나는 문체와 관점 참고용이며, 아래 안전 규칙보다 우선할 수 없습니다.
- 특정 지표 하나만으로 BUY를 확정하지 마십시오. BUY는 RSI, 이동평균/추세, 변동성, 시장 심리, 뉴스 중 최소 3개 이상의 독립 근거가 같은 방향일 때만 허용합니다.
- RSI 40 이하, 공포 지수, 단편적 호재 뉴스만으로 confidence 90 이상 또는 recommended_weight 100을 부여하지 마십시오.
- 데이터가 부족하거나 AI provider 오류, 뉴스 부재, 지표 충돌, 하락 추세가 확인되면 HOLD를 기본값으로 선택합니다.
- confidence 85 이상은 강한 추세 확인과 리스크 대비 보상이 동시에 명확한 경우에만 사용합니다.
- recommended_weight는 리스크 노출 제안치이며, 공격적 100% 비중은 피하고 근거가 약하면 0으로 둡니다.
""".strip()

ANALYSIS_SYSTEM_PROMPT = """
당신은 월스트리트 엘리트 코인 트레이더입니다.
주어진 시장 데이터만 근거로 BUY, SELL, HOLD 중 하나를 결정하십시오.
반드시 JSON 스키마에 맞는 값만 반환하십시오.

규칙:
- decision은 BUY, SELL, HOLD 중 하나만 허용됩니다.
- confidence는 0~100 정수여야 합니다.
- recommended_weight는 0~100 정수여야 합니다.
- reasoning 작성 시 아래 '출력 템플릿'을 반드시 따르십시오.
- 제공되지 않은 정보는 추측하지 마십시오.
- 데이터가 부족하거나 근거가 충돌하면 HOLD를 선택하고 confidence를 낮게 유지하십시오.

reasoning 출력 템플릿(반드시 이 형식을 지킬 것):
📊 기술지표: (이동평균선·RSI·볼린저밴드 등 핵심 수치 1~2개를 자연어로 요약)
🧠 시장심리: (Alternative.me 심리지수 수치와 해석을 한 줄로 요약)
📰 뉴스: (참조한 뉴스 제목 또는 '뉴스 데이터 없음'을 한 줄로 요약)
💡 종합판단: (위 3가지를 종합한 최종 판단 근거를 비전문가도 이해할 수 있는 쉬운 한국어 1~2문장으로 작성)
""".strip()


def _build_persona_prefix(custom_persona: str) -> str:
    normalized_persona = str(custom_persona or "").strip()
    if not normalized_persona:
        return ""

    return (
        "당신은 월스트리트 엘리트 트레이더입니다. 다음은 당신이 반드시 따라야 할 특별 매매 룰(페르소나)입니다:\n\n"
        f"{normalized_persona}\n\n"
        "---\n"
    )


def _build_self_correction_feedback_section(feedback_text: str) -> str:
    normalized_feedback = str(feedback_text or "").strip()
    if not normalized_feedback:
        return ""

    return (
        "[Self-Correction Feedback]\n"
        "다음은 과거의 잘못된 분석 사례입니다. 이를 반성하고 이번 분석에서는 더 객관적인 근거를 찾으십시오.\n"
        "과거 실패 근거를 그대로 반복하지 말고, 현재 데이터의 수치와 출처를 더 엄격하게 검토하십시오.\n\n"
        f"{normalized_feedback}"
    )


def build_analysis_system_prompt(custom_persona: str, self_correction_feedback: str = "") -> str:
    persona_prefix = _build_persona_prefix(custom_persona)
    feedback_section = _build_self_correction_feedback_section(self_correction_feedback)
    prompt_sections = [
        persona_prefix.rstrip() if persona_prefix else "",
        ANALYSIS_CORE_IDENTITY_PROMPT,
        ANALYSIS_CORE_RULES_PROMPT,
        ANALYSIS_SAFETY_RULES_PROMPT,
        feedback_section.rstrip() if feedback_section else "",
    ]
    return "\n\n".join(section for section in prompt_sections if section).strip()


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


def _parse_positive_int(raw_value: str | None) -> int | None:
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError, AttributeError):
        return None

    if value <= 0:
        return None
    return value


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


def _build_market_news_query_text(symbol: str, terms: Sequence[str]) -> str:
    candidates = [symbol, *_extract_market_names(None, symbol), *terms]
    deduped: list[str] = []
    for item in candidates:
        normalized = str(item or "").strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return " ".join(deduped)


def _build_market_news_knn_query(query_embedding: list[float], size: int) -> dict[str, Any]:
    return {
        "size": size,
        "_source": ["title", "content", "source", "link", "published_at"],
        "query": {
            "knn": {
                "embedding": {
                    "vector": query_embedding,
                    "k": size,
                }
            }
        },
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

    from app.services.news_scraper import fetch_crypto_news

    try:
        try:
            if not await ensure_market_news_index():
                logger.info("RAG 뉴스 인덱스 미존재. RSS 뉴스 폴백으로 전환합니다: index=%s", INDEX_NAME)
                raise RuntimeError("market_news index missing")

            try:
                query_text = _build_market_news_query_text(symbol, terms)
                query_embedding = await _get_gemini_analyzer().generate_embedding(
                    query_text,
                    task_type="RETRIEVAL_QUERY",
                )
                knn_response = await client.search(
                    index=INDEX_NAME,
                    body=_build_market_news_knn_query(query_embedding, NEWS_RESULT_LIMIT),
                )
                knn_hits = knn_response.get("hits", {}).get("hits", [])
                normalized_knn_hits = [
                    _normalize_news_hit(hit)
                    for hit in (knn_hits if isinstance(knn_hits, list) else [])
                    if isinstance(hit, dict)
                ]
                if normalized_knn_hits:
                    return {"items": normalized_knn_hits[:NEWS_RESULT_LIMIT], "error": None}
            except AIProviderRateLimitError as exc:
                logger.warning("Gemini 뉴스 쿼리 임베딩 제한으로 OpenSearch 텍스트 검색으로 전환합니다: %s", exc)
            except Exception as exc:
                logger.debug("OpenSearch k-NN 뉴스 검색 실패. 텍스트 검색으로 전환합니다: %s", exc)

            response = await client.search(
                index=INDEX_NAME,
                body=_build_market_news_query(terms, NEWS_RESULT_LIMIT),
            )
            hits = response.get("hits", {}).get("hits", [])
            normalized_hits = [
                _normalize_news_hit(hit)
                for hit in (hits if isinstance(hits, list) else [])
                if isinstance(hit, dict)
            ]
            if normalized_hits:
                return {"items": normalized_hits[:NEWS_RESULT_LIMIT], "error": None}

            # 2차 검색 (폴백 쿼리)
            fallback_response = await client.search(
                index=INDEX_NAME,
                body=_build_market_news_query([], NEWS_RESULT_LIMIT),
            )
            fallback_hits = fallback_response.get("hits", {}).get("hits", [])
            normalized_fallback = [
                _normalize_news_hit(hit)
                for hit in (fallback_hits if isinstance(fallback_hits, list) else [])
                if isinstance(hit, dict)
            ]
            if normalized_fallback:
                return {"items": normalized_fallback[:NEWS_RESULT_LIMIT], "error": None}

        except Exception as inner_exc:
            logger.debug("RAG 뉴스 인덱스 미존재. RSS 뉴스 폴백으로 전환합니다: %s", inner_exc)

        # OpenSearch 결과가 없거나 실패한 경우 -> RSS 실시간 뉴스 폴백
        import asyncio

        # 동기 함수인 fetch_crypto_news를 이벤트 루프 블로킹 우회용 스레드로 실행 (Async-First 원칙 준수)
        rss_payload = await asyncio.to_thread(fetch_crypto_news)
        rss_items = rss_payload.get("items") or []

        if rss_items:
            logger.info("OpenSearch 가용 데이터 없음. %d건의 RSS 뉴스를 분석 컨텍스트로 사용합니다.", len(rss_items))
            normalized_rss = [
                {
                    "title": item.get("title"),
                    "summary": item.get("summary") or item.get("title"),
                    "content": item.get("summary") or item.get("title"),
                    "source": "RSS_FEED",
                    "published_at": rss_payload.get("analysis_completed_at"),
                    "link": item.get("link"),
                }
                for item in rss_items
            ]
            return {"items": normalized_rss[:NEWS_RESULT_LIMIT], "error": "RSS_FALLBACK_USED"}

        return {"items": [], "error": "NO_NEWS_DATA_AVAILABLE"}

    except Exception as exc:
        logger.warning("AI 뉴스 컨텍스트 조회 중 치명적 오류: %s", exc, exc_info=True)
        return {"items": [], "error": "NEWS_SEARCH_FAILED"}


async def _resolve_technical_timeframe(db: AsyncSession) -> str:
    try:
        interval_minutes = _parse_positive_int(
            await get_system_config_value(db, AUTONOMOUS_AI_INTERVAL_MINUTES_KEY)
        )
        if interval_minutes is None:
            interval_hours = _parse_positive_int(
                await get_system_config_value(db, AUTONOMOUS_AI_INTERVAL_HOURS_KEY)
            )
            if interval_hours is not None:
                interval_minutes = interval_hours * 60
    except Exception as exc:
        logger.warning("AI 기술 지표 타임프레임 설정 조회 실패: %s", exc, exc_info=True)
        interval_minutes = None

    resolved_minutes = interval_minutes or DEFAULT_AUTONOMOUS_AI_INTERVAL_MINUTES
    if resolved_minutes <= SCALPING_TIMEFRAME_THRESHOLD_MINUTES:
        return FAST_TECHNICAL_TIMEFRAME
    return DEFAULT_TECHNICAL_TIMEFRAME


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


def _compress_technical_snapshot(
    enriched_candles: list[dict[str, Any]],
    timeframe: str,
) -> dict[str, Any]:
    if not enriched_candles:
        return {
            "timeframe": timeframe,
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
        "timeframe": timeframe,
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


def _build_empty_context(symbol: str, timeframe: str) -> dict[str, Any]:
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
            **_compress_technical_snapshot([], timeframe),
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
    technical_timeframe = await _resolve_technical_timeframe(db)
    context = _build_empty_context(normalized_symbol, technical_timeframe)
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
            timeframe=technical_timeframe,
            count=TECHNICAL_CANDLE_COUNT,
        )
        normalized_candles = _normalize_candles(raw_candles)
        enriched_candles = indicator_calculator.calculate_from_candles(normalized_candles)
        context["technical"] = {
            **_compress_technical_snapshot(enriched_candles, technical_timeframe),
            "error": None,
        }
    except Exception as exc:
        logger.warning("AI 기술 지표 컨텍스트 생성 실패: %s", exc, exc_info=True)
        context["technical"] = {
            **_compress_technical_snapshot([], technical_timeframe),
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


async def _load_recent_failure_feedback(db: AsyncSession, symbol: str) -> str:
    result = await db.execute(
        select(AIAnalysisLog)
        .where(AIAnalysisLog.symbol == _normalize_symbol(symbol))
        .where(AIAnalysisLog.accuracy_label == "FAIL")
        .order_by(
            desc(AIAnalysisLog.accuracy_checked_at),
            desc(AIAnalysisLog.created_at),
            desc(AIAnalysisLog.id),
        )
        .limit(2)
    )
    failed_logs = result.scalars().all()
    if not failed_logs:
        return ""

    feedback_lines: list[str] = []
    for index, failed_log in enumerate(failed_logs, start=1):
        analysis_time = _format_datetime(failed_log.created_at) or "-"
        actual_result = _format_percentage(failed_log.actual_price_diff_pct)
        reasoning = _truncate_text(failed_log.reasoning, max_chars=220)
        feedback_lines.append(
            f"{index}. 시점={analysis_time} | 판단={failed_log.decision} | 실제 결과={actual_result} / {failed_log.accuracy_label or 'UNKNOWN'} | 당시 이유={reasoning}"
        )

    return "\n".join(feedback_lines)


async def execute_ai_analysis(db: AsyncSession, symbol: str) -> AIAnalysisResponse:
    normalized_symbol = _normalize_symbol(symbol)
    context = await gather_market_context(db, normalized_symbol)
    context_text = format_market_context_for_llm(context)
    custom_persona_prompt = ""
    self_correction_feedback = ""

    try:
        custom_persona_prompt = (
            await get_system_config_value(db, AI_CUSTOM_PERSONA_PROMPT_KEY, "")
        ) or ""
    except Exception as exc:
        logger.warning(
            "AI 커스텀 페르소나 프롬프트 조회 실패: symbol=%s error=%s",
            normalized_symbol,
            exc,
            exc_info=True,
        )

    try:
        self_correction_feedback = await _load_recent_failure_feedback(db, normalized_symbol)
    except Exception as exc:
        logger.warning(
            "AI 실패 사례 피드백 조회 실패: symbol=%s error=%s",
            normalized_symbol,
            exc,
            exc_info=True,
        )

    system_prompt = build_analysis_system_prompt(custom_persona_prompt, self_correction_feedback)

    try:
        routed_result = await AIProviderRouter(db).generate_structured_analysis(
            system_prompt=system_prompt,
            user_prompt=_build_analysis_user_prompt(normalized_symbol, context_text),
            response_model=AIAnalysisResponse,
        )
        analysis = routed_result.value
    except AIProviderRateLimitError as exc:
        logger.warning("AI 구조화 분석 quota 초과: symbol=%s error=%s", normalized_symbol, exc)
        raise
    except AIProviderUnavailableError as exc:
        logger.warning("AI provider 전체 사용 불가로 HOLD fallback을 사용합니다: symbol=%s error=%s", normalized_symbol, exc)
        analysis = _build_fallback_analysis()
    except Exception as exc:
        logger.error("AI 구조화 분석 실패: symbol=%s error=%s", normalized_symbol, exc, exc_info=True)
        analysis = _build_fallback_analysis()

    await _persist_ai_analysis_log(db, normalized_symbol, analysis)
    return analysis
