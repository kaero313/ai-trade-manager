import hashlib
import hmac
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from app.core.config import settings

ADMIN_REAUTH_PURPOSE_ENABLE_LIVE_TRADING = "ENABLE_LIVE_TRADING"
ADMIN_REAUTH_TTL = timedelta(minutes=5)
_REAUTH_ISSUER = "ai-trade-manager"
_REAUTH_AUDIENCE = "trading-mode-control"
_REAUTH_SUBJECT = "admin-reauth"
_REAUTH_ALGORITHM = "HS256"
_MIN_SIGNING_SECRET_LENGTH = 32
_MIN_SIGNING_SECRET_ENTROPY_BITS_PER_CHAR = 3.5


class AdminReauthError(RuntimeError):
    error_code = "ADMIN_REAUTH_INVALID"

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code


@dataclass(frozen=True, slots=True)
class AdminReauthProof:
    proof: str
    jti: str
    purpose: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AdminReauthClaims:
    jti: str
    purpose: str
    issued_at: datetime
    expires_at: datetime
    expired: bool


def _configured_admin_token() -> str:
    configured = str(settings.admin_api_token or "").strip()
    if not configured:
        raise AdminReauthError(
            "운영 관리 토큰이 서버에 설정되지 않았습니다.",
            error_code="ADMIN_REAUTH_UNAVAILABLE",
        )
    return configured


def _configured_signing_secret() -> str:
    secret = str(settings.admin_reauth_signing_secret or "").strip()
    normalized = secret.lower()
    entropy = 0.0
    if secret:
        for character in set(secret):
            probability = secret.count(character) / len(secret)
            entropy -= probability * math.log2(probability)
    repeated_pattern = any(
        len(secret) % period == 0
        and secret == secret[:period] * (len(secret) // period)
        for period in range(1, max(1, len(secret) // 2 + 1))
    )
    weak_marker = any(
        marker in normalized
        for marker in ("change_me", "changeme", "your_", "example", "placeholder")
    )
    admin_token = str(settings.admin_api_token or "").strip()
    same_as_admin_token = bool(
        admin_token
        and len(secret) == len(admin_token)
        and hmac.compare_digest(secret, admin_token)
    )
    if (
        len(secret) < _MIN_SIGNING_SECRET_LENGTH
        or entropy < _MIN_SIGNING_SECRET_ENTROPY_BITS_PER_CHAR
        or repeated_pattern
        or weak_marker
        or same_as_admin_token
    ):
        raise AdminReauthError(
            "관리자 재인증 서명 secret이 없거나 충분히 강하지 않습니다.",
            error_code="ADMIN_REAUTH_UNAVAILABLE",
        )
    return secret


def _signing_key() -> bytes:
    return hashlib.sha256(
        b"ai-trade-manager:admin-reauth:v1\0"
        + _configured_signing_secret().encode("utf-8")
    ).digest()


def _require_uuid4(value: object) -> str:
    try:
        parsed = UUID(str(value).strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise AdminReauthError("재인증 proof의 jti가 올바르지 않습니다.") from exc
    if parsed.version != 4:
        raise AdminReauthError("재인증 proof의 jti가 UUID v4가 아닙니다.")
    return str(parsed)


def verify_reentered_admin_token(submitted_token: str) -> None:
    configured = _configured_admin_token()
    submitted = str(submitted_token or "").strip()
    if not submitted or not hmac.compare_digest(submitted, configured):
        raise AdminReauthError(
            "다시 입력한 운영 관리 토큰이 일치하지 않습니다.",
            error_code="ADMIN_REAUTH_FAILED",
        )


def issue_admin_reauth_proof(
    submitted_token: str,
    *,
    purpose: str,
    now: datetime | None = None,
) -> AdminReauthProof:
    verify_reentered_admin_token(submitted_token)
    if purpose != ADMIN_REAUTH_PURPOSE_ENABLE_LIVE_TRADING:
        raise AdminReauthError("지원하지 않는 관리자 재인증 목적입니다.")

    issued_at = (now or datetime.now(UTC)).astimezone(UTC)
    expires_at = issued_at + ADMIN_REAUTH_TTL
    jti = str(uuid4())
    payload = {
        "iss": _REAUTH_ISSUER,
        "aud": _REAUTH_AUDIENCE,
        "sub": _REAUTH_SUBJECT,
        "purpose": purpose,
        "jti": jti,
        "iat": issued_at,
        "nbf": issued_at,
        "exp": expires_at,
    }
    proof = jwt.encode(
        payload,
        _signing_key(),
        algorithm=_REAUTH_ALGORITHM,
    )
    return AdminReauthProof(
        proof=proof,
        jti=jti,
        purpose=purpose,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def verify_admin_reauth_proof(
    proof: str,
    *,
    expected_purpose: str,
    allow_expired: bool = False,
    now: datetime | None = None,
) -> AdminReauthClaims:
    encoded = str(proof or "").strip()
    if not encoded:
        raise AdminReauthError("관리자 재인증 proof가 필요합니다.")

    try:
        payload = jwt.decode(
            encoded,
            _signing_key(),
            algorithms=[_REAUTH_ALGORITHM],
            audience=_REAUTH_AUDIENCE,
            issuer=_REAUTH_ISSUER,
            options={"verify_exp": not allow_expired},
        )
    except ExpiredSignatureError as exc:
        raise AdminReauthError(
            "관리자 재인증 proof가 만료되었습니다.",
            error_code="ADMIN_REAUTH_EXPIRED",
        ) from exc
    except InvalidTokenError as exc:
        raise AdminReauthError("관리자 재인증 proof를 검증할 수 없습니다.") from exc

    if payload.get("sub") != _REAUTH_SUBJECT:
        raise AdminReauthError("관리자 재인증 proof의 subject가 일치하지 않습니다.")
    purpose = str(payload.get("purpose") or "")
    if purpose != expected_purpose:
        raise AdminReauthError("관리자 재인증 proof의 purpose가 일치하지 않습니다.")

    try:
        issued_at = datetime.fromtimestamp(float(payload["iat"]), tz=UTC)
        expires_at = datetime.fromtimestamp(float(payload["exp"]), tz=UTC)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise AdminReauthError("관리자 재인증 proof의 시간이 올바르지 않습니다.") from exc
    if expires_at <= issued_at or expires_at - issued_at > ADMIN_REAUTH_TTL:
        raise AdminReauthError("관리자 재인증 proof의 유효 기간이 올바르지 않습니다.")

    current = (now or datetime.now(UTC)).astimezone(UTC)
    expired = current >= expires_at
    if expired and not allow_expired:
        raise AdminReauthError(
            "관리자 재인증 proof가 만료되었습니다.",
            error_code="ADMIN_REAUTH_EXPIRED",
        )
    return AdminReauthClaims(
        jti=_require_uuid4(payload.get("jti")),
        purpose=purpose,
        issued_at=issued_at,
        expires_at=expires_at,
        expired=expired,
    )
