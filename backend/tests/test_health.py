import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.services.health import HealthService

settings = get_settings()


@pytest.mark.asyncio
async def test_liveness_endpoint_returns_200(async_client: AsyncClient) -> None:
    """Verify that GET /health/live returns HTTP 200 OK without dependencies."""
    response = await async_client.get(f"{settings.API_V1_PREFIX}/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"


@pytest.mark.asyncio
async def test_liveness_response_contains_correct_service_name(
    async_client: AsyncClient,
) -> None:
    """Verify that GET /health/live returns service name 'unified-ai-gateway'."""
    response = await async_client.get(f"{settings.API_V1_PREFIX}/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "unified-ai-gateway"


@pytest.mark.asyncio
async def test_readiness_endpoint_success_when_dependencies_healthy(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that GET /health/ready returns HTTP 200 when database and redis are healthy."""

    async def mock_db(self: HealthService) -> bool:
        return True

    async def mock_redis(self: HealthService) -> bool:
        return True

    monkeypatch.setattr(HealthService, "check_database", mock_db)
    monkeypatch.setattr(HealthService, "check_redis", mock_redis)

    response = await async_client.get(f"{settings.API_V1_PREFIX}/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["database"] == "connected"
    assert data["checks"]["redis"] == "connected"


@pytest.mark.asyncio
async def test_readiness_endpoint_returns_503_when_database_unavailable(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that GET /health/ready returns HTTP 503 when the database fails."""

    async def mock_db(self: HealthService) -> bool:
        return False

    async def mock_redis(self: HealthService) -> bool:
        return True

    monkeypatch.setattr(HealthService, "check_database", mock_db)
    monkeypatch.setattr(HealthService, "check_redis", mock_redis)

    response = await async_client.get(f"{settings.API_V1_PREFIX}/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["checks"]["database"] == "disconnected"
    assert data["checks"]["redis"] == "connected"


@pytest.mark.asyncio
async def test_readiness_endpoint_returns_503_when_redis_unavailable(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that GET /health/ready returns HTTP 503 when Redis fails."""

    async def mock_db(self: HealthService) -> bool:
        return True

    async def mock_redis(self: HealthService) -> bool:
        return False

    monkeypatch.setattr(HealthService, "check_database", mock_db)
    monkeypatch.setattr(HealthService, "check_redis", mock_redis)

    response = await async_client.get(f"{settings.API_V1_PREFIX}/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["checks"]["database"] == "connected"
    assert data["checks"]["redis"] == "disconnected"


@pytest.mark.asyncio
async def test_readiness_response_correctly_identifies_individual_states(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that individual states are accurately reported when both dependencies fail."""

    async def mock_db(self: HealthService) -> bool:
        return False

    async def mock_redis(self: HealthService) -> bool:
        return False

    monkeypatch.setattr(HealthService, "check_database", mock_db)
    monkeypatch.setattr(HealthService, "check_redis", mock_redis)

    response = await async_client.get(f"{settings.API_V1_PREFIX}/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["checks"]["database"] == "disconnected"
    assert data["checks"]["redis"] == "disconnected"
