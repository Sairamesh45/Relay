from fastapi import APIRouter

from app.api.routes import health, keys, models, providers, routing, usage

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(providers.router, prefix="/providers", tags=["Providers"])
api_router.include_router(models.router, prefix="/models", tags=["Models"])
api_router.include_router(keys.router, prefix="/keys", tags=["Virtual Keys"])
api_router.include_router(routing.router, prefix="/routing", tags=["Routing"])
api_router.include_router(usage.router, prefix="/usage", tags=["Usage Tracking"])

__all__ = ["api_router"]
