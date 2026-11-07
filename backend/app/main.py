from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import get_settings
from app.core.logging import logger, setup_logging
from app.db.session import close_db_engine, redis_manager

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle events (startup and shutdown)."""
    # 1. Startup
    setup_logging(settings.LOG_LEVEL)
    logger.info("Starting %s in %s environment", settings.APP_NAME, settings.APP_ENV)
    logger.info("API prefix mounted at: %s", settings.API_V1_PREFIX)

    yield

    # 2. Shutdown
    logger.info("Initiating graceful shutdown for %s...", settings.APP_NAME)
    await redis_manager.close()
    await close_db_engine()
    logger.info("Application shutdown completed.")


def create_application() -> FastAPI:
    """FastAPI application factory configuring middleware, routes, and lifespan."""
    app = FastAPI(
        title=settings.APP_NAME,
        description="Unified AI Gateway - Scalable core infrastructure for multi-provider AI routing and governance.",
        version="0.1.0",
        debug=settings.DEBUG,
        lifespan=lifespan,
    )

    # Configure Cross-Origin Resource Sharing (CORS)
    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Register API routes with configured version prefix
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_application()
