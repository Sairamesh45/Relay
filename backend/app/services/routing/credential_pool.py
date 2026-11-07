"""Credential Pool Manager orchestrating multi-account selection and deferred secret decryption."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_api_key
from app.models.provider_credential import ProviderCredential
from app.models.routing_policy import VirtualKeyRoutingPolicy
from app.services.routing.candidates import Candidate
from app.services.routing.metrics import CandidateMetrics
from app.services.routing.policies import CredentialSelectionStrategy
from app.services.routing.strategies import (
    BaseCredentialStrategy,
    DeterministicDefaultStrategy,
    LeastRecentlyUsedStrategy,
    LowestLatencyStrategy,
    PreferredCredentialStrategy,
    RoundRobinStrategy,
)


class CredentialPoolManager:
    """Manages multi-account credential pooling, selection strategies, and deferred decryption."""

    def __init__(self) -> None:
        self._strategies: dict[str, BaseCredentialStrategy] = {
            CredentialSelectionStrategy.ROUND_ROBIN.value: RoundRobinStrategy(),
            CredentialSelectionStrategy.LEAST_RECENTLY_USED.value: LeastRecentlyUsedStrategy(),
            CredentialSelectionStrategy.PREFERRED.value: PreferredCredentialStrategy(),
            CredentialSelectionStrategy.LOWEST_LATENCY.value: LowestLatencyStrategy(),
            CredentialSelectionStrategy.DETERMINISTIC_DEFAULT.value: DeterministicDefaultStrategy(),
        }

    def get_strategy(self, strategy_name: str) -> BaseCredentialStrategy:
        """Retrieve the configured strategy or fallback to deterministic default."""
        return self._strategies.get(
            strategy_name,
            self._strategies[CredentialSelectionStrategy.DETERMINISTIC_DEFAULT.value],
        )

    async def select_from_pool(
        self,
        db: AsyncSession,
        candidates: list[Candidate],
        policy: VirtualKeyRoutingPolicy,
        metrics_map: dict[tuple[str, str, uuid.UUID | None], CandidateMetrics],
    ) -> tuple[Candidate, str, str]:
        """Select a single candidate offering from multiple eligible credentials.

        Returns (selected_candidate, strategy_name, selection_explanation).
        """
        if not candidates:
            raise ValueError("Cannot select from an empty candidate pool.")

        strategy_name = (
            policy.credential_selection_strategy
            or CredentialSelectionStrategy.ROUND_ROBIN.value
        )
        strategy = self.get_strategy(strategy_name)

        selected_cand, explanation = await strategy.select_candidate(
            db=db,
            candidates=candidates,
            policy=policy,
            metrics_map=metrics_map,
        )

        return selected_cand, strategy_name, explanation

    async def decrypt_credential(
        self,
        db: AsyncSession,
        credential_id: uuid.UUID,
    ) -> str:
        """Safely decrypt provider API key immediately prior to upstream dispatch.

        Never decrypts credentials during candidate discovery or scoring.
        """
        stmt = select(ProviderCredential).where(ProviderCredential.id == credential_id)
        res = await db.execute(stmt)
        cred = res.scalar_one_or_none()
        if not cred:
            raise ValueError(f"Provider credential '{credential_id}' not found.")

        return decrypt_api_key(cred.encrypted_api_key, cred.key_version)


credential_pool_manager = CredentialPoolManager()


def get_credential_pool_manager() -> CredentialPoolManager:
    """Dependency getter for CredentialPoolManager."""
    return credential_pool_manager
