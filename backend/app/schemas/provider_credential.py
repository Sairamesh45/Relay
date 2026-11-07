"""Pydantic schemas for provider credential management."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CredentialCreateRequest(BaseModel):
    """Payload for submitting and encrypting a new AI provider credential."""

    api_key: str = Field(
        ...,
        min_length=1,
        description="Plaintext API key from the provider (validated and encrypted immediately; never stored in plaintext)",
    )
    display_name: str | None = Field(
        None,
        max_length=100,
        description="Optional human-readable label for this key (e.g. 'Production Gemini Key')",
    )


class CredentialResponse(BaseModel):
    """Public representation of an encrypted credential (secrets are never returned)."""

    id: uuid.UUID
    provider: str
    display_name: str | None = None
    status: str
    masked_key: str
    key_version: int = 1
    last_validated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CredentialRotateRequest(BaseModel):
    """Optional target key version for credential rotation."""

    target_version: int | None = Field(
        None,
        description="Target encryption key version to rotate to (defaults to active key version)",
    )


class CredentialRotateResponse(BaseModel):
    """Response returned upon rotating a credential's encryption key."""

    id: uuid.UUID
    provider: str
    key_version: int
    updated_at: datetime
    message: str = "Credential encryption key rotated successfully"


class CredentialValidationResponse(BaseModel):
    """Response returned upon re-validating a stored credential with the provider."""

    id: uuid.UUID
    provider: str
    status: str
    is_valid: bool
    last_validated_at: datetime
    message: str = "Credential validated successfully"
