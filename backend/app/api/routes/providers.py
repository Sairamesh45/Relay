"""FastAPI routes for provider discovery, credential vault management, and model discovery."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.providers.exceptions import (
    InvalidCredentialsError,
    ProviderConfigurationError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.providers.manager import ProviderManager, get_provider_manager
from app.providers.schemas.model import UnifiedModel
from app.providers.schemas.provider import ProviderListResponse
from app.schemas.provider_credential import (
    CredentialCreateRequest,
    CredentialResponse,
    CredentialRotateRequest,
    CredentialRotateResponse,
    CredentialValidationResponse,
)
from app.services.credential_service import (
    CredentialNotFoundError,
    CredentialService,
    DuplicateCredentialError,
    get_credential_service,
)

router = APIRouter()


@router.get(
    "",
    response_model=ProviderListResponse,
    summary="List supported AI providers",
    description="Returns metadata for all AI providers currently integrated into the gateway.",
)
async def list_providers(
    provider_mgr: Annotated[ProviderManager, Depends(get_provider_manager)],
) -> ProviderListResponse:
    """Return catalog of supported AI providers."""
    providers = provider_mgr.list_supported_providers()
    return ProviderListResponse(providers=providers)


@router.post(
    "/{provider}/credentials",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect and encrypt provider credentials",
    description="Validates API credentials directly with the provider, encrypts with AES-256-GCM, and stores securely.",
)
async def connect_credential(
    provider: str,
    payload: CredentialCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[CredentialService, Depends(get_credential_service)],
) -> CredentialResponse:
    """Validate, encrypt, and store credentials for a specific provider."""
    try:
        credential = await service.create_credential(
            db=db,
            user=current_user,
            provider_id=provider,
            api_key=payload.api_key,
            display_name=payload.display_name,
        )
        return CredentialResponse(
            id=credential.id,
            provider=credential.provider,
            display_name=credential.display_name,
            status=credential.status,
            masked_key=credential.masked_key or "",
            key_version=credential.key_version,
            last_validated_at=credential.last_validated_at,
            created_at=credential.created_at,
            updated_at=credential.updated_at,
        )
    except ProviderConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Credential validation failed: {exc.message}",
        ) from exc
    except DuplicateCredentialError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except RateLimitError as exc:
        headers = {}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(int(exc.retry_after))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Provider rate limit exceeded during validation",
            headers=headers,
        ) from exc
    except ProviderTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc.message),
        ) from exc
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider service unavailable: {exc.message}",
        ) from exc
    except ProviderRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider request error: {exc.message}",
        ) from exc


@router.get(
    "/credentials",
    response_model=list[CredentialResponse],
    summary="List user credentials",
    description="List all active/stored provider credentials for the authenticated user with masked API keys.",
)
async def list_credentials(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[CredentialService, Depends(get_credential_service)],
) -> list[CredentialResponse]:
    """Retrieve all credentials belonging to the current user."""
    credentials = await service.list_credentials(db=db, user=current_user)
    return [
        CredentialResponse(
            id=cred.id,
            provider=cred.provider,
            display_name=cred.display_name,
            status=cred.status,
            masked_key=cred.masked_key or "",
            key_version=cred.key_version,
            last_validated_at=cred.last_validated_at,
            created_at=cred.created_at,
            updated_at=cred.updated_at,
        )
        for cred in credentials
    ]


@router.delete(
    "/credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke and delete credential",
    description="Revokes and deletes a specific provider credential after verifying ownership.",
)
async def delete_credential(
    credential_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[CredentialService, Depends(get_credential_service)],
) -> Response:
    """Delete a user credential."""
    try:
        await service.delete_credential(
            db=db, user=current_user, credential_id=credential_id
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found or access denied.",
        ) from exc


@router.post(
    "/credentials/{credential_id}/validate",
    response_model=CredentialValidationResponse,
    summary="Validate existing stored credential",
    description="Decrypts stored credential internally and tests against provider API, updating verification timestamp.",
)
async def revalidate_credential(
    credential_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[CredentialService, Depends(get_credential_service)],
) -> CredentialValidationResponse:
    """Re-validate an existing stored credential."""
    try:
        cred, is_valid = await service.validate_stored_credential(
            db=db, user=current_user, credential_id=credential_id
        )
        msg = (
            "Credential validated successfully"
            if is_valid
            else "Credential validation failed: provider rejected API key"
        )
        return CredentialValidationResponse(
            id=cred.id,
            provider=cred.provider,
            status=cred.status,
            is_valid=is_valid,
            last_validated_at=cred.last_validated_at or cred.updated_at,
            message=msg,
        )
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found or access denied.",
        ) from exc
    except ProviderTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc.message),
        ) from exc
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider unavailable: {exc.message}",
        ) from exc
    except ProviderRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider request error: {exc.message}",
        ) from exc


@router.get(
    "/credentials/{credential_id}/models",
    response_model=list[UnifiedModel],
    summary="Discover models for credential",
    description="Discovers available models for the specified credential, returning standardized metadata.",
)
async def discover_models(
    credential_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[CredentialService, Depends(get_credential_service)],
) -> list[UnifiedModel]:
    """Retrieve normalized models accessible with the specified credential."""
    try:
        return await service.list_models_for_credential(
            db=db, user=current_user, credential_id=credential_id
        )
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found or access denied.",
        ) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Credential is no longer valid: {exc.message}",
        ) from exc
    except RateLimitError as exc:
        headers = {}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(int(exc.retry_after))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Provider rate limit exceeded during model discovery",
            headers=headers,
        ) from exc
    except ProviderTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc.message),
        ) from exc
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider unavailable: {exc.message}",
        ) from exc
    except ProviderRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider request error: {exc.message}",
        ) from exc


@router.post(
    "/credentials/{credential_id}/rotate",
    response_model=CredentialRotateResponse,
    summary="Rotate credential encryption key",
    description="Re-encrypts the stored API key under the designated or active key version without loss of access.",
)
async def rotate_credential_key(
    credential_id: uuid.UUID,
    payload: CredentialRotateRequest | None = None,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    service: Annotated[CredentialService, Depends(get_credential_service)] = None,
) -> CredentialRotateResponse:
    """Rotate the encryption key of a stored credential."""
    try:
        target_version = payload.target_version if payload else None
        cred = await service.rotate_credential_key(
            db=db,
            user=current_user,
            credential_id=credential_id,
            target_version=target_version,
        )
        return CredentialRotateResponse(
            id=cred.id,
            provider=cred.provider,
            key_version=cred.key_version,
            updated_at=cred.updated_at,
            message="Credential encryption key rotated successfully",
        )
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential not found or access denied.",
        ) from exc
    except ProviderRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider request error: {exc.message}",
        ) from exc
