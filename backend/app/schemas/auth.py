"""Pydantic schemas for authentication and user identity."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GoogleAuthRequest(BaseModel):
    """Payload for Google ID token authentication."""

    id_token: str = Field(..., description="Google ID token returned by Google Identity Services")


class RefreshTokenRequest(BaseModel):
    """Optional payload for refresh token when not provided in HttpOnly cookie."""

    refresh_token: str | None = Field(default=None, description="Optional raw refresh token")


class UserResponse(BaseModel):
    """Public user identity representation."""

    id: uuid.UUID
    email: str | None = None
    full_name: str | None = None
    avatar_url: str | None = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuthResponse(BaseModel):
    """Response returned upon successful authentication or token refresh."""

    user: UserResponse
    status: str = "ok"
