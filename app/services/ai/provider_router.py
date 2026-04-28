from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.repository import AI_PROVIDER_PRIORITY_KEY
from app.db.repository import AI_PROVIDER_SETTINGS_KEY
from app.db.repository import AI_PROVIDER_STATUS_KEY
from app.db.repository import DEFAULT_AI_PROVIDER_PRIORITY_VALUE
from app.db.repository import DEFAULT_AI_PROVIDER_SETTINGS_VALUE
from app.db.repository import DEFAULT_AI_PROVIDER_STATUS_VALUE
from app.db.repository import get_system_config_value
from app.db.repository import upsert_system_config
from app.services.ai.analyzer import AIAnalyzerFactory
from app.services.ai.providers.base import AIProviderRateLimitError
from app.services.ai.providers.base import is_provider_rate_limit_error
from app.services.ai.providers.base import normalize_utc
from app.services.ai.providers.base import resolve_provider_block_until
from app.services.ai.providers.base import utc_now
from app.services.ai.providers.gemini import GEMINI_TEXT_MODEL
from app.services.ai.providers.openai import OPENAI_TEXT_MODEL

logger = logging.getLogger(__name__)

SUPPORTED_AI_PROVIDERS = ("gemini", "openai")
DEFAULT_PROVIDER_MODELS = {
    "gemini": GEMINI_TEXT_MODEL,
    "openai": OPENAI_TEXT_MODEL,
}

T = TypeVar("T")
StructuredResponseT = TypeVar("StructuredResponseT", bound=BaseModel)


@dataclass(frozen=True)
class AIProviderCandidate:
    provider: str
    model: str


@dataclass(frozen=True)
class AIProviderExecutionResult(Generic[T]):
    value: T
    provider: str
    model: str


class AIProviderUnavailableError(RuntimeError):
    """설정된 AI provider를 모두 사용할 수 없는 경우."""


def _loads_json(raw_value: str | None, fallback: Any) -> Any:
    if raw_value is None:
        return fallback
    try:
        parsed = json.loads(raw_value)
    except Exception:
        return fallback
    return parsed


def _normalize_priority(raw_value: Any) -> list[str]:
    if not isinstance(raw_value, list):
        raw_value = _loads_json(DEFAULT_AI_PROVIDER_PRIORITY_VALUE, ["gemini", "openai"])

    priority: list[str] = []
    for item in raw_value:
        provider = str(item or "").strip().lower()
        if provider in SUPPORTED_AI_PROVIDERS and provider not in priority:
            priority.append(provider)

    for provider in SUPPORTED_AI_PROVIDERS:
        if provider not in priority:
            priority.append(provider)

    return priority


def _normalize_settings(raw_value: Any) -> dict[str, dict[str, Any]]:
    defaults = _loads_json(DEFAULT_AI_PROVIDER_SETTINGS_VALUE, {})
    if not isinstance(raw_value, dict):
        raw_value = defaults

    normalized: dict[str, dict[str, Any]] = {}
    for provider in SUPPORTED_AI_PROVIDERS:
        provider_defaults = defaults.get(provider, {}) if isinstance(defaults, dict) else {}
        provider_settings = raw_value.get(provider, {}) if isinstance(raw_value, dict) else {}
        if not isinstance(provider_settings, dict):
            provider_settings = {}

        enabled = provider_settings.get("enabled", provider_defaults.get("enabled", True))
        model = str(
            provider_settings.get("model")
            or provider_defaults.get("model")
            or DEFAULT_PROVIDER_MODELS[provider]
        ).strip()

        normalized[provider] = {
            "enabled": bool(enabled),
            "model": model or DEFAULT_PROVIDER_MODELS[provider],
        }

    return normalized


def _normalize_status(raw_value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_value, dict):
        raw_value = _loads_json(DEFAULT_AI_PROVIDER_STATUS_VALUE, {})
    if not isinstance(raw_value, dict):
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for provider, status in raw_value.items():
        provider_name = str(provider or "").strip().lower()
        if provider_name not in SUPPORTED_AI_PROVIDERS or not isinstance(status, dict):
            continue
        normalized[provider_name] = dict(status)
    return normalized


def _parse_datetime(raw_value: object) -> datetime | None:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return None
    text = raw_value.strip().replace("Z", "+00:00")
    try:
        return normalize_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def _serialize_datetime(value: datetime) -> str:
    return normalize_utc(value).isoformat().replace("+00:00", "Z")


def _has_valid_api_key(provider: str) -> bool:
    raw_key = settings.GEMINI_API_KEY if provider == "gemini" else settings.OPENAI_API_KEY
    api_key = str(raw_key or "").strip()
    if not api_key:
        return False

    normalized = api_key.lower()
    if normalized.startswith("your_"):
        return False
    if normalized.endswith("_here") or normalized.endswith("here"):
        return False
    return True


def resolve_provider_candidates(
    *,
    priority_value: Any,
    settings_value: Any,
    status_value: Any,
    now: datetime | None = None,
    preferred_provider: str | None = None,
    available_providers: Mapping[str, bool] | None = None,
) -> list[AIProviderCandidate]:
    current = normalize_utc(now or utc_now())
    priority = _normalize_priority(priority_value)
    normalized_preferred = str(preferred_provider or "").strip().lower()
    if normalized_preferred in SUPPORTED_AI_PROVIDERS:
        priority = [
            normalized_preferred,
            *[provider for provider in priority if provider != normalized_preferred],
        ]

    provider_settings = _normalize_settings(settings_value)
    provider_status = _normalize_status(status_value)
    availability = available_providers or {
        provider: _has_valid_api_key(provider) for provider in SUPPORTED_AI_PROVIDERS
    }

    candidates: list[AIProviderCandidate] = []
    for provider in priority:
        if not bool(availability.get(provider)):
            continue

        current_settings = provider_settings.get(provider, {})
        if not bool(current_settings.get("enabled", True)):
            continue

        blocked_until = _parse_datetime(provider_status.get(provider, {}).get("blocked_until"))
        if blocked_until is not None and blocked_until > current:
            continue

        model = str(current_settings.get("model") or DEFAULT_PROVIDER_MODELS[provider]).strip()
        candidates.append(AIProviderCandidate(provider=provider, model=model))

    return candidates


class AIProviderRouter:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _load_config_values(self) -> tuple[Any, Any, Any]:
        priority_raw = await get_system_config_value(
            self.db,
            AI_PROVIDER_PRIORITY_KEY,
            DEFAULT_AI_PROVIDER_PRIORITY_VALUE,
        )
        settings_raw = await get_system_config_value(
            self.db,
            AI_PROVIDER_SETTINGS_KEY,
            DEFAULT_AI_PROVIDER_SETTINGS_VALUE,
        )
        status_raw = await get_system_config_value(
            self.db,
            AI_PROVIDER_STATUS_KEY,
            DEFAULT_AI_PROVIDER_STATUS_VALUE,
        )
        return (
            _loads_json(priority_raw, ["gemini", "openai"]),
            _loads_json(settings_raw, {}),
            _loads_json(status_raw, {}),
        )

    async def get_candidates(self, preferred_provider: str | None = None) -> list[AIProviderCandidate]:
        priority_value, settings_value, status_value = await self._load_config_values()
        return resolve_provider_candidates(
            priority_value=priority_value,
            settings_value=settings_value,
            status_value=status_value,
            preferred_provider=preferred_provider,
        )

    async def _load_status(self) -> dict[str, dict[str, Any]]:
        status_raw = await get_system_config_value(
            self.db,
            AI_PROVIDER_STATUS_KEY,
            DEFAULT_AI_PROVIDER_STATUS_VALUE,
        )
        return _normalize_status(_loads_json(status_raw, {}))

    async def _save_status(self, status: dict[str, dict[str, Any]]) -> None:
        await upsert_system_config(
            self.db,
            AI_PROVIDER_STATUS_KEY,
            json.dumps(status, ensure_ascii=False, sort_keys=True),
            "AI provider별 쿼터 차단/성공 상태(JSON 객체)",
        )

    async def mark_success(self, provider: str) -> None:
        provider_name = provider.strip().lower()
        status = await self._load_status()
        current = status.get(provider_name, {})
        current.pop("blocked_until", None)
        current.pop("reason", None)
        current.pop("last_error", None)
        current.pop("last_error_at", None)
        current["last_success_at"] = _serialize_datetime(utc_now())
        status[provider_name] = current
        await self._save_status(status)

    async def mark_error(self, provider: str, error: Exception) -> None:
        provider_name = provider.strip().lower()
        status = await self._load_status()
        current = status.get(provider_name, {})
        current["last_error_at"] = _serialize_datetime(utc_now())
        current["last_error"] = str(error)[:500]
        status[provider_name] = current
        await self._save_status(status)

    async def mark_rate_limited(self, provider: str, error: Exception) -> None:
        provider_name = provider.strip().lower()
        blocked_until = getattr(error, "blocked_until", None)
        if not isinstance(blocked_until, datetime):
            blocked_until = resolve_provider_block_until(provider_name, error)

        reason = str(getattr(error, "reason", "") or "rate_limit")
        status = await self._load_status()
        current = status.get(provider_name, {})
        current["blocked_until"] = _serialize_datetime(blocked_until)
        current["reason"] = reason
        current["last_error_at"] = _serialize_datetime(utc_now())
        current["last_error"] = str(error)[:500]
        status[provider_name] = current
        await self._save_status(status)

    async def execute(
        self,
        operation: Callable[[AIProviderCandidate], Awaitable[T]],
        *,
        preferred_provider: str | None = None,
    ) -> AIProviderExecutionResult[T]:
        candidates = await self.get_candidates(preferred_provider=preferred_provider)
        if not candidates:
            raise AIProviderUnavailableError("사용 가능한 AI provider가 없습니다.")

        last_error: Exception | None = None
        for candidate in candidates:
            try:
                value = await operation(candidate)
            except AIProviderRateLimitError as exc:
                last_error = exc
                await self.mark_rate_limited(candidate.provider, exc)
                logger.warning(
                    "AI provider 한도 도달로 다음 provider를 시도합니다: provider=%s model=%s error=%s",
                    candidate.provider,
                    candidate.model,
                    exc,
                )
                continue
            except Exception as exc:
                last_error = exc
                if is_provider_rate_limit_error(candidate.provider, exc):
                    await self.mark_rate_limited(candidate.provider, exc)
                else:
                    await self.mark_error(candidate.provider, exc)
                logger.warning(
                    "AI provider 호출 실패로 다음 provider를 시도합니다: provider=%s model=%s error=%s",
                    candidate.provider,
                    candidate.model,
                    exc,
                    exc_info=True,
                )
                continue

            await self.mark_success(candidate.provider)
            return AIProviderExecutionResult(
                value=value,
                provider=candidate.provider,
                model=candidate.model,
            )

        detail = f"마지막 오류: {last_error}" if last_error is not None else "후보 없음"
        raise AIProviderUnavailableError(f"모든 AI provider 호출에 실패했습니다. {detail}")

    async def generate_report(
        self,
        prompt: str,
        *,
        preferred_provider: str | None = None,
    ) -> AIProviderExecutionResult[str]:
        async def _operation(candidate: AIProviderCandidate) -> str:
            analyzer = AIAnalyzerFactory.get_analyzer(candidate.provider, model=candidate.model)
            return await analyzer.generate_report(prompt)

        return await self.execute(_operation, preferred_provider=preferred_provider)

    async def generate_structured_analysis(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredResponseT],
        preferred_provider: str | None = None,
    ) -> AIProviderExecutionResult[StructuredResponseT]:
        async def _operation(candidate: AIProviderCandidate) -> StructuredResponseT:
            analyzer = AIAnalyzerFactory.get_analyzer(candidate.provider, model=candidate.model)
            return await analyzer.generate_structured_analysis(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
            )

        return await self.execute(_operation, preferred_provider=preferred_provider)
