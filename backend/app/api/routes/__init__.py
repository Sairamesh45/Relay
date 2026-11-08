from fastapi import APIRouter

from app.api.routes import (
    auth,
    health,
    keys,
    models,
    providers,
    quotas,
    reliability_events,
    reliability_health,
    routing,
    usage,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(providers.router, prefix="/providers", tags=["Providers"])
api_router.include_router(models.router, prefix="/models", tags=["Models"])
api_router.include_router(keys.router, prefix="/keys", tags=["Virtual Keys"])
api_router.include_router(routing.router, prefix="/routing", tags=["Routing"])
api_router.include_router(usage.router, prefix="/usage", tags=["Usage Tracking"])
api_router.include_router(reliability_health.router, tags=["Reliability Health"])
api_router.include_router(quotas.router, prefix="/quotas", tags=["Quotas"])
api_router.include_router(
    reliability_events.router, prefix="/reliability", tags=["Reliability Events"]
)

__all__ = ["api_router"]
