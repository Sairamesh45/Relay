"""Unified Model Registry API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.model import (
    ProviderSummaryResponse,
    UnifiedModelListResponse,
    UnifiedModelRead,
)
from app.schemas.model_sync import (
    ModelSyncLogRead,
    SyncReportResponse,
    SyncStatusResponse,
    SyncTriggerRequest,
)
from app.services.credential_service import (
    CredentialNotFoundError,
    CredentialService,
    get_credential_service,
)
from app.services.model_registry import (
    ModelRegistryService,
    get_model_registry_service,
)
from app.services.model_sync import (
    ModelSyncService,
    get_model_sync_service,
)

router = APIRouter()


@router.get(
    "",
    response_model=UnifiedModelListResponse,
    summary="List available models for authenticated user",
)
async def list_models(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    registry_service: Annotated[
        ModelRegistryService, Depends(get_model_registry_service)
    ],
    provider: str | None = Query(
        None, description="Filter by provider (e.g. 'gemini', 'groq', 'openrouter')"
    ),
    modality: str | None = Query(
        None,
        description="Filter by modality (e.g. 'text->text', 'multimodal', 'audio')",
    ),
    input_modality: str | None = Query(
        None, description="Filter by input modality (e.g. 'text', 'image', 'audio')"
    ),
    output_modality: str | None = Query(
        None, description="Filter by output modality (e.g. 'text', 'image', 'audio')"
    ),
    capability: str | None = Query(
        None,
        description="Filter by capability ('vision', 'tools', 'streaming', 'structured_output', 'reasoning')",
    ),
    availability_status: str | None = Query(
        "available",
        description="Filter by status ('available', 'unavailable', or 'all')",
    ),
    limit: int = Query(500, ge=1, le=1000, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
) -> UnifiedModelListResponse:
    """Return models available through the authenticated user's connected credentials.

    Aggregates provider-specific offerings under canonical model identities while ensuring
    strict user credential isolation.
    """
    return await registry_service.list_models_for_user(
        db=db,
        user=user,
        provider=provider,
        modality=modality,
        input_modality=input_modality,
        output_modality=output_modality,
        capability=capability,
        availability_status=availability_status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/providers",
    response_model=ProviderSummaryResponse,
    summary="Get summary of models across connected providers",
)
async def get_providers_summary(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    registry_service: Annotated[
        ModelRegistryService, Depends(get_model_registry_service)
    ],
) -> ProviderSummaryResponse:
    """Return aggregated metrics of connected providers and model offerings for the user."""
    return await registry_service.get_provider_summary(db=db, user=user)


@router.post(
    "/sync",
    response_model=SyncReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger model discovery synchronization",
)
async def trigger_model_sync(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    sync_service: Annotated[ModelSyncService, Depends(get_model_sync_service)],
    credential_svc: Annotated[CredentialService, Depends(get_credential_service)],
    payload: SyncTriggerRequest | None = None,
) -> SyncReportResponse:
    """Trigger model discovery synchronization for the authenticated user's credentials.

    Supports synchronizing all connected credentials, a single provider, or a specific credential.
    Validates ownership of any requested credential.
    """
    provider = payload.provider if payload else None
    credential_id = payload.credential_id if payload else None

    # Validate credential ownership if explicit credential_id was provided
    if credential_id:
        try:
            await credential_svc.get_credential(db, user, credential_id)
        except CredentialNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Credential {credential_id} not found or not owned by user.",
            ) from exc

    return await sync_service.sync_for_user(
        db=db,
        user=user,
        provider=provider,
        credential_id=credential_id,
    )


@router.get(
    "/sync/status",
    response_model=SyncStatusResponse,
    summary="Get latest synchronization status and history",
)
async def get_sync_status(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    sync_service: Annotated[ModelSyncService, Depends(get_model_sync_service)],
    limit: int = Query(20, ge=1, le=100, description="Number of logs to retrieve"),
) -> SyncStatusResponse:
    """Retrieve recent synchronization audit logs for the authenticated user."""
    logs = await sync_service.get_latest_sync_status(db=db, user=user, limit=limit)
    return SyncStatusResponse(
        logs=[ModelSyncLogRead.model_validate(log) for log in logs]
    )


@router.get(
    "/{model_id:path}",
    response_model=UnifiedModelRead,
    summary="Get detailed canonical model information",
)
async def get_model_details(
    model_id: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    registry_service: Annotated[
        ModelRegistryService, Depends(get_model_registry_service)
    ],
) -> UnifiedModelRead:
    """Retrieve detailed information about a canonical model, including user's provider offerings.

    Accepts either UUID or canonical model identifier (e.g. 'google/gemini-2.5-flash').
    """
    model = await registry_service.get_model_details(
        db=db, user=user, model_id=model_id
    )
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model_id}' not found or not available through your connected credentials.",
        )
    return model
