"""Gateway usage and request log analytics endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.gateway_usage import (
    GatewayRequestLogsListResponse,
    GatewayUsageSummaryResponse,
)
from app.services.gateway_usage import (
    GatewayUsageService,
    get_gateway_usage_service,
)

router = APIRouter()


@router.get(
    "/summary",
    response_model=GatewayUsageSummaryResponse,
    summary="Get aggregated gateway usage metrics",
)
async def get_usage_summary(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    usage_service: Annotated[GatewayUsageService, Depends(get_gateway_usage_service)],
    provider: str | None = Query(None, description="Optional provider filter"),
) -> GatewayUsageSummaryResponse:
    """Retrieve aggregated usage statistics strictly for the authenticated user."""
    return await usage_service.get_usage_summary(db=db, user=user, provider=provider)


@router.get(
    "/requests",
    response_model=GatewayRequestLogsListResponse,
    summary="Get paginated gateway request audit logs",
)
async def get_request_logs(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    usage_service: Annotated[GatewayUsageService, Depends(get_gateway_usage_service)],
    limit: int = Query(50, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    provider: str | None = Query(None, description="Filter by provider"),
    status: str | None = Query(
        None, description="Filter by status ('success', 'error')"
    ),
) -> GatewayRequestLogsListResponse:
    """Retrieve paginated audit logs for gateway requests executed by the authenticated user."""
    return await usage_service.get_request_logs(
        db=db,
        user=user,
        limit=limit,
        offset=offset,
        provider=provider,
        status=status,
    )
