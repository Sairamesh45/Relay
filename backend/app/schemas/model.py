"""Pydantic schemas for unified models, provider offerings, and registry queries."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProviderOfferingRead(BaseModel):
    """Schema representing a provider-specific offering of a model."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    provider_model_id: str
    credential_id: uuid.UUID | None = None

    context_window: int | None = None
    max_output_tokens: int | None = None

    input_price_per_million: Decimal | None = None
    output_price_per_million: Decimal | None = None

    supports_streaming: bool | None = None
    supports_tools: bool | None = None
    supports_structured_output: bool | None = None
    supports_vision: bool | None = None
    supports_reasoning: bool | None = None

    availability_status: str
    metadata_source: str
    capability_metadata: dict[str, Any] = Field(default_factory=dict)

    last_seen_at: datetime | None = None
    last_verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UnifiedModelRead(BaseModel):
    """Schema representing canonical model identity and user-accessible provider offerings."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    canonical_id: str
    display_name: str | None = None
    description: str | None = None
    provider_model_family: str | None = None
    modality: str | None = None
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)

    created_at: datetime
    updated_at: datetime

    provider_offerings: list[ProviderOfferingRead] = Field(default_factory=list)


class UnifiedModelListResponse(BaseModel):
    """Paginated list response of unified models."""

    total: int
    limit: int
    offset: int
    items: list[UnifiedModelRead]


class ProviderSummaryItem(BaseModel):
    """Summary of model availability for a specific provider."""

    provider: str
    total_models: int
    available_models: int
    credentials_count: int
    modalities: list[str] = Field(default_factory=list)


class ProviderSummaryResponse(BaseModel):
    """Aggregated provider summary for the user."""

    providers: list[ProviderSummaryItem]
