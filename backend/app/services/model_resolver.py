"""Model resolution service mapping gateway model identifiers to user credentials and provider offerings."""

from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_api_key
from app.core.gateway_errors import (
    openai_invalid_request_error,
    openai_model_not_found_error,
)
from app.models.provider_credential import ProviderCredential
from app.models.provider_model import ProviderModel
from app.models.user import User
from app.schemas.chat import OpenAIModelListItem


class ResolvedOffering(NamedTuple):
    """Container holding resolved provider adapter attributes and decrypted credential."""

    provider: str
    provider_model_id: str
    gateway_model_id: str
    raw_api_key: str
    credential_id: str
    provider_model: ProviderModel


class ModelResolverService:
    """Service resolving gateway model identifiers ('provider:provider_model_id') to authenticated user offerings."""

    async def resolve_model(
        self,
        db: AsyncSession,
        user: User,
        gateway_model_id: str,
    ) -> ResolvedOffering:
        """Resolve a requested gateway model identifier to a verified user credential and provider offering.

        Format: '{provider}:{provider_model_id}' (e.g. 'gemini:gemini-2.5-flash').
        Enforces strict credential ownership and model availability.
        Decrypts the provider credential safely in memory.
        """
        clean_model = gateway_model_id.strip()
        if ":" not in clean_model:
            raise openai_invalid_request_error(
                f"Invalid model format '{gateway_model_id}'. Expected format is 'provider:model_id' (e.g. 'gemini:gemini-2.5-flash' or 'groq:llama-3.3-70b-versatile').",
                param="model",
            )

        provider, provider_model_id = clean_model.split(":", 1)
        provider = provider.strip().lower()
        provider_model_id = provider_model_id.strip()

        if not provider or not provider_model_id:
            raise openai_invalid_request_error(
                f"Malformed model identifier '{gateway_model_id}'. Provider and model ID cannot be empty.",
                param="model",
            )

        # Query user's active credentials for this provider
        cred_stmt = select(ProviderCredential).where(
            ProviderCredential.user_id == user.id,
            ProviderCredential.provider == provider,
            ProviderCredential.status == "active",
        )
        cred_res = await db.execute(cred_stmt)
        user_creds = list(cred_res.scalars().all())

        if not user_creds:
            raise openai_model_not_found_error(gateway_model_id)

        user_cred_ids = [c.id for c in user_creds]
        cred_map = {c.id: c for c in user_creds}

        # Query offering matching provider_model_id or stripped/prefixed variations (e.g. models/gemini-2.5-flash)
        model_variants = [provider_model_id]
        if provider == "gemini":
            if provider_model_id.startswith("models/"):
                model_variants.append(provider_model_id.removeprefix("models/"))
            else:
                model_variants.append(f"models/{provider_model_id}")

        stmt = (
            select(ProviderModel)
            .where(
                ProviderModel.provider == provider,
                ProviderModel.provider_model_id.in_(model_variants),
                ProviderModel.credential_id.in_(user_cred_ids),
            )
            .order_by(ProviderModel.credential_id)
        )
        res = await db.execute(stmt)
        offering = res.scalars().first()

        if offering is None:
            raise openai_model_not_found_error(gateway_model_id)

        if offering.availability_status != "available":
            raise openai_invalid_request_error(
                f"Model '{gateway_model_id}' is currently marked unavailable by provider '{provider}'.",
                code="model_unavailable",
                param="model",
            )

        matched_cred = cred_map.get(offering.credential_id)
        if matched_cred is None:
            raise openai_model_not_found_error(gateway_model_id)

        # Decrypt provider key in-memory
        raw_key = decrypt_api_key(
            matched_cred.encrypted_api_key, matched_cred.key_version
        )

        return ResolvedOffering(
            provider=provider,
            provider_model_id=offering.provider_model_id,
            gateway_model_id=gateway_model_id,
            raw_api_key=raw_key,
            credential_id=str(matched_cred.id),
            provider_model=offering,
        )

    async def list_user_models(
        self,
        db: AsyncSession,
        user: User,
    ) -> list[OpenAIModelListItem]:
        """Fetch all gateway model offerings accessible through the user's active credentials."""
        # Find active user credentials
        creds_stmt = select(ProviderCredential.id).where(
            ProviderCredential.user_id == user.id,
            ProviderCredential.status == "active",
        )
        creds_res = await db.execute(creds_stmt)
        cred_ids = list(creds_res.scalars().all())

        if not cred_ids:
            return []

        stmt = (
            select(ProviderModel)
            .where(
                ProviderModel.credential_id.in_(cred_ids),
                ProviderModel.availability_status == "available",
            )
            .order_by(ProviderModel.provider, ProviderModel.provider_model_id)
        )
        res = await db.execute(stmt)
        offerings = res.scalars().all()

        seen_models: set[str] = set()
        items: list[OpenAIModelListItem] = []

        for pm in offerings:
            gateway_id = f"{pm.provider}:{pm.provider_model_id}"
            if gateway_id not in seen_models:
                seen_models.add(gateway_id)
                items.append(
                    OpenAIModelListItem(
                        id=gateway_id,
                        object="model",
                        created=int(pm.created_at.timestamp()) if pm.created_at else 0,
                        owned_by=pm.provider,
                    )
                )

        return items


# Singleton instance
model_resolver_service = ModelResolverService()


def get_model_resolver_service() -> ModelResolverService:
    """FastAPI dependency provider for ModelResolverService."""
    return model_resolver_service
