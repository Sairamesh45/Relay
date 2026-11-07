"""Intelligent Routing Engine orchestrating discovery, scoring, credential selection, and audit logging."""

import time
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gateway_errors import (
    openai_model_not_found_error,
)
from app.models.routing_decision_log import RoutingDecisionLog
from app.models.routing_policy import VirtualKeyRoutingPolicy
from app.models.user import User
from app.models.virtual_api_key import VirtualAPIKey
from app.schemas.chat import ChatCompletionRequest
from app.services.routing.candidates import (
    Candidate,
    CandidateDiscoveryService,
    get_candidate_discovery_service,
)
from app.services.routing.context import RoutingContext
from app.services.routing.credential_pool import (
    CredentialPoolManager,
    get_credential_pool_manager,
)
from app.services.routing.explanations import generate_routing_explanation
from app.services.routing.metrics import (
    RoutingMetricsService,
    get_routing_metrics_service,
)
from app.services.routing.scoring import (
    ModelScorer,
    ScoreBreakdown,
    get_model_scorer,
)


@dataclass
class RoutingDecision:
    """Selected candidate, decrypted API key, and routing decision audit metadata."""

    selected_candidate: Candidate
    raw_api_key: str
    provider: str
    provider_model_id: str
    gateway_model_id: str
    credential_id: uuid.UUID
    routing_mode: str
    routing_preset: str | None
    candidate_count: int
    selection_strategy: str
    score_breakdown: ScoreBreakdown | None
    explanation: str
    decision_latency_ms: float


class RoutingEngine:
    """Core intelligent routing engine for Relay virtual API keys."""

    def __init__(
        self,
        discovery_service: CandidateDiscoveryService | None = None,
        scorer: ModelScorer | None = None,
        metrics_service: RoutingMetricsService | None = None,
        credential_pool: CredentialPoolManager | None = None,
    ) -> None:
        self.discovery_service = discovery_service or get_candidate_discovery_service()
        self.scorer = scorer or get_model_scorer()
        self.metrics_service = metrics_service or get_routing_metrics_service()
        self.credential_pool = credential_pool or get_credential_pool_manager()

    async def get_or_create_policy(
        self,
        db: AsyncSession,
        key: VirtualAPIKey,
        user: User,
    ) -> VirtualKeyRoutingPolicy:
        """Fetch active routing policy for virtual key or create backwards-compatible default."""
        if key.routing_policy:
            return key.routing_policy

        stmt = select(VirtualKeyRoutingPolicy).where(
            VirtualKeyRoutingPolicy.virtual_api_key_id == key.id
        )
        res = await db.execute(stmt)
        policy = res.scalar_one_or_none()

        if policy is None:
            policy = VirtualKeyRoutingPolicy(
                virtual_api_key_id=key.id,
                user_id=user.id,
                routing_mode="preset",
                routing_preset="balanced",
                quality_weight=Decimal("0.2500"),
                speed_weight=Decimal("0.2500"),
                availability_weight=Decimal("0.2500"),
                cost_weight=Decimal("0.2500"),
                model_access_profile="all_models",
                credential_selection_strategy="round_robin",
            )
            db.add(policy)
            await db.commit()
            await db.refresh(policy)

        return policy

    async def route(
        self,
        db: AsyncSession,
        user: User,
        key: VirtualAPIKey,
        request: ChatCompletionRequest,
        request_id: str | None = None,
    ) -> RoutingDecision:
        """Select an eligible model and provider credential, decrypt the key, and record decision audit."""
        start_time = time.perf_counter()

        policy = await self.get_or_create_policy(db, key, user)
        ctx = RoutingContext.from_request(
            user=user, key=key, policy=policy, request=request
        )

        # 1. Discover candidates and evaluate hard constraints
        discovery = await self.discovery_service.discover_candidates(db, ctx)

        if not discovery.eligible:
            # Format diagnostic exclusion message without leaking foreign secrets
            diag_reasons: list[str] = []
            for reasons in discovery.excluded.values():
                diag_reasons.extend(reasons)
            reasons_summary = (
                "; ".join(diag_reasons)
                if diag_reasons
                else "No matching models available."
            )
            raise openai_model_not_found_error(
                f"No eligible provider models found for '{request.model}'. Constraints: {reasons_summary}"
            )

        # 2. Fetch historical operational metrics for eligible candidates
        metrics_map = await self.metrics_service.get_metrics_for_candidates(db, user.id)

        # 3. Explicit vs Alias / Auto Routing
        if ctx.is_explicit:
            routing_mode = "explicit"
            weights = self.scorer.resolve_effective_weights(
                routing_mode=policy.routing_mode,
                routing_preset=policy.routing_preset,
                quality_weight=policy.quality_weight,
                speed_weight=policy.speed_weight,
                availability_weight=policy.availability_weight,
                cost_weight=policy.cost_weight,
            )
            # All eligible candidates match this explicit model
            (
                selected_cand,
                strategy_name,
                strategy_expl,
            ) = await self.credential_pool.select_from_pool(
                db=db,
                candidates=discovery.eligible,
                policy=policy,
                metrics_map=metrics_map,
            )
            # Evaluate single candidate score for observability
            cand_metric = metrics_map.get(
                (
                    selected_cand.provider,
                    selected_cand.provider_model_id,
                    selected_cand.credential_id,
                )
            )
            score_breakdown = self.scorer.score_candidate(
                selected_cand, cand_metric, weights
            )
            explanation = generate_routing_explanation(
                selected=selected_cand,
                score_breakdown=score_breakdown,
                candidate_count=len(discovery.eligible),
                selection_strategy=strategy_name,
                strategy_explanation=strategy_expl,
                routing_mode=routing_mode,
            )

        else:
            routing_mode = ctx.alias or "auto"
            weights = self.scorer.resolve_effective_weights(
                routing_mode=policy.routing_mode,
                routing_preset=policy.routing_preset,
                quality_weight=policy.quality_weight,
                speed_weight=policy.speed_weight,
                availability_weight=policy.availability_weight,
                cost_weight=policy.cost_weight,
                alias_override=ctx.alias,
            )
            # Rank candidates using explainable multi-factor scoring
            ranked = self.scorer.rank_candidates(
                discovery.eligible, metrics_map, weights
            )
            top_ranked = ranked[0]
            top_model_id = top_ranked.candidate.provider_model_id
            top_provider = top_ranked.candidate.provider

            # Find all candidates offering this top-ranked model across credentials
            top_model_candidates = [
                rc.candidate
                for rc in ranked
                if rc.candidate.provider == top_provider
                and rc.candidate.provider_model_id == top_model_id
            ]

            (
                selected_cand,
                strategy_name,
                strategy_expl,
            ) = await self.credential_pool.select_from_pool(
                db=db,
                candidates=top_model_candidates,
                policy=policy,
                metrics_map=metrics_map,
            )
            score_breakdown = top_ranked.score_breakdown
            explanation = generate_routing_explanation(
                selected=selected_cand,
                score_breakdown=score_breakdown,
                candidate_count=len(discovery.eligible),
                selection_strategy=strategy_name,
                strategy_explanation=strategy_expl,
                routing_mode=routing_mode,
            )

        # 4. Decrypt provider API key only for the selected candidate
        raw_key = await self.credential_pool.decrypt_credential(
            db=db, credential_id=selected_cand.credential_id
        )

        decision_latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # 5. Persist routing decision audit log
        decision_req_id = request_id or f"req_{uuid.uuid4().hex}"
        log_entry = RoutingDecisionLog(
            request_id=decision_req_id,
            user_id=user.id,
            virtual_api_key_id=key.id,
            routing_mode=routing_mode,
            routing_preset=policy.routing_preset,
            selected_provider=selected_cand.provider,
            selected_model=selected_cand.provider_model_id,
            selected_credential_id=selected_cand.credential_id,
            candidate_count=len(discovery.eligible),
            selection_strategy=strategy_name,
            score_breakdown=score_breakdown.to_dict() if score_breakdown else {},
            explanation=explanation,
            decision_latency_ms=decision_latency_ms,
        )
        db.add(log_entry)
        await db.commit()

        return RoutingDecision(
            selected_candidate=selected_cand,
            raw_api_key=raw_key,
            provider=selected_cand.provider,
            provider_model_id=selected_cand.provider_model_id,
            gateway_model_id=selected_cand.gateway_model_id,
            credential_id=selected_cand.credential_id,
            routing_mode=routing_mode,
            routing_preset=policy.routing_preset,
            candidate_count=len(discovery.eligible),
            selection_strategy=strategy_name,
            score_breakdown=score_breakdown,
            explanation=explanation,
            decision_latency_ms=decision_latency_ms,
        )


routing_engine = RoutingEngine()


def get_routing_engine() -> RoutingEngine:
    """Dependency getter for RoutingEngine."""
    return routing_engine
