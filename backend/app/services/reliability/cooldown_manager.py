"""Scope-aware cooldown manager for AI provider credentials and models.

Implements exponential backoff with jitter, respects confirmed upstream reset
times (Retry-After), enforces scope-aware cooldowns (model vs credential),
and resets failure counters upon successful execution.
"""

from __future__ import annotations

import enum
import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reliability import CredentialHealth, HealthStatus
from app.services.reliability.error_classifier import ClassifiedError, ErrorCategory


class CooldownScope(enum.StrEnum):
    """Scope granularity for cooldown enforcement."""

    CREDENTIAL = "credential"
    MODEL = "model"


class CooldownManager:
    """Manages scoped backoff intervals and cooldown tracking."""

    def __init__(
        self,
        initial_backoff: float = 2.0,
        max_cooldown: float = 300.0,
        backoff_multiplier: float = 2.0,
    ) -> None:
        self.initial_backoff = initial_backoff
        self.max_cooldown = max_cooldown
        self.backoff_multiplier = backoff_multiplier
        # In-memory storage for fine-grained model-specific cooldowns: (credential_id, model_id) -> expiry_datetime
        self._model_cooldowns: dict[tuple[uuid.UUID, str], datetime] = {}

    def calculate_cooldown(
        self,
        consecutive_failures: int,
        retry_after: float | None = None,
        initial_backoff: float | None = None,
        max_cooldown: float | None = None,
        jitter: bool = True,
    ) -> float:
        """Calculate cooldown duration in seconds using exponential backoff with full jitter.

        If upstream provides an explicit retry_after value, that duration is prioritized.
        """
        init_bo = (
            initial_backoff if initial_backoff is not None else self.initial_backoff
        )
        max_cd = max_cooldown if max_cooldown is not None else self.max_cooldown

        if retry_after is not None and retry_after > 0:
            # Respect upstream provider reset duration
            delay = float(retry_after)
            return min(delay, max_cd)

        # Exponential backoff based on consecutive failures
        exp = max(0, consecutive_failures - 1)
        base = min(init_bo * (self.backoff_multiplier**exp), max_cd)

        if jitter:
            # Full jitter: randomized between 0.5 * base and 1.5 * base
            delay = random.uniform(0.5 * base, 1.5 * base)
        else:
            delay = base

        return min(delay, max_cd)

    def determine_cooldown_scope(
        self,
        error: ClassifiedError,
        model_id: str | None = None,
    ) -> CooldownScope:
        """Determine whether the cooldown should apply narrowly to a model or broadly to the credential."""
        if not model_id:
            return CooldownScope.CREDENTIAL

        # Errors strictly bound to a specific model architecture
        if error.category in (
            ErrorCategory.MODEL_UNAVAILABLE,
            ErrorCategory.CONTEXT_LENGTH_EXCEEDED,
            ErrorCategory.UNSUPPORTED_PARAMETER,
        ):
            return CooldownScope.MODEL

        # For rate limits on Groq (which are often per-model), narrow to model scope if model_id is present
        if (
            error.category == ErrorCategory.RATE_LIMITED
            and error.provider.lower() == "groq"
        ):
            return CooldownScope.MODEL

        # Credential-wide failures: Auth, Perm, Quota, Server Error, Provider Outage
        return CooldownScope.CREDENTIAL

    async def apply_cooldown(
        self,
        db: AsyncSession,
        health: CredentialHealth,
        error: ClassifiedError,
        model_id: str | None = None,
    ) -> tuple[datetime, CooldownScope]:
        """Apply a calculated cooldown either to the in-memory model registry or the database CredentialHealth."""
        now = datetime.now(UTC)
        duration = self.calculate_cooldown(
            consecutive_failures=health.consecutive_failures,
            retry_after=error.retry_after,
        )
        expiry = now + timedelta(seconds=duration)
        scope = self.determine_cooldown_scope(error, model_id)

        if scope == CooldownScope.MODEL and model_id:
            # Record narrow model cooldown
            self._model_cooldowns[(health.credential_id, model_id)] = expiry
        else:
            # Record credential-wide cooldown
            health.cooldown_until = expiry
            if health.health_status not in (
                HealthStatus.AUTH_FAILED,
                HealthStatus.PERM_DENIED,
                HealthStatus.DISABLED,
            ):
                health.health_status = (
                    HealthStatus.RATE_LIMITED
                    if error.category
                    in (ErrorCategory.RATE_LIMITED, ErrorCategory.QUOTA_EXHAUSTED)
                    else HealthStatus.COOLING_DOWN
                )
            await db.flush()

        return expiry, scope

    def is_cooling_down(
        self,
        health: CredentialHealth | None,
        model_id: str | None = None,
    ) -> bool:
        """Check whether a credential or specific model on that credential is under active cooldown."""
        now = datetime.now(UTC)

        # Check credential-level cooldown in DB health model
        if health and health.cooldown_until and now < health.cooldown_until:
            return True

        # Check model-level cooldown in in-memory scope registry
        if health and model_id:
            model_key = (health.credential_id, model_id)
            expiry = self._model_cooldowns.get(model_key)
            if expiry:
                if now < expiry:
                    return True
                # Clean up expired entry
                self._model_cooldowns.pop(model_key, None)

        return False

    def clear_model_cooldown(self, credential_id: uuid.UUID, model_id: str) -> None:
        """Clear model-specific cooldown upon successful recovery."""
        self._model_cooldowns.pop((credential_id, model_id), None)

    def clear_all_model_cooldowns(self, credential_id: uuid.UUID) -> None:
        """Clear all model cooldowns for a credential."""
        keys_to_remove = [k for k in self._model_cooldowns if k[0] == credential_id]
        for k in keys_to_remove:
            self._model_cooldowns.pop(k, None)


# Singleton instance provider
_cooldown_manager: CooldownManager | None = None


def get_cooldown_manager() -> CooldownManager:
    """Dependency injection provider for CooldownManager."""
    global _cooldown_manager
    if _cooldown_manager is None:
        _cooldown_manager = CooldownManager()
    return _cooldown_manager
