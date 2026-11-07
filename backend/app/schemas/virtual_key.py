"""Pydantic schemas for Virtual API Key management."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VirtualKeyCreate(BaseModel):
    """Payload to create a new virtual API key."""

    name: str = Field(
        ..., min_length=1, max_length=100, description="User-defined key label"
    )
    expires_at: datetime | None = Field(
        None, description="Optional ISO timestamp when the key expires"
    )
    permissions: dict[str, Any] = Field(
        default_factory=dict, description="Optional permission scope dict"
    )


class VirtualKeyRead(BaseModel):
    """Metadata for an existing virtual API key. Never exposes raw secret or key hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    key_prefix: str
    permissions: dict[str, Any]
    is_active: bool
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime
    revoked_at: datetime | None = None


class VirtualKeyCreateResponse(BaseModel):
    """Response returned upon key creation or rotation containing the raw plaintext key."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    key_prefix: str
    key: str = Field(
        ..., description="Complete plaintext virtual API key. Displayed only once."
    )
    permissions: dict[str, Any]
    is_active: bool
    expires_at: datetime | None = None
    created_at: datetime


class VirtualKeyListResponse(BaseModel):
    """List response of user's virtual API keys."""

    keys: list[VirtualKeyRead]
