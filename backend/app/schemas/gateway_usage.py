"""Pydantic schemas for Gateway Request Logs and Usage Tracking."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GatewayRequestLogRead(BaseModel):
    """Schema for individual gateway request audit log records."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    virtual_api_key_id: uuid.UUID | None = None
    provider: str
    provider_model_id: str
    gateway_model_id: str
    request_id: str
    status: str
    status_code: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int
    streaming: bool
    error_code: str | None = None
    error_summary: str | None = None
    created_at: datetime


class GatewayRequestLogsListResponse(BaseModel):
    """Paginated list of request audit logs."""

    total: int
    limit: int
    offset: int
    logs: list[GatewayRequestLogRead]


class ProviderUsageMetrics(BaseModel):
    """Aggregated usage metrics for a specific provider."""

    total_requests: int
    total_tokens: int
    input_tokens: int
    output_tokens: int


class GatewayUsageSummaryResponse(BaseModel):
    """Aggregated usage metrics across providers and models for user."""

    total_requests: int
    successful_requests: int
    failed_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    average_latency_ms: float
    by_provider: dict[str, ProviderUsageMetrics]
    by_model: dict[str, int]
