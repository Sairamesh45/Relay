"""Credential vault service managing encryption, storage, validation, and discovery."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import (
    decrypt_api_key,
    encrypt_api_key,
    extract_key_version,
    generate_credential_fingerprint,
    mask_api_key,
)
from app.models.provider_credential import ProviderCredential
from app.models.user import User
from app.providers.exceptions import (
    InvalidCredentialsError,
    ProviderConfigurationError,
)
from app.providers.manager import ProviderManager, get_provider_manager
from app.providers.schemas.model import UnifiedModel


class CredentialServiceError(Exception):
    """Base exception for credential service errors."""

    pass


class CredentialNotFoundError(CredentialServiceError):
    """Raised when a requested credential does not exist or does not belong to the user."""

    pass


class DuplicateCredentialError(CredentialServiceError):
    """Raised when registering an identical key for the same user and provider."""

    pass


class CredentialService:
    """Service encapsulating secure provider credential operations."""

    def __init__(self, provider_mgr: ProviderManager | None = None) -> None:
        self.provider_manager = provider_mgr or get_provider_manager()

    async def create_credential(
        self,
        db: AsyncSession,
        user: User,
        provider_id: str,
        api_key: str,
        display_name: str | None = None,
    ) -> ProviderCredential:
        """Validate, encrypt, and store a new provider credential for a user.

        Workflow:
        1. Resolve provider adapter.
        2. Validate API key directly against provider API.
        3. Compute keyed HMAC fingerprint to detect duplicates.
        4. Encrypt API key with fresh AES-256-GCM nonce.
        5. Persist credential record and return masked representation.
        """
        clean_provider_id = provider_id.strip().lower()
        if not self.provider_manager.is_supported(clean_provider_id):
            raise ProviderConfigurationError(
                f"Provider '{provider_id}' is not supported.",
                provider=clean_provider_id,
            )

        provider = self.provider_manager.get_provider(clean_provider_id)

        # 1. Validate directly with provider
        clean_key = api_key.strip()
        await provider.validate_credentials(clean_key)

        # 2. Check for duplicate credentials using HMAC fingerprint
        fingerprint = generate_credential_fingerprint(clean_key)
        existing_stmt = select(ProviderCredential).where(
            ProviderCredential.user_id == user.id,
            ProviderCredential.provider == clean_provider_id,
            ProviderCredential.credential_fingerprint == fingerprint,
        )
        existing_res = await db.execute(existing_stmt)
        existing_cred = existing_res.scalar_one_or_none()

        now = datetime.now(UTC)

        if existing_cred is not None:
            if existing_cred.status == "active":
                raise DuplicateCredentialError(
                    f"A credential for provider '{clean_provider_id}' with the same key is already active."
                )
            # Reactivate if previously marked invalid or revoked
            existing_cred.status = "active"
            existing_cred.last_validated_at = now
            if display_name:
                existing_cred.display_name = display_name
            await db.commit()
            await db.refresh(existing_cred)
            return existing_cred

        # 3. Encrypt API key using AES-256-GCM
        encrypted_key = encrypt_api_key(clean_key)
        key_ver = extract_key_version(encrypted_key)
        masked = mask_api_key(clean_key)

        # 4. Create database record
        new_cred = ProviderCredential(
            user_id=user.id,
            provider=clean_provider_id,
            encrypted_api_key=encrypted_key,
            key_version=key_ver,
            credential_fingerprint=fingerprint,
            masked_key=masked,
            display_name=display_name,
            status="active",
            last_validated_at=now,
        )
        db.add(new_cred)
        await db.commit()
        await db.refresh(new_cred)
        return new_cred

    async def list_credentials(
        self,
        db: AsyncSession,
        user: User,
    ) -> list[ProviderCredential]:
        """List all credentials belonging to the user without exposing secrets."""
        stmt = (
            select(ProviderCredential)
            .where(ProviderCredential.user_id == user.id)
            .order_by(ProviderCredential.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_credential(
        self,
        db: AsyncSession,
        user: User,
        credential_id: uuid.UUID,
    ) -> ProviderCredential:
        """Retrieve a specific credential while verifying user ownership."""
        stmt = select(ProviderCredential).where(
            ProviderCredential.id == credential_id,
            ProviderCredential.user_id == user.id,
        )
        result = await db.execute(stmt)
        cred = result.scalar_one_or_none()
        if cred is None:
            raise CredentialNotFoundError(
                f"Credential {credential_id} not found or access denied."
            )
        return cred

    async def delete_credential(
        self,
        db: AsyncSession,
        user: User,
        credential_id: uuid.UUID,
    ) -> None:
        """Revoke and delete a user's credential verifying ownership."""
        cred = await self.get_credential(db, user, credential_id)
        await db.delete(cred)
        await db.commit()

    async def validate_stored_credential(
        self,
        db: AsyncSession,
        user: User,
        credential_id: uuid.UUID,
    ) -> tuple[ProviderCredential, bool]:
        """Decrypt a stored credential internally and re-validate against the provider API."""
        cred = await self.get_credential(db, user, credential_id)
        raw_key = decrypt_api_key(cred.encrypted_api_key, cred.key_version)
        provider = self.provider_manager.get_provider(cred.provider)

        now = datetime.now(UTC)
        try:
            is_valid = await provider.validate_credentials(raw_key)
            cred.status = "active" if is_valid else "invalid"
            cred.last_validated_at = now
            await db.commit()
            await db.refresh(cred)
            return cred, is_valid
        except InvalidCredentialsError:
            cred.status = "invalid"
            cred.last_validated_at = now
            await db.commit()
            await db.refresh(cred)
            return cred, False

    async def list_models_for_credential(
        self,
        db: AsyncSession,
        user: User,
        credential_id: uuid.UUID,
    ) -> list[UnifiedModel]:
        """Decrypt stored credential internally and discover available models."""
        cred = await self.get_credential(db, user, credential_id)
        raw_key = decrypt_api_key(cred.encrypted_api_key, cred.key_version)
        provider = self.provider_manager.get_provider(cred.provider)
        return await provider.list_models(raw_key)

    async def rotate_credential_key(
        self,
        db: AsyncSession,
        user: User,
        credential_id: uuid.UUID,
        target_version: int | None = None,
    ) -> ProviderCredential:
        """Re-encrypt a stored credential under a new or active key version without losing access."""
        cred = await self.get_credential(db, user, credential_id)
        raw_key = decrypt_api_key(cred.encrypted_api_key, cred.key_version)

        new_encrypted = encrypt_api_key(raw_key, key_version=target_version)
        new_version = extract_key_version(new_encrypted)

        cred.encrypted_api_key = new_encrypted
        cred.key_version = new_version
        cred.updated_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(cred)
        return cred

    async def rotate_all_credentials_for_user(
        self,
        db: AsyncSession,
        user: User,
        target_version: int | None = None,
    ) -> int:
        """Batch rotate all credentials belonging to the user that are not yet on target_version."""
        creds = await self.list_credentials(db, user)
        rotated_count = 0
        for cred in creds:
            raw_key = decrypt_api_key(cred.encrypted_api_key, cred.key_version)
            new_encrypted = encrypt_api_key(raw_key, key_version=target_version)
            new_version = extract_key_version(new_encrypted)
            if cred.key_version != new_version or not cred.encrypted_api_key.startswith(
                f"v{new_version}:"
            ):
                cred.encrypted_api_key = new_encrypted
                cred.key_version = new_version
                cred.updated_at = datetime.now(UTC)
                rotated_count += 1
        if rotated_count > 0:
            await db.commit()
        return rotated_count


# Reusable service instance
credential_service = CredentialService()


def get_credential_service() -> CredentialService:
    """FastAPI dependency for accessing the credential service."""
    return credential_service
