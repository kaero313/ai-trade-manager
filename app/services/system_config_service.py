from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repository import AI_ANALYSIS_MAX_AGE_MINUTES_KEY
from app.db.repository import AI_BRIEFING_TIME_KEY
from app.db.repository import AI_CALIBRATION_MIN_SUCCESS_RATE_KEY
from app.db.repository import AI_CUSTOM_PERSONA_PROMPT_KEY
from app.db.repository import AI_ENTRY_SCORE_THRESHOLD_KEY
from app.db.repository import AI_ENTRY_SHADOW_MODE_KEY
from app.db.repository import AI_MAX_BUY_WEIGHT_PCT_KEY
from app.db.repository import AI_MAX_CONCURRENT_POSITIONS_KEY
from app.db.repository import AI_MIN_CONFIDENCE_TRADE_KEY
from app.db.repository import AI_PROVIDER_PRIORITY_KEY
from app.db.repository import AI_PROVIDER_SETTINGS_KEY
from app.db.repository import AI_PROVIDER_STATUS_KEY
from app.db.repository import AI_TRADE_EXCLUDED_SYMBOLS_KEY
from app.db.repository import AI_TRADE_TARGET_SYMBOLS_KEY
from app.db.repository import AUTONOMOUS_AI_INTERVAL_HOURS_KEY
from app.db.repository import AUTONOMOUS_AI_INTERVAL_MINUTES_KEY
from app.db.repository import HARD_STOP_LOSS_PCT_KEY
from app.db.repository import HARD_TAKE_PROFIT_PCT_KEY
from app.db.repository import LIVE_BUY_ENABLED_KEY
from app.db.repository import LIVE_ORDER_V2_ENABLED_KEY
from app.db.repository import MARKET_SENTIMENT_SNAPSHOT_KEY
from app.db.repository import MAX_ALLOCATION_PCT_KEY
from app.db.repository import NEWS_INTERVAL_HOURS_KEY
from app.db.repository import PAPER_TRADING_KRW_BALANCE_KEY
from app.db.repository import RAG_BUY_PRECHECK_NEWS_MAX_AGE_MINUTES_KEY
from app.db.repository import RAG_BUY_PRECHECK_NEWS_REFRESH_ENABLED_KEY
from app.db.repository import RAG_SCHEDULED_OPENAI_TRANSLATION_FALLBACK_ENABLED_KEY
from app.db.repository import SENTIMENT_INTERVAL_MINUTES_KEY
from app.db.repository import SLACK_PORTFOLIO_ALERT_SETTINGS_KEY
from app.db.repository import TRADING_MODE_KEY as _TRADING_MODE_CONFIG_KEY
from app.models.domain import SystemConfig


class SystemConfigCategory(StrEnum):
    PUBLIC_MUTABLE = "PUBLIC_MUTABLE"
    INTERNAL_STATE = "INTERNAL_STATE"
    DEDICATED_PROTECTED = "DEDICATED_PROTECTED"
    LEGACY_READ_ONLY = "LEGACY_READ_ONLY"


class SystemConfigServiceError(ValueError):
    def __init__(self, message: str, *, config_key: str | None = None) -> None:
        super().__init__(message)
        self.config_key = config_key


class SystemConfigValidationError(SystemConfigServiceError):
    pass


class SystemConfigConflictError(SystemConfigServiceError):
    pass


class SystemConfigProtectedError(SystemConfigServiceError):
    pass


class SystemConfigMissingError(SystemConfigServiceError):
    pass


Validator = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class SystemConfigDefinition:
    category: SystemConfigCategory
    validator: Validator | None = None


@dataclass(frozen=True, slots=True)
class SystemConfigMutation:
    config_key: str
    config_value: str
    expected_version: int


def _error(config_key: str, message: str) -> SystemConfigValidationError:
    return SystemConfigValidationError(f"{config_key}: {message}", config_key=config_key)


def _strict_int(config_key: str, minimum: int, maximum: int) -> Validator:
    def validate(raw_value: str) -> str:
        value = str(raw_value).strip()
        if len(value) > 32 or not re.fullmatch(r"[+-]?\d+", value):
            raise _error(config_key, "정수 값이 필요합니다.")
        try:
            number = int(value)
        except ValueError as exc:
            raise _error(config_key, "정수 값이 필요합니다.") from exc
        if not minimum <= number <= maximum:
            raise _error(config_key, f"{minimum}~{maximum} 범위여야 합니다.")
        return str(number)

    return validate


def _strict_decimal(config_key: str, minimum: str, maximum: str) -> Validator:
    lower = Decimal(minimum)
    upper = Decimal(maximum)

    def validate(raw_value: str) -> str:
        value = str(raw_value).strip()
        if len(value) > 64 or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value):
            raise _error(config_key, "지수 표기가 아닌 유한한 10진수 값이 필요합니다.")
        try:
            number = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise _error(config_key, "유효한 숫자 값이 필요합니다.") from exc
        if not number.is_finite():
            raise _error(config_key, "NaN 또는 Infinity를 저장할 수 없습니다.")
        if not lower <= number <= upper:
            raise _error(config_key, f"{minimum}~{maximum} 범위여야 합니다.")
        normalized = format(number.normalize(), "f")
        return "0" if normalized in {"-0", ""} else normalized

    return validate


def _strict_bool(config_key: str) -> Validator:
    def validate(raw_value: str) -> str:
        value = str(raw_value).strip().lower()
        if value not in {"true", "false"}:
            raise _error(config_key, "true 또는 false만 허용됩니다.")
        return value

    return validate


def _strict_time(config_key: str) -> Validator:
    def validate(raw_value: str) -> str:
        value = str(raw_value).strip()
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise _error(config_key, "HH:MM 형식의 유효한 시각이 필요합니다.")
        return value

    return validate


def _persona(raw_value: str) -> str:
    value = str(raw_value)
    if len(value) > 8_000:
        raise _error(AI_CUSTOM_PERSONA_PROMPT_KEY, "8,000자를 초과할 수 없습니다.")
    return value


def _json_value(config_key: str, raw_value: str) -> Any:
    try:
        return json.loads(str(raw_value))
    except (json.JSONDecodeError, TypeError) as exc:
        raise _error(config_key, "올바른 JSON 값이 필요합니다.") from exc


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _symbol_list(config_key: str, *, allow_empty: bool) -> Validator:
    def validate(raw_value: str) -> str:
        parsed = _json_value(config_key, raw_value)
        if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
            raise _error(config_key, "문자열로 구성된 JSON 배열이 필요합니다.")
        symbols = [item.strip().upper() for item in parsed]
        if not allow_empty and not symbols:
            raise _error(config_key, "최소 한 종목이 필요합니다.")
        if len(symbols) > 50:
            raise _error(config_key, "종목은 최대 50개까지 허용됩니다.")
        if any(not re.fullmatch(r"KRW-[A-Z0-9]{2,20}", symbol) for symbol in symbols):
            raise _error(config_key, "모든 종목은 KRW-* 형식이어야 합니다.")
        if len(symbols) != len(set(symbols)):
            raise _error(config_key, "중복 종목은 허용되지 않습니다.")
        return _canonical_json(symbols)

    return validate


_PROVIDERS = {"gemini", "openai"}
_PROVIDER_PURPOSES = {
    "trade_analysis",
    "buy_precheck",
    "portfolio_briefing",
    "chat",
    "news_sentiment",
    "news_translation",
    "backtest_briefing",
}


def _provider_priority(raw_value: str) -> str:
    parsed = _json_value(AI_PROVIDER_PRIORITY_KEY, raw_value)
    if not isinstance(parsed, list):
        raise _error(AI_PROVIDER_PRIORITY_KEY, "provider JSON 배열이 필요합니다.")
    providers = [str(item).strip().lower() for item in parsed]
    if len(providers) != len(_PROVIDERS) or set(providers) != _PROVIDERS:
        raise _error(AI_PROVIDER_PRIORITY_KEY, "gemini와 openai를 각각 한 번 포함해야 합니다.")
    return _canonical_json(providers)


def _provider_settings(raw_value: str) -> str:
    parsed = _json_value(AI_PROVIDER_SETTINGS_KEY, raw_value)
    if not isinstance(parsed, dict) or set(parsed) != _PROVIDERS:
        raise _error(AI_PROVIDER_SETTINGS_KEY, "gemini와 openai 설정이 모두 필요합니다.")

    normalized: dict[str, Any] = {}
    for provider, settings in parsed.items():
        if not isinstance(settings, dict):
            raise _error(AI_PROVIDER_SETTINGS_KEY, f"{provider} 설정은 객체여야 합니다.")
        if set(settings) - {"enabled", "model", "models"}:
            raise _error(AI_PROVIDER_SETTINGS_KEY, f"{provider}에 알 수 없는 필드가 있습니다.")
        if not isinstance(settings.get("enabled"), bool):
            raise _error(AI_PROVIDER_SETTINGS_KEY, f"{provider}.enabled는 boolean이어야 합니다.")
        raw_model = settings.get("model")
        if not isinstance(raw_model, str):
            raise _error(AI_PROVIDER_SETTINGS_KEY, f"{provider}.model은 문자열이어야 합니다.")
        model = raw_model.strip()
        if not 1 <= len(model) <= 128:
            raise _error(AI_PROVIDER_SETTINGS_KEY, f"{provider}.model은 1~128자여야 합니다.")
        item: dict[str, Any] = {"enabled": settings["enabled"], "model": model}
        if "models" in settings:
            models = settings["models"]
            if not isinstance(models, dict):
                raise _error(AI_PROVIDER_SETTINGS_KEY, f"{provider}.models는 객체여야 합니다.")
            if set(models) - _PROVIDER_PURPOSES:
                raise _error(AI_PROVIDER_SETTINGS_KEY, "지원하지 않는 AI purpose가 포함되어 있습니다.")
            if any(not isinstance(name, str) for name in models.values()):
                raise _error(AI_PROVIDER_SETTINGS_KEY, "purpose별 model은 문자열이어야 합니다.")
            normalized_models = {str(purpose): name.strip() for purpose, name in models.items()}
            if any(not 1 <= len(name) <= 128 for name in normalized_models.values()):
                raise _error(AI_PROVIDER_SETTINGS_KEY, "purpose별 model은 1~128자여야 합니다.")
            item["models"] = normalized_models
        normalized[provider] = item
    return _canonical_json(normalized)


_WEEKDAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
_SECTIONS = {"portfolio", "fear_index", "favorite_ai_signals", "market_impact_news"}
_DECISIONS = {"BUY", "SELL", "HOLD"}
_PRESETS = {
    "daily_once",
    "daily_twice",
    "weekday_once",
    "weekday_twice",
    "weekend_once",
    "weekly_once",
    "mon_wed_fri",
    "tue_thu",
}


def _strict_unique_string_list(
    config_key: str,
    value: Any,
    allowed: set[str],
    field: str,
    *,
    upper: bool = False,
) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        raise _error(config_key, f"{field}는 비어 있지 않은 문자열 배열이어야 합니다.")
    normalized = [(item.strip().upper() if upper else item.strip().lower()) for item in value]
    if any(item not in allowed for item in normalized):
        raise _error(config_key, f"{field}에 허용되지 않은 값이 있습니다.")
    if len(normalized) != len(set(normalized)):
        raise _error(config_key, f"{field}에 중복 값이 있습니다.")
    return normalized


def _slack_settings(raw_value: str) -> str:
    key = SLACK_PORTFOLIO_ALERT_SETTINGS_KEY
    parsed = _json_value(key, raw_value)
    if not isinstance(parsed, dict) or set(parsed) != {"enabled", "mode", "preset", "rules"}:
        raise _error(key, "enabled, mode, preset, rules 필드가 정확히 필요합니다.")
    if not isinstance(parsed["enabled"], bool) or parsed["mode"] not in {"preset", "advanced"}:
        raise _error(key, "enabled 또는 mode 값이 올바르지 않습니다.")
    if parsed["preset"] not in _PRESETS:
        raise _error(key, "지원하지 않는 preset입니다.")
    if not isinstance(parsed["rules"], list) or not 1 <= len(parsed["rules"]) <= 20:
        raise _error(key, "rules는 1~20개의 규칙 배열이어야 합니다.")

    normalized_rules: list[dict[str, Any]] = []
    ids: set[str] = set()
    for rule in parsed["rules"]:
        required = {"id", "enabled", "weekdays", "times", "sections", "signal_decisions", "min_confidence"}
        if not isinstance(rule, dict) or set(rule) != required:
            raise _error(key, "각 규칙의 필드 구성이 올바르지 않습니다.")
        if not isinstance(rule["id"], str):
            raise _error(key, "규칙 id는 문자열이어야 합니다.")
        rule_id = rule["id"].strip().lower()
        if not re.fullmatch(r"[a-z0-9_-]{1,64}", rule_id) or rule_id in ids:
            raise _error(key, "규칙 id가 유효하지 않거나 중복되었습니다.")
        ids.add(rule_id)
        if not isinstance(rule["enabled"], bool):
            raise _error(key, "규칙 enabled는 boolean이어야 합니다.")
        weekdays = _strict_unique_string_list(key, rule["weekdays"], _WEEKDAYS, "weekdays")
        sections = _strict_unique_string_list(key, rule["sections"], _SECTIONS, "sections")
        decisions = _strict_unique_string_list(
            key, rule["signal_decisions"], _DECISIONS, "signal_decisions", upper=True
        )
        if not isinstance(rule["times"], list) or not rule["times"]:
            raise _error(key, "times는 비어 있지 않은 배열이어야 합니다.")
        times = [_strict_time(key)(str(value)) for value in rule["times"]]
        if len(times) != len(set(times)):
            raise _error(key, "times에 중복 값이 있습니다.")
        confidence = rule["min_confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, int) or not 0 <= confidence <= 100:
            raise _error(key, "min_confidence는 0~100 정수여야 합니다.")
        normalized_rules.append(
            {
                "id": rule_id,
                "enabled": rule["enabled"],
                "weekdays": weekdays,
                "times": times,
                "sections": sections,
                "signal_decisions": decisions,
                "min_confidence": confidence,
            }
        )
    return _canonical_json(
        {
            "enabled": parsed["enabled"],
            "mode": parsed["mode"],
            "preset": parsed["preset"],
            "rules": normalized_rules,
        }
    )


SYSTEM_CONFIG_REGISTRY: Mapping[str, SystemConfigDefinition] = {
    NEWS_INTERVAL_HOURS_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_int(NEWS_INTERVAL_HOURS_KEY, 1, 23)),
    SENTIMENT_INTERVAL_MINUTES_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_int(SENTIMENT_INTERVAL_MINUTES_KEY, 1, 59)),
    AI_BRIEFING_TIME_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_time(AI_BRIEFING_TIME_KEY)),
    AUTONOMOUS_AI_INTERVAL_MINUTES_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_int(AUTONOMOUS_AI_INTERVAL_MINUTES_KEY, 1, 1440)),
    MAX_ALLOCATION_PCT_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_decimal(MAX_ALLOCATION_PCT_KEY, "0", "100")),
    HARD_TAKE_PROFIT_PCT_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_decimal(HARD_TAKE_PROFIT_PCT_KEY, "0", "1000")),
    HARD_STOP_LOSS_PCT_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_decimal(HARD_STOP_LOSS_PCT_KEY, "-1000", "0")),
    AI_MIN_CONFIDENCE_TRADE_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_int(AI_MIN_CONFIDENCE_TRADE_KEY, 0, 100)),
    AI_ANALYSIS_MAX_AGE_MINUTES_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_int(AI_ANALYSIS_MAX_AGE_MINUTES_KEY, 1, 1440)),
    AI_CUSTOM_PERSONA_PROMPT_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _persona),
    LIVE_BUY_ENABLED_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_bool(LIVE_BUY_ENABLED_KEY)),
    AI_MAX_BUY_WEIGHT_PCT_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_decimal(AI_MAX_BUY_WEIGHT_PCT_KEY, "0", "30")),
    AI_TRADE_TARGET_SYMBOLS_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _symbol_list(AI_TRADE_TARGET_SYMBOLS_KEY, allow_empty=False)),
    AI_TRADE_EXCLUDED_SYMBOLS_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _symbol_list(AI_TRADE_EXCLUDED_SYMBOLS_KEY, allow_empty=True)),
    AI_ENTRY_SCORE_THRESHOLD_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_int(AI_ENTRY_SCORE_THRESHOLD_KEY, 0, 100)),
    AI_ENTRY_SHADOW_MODE_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_bool(AI_ENTRY_SHADOW_MODE_KEY)),
    AI_CALIBRATION_MIN_SUCCESS_RATE_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_decimal(AI_CALIBRATION_MIN_SUCCESS_RATE_KEY, "0", "100")),
    AI_MAX_CONCURRENT_POSITIONS_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_int(AI_MAX_CONCURRENT_POSITIONS_KEY, 1, 10)),
    RAG_SCHEDULED_OPENAI_TRANSLATION_FALLBACK_ENABLED_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_bool(RAG_SCHEDULED_OPENAI_TRANSLATION_FALLBACK_ENABLED_KEY)),
    RAG_BUY_PRECHECK_NEWS_REFRESH_ENABLED_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_bool(RAG_BUY_PRECHECK_NEWS_REFRESH_ENABLED_KEY)),
    RAG_BUY_PRECHECK_NEWS_MAX_AGE_MINUTES_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _strict_int(RAG_BUY_PRECHECK_NEWS_MAX_AGE_MINUTES_KEY, 1, 1440)),
    AI_PROVIDER_PRIORITY_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _provider_priority),
    AI_PROVIDER_SETTINGS_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _provider_settings),
    SLACK_PORTFOLIO_ALERT_SETTINGS_KEY: SystemConfigDefinition(SystemConfigCategory.PUBLIC_MUTABLE, _slack_settings),
    PAPER_TRADING_KRW_BALANCE_KEY: SystemConfigDefinition(SystemConfigCategory.INTERNAL_STATE),
    MARKET_SENTIMENT_SNAPSHOT_KEY: SystemConfigDefinition(SystemConfigCategory.INTERNAL_STATE),
    AI_PROVIDER_STATUS_KEY: SystemConfigDefinition(SystemConfigCategory.INTERNAL_STATE),
    LIVE_ORDER_V2_ENABLED_KEY: SystemConfigDefinition(SystemConfigCategory.DEDICATED_PROTECTED),
    _TRADING_MODE_CONFIG_KEY: SystemConfigDefinition(SystemConfigCategory.DEDICATED_PROTECTED),
    AUTONOMOUS_AI_INTERVAL_HOURS_KEY: SystemConfigDefinition(SystemConfigCategory.LEGACY_READ_ONLY),
}

SCHEDULER_RELOAD_CONFIG_KEYS = frozenset(
    {
        NEWS_INTERVAL_HOURS_KEY,
        SENTIMENT_INTERVAL_MINUTES_KEY,
        AI_BRIEFING_TIME_KEY,
        AUTONOMOUS_AI_INTERVAL_HOURS_KEY,
        AUTONOMOUS_AI_INTERVAL_MINUTES_KEY,
        SLACK_PORTFOLIO_ALERT_SETTINGS_KEY,
    }
)


def normalize_public_config_value(config_key: str, config_value: str) -> str:
    if not isinstance(config_key, str) or not isinstance(config_value, str):
        raise SystemConfigValidationError("config_key와 config_value는 문자열이어야 합니다.")
    raw_key = config_key
    key = raw_key.strip()
    if not key or raw_key != key:
        raise SystemConfigValidationError(
            "config_key 앞뒤 공백은 허용되지 않습니다.", config_key=key or None
        )
    definition = SYSTEM_CONFIG_REGISTRY.get(key)
    if definition is None:
        raise SystemConfigValidationError(f"알 수 없는 SystemConfig 키입니다: {key}", config_key=key)
    if definition.category is SystemConfigCategory.DEDICATED_PROTECTED:
        raise SystemConfigProtectedError(
            f"보호된 설정은 전용 안전 경계에서만 변경할 수 있습니다: {key}",
            config_key=key,
        )
    if definition.category is not SystemConfigCategory.PUBLIC_MUTABLE or definition.validator is None:
        raise SystemConfigValidationError(
            f"일반 설정 API에서 변경할 수 없는 SystemConfig 키입니다: {key}",
            config_key=key,
        )
    return definition.validator(config_value)


async def update_public_system_configs(
    db: AsyncSession,
    mutations: Sequence[SystemConfigMutation],
) -> list[SystemConfig]:
    if not mutations:
        raise SystemConfigValidationError("최소 한 개의 설정 변경이 필요합니다.")

    if any(
        not isinstance(item.config_key, str) or not isinstance(item.config_value, str)
        for item in mutations
    ):
        raise SystemConfigValidationError("config_key와 config_value는 문자열이어야 합니다.")
    raw_keys = [item.config_key for item in mutations]
    keys = [key.strip() for key in raw_keys]
    if (
        any(not key or raw != key for raw, key in zip(raw_keys, keys, strict=True))
        or len(keys) != len(set(keys))
    ):
        raise SystemConfigValidationError("config_key는 비어 있거나 중복될 수 없습니다.")
    if any(
        isinstance(item.expected_version, bool)
        or not isinstance(item.expected_version, int)
        or item.expected_version < 1
        for item in mutations
    ):
        raise SystemConfigValidationError("expected_version은 1 이상의 정수여야 합니다.")
    canonical_by_key = {
        key: normalize_public_config_value(key, item.config_value)
        for key, item in zip(keys, mutations, strict=True)
    }
    expected_by_key = {
        key: item.expected_version for key, item in zip(keys, mutations, strict=True)
    }
    lock_keys = set(keys)
    if lock_keys & {LIVE_BUY_ENABLED_KEY, AI_ENTRY_SHADOW_MODE_KEY}:
        lock_keys.update({LIVE_BUY_ENABLED_KEY, AI_ENTRY_SHADOW_MODE_KEY})

    try:
        result = await db.execute(
            select(SystemConfig)
            .where(SystemConfig.config_key.in_(sorted(lock_keys)))
            .order_by(SystemConfig.config_key)
            .with_for_update()
        )
        rows_by_key = {row.config_key: row for row in result.scalars().all()}
        missing = sorted(lock_keys - rows_by_key.keys())
        if missing:
            raise SystemConfigMissingError(
                f"필수 SystemConfig 행이 없습니다: {', '.join(missing)}",
                config_key=missing[0],
            )
        for key in keys:
            row = rows_by_key[key]
            if row.version != expected_by_key[key]:
                raise SystemConfigConflictError(
                    f"설정 버전이 변경되었습니다: {key} (expected={expected_by_key[key]}, actual={row.version})",
                    config_key=key,
                )

        merged = {key: row.config_value for key, row in rows_by_key.items()}
        merged.update(canonical_by_key)
        if merged.get(LIVE_BUY_ENABLED_KEY) == "true" and merged.get(AI_ENTRY_SHADOW_MODE_KEY) == "true":
            raise SystemConfigValidationError(
                "live_buy_enabled=true와 ai_entry_shadow_mode=true는 동시에 저장할 수 없습니다."
            )

        updated: list[SystemConfig] = []
        for key in sorted(keys):
            row = rows_by_key[key]
            row.config_value = canonical_by_key[key]
            row.version += 1
            updated.append(row)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    for row in updated:
        await db.refresh(row)
    return updated


async def reset_ai_provider_status(
    db: AsyncSession,
    *,
    expected_version: int,
) -> SystemConfig:
    if (
        isinstance(expected_version, bool)
        or not isinstance(expected_version, int)
        or expected_version < 1
    ):
        raise SystemConfigValidationError("expected_version은 1 이상의 정수여야 합니다.")
    try:
        row = (
            await db.execute(
                select(SystemConfig)
                .where(SystemConfig.config_key == AI_PROVIDER_STATUS_KEY)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise SystemConfigMissingError(
                "AI provider 상태 설정 행이 없습니다.", config_key=AI_PROVIDER_STATUS_KEY
            )
        if row.version != expected_version:
            raise SystemConfigConflictError(
                f"설정 버전이 변경되었습니다: {AI_PROVIDER_STATUS_KEY} "
                f"(expected={expected_version}, actual={row.version})",
                config_key=AI_PROVIDER_STATUS_KEY,
            )
        row.config_value = "{}"
        row.version += 1
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(row)
    return row


async def mutate_internal_json_config(
    db: AsyncSession,
    *,
    config_key: str,
    mutator: Callable[[dict[str, Any]], dict[str, Any]],
) -> SystemConfig:
    definition = SYSTEM_CONFIG_REGISTRY.get(config_key)
    if definition is None or definition.category is not SystemConfigCategory.INTERNAL_STATE:
        raise SystemConfigProtectedError(
            f"내부 상태 writer가 변경할 수 없는 키입니다: {config_key}", config_key=config_key
        )
    try:
        row = (
            await db.execute(
                select(SystemConfig).where(SystemConfig.config_key == config_key).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise SystemConfigMissingError(
                f"필수 SystemConfig 행이 없습니다: {config_key}", config_key=config_key
            )
        parsed = _json_value(config_key, row.config_value)
        if not isinstance(parsed, dict):
            parsed = {}
        updated = mutator(dict(parsed))
        if not isinstance(updated, dict):
            raise SystemConfigValidationError(
                "내부 JSON mutator는 객체를 반환해야 합니다.", config_key=config_key
            )
        row.config_value = _canonical_json(updated)
        row.version += 1
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(row)
    return row
