"""FastAPI routes for provider health matrix, credential health inspection, and credential revalidation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.provider_credential import ProviderCredential
from app.models.reliability import CredentialHealth
from app.models.user import User
from app.providers.exceptions import (
    ProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.services.credential_service import (
    CredentialNotFoundError,
    CredentialService,
    get_credential_service,
)
from app.services.reliability.health_service import (
    HealthService,
    get_health_service,
)

router = APIRouter()


class ProviderHealthStatus(BaseModel):
    """Health metrics and operational status for an AI provider."""

    provider: str
    status: str
    active_credentials: int
    healthy_credentials: int
    cooling_down_credentials: int
    degraded_credentials: int
    failed_credentials: int
    updated_at: str


class ProviderHealthMatrixResponse(BaseModel):
    """Aggregated health matrix response across all providers."""

    providers: dict[str, ProviderHealthStatus]


class CredentialHealthResponse(BaseModel):
    """Health details for an individual credential."""

    id: uuid.UUID
    credential_id: uuid.UUID
    provider: str
    health_status: str
    failure_count: int
    consecutive_failures: int
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    cooldown_until: datetime | None = None
    is_cooling_down: bool
    last_error_category: str | None = None
    error_details: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime


class CredentialHealthListResponse(BaseModel):
    """Paginated list of credential health records."""

    items: list[CredentialHealthResponse]
    total: int
    limit: int
    offset: int


class CredentialRevalidateResponse(BaseModel):
    """Result of credential validation probe."""

    credential_id: uuid.UUID
    provider: str
    is_valid: bool
    health_status: str
    message: str
    validated_at: datetime


@router.get(
    "/health/providers",
    response_model=ProviderHealthMatrixResponse,
    summary="Get aggregated provider health matrix",
    description="Returns high-level operational status, active credentials, and failure counts for Gemini, Groq, and OpenRouter.",
)
async def get_provider_health_matrix(
    db: Annotated[AsyncSession, Depends(get_db)],
    health_service: Annotated[HealthService, Depends(get_health_service)],
) -> ProviderHealthMatrixResponse:
    """Return health matrix across all supported providers."""
    matrix_raw = await health_service.get_provider_health_matrix(db)
    providers = {k: ProviderHealthStatus(**v) for k, v in matrix_raw.items()}
    return ProviderHealthMatrixResponse(providers=providers)


@router.get(
    "/providers/credentials/health",
    response_model=CredentialHealthListResponse,
    summary="List credential health states",
    description="Returns paginated health states for credentials belonging to the authenticated user.",
)
async def list_credential_health(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    health_service: Annotated[HealthService, Depends(get_health_service)],
    provider: str | None = Query(None, description="Filter by provider name"),
    status: str | None = Query(None, description="Filter by health status"),
    limit: int = Query(50, ge=1, le=100, description="Items per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> CredentialHealthListResponse:
    """List credential health records for the current user."""
    # Query credentials owned by current user
    cred_query = select(ProviderCredential.id, ProviderCredential.provider).where(
        ProviderCredential.user_id == current_user.id
    )
    if provider:
        cred_query = cred_query.where(
            ProviderCredential.provider == provider.lower().strip()
        )

    cred_res = await db.execute(cred_query)
    cred_rows = cred_res.all()
    user_cred_map = {row[0]: row[1] for row in cred_rows}

    if not user_cred_map:
        return CredentialHealthListResponse(
            items=[], total=0, limit=limit, offset=offset
        )

    cred_ids = list(user_cred_map.keys())

    # Build query on CredentialHealth
    health_query = select(CredentialHealth).where(
        CredentialHealth.credential_id.in_(cred_ids)
    )
    if status:
        health_query = health_query.where(
            CredentialHealth.health_status == status.lower().strip()
        )

    # Count total matching
    count_query = select(func.count()).select_from(health_query.subquery())
    total_res = await db.execute(count_query)
    total = total_res.scalar_one() or 0

    # Paginate
    paged_query = (
        health_query.order_by(CredentialHealth.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(paged_query)
    health_records = list(res.scalars().all())

    now = datetime.now(UTC)
    items: list[CredentialHealthResponse] = []
    for h in health_records:
        items.append(
            CredentialHealthResponse(
                id=h.id,
                credential_id=h.credential_id,
                provider=user_cred_map.get(h.credential_id, "unknown"),
                health_status=(
                    h.health_status.value
                    if hasattr(h.health_status, "value")
                    else str(h.health_status)
                ),
                failure_count=h.failure_count,
                consecutive_failures=h.consecutive_failures,
                last_success_at=h.last_success_at,
                last_failure_at=h.last_failure_at,
                cooldown_until=h.cooldown_until,
                is_cooling_down=bool(h.cooldown_until and now < h.cooldown_until),
                last_error_category=h.last_error_category,
                error_details=h.error_details,
                updated_at=h.updated_at,
            )
        )

    return CredentialHealthListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/providers/credentials/{credential_id}/health",
    response_model=CredentialHealthResponse,
    summary="Get single credential health details",
    description="Returns operational health state, failure counters, and cooldown expiry for a specific user credential.",
)
async def get_single_credential_health(
    credential_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    health_service: Annotated[HealthService, Depends(get_health_service)],
) -> CredentialHealthResponse:
    """Retrieve detailed health record for a user's credential."""
    # Enforce user ownership check
    cred_query = select(ProviderCredential).where(
        ProviderCredential.id == credential_id,
        ProviderCredential.user_id == current_user.id,
    )
    cred_res = await db.execute(cred_query)
    cred = cred_res.scalars().first()
    if not cred:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found or access denied.",
        )

    health = await health_service.get_or_create_health(db, credential_id)
    now = datetime.now(UTC)

    return CredentialHealthResponse(
        id=health.id,
        credential_id=health.credential_id,
        provider=cred.provider,
        health_status=(
            health.health_status.value
            if hasattr(health.health_status, "value")
            else str(health.health_status)
        ),
        failure_count=health.failure_count,
        consecutive_failures=health.consecutive_failures,
        last_success_at=health.last_success_at,
        last_failure_at=health.last_failure_at,
        cooldown_until=health.cooldown_until,
        is_cooling_down=bool(health.cooldown_until and now < health.cooldown_until),
        last_error_category=health.last_error_category,
        error_details=health.error_details,
        updated_at=health.updated_at,
    )


@router.post(
    "/providers/credentials/{credential_id}/revalidate",
    response_model=CredentialRevalidateResponse,
    summary="Force credential validation probe",
    description="Tests the credential against the upstream provider and updates health state, recovering from auth failures if valid.",
)
async def revalidate_credential(
    credential_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    credential_service: Annotated[CredentialService, Depends(get_credential_service)],
    health_service: Annotated[HealthService, Depends(get_health_service)],
) -> CredentialRevalidateResponse:
    """Execute live validation probe and update CredentialHealth state."""
    try:
        cred, is_valid = await credential_service.validate_stored_credential(
            db=db, user=current_user, credential_id=credential_id
        )
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found or access denied.",
        ) from exc
    except ProviderTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Provider timed out during revalidation: {exc.message}",
        ) from exc
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider unavailable during revalidation: {exc.message}",
        ) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider error during revalidation: {exc.message}",
        ) from exc

    # Update CredentialHealth state with revalidation result
    health = await health_service.revalidate_credential_health(
        db=db,
        credential_id=credential_id,
        is_valid=is_valid,
        error_message=None if is_valid else "Provider rejected credentials",
    )
    await db.commit()

    msg = (
        "Credential validated successfully and marked healthy"
        if is_valid
        else "Credential revalidation failed: provider rejected API key"
    )

    return CredentialRevalidateResponse(
        credential_id=cred.id,
        provider=cred.provider,
        is_valid=is_valid,
        health_status=(
            health.health_status.value
            if hasattr(health.health_status, "value")
            else str(health.health_status)
        ),
        message=msg,
        validated_at=datetime.now(UTC),
    )
