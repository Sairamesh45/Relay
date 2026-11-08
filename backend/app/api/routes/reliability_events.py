"""FastAPI routes for reliability audit events and system health KPIs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.reliability import ReliabilityEvent
from app.models.user import User
from app.services.reliability.event_recorder import (
    EventRecorder,
    get_event_recorder,
)

router = APIRouter()


class ReliabilityEventItemResponse(BaseModel):
    """Normalized representation of a single reliability audit event."""

    id: uuid.UUID
    timestamp: datetime
    event_type: str
    provider: str
    credential_id: uuid.UUID | None = None
    model_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @classmethod
    def from_model(cls, model: ReliabilityEvent) -> ReliabilityEventItemResponse:
        """Construct response item from SQLAlchemy model."""
        return cls(
            id=model.id,
            timestamp=model.timestamp,
            event_type=model.event_type,
            provider=model.provider,
            credential_id=model.credential_id,
            model_id=model.model_id,
            metadata=model.event_metadata or {},
            created_at=model.created_at,
        )


class ReliabilityEventListResponse(BaseModel):
    """Paginated collection of reliability audit events."""

    items: list[ReliabilityEventItemResponse]
    total: int
    limit: int
    offset: int


class ReliabilitySummaryResponse(BaseModel):
    """Aggregated reliability KPIs and health indicators."""

    total_requests: int = 0
    failover_success_count: int = 0
    failover_started_count: int = 0
    failover_events_count: int = 0
    failover_success_rate: float = 100.0
    circuit_trip_count: int = 0
    active_cooldowns_count: int = 0
    open_circuits_count: int = 0
    provider_stats: dict[str, int] = Field(default_factory=dict)


@router.get(
    "/events",
    response_model=ReliabilityEventListResponse,
    summary="List reliability events",
    description="Returns paginated, filterable audit events including rate limits, cooldowns, failovers, and circuit trips.",
)
async def list_reliability_events(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    event_recorder: Annotated[EventRecorder, Depends(get_event_recorder)],
    event_type: str | None = Query(default=None, description="Filter by event type"),
    provider: str | None = Query(default=None, description="Filter by provider name"),
    credential_id: uuid.UUID | None = Query(
        default=None, description="Filter by credential UUID"
    ),
    model_id: str | None = Query(default=None, description="Filter by model ID"),
    limit: int = Query(default=50, ge=1, le=100, description="Items per page"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
) -> ReliabilityEventListResponse:
    """Fetch paginated reliability events scoped to the current user."""
    events, total = await event_recorder.get_events(
        db=db,
        user_id=current_user.id,
        event_type=event_type,
        provider=provider,
        credential_id=credential_id,
        model_id=model_id,
        limit=limit,
        offset=offset,
    )

    items = [ReliabilityEventItemResponse.from_model(ev) for ev in events]
    return ReliabilityEventListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/summary",
    response_model=ReliabilitySummaryResponse,
    summary="Get reliability summary metrics",
    description="Returns aggregate reliability indicators: failover counts, circuit trip counts, cooldown counts, and success rates.",
)
async def get_reliability_summary(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    event_recorder: Annotated[EventRecorder, Depends(get_event_recorder)],
) -> ReliabilitySummaryResponse:
    """Compute aggregate reliability summary metrics for the current user."""
    summary_data = await event_recorder.get_summary(db=db, user_id=current_user.id)
    return ReliabilitySummaryResponse(**summary_data)
