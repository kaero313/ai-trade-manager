import hmac
import logging
from types import MappingProxyType
from typing import Final, Mapping

from fastapi import Depends, Header, HTTPException, Request, Response, status

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.rate_limit import (
    ApiRateLimitDecision,
    ApiRateLimitPolicy,
    ApiRateLimitService,
    ApiRateLimitUnavailableError,
)


logger = logging.getLogger(__name__)

RouteKey = tuple[str, str]

ROUTE_RATE_LIMIT_POLICIES: Final[Mapping[RouteKey, ApiRateLimitPolicy]] = MappingProxyType(
    {
        ("GET", "/api/health"): ApiRateLimitPolicy.HEALTH_EXEMPT,
        ("GET", "/api/health/live"): ApiRateLimitPolicy.HEALTH_EXEMPT,
        ("GET", "/api/health/ready"): ApiRateLimitPolicy.HEALTH_EXEMPT,
        ("GET", "/api/markets/"): ApiRateLimitPolicy.PUBLIC_MARKET_READ,
        ("GET", "/api/markets/tickers"): ApiRateLimitPolicy.PUBLIC_MARKET_READ,
        ("GET", "/api/markets/sentiment"): ApiRateLimitPolicy.PUBLIC_MARKET_READ,
        ("GET", "/api/markets/{symbol}/candles"): ApiRateLimitPolicy.PUBLIC_MARKET_READ,
        ("GET", "/api/news/"): ApiRateLimitPolicy.PUBLIC_NEWS_READ,
        ("GET", "/api/admin/session"): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("GET", "/api/dashboard"): ApiRateLimitPolicy.ADMIN_EXTERNAL_READ,
        ("GET", "/api/status"): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("POST", "/api/bot/start"): ApiRateLimitPolicy.STATE_MUTATION,
        ("POST", "/api/admin/reauth"): ApiRateLimitPolicy.STATE_MUTATION,
        ("GET", "/api/bot/trading-mode"): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("POST", "/api/bot/trading-mode/live"): ApiRateLimitPolicy.STATE_MUTATION,
        ("POST", "/api/bot/trading-mode/paper"): ApiRateLimitPolicy.SAFETY_STOP,
        ("POST", "/api/bot/stop"): ApiRateLimitPolicy.SAFETY_STOP,
        ("GET", "/api/bot/order-gate"): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("POST", "/api/bot/order-gate/arm"): ApiRateLimitPolicy.STATE_MUTATION,
        ("POST", "/api/bot/order-gate/block"): ApiRateLimitPolicy.SAFETY_STOP,
        ("POST", "/api/bot/liquidate"): ApiRateLimitPolicy.STATE_MUTATION,
        (
            "GET",
            "/api/bot/liquidations/{operation_id}",
        ): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("GET", "/api/config"): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("POST", "/api/config"): ApiRateLimitPolicy.STATE_MUTATION,
        ("GET", "/api/system/configs"): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("PUT", "/api/system/configs"): ApiRateLimitPolicy.STATE_MUTATION,
        ("GET", "/api/system/ai/providers/status"): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("POST", "/api/system/ai/providers/status/reset"): ApiRateLimitPolicy.STATE_MUTATION,
        ("POST", "/api/system/paper/reset"): ApiRateLimitPolicy.STATE_MUTATION,
        ("POST", "/api/chat/sessions"): ApiRateLimitPolicy.STATE_MUTATION,
        ("GET", "/api/chat/sessions"): ApiRateLimitPolicy.ADMIN_DB_READ,
        (
            "DELETE",
            "/api/chat/sessions/{session_id}",
        ): ApiRateLimitPolicy.STATE_MUTATION,
        (
            "POST",
            "/api/chat/sessions/{session_id}/messages",
        ): ApiRateLimitPolicy.EXPENSIVE_ACTION,
        (
            "GET",
            "/api/chat/sessions/{session_id}/messages",
        ): ApiRateLimitPolicy.ADMIN_DB_READ,
        (
            "POST",
            "/api/chat/sessions/{session_id}/approve",
        ): ApiRateLimitPolicy.STATE_MUTATION,
        ("GET", "/api/positions"): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("GET", "/api/favorites/"): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("POST", "/api/favorites/"): ApiRateLimitPolicy.STATE_MUTATION,
        ("DELETE", "/api/favorites/{symbol}"): ApiRateLimitPolicy.STATE_MUTATION,
        ("GET", "/api/orders/intents"): ApiRateLimitPolicy.ADMIN_DB_READ,
        (
            "POST",
            "/api/orders/intents/{intent_id}/reconcile",
        ): ApiRateLimitPolicy.STATE_MUTATION,
        (
            "POST",
            "/api/orders/intents/{intent_id}/resolve-no-order",
        ): ApiRateLimitPolicy.STATE_MUTATION,
        ("GET", "/api/orders/"): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("GET", "/api/portfolio/snapshots"): ApiRateLimitPolicy.ADMIN_DB_READ,
        (
            "POST",
            "/api/portfolio/snapshots/now",
        ): ApiRateLimitPolicy.EXPENSIVE_ACTION,
        ("GET", "/api/portfolio/briefing"): ApiRateLimitPolicy.EXPENSIVE_ACTION,
        ("GET", "/api/news/rag/status"): ApiRateLimitPolicy.ADMIN_EXTERNAL_READ,
        ("GET", "/api/news/sentiment"): ApiRateLimitPolicy.EXPENSIVE_ACTION,
        ("GET", "/api/upbit/accounts"): ApiRateLimitPolicy.ADMIN_EXTERNAL_READ,
        ("GET", "/api/upbit/order"): ApiRateLimitPolicy.ADMIN_EXTERNAL_READ,
        ("GET", "/api/upbit/orders/open"): ApiRateLimitPolicy.ADMIN_EXTERNAL_READ,
        ("GET", "/api/upbit/orders/closed"): ApiRateLimitPolicy.ADMIN_EXTERNAL_READ,
        ("GET", "/api/upbit/orders/uuids"): ApiRateLimitPolicy.ADMIN_EXTERNAL_READ,
        ("POST", "/api/slack/test"): ApiRateLimitPolicy.EXPENSIVE_ACTION,
        ("GET", "/api/ai/analyze"): ApiRateLimitPolicy.EXPENSIVE_ACTION,
        ("GET", "/api/ai/latest-analysis"): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("POST", "/api/ai/manual-cycle"): ApiRateLimitPolicy.EXPENSIVE_ACTION,
        ("GET", "/api/ai/latest-analysis-batch"): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("GET", "/api/ai/performance"): ApiRateLimitPolicy.ADMIN_DB_READ,
        ("GET", "/api/ai/test-analysis"): ApiRateLimitPolicy.EXPENSIVE_ACTION,
        ("POST", "/api/backtest/run"): ApiRateLimitPolicy.EXPENSIVE_ACTION,
    }
)

_ADMIN_ROUTE_POLICIES: Final = frozenset(
    {
        ApiRateLimitPolicy.ADMIN_DB_READ,
        ApiRateLimitPolicy.ADMIN_EXTERNAL_READ,
        ApiRateLimitPolicy.EXPENSIVE_ACTION,
        ApiRateLimitPolicy.STATE_MUTATION,
        ApiRateLimitPolicy.SAFETY_STOP,
    }
)
_rate_limit_service = ApiRateLimitService(AsyncSessionLocal)


def _header_value(value: str | None) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _extract_bearer_token(authorization: str | None) -> str:
    raw_value = _header_value(authorization)
    if not raw_value:
        return ""

    scheme, _, token = raw_value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return ""
    return token.strip()


def get_api_rate_limit_service() -> ApiRateLimitService:
    return _rate_limit_service


def _rate_limit_subject_secret() -> str | None:
    subject_secret = str(settings.rate_limit_subject_secret or "").strip()
    for protected_secret in (
        settings.admin_api_token,
        settings.admin_reauth_signing_secret,
    ):
        normalized = str(protected_secret or "").strip()
        if normalized and subject_secret and hmac.compare_digest(subject_secret, normalized):
            raise ApiRateLimitUnavailableError(
                "요청 제한 subject secret은 관리자 인증 secret과 분리해야 합니다."
            )
    return subject_secret or None


def _canonical_route_key(request: Request) -> RouteKey:
    fastapi_scope = request.scope.get("fastapi")
    effective_route = (
        fastapi_scope.get("effective_route_context")
        if isinstance(fastapi_scope, dict)
        else None
    )
    path = getattr(effective_route, "path_format", None)
    if not path:
        route = request.scope.get("route")
        path = getattr(route, "path_format", None) or getattr(route, "path", None)
    if not isinstance(path, str) or not path:
        raise ApiRateLimitUnavailableError("요청의 canonical API route를 확인하지 못했습니다.")
    return request.method.upper(), path


def _route_policy(request: Request) -> ApiRateLimitPolicy:
    route_key = _canonical_route_key(request)
    policy = ROUTE_RATE_LIMIT_POLICIES.get(route_key)
    if policy is None:
        raise ApiRateLimitUnavailableError(
            f"분류되지 않은 API route입니다: {route_key[0]} {route_key[1]}"
        )
    return policy


def _decision_headers(decision: ApiRateLimitDecision) -> dict[str, str]:
    return {
        "X-RateLimit-Policy": decision.policy.value,
        "X-RateLimit-Limit": str(decision.request_limit),
        "X-RateLimit-Remaining": str(max(decision.remaining, 0)),
        "X-RateLimit-Reset": str(decision.reset_epoch),
    }


def _unavailable_response(exc: Exception, *, policy: ApiRateLimitPolicy | None) -> HTTPException:
    logger.error(
        "PostgreSQL API 요청 제한 상태를 확정하지 못했습니다.",
        extra={
            "event": "api_rate_limit_unavailable",
            "policy": policy.value if policy is not None else "UNCLASSIFIED",
            "error_type": type(exc).__name__,
        },
    )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error_code": "RATE_LIMIT_UNAVAILABLE",
            "message": "API 요청 제한 상태를 확인하지 못했습니다.",
        },
    )


def _enforce_decision(decision: ApiRateLimitDecision, response: Response) -> None:
    headers = _decision_headers(decision)
    if not decision.allowed:
        headers["Retry-After"] = str(max(decision.retry_after_seconds, 1))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": "요청 제한을 초과했습니다.",
                "policy": decision.policy.value,
            },
            headers=headers,
        )
    for key, value in headers.items():
        response.headers[key] = value


async def _consume_route_policy(
    request: Request,
    response: Response,
    service: ApiRateLimitService,
    *,
    expected_policy: ApiRateLimitPolicy | None = None,
) -> None:
    try:
        policy = _route_policy(request)
        if expected_policy is not None and policy is not expected_policy:
            raise ApiRateLimitUnavailableError("API route의 요청 제한 정책이 일치하지 않습니다.")
        decision = await service.consume(
            policy,
            subject_secret=_rate_limit_subject_secret(),
        )
    except ApiRateLimitUnavailableError as exc:
        raise _unavailable_response(exc, policy=locals().get("policy")) from exc
    _enforce_decision(decision, response)


async def require_public_market_rate_limit(
    request: Request,
    response: Response,
    service: ApiRateLimitService = Depends(get_api_rate_limit_service),
) -> None:
    await _consume_route_policy(
        request,
        response,
        service,
        expected_policy=ApiRateLimitPolicy.PUBLIC_MARKET_READ,
    )


async def require_public_news_rate_limit(
    request: Request,
    response: Response,
    service: ApiRateLimitService = Depends(get_api_rate_limit_service),
) -> None:
    await _consume_route_policy(
        request,
        response,
        service,
        expected_policy=ApiRateLimitPolicy.PUBLIC_NEWS_READ,
    )


def _admin_error(*, submitted_token: str) -> HTTPException:
    if not submitted_token:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="관리 API 호출에는 운영 관리 토큰이 필요합니다.",
        )
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="운영 관리 토큰이 일치하지 않습니다.",
    )


async def require_rate_limited_admin_token(
    request: Request,
    response: Response,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    authorization: str | None = Header(default=None),
    service: ApiRateLimitService = Depends(get_api_rate_limit_service),
) -> None:
    configured_token = str(settings.admin_api_token or "").strip()
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="운영 관리 토큰이 서버에 설정되지 않았습니다.",
        )

    route_key: RouteKey | None
    try:
        route_key = _canonical_route_key(request)
    except ApiRateLimitUnavailableError:
        route_key = None
    explicit_token = _header_value(x_admin_token)
    submitted_token = (
        explicit_token
        if route_key == ("POST", "/api/admin/reauth")
        else explicit_token or _extract_bearer_token(authorization)
    )
    if not submitted_token or not hmac.compare_digest(submitted_token, configured_token):
        auth_error = _admin_error(submitted_token=submitted_token)
        try:
            decision = await service.consume(
                ApiRateLimitPolicy.AUTH_FAILURE,
                subject_secret=_rate_limit_subject_secret(),
            )
        except ApiRateLimitUnavailableError as exc:
            logger.warning(
                "인증 실패 요청의 PostgreSQL 요청 제한 상태를 확인하지 못했습니다.",
                extra={
                    "event": "api_auth_failure_rate_limit_unavailable",
                    "error_type": type(exc).__name__,
                },
            )
            raise auth_error from None
        if not decision.allowed:
            _enforce_decision(decision, response)
        auth_error.headers = _decision_headers(decision)
        raise auth_error

    try:
        policy = _route_policy(request)
        if policy not in _ADMIN_ROUTE_POLICIES:
            raise ApiRateLimitUnavailableError("관리 API route 정책이 올바르지 않습니다.")
        decision = await service.consume(
            policy,
            subject_secret=_rate_limit_subject_secret(),
        )
    except ApiRateLimitUnavailableError as exc:
        raise _unavailable_response(exc, policy=locals().get("policy")) from exc
    _enforce_decision(decision, response)


async def require_admin_token(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    authorization: str | None = Header(default=None),
) -> None:
    configured_token = str(settings.admin_api_token or "").strip()
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="운영 관리 토큰이 서버에 설정되지 않았습니다.",
        )

    submitted_token = _header_value(x_admin_token) or _extract_bearer_token(authorization)
    if not submitted_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="관리 API 호출에는 운영 관리 토큰이 필요합니다.",
        )

    if not hmac.compare_digest(submitted_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="운영 관리 토큰이 일치하지 않습니다.",
        )


async def require_reentered_admin_token(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> str:
    """재인증 전용 경계에서 명시적으로 다시 입력한 헤더 토큰을 반환합니다."""
    configured_token = str(settings.admin_api_token or "").strip()
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="운영 관리 토큰이 서버에 설정되지 않았습니다.",
        )

    submitted_token = _header_value(x_admin_token)
    if not submitted_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="관리자 재인증에는 X-Admin-Token 헤더를 다시 입력해야 합니다.",
        )
    if not hmac.compare_digest(submitted_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="운영 관리 토큰이 일치하지 않습니다.",
        )
    return submitted_token
