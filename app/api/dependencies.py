import hmac

from fastapi import Header, HTTPException, status

from app.core.config import settings


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
