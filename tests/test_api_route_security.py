from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from functools import cache
from typing import Any

import httpx
from fastapi import FastAPI

from app.api.dependencies import get_api_rate_limit_service
from app.api.dependencies import require_rate_limited_admin_token
from app.api.router import api_router
from app.api.routes import markets as markets_route
from app.api.routes import news as news_route
from app.core.config import settings
from app.db.session import get_db
from app.models.schemas import MarketSentimentSnapshot
from app.services.rate_limit import ApiRateLimitDecision, ApiRateLimitPolicy

PUBLIC_ROUTES = {
    ("GET", "/api/health"),
    ("GET", "/api/health/live"),
    ("GET", "/api/health/ready"),
    ("GET", "/api/markets/"),
    ("GET", "/api/markets/tickers"),
    ("GET", "/api/markets/sentiment"),
    ("GET", "/api/markets/{symbol}/candles"),
    ("GET", "/api/news/"),
}


def _has_admin_dependency(route: Any) -> bool:
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        if dependency.call is require_rate_limited_admin_token:
            return True
        pending.extend(dependency.dependencies)
    return False


@cache
def _introspection_app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.openapi()
    return app


def _api_routes() -> list[Any]:
    app = _introspection_app()

    def walk(candidate: Any) -> list[Any]:
        if (
            getattr(candidate, "path_format", None)
            and getattr(candidate, "methods", None)
            and getattr(candidate, "dependant", None) is not None
        ):
            return [candidate]
        nested: list[Any] = []
        for child in getattr(candidate, "_effective_candidates", ()):
            nested.extend(walk(child))
        return nested

    return [route for included in app.routes for route in walk(included)]


def test_api_router_protects_every_route_outside_public_allowlist() -> None:
    actual_public_routes: set[tuple[str, str]] = set()

    for route in _api_routes():
        methods = set(route.methods or set()) - {"HEAD", "OPTIONS"}
        for method in methods:
            route_key = (method, route.path_format)
            if _has_admin_dependency(route):
                assert route_key not in PUBLIC_ROUTES
            else:
                actual_public_routes.add(route_key)

    assert actual_public_routes == PUBLIC_ROUTES


class _HealthDb:
    async def execute(self, _statement: object) -> None:
        return None


class _PublicMarketBroker:
    async def get_all_markets(self) -> list[dict[str, Any]]:
        return []

    async def get_ticker(self, _markets: list[str]) -> list[dict[str, Any]]:
        return []

    async def get_candles(
        self,
        *,
        market: str,
        timeframe: str,
        count: int,
    ) -> list[dict[str, Any]]:
        del market, timeframe, count
        return []


async def _get_health_db() -> AsyncIterator[_HealthDb]:
    yield _HealthDb()


class _FailingDb:
    async def execute(self, _statement: object) -> None:
        raise RuntimeError("database is unavailable")


async def _get_failing_db() -> AsyncIterator[_FailingDb]:
    yield _FailingDb()


class _AllowingRateLimitService:
    async def consume(
        self,
        policy: ApiRateLimitPolicy,
        *,
        subject_secret: str | None,
    ) -> ApiRateLimitDecision:
        del subject_secret
        return ApiRateLimitDecision(
            policy=policy,
            allowed=True,
            request_limit=100,
            remaining=99,
            retry_after_seconds=0,
            reset_epoch=1_800_000_000,
        )


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.dependency_overrides[get_db] = _get_health_db
    app.dependency_overrides[get_api_rate_limit_service] = lambda: _AllowingRateLimitService()
    return app


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    **kwargs: Any,
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await client.request(method, path, **kwargs)


def test_admin_session_accepts_only_valid_admin_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "server-admin-token")
    app = _build_test_app()

    missing = asyncio.run(_request(app, "GET", "/api/admin/session"))
    mismatch = asyncio.run(
        _request(
            app,
            "GET",
            "/api/admin/session",
            headers={"X-Admin-Token": "wrong-token"},
        )
    )
    accepted = asyncio.run(
        _request(
            app,
            "GET",
            "/api/admin/session",
            headers={"X-Admin-Token": "server-admin-token"},
        )
    )

    assert missing.status_code == 401
    assert mismatch.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json() == {"authenticated": True}


def test_router_level_auth_blocks_sensitive_routes_before_upstream_calls(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "server-admin-token")
    app = _build_test_app()

    for method, path in (
        ("GET", "/api/dashboard"),
        ("GET", "/api/status"),
        ("GET", "/api/config"),
        ("GET", "/api/system/configs"),
        ("GET", "/api/chat/sessions"),
        ("GET", "/api/positions"),
        ("GET", "/api/favorites/"),
        ("GET", "/api/orders/"),
        ("GET", "/api/portfolio/snapshots"),
        ("GET", "/api/upbit/accounts"),
        ("GET", "/api/ai/performance"),
        ("POST", "/api/backtest/run"),
        ("GET", "/api/news/rag/status"),
        ("GET", "/api/news/sentiment"),
    ):
        response = asyncio.run(_request(app, method, path))
        assert response.status_code == 401, (method, path, response.text)


def test_public_allowlist_is_available_without_admin_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "server-admin-token")
    monkeypatch.setattr(markets_route, "broker", _PublicMarketBroker())
    monkeypatch.setattr(
        news_route,
        "fetch_crypto_news",
        lambda *args, **kwargs: {
            "items": [],
            "analysis_completed_at": "2026-07-13T00:00:00+00:00",
        },
    )

    async def fake_sentiment(_db: object) -> MarketSentimentSnapshot:
        return MarketSentimentSnapshot(
            score=50,
            classification="neutral",
            updated_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(markets_route, "get_or_refresh_market_sentiment", fake_sentiment)
    app = _build_test_app()

    for path in (
        "/api/health",
        "/api/health/live",
        "/api/health/ready",
        "/api/markets/",
        "/api/markets/tickers?symbols=KRW-BTC",
        "/api/markets/sentiment",
        "/api/markets/KRW-BTC/candles",
        "/api/news/",
    ):
        response = asyncio.run(_request(app, "GET", path))
        assert response.status_code == 200, (path, response.text)


def test_liveness_survives_db_outage_while_readiness_reports_unavailable() -> None:
    app = _build_test_app()
    app.dependency_overrides[get_db] = _get_failing_db

    live = asyncio.run(_request(app, "GET", "/api/health/live"))
    assert live.status_code == 200, live.text
    assert live.json() == {"status": "ok"}

    ready = asyncio.run(_request(app, "GET", "/api/health/ready"))
    assert ready.status_code == 503, ready.text
    assert ready.json() == {"status": "unavailable", "db": "disconnected"}
