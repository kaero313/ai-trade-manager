import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.provider_router import AIProviderRouter
from app.services.ai.provider_router import AIProviderUnavailableError

logger = logging.getLogger(__name__)

_FALLBACK_SCORE = 50
_FALLBACK_SUMMARY = [
    "AI 감성 분석을 완료하지 못했습니다.",
    "시장 변동성이 높을 수 있으니 보수적으로 대응하세요.",
    "잠시 후 다시 시도해 주세요.",
]


def _build_sentiment_prompt(news_list: list[dict[str, Any]]) -> str:
    titles: list[str] = []
    for item in news_list:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if title:
            titles.append(title)

    if not titles:
        titles.append("최신 뉴스 없음")

    headlines = "\n".join(f"{idx + 1}. {title}" for idx, title in enumerate(titles))
    return (
        "아래는 최신 가상자산 관련 뉴스 헤드라인 목록입니다.\n"
        f"{headlines}\n\n"
        "현재 시장의 탐욕/공포 심리를 0~100점(100은 극단적 탐욕)으로 평가하고, "
        "가장 중요한 호재/악재를 3줄로 요약해 주세요. "
        '반드시 JSON 형식({"score": int, "summary": [str, str, str]})으로만 응답하세요.'
    )


def _extract_json_text(raw_text: str) -> str | None:
    text = raw_text.strip()
    if not text:
        return None

    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()

    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return None

    return text[start_idx : end_idx + 1].strip()


def _normalize_score(raw_score: Any) -> int:
    try:
        score = int(float(raw_score))
    except (TypeError, ValueError):
        return _FALLBACK_SCORE
    return max(0, min(100, score))


def _normalize_summary(raw_summary: Any) -> list[str]:
    if isinstance(raw_summary, list):
        summary = [str(item).strip() for item in raw_summary if str(item).strip()]
    elif isinstance(raw_summary, str) and raw_summary.strip():
        summary = [raw_summary.strip()]
    else:
        summary = []

    while len(summary) < 3:
        summary.append(_FALLBACK_SUMMARY[len(summary)])
    return summary[:3]


def _parse_sentiment_result(raw_response: str) -> dict[str, Any] | None:
    json_text = _extract_json_text(raw_response)
    if not json_text:
        return None

    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    return {
        "score": _normalize_score(payload.get("score")),
        "summary": _normalize_summary(payload.get("summary")),
    }


def _fallback_result() -> dict[str, Any]:
    return {
        "score": _FALLBACK_SCORE,
        "summary": list(_FALLBACK_SUMMARY),
    }


async def analyze_market_sentiment(
    news_list: list[dict[str, Any]],
    db: AsyncSession,
) -> dict[str, Any]:
    prompt = _build_sentiment_prompt(news_list)

    try:
        result = await AIProviderRouter(db).generate_report(prompt)
    except AIProviderUnavailableError as exc:
        logger.error("뉴스 감성 분석 provider를 사용할 수 없습니다: %s", exc)
        return _fallback_result()

    parsed = _parse_sentiment_result(result.value)
    if parsed is not None:
        return parsed

    logger.warning(
        "뉴스 감성 분석 JSON 파싱 실패: provider=%s model=%s",
        result.provider,
        result.model,
    )
    return _fallback_result()
