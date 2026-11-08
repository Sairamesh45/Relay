"""Credential Health State Machine and Provider Health Matrix Service.

Tracks 9 discrete health states for provider credentials, manages failure counters,
enforces non-auto-recovery for authentication/permission failures, and provides
candidate eligibility filtering for the routing and execution engines.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider_credential import ProviderCredential
from app.models.reliability import CredentialHealth, HealthStatus
from app.services.reliability.cooldown_manager import (
    CooldownManager,
    get_cooldown_manager,
)
from app.services.reliability.error_classifier import (
    ClassifiedError,
    ErrorCategory,
    sanitize_dict,
)


class HealthService:
    """Credential health tracking and state transition service."""

    def __init__(self, cooldown_manager: CooldownManager | None = None) -> None:
        self.cooldown_manager = cooldown_manager or get_cooldown_manager()

    async def get_or_create_health(
        self,
        db: AsyncSession,
        credential_id: uuid.UUID,
    ) -> CredentialHealth:
        """Fetch existing CredentialHealth or initialize default HEALTHY state."""
        stmt = select(CredentialHealth).where(
            CredentialHealth.credential_id == credential_id
        )
        res = await db.execute(stmt)
        health = res.scalars().first()

        if health is None:
            health = CredentialHealth(
                credential_id=credential_id,
                health_status=HealthStatus.HEALTHY,
                failure_count=0,
                consecutive_failures=0,
                error_details={},
            )
            db.add(health)
            await db.flush()

        return health

    async def get_health(
        self,
        db: AsyncSession,
        credential_id: uuid.UUID,
    ) -> CredentialHealth | None:
        """Retrieve existing CredentialHealth without creating a new record."""
        stmt = select(CredentialHealth).where(
            CredentialHealth.credential_id == credential_id
        )
        res = await db.execute(stmt)
        return res.scalars().first()

    async def record_success(
        self,
        db: AsyncSession,
        credential_id: uuid.UUID,
        model_id: str | None = None,
    ) -> CredentialHealth:
        """Record successful request execution for a credential.

        Resets consecutive failure counters and clears active cooldowns.
        Non-auto-recovery rule: Does NOT automatically recover credentials in
        AUTH_FAILED, PERM_DENIED, or DISABLED states without explicit revalidation.
        """
        health = await self.get_or_create_health(db, credential_id)

        # Terminal and administrative states do NOT automatically recover by time or stray execution
        if health.health_status in (
            HealthStatus.AUTH_FAILED,
            HealthStatus.PERM_DENIED,
            HealthStatus.DISABLED,
        ):
            return health

        now = datetime.now(UTC)
        health.consecutive_failures = 0
        health.last_success_at = now
        health.cooldown_until = None
        health.health_status = HealthStatus.HEALTHY

        # Clear any fine-grained model cooldowns
        if model_id:
            self.cooldown_manager.clear_model_cooldown(credential_id, model_id)
        else:
            self.cooldown_manager.clear_all_model_cooldowns(credential_id)

        await db.flush()
        return health

    async def record_failure(
        self,
        db: AsyncSession,
        credential_id: uuid.UUID,
        error: ClassifiedError,
        model_id: str | None = None,
    ) -> CredentialHealth:
        """Record request execution failure, transition health state, and trigger cooldown.

        Strictly enforces non-auto-recovery for authentication and permission failures.
        """
        health = await self.get_or_create_health(db, credential_id)
        now = datetime.now(UTC)

        health.failure_count += 1
        health.consecutive_failures += 1
        health.last_failure_at = now
        health.last_error_category = error.category.value

        # Redact and sanitize error details before storing in JSONB
        health.error_details = sanitize_dict(
            {
                "category": error.category.value,
                "message": error.message,
                "status_code": error.status_code,
                "model_id": model_id,
                "details": error.details,
            }
        )

        # ---------------------------------------------------------------------
        # State Transitions
        # ---------------------------------------------------------------------
        if error.category == ErrorCategory.AUTHENTICATION_FAILED:
            # Terminal state until explicit user revalidation
            health.health_status = HealthStatus.AUTH_FAILED
            health.cooldown_until = None
            await db.flush()
            return health

        if error.category == ErrorCategory.PERMISSION_DENIED:
            health.health_status = HealthStatus.PERM_DENIED
            health.cooldown_until = None
            await db.flush()
            return health

        # Apply backoff / cooldown
        await self.cooldown_manager.apply_cooldown(
            db=db,
            health=health,
            error=error,
            model_id=model_id,
        )

        # Set status based on severity and consecutive failures
        if health.health_status not in (
            HealthStatus.AUTH_FAILED,
            HealthStatus.PERM_DENIED,
            HealthStatus.DISABLED,
        ):
            if health.consecutive_failures >= 3:
                health.health_status = HealthStatus.TEMP_UNAVAILABLE
            elif error.category in (
                ErrorCategory.RATE_LIMITED,
                ErrorCategory.QUOTA_EXHAUSTED,
            ):
                health.health_status = HealthStatus.RATE_LIMITED
            elif health.is_cooling_down:
                health.health_status = HealthStatus.COOLING_DOWN
            else:
                health.health_status = HealthStatus.DEGRADED

        await db.flush()
        return health

    def is_candidate_eligible(
        self,
        health: CredentialHealth | None,
        model_id: str | None = None,
    ) -> bool:
        """Determine if a credential candidate is eligible to receive traffic.

        Returns False if:
        1. Credential is in AUTH_FAILED, PERM_DENIED, or DISABLED.
        2. Credential is under active credential-wide cooldown.
        3. Model is under active model-specific cooldown.
        """
        if health is None:
            return True

        # Non-auto-recovery terminal states
        if health.health_status in (
            HealthStatus.AUTH_FAILED,
            HealthStatus.PERM_DENIED,
            HealthStatus.DISABLED,
        ):
            return False

        # Check cooldown (both credential-level and model-level)
        if self.cooldown_manager.is_cooling_down(health, model_id=model_id):
            return False

        return True

    async def filter_eligible_credentials(
        self,
        db: AsyncSession,
        credential_ids: list[uuid.UUID],
    ) -> list[uuid.UUID]:
        """Filter a list of candidate credential IDs, removing cooling down or auth-failed candidates."""
        if not credential_ids:
            return []

        stmt = select(CredentialHealth).where(
            CredentialHealth.credential_id.in_(credential_ids)
        )
        res = await db.execute(stmt)
        health_map = {h.credential_id: h for h in res.scalars().all()}

        eligible: list[uuid.UUID] = []
        for cid in credential_ids:
            h = health_map.get(cid)
            if self.is_candidate_eligible(h):
                eligible.append(cid)

        return eligible

    async def revalidate_credential_health(
        self,
        db: AsyncSession,
        credential_id: uuid.UUID,
        is_valid: bool,
        error_message: str | None = None,
    ) -> CredentialHealth:
        """Force validation result update for a credential.

        Recovers a credential from AUTH_FAILED if validation succeeds.
        """
        health = await self.get_or_create_health(db, credential_id)
        now = datetime.now(UTC)

        if is_valid:
            health.health_status = HealthStatus.HEALTHY
            health.consecutive_failures = 0
            health.cooldown_until = None
            health.last_success_at = now
            health.error_details = {
                "revalidation": "success",
                "timestamp": now.isoformat(),
            }
            self.cooldown_manager.clear_all_model_cooldowns(credential_id)
        else:
            health.health_status = HealthStatus.AUTH_FAILED
            health.consecutive_failures += 1
            health.last_failure_at = now
            health.last_error_category = ErrorCategory.AUTHENTICATION_FAILED.value
            health.error_details = sanitize_dict(
                {
                    "revalidation": "failed",
                    "error": error_message
                    or "Provider API key rejected during revalidation",
                    "timestamp": now.isoformat(),
                }
            )

        await db.flush()
        return health

    async def get_provider_health_matrix(
        self,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Generate aggregated health matrix across all supported AI providers."""
        supported_providers = ["gemini", "groq", "openrouter"]

        # Fetch all credentials joined with their health
        stmt = (
            select(ProviderCredential, CredentialHealth)
            .outerjoin(
                CredentialHealth,
                ProviderCredential.id == CredentialHealth.credential_id,
            )
            .where(ProviderCredential.status == "active")
        )
        res = await db.execute(stmt)
        rows = res.all()

        provider_map: dict[
            str, list[tuple[ProviderCredential, CredentialHealth | None]]
        ] = {p: [] for p in supported_providers}
        for cred, health in rows:
            p = cred.provider.lower().strip()
            if p in provider_map:
                provider_map[p].append((cred, health))

        matrix: dict[str, Any] = {}
        now = datetime.now(UTC)

        for p in supported_providers:
            creds = provider_map[p]
            total_creds = len(creds)
            if total_creds == 0:
                matrix[p] = {
                    "provider": p,
                    "status": "not_configured",
                    "active_credentials": 0,
                    "healthy_credentials": 0,
                    "cooling_down_credentials": 0,
                    "degraded_credentials": 0,
                    "failed_credentials": 0,
                    "updated_at": now.isoformat(),
                }
                continue

            healthy = 0
            cooling_down = 0
            degraded = 0
            failed = 0

            for _, h in creds:
                if h is None or h.health_status == HealthStatus.HEALTHY:
                    if h and h.cooldown_until and now < h.cooldown_until:
                        cooling_down += 1
                    else:
                        healthy += 1
                elif h.health_status in (
                    HealthStatus.COOLING_DOWN,
                    HealthStatus.RATE_LIMITED,
                ):
                    if h.cooldown_until and now >= h.cooldown_until:
                        healthy += 1
                    else:
                        cooling_down += 1
                elif h.health_status in (
                    HealthStatus.DEGRADED,
                    HealthStatus.TEMP_UNAVAILABLE,
                ):
                    degraded += 1
                elif h.health_status in (
                    HealthStatus.AUTH_FAILED,
                    HealthStatus.PERM_DENIED,
                    HealthStatus.DISABLED,
                ):
                    failed += 1

            if healthy > 0 and failed == 0 and cooling_down == 0 and degraded == 0:
                agg_status = "operational"
            elif healthy > 0:
                agg_status = "degraded"
            elif cooling_down > 0 and healthy == 0:
                agg_status = "rate_limited"
            else:
                agg_status = "outage"

            matrix[p] = {
                "provider": p,
                "status": agg_status,
                "active_credentials": total_creds,
                "healthy_credentials": healthy,
                "cooling_down_credentials": cooling_down,
                "degraded_credentials": degraded,
                "failed_credentials": failed,
                "updated_at": now.isoformat(),
            }

        return matrix


# Singleton instance provider
_health_service: HealthService | None = None


def get_health_service() -> HealthService:
    """Dependency injection provider for HealthService."""
    global _health_service
    if _health_service is None:
        _health_service = HealthService()
    return _health_service
