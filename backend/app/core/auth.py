"""Authentication boundary supporting development identity and future Google OAuth integration."""

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.models.user import User

settings = get_settings()

DEFAULT_DEV_USER_EMAIL = "developer@gateway.local"
DEFAULT_DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_dev_user_id: Annotated[str | None, Header(alias="X-Dev-User-Id")] = None,
    x_dev_user_email: Annotated[str | None, Header(alias="X-Dev-User-Email")] = None,
) -> User:
    """Resolve the authenticated user.

    Security Boundary Rules:
    1. Development identity only functions when APP_ENV == 'development' AND ENABLE_DEV_AUTH is True.
    2. Any attempt to use development identity headers in production or staging is rejected with 401.
    3. All credential management operations are strictly scoped to the resolved User entity.
    4. Will be replaced by Google OAuth Bearer token validation in Phase 3.
    """
    is_dev = settings.APP_ENV.lower() == "development"
    dev_auth_enabled = settings.ENABLE_DEV_AUTH

    if not is_dev or not dev_auth_enabled:
        # In production, staging, or whenever dev auth is disabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Production authentication required. Google OAuth is not yet configured.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Resolve identity in development mode
    user_id: uuid.UUID = DEFAULT_DEV_USER_ID
    email: str = DEFAULT_DEV_USER_EMAIL

    if x_dev_user_id:
        try:
            user_id = uuid.UUID(x_dev_user_id.strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Dev-User-Id header: must be a valid UUID.",
            ) from exc

    if x_dev_user_email:
        email = x_dev_user_email.strip().lower()
    elif x_dev_user_id and user_id != DEFAULT_DEV_USER_ID:
        email = f"user-{str(user_id)[:8]}@gateway.local"

    # Query or auto-provision the development user in the database
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        # Check if email is already taken by another ID
        email_result = await db.execute(select(User).where(User.email == email))
        existing_email_user = email_result.scalar_one_or_none()
        if existing_email_user is not None:
            user = existing_email_user
        else:
            user = User(
                id=user_id,
                email=email,
                is_active=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    return user
