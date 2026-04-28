import math
import re
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypeVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel

SYSTEM_PROMPT = (
    "당신은 월스트리트의 냉철하고 전문적인 크립토/주식 포트폴리오 분석가입니다. "
    "주어진 포트폴리오의 자산 비중과 수익률을 객관적으로 분석하십시오. "
    "리스크가 높은 자산은 경고하며, 다음 트레이딩 액션에 대한 시나리오 기반의 조언(3문단 이내)을 "
    "읽기 쉬운 마크다운 텍스트 템플릿 포맷으로 제공하십시오."
)


StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)

DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 300
OPENAI_INSUFFICIENT_QUOTA_BLOCK_SECONDS = 24 * 60 * 60
PACIFIC_TIMEZONE = ZoneInfo("America/Los_Angeles")


class AIProviderRateLimitError(RuntimeError):
    """Provider 쿼터/레이트 리밋으로 다음 provider fallback이 필요한 경우."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        reason: str = "rate_limit",
        blocked_until: datetime | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.reason = reason
        self.blocked_until = blocked_until


def utc_now() -> datetime:
    return datetime.now(UTC)


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def next_pacific_midnight(now: datetime | None = None) -> datetime:
    current = normalize_utc(now or utc_now()).astimezone(PACIFIC_TIMEZONE)
    next_day = current.date() + timedelta(days=1)
    reset_at = datetime.combine(next_day, datetime.min.time(), tzinfo=PACIFIC_TIMEZONE)
    return reset_at.astimezone(UTC)


def parse_duration_seconds(raw_value: object) -> int | None:
    text = str(raw_value or "").strip().lower()
    if not text:
        return None

    if text.isdigit():
        return max(1, int(text))

    total = 0.0
    matched = False
    for value, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h)", text):
        matched = True
        number = float(value)
        if unit == "ms":
            total += number / 1000
        elif unit == "s":
            total += number
        elif unit == "m":
            total += number * 60
        elif unit == "h":
            total += number * 3600

    if not matched:
        return None

    return max(1, int(math.ceil(total)))


def extract_retry_delay_seconds(error: Exception) -> int | None:
    message = str(error)
    retry_delay_match = re.search(
        r"retry_delay\s*\{[^}]*seconds:\s*(\d+)",
        message,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if retry_delay_match:
        return max(1, int(retry_delay_match.group(1)))

    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        for key in (
            "retry-after",
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens",
        ):
            value = headers.get(key) if hasattr(headers, "get") else None
            seconds = parse_duration_seconds(value)
            if seconds is not None:
                return seconds

    return None


def is_provider_rate_limit_error(provider: str, error: Exception) -> bool:
    message = str(error).lower()
    status_code = getattr(error, "status_code", None)
    if status_code == 429:
        return True

    if provider == "gemini":
        return (
            "resource_exhausted" in message
            or "quota" in message
            or "429" in message
            or "rate limit" in message
            or "retry_delay" in message
            or "503" in message
            or "unavailable" in message
            or "high demand" in message
            or "overloaded" in message
        )

    if provider == "openai":
        return (
            "rate limit" in message
            or "insufficient_quota" in message
            or "quota" in message
            or "429" in message
        )

    return "rate limit" in message or "quota" in message or "429" in message


def resolve_provider_block_until(
    provider: str,
    error: Exception,
    *,
    now: datetime | None = None,
) -> datetime:
    current = normalize_utc(now or utc_now())
    message = str(error).lower()
    retry_delay_seconds = extract_retry_delay_seconds(error)

    if provider == "gemini":
        if retry_delay_seconds is not None:
            return current + timedelta(seconds=retry_delay_seconds)
        if (
            "free_tier_requests" in message
            or "requests per day" in message
            or "request per day" in message
            or "rpd" in message
            or "daily" in message
        ):
            return next_pacific_midnight(current)
        return current + timedelta(seconds=DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS)

    if provider == "openai":
        if "insufficient_quota" in message or "billing" in message:
            return current + timedelta(seconds=OPENAI_INSUFFICIENT_QUOTA_BLOCK_SECONDS)
        if retry_delay_seconds is not None:
            return current + timedelta(seconds=retry_delay_seconds)
        return current + timedelta(seconds=DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS)

    return current + timedelta(seconds=DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS)


class BaseAIAnalyzer(Protocol):
    async def generate_report(self, portfolio_str: str) -> str:
        ...

    async def generate_structured_analysis(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredResponseT],
    ) -> StructuredResponseT:
        ...
