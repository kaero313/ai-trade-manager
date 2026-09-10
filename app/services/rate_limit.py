from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Mapping

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.rate_limit_repository import ApiRateLimitRepository


class ApiRateLimitPolicy(StrEnum):
    HEALTH_EXEMPT = "HEALTH_EXEMPT"
    PUBLIC_MARKET_READ = "PUBLIC_MARKET_READ"
    PUBLIC_NEWS_READ = "PUBLIC_NEWS_READ"
    ADMIN_DB_READ = "ADMIN_DB_READ"
    ADMIN_EXTERNAL_READ = "ADMIN_EXTERNAL_READ"
    EXPENSIVE_ACTION = "EXPENSIVE_ACTION"
    STATE_MUTATION = "STATE_MUTATION"
    SAFETY_STOP = "SAFETY_STOP"
    AUTH_FAILURE = "AUTH_FAILURE"


@dataclass(frozen=True, slots=True)
class RateLimitPolicyContract:
    request_limit: int
    window_seconds: int
    principal: str


RATE_LIMIT_POLICY_CONTRACTS: Final[Mapping[ApiRateLimitPolicy, RateLimitPolicyContract]] = (
    MappingProxyType(
        {
            ApiRateLimitPolicy.PUBLIC_MARKET_READ: RateLimitPolicyContract(
                request_limit=120,
                window_seconds=60,
                principal="public:global",
            ),
            ApiRateLimitPolicy.PUBLIC_NEWS_READ: RateLimitPolicyContract(
                request_limit=12,
                window_seconds=60,
                principal="public:global",
            ),
            ApiRateLimitPolicy.ADMIN_DB_READ: RateLimitPolicyContract(
                request_limit=600,
                window_seconds=60,
                principal="admin:primary",
            ),
            ApiRateLimitPolicy.ADMIN_EXTERNAL_READ: RateLimitPolicyContract(
                request_limit=120,
                window_seconds=60,
                principal="admin:primary",
            ),
            ApiRateLimitPolicy.EXPENSIVE_ACTION: RateLimitPolicyContract(
                request_limit=20,
                window_seconds=300,
                principal="admin:primary",
            ),
            ApiRateLimitPolicy.STATE_MUTATION: RateLimitPolicyContract(
                request_limit=60,
                window_seconds=60,
                principal="admin:primary",
            ),
            ApiRateLimitPolicy.SAFETY_STOP: RateLimitPolicyContract(
                request_limit=600,
                window_seconds=60,
                principal="admin:primary",
            ),
            ApiRateLimitPolicy.AUTH_FAILURE: RateLimitPolicyContract(
                request_limit=10,
                window_seconds=300,
                principal="auth-failure:global",
            ),
        }
    )
)


@dataclass(frozen=True, slots=True)
class ApiRateLimitDecision:
    policy: ApiRateLimitPolicy
    allowed: bool
    request_limit: int
    remaining: int
    retry_after_seconds: int
    reset_epoch: int


class ApiRateLimitUnavailableError(RuntimeError):
    pass


class ApiRateLimitService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        repository: ApiRateLimitRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository or ApiRateLimitRepository()

    async def consume(
        self,
        policy: ApiRateLimitPolicy,
        *,
        subject_secret: str | None,
    ) -> ApiRateLimitDecision:
        contract = RATE_LIMIT_POLICY_CONTRACTS.get(policy)
        if contract is None:
            raise ApiRateLimitUnavailableError("요청 제한 정책이 구성되지 않았습니다.")

        try:
            subject_hash = _build_subject_hash(
                policy=policy,
                principal=contract.principal,
                subject_secret=subject_secret,
            )
            async with self._session_factory() as db:
                async with db.begin():
                    window = await self._repository.consume_window(
                        db,
                        policy_key=policy.value,
                        subject_hash=subject_hash,
                        request_limit=contract.request_limit,
                        window_seconds=contract.window_seconds,
                    )
        except ApiRateLimitUnavailableError:
            raise
        except Exception as exc:
            raise ApiRateLimitUnavailableError(
                "PostgreSQL 요청 제한 상태를 확정하지 못했습니다."
            ) from exc

        return ApiRateLimitDecision(
            policy=policy,
            allowed=window.allowed,
            request_limit=contract.request_limit,
            remaining=window.remaining,
            retry_after_seconds=window.retry_after_seconds,
            reset_epoch=window.reset_epoch,
        )


def _build_subject_hash(
    *,
    policy: ApiRateLimitPolicy,
    principal: str,
    subject_secret: str | None,
) -> str:
    normalized_secret = str(subject_secret or "").strip()
    secret_bytes = normalized_secret.encode("utf-8")
    if len(secret_bytes) < 32:
        raise ApiRateLimitUnavailableError(
            "요청 제한 subject secret은 최소 32바이트여야 합니다."
        )

    message = f"atm-api-rate-limit:v1:{policy.value}:{principal}".encode("utf-8")
    return hmac.new(secret_bytes, message, hashlib.sha256).hexdigest()
