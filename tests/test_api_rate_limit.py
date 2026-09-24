from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI

from app.api.dependencies import (
    get_api_rate_limit_service,
    require_public_market_rate_limit,
    require_rate_limited_admin_token,
)
from app.core.config import settings
from app.db.rate_limit_repository import RateLimitWindowDecision
from app.services.rate_limit import (
    RATE_LIMIT_POLICY_CONTRACTS,
    ApiRateLimitDecision,
    ApiRateLimitPolicy,
    ApiRateLimitService,
    ApiRateLimitUnavailableError,
)


class _FakeRateLimitService:
    def __init__(self) -> None:
        self.calls: list[ApiRateLimitPolicy] = []
        self.denied_policies: set[ApiRateLimitPolicy] = set()
        self.failed_policies: set[ApiRateLimitPolicy] = set()

    async def consume(
        self,
        policy: ApiRateLimitPolicy,
        *,
        subject_secret: str | None,
    ) -> ApiRateLimitDecision:
        del subject_secret
        self.calls.append(policy)
        if policy in self.failed_policies:
            raise ApiRateLimitUnavailableError("database unavailable")
        allowed = policy not in self.denied_policies
        return ApiRateLimitDecision(
            policy=policy,
            allowed=allowed,
            request_limit=10,
            remaining=9 if allowed else 0,
            retry_after_seconds=37 if not allowed else 0,
            reset_epoch=1_800_000_000,
        )


def _build_app(service: _FakeRateLimitService, endpoint_calls: dict[str, int]) -> FastAPI:
    app = FastAPI()

    @app.get(
        "/api/status",
        dependencies=[Depends(require_rate_limited_admin_token)],
    )
    async def admin_status() -> dict[str, bool]:
        endpoint_calls["admin"] += 1
        return {"ok": True}

    @app.post(
        "/api/admin/reauth",
        dependencies=[Depends(require_rate_limited_admin_token)],
    )
    async def admin_reauth() -> dict[str, bool]:
        endpoint_calls["reauth"] += 1
        return {"ok": True}

    @app.get(
        "/api/markets/tickers",
        dependencies=[Depends(require_public_market_rate_limit)],
    )
    async def public_market() -> dict[str, bool]:
        endpoint_calls["public"] += 1
        return {"ok": True}

    app.dependency_overrides[get_api_rate_limit_service] = lambda: service
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


def test_policy_contracts_match_the_approved_limits() -> None:
    expected = {
        ApiRateLimitPolicy.PUBLIC_MARKET_READ: (120, 60, "public:global"),
        ApiRateLimitPolicy.PUBLIC_NEWS_READ: (12, 60, "public:global"),
        ApiRateLimitPolicy.ADMIN_DB_READ: (600, 60, "admin:primary"),
        ApiRateLimitPolicy.ADMIN_EXTERNAL_READ: (120, 60, "admin:primary"),
        ApiRateLimitPolicy.EXPENSIVE_ACTION: (20, 300, "admin:primary"),
        ApiRateLimitPolicy.STATE_MUTATION: (60, 60, "admin:primary"),
        ApiRateLimitPolicy.SAFETY_STOP: (600, 60, "admin:primary"),
        ApiRateLimitPolicy.AUTH_FAILURE: (10, 300, "auth-failure:global"),
    }
    assert {
        policy: (contract.request_limit, contract.window_seconds, contract.principal)
        for policy, contract in RATE_LIMIT_POLICY_CONTRACTS.items()
    } == expected


@pytest.mark.asyncio
async def test_valid_admin_consumes_declared_policy_before_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "server-token")
    service = _FakeRateLimitService()
    calls = {"admin": 0, "reauth": 0, "public": 0}
    app = _build_app(service, calls)

    response = await _request(
        app,
        "GET",
        "/api/status",
        headers={"X-Admin-Token": "server-token"},
    )

    assert response.status_code == 200
    assert service.calls == [ApiRateLimitPolicy.ADMIN_DB_READ]
    assert calls["admin"] == 1
    assert response.headers["x-ratelimit-policy"] == "ADMIN_DB_READ"
    assert response.headers["x-ratelimit-remaining"] == "9"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "expected_status"),
    [
        ({}, 401),
        ({"X-Admin-Token": "wrong-token"}, 403),
        ({"X-Forwarded-For": "203.0.113.10", "Forwarded": "for=203.0.113.11"}, 401),
    ],
)
async def test_invalid_admin_consumes_only_global_auth_failure_before_endpoint(
    monkeypatch,
    headers: dict[str, str],
    expected_status: int,
) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "server-token")
    service = _FakeRateLimitService()
    calls = {"admin": 0, "reauth": 0, "public": 0}
    app = _build_app(service, calls)

    response = await _request(app, "GET", "/api/status", headers=headers)

    assert response.status_code == expected_status
    assert service.calls == [ApiRateLimitPolicy.AUTH_FAILURE]
    assert calls["admin"] == 0
    assert response.headers["x-ratelimit-policy"] == "AUTH_FAILURE"


@pytest.mark.asyncio
async def test_auth_failure_limiter_outage_preserves_original_auth_error(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "server-token")
    service = _FakeRateLimitService()
    service.failed_policies.add(ApiRateLimitPolicy.AUTH_FAILURE)
    calls = {"admin": 0, "reauth": 0, "public": 0}
    app = _build_app(service, calls)

    response = await _request(
        app,
        "GET",
        "/api/status",
        headers={"X-Admin-Token": "wrong-token"},
    )

    assert response.status_code == 403
    assert calls["admin"] == 0
    assert "x-ratelimit-limit" not in response.headers


@pytest.mark.asyncio
async def test_valid_or_public_limiter_outage_is_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "server-token")
    service = _FakeRateLimitService()
    service.failed_policies.update(
        {ApiRateLimitPolicy.ADMIN_DB_READ, ApiRateLimitPolicy.PUBLIC_MARKET_READ}
    )
    calls = {"admin": 0, "reauth": 0, "public": 0}
    app = _build_app(service, calls)

    admin = await _request(
        app,
        "GET",
        "/api/status",
        headers={"X-Admin-Token": "server-token"},
    )
    public = await _request(app, "GET", "/api/markets/tickers")

    assert admin.status_code == 503
    assert public.status_code == 503
    assert admin.json()["detail"]["error_code"] == "RATE_LIMIT_UNAVAILABLE"
    assert public.json()["detail"]["error_code"] == "RATE_LIMIT_UNAVAILABLE"
    assert calls == {"admin": 0, "reauth": 0, "public": 0}


@pytest.mark.asyncio
async def test_rate_limit_secret_reuse_is_fail_closed_before_endpoint(monkeypatch) -> None:
    shared_secret = "shared-admin-and-rate-limit-secret-123456789"
    monkeypatch.setattr(settings, "admin_api_token", shared_secret)
    monkeypatch.setattr(settings, "rate_limit_subject_secret", shared_secret)
    service = _FakeRateLimitService()
    calls = {"admin": 0, "reauth": 0, "public": 0}
    app = _build_app(service, calls)

    response = await _request(
        app,
        "GET",
        "/api/status",
        headers={"X-Admin-Token": shared_secret},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "RATE_LIMIT_UNAVAILABLE"
    assert service.calls == []
    assert calls["admin"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "headers", "policy", "counter"),
    [
        (
            "/api/status",
            {"X-Admin-Token": "server-token"},
            ApiRateLimitPolicy.ADMIN_DB_READ,
            "admin",
        ),
        (
            "/api/markets/tickers",
            {},
            ApiRateLimitPolicy.PUBLIC_MARKET_READ,
            "public",
        ),
        (
            "/api/status",
            {"X-Admin-Token": "wrong-token"},
            ApiRateLimitPolicy.AUTH_FAILURE,
            "admin",
        ),
    ],
)
async def test_limit_exceeded_returns_retry_headers_before_endpoint(
    monkeypatch,
    path: str,
    headers: dict[str, str],
    policy: ApiRateLimitPolicy,
    counter: str,
) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "server-token")
    service = _FakeRateLimitService()
    service.denied_policies.add(policy)
    calls = {"admin": 0, "reauth": 0, "public": 0}
    app = _build_app(service, calls)

    response = await _request(app, "GET", path, headers=headers)

    assert response.status_code == 429
    assert response.headers["retry-after"] == "37"
    assert response.headers["x-ratelimit-policy"] == policy.value
    assert response.headers["x-ratelimit-limit"] == "10"
    assert response.headers["x-ratelimit-remaining"] == "0"
    assert calls[counter] == 0


@pytest.mark.asyncio
async def test_reauth_requires_explicit_header_before_state_policy(monkeypatch) -> None:
    monkeypatch.setattr(settings, "admin_api_token", "server-token")
    service = _FakeRateLimitService()
    calls = {"admin": 0, "reauth": 0, "public": 0}
    app = _build_app(service, calls)

    response = await _request(
        app,
        "POST",
        "/api/admin/reauth",
        headers={"Authorization": "Bearer server-token"},
    )

    assert response.status_code == 401
    assert service.calls == [ApiRateLimitPolicy.AUTH_FAILURE]
    assert calls["reauth"] == 0


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Session:
    def begin(self) -> _Transaction:
        return _Transaction()

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _SessionFactory:
    def __call__(self) -> _Session:
        return _Session()


class _CapturingRepository:
    def __init__(self) -> None:
        self.policy_key: str | None = None
        self.subject_hash: str | None = None

    async def consume_window(self, _db: object, **values: Any) -> RateLimitWindowDecision:
        self.policy_key = str(values["policy_key"])
        self.subject_hash = str(values["subject_hash"])
        return RateLimitWindowDecision(
            allowed=True,
            request_count=1,
            rejected_count=0,
            remaining=119,
            retry_after_seconds=0,
            reset_epoch=1_800_000_000,
        )


@pytest.mark.asyncio
async def test_subject_hash_uses_only_fixed_policy_principal_and_secret() -> None:
    repository = _CapturingRepository()
    service = ApiRateLimitService(_SessionFactory(), repository)  # type: ignore[arg-type]
    secret = "s" * 32

    await service.consume(
        ApiRateLimitPolicy.PUBLIC_MARKET_READ,
        subject_secret=secret,
    )

    assert repository.policy_key == "PUBLIC_MARKET_READ"
    assert repository.subject_hash is not None
    assert len(repository.subject_hash) == 64
    assert secret not in repository.subject_hash
    assert "public:global" not in repository.subject_hash


@pytest.mark.asyncio
async def test_short_subject_secret_fails_closed_before_repository_call() -> None:
    repository = _CapturingRepository()
    service = ApiRateLimitService(_SessionFactory(), repository)  # type: ignore[arg-type]

    with pytest.raises(ApiRateLimitUnavailableError):
        await service.consume(
            ApiRateLimitPolicy.PUBLIC_MARKET_READ,
            subject_secret="too-short",
        )

    assert repository.subject_hash is None
