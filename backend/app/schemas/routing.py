"""Pydantic schemas for Virtual API Key Routing Policies and Routing Previews."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RoutingPolicyBase(BaseModel):
    """Shared fields for routing policy representations."""

    routing_mode: str = Field(
        default="preset",
        description="Mode of routing: 'preset' or 'custom'.",
    )
    routing_preset: str = Field(
        default="balanced",
        description="Routing preset: balanced, quality_first, speed_first, cost_optimized, custom.",
    )
    quality_weight: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Priority weight for model quality (0.0 - 1.0).",
    )
    speed_weight: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Priority weight for low latency (0.0 - 1.0).",
    )
    availability_weight: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Priority weight for provider availability (0.0 - 1.0).",
    )
    cost_weight: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Priority weight for cost optimization (0.0 - 1.0).",
    )
    model_access_profile: str = Field(
        default="all_models",
        description="Modality restriction profile: all_models, text_only, text_image, text_audio, text_video, all_modalities.",
    )
    required_capabilities: list[str] = Field(
        default_factory=list,
        description="Hard capability requirements (e.g. streaming, tools, vision, structured_output).",
    )
    allowed_providers: list[str] = Field(
        default_factory=list,
        description="Permitted providers. Empty list permits all active providers.",
    )
    excluded_providers: list[str] = Field(
        default_factory=list,
        description="Blacklisted providers.",
    )
    allowed_models: list[str] = Field(
        default_factory=list,
        description="Permitted model identifiers. Empty list permits all active models.",
    )
    excluded_models: list[str] = Field(
        default_factory=list,
        description="Blacklisted model identifiers.",
    )
    preferred_provider: str | None = Field(
        default=None,
        description="Optional preferred provider for tie-breaking.",
    )
    preferred_credential_id: uuid.UUID | None = Field(
        default=None,
        description="Optional preferred credential ID.",
    )
    minimum_context_window: int | None = Field(
        default=None,
        ge=1,
        description="Minimum token context window required.",
    )
    maximum_cost_per_request: float | None = Field(
        default=None,
        ge=0.0,
        description="Maximum estimated request cost in USD.",
    )
    credential_selection_strategy: str = Field(
        default="round_robin",
        description="Pool selection strategy: round_robin, least_recently_used, preferred, lowest_latency, deterministic_default.",
    )


class RoutingPolicyRead(RoutingPolicyBase):
    """Output representation of a virtual API key's persisted routing policy."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    virtual_api_key_id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class RoutingPolicyUpdate(BaseModel):
    """Payload for updating a virtual API key's routing policy."""

    routing_mode: str | None = None
    routing_preset: str | None = None
    quality_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    speed_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    availability_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    cost_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    model_access_profile: str | None = None
    required_capabilities: list[str] | None = None
    allowed_providers: list[str] | None = None
    excluded_providers: list[str] | None = None
    allowed_models: list[str] | None = None
    excluded_models: list[str] | None = None
    preferred_provider: str | None = None
    preferred_credential_id: uuid.UUID | None = None
    minimum_context_window: int | None = Field(default=None, ge=1)
    maximum_cost_per_request: float | None = Field(default=None, ge=0.0)
    credential_selection_strategy: str | None = None


class CandidatePreviewItem(BaseModel):
    """Individual candidate ranking representation in a routing preview."""

    rank: int
    provider: str
    provider_model_id: str
    gateway_model_id: str
    canonical_name: str
    credential_id: uuid.UUID
    credential_display_name: str | None
    score: float
    score_breakdown: dict[str, Any]
    observed_latency_ms: float | None
    input_price_per_million: float | None
    output_price_per_million: float | None
    context_window: int | None
    supports_streaming: bool | None
    supports_tools: bool | None
    supports_vision: bool | None
    supports_reasoning: bool | None


class RoutingPreviewRequest(BaseModel):
    """Request payload for evaluating hypothetical routing policy settings."""

    policy_overrides: RoutingPolicyUpdate | None = None
    model: str = Field(default="auto", description="Requested model or routing alias.")
    stream: bool = Field(
        default=False, description="Whether the request will require streaming."
    )
    tools: list[dict[str, Any]] | None = Field(
        default=None, description="Optional tools parameter."
    )
    estimated_tokens: int = Field(
        default=500, description="Estimated input token volume."
    )


class RoutingPreviewResponse(BaseModel):
    """Response containing ranked candidates, selection explanation, and exclusion diagnostics."""

    virtual_api_key_id: uuid.UUID
    selected_candidate: CandidatePreviewItem | None
    ranked_candidates: list[CandidatePreviewItem]
    excluded_candidates: dict[str, list[str]]
    effective_weights: dict[str, float]
    data_confidence: str
    missing_measurements: list[str]
    selection_strategy: str
    disclaimer: str = (
        "Preview snapshot only; actual execution may vary based on concurrency, "
        "model availability, and real-time operational metrics."
    )


class RoutingPresetsResponse(BaseModel):
    """Catalog of supported routing presets and their canonical priority weights."""

    presets: dict[str, dict[str, Any]]


class RoutingCapabilitiesResponse(BaseModel):
    """Catalog of supported modality profiles, capability flags, and selection strategies."""

    modality_profiles: list[str]
    supported_capabilities: list[str]
    credential_selection_strategies: list[str]
