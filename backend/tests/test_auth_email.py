"""Tests for production email authentication and user isolation."""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@pytest.mark.asyncio
async def test_email_auth_registration_and_login(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """Test user registration and subsequent login via email."""
    test_email = f"prod_test_{uuid.uuid4().hex[:8]}@example.com"

    # 1. First registration
    response = await async_client.post(
        "/api/v1/auth/email",
        json={"email": test_email, "full_name": "Test User"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["user"]["email"] == test_email
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies

    user_id = data["user"]["id"]

    # Verify user in database
    result = await db_session.execute(select(User).where(User.email == test_email))
    db_user = result.scalar_one_or_none()
    assert db_user is not None
    assert str(db_user.id) == user_id

    # 2. Subsequent login with same email
    response2 = await async_client.post(
        "/api/v1/auth/email",
        json={"email": test_email},
    )
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["user"]["id"] == user_id


@pytest.mark.asyncio
async def test_email_auth_invalid_email(async_client: AsyncClient):
    """Test rejection of malformed email addresses."""
    response = await async_client.post(
        "/api/v1/auth/email",
        json={"email": "not-an-email"},
    )
    assert response.status_code == 400
