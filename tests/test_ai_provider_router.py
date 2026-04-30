from datetime import UTC, datetime, timedelta

from app.services.ai.provider_router import resolve_provider_candidates
from app.services.ai.provider_router import resolve_provider_runtime_status
from app.services.ai.providers.base import resolve_provider_block_until


def _settings() -> dict[str, dict[str, object]]:
    return {
        "gemini": {"enabled": True, "model": "gemini-3-flash-preview"},
        "openai": {"enabled": True, "model": "gpt-5-mini"},
    }


def test_provider_candidates_follow_priority() -> None:
    now = datetime(2026, 4, 28, 3, 0, tzinfo=UTC)

    candidates = resolve_provider_candidates(
        priority_value=["gemini", "openai"],
        settings_value=_settings(),
        status_value={},
        now=now,
        available_providers={"gemini": True, "openai": True},
    )

    assert [candidate.provider for candidate in candidates] == ["gemini", "openai"]


def test_blocked_first_provider_is_skipped() -> None:
    now = datetime(2026, 4, 28, 3, 0, tzinfo=UTC)

    candidates = resolve_provider_candidates(
        priority_value=["gemini", "openai"],
        settings_value=_settings(),
        status_value={
            "gemini": {
                "blocked_until": (now + timedelta(hours=1)).isoformat(),
                "reason": "rate_limit",
            }
        },
        now=now,
        available_providers={"gemini": True, "openai": True},
    )

    assert [candidate.provider for candidate in candidates] == ["openai"]


def test_expired_blocked_provider_returns_to_priority() -> None:
    now = datetime(2026, 4, 28, 3, 0, tzinfo=UTC)

    candidates = resolve_provider_candidates(
        priority_value=["gemini", "openai"],
        settings_value=_settings(),
        status_value={
            "gemini": {
                "blocked_until": (now - timedelta(minutes=1)).isoformat(),
                "reason": "rate_limit",
            }
        },
        now=now,
        available_providers={"gemini": True, "openai": True},
    )

    assert [candidate.provider for candidate in candidates] == ["gemini", "openai"]


def test_disabled_provider_is_skipped() -> None:
    now = datetime(2026, 4, 28, 3, 0, tzinfo=UTC)
    settings = _settings()
    settings["gemini"]["enabled"] = False

    candidates = resolve_provider_candidates(
        priority_value=["gemini", "openai"],
        settings_value=settings,
        status_value={},
        now=now,
        available_providers={"gemini": True, "openai": True},
    )

    assert [candidate.provider for candidate in candidates] == ["openai"]


def test_gemini_daily_quota_blocks_until_next_pacific_midnight() -> None:
    now = datetime(2026, 4, 28, 3, 0, tzinfo=UTC)
    error = RuntimeError("RESOURCE_EXHAUSTED quota_metric: generate_content_free_tier_requests")

    blocked_until = resolve_provider_block_until("gemini", error, now=now)

    assert blocked_until == datetime(2026, 4, 28, 7, 0, tzinfo=UTC)


def test_runtime_status_explains_active_and_fallback_candidates() -> None:
    now = datetime(2026, 4, 28, 3, 0, tzinfo=UTC)

    payload = resolve_provider_runtime_status(
        priority_value=["gemini", "openai"],
        settings_value=_settings(),
        status_value={},
        now=now,
        available_providers={"gemini": True, "openai": True},
    )

    assert payload["active_provider"] == "gemini"
    assert [item["status"] for item in payload["providers"]] == ["active", "fallback_ready"]
    assert [item["is_candidate"] for item in payload["providers"]] == [True, True]


def test_runtime_status_explains_skipped_provider_reason() -> None:
    now = datetime(2026, 4, 28, 3, 0, tzinfo=UTC)

    payload = resolve_provider_runtime_status(
        priority_value=["gemini", "openai"],
        settings_value=_settings(),
        status_value={
            "gemini": {
                "blocked_until": (now + timedelta(hours=1)).isoformat(),
                "reason": "daily_quota",
            }
        },
        now=now,
        available_providers={"gemini": True, "openai": True},
    )

    providers = payload["providers"]
    assert payload["active_provider"] == "openai"
    assert providers[0]["status"] == "blocked"
    assert providers[0]["skip_reason"] == "쿼터 또는 rate limit으로 일시 차단됨"
    assert providers[1]["status"] == "active"


def test_runtime_status_marks_missing_api_key() -> None:
    now = datetime(2026, 4, 28, 3, 0, tzinfo=UTC)

    payload = resolve_provider_runtime_status(
        priority_value=["gemini", "openai"],
        settings_value=_settings(),
        status_value={},
        now=now,
        available_providers={"gemini": False, "openai": True},
    )

    providers = payload["providers"]
    assert payload["active_provider"] == "openai"
    assert providers[0]["status"] == "missing_key"
    assert providers[0]["api_key_configured"] is False
