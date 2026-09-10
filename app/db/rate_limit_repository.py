from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


RATE_LIMIT_RETENTION_HOURS = 24


@dataclass(frozen=True, slots=True)
class RateLimitWindowDecision:
    allowed: bool
    request_count: int
    rejected_count: int
    remaining: int
    retry_after_seconds: int
    reset_epoch: int


_CONSUME_WINDOW_SQL = text(
    """
    WITH clock AS (
        SELECT
            statement_timestamp() AS now_at,
            date_bin(
                make_interval(secs => CAST(:window_seconds AS double precision)),
                statement_timestamp(),
                TIMESTAMPTZ '1970-01-01 00:00:00+00'
            ) AS window_started_at
    ),
    expired AS (
        DELETE FROM api_rate_limit_windows
        WHERE window_started_at < (
            SELECT now_at - make_interval(hours => :retention_hours)
            FROM clock
        )
        RETURNING 1
    ),
    consumed AS (
        INSERT INTO api_rate_limit_windows (
            policy_key,
            subject_hash,
            window_started_at,
            request_count,
            rejected_count,
            last_seen_at,
            created_at,
            updated_at
        )
        SELECT
            :policy_key,
            :subject_hash,
            clock.window_started_at,
            1,
            0,
            clock.now_at,
            clock.now_at,
            clock.now_at
        FROM clock
        ON CONFLICT (policy_key, subject_hash, window_started_at)
        DO UPDATE SET
            request_count = LEAST(
                api_rate_limit_windows.request_count + 1,
                CAST(:request_limit AS bigint) + 1
            ),
            rejected_count = api_rate_limit_windows.rejected_count + CASE
                WHEN api_rate_limit_windows.request_count >= CAST(:request_limit AS bigint)
                THEN 1
                ELSE 0
            END,
            last_seen_at = (SELECT now_at FROM clock),
            updated_at = (SELECT now_at FROM clock)
        RETURNING
            request_count,
            rejected_count,
            window_started_at,
            last_seen_at
    ),
    cleanup AS (
        SELECT count(*) AS deleted_count
        FROM expired
    )
    SELECT
        consumed.request_count <= CAST(:request_limit AS bigint) AS allowed,
        consumed.request_count,
        consumed.rejected_count,
        GREATEST(
            CAST(:request_limit AS bigint) - consumed.request_count,
            0
        ) AS remaining,
        CASE
            WHEN consumed.request_count <= CAST(:request_limit AS bigint) THEN 0
            ELSE GREATEST(
                1,
                CEIL(
                    EXTRACT(
                        EPOCH FROM (
                            consumed.window_started_at
                            + make_interval(
                                secs => CAST(:window_seconds AS double precision)
                            )
                            - consumed.last_seen_at
                        )
                    )
                )
            )::integer
        END AS retry_after_seconds,
        CEIL(
            EXTRACT(
                EPOCH FROM (
                    consumed.window_started_at
                    + make_interval(secs => CAST(:window_seconds AS double precision))
                )
            )
        )::bigint AS reset_epoch
    FROM consumed
    CROSS JOIN cleanup
    """
)


class ApiRateLimitRepository:
    async def consume_window(
        self,
        db: AsyncSession,
        *,
        policy_key: str,
        subject_hash: str,
        request_limit: int,
        window_seconds: int,
    ) -> RateLimitWindowDecision:
        if not policy_key.strip():
            raise ValueError("요청 제한 policy key는 비어 있을 수 없습니다.")
        if len(subject_hash) != 64:
            raise ValueError("요청 제한 subject hash는 SHA-256 hex여야 합니다.")
        if request_limit <= 0 or window_seconds <= 0:
            raise ValueError("요청 제한 횟수와 window는 양수여야 합니다.")

        result = await db.execute(
            _CONSUME_WINDOW_SQL,
            {
                "policy_key": policy_key,
                "subject_hash": subject_hash,
                "request_limit": request_limit,
                "window_seconds": window_seconds,
                "retention_hours": RATE_LIMIT_RETENTION_HOURS,
            },
        )
        row = result.mappings().one()
        return RateLimitWindowDecision(
            allowed=bool(row["allowed"]),
            request_count=int(row["request_count"]),
            rejected_count=int(row["rejected_count"]),
            remaining=int(row["remaining"]),
            retry_after_seconds=int(row["retry_after_seconds"]),
            reset_epoch=int(row["reset_epoch"]),
        )
