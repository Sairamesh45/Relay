from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.services.health import HealthService

router = APIRouter()


def get_health_service() -> HealthService:
    return HealthService()


@router.get("/health", summary="Health check endpoint")
async def health_check(
    service: HealthService = Depends(get_health_service),
) -> Dict[str, Any]:
    """Return health status of the API Gateway."""
    return await service.check_health()
