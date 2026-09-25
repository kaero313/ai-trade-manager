from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from app.core.config import parse_cors_allowed_origins, settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_cors_origins_are_normalized_and_deduplicated() -> None:
    assert parse_cors_allowed_origins(
        " http://localhost:5173/,https://admin.example.com,"
        "http://localhost:5173 "
    ) == [
        "http://localhost:5173",
        "https://admin.example.com",
    ]


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "ftp://admin.example.com",
        "https://user:password@admin.example.com",
        "https://admin.example.com/private",
        "https://admin.example.com?token=secret",
        "https://admin.example.com#fragment",
        "https://admin.example.com:not-a-port",
    ],
)
def test_cors_origins_reject_wildcard_and_non_origin_values(origin: str) -> None:
    with pytest.raises(ValueError):
        parse_cors_allowed_origins(origin)


@pytest.mark.asyncio
async def test_cors_preflight_allows_only_configured_origin_and_explicit_headers(
    monkeypatch,
) -> None:
    from app.main import CORS_EXPOSE_HEADERS, create_app

    monkeypatch.setattr(settings, "cors_allowed_origins", "https://admin.example.com")
    app = create_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        allowed = await client.options(
            "/api/health",
            headers={
                "Origin": "https://admin.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "authorization,content-type,idempotency-key,if-match,x-admin-token"
                ),
            },
        )
        rejected = await client.options(
            "/api/health",
            headers={
                "Origin": "https://attacker.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://admin.example.com"
    assert "access-control-allow-credentials" not in allowed.headers

    allowed_methods = {
        method.strip()
        for method in allowed.headers["access-control-allow-methods"].split(",")
    }
    assert allowed_methods == {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}

    allowed_headers = {
        header.strip().lower()
        for header in allowed.headers["access-control-allow-headers"].split(",")
    }
    assert {
        "authorization",
        "content-type",
        "idempotency-key",
        "if-match",
        "x-admin-token",
    } <= allowed_headers
    assert set(CORS_EXPOSE_HEADERS) == {
        "ETag",
        "Retry-After",
        "X-Config-Version",
        "X-RateLimit-Limit",
        "X-RateLimit-Policy",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
    }

    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers
    assert "access-control-allow-credentials" not in rejected.headers


@pytest.mark.asyncio
async def test_fastapi_introspection_routes_are_not_public() -> None:
    from app.main import create_app

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        responses = [
            await client.get(path)
            for path in (
                "/docs",
                "/docs/oauth2-redirect",
                "/redoc",
                "/openapi.json",
            )
        ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404]


def test_all_development_compose_host_ports_are_loopback_only() -> None:
    compose_text = (PROJECT_ROOT / "docker-compose-dev.yml").read_text(encoding="utf-8")
    port_bindings = re.findall(
        r'^\s*-\s*["\']([^"\']*:\d+)["\']\s*$',
        compose_text,
        flags=re.MULTILINE,
    )

    assert set(port_bindings) == {
        "127.0.0.1:5432:5432",
        "127.0.0.1:8000:8000",
        "127.0.0.1:5173:5173",
        "127.0.0.1:9200:9200",
        "127.0.0.1:5601:5601",
    }
    assert all(binding.startswith("127.0.0.1:") for binding in port_bindings)


def test_local_compose_backend_healthcheck_uses_public_health_endpoint() -> None:
    compose_text = (PROJECT_ROOT / "docker-compose.local.yml").read_text(
        encoding="utf-8"
    )

    assert "http://127.0.0.1:8000/api/health" in compose_text
    assert "http://127.0.0.1:8000/openapi.json" not in compose_text


def test_native_development_backend_binds_to_loopback_only() -> None:
    script = (PROJECT_ROOT / "start_dev.bat").read_text(encoding="utf-8")

    assert "uvicorn app.main:app --host 127.0.0.1 --port 8000" in script
    assert "uvicorn app.main:app --host 0.0.0.0" not in script
