"""Pydantic schemas for model synchronization triggers, audit logs, and reports."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SyncTriggerRequest(BaseModel):
    """Request payload to trigger model discovery synchronization."""

    provider: str | None = Field(
        None, description="Optional provider identifier to sync only one provider"
    )
    credential_id: uuid.UUID | None = Field(
        None, description="Optional specific credential ID to sync"
    )


class CredentialSyncResult(BaseModel):
    """Result of synchronizing a single provider credential."""

    credential_id: uuid.UUID
    provider: str
    status: str
    models_discovered: int = 0
    models_added: int = 0
    models_updated: int = 0
    models_marked_unavailable: int = 0
    error_summary: str | None = None


class SyncReportResponse(BaseModel):
    """Comprehensive report returned upon initiating/completing synchronization."""

    sync_id: uuid.UUID
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    total_discovered: int = 0
    total_added: int = 0
    total_updated: int = 0
    total_marked_unavailable: int = 0
    credentials_synced: list[CredentialSyncResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ModelSyncLogRead(BaseModel):
    """Audit log item for a synchronization operation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    provider: str | None = None
    credential_id: uuid.UUID | None = None
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    models_discovered: int
    models_added: int
    models_updated: int
    models_marked_unavailable: int
    error_summary: str | None = None


class SyncStatusResponse(BaseModel):
    """Recent synchronization logs for the authenticated user."""

    logs: list[ModelSyncLogRead]
