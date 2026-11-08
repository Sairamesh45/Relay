"""FastAPI routes for quota observations, rate-limit tracking, and capacity limits."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.reliability.quota_service import (
    QuotaService,
    get_quota_service,
)

router = APIRouter()


class QuotaItemResponse(BaseModel):
    """Normalized quota observation record."""

    id: uuid.UUID
    credential_id: uuid.UUID | None = None
    provider: str
    quota_scope: str
    model_id: str | None = None
    resource_type: str
    limit: int | None = None
    remaining: int | None = None
    reset_at: datetime | None = None
    retry_after: int | None = None
    confidence: str
    source: str
    observed_at: datetime


class QuotaListResponse(BaseModel):
    """Paginated quota observations response."""

    items: list[QuotaItemResponse]
    total: int
    limit: int
    offset: int


@router.get(
    "",
    response_model=QuotaListResponse,
    summary="List quota observations and capacity limits",
    description="Returns paginated quota observations for the authenticated user with filtering by provider, credential, scope, and resource type.",
)
async def list_quotas(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    quota_service: Annotated[QuotaService, Depends(get_quota_service)],
    provider: str | None = Query(None, description="Filter by provider name"),
    credential_id: uuid.UUID | None = Query(
        None, description="Filter by credential ID"
    ),
    quota_scope: str | None = Query(
        None, description="Filter by quota scope (credential, model, organization)"
    ),
    resource_type: str | None = Query(
        None, description="Filter by resource type (requests, tokens, credits)"
    ),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> QuotaListResponse:
    """Retrieve paginated quota states for the user's provider accounts."""
    records, total = await quota_service.get_quota_states(
        db=db,
        user_id=current_user.id,
        provider=provider,
        credential_id=credential_id,
        quota_scope=quota_scope,
        resource_type=resource_type,
        limit=limit,
        offset=offset,
    )

    items = [
        QuotaItemResponse(
            id=r.id,
            credential_id=r.credential_id,
            provider=r.provider,
            quota_scope=r.quota_scope,
            model_id=r.model_id,
            resource_type=r.resource_type,
            limit=r.limit,
            remaining=r.remaining,
            reset_at=r.reset_at,
            retry_after=r.retry_after,
            confidence=r.confidence,
            source=r.source,
            observed_at=r.observed_at,
        )
        for r in records
    ]

    return QuotaListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )
