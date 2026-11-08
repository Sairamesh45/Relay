"""PostgreSQL-backed rate limiting service per virtual API key."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.gateway_errors import openai_rate_limit_error
from app.models.rate_limit import RateLimitBucket

settings = get_settings()


class RateLimiterService:
    """Fixed-window rate limiter tracking requests per virtual key in PostgreSQL.

    Isolated design ready for drop-in Redis replacement in future phases.
    """

    def __init__(self, default_rpm: int | None = None) -> None:
        self.default_rpm = default_rpm or settings.GATEWAY_RATE_LIMIT_RPM

    async def check_rate_limit(
        self,
        db: AsyncSession,
        key_id: uuid.UUID,
        custom_limit: int | None = None,
    ) -> None:
        """Check and update the rate limit bucket for the given virtual key.

        Raises OpenAIHTTPException with 429 status and Retry-After header if limit exceeded.
        """
        limit = custom_limit or self.default_rpm
        now = datetime.now(UTC)

        from sqlalchemy.dialects.postgresql import insert as pg_insert

        # Ensure bucket exists atomically with ON CONFLICT DO NOTHING
        init_stmt = (
            pg_insert(RateLimitBucket)
            .values(key_id=key_id, window_start=now, request_count=0)
            .on_conflict_do_nothing(index_elements=["key_id"])
        )
        await db.execute(init_stmt)
        await db.flush()

        stmt = (
            select(RateLimitBucket)
            .where(RateLimitBucket.key_id == key_id)
            .with_for_update()
        )
        res = await db.execute(stmt)
        bucket = res.scalar_one()

        elapsed = (now - bucket.window_start).total_seconds()

        if elapsed >= 60.0:
            # Window expired; reset window and counter
            bucket.window_start = now
            bucket.request_count = 1
            await db.flush()
            return

        if bucket.request_count >= limit:
            retry_after = max(1, int(60.0 - elapsed))
            raise openai_rate_limit_error(
                message=f"Rate limit of {limit} requests per minute exceeded for this API key.",
                retry_after=retry_after,
            )

        bucket.request_count += 1
        await db.flush()


# Singleton service instance
rate_limiter_service = RateLimiterService()


def get_rate_limiter_service() -> RateLimiterService:
    """FastAPI dependency provider for RateLimiterService."""
    return rate_limiter_service
