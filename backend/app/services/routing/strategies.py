"""Credential selection strategies for multi-account pools."""

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gateway_request_log import GatewayRequestLog
from app.models.routing_policy import VirtualKeyRoutingPolicy
from app.models.routing_state import CredentialPoolState
from app.services.routing.candidates import Candidate
from app.services.routing.metrics import CandidateMetrics


class BaseCredentialStrategy(ABC):
    """Abstract strategy for picking a single candidate from multiple eligible credential offerings."""

    @abstractmethod
    async def select_candidate(
        self,
        db: AsyncSession,
        candidates: list[Candidate],
        policy: VirtualKeyRoutingPolicy,
        metrics_map: dict[tuple[str, str, uuid.UUID | None], CandidateMetrics],
    ) -> tuple[Candidate, str]:
        """Select a candidate from the pool and return (selected_candidate, strategy_explanation)."""
        pass


class DeterministicDefaultStrategy(BaseCredentialStrategy):
    """Fallback strategy selecting the candidate with lowest UUID for strict determinism."""

    async def select_candidate(
        self,
        db: AsyncSession,
        candidates: list[Candidate],
        policy: VirtualKeyRoutingPolicy,
        metrics_map: dict[tuple[str, str, uuid.UUID | None], CandidateMetrics],
    ) -> tuple[Candidate, str]:
        sorted_cands = sorted(candidates, key=lambda c: str(c.credential_id))
        selected = sorted_cands[0]
        return (
            selected,
            f"Selected credential '{selected.credential_id}' via deterministic default ordering.",
        )


class PreferredCredentialStrategy(BaseCredentialStrategy):
    """Strategy prioritizing the user's explicitly configured preferred credential."""

    def __init__(self, fallback: BaseCredentialStrategy | None = None) -> None:
        self.fallback = fallback or DeterministicDefaultStrategy()

    async def select_candidate(
        self,
        db: AsyncSession,
        candidates: list[Candidate],
        policy: VirtualKeyRoutingPolicy,
        metrics_map: dict[tuple[str, str, uuid.UUID | None], CandidateMetrics],
    ) -> tuple[Candidate, str]:
        if policy.preferred_credential_id:
            for c in candidates:
                if c.credential_id == policy.preferred_credential_id:
                    return (
                        c,
                        f"Selected preferred credential '{c.credential_id}'.",
                    )

        # Fallback if preferred credential is unset or ineligible
        fallback_cand, reason = await self.fallback.select_candidate(
            db, candidates, policy, metrics_map
        )
        return (
            fallback_cand,
            f"Preferred credential unavailable or unset; {reason}",
        )


class RoundRobinStrategy(BaseCredentialStrategy):
    """Concurrency-safe PostgreSQL-backed Round Robin selection across multiple workers."""

    async def select_candidate(
        self,
        db: AsyncSession,
        candidates: list[Candidate],
        policy: VirtualKeyRoutingPolicy,
        metrics_map: dict[tuple[str, str, uuid.UUID | None], CandidateMetrics],
    ) -> tuple[Candidate, str]:
        if len(candidates) == 1:
            return (
                candidates[0],
                f"Single candidate available for credential pool; selected '{candidates[0].credential_id}'.",
            )

        # Sort candidates deterministically before indexing
        sorted_cands = sorted(candidates, key=lambda c: str(c.credential_id))
        n = len(sorted_cands)

        prov = sorted_cands[0].provider
        model_id = sorted_cands[0].provider_model_id
        user_id = policy.user_id

        # Atomic PostgreSQL UPSERT to update selection counter and record state
        stmt = (
            insert(CredentialPoolState)
            .values(
                user_id=user_id,
                provider=prov,
                provider_model_id=model_id,
                selection_counter=1,
                updated_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                constraint="uq_pool_state_user_prov_model",
                set_={
                    "selection_counter": CredentialPoolState.selection_counter + 1,
                    "updated_at": datetime.now(UTC),
                },
            )
            .returning(CredentialPoolState.selection_counter)
        )
        res = await db.execute(stmt)
        counter = res.scalar_one()

        idx = (counter - 1) % n
        selected = sorted_cands[idx]

        # Update last_selected_credential_id asynchronously in session
        state_stmt = select(CredentialPoolState).where(
            CredentialPoolState.user_id == user_id,
            CredentialPoolState.provider == prov,
            CredentialPoolState.provider_model_id == model_id,
        )
        state_res = await db.execute(state_stmt)
        state_obj = state_res.scalar_one_or_none()
        if state_obj:
            state_obj.last_selected_credential_id = selected.credential_id

        return (
            selected,
            f"Selected credential '{selected.credential_id}' via round-robin (turn {counter} across {n} offerings).",
        )


class LeastRecentlyUsedStrategy(BaseCredentialStrategy):
    """Selects the credential with the oldest recorded gateway execution timestamp."""

    async def select_candidate(
        self,
        db: AsyncSession,
        candidates: list[Candidate],
        policy: VirtualKeyRoutingPolicy,
        metrics_map: dict[tuple[str, str, uuid.UUID | None], CandidateMetrics],
    ) -> tuple[Candidate, str]:
        if len(candidates) == 1:
            return (
                candidates[0],
                f"Single candidate available; selected '{candidates[0].credential_id}'.",
            )

        cand_cred_ids = [c.credential_id for c in candidates]

        # Query latest request per credential
        stmt = (
            select(
                GatewayRequestLog.provider_credential_id,
                GatewayRequestLog.created_at,
            )
            .where(
                GatewayRequestLog.user_id == policy.user_id,
                GatewayRequestLog.provider_credential_id.in_(cand_cred_ids),
            )
            .order_by(GatewayRequestLog.created_at.desc())
        )
        res = await db.execute(stmt)
        rows = res.all()

        last_used_map: dict[uuid.UUID, datetime] = {}
        for r in rows:
            if r.provider_credential_id not in last_used_map:
                last_used_map[r.provider_credential_id] = r.created_at

        # Sort candidates: credentials never used come first, then oldest created_at
        sorted_cands = sorted(
            candidates,
            key=lambda c: (
                last_used_map.get(c.credential_id) is not None,
                last_used_map.get(c.credential_id) or datetime.min,
                str(c.credential_id),
            ),
        )
        selected = sorted_cands[0]
        ts_desc = (
            last_used_map.get(selected.credential_id).isoformat()
            if last_used_map.get(selected.credential_id)
            else "never"
        )
        return (
            selected,
            f"Selected credential '{selected.credential_id}' via least recently used (last active: {ts_desc}).",
        )


class LowestLatencyStrategy(BaseCredentialStrategy):
    """Selects the credential offering with the lowest observed average latency."""

    async def select_candidate(
        self,
        db: AsyncSession,
        candidates: list[Candidate],
        policy: VirtualKeyRoutingPolicy,
        metrics_map: dict[tuple[str, str, uuid.UUID | None], CandidateMetrics],
    ) -> tuple[Candidate, str]:
        def cand_latency(c: Candidate) -> tuple[float, str]:
            m = metrics_map.get((c.provider, c.provider_model_id, c.credential_id))
            if m and m.avg_latency_ms is not None:
                return (m.avg_latency_ms, str(c.credential_id))
            return (999999.0, str(c.credential_id))

        sorted_cands = sorted(candidates, key=cand_latency)
        selected = sorted_cands[0]
        m = metrics_map.get(
            (selected.provider, selected.provider_model_id, selected.credential_id)
        )
        lat_desc = f"{m.avg_latency_ms}ms" if (m and m.avg_latency_ms) else "unmeasured"
        return (
            selected,
            f"Selected credential '{selected.credential_id}' via lowest observed latency ({lat_desc}).",
        )
