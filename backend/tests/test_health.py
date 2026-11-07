import pytest
from httpx import AsyncClient

from app.core.config import get_settings

settings = get_settings()


@pytest.mark.asyncio
async def test_health_check_endpoint(async_client: AsyncClient) -> None:
    response = await async_client.get(f"{settings.API_V1_STR}/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["project"] == settings.PROJECT_NAME
    assert data["environment"] == settings.ENVIRONMENT


@pytest.mark.asyncio
async def test_root_health_check_endpoint(async_client: AsyncClient) -> None:
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
