import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import AI_CALIBRATION_MIN_SUCCESS_RATE_KEY
from app.db.repository import AI_ENTRY_SCORE_THRESHOLD_KEY
from app.db.repository import AI_ENTRY_SHADOW_MODE_KEY
from app.db.repository import AI_MAX_CONCURRENT_POSITIONS_KEY
from app.db.repository import AI_TRADE_EXCLUDED_SYMBOLS_KEY
from app.db.repository import AI_TRADE_TARGET_SYMBOLS_KEY
from app.db.repository import get_system_config_value
from app.models.domain import AIAnalysisLog
from app.schemas.portfolio import AssetItem, PortfolioSummary
from app.services.trading.ai_analyst import gather_market_context
from app.services.trading.ai_analyst import is_fallback_news_item

logger = logging.getLogger(__name__)

DEFAULT_TRADE_TARGET_SYMBOLS = ("KRW-BTC", "KRW-ETH", "KRW-XRP")
DEFAULT_TRADE_EXCLUDED_SYMBOLS = ("KRW-DOGE",)
DEFAULT_ENTRY_SCORE_THRESHOLD = 70
DEFAULT_ENTRY_SHADOW_MODE = True
DEFAULT_CALIBRATION_MIN_SUCCESS_RATE = 45.0
DEFAULT_MAX_CONCURRENT_POSITIONS = 2
DEFAULT_MIN_CALIBRATED_CONFIDENCE = 85
MIN_POSITION_VALUE_KRW = 5_000.0


@dataclass(frozen=True, slots=True)
class EntryGateConfig:
    target_symbols: tuple[str, ...]
    excluded_symbols: tuple[str, ...]
    score_threshold: int
    shadow_mode: bool
    min_success_rate_pct: float
    max_concurrent_positions: int
    min_calibrated_confidence: int


@dataclass(frozen=True, slots=True)
class AIConfidenceCalibration:
    checked_count: int
    success_count: int
    success_rate_pct: float | None
    calibrated_confidence: int


@dataclass(frozen=True, slots=True)
class EntryScore:
    score: int
    components: dict[str, int]
    technical_ok: bool
    sentiment_ok: bool
    real_news_count: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EntryGateResult:
    allowed: bool
    score: int
    components: dict[str, int]
    reasons: tuple[str, ...]
    config: EntryGateConfig
    calibration: AIConfidenceCalibration
    shadow_mode: bool

    def to_log_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "score": self.score,
            "components": self.components,
            "reasons": list(self.reasons),
            "shadow_mode": self.shadow_mode,
            "calibrated_confidence": self.calibration.calibrated_confidence,
            "success_rate_pct": self.calibration.success_rate_pct,
            "checked_count": self.calibration.checked_count,
        }


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def parse_symbol_list_config(raw_value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    candidates: list[Any]
    try:
        payload = json.loads(str(raw_value or ""))
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, list):
        candidates = payload
    elif raw_value:
        candidates = str(raw_value).split(",")
    else:
        candidates = list(default)

    normalized: list[str] = []
    for item in candidates:
        symbol = normalize_symbol(str(item))
        if symbol and symbol not in normalized:
            normalized.append(symbol)

    return tuple(normalized or default)


def _parse_bool_config(raw_value: str | None, default: bool) -> bool:
    normalized = str(raw_value or "").strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _parse_int_config(raw_value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(raw_value).strip())
    except (TypeError, ValueError, AttributeError):
        return default
    if parsed < minimum or parsed > maximum:
        return default
    return parsed


def _parse_float_config(
    raw_value: str | None,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(str(raw_value).strip())
    except (TypeError, ValueError, AttributeError):
        return default
    if parsed < minimum or parsed > maximum:
        return default
    return parsed


async def load_entry_gate_config(
    db: AsyncSession,
    *,
    min_calibrated_confidence: int = DEFAULT_MIN_CALIBRATED_CONFIDENCE,
) -> EntryGateConfig:
    target_symbols = parse_symbol_list_config(
        await get_system_config_value(
            db,
            AI_TRADE_TARGET_SYMBOLS_KEY,
            default=json.dumps(DEFAULT_TRADE_TARGET_SYMBOLS),
        ),
        DEFAULT_TRADE_TARGET_SYMBOLS,
    )
    excluded_symbols = parse_symbol_list_config(
        await get_system_config_value(
            db,
            AI_TRADE_EXCLUDED_SYMBOLS_KEY,
            default=json.dumps(DEFAULT_TRADE_EXCLUDED_SYMBOLS),
        ),
        DEFAULT_TRADE_EXCLUDED_SYMBOLS,
    )
    score_threshold = _parse_int_config(
        await get_system_config_value(db, AI_ENTRY_SCORE_THRESHOLD_KEY),
        DEFAULT_ENTRY_SCORE_THRESHOLD,
        0,
        100,
    )
    shadow_mode = _parse_bool_config(
        await get_system_config_value(db, AI_ENTRY_SHADOW_MODE_KEY),
        DEFAULT_ENTRY_SHADOW_MODE,
    )
    min_success_rate_pct = _parse_float_config(
        await get_system_config_value(db, AI_CALIBRATION_MIN_SUCCESS_RATE_KEY),
        DEFAULT_CALIBRATION_MIN_SUCCESS_RATE,
        0.0,
        100.0,
    )
    max_concurrent_positions = _parse_int_config(
        await get_system_config_value(db, AI_MAX_CONCURRENT_POSITIONS_KEY),
        DEFAULT_MAX_CONCURRENT_POSITIONS,
        1,
        10,
    )

    return EntryGateConfig(
        target_symbols=target_symbols,
        excluded_symbols=excluded_symbols,
        score_threshold=score_threshold,
        shadow_mode=shadow_mode,
        min_success_rate_pct=min_success_rate_pct,
        max_concurrent_positions=max_concurrent_positions,
        min_calibrated_confidence=min_calibrated_confidence,
    )


def is_symbol_allowed(symbol: str, config: EntryGateConfig) -> bool:
    normalized_symbol = normalize_symbol(symbol)
    return normalized_symbol in config.target_symbols and normalized_symbol not in config.excluded_symbols


def filter_trade_symbols(symbols: list[str], config: EntryGateConfig) -> list[str]:
    filtered: list[str] = []
    for symbol in symbols:
        normalized_symbol = normalize_symbol(symbol)
        if is_symbol_allowed(normalized_symbol, config) and normalized_symbol not in filtered:
            filtered.append(normalized_symbol)
    return filtered


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_int(value: float, minimum: int = 0, maximum: int = 100) -> int:
    return max(min(int(round(value)), maximum), minimum)


async def load_buy_confidence_calibration(
    db: AsyncSession,
    symbol: str,
    raw_confidence: int,
) -> AIConfidenceCalibration:
    result = await db.execute(
        select(AIAnalysisLog.accuracy_label)
        .where(AIAnalysisLog.symbol == normalize_symbol(symbol))
        .where(AIAnalysisLog.decision == "BUY")
        .where(AIAnalysisLog.accuracy_label.in_(("SUCCESS", "FAIL")))
        .order_by(desc(AIAnalysisLog.accuracy_checked_at), desc(AIAnalysisLog.created_at))
        .limit(200)
    )
    labels = [str(label or "").upper() for label in result.scalars().all()]
    checked_count = len(labels)
    success_count = sum(1 for label in labels if label == "SUCCESS")
    success_rate_pct = (success_count / checked_count) * 100.0 if checked_count else None
    effective_rate = success_rate_pct if success_rate_pct is not None else 50.0
    calibrated_confidence = _clamp_int(raw_confidence * (effective_rate / 50.0))

    return AIConfidenceCalibration(
        checked_count=checked_count,
        success_count=success_count,
        success_rate_pct=success_rate_pct,
        calibrated_confidence=calibrated_confidence,
    )


def _find_portfolio_item(portfolio: PortfolioSummary, symbol: str) -> AssetItem | None:
    currency = normalize_symbol(symbol).split("-", 1)[1] if "-" in symbol else normalize_symbol(symbol)
    for item in portfolio.items:
        if item.currency.upper() == currency:
            return item
    return None


def _position_value(item: AssetItem | None) -> float:
    if item is None:
        return 0.0
    return max(_to_float(item.total_value) or 0.0, 0.0)


def _count_active_target_positions(
    portfolio: PortfolioSummary,
    config: EntryGateConfig,
) -> tuple[int, set[str]]:
    active_symbols: set[str] = set()
    for symbol in config.target_symbols:
        item = _find_portfolio_item(portfolio, symbol)
        if _position_value(item) >= MIN_POSITION_VALUE_KRW:
            active_symbols.add(symbol)
    return len(active_symbols), active_symbols


def score_entry_context(
    context: dict[str, Any],
    calibration: AIConfidenceCalibration,
    config: EntryGateConfig,
) -> EntryScore:
    technical = context.get("technical") if isinstance(context.get("technical"), dict) else {}
    sentiment = context.get("sentiment") if isinstance(context.get("sentiment"), dict) else {}
    news = context.get("news") if isinstance(context.get("news"), dict) else {}
    reasons: list[str] = []

    close = _to_float(technical.get("close"))
    sma20 = _to_float(technical.get("sma_20"))
    ema50 = _to_float(technical.get("ema_50"))
    rsi14 = _to_float(technical.get("rsi_14"))
    price_vs_sma20 = _to_float(technical.get("price_vs_sma20_pct"))

    above_sma20 = close is not None and sma20 is not None and close >= sma20
    above_ema50 = close is not None and ema50 is not None and close >= ema50
    rebound_candidate = (
        rsi14 is not None
        and 35.0 <= rsi14 <= 55.0
        and price_vs_sma20 is not None
        and price_vs_sma20 >= -1.0
    )

    technical_score = 0
    technical_ok = False
    if above_sma20 and above_ema50:
        technical_score = 28
        technical_ok = True
        reasons.append("가격이 SMA20과 EMA50 위에 있습니다.")
    elif above_sma20 or above_ema50:
        technical_score = 22
        technical_ok = True
        reasons.append("가격이 주요 추세선 중 하나를 회복했습니다.")
    elif rebound_candidate:
        technical_score = 20
        technical_ok = True
        reasons.append("RSI 과매도권 이후 반등 후보 구간입니다.")
    else:
        reasons.append("추세 회복 또는 RSI 반등 조건이 부족합니다.")

    if rsi14 is not None:
        if 45.0 <= rsi14 <= 65.0:
            technical_score += 7
        elif 40.0 <= rsi14 <= 70.0:
            technical_score += 4
        elif rebound_candidate:
            technical_score += 3
    technical_score = min(technical_score, 35)

    bb_upper = _to_float(technical.get("bb_upper_20_2"))
    bb_lower = _to_float(technical.get("bb_lower_20_2"))
    volatility_score = 5
    if close is not None and bb_upper is not None and bb_lower is not None and bb_upper > bb_lower:
        band_position = (close - bb_lower) / (bb_upper - bb_lower)
        if 0.2 <= band_position <= 0.8:
            volatility_score = 15
        elif 0.1 <= band_position <= 0.9:
            volatility_score = 10
        else:
            volatility_score = 4

    sentiment_score_raw = _to_float(sentiment.get("score"))
    sentiment_ok = sentiment_score_raw is not None and sentiment_score_raw >= 40.0
    if sentiment_score_raw is None:
        sentiment_score = 0
        reasons.append("시장심리 점수를 확인하지 못했습니다.")
    elif sentiment_score_raw >= 60.0:
        sentiment_score = 20
    elif sentiment_score_raw >= 50.0:
        sentiment_score = 16
    elif sentiment_score_raw >= 40.0:
        sentiment_score = 10
    else:
        sentiment_score = 0
        reasons.append("시장심리 점수가 40 미만입니다.")

    news_items = news.get("items")
    real_news = [
        item
        for item in (news_items if isinstance(news_items, list) else [])
        if isinstance(item, dict) and not is_fallback_news_item(item)
    ]
    news_score = 10 if real_news else 0
    if not real_news:
        reasons.append("실제 뉴스/RAG 근거가 없어 뉴스 점수는 0점입니다.")

    ai_score = min(calibration.calibrated_confidence // 5, 20)
    components = {
        "technical": technical_score,
        "volatility": volatility_score,
        "sentiment": sentiment_score,
        "news": news_score,
        "ai_confidence": ai_score,
    }
    total_score = sum(components.values())
    return EntryScore(
        score=total_score,
        components=components,
        technical_ok=technical_ok,
        sentiment_ok=sentiment_ok,
        real_news_count=len(real_news),
        reasons=tuple(reasons),
    )


async def evaluate_ai_buy_entry_gate(
    db: AsyncSession,
    *,
    symbol: str,
    analysis: AIAnalysisLog,
    portfolio: PortfolioSummary,
    min_calibrated_confidence: int = DEFAULT_MIN_CALIBRATED_CONFIDENCE,
) -> EntryGateResult:
    normalized_symbol = normalize_symbol(symbol)
    config = await load_entry_gate_config(
        db,
        min_calibrated_confidence=min_calibrated_confidence,
    )
    calibration = await load_buy_confidence_calibration(
        db,
        normalized_symbol,
        int(analysis.confidence),
    )
    blocking_reasons: list[str] = []

    if not is_symbol_allowed(normalized_symbol, config):
        blocking_reasons.append("허용 종목이 아니거나 제외 종목입니다.")

    if str(analysis.decision or "").upper() != "BUY":
        blocking_reasons.append("AI 최종 판단이 BUY가 아닙니다.")

    if analysis.recommended_weight <= 0:
        blocking_reasons.append("AI 추천 비중이 0 이하입니다.")

    if (
        calibration.success_rate_pct is not None
        and calibration.success_rate_pct < config.min_success_rate_pct
    ):
        blocking_reasons.append("심볼별 과거 AI BUY 적중률이 기준 미만입니다.")

    if calibration.calibrated_confidence < config.min_calibrated_confidence:
        blocking_reasons.append("보정 확신도가 기준 미만입니다.")

    active_position_count, active_symbols = _count_active_target_positions(portfolio, config)
    symbol_already_held = normalized_symbol in active_symbols
    if (
        not symbol_already_held
        and active_position_count >= config.max_concurrent_positions
    ):
        blocking_reasons.append("동시 보유 종목 수 상한에 도달했습니다.")

    if blocking_reasons:
        return EntryGateResult(
            allowed=False,
            score=0,
            components={},
            reasons=tuple(blocking_reasons),
            config=config,
            calibration=calibration,
            shadow_mode=config.shadow_mode,
        )

    try:
        context = await gather_market_context(db, normalized_symbol)
    except Exception as exc:
        logger.warning("AI BUY 진입 점수 컨텍스트 생성 실패: symbol=%s error=%s", symbol, exc)
        return EntryGateResult(
            allowed=False,
            score=0,
            components={},
            reasons=("시장 컨텍스트 생성에 실패했습니다.",),
            config=config,
            calibration=calibration,
            shadow_mode=config.shadow_mode,
        )

    entry_score = score_entry_context(context, calibration, config)
    if not entry_score.technical_ok:
        blocking_reasons.append("기술적 진입 조건을 통과하지 못했습니다.")
    if not entry_score.sentiment_ok:
        blocking_reasons.append("시장심리 조건을 통과하지 못했습니다.")
    if entry_score.score < config.score_threshold:
        blocking_reasons.append("진입 점수가 기준 미만입니다.")

    return EntryGateResult(
        allowed=not blocking_reasons,
        score=entry_score.score,
        components=entry_score.components,
        reasons=tuple([*entry_score.reasons, *blocking_reasons]),
        config=config,
        calibration=calibration,
        shadow_mode=config.shadow_mode,
    )
