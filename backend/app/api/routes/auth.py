"""Authentication routes for Google Sign-In, token refresh, session validation, and logout."""

import logging
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    GoogleAuthRequest,
    RefreshTokenRequest,
    UserResponse,
)
from app.services.auth_service import (
    REFRESH_TOKEN_COOKIE_NAME,
    authenticate_with_google,
    clear_auth_cookies,
    revoke_refresh_token,
    rotate_refresh_token,
    set_auth_cookies,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/google",
    response_model=AuthResponse,
    summary="Sign in or register with Google",
    description="Verifies Google ID token, generates Relay JWTs, sets HttpOnly cookies, and returns the authenticated user profile.",
)
async def google_auth(
    payload: GoogleAuthRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthResponse:
    """Authenticate or register user with a verified Google Identity Services ID token."""
    user, access_token, refresh_token = await authenticate_with_google(
        id_token=payload.id_token,
        db=db,
    )
    set_auth_cookies(response, access_token=access_token, refresh_token=refresh_token)
    return AuthResponse(user=UserResponse.model_validate(user), status="ok")


@router.post(
    "/refresh",
    response_model=AuthResponse,
    summary="Rotate refresh token and issue new session cookies",
    description="Reads current refresh token from HttpOnly cookie, verifies active status, rotates token in DB, and issues fresh cookies.",
)
async def refresh_session(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: RefreshTokenRequest | None = None,
    cookie_token: Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE_NAME)] = None,
) -> AuthResponse:
    """Rotate refresh token and set new HttpOnly cookies."""
    raw_token = cookie_token or (payload.refresh_token if payload else None)
    if not raw_token:
        # Also check Authorization header fallback
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.strip().lower().startswith("bearer "):
            raw_token = auth_header.strip()[7:].strip()

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user, new_access_token, new_refresh_token = await rotate_refresh_token(
        raw_refresh_token=raw_token,
        db=db,
    )
    set_auth_cookies(
        response, access_token=new_access_token, refresh_token=new_refresh_token
    )
    return AuthResponse(user=UserResponse.model_validate(user), status="ok")


@router.post(
    "/logout",
    summary="Log out and revoke session",
    description="Revokes active refresh token in database and clears authentication HttpOnly cookies.",
)
async def logout(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: RefreshTokenRequest | None = None,
    cookie_token: Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE_NAME)] = None,
) -> dict[str, str]:
    """Revoke refresh token and delete session cookies."""
    raw_token = cookie_token or (payload.refresh_token if payload else None)
    if not raw_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.strip().lower().startswith("bearer "):
            raw_token = auth_header.strip()[7:].strip()

    if raw_token:
        try:
            await revoke_refresh_token(raw_token, db)
        except Exception as exc:
            logger.warning("Error revoking refresh token on logout: %s", exc)

    clear_auth_cookies(response)
    return {"status": "ok", "message": "Successfully logged out."}


@router.get(
    "/me",
    response_model=AuthResponse,
    summary="Get current authenticated user",
    description="Returns user profile resolved from HttpOnly access token cookie or Authorization header.",
)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> AuthResponse:
    """Retrieve currently authenticated user profile."""
    return AuthResponse(user=UserResponse.model_validate(current_user), status="ok")
