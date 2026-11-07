"""Candidate data model and user-scoped discovery service with hard constraint filtering."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.provider_credential import ProviderCredential
from app.models.provider_model import ProviderModel
from app.services.routing.context import RoutingContext
from app.services.routing.policies import is_modality_compatible


@dataclass
class Candidate:
    """Represents a concrete provider, provider model, and credential combination."""

    provider: str
    provider_model_id: str
    gateway_model_id: str
    credential_id: uuid.UUID
    credential_display_name: str | None
    canonical_model_id: uuid.UUID
    canonical_name: str
    context_window: int | None
    max_output_tokens: int | None
    input_price_per_million: Decimal | None
    output_price_per_million: Decimal | None
    supports_streaming: bool | None
    supports_tools: bool | None
    supports_structured_output: bool | None
    supports_vision: bool | None
    supports_reasoning: bool | None
    input_modalities: list[str] = field(default_factory=list)
    output_modalities: list[str] = field(default_factory=list)
    availability_status: str = "available"
    last_seen_at: datetime | None = None
    capability_metadata: dict[str, Any] = field(default_factory=dict)
    provider_model: ProviderModel | None = None


@dataclass
class CandidateDiscoveryResult:
    """Discovery output holding eligible candidates and exclusion diagnostics."""

    eligible: list[Candidate]
    excluded: dict[str, list[str]] = field(default_factory=dict)


class CandidateDiscoveryService:
    """Discovers and hard-filters candidate offerings scoped to the authenticated user."""

    async def discover_candidates(
        self,
        db: AsyncSession,
        ctx: RoutingContext,
    ) -> CandidateDiscoveryResult:
        """Fetch all offerings connected to active user credentials and filter by hard constraints."""
        # 1. Query active credentials of user
        cred_stmt = select(ProviderCredential).where(
            ProviderCredential.user_id == ctx.user.id,
            ProviderCredential.status == "active",
        )
        cred_res = await db.execute(cred_stmt)
        user_creds = list(cred_res.scalars().all())

        if not user_creds:
            return CandidateDiscoveryResult(
                eligible=[],
                excluded={
                    "user": ["No active provider credentials configured for user."]
                },
            )

        cred_map = {c.id: c for c in user_creds}
        cred_ids = list(cred_map.keys())

        # 2. Query available ProviderModels offering through these credentials
        model_stmt = (
            select(ProviderModel)
            .options(selectinload(ProviderModel.unified_model))
            .where(
                ProviderModel.credential_id.in_(cred_ids),
                ProviderModel.availability_status == "available",
            )
        )
        model_res = await db.execute(model_stmt)
        offerings = list(model_res.scalars().all())

        eligible_candidates: list[Candidate] = []
        excluded_candidates: dict[str, list[str]] = {}

        policy = ctx.policy

        # Handle explicit request model variants (e.g. Gemini prefix)
        target_variants: list[str] = []
        if ctx.is_explicit and ctx.explicit_provider_model_id:
            m_id = ctx.explicit_provider_model_id
            target_variants.append(m_id)
            if ctx.explicit_provider == "gemini":
                if m_id.startswith("models/"):
                    target_variants.append(m_id.removeprefix("models/"))
                else:
                    target_variants.append(f"models/{m_id}")

        for pm in offerings:
            cred = cred_map.get(pm.credential_id)
            if not cred:
                continue

            candidate_key = f"{pm.provider}:{pm.provider_model_id}#{cred.id}"
            reasons: list[str] = []

            # Hard Constraint: Explicit match
            if ctx.is_explicit:
                if (
                    ctx.explicit_provider
                    and pm.provider.lower() != ctx.explicit_provider.lower()
                ):
                    continue

                if ctx.explicit_provider_model_id:
                    target_lower = [v.lower() for v in target_variants]
                    pm_lower = pm.provider_model_id.lower()
                    canonical_lower = (
                        pm.unified_model.canonical_id.lower()
                        if pm.unified_model and pm.unified_model.canonical_id
                        else None
                    )
                    display_lower = (
                        pm.unified_model.display_name.lower()
                        if pm.unified_model and pm.unified_model.display_name
                        else None
                    )
                    matches_explicit = (
                        pm_lower in target_lower
                        or (canonical_lower and canonical_lower in target_lower)
                        or (display_lower and display_lower in target_lower)
                    )
                    if not matches_explicit:
                        continue

            # Hard Constraint: Virtual API Key Permissions
            if ctx.key and ctx.key.permissions:
                perms = ctx.key.permissions
                # Check provider permissions
                if (
                    "providers" in perms
                    and isinstance(perms["providers"], list)
                    and perms["providers"]
                ):
                    allowed_p = [p.lower() for p in perms["providers"]]
                    if pm.provider.lower() not in allowed_p:
                        reasons.append(
                            f"Provider '{pm.provider}' not permitted by virtual API key permissions."
                        )
                # Check model permissions
                if (
                    "models" in perms
                    and isinstance(perms["models"], list)
                    and perms["models"]
                ):
                    gw_id_lower = f"{pm.provider}:{pm.provider_model_id}".lower()
                    pm_id_lower = pm.provider_model_id.lower()
                    canon_lower = (
                        pm.unified_model.canonical_id.lower()
                        if pm.unified_model and pm.unified_model.canonical_id
                        else None
                    )

                    allowed = False
                    for pattern in perms["models"]:
                        pat = pattern.lower().strip()
                        if pat == "*":
                            allowed = True
                            break
                        if pat.endswith(":*"):
                            if pm.provider.lower() == pat[:-2]:
                                allowed = True
                                break
                        elif pat in (gw_id_lower, pm_id_lower, canon_lower):
                            allowed = True
                            break

                    if not allowed:
                        reasons.append(
                            f"Model '{pm.provider_model_id}' not permitted by virtual API key permissions."
                        )

            # Hard Constraint: Provider Whitelist / Blacklist (enforced for both explicit and auto)
            if policy.allowed_providers and pm.provider.lower() not in [
                p.lower() for p in policy.allowed_providers
            ]:
                reasons.append(f"Provider '{pm.provider}' not in allowed_providers.")

            if policy.excluded_providers and pm.provider.lower() in [
                p.lower() for p in policy.excluded_providers
            ]:
                reasons.append(f"Provider '{pm.provider}' in excluded_providers.")

            # Hard Constraint: Model Whitelist / Blacklist
            model_names = [pm.provider_model_id.lower()]
            if pm.unified_model:
                if pm.unified_model.display_name:
                    model_names.append(pm.unified_model.display_name.lower())
                if pm.unified_model.canonical_id:
                    model_names.append(pm.unified_model.canonical_id.lower())

            if policy.allowed_models:
                allowed_lower = [m.lower() for m in policy.allowed_models]
                if not any(
                    m in allowed_lower
                    or any(m in al or al in m for al in allowed_lower)
                    for m in model_names
                ):
                    reasons.append(
                        f"Model '{pm.provider_model_id}' not in allowed_models."
                    )

            if policy.excluded_models:
                excluded_lower = [m.lower() for m in policy.excluded_models]
                if any(
                    m in excluded_lower
                    or any(m in ex or ex in m for ex in excluded_lower)
                    for m in model_names
                ):
                    reasons.append(
                        f"Model '{pm.provider_model_id}' in excluded_models."
                    )

            # Modality and Model Access Profile
            input_mods = (
                pm.unified_model.input_modalities if pm.unified_model else ["text"]
            )
            output_mods = (
                pm.unified_model.output_modalities if pm.unified_model else ["text"]
            )
            if not is_modality_compatible(
                policy.model_access_profile, input_mods, output_mods
            ):
                reasons.append(
                    f"Model input modalities {input_mods} incompatible with access profile '{policy.model_access_profile}'."
                )

            # Request Capabilities
            if ctx.requires_streaming and pm.supports_streaming is False:
                reasons.append(
                    "Request requires streaming, but candidate does not support streaming."
                )

            if ctx.requires_tools and not pm.supports_tools:
                reasons.append(
                    "Request requires tool calling, but candidate does not support tools."
                )

            if ctx.requires_structured_output and not pm.supports_structured_output:
                reasons.append(
                    "Request requires structured JSON output, but candidate does not support it."
                )

            if ctx.requires_vision and not pm.supports_vision:
                reasons.append(
                    "Request requires vision support, but candidate does not support vision."
                )

            # Policy Required Capabilities
            if policy.required_capabilities:
                for cap in policy.required_capabilities:
                    cap_lower = cap.lower()
                    if cap_lower == "streaming" and pm.supports_streaming is False:
                        reasons.append("Policy requires streaming.")
                    elif cap_lower == "tools" and not pm.supports_tools:
                        reasons.append("Policy requires tool support.")
                    elif cap_lower == "vision" and not pm.supports_vision:
                        reasons.append("Policy requires vision support.")
                    elif (
                        cap_lower == "structured_output"
                        and not pm.supports_structured_output
                    ):
                        reasons.append("Policy requires structured output support.")
                    elif cap_lower == "reasoning" and not pm.supports_reasoning:
                        reasons.append("Policy requires reasoning support.")

            # Context Window Constraints
            if policy.minimum_context_window:
                if (
                    pm.context_window is not None
                    and pm.context_window < policy.minimum_context_window
                ):
                    reasons.append(
                        f"Context window ({pm.context_window}) below policy minimum ({policy.minimum_context_window})."
                    )

            if ctx.estimated_input_tokens:
                if (
                    pm.context_window is not None
                    and pm.context_window < ctx.estimated_input_tokens
                ):
                    reasons.append(
                        f"Estimated input tokens ({ctx.estimated_input_tokens}) exceed context window ({pm.context_window})."
                    )

            # Maximum Cost Constraint
            if policy.maximum_cost_per_request is not None:
                if (
                    pm.input_price_per_million is not None
                    and pm.output_price_per_million is not None
                ):
                    max_out = ctx.request_params.get("max_tokens") or 1000
                    est_cost = (
                        Decimal(ctx.estimated_input_tokens) / Decimal(1_000_000)
                    ) * pm.input_price_per_million + (
                        Decimal(max_out) / Decimal(1_000_000)
                    ) * pm.output_price_per_million
                    if est_cost > policy.maximum_cost_per_request:
                        reasons.append(
                            f"Estimated cost (${float(est_cost):.6f}) exceeds maximum threshold (${float(policy.maximum_cost_per_request):.6f})."
                        )

            if reasons:
                excluded_candidates[candidate_key] = reasons
            else:
                gateway_id = f"{pm.provider}:{pm.provider_model_id}"
                c = Candidate(
                    provider=pm.provider,
                    provider_model_id=pm.provider_model_id,
                    gateway_model_id=gateway_id,
                    credential_id=cred.id,
                    credential_display_name=cred.display_name,
                    canonical_model_id=pm.unified_model_id,
                    canonical_name=(
                        pm.unified_model.display_name
                        if (pm.unified_model and pm.unified_model.display_name)
                        else (
                            pm.unified_model.canonical_id
                            if pm.unified_model
                            else pm.provider_model_id
                        )
                    ),
                    context_window=pm.context_window,
                    max_output_tokens=pm.max_output_tokens,
                    input_price_per_million=pm.input_price_per_million,
                    output_price_per_million=pm.output_price_per_million,
                    supports_streaming=pm.supports_streaming,
                    supports_tools=pm.supports_tools,
                    supports_structured_output=pm.supports_structured_output,
                    supports_vision=pm.supports_vision,
                    supports_reasoning=pm.supports_reasoning,
                    input_modalities=input_mods,
                    output_modalities=output_mods,
                    availability_status=pm.availability_status,
                    last_seen_at=pm.last_seen_at,
                    capability_metadata=pm.capability_metadata or {},
                    provider_model=pm,
                )
                eligible_candidates.append(c)

        return CandidateDiscoveryResult(
            eligible=eligible_candidates,
            excluded=excluded_candidates,
        )


candidate_discovery_service = CandidateDiscoveryService()


def get_candidate_discovery_service() -> CandidateDiscoveryService:
    """Dependency getter for CandidateDiscoveryService."""
    return candidate_discovery_service
