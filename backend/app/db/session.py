import logging
from collections.abc import AsyncGenerator
from typing import Any

from redis.asyncio import Redis, from_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

logger = logging.getLogger("unified_ai_gateway.db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Create or return the cached asynchronous database engine.

    Configures connection pooling and ensures no connection is dialed during module import.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        engine_kwargs: dict[str, Any] = {
            "echo": settings.DEBUG and settings.APP_ENV == "development",
            "pool_pre_ping": True,
            "pool_recycle": settings.DB_POOL_RECYCLE,
        }
        if "sqlite" not in settings.DATABASE_URL:
            engine_kwargs.update(
                {
                    "pool_size": settings.DB_POOL_SIZE,
                    "max_overflow": settings.DB_MAX_OVERFLOW,
                    "pool_timeout": settings.DB_POOL_TIMEOUT,
                }
            )
        _engine = create_async_engine(settings.DATABASE_URL, **engine_kwargs)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the cached async sessionmaker factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides an asynchronous database session with managed lifecycle."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def close_db_engine() -> None:
    """Dispose the database engine and connection pool during application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine connection pool disposed.")


class RedisManager:
    """Reusable Redis connection manager supporting lazy initialization, pings, and graceful shutdowns."""

    def __init__(self) -> None:
        self._client: Redis | None = None

    def get_client(self) -> Redis:
        """Return the Redis client, initializing lazily if not yet created."""
        if self._client is None:
            settings = get_settings()
            self._client = from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
            )
        return self._client

    async def ping(self) -> bool:
        """Ping Redis server to verify connectivity. Never reports healthy if unavailable."""
        try:
            client = self.get_client()
            response = await client.ping()
            return bool(response)
        except Exception as e:
            logger.warning("Redis ping check failed: %s", str(e))
            return False

    async def close(self) -> None:
        """Close Redis connections cleanly during application shutdown."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as e:
                logger.warning("Error while closing Redis connection: %s", str(e))
            finally:
                self._client = None
                logger.info("Redis connection closed.")


redis_manager = RedisManager()


def get_redis() -> Redis:
    """Reusable dependency to acquire the Redis client."""
    return redis_manager.get_client()
