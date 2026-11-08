"""Authentication service for Google Identity Services and Relay JWT sessions."""

import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import HTTPException, Response, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.refresh_token import RefreshToken
from app.models.user import User

logger = logging.getLogger(__name__)
settings = get_settings()

VALID_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
ACCESS_TOKEN_COOKIE_NAME = "access_token"
REFRESH_TOKEN_COOKIE_NAME = "refresh_token"


def _hash_token(raw_token: str) -> str:
    """Compute SHA-256 hash of a token string."""
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


def verify_google_id_token(id_token: str) -> dict[str, Any]:
    """Verify and decode a Google ID token using google-auth.

    Validates signature, issuer, audience, and verifies email status.
    """
    if not id_token or not id_token.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google ID token is required.",
        )

    try:
        request = google_requests.Request()
        # If GOOGLE_CLIENT_ID is configured, enforce audience check; otherwise allow None
        audience = settings.GOOGLE_CLIENT_ID if settings.GOOGLE_CLIENT_ID else None
        claims = google_id_token.verify_oauth2_token(
            id_token.strip(),
            request,
            audience=audience,
        )
    except ValueError as exc:
        logger.warning("Google ID token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Google ID token: {exc}",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error verifying Google ID token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Failed to verify Google ID token.",
        ) from exc

    # Validate issuer
    issuer = claims.get("iss")
    if issuer not in VALID_GOOGLE_ISSUERS:
        logger.warning("Invalid Google ID token issuer: %s", issuer)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token issuer '{issuer}'. Expected Google issuer.",
        )

    # Require verified email
    email_verified = claims.get("email_verified")
    if email_verified is not True:
        logger.warning("Google account email is not verified: %s", claims.get("email"))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google email address must be verified.",
        )

    # Require external subject (sub)
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google ID token missing 'sub' subject claim.",
        )

    return claims


def create_access_token(user: User) -> str:
    """Generate short-lived Relay JWT access token."""
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


async def create_refresh_token(
    user: User, db: AsyncSession
) -> tuple[str, RefreshToken]:
    """Generate long-lived rotating refresh token and persist hashed record."""
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    jti = str(uuid.uuid4())

    payload = {
        "sub": str(user.id),
        "jti": jti,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    raw_token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")
    token_hash = _hash_token(raw_token)

    db_token = RefreshToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=token_hash,
        jti=jti,
        expires_at=expires_at,
        is_revoked=False,
        created_at=now,
    )
    db.add(db_token)
    await db.flush()

    return raw_token, db_token


def decode_relay_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    """Decode and validate a Relay-issued JWT token."""
    try:
        payload = jwt.decode(
            token.strip(),
            settings.JWT_SECRET_KEY,
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature or payload.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    token_type = payload.get("type")
    if token_type != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token type: expected '{expected_type}', got '{token_type}'.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def get_or_create_user_from_google(
    claims: dict[str, Any], db: AsyncSession
) -> User:
    """Find or register a User using verified Google claims.

    Uses Google sub as primary identifier, maps to internal User UUID.
    """
    google_sub = str(claims["sub"]).strip()
    google_email = str(claims.get("email", "")).strip().lower()
    full_name = claims.get("name") or claims.get("given_name")
    avatar_url = claims.get("picture")

    # 1. Search by oauth_sub and oauth_provider='google'
    stmt = select(User).where(
        User.oauth_sub == google_sub, User.oauth_provider == "google"
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        # Update mutable profile info if changed
        updated = False
        if full_name and user.full_name != full_name:
            user.full_name = full_name
            updated = True
        if avatar_url and user.avatar_url != avatar_url:
            user.avatar_url = avatar_url
            updated = True
        if google_email and user.email != google_email:
            user.email = google_email
            updated = True
        if updated:
            await db.flush()
    else:
        # 2. Check if a user with this email already exists (e.g. invited or migrated)
        if google_email:
            stmt_email = select(User).where(User.email == google_email)
            email_result = await db.execute(stmt_email)
            existing_user = email_result.scalar_one_or_none()
            if existing_user:
                existing_user.oauth_provider = "google"
                existing_user.oauth_sub = google_sub
                if full_name and not existing_user.full_name:
                    existing_user.full_name = full_name
                if avatar_url and not existing_user.avatar_url:
                    existing_user.avatar_url = avatar_url
                await db.flush()
                user = existing_user

        # 3. Create new User
        if not user:
            user = User(
                id=uuid.uuid4(),
                email=google_email or None,
                oauth_provider="google",
                oauth_sub=google_sub,
                full_name=full_name,
                avatar_url=avatar_url,
                is_active=True,
            )
            db.add(user)
            await db.flush()
            await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    return user


async def authenticate_with_google(
    id_token: str, db: AsyncSession
) -> tuple[User, str, str]:
    """Verify Google token, provision/update user, and generate access + refresh tokens."""
    claims = verify_google_id_token(id_token)
    user = await get_or_create_user_from_google(claims, db)

    access_token = create_access_token(user)
    raw_refresh_token, _ = await create_refresh_token(user, db)
    await db.commit()
    await db.refresh(user)

    return user, access_token, raw_refresh_token


async def authenticate_with_email(
    email: str, db: AsyncSession, full_name: str | None = None
) -> tuple[User, str, str]:
    """Authenticate or register user with email and generate access + refresh tokens."""
    clean_email = email.strip().lower()
    if not clean_email or "@" not in clean_email or "." not in clean_email.split("@")[-1]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A valid email address is required.",
        )

    stmt = select(User).where(User.email == clean_email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        computed_name = (
            full_name
            or clean_email.split("@")[0].replace(".", " ").replace("-", " ").title()
        )
        user = User(
            id=uuid.uuid4(),
            email=clean_email,
            full_name=computed_name,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    access_token = create_access_token(user)
    raw_refresh_token, _ = await create_refresh_token(user, db)
    await db.commit()
    await db.refresh(user)

    return user, access_token, raw_refresh_token


async def rotate_refresh_token(
    raw_refresh_token: str, db: AsyncSession
) -> tuple[User, str, str]:
    """Rotate an active refresh token: revoke current token and issue new token pair."""
    decode_relay_token(raw_refresh_token, expected_type="refresh")
    token_hash = _hash_token(raw_refresh_token)

    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    result = await db.execute(stmt)
    db_token = result.scalar_one_or_none()

    if not db_token:
        logger.warning(
            "Refresh token not found in database: token_hash=%s", token_hash[:12]
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token.",
        )

    if db_token.is_revoked:
        logger.warning(
            "Attempted reuse of revoked refresh token: id=%s, user_id=%s",
            db_token.id,
            db_token.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked.",
        )

    if db_token.expires_at <= datetime.now(UTC):
        logger.warning("Refresh token has expired in database: id=%s", db_token.id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired.",
        )

    # Fetch user
    user_stmt = select(User).where(User.id == db_token.user_id)
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive or not found.",
        )

    # Mark current token revoked and rotated
    db_token.is_revoked = True
    db_token.rotated_at = datetime.now(UTC)

    # Generate new token pair
    new_access_token = create_access_token(user)
    new_raw_refresh_token, _ = await create_refresh_token(user, db)
    await db.commit()

    return user, new_access_token, new_raw_refresh_token


async def revoke_refresh_token(raw_refresh_token: str, db: AsyncSession) -> bool:
    """Revoke a refresh token upon logout."""
    if not raw_refresh_token:
        return False

    token_hash = _hash_token(raw_refresh_token)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    result = await db.execute(stmt)
    db_token = result.scalar_one_or_none()

    if db_token and not db_token.is_revoked:
        db_token.is_revoked = True
        db_token.rotated_at = datetime.now(UTC)
        await db.commit()
        return True

    return False


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
) -> None:
    """Set secure HttpOnly cookies for access and refresh tokens."""
    is_secure = settings.AUTH_COOKIE_SECURE or settings.APP_ENV.lower() == "production"

    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=is_secure,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        domain=settings.AUTH_COOKIE_DOMAIN,
    )

    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=is_secure,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/",
        domain=settings.AUTH_COOKIE_DOMAIN,
    )


def clear_auth_cookies(response: Response) -> None:
    """Delete authentication cookies upon logout."""
    response.delete_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        path="/",
        domain=settings.AUTH_COOKIE_DOMAIN,
    )
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        path="/",
        domain=settings.AUTH_COOKIE_DOMAIN,
    )
