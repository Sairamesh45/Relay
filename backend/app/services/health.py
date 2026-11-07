import asyncio
import logging
from typing import Any

from sqlalchemy import text

from app.db.session import get_engine, redis_manager

logger = logging.getLogger("unified_ai_gateway.health")


class HealthService:
    """Service layer for performing application liveness and dependency readiness checks."""

    @staticmethod
    def check_liveness() -> dict[str, str]:
        """Perform liveness check without external dependency queries."""
        return {
            "status": "alive",
            "service": "unified-ai-gateway",
        }

    async def check_database(self) -> bool:
        """Verify PostgreSQL connectivity by executing a lightweight SELECT 1 query."""
        try:
            engine = get_engine()
            async with asyncio.timeout(3.0):
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.warning("Database health check failed: %s", type(e).__name__)
            return False

    async def check_redis(self) -> bool:
        """Verify Redis connectivity via ping."""
        try:
            async with asyncio.timeout(3.0):
                return await redis_manager.ping()
        except Exception as e:
            logger.warning("Redis health check failed: %s", type(e).__name__)
            return False

    async def check_readiness(self) -> tuple[bool, dict[str, Any]]:
        """Verify all critical infrastructure dependencies concurrently.

        Returns:
            Tuple of (is_ready: bool, details_dict: dict)
        """
        db_ok, redis_ok = await asyncio.gather(
            self.check_database(),
            self.check_redis(),
            return_exceptions=False,
        )

        checks = {
            "database": "connected" if db_ok else "disconnected",
            "redis": "connected" if redis_ok else "disconnected",
        }

        is_ready = db_ok and redis_ok
        payload = {
            "status": "ready" if is_ready else "unhealthy",
            "checks": checks,
        }

        return is_ready, payload
