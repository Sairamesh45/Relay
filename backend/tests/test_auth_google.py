"""Comprehensive test suite for Google Sign-In authentication, token rotation, and user isolation."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

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


def _generate_unique_google_claims() -> dict:
    """Generate isolated Google OAuth claims dictionary."""
    unique_id = uuid.uuid4().hex[:8]
    return {
        "sub": f"google-sub-{unique_id}",
        "email": f"relay.user.{unique_id}@gmail.com",
        "email_verified": True,
        "name": f"Relay User {unique_id}",
        "picture": f"https://lh3.googleusercontent.com/avatar-{unique_id}.png",
        "iss": "https://accounts.google.com",
        "aud": settings.GOOGLE_CLIENT_ID or "relay-client-id",
        "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
    }


@pytest.mark.asyncio
async def test_google_auth_registration_success(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """Test new user registration via verified Google ID token."""
    claims = _generate_unique_google_claims()
    with patch(
        "app.services.auth_service.google_id_token.verify_oauth2_token",
        return_value=claims,
    ):
        response = await async_client.post(
            "/api/auth/google",
            json={"id_token": "valid-simulated-google-jwt-token"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["user"]["email"] == claims["email"]
    assert data["user"]["full_name"] == claims["name"]
    assert data["user"]["avatar_url"] == claims["picture"]
    assert data["user"]["is_active"] is True
    user_id = uuid.UUID(data["user"]["id"])

    # Verify cookies
    assert ACCESS_TOKEN_COOKIE_NAME in response.cookies
    assert REFRESH_TOKEN_COOKIE_NAME in response.cookies

    # Verify User record in DB
    user = await db_session.get(User, user_id, populate_existing=True)
    assert user is not None
    assert user.oauth_provider == "google"
    assert user.oauth_sub == claims["sub"]

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
):
    """Test login for an already registered Google user without creating duplicates."""
    claims = _generate_unique_google_claims()
    with patch(
        "app.services.auth_service.google_id_token.verify_oauth2_token",
        return_value=claims,
    ):
        # 1. First authentication (registers user)
        res1 = await async_client.post(
            "/api/auth/google",
            json={"id_token": "token-1"},
        )
        assert res1.status_code == 200
        user_id_1 = res1.json()["user"]["id"]

        # 2. Second authentication with updated full_name
        updated_claims = dict(claims)
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
    stmt = select(User).where(User.oauth_sub == claims["sub"])
    users = (await db_session.execute(stmt)).scalars().all()
    assert len(users) == 1


@pytest.mark.asyncio
async def test_google_auth_link_existing_email_user(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """Test linking Google sub to an existing account that had matching email."""
    unique_id = uuid.uuid4().hex[:8]
    unique_email = f"preexisting_{unique_id}@studio.dev"
    unique_sub = f"google-sub-{unique_id}"

    pre_existing_id = uuid.uuid4()
    pre_user = User(
        id=pre_existing_id,
        email=unique_email,
        is_active=True,
    )
    db_session.add(pre_user)
    await db_session.commit()

    claims = {
        "sub": unique_sub,
        "email": unique_email,
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

    refreshed_user = await db_session.get(User, pre_existing_id, populate_existing=True)
    assert refreshed_user.oauth_provider == "google"
    assert refreshed_user.oauth_sub == unique_sub


@pytest.mark.asyncio
async def test_google_auth_unverified_email_rejected(async_client: AsyncClient):
    """Test rejection when Google reports email is not verified."""
    unverified_claims = {
        "sub": f"google-unverified-{uuid.uuid4().hex[:6]}",
        "email": f"unverified_{uuid.uuid4().hex[:6]}@gmail.com",
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
        email=f"me.user.{uuid.uuid4().hex[:8]}@relay.internal",
        full_name="Me User",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(user)

    # 1. Test via HttpOnly access_token cookie
    res_cookie = await async_client.get(
        "/api/auth/me",
        cookies={ACCESS_TOKEN_COOKIE_NAME: token},
    )
    assert res_cookie.status_code == 200
    assert res_cookie.json()["user"]["email"] == user.email

    # 2. Test via Authorization: Bearer <token>
    res_bearer = await async_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_bearer.status_code == 200
    assert res_bearer.json()["user"]["email"] == user.email


@pytest.mark.asyncio
async def test_get_me_expired_token(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Test GET /api/auth/me rejects an expired Relay access token."""
    monkeypatch.setattr(settings, "ENABLE_DEV_AUTH", False)

    expired_payload = {
        "sub": str(uuid.uuid4()),
        "email": "expired@test.com",
        "type": "access",
        "iat": int((datetime.now(UTC) - timedelta(hours=2)).timestamp()),
        "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
    }
    expired_token = jwt.encode(
        expired_payload, settings.JWT_SECRET_KEY, algorithm="HS256"
    )

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
        email=f"inactive.{uuid.uuid4().hex[:8]}@relay.internal",
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
        email=f"rotator.{uuid.uuid4().hex[:8]}@relay.internal",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    raw_refresh_1, db_token_1 = await create_refresh_token(user, db_session)
    await db_session.commit()

    # 1. Rotate token via cookie
    rotate_res = await async_client.post(
        "/api/auth/refresh",
        cookies={REFRESH_TOKEN_COOKIE_NAME: raw_refresh_1},
    )

    assert rotate_res.status_code == 200
    assert rotate_res.json()["status"] == "ok"

    # Verify old token is now marked revoked in DB
    refreshed_db_token = await db_session.get(
        RefreshToken, db_token_1.id, populate_existing=True
    )
    assert refreshed_db_token.is_revoked is True
    assert refreshed_db_token.rotated_at is not None

    # New refresh token is set in response cookies
    raw_refresh_2 = rotate_res.cookies.get(REFRESH_TOKEN_COOKIE_NAME)
    assert raw_refresh_2 is not None
    assert raw_refresh_2 != raw_refresh_1

    # 2. Attempting to reuse old revoked token is rejected (replay attack prevention)
    replay_res = await async_client.post(
        "/api/auth/refresh",
        cookies={REFRESH_TOKEN_COOKIE_NAME: raw_refresh_1},
    )
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
        email=f"logout.user.{uuid.uuid4().hex[:8]}@relay.internal",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    raw_refresh, db_token = await create_refresh_token(user, db_session)
    await db_session.commit()

    logout_res = await async_client.post(
        "/api/auth/logout",
        cookies={
            REFRESH_TOKEN_COOKIE_NAME: raw_refresh,
            ACCESS_TOKEN_COOKIE_NAME: "dummy-access",
        },
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["status"] == "ok"

    # Verify DB token is revoked
    refreshed_token = await db_session.get(
        RefreshToken, db_token.id, populate_existing=True
    )
    assert refreshed_token.is_revoked is True

    # Verify response sets deletion on cookies
    set_cookie_headers = logout_res.headers.get_list("set-cookie")
    assert any(ACCESS_TOKEN_COOKIE_NAME in h for h in set_cookie_headers)
    assert any(REFRESH_TOKEN_COOKIE_NAME in h for h in set_cookie_headers)


@pytest.mark.asyncio
async def test_user_isolation_virtual_keys(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    """Test strict tenant isolation: User B cannot view or access User A's virtual keys."""
    unique_a = uuid.uuid4().hex[:8]
    unique_b = uuid.uuid4().hex[:8]
    user_a = User(
        id=uuid.uuid4(), email=f"user_a_{unique_a}@tenant.com", is_active=True
    )
    user_b = User(
        id=uuid.uuid4(), email=f"user_b_{unique_b}@tenant.com", is_active=True
    )
    db_session.add_all([user_a, user_b])
    await db_session.commit()

    token_a = create_access_token(user_a)
    token_b = create_access_token(user_b)

    # 1. User A creates a virtual API key
    res_create = await async_client.post(
        "/api/v1/keys",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": f"user-a-secret-key-{unique_a}"},
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
    # User B should see NO keys from User A
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
    unique_id = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(), email=f"dual.mount.{unique_id}@test.com", is_active=True
    )
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(user)

    res1 = await async_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    res2 = await async_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res1.json()["user"]["email"] == user.email
    assert res2.json()["user"]["email"] == user.email
