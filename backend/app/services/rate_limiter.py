"""Redis-backed rate limiting service per virtual API key."""

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import case, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.gateway_errors import openai_rate_limit_error
from app.db.session import redis_manager
from app.models.rate_limit import RateLimitBucket

settings = get_settings()
logger = logging.getLogger(__name__)


class RateLimiterService:
    """Atomic fixed-window rate limiter backed by Redis with a DB fallback."""

    _INCREMENT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], 60)
end
local ttl = redis.call('TTL', KEYS[1])
if count > tonumber(ARGV[1]) then
  redis.call('DECR', KEYS[1])
  return {-1, ttl}
end
return {count, ttl}
"""

    def __init__(
        self,
        default_rpm: int | None = None,
        redis_client: Redis | None = None,
    ) -> None:
        self.default_rpm = default_rpm or settings.GATEWAY_RATE_LIMIT_RPM
        self._redis = redis_client
        self._redis_unavailable_logged = False
        self._redis_retry_at = 0.0

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
        if limit <= 0:
            raise ValueError("Rate limit must be greater than zero.")

        if time.monotonic() >= self._redis_retry_at:
            try:
                await self._check_redis_rate_limit(key_id=key_id, limit=limit)
                return
            except RedisError as exc:
                self._redis_retry_at = time.monotonic() + 10.0
                if not self._redis_unavailable_logged:
                    logger.warning(
                        "Redis rate limiter unavailable; using PostgreSQL fallback: %s",
                        exc,
                    )
                    self._redis_unavailable_logged = True
                if settings.RATE_LIMIT_REDIS_REQUIRED:
                    raise RuntimeError(
                        "Redis is required for rate limiting but is unavailable."
                    ) from exc

        await self._check_database_rate_limit(db=db, key_id=key_id, limit=limit)

    async def _check_redis_rate_limit(self, key_id: uuid.UUID, limit: int) -> None:
        """Increment a Redis bucket atomically without holding a database lock."""
        client = self._redis or redis_manager.get_client()
        key = f"{settings.RATE_LIMIT_REDIS_KEY_PREFIX}:{key_id}"
        result = await client.eval(self._INCREMENT_SCRIPT, 1, key, limit)
        count = int(result[0])
        ttl = max(1, int(result[1]))
        if count == -1:
            raise openai_rate_limit_error(
                message=f"Rate limit of {limit} requests per minute exceeded for this API key.",
                retry_after=ttl,
            )

    async def _check_database_rate_limit(
        self,
        db: AsyncSession,
        key_id: uuid.UUID,
        limit: int,
    ) -> None:
        """Fallback limiter for local/dev environments without Redis."""
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

        window_expired = RateLimitBucket.window_start <= now - timedelta(seconds=60)
        increment_stmt = (
            update(RateLimitBucket)
            .where(
                RateLimitBucket.key_id == key_id,
                or_(window_expired, RateLimitBucket.request_count < limit),
            )
            .values(
                window_start=case(
                    (window_expired, now),
                    else_=RateLimitBucket.window_start,
                ),
                request_count=case(
                    (window_expired, 1),
                    else_=RateLimitBucket.request_count + 1,
                ),
            )
            .returning(
                RateLimitBucket.request_count,
                RateLimitBucket.window_start,
            )
        )
        result = await db.execute(increment_stmt)
        updated = result.one_or_none()
        if updated is not None:
            await db.flush()
            return

        bucket_result = await db.execute(
            select(RateLimitBucket.window_start).where(
                RateLimitBucket.key_id == key_id
            )
        )
        window_start = bucket_result.scalar_one()
        elapsed = (now - window_start).total_seconds()
        retry_after = max(1, int(60.0 - elapsed))
        if elapsed < 60.0:
            raise openai_rate_limit_error(
                message=f"Rate limit of {limit} requests per minute exceeded for this API key.",
                retry_after=retry_after,
            )


# Singleton service instance
rate_limiter_service = RateLimiterService()


def get_rate_limiter_service() -> RateLimiterService:
    """FastAPI dependency provider for RateLimiterService."""
    return rate_limiter_service
