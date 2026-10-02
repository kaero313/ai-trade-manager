from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.services.rag import ingestion


@pytest.mark.asyncio
async def test_recent_partial_ingestion_with_indexed_news_is_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def latest() -> dict[str, Any]:
        return {
            "run_id": "recent-partial",
            "finished_at": datetime.now(UTC).isoformat(),
            "status": "partial",
            "indexed": 2,
            "errors": 1,
        }

    async def unexpected_run(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("사용 가능한 최신 partial ingestion은 재수집하면 안 됩니다.")

    monkeypatch.setattr(ingestion, "_fetch_latest_ingestion_run", latest)
    monkeypatch.setattr(ingestion, "run_market_news_ingestion_job", unexpected_run)

    result = await ingestion.refresh_market_news_for_buy_precheck_if_stale(
        max_age_minutes=60
    )

    assert result["refreshed"] is False
    assert result["reason"] == "fresh"
    assert result["latest_ingestion"]["status"] == "partial"
    assert result["latest_ingestion"]["indexed"] == 2


@pytest.mark.asyncio
async def test_recent_failed_or_empty_ingestion_is_not_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def latest() -> dict[str, Any]:
        return {
            "run_id": "recent-empty",
            "finished_at": datetime.now(UTC).isoformat(),
            "status": "failed",
            "indexed": 0,
            "errors": 1,
        }

    async def run(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        assert kwargs == {
            "context": ingestion.INGESTION_CONTEXT_BUY_PRECHECK,
            "allow_openai_translation_fallback": True,
        }
        calls += 1
        return {"run_id": "recovered", "indexed": 3, "errors": 0, "status": "success"}

    monkeypatch.setattr(ingestion, "_fetch_latest_ingestion_run", latest)
    monkeypatch.setattr(ingestion, "run_market_news_ingestion_job", run)

    result = await ingestion.refresh_market_news_for_buy_precheck_if_stale(
        max_age_minutes=60
    )

    assert calls == 1
    assert result["refreshed"] is True
    assert result["reason"] == "stale_or_missing"
    assert result["latest_ingestion"]["status"] == "success"


@pytest.mark.asyncio
async def test_new_ingestion_with_zero_indexed_news_is_refresh_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def latest() -> None:
        return None

    async def run(**_kwargs: Any) -> dict[str, Any]:
        return {"run_id": "empty", "indexed": 0, "errors": 0}

    monkeypatch.setattr(ingestion, "_fetch_latest_ingestion_run", latest)
    monkeypatch.setattr(ingestion, "run_market_news_ingestion_job", run)

    result = await ingestion.refresh_market_news_for_buy_precheck_if_stale()

    assert result["refreshed"] is False
    assert result["reason"] == "refresh_failed"
    assert result["error"] == "INGESTION_INDEXED_NO_NEWS"
    assert result["latest_ingestion"]["status"] == "failed"
    assert result["latest_ingestion"]["indexed"] == 0


@pytest.mark.asyncio
async def test_explicit_failed_ingestion_is_never_promoted_by_positive_indexed_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def latest() -> None:
        return None

    async def run(**_kwargs: Any) -> dict[str, Any]:
        return {"run_id": "failed", "status": "failed", "indexed": 4, "errors": 0}

    monkeypatch.setattr(ingestion, "_fetch_latest_ingestion_run", latest)
    monkeypatch.setattr(ingestion, "run_market_news_ingestion_job", run)

    result = await ingestion.refresh_market_news_for_buy_precheck_if_stale()

    assert result["refreshed"] is False
    assert result["reason"] == "refresh_failed"
    assert result["error"] == "INGESTION_STATUS_UNUSABLE"
    assert result["latest_ingestion"]["status"] == "failed"
    assert result["latest_ingestion"]["indexed"] == 4


@pytest.mark.parametrize("indexed", [True, 1.5, -1, "1.5"])
def test_malformed_indexed_count_is_never_usable(indexed: Any) -> None:
    payload = {"status": "success", "indexed": indexed, "errors": 0}

    assert ingestion._has_usable_ingestion_result(payload) is False
    assert ingestion._buy_precheck_ingestion_failure_code(payload) == (
        "INGESTION_INDEXED_INVALID"
    )
    normalized = ingestion._normalize_buy_precheck_ingestion_result(payload)
    assert normalized["status"] == "failed"
    assert normalized["indexed"] == 0


@pytest.mark.asyncio
async def test_new_ingestion_with_errors_and_indexed_news_is_partial_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def latest() -> None:
        return None

    async def run(**_kwargs: Any) -> dict[str, Any]:
        return {"run_id": "partial", "indexed": 4, "errors": 2}

    monkeypatch.setattr(ingestion, "_fetch_latest_ingestion_run", latest)
    monkeypatch.setattr(ingestion, "run_market_news_ingestion_job", run)

    result = await ingestion.refresh_market_news_for_buy_precheck_if_stale()

    assert result["refreshed"] is True
    assert result["reason"] == "stale_or_missing_partial"
    assert result["latest_ingestion"]["status"] == "partial"
    assert result["latest_ingestion"]["indexed"] == 4
    assert result["latest_ingestion"]["errors"] == 2
