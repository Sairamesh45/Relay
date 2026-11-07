"""Model registry query service providing user-scoped model discovery, filtering, and summaries."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.provider_credential import ProviderCredential
from app.models.provider_model import ProviderModel
from app.models.unified_model import UnifiedModel
from app.models.user import User
from app.schemas.model import (
    ProviderOfferingRead,
    ProviderSummaryItem,
    ProviderSummaryResponse,
    UnifiedModelListResponse,
    UnifiedModelRead,
)


class ModelRegistryService:
    """Service handling catalog queries and user-scoped model filtering."""

    async def get_user_credential_ids(
        self, db: AsyncSession, user: User, provider: str | None = None
    ) -> list[uuid.UUID]:
        """Fetch all credential IDs belonging to the authenticated user."""
        stmt = select(ProviderCredential.id).where(
            ProviderCredential.user_id == user.id
        )
        if provider:
            stmt = stmt.where(ProviderCredential.provider == provider.strip().lower())
        res = await db.execute(stmt)
        return list(res.scalars().all())

    async def list_models_for_user(
        self,
        db: AsyncSession,
        user: User,
        provider: str | None = None,
        modality: str | None = None,
        input_modality: str | None = None,
        output_modality: str | None = None,
        capability: str | None = None,
        availability_status: str | None = "available",
        limit: int = 50,
        offset: int = 0,
    ) -> UnifiedModelListResponse:
        """List canonical models available to the authenticated user with granular filters and pagination.

        Guarantees strict user isolation: only models associated with the user's
        credentials are returned, aggregating provider offerings under canonical identities.
        """
        user_cred_ids = await self.get_user_credential_ids(db, user, provider=provider)
        if not user_cred_ids:
            return UnifiedModelListResponse(
                total=0,
                limit=limit,
                offset=offset,
                items=[],
            )

        # Base query joining UnifiedModel and ProviderModel
        base_query = (
            select(UnifiedModel.id, UnifiedModel.canonical_id)
            .join(ProviderModel, ProviderModel.unified_model_id == UnifiedModel.id)
            .where(ProviderModel.credential_id.in_(user_cred_ids))
        )

        # Apply ProviderModel filters
        if provider:
            base_query = base_query.where(
                ProviderModel.provider == provider.strip().lower()
            )

        if availability_status and availability_status.lower() != "all":
            base_query = base_query.where(
                ProviderModel.availability_status == availability_status.lower()
            )

        # Capability filters on ProviderModel
        if capability:
            cap = capability.strip().lower()
            if cap in ["streaming", "supports_streaming"]:
                base_query = base_query.where(
                    ProviderModel.supports_streaming.is_(True)
                )
            elif cap in ["tools", "function_calling", "supports_tools"]:
                base_query = base_query.where(ProviderModel.supports_tools.is_(True))
            elif cap in ["vision", "supports_vision"]:
                base_query = base_query.where(ProviderModel.supports_vision.is_(True))
            elif cap in ["structured_output", "supports_structured_output"]:
                base_query = base_query.where(
                    ProviderModel.supports_structured_output.is_(True)
                )
            elif cap in ["reasoning", "supports_reasoning"]:
                base_query = base_query.where(
                    ProviderModel.supports_reasoning.is_(True)
                )

        # UnifiedModel filters
        if modality:
            base_query = base_query.where(
                UnifiedModel.modality == modality.strip().lower()
            )

        if input_modality:
            # JSONB contains check
            base_query = base_query.where(
                UnifiedModel.input_modalities.contains([input_modality.strip().lower()])
            )

        if output_modality:
            base_query = base_query.where(
                UnifiedModel.output_modalities.contains(
                    [output_modality.strip().lower()]
                )
            )

        # Count total distinct matching canonical models and retrieve paginated IDs
        subq = base_query.distinct().subquery()
        count_stmt = select(func.count()).select_from(subq)
        total_count = (await db.execute(count_stmt)).scalar() or 0

        distinct_ids_stmt = (
            select(subq.c.id).order_by(subq.c.canonical_id).limit(limit).offset(offset)
        )
        paged_ids = (await db.execute(distinct_ids_stmt)).scalars().all()

        if not paged_ids:
            return UnifiedModelListResponse(
                total=total_count,
                limit=limit,
                offset=offset,
                items=[],
            )

        # Fetch canonical models with eager loaded offerings
        fetch_stmt = (
            select(UnifiedModel)
            .where(UnifiedModel.id.in_(paged_ids))
            .options(selectinload(UnifiedModel.provider_models))
        )
        res = await db.execute(fetch_stmt)
        raw_unified_models = res.scalars().all()

        # Preserve the deterministic canonical_id pagination order
        um_map = {um.id: um for um in raw_unified_models}
        ordered_unified_models = [um_map[uid] for uid in paged_ids if uid in um_map]

        # Build response items filtering offerings strictly to user's credentials
        items: list[UnifiedModelRead] = []
        for um in ordered_unified_models:
            user_offerings: list[ProviderOfferingRead] = []
            for pm in um.provider_models:
                if pm.credential_id in user_cred_ids:
                    if (
                        availability_status
                        and availability_status.lower() != "all"
                        and pm.availability_status != availability_status.lower()
                    ):
                        continue
                    if provider and pm.provider != provider.strip().lower():
                        continue

                    user_offerings.append(ProviderOfferingRead.model_validate(pm))

            if user_offerings:
                items.append(
                    UnifiedModelRead(
                        id=um.id,
                        canonical_id=um.canonical_id,
                        display_name=um.display_name,
                        description=um.description,
                        provider_model_family=um.provider_model_family,
                        modality=um.modality,
                        input_modalities=um.input_modalities,
                        output_modalities=um.output_modalities,
                        created_at=um.created_at,
                        updated_at=um.updated_at,
                        provider_offerings=user_offerings,
                    )
                )

        return UnifiedModelListResponse(
            total=total_count,
            limit=limit,
            offset=offset,
            items=items,
        )

    async def get_model_details(
        self,
        db: AsyncSession,
        user: User,
        model_id: str,
    ) -> UnifiedModelRead | None:
        """Retrieve detailed model information scoped to user's provider offerings.

        Accepts either UUID or canonical_id string.
        """
        user_cred_ids = await self.get_user_credential_ids(db, user)
        if not user_cred_ids:
            return None

        # Build query for canonical model
        stmt = select(UnifiedModel).options(selectinload(UnifiedModel.provider_models))

        # Check if model_id is a UUID or canonical_id string
        is_uuid = False
        try:
            parsed_uuid = uuid.UUID(model_id)
            is_uuid = True
        except ValueError:
            is_uuid = False

        if is_uuid:
            stmt = stmt.where(UnifiedModel.id == parsed_uuid)
        else:
            stmt = stmt.where(UnifiedModel.canonical_id == model_id.strip().lower())

        res = await db.execute(stmt)
        um = res.scalar_one_or_none()

        if um is None:
            return None

        # Filter offerings to user credentials only
        user_offerings: list[ProviderOfferingRead] = [
            ProviderOfferingRead.model_validate(pm)
            for pm in um.provider_models
            if pm.credential_id in user_cred_ids
        ]

        if not user_offerings:
            # User has no credentials that offer this model
            return None

        return UnifiedModelRead(
            id=um.id,
            canonical_id=um.canonical_id,
            display_name=um.display_name,
            description=um.description,
            provider_model_family=um.provider_model_family,
            modality=um.modality,
            input_modalities=um.input_modalities,
            output_modalities=um.output_modalities,
            created_at=um.created_at,
            updated_at=um.updated_at,
            provider_offerings=user_offerings,
        )

    async def get_provider_summary(
        self,
        db: AsyncSession,
        user: User,
    ) -> ProviderSummaryResponse:
        """Provide aggregated metrics of connected providers and model offerings for user."""
        # Find all user credentials
        creds_stmt = select(ProviderCredential).where(
            ProviderCredential.user_id == user.id
        )
        creds_res = await db.execute(creds_stmt)
        user_creds = creds_res.scalars().all()

        if not user_creds:
            return ProviderSummaryResponse(providers=[])

        cred_map: dict[str, list[uuid.UUID]] = {}
        for c in user_creds:
            cred_map.setdefault(c.provider, []).append(c.id)

        all_user_cred_ids = [c.id for c in user_creds]

        # Query provider offerings across these credentials
        stmt = (
            select(
                ProviderModel.provider,
                ProviderModel.availability_status,
                UnifiedModel.modality,
            )
            .join(UnifiedModel, UnifiedModel.id == ProviderModel.unified_model_id)
            .where(ProviderModel.credential_id.in_(all_user_cred_ids))
        )
        res = await db.execute(stmt)
        rows = res.all()

        summary_dict: dict[str, dict[str, Any]] = {}
        for provider, cred_ids in cred_map.items():
            summary_dict[provider] = {
                "total_models": 0,
                "available_models": 0,
                "credentials_count": len(cred_ids),
                "modalities": set(),
            }

        for row in rows:
            p = row[0]
            status = row[1]
            modality = row[2]

            if p in summary_dict:
                summary_dict[p]["total_models"] += 1
                if status == "available":
                    summary_dict[p]["available_models"] += 1
                if modality:
                    summary_dict[p]["modalities"].add(modality)

        items = [
            ProviderSummaryItem(
                provider=p,
                total_models=data["total_models"],
                available_models=data["available_models"],
                credentials_count=data["credentials_count"],
                modalities=sorted(data["modalities"]),
            )
            for p, data in summary_dict.items()
        ]

        return ProviderSummaryResponse(providers=items)


# Singleton query service
model_registry_service = ModelRegistryService()


def get_model_registry_service() -> ModelRegistryService:
    """Dependency provider for ModelRegistryService."""
    return model_registry_service
