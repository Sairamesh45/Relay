"""Asynchronous Registry Synchronization Service.

Discovers models from connected provider credentials, normalizes their metadata,
upserts canonical and provider offerings into PostgreSQL, and audits synchronization runs.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_api_key
from app.models.model_sync_log import ModelSyncLog
from app.models.provider_credential import ProviderCredential
from app.models.provider_model import ProviderModel
from app.models.unified_model import UnifiedModel
from app.models.user import User
from app.providers.exceptions import (
    InvalidCredentialsError,
    ProviderError,
    RateLimitError,
)
from app.providers.manager import ProviderManager, get_provider_manager
from app.schemas.model_sync import CredentialSyncResult, SyncReportResponse
from app.services.model_normalizer import ModelNormalizer, get_model_normalizer

logger = logging.getLogger(__name__)


class ModelSyncService:
    """Service orchestrating model discovery and database synchronization."""

    def __init__(
        self,
        provider_manager: ProviderManager | None = None,
        normalizer: ModelNormalizer | None = None,
    ) -> None:
        self.provider_manager = provider_manager or get_provider_manager()
        self.normalizer = normalizer or get_model_normalizer()

    async def sync_credential(
        self,
        db: AsyncSession,
        user: User | uuid.UUID,
        credential: ProviderCredential,
    ) -> CredentialSyncResult:
        """Synchronize models for a single validated provider credential.

        Idempotent: updates existing offerings, adds newly discovered offerings,
        and marks missing offerings as 'unavailable' without deleting history.
        """
        started_at = datetime.now(UTC)
        user_id = user if isinstance(user, uuid.UUID) else user.id
        provider_name = credential.provider
        credential_id = credential.id

        sync_log = ModelSyncLog(
            user_id=user_id,
            provider=provider_name,
            credential_id=credential_id,
            status="in_progress",
            started_at=started_at,
        )
        db.add(sync_log)
        await db.flush()

        result = CredentialSyncResult(
            credential_id=credential_id,
            provider=provider_name,
            status="completed",
        )

        try:
            # 1. Decrypt credential key safely
            raw_key = decrypt_api_key(
                credential.encrypted_api_key, credential.key_version
            )
            provider_adapter = self.provider_manager.get_provider(provider_name)

            # 2. Query provider models
            discovered_models = await provider_adapter.list_models(raw_key)
            result.models_discovered = len(discovered_models)
            sync_log.models_discovered = len(discovered_models)

            now = datetime.now(UTC)
            returned_provider_model_ids: set[str] = set()

            # Pre-normalize discovered models
            normalized_list = [
                self.normalizer.normalize(raw_m, availability_status="available")
                for raw_m in discovered_models
            ]
            canonical_ids = {norm.canonical_id for norm in normalized_list}

            # Batch pre-fetch existing UnifiedModels in a single query
            canonical_um_map: dict[str, UnifiedModel] = {}
            if canonical_ids:
                stmt_um = select(UnifiedModel).where(
                    UnifiedModel.canonical_id.in_(canonical_ids)
                )
                um_res = await db.execute(stmt_um)
                canonical_um_map = {
                    um.canonical_id: um for um in um_res.scalars().all()
                }

            # Batch pre-fetch all existing ProviderModels for this credential
            stmt_pm = select(ProviderModel).where(
                ProviderModel.credential_id == credential_id,
                ProviderModel.provider == provider_name,
            )
            pm_res = await db.execute(stmt_pm)
            prov_model_map: dict[str, ProviderModel] = {
                pm.provider_model_id: pm for pm in pm_res.scalars().all()
            }

            # 3. Process each discovered model in memory with single flush
            for norm in normalized_list:
                returned_provider_model_ids.add(norm.provider_model_id)

                # Resolve or create canonical UnifiedModel
                canonical_um = canonical_um_map.get(norm.canonical_id)
                if canonical_um is None:
                    try:
                        async with db.begin_nested():
                            canonical_um = UnifiedModel(
                                canonical_id=norm.canonical_id,
                                display_name=norm.display_name,
                                description=norm.description,
                                provider_model_family=norm.provider_model_family,
                                modality=norm.modality,
                                input_modalities=norm.input_modalities,
                                output_modalities=norm.output_modalities,
                                model_metadata=norm.raw_metadata,
                                created_at=now,
                                updated_at=now,
                            )
                            db.add(canonical_um)
                            await db.flush()
                    except Exception:
                        # Concurrently inserted by another worker; fetch existing
                        stmt_existing = select(UnifiedModel).where(
                            UnifiedModel.canonical_id == norm.canonical_id
                        )
                        res_existing = await db.execute(stmt_existing)
                        canonical_um = res_existing.scalar_one()
                    canonical_um_map[norm.canonical_id] = canonical_um
                else:
                    if norm.display_name and not canonical_um.display_name:
                        canonical_um.display_name = norm.display_name
                    if norm.description and not canonical_um.description:
                        canonical_um.description = norm.description
                    canonical_um.updated_at = now

                # Upsert ProviderModel offering for this credential
                prov_model = prov_model_map.get(norm.provider_model_id)
                if prov_model is None:
                    prov_model = ProviderModel(
                        unified_model_id=canonical_um.id,
                        provider=provider_name,
                        provider_model_id=norm.provider_model_id,
                        credential_id=credential_id,
                        context_window=norm.context_window,
                        max_output_tokens=norm.max_output_tokens,
                        input_price_per_million=norm.input_price_per_million,
                        output_price_per_million=norm.output_price_per_million,
                        supports_streaming=norm.supports_streaming,
                        supports_tools=norm.supports_tools,
                        supports_structured_output=norm.supports_structured_output,
                        supports_vision=norm.supports_vision,
                        supports_reasoning=norm.supports_reasoning,
                        availability_status="available",
                        metadata_source=norm.metadata_source,
                        capability_metadata=norm.capability_metadata,
                        raw_metadata=norm.raw_metadata,
                        last_seen_at=now,
                        last_verified_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    db.add(prov_model)
                    prov_model_map[norm.provider_model_id] = prov_model
                    result.models_added += 1
                else:
                    prov_model.unified_model_id = canonical_um.id
                    prov_model.context_window = norm.context_window
                    prov_model.max_output_tokens = norm.max_output_tokens
                    prov_model.input_price_per_million = norm.input_price_per_million
                    prov_model.output_price_per_million = norm.output_price_per_million
                    prov_model.supports_streaming = norm.supports_streaming
                    prov_model.supports_tools = norm.supports_tools
                    prov_model.supports_structured_output = (
                        norm.supports_structured_output
                    )
                    prov_model.supports_vision = norm.supports_vision
                    prov_model.supports_reasoning = norm.supports_reasoning
                    prov_model.availability_status = "available"
                    prov_model.metadata_source = norm.metadata_source
                    prov_model.capability_metadata = norm.capability_metadata
                    prov_model.raw_metadata = norm.raw_metadata
                    prov_model.last_seen_at = now
                    prov_model.last_verified_at = now
                    prov_model.updated_at = now
                    result.models_updated += 1

            # 4. Availability reconciliation for missing models (only if list_models succeeded)
            for pm in prov_model_map.values():
                if (
                    pm.provider_model_id not in returned_provider_model_ids
                    and pm.availability_status != "unavailable"
                ):
                    pm.availability_status = "unavailable"
                    pm.updated_at = now
                    result.models_marked_unavailable += 1

            # Update credential last_validated_at
            credential.last_validated_at = now
            credential.status = "active"

            sync_log.status = "completed"
            sync_log.completed_at = now
            sync_log.models_added = result.models_added
            sync_log.models_updated = result.models_updated
            sync_log.models_marked_unavailable = result.models_marked_unavailable
            await db.commit()

        except InvalidCredentialsError as exc:
            logger.warning(
                "Sync failed due to invalid credentials for provider %s: %s",
                provider_name,
                exc.message,
            )
            await db.rollback()
            now = datetime.now(UTC)
            error_msg = f"Provider {provider_name} authentication failed: {exc.message}"
            fail_log = ModelSyncLog(
                user_id=user_id,
                provider=provider_name,
                credential_id=credential_id,
                status="failed",
                started_at=started_at,
                completed_at=now,
                error_summary=error_msg,
            )
            db.add(fail_log)
            # Mark credential invalid
            cred_res = await db.execute(
                select(ProviderCredential).where(ProviderCredential.id == credential_id)
            )
            c = cred_res.scalar_one_or_none()
            if c:
                c.status = "invalid"
                c.last_validated_at = now
            await db.commit()

            result.status = "failed"
            result.error_summary = error_msg

        except (RateLimitError, ProviderError) as exc:
            logger.warning(
                "Sync failed due to provider error for provider %s: %s",
                provider_name,
                exc.message,
            )
            await db.rollback()
            now = datetime.now(UTC)
            error_msg = f"Provider {provider_name} request error: {exc.message}"
            fail_log = ModelSyncLog(
                user_id=user_id,
                provider=provider_name,
                credential_id=credential_id,
                status="failed",
                started_at=started_at,
                completed_at=now,
                error_summary=error_msg,
            )
            db.add(fail_log)
            await db.commit()

            result.status = "failed"
            result.error_summary = error_msg

        except Exception as exc:
            logger.error(
                "Unexpected error during sync for provider %s: %s",
                provider_name,
                str(exc),
                exc_info=True,
            )
            await db.rollback()
            now = datetime.now(UTC)
            error_msg = f"Unexpected sync error: {type(exc).__name__}"
            fail_log = ModelSyncLog(
                user_id=user_id,
                provider=provider_name,
                credential_id=credential_id,
                status="failed",
                started_at=started_at,
                completed_at=now,
                error_summary=error_msg,
            )
            db.add(fail_log)
            await db.commit()

            result.status = "failed"
            result.error_summary = error_msg

        return result

    async def sync_for_user(
        self,
        db: AsyncSession,
        user: User,
        provider: str | None = None,
        credential_id: uuid.UUID | None = None,
    ) -> SyncReportResponse:
        """Trigger model discovery sync across filtered or all credentials for the user."""
        started_at = datetime.now(UTC)
        sync_run_id = uuid.uuid4()
        user_id = user.id

        # Query credential IDs upfront to avoid ORM instance expiration issues across sub-commits
        query = select(ProviderCredential.id).where(
            ProviderCredential.user_id == user_id,
            ProviderCredential.status == "active",
        )
        if credential_id:
            query = query.where(ProviderCredential.id == credential_id)
        if provider:
            query = query.where(ProviderCredential.provider == provider.strip().lower())

        creds_res = await db.execute(query)
        cred_ids = list(creds_res.scalars().all())

        report = SyncReportResponse(
            sync_id=sync_run_id,
            status="completed",
            started_at=started_at,
        )

        if not cred_ids:
            report.completed_at = datetime.now(UTC)
            if credential_id or provider:
                report.errors.append(
                    "No active credentials found matching the criteria."
                )
            return report

        has_failure = False
        has_success = False

        for c_id in cred_ids:
            cred_stmt = select(ProviderCredential).where(ProviderCredential.id == c_id)
            c_res = await db.execute(cred_stmt)
            cred = c_res.scalar_one_or_none()
            if not cred:
                continue

            cred_result = await self.sync_credential(db, user_id, cred)
            report.credentials_synced.append(cred_result)
            report.total_discovered += cred_result.models_discovered
            report.total_added += cred_result.models_added
            report.total_updated += cred_result.models_updated
            report.total_marked_unavailable += cred_result.models_marked_unavailable

            if cred_result.status == "completed":
                has_success = True
            else:
                has_failure = True
                if cred_result.error_summary:
                    report.errors.append(cred_result.error_summary)

        report.completed_at = datetime.now(UTC)
        if has_failure and has_success:
            report.status = "partial_failure"
        elif has_failure:
            report.status = "failed"
        else:
            report.status = "completed"

        return report

    async def get_latest_sync_status(
        self,
        db: AsyncSession,
        user: User,
        limit: int = 20,
    ) -> list[ModelSyncLog]:
        """Fetch historical synchronization logs strictly for the authenticated user."""
        stmt = (
            select(ModelSyncLog)
            .where(ModelSyncLog.user_id == user.id)
            .order_by(ModelSyncLog.started_at.desc())
            .limit(limit)
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())


# Singleton instance
model_sync_service = ModelSyncService()


def get_model_sync_service() -> ModelSyncService:
    """Dependency provider for ModelSyncService."""
    return model_sync_service
