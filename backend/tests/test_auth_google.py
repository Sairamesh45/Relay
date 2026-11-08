"""Comprehensive test suite for Google Sign-In authentication, token rotation, and user isolation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
import uuid

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services.auth_service import (
    ACCESS_TOKEN_COOKIE_NAME,
    REFRESH_TOKEN_COOKIE_NAME,
    create_access_token,
    create_refresh_token,
)

settings = get_settings()


@pytest.fixture
def mock_google_claims():
    """Standard verified Google OAuth claims dictionary."""
    return {
        "sub": "google-oauth2-unique-sub-1001",
        "email": "relay.user@gmail.com",
        "email_verified": True,
        "name": "Relay Test User",
        "picture": "https://lh3.googleusercontent.com/test-avatar.png",
        "iss": "https://accounts.google.com",
        "aud": settings.GOOGLE_CLIENT_ID or "relay-client-id",
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }


@pytest.mark.asyncio
async def test_google_auth_registration_success(
    async_client: AsyncClient,
    db_session: AsyncSession,
    mock_google_claims: dict,
):
    """Test new user registration via verified Google ID token."""
    with patch(
        "app.services.auth_service.google_id_token.verify_oauth2_token",
        return_value=mock_google_claims,
    ):
        response = await async_client.post(
            "/api/auth/google",
            json={"id_token": "valid-simulated-google-jwt-token"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["user"]["email"] == "relay.user@gmail.com"
    assert data["user"]["full_name"] == "Relay Test User"
    assert data["user"]["avatar_url"] == "https://lh3.googleusercontent.com/test-avatar.png"
    assert data["user"]["is_active"] is True
    user_id = uuid.UUID(data["user"]["id"])

    # Verify cookies
    assert ACCESS_TOKEN_COOKIE_NAME in response.cookies
    assert REFRESH_TOKEN_COOKIE_NAME in response.cookies

    # Verify User record in DB
    user = await db_session.get(User, user_id)
    assert user is not None
    assert user.oauth_provider == "google"
    assert user.oauth_sub == "google-oauth2-unique-sub-1001"

    # Verify RefreshToken record in DB
    token_stmt = select(RefreshToken).where(RefreshToken.user_id == user_id)
    token_res = await db_session.execute(token_stmt)
    refresh_tokens = token_res.scalars().all()
    assert len(refresh_tokens) >= 1
    assert refresh_tokens[0].is_revoked is False


@pytest.mark.asyncio
async def test_google_auth_login_existing_user(
    async_client: AsyncClient,
    db_session: AsyncSession,
    mock_google_claims: dict,
):
    """Test login for an already registered Google user without creating duplicates."""
    with patch(
        "app.services.auth_service.google_id_token.verify_oauth2_token",
        return_value=mock_google_claims,
    ):
        # 1. First authentication (registers user)
        res1 = await async_client.post(
            "/api/auth/google",
            json={"id_token": "token-1"},
        )
        assert res1.status_code == 200
        user_id_1 = res1.json()["user"]["id"]

        # 2. Second authentication with updated full_name
        updated_claims = dict(mock_google_claims)
        updated_claims["name"] = "Relay Updated Name"
        with patch(
            "app.services.auth_service.google_id_token.verify_oauth2_token",
            return_value=updated_claims,
        ):
            res2 = await async_client.post(
                "/api/auth/google",
                json={"id_token": "token-2"},
            )

    assert res2.status_code == 200
    assert res2.json()["user"]["id"] == user_id_1
    assert res2.json()["user"]["full_name"] == "Relay Updated Name"

    # Verify only one user exists with this sub
    stmt = select(User).where(User.oauth_sub == mock_google_claims["sub"])
    users = (await db_session.execute(stmt)).scalars().all()
    assert len(users) == 1


@pytest.mark.asyncio
async def test_google_auth_link_existing_email_user(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """Test linking Google sub to an existing account that had matching email."""
    pre_existing_id = uuid.uuid4()
    pre_user = User(
        id=pre_existing_id,
        email="preexisting@studio.dev",
        is_active=True,
    )
    db_session.add(pre_user)
    await db_session.commit()

    claims = {
        "sub": "new-google-sub-777",
        "email": "preexisting@studio.dev",
        "email_verified": True,
        "name": "Studio Dev",
        "iss": "accounts.google.com",
    }

    with patch(
        "app.services.auth_service.google_id_token.verify_oauth2_token",
        return_value=claims,
    ):
        response = await async_client.post(
            "/api/auth/google",
            json={"id_token": "token-xyz"},
        )

    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(pre_existing_id)

    refreshed_user = await db_session.get(User, pre_existing_id)
    assert refreshed_user.oauth_provider == "google"
    assert refreshed_user.oauth_sub == "new-google-sub-777"


@pytest.mark.asyncio
async def test_google_auth_unverified_email_rejected(async_client: AsyncClient):
    """Test rejection when Google reports email is not verified."""
    unverified_claims = {
        "sub": "google-unverified-1",
        "email": "unverified@gmail.com",
        "email_verified": False,
        "iss": "https://accounts.google.com",
    }

    with patch(
        "app.services.auth_service.google_id_token.verify_oauth2_token",
        return_value=unverified_claims,
    ):
        response = await async_client.post(
            "/api/auth/google",
            json={"id_token": "unverified-token"},
        )

    assert response.status_code == 400
    assert "verified" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_google_auth_invalid_token_rejected(async_client: AsyncClient):
    """Test rejection when Google ID token fails cryptographic verification."""
    with patch(
        "app.services.auth_service.google_id_token.verify_oauth2_token",
        side_effect=ValueError("Token expired or corrupted"),
    ):
        response = await async_client.post(
            "/api/auth/google",
            json={"id_token": "bad-token"},
        )

    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_google_auth_invalid_issuer_rejected(async_client: AsyncClient):
    """Test rejection when token issuer is not Google."""
    bad_issuer_claims = {
        "sub": "bad-iss-1",
        "email": "test@evil.com",
        "email_verified": True,
        "iss": "https://attacker.example.com",
    }

    with patch(
        "app.services.auth_service.google_id_token.verify_oauth2_token",
        return_value=bad_issuer_claims,
    ):
        response = await async_client.post(
            "/api/auth/google",
            json={"id_token": "token-from-rogue-issuer"},
        )

    assert response.status_code == 401
    assert "issuer" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_me_with_cookie_and_bearer(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """Test GET /api/auth/me succeeds with HttpOnly cookie and Bearer header."""
    user = User(
        id=uuid.uuid4(),
        email="me.user@relay.internal",
        full_name="Me User",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token(user)

    # 1. Test via HttpOnly access_token cookie
    async_client.cookies.set(ACCESS_TOKEN_COOKIE_NAME, token)
    res_cookie = await async_client.get("/api/auth/me")
    assert res_cookie.status_code == 200
    assert res_cookie.json()["user"]["email"] == "me.user@relay.internal"

    # Clear cookie
    async_client.cookies.clear()

    # 2. Test via Authorization: Bearer <token>
    res_bearer = await async_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_bearer.status_code == 200
    assert res_bearer.json()["user"]["email"] == "me.user@relay.internal"


@pytest.mark.asyncio
async def test_get_me_expired_token(async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    """Test GET /api/auth/me rejects an expired Relay access token."""
    monkeypatch.setattr(settings, "ENABLE_DEV_AUTH", False)

    expired_payload = {
        "sub": str(uuid.uuid4()),
        "email": "expired@test.com",
        "type": "access",
        "iat": int((datetime.now(UTC) - timedelta(hours=2)).timestamp()),
        "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
    }
    expired_token = jwt.encode(expired_payload, settings.JWT_SECRET_KEY, algorithm="HS256")

    response = await async_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_me_inactive_user_forbidden(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """Test inactive user is rejected with 403 Forbidden."""
    inactive_user = User(
        id=uuid.uuid4(),
        email="inactive@relay.internal",
        is_active=False,
    )
    db_session.add(inactive_user)
    await db_session.commit()

    token = create_access_token(inactive_user)
    response = await async_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert "inactive" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_refresh_token_rotation_lifecycle(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """Test complete refresh token rotation and revocation of previous token."""
    user = User(
        id=uuid.uuid4(),
        email="rotator@relay.internal",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    raw_refresh_1, db_token_1 = await create_refresh_token(user, db_session)
    await db_session.commit()

    # 1. Rotate token via cookie
    async_client.cookies.set(REFRESH_TOKEN_COOKIE_NAME, raw_refresh_1)
    rotate_res = await async_client.post("/api/auth/refresh")

    assert rotate_res.status_code == 200
    assert rotate_res.json()["status"] == "ok"

    # Verify old token is now marked revoked in DB
    await db_session.refresh(db_token_1)
    assert db_token_1.is_revoked is True
    assert db_token_1.rotated_at is not None

    # New refresh token is set in response cookies
    raw_refresh_2 = rotate_res.cookies.get(REFRESH_TOKEN_COOKIE_NAME)
    assert raw_refresh_2 is not None
    assert raw_refresh_2 != raw_refresh_1

    # 2. Attempting to reuse old revoked token is rejected (replay attack prevention)
    async_client.cookies.set(REFRESH_TOKEN_COOKIE_NAME, raw_refresh_1)
    replay_res = await async_client.post("/api/auth/refresh")
    assert replay_res.status_code == 401
    assert "revoked" in replay_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_logout_revokes_token_and_clears_cookies(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """Test logout revokes the active refresh token and clears session cookies."""
    user = User(
        id=uuid.uuid4(),
        email="logout.user@relay.internal",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    raw_refresh, db_token = await create_refresh_token(user, db_session)
    await db_session.commit()

    async_client.cookies.set(REFRESH_TOKEN_COOKIE_NAME, raw_refresh)
    async_client.cookies.set(ACCESS_TOKEN_COOKIE_NAME, "dummy-access")

    logout_res = await async_client.post("/api/auth/logout")
    assert logout_res.status_code == 200
    assert logout_res.json()["status"] == "ok"

    # Verify DB token is revoked
    await db_session.refresh(db_token)
    assert db_token.is_revoked is True

    # Verify response sets deletion / clearing on cookies
    set_cookie_headers = logout_res.headers.get_list("set-cookie")
    assert any(ACCESS_TOKEN_COOKIE_NAME in h for h in set_cookie_headers)
    assert any(REFRESH_TOKEN_COOKIE_NAME in h for h in set_cookie_headers)


@pytest.mark.asyncio
async def test_user_isolation_virtual_keys(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """Test strict tenant isolation: User B cannot view or access User A's virtual keys."""
    # Create User A
    user_a = User(id=uuid.uuid4(), email="user_a@tenant.com", is_active=True)
    # Create User B
    user_b = User(id=uuid.uuid4(), email="user_b@tenant.com", is_active=True)
    db_session.add_all([user_a, user_b])
    await db_session.commit()

    token_a = create_access_token(user_a)
    token_b = create_access_token(user_b)

    # 1. User A creates a virtual API key
    res_create = await async_client.post(
        "/api/v1/keys",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "user-a-secret-key"},
    )
    assert res_create.status_code == 201
    user_a_key_id = res_create.json()["id"]

    # 2. User B lists virtual API keys
    res_list_b = await async_client.get(
        "/api/v1/keys",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_list_b.status_code == 200
    b_keys = res_list_b.json()["keys"]
    # User B should see NO keys
    assert not any(k["id"] == user_a_key_id for k in b_keys)

    # 3. User B attempts to access User A's key by ID -> 404 Not Found
    res_get_b = await async_client.get(
        f"/api/v1/keys/{user_a_key_id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_get_b.status_code == 404

    # 4. User A accesses their own key -> 200 OK
    res_get_a = await async_client.get(
        f"/api/v1/keys/{user_a_key_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_get_a.status_code == 200
    assert res_get_a.json()["id"] == user_a_key_id


@pytest.mark.asyncio
async def test_dual_mount_auth_endpoints(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """Verify auth endpoints respond identically under /api/auth and /api/v1/auth."""
    user = User(id=uuid.uuid4(), email="dual.mount@test.com", is_active=True)
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(user)

    res1 = await async_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    res2 = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res1.json()["user"]["email"] == "dual.mount@test.com"
    assert res2.json()["user"]["email"] == "dual.mount@test.com"
