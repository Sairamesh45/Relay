from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.services.health import HealthService

router = APIRouter()


def get_health_service() -> HealthService:
    """Dependency injection provider for HealthService."""
    return HealthService()


@router.get(
    "/live",
    summary="Liveness probe",
    description="Returns HTTP 200 when the application process is running. Does not check dependencies.",
    status_code=status.HTTP_200_OK,
)
async def liveness(
    service: HealthService = Depends(get_health_service),
) -> dict[str, str]:
    return service.check_liveness()


@router.get(
    "/ready",
    summary="Readiness probe",
    description="Independently verifies PostgreSQL and Redis connectivity. Returns HTTP 503 if any dependency fails.",
)
async def readiness(
    service: HealthService = Depends(get_health_service),
) -> JSONResponse:
    is_ready, details = await service.check_readiness()
    status_code = (
        status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=status_code, content=details)
