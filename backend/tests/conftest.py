from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import close_db_engine, get_session_factory
from app.main import app

settings = get_settings()


@pytest.fixture(autouse=True)
def setup_test_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure test settings are consistently configured for all test runs."""
    monkeypatch.setattr(settings, "ENABLE_DEV_AUTH", True)


@pytest.fixture(autouse=True)
async def cleanup_db_session() -> AsyncGenerator[None, None]:
    """Dispose DB engine after each async test to prevent cross-event-loop connection leakage."""
    yield
    await close_db_engine()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated database session for testing."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an asynchronous HTTP client for end-to-end endpoint testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
