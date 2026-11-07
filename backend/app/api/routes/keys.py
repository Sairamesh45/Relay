"""Virtual API Key management endpoints."""

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.provider_credential import ProviderCredential
from app.models.routing_policy import VirtualKeyRoutingPolicy
from app.models.user import User
from app.schemas.routing import (
    CandidatePreviewItem,
    RoutingPolicyRead,
    RoutingPolicyUpdate,
    RoutingPreviewRequest,
    RoutingPreviewResponse,
)
from app.schemas.virtual_key import (
    VirtualKeyCreate,
    VirtualKeyCreateResponse,
    VirtualKeyListResponse,
    VirtualKeyRead,
)
from app.services.routing.candidates import (
    CandidateDiscoveryService,
    get_candidate_discovery_service,
)
from app.services.routing.context import RoutingContext
from app.services.routing.engine import RoutingEngine, get_routing_engine
from app.services.routing.metrics import (
    RoutingMetricsService,
    get_routing_metrics_service,
)
from app.services.routing.policies import (
    ModelAccessProfile,
    RoutingPreset,
    get_preset_weights,
    validate_and_normalize_weights,
)
from app.services.routing.scoring import ModelScorer, get_model_scorer
from app.services.virtual_key_service import (
    VirtualKeyNotFoundError,
    VirtualKeyService,
    get_virtual_key_service,
)

router = APIRouter()


@router.post(
    "",
    response_model=VirtualKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new virtual API key",
)
async def create_virtual_key(
    payload: VirtualKeyCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    key_service: Annotated[VirtualKeyService, Depends(get_virtual_key_service)],
) -> VirtualKeyCreateResponse:
    """Generate a new virtual API key for external client access.

    Returns the plaintext key only once in the response.
    """
    key_record, raw_key = await key_service.create_key(
        db=db,
        user=user,
        name=payload.name,
        expires_at=payload.expires_at,
        permissions=payload.permissions,
    )
    return VirtualKeyCreateResponse(
        id=key_record.id,
        name=key_record.name,
        key_prefix=key_record.key_prefix,
        key=raw_key,
        permissions=key_record.permissions,
        is_active=key_record.is_active,
        expires_at=key_record.expires_at,
        created_at=key_record.created_at,
    )


@router.get(
    "",
    response_model=VirtualKeyListResponse,
    summary="List all virtual API keys for user",
)
async def list_virtual_keys(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    key_service: Annotated[VirtualKeyService, Depends(get_virtual_key_service)],
) -> VirtualKeyListResponse:
    """List all virtual API keys belonging to the authenticated user."""
    keys = await key_service.list_keys(db=db, user=user)
    return VirtualKeyListResponse(keys=[VirtualKeyRead.model_validate(k) for k in keys])


@router.get(
    "/{key_id}",
    response_model=VirtualKeyRead,
    summary="Get metadata for a virtual API key",
)
async def get_virtual_key(
    key_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    key_service: Annotated[VirtualKeyService, Depends(get_virtual_key_service)],
) -> VirtualKeyRead:
    """Retrieve metadata for a specific virtual key with ownership verification."""
    try:
        key_record = await key_service.get_key(db=db, user=user, key_id=key_id)
        return VirtualKeyRead.model_validate(key_record)
    except VirtualKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc


@router.delete(
    "/{key_id}",
    response_model=VirtualKeyRead,
    summary="Revoke a virtual API key",
)
async def revoke_virtual_key(
    key_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    key_service: Annotated[VirtualKeyService, Depends(get_virtual_key_service)],
) -> VirtualKeyRead:
    """Revoke a virtual API key. Revoked keys immediately fail authentication."""
    try:
        revoked_key = await key_service.revoke_key(db=db, user=user, key_id=key_id)
        return VirtualKeyRead.model_validate(revoked_key)
    except VirtualKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc


@router.post(
    "/{key_id}/rotate",
    response_model=VirtualKeyCreateResponse,
    summary="Rotate a virtual API key",
)
async def rotate_virtual_key(
    key_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    key_service: Annotated[VirtualKeyService, Depends(get_virtual_key_service)],
) -> VirtualKeyCreateResponse:
    """Rotate secret entropy for an existing virtual key.

    Returns the new plaintext key once. Previous key credentials immediately become invalid.
    """
    try:
        key_record, new_raw_key = await key_service.rotate_key(
            db=db, user=user, key_id=key_id
        )
        return VirtualKeyCreateResponse(
            id=key_record.id,
            name=key_record.name,
            key_prefix=key_record.key_prefix,
            key=new_raw_key,
            permissions=key_record.permissions,
            is_active=key_record.is_active,
            expires_at=key_record.expires_at,
            created_at=key_record.created_at,
        )
    except VirtualKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc


@router.get(
    "/{key_id}/routing",
    response_model=RoutingPolicyRead,
    summary="Get routing policy for a virtual API key",
)
async def get_virtual_key_routing_policy(
    key_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    key_service: Annotated[VirtualKeyService, Depends(get_virtual_key_service)],
    routing_engine: Annotated[RoutingEngine, Depends(get_routing_engine)],
) -> RoutingPolicyRead:
    """Retrieve the routing policy configured for a virtual API key with ownership verification."""
    try:
        key_record = await key_service.get_key(db=db, user=user, key_id=key_id)
    except VirtualKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc

    policy = await routing_engine.get_or_create_policy(db, key_record, user)
    return RoutingPolicyRead.model_validate(policy)


@router.put(
    "/{key_id}/routing",
    response_model=RoutingPolicyRead,
    summary="Update routing policy for a virtual API key",
)
async def update_virtual_key_routing_policy(
    key_id: uuid.UUID,
    payload: RoutingPolicyUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    key_service: Annotated[VirtualKeyService, Depends(get_virtual_key_service)],
    routing_engine: Annotated[RoutingEngine, Depends(get_routing_engine)],
) -> RoutingPolicyRead:
    """Update configuration, priority weights, modality profiles, or credential strategy for a key's policy."""
    try:
        key_record = await key_service.get_key(db=db, user=user, key_id=key_id)
    except VirtualKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc

    policy = await routing_engine.get_or_create_policy(db, key_record, user)

    # 1. Validate preset & mode
    if payload.routing_preset is not None:
        try:
            preset_enum = RoutingPreset(payload.routing_preset)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid routing preset '{payload.routing_preset}'.",
            ) from exc
        policy.routing_preset = preset_enum.value

    if payload.routing_mode is not None:
        if payload.routing_mode not in ("preset", "custom"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Routing mode must be 'preset' or 'custom'.",
            )
        policy.routing_mode = payload.routing_mode

    # 2. Priority Weights handling
    has_custom_weights = any(
        w is not None
        for w in (
            payload.quality_weight,
            payload.speed_weight,
            payload.availability_weight,
            payload.cost_weight,
        )
    )
    if has_custom_weights:
        q = (
            payload.quality_weight
            if payload.quality_weight is not None
            else float(policy.quality_weight)
        )
        s = (
            payload.speed_weight
            if payload.speed_weight is not None
            else float(policy.speed_weight)
        )
        a = (
            payload.availability_weight
            if payload.availability_weight is not None
            else float(policy.availability_weight)
        )
        c = (
            payload.cost_weight
            if payload.cost_weight is not None
            else float(policy.cost_weight)
        )
        try:
            normalized = validate_and_normalize_weights(
                quality=q, speed=s, availability=a, cost=c
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        policy.quality_weight = Decimal(str(normalized["quality"]))
        policy.speed_weight = Decimal(str(normalized["speed"]))
        policy.availability_weight = Decimal(str(normalized["availability"]))
        policy.cost_weight = Decimal(str(normalized["cost"]))
        policy.routing_mode = "custom"
        policy.routing_preset = RoutingPreset.CUSTOM.value
    elif (
        payload.routing_preset is not None
        and payload.routing_preset != RoutingPreset.CUSTOM.value
    ):
        pw = get_preset_weights(payload.routing_preset)
        policy.quality_weight = Decimal(str(pw["quality"]))
        policy.speed_weight = Decimal(str(pw["speed"]))
        policy.availability_weight = Decimal(str(pw["availability"]))
        policy.cost_weight = Decimal(str(pw["cost"]))

    # 3. Model access profile validation
    if payload.model_access_profile is not None:
        try:
            access_enum = ModelAccessProfile(payload.model_access_profile)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid model access profile '{payload.model_access_profile}'.",
            ) from exc
        policy.model_access_profile = access_enum.value

    # 4. Modality, Provider, Model whitelists/blacklists
    if payload.required_capabilities is not None:
        policy.required_capabilities = payload.required_capabilities
    if payload.allowed_providers is not None:
        policy.allowed_providers = payload.allowed_providers
    if payload.excluded_providers is not None:
        policy.excluded_providers = payload.excluded_providers
    if payload.allowed_models is not None:
        policy.allowed_models = payload.allowed_models
    if payload.excluded_models is not None:
        policy.excluded_models = payload.excluded_models
    if payload.preferred_provider is not None:
        policy.preferred_provider = payload.preferred_provider

    # 5. Preferred credential ownership verification
    if payload.preferred_credential_id is not None:
        cred_check = await db.execute(
            select(ProviderCredential).where(
                ProviderCredential.id == payload.preferred_credential_id,
                ProviderCredential.user_id == user.id,
            )
        )
        if not cred_check.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Preferred credential '{payload.preferred_credential_id}' not found or not owned by user.",
            )
        policy.preferred_credential_id = payload.preferred_credential_id

    if payload.minimum_context_window is not None:
        policy.minimum_context_window = payload.minimum_context_window
    if payload.maximum_cost_per_request is not None:
        policy.maximum_cost_per_request = Decimal(str(payload.maximum_cost_per_request))

    if payload.credential_selection_strategy is not None:
        policy.credential_selection_strategy = payload.credential_selection_strategy

    await db.commit()
    await db.refresh(policy)
    return RoutingPolicyRead.model_validate(policy)


@router.post(
    "/{key_id}/routing/preview",
    response_model=RoutingPreviewResponse,
    summary="Preview ranked candidate models without persisting changes",
)
async def preview_routing(
    key_id: uuid.UUID,
    payload: RoutingPreviewRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    key_service: Annotated[VirtualKeyService, Depends(get_virtual_key_service)],
    routing_engine: Annotated[RoutingEngine, Depends(get_routing_engine)],
    discovery_service: Annotated[
        CandidateDiscoveryService, Depends(get_candidate_discovery_service)
    ],
    scorer: Annotated[ModelScorer, Depends(get_model_scorer)],
    metrics_service: Annotated[
        RoutingMetricsService, Depends(get_routing_metrics_service)
    ],
) -> RoutingPreviewResponse:
    """Non-persistent snapshot preview showing how current or proposed routing policy scores and ranks candidate models."""
    try:
        key_record = await key_service.get_key(db=db, user=user, key_id=key_id)
    except VirtualKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        ) from exc

    current_policy = await routing_engine.get_or_create_policy(db, key_record, user)

    # In-memory simulated policy with hypothetical overrides applied
    sim_policy = VirtualKeyRoutingPolicy(
        virtual_api_key_id=key_record.id,
        user_id=user.id,
        routing_mode=current_policy.routing_mode,
        routing_preset=current_policy.routing_preset,
        quality_weight=current_policy.quality_weight,
        speed_weight=current_policy.speed_weight,
        availability_weight=current_policy.availability_weight,
        cost_weight=current_policy.cost_weight,
        model_access_profile=current_policy.model_access_profile,
        required_capabilities=list(current_policy.required_capabilities or []),
        allowed_providers=list(current_policy.allowed_providers or []),
        excluded_providers=list(current_policy.excluded_providers or []),
        allowed_models=list(current_policy.allowed_models or []),
        excluded_models=list(current_policy.excluded_models or []),
        preferred_provider=current_policy.preferred_provider,
        preferred_credential_id=current_policy.preferred_credential_id,
        minimum_context_window=current_policy.minimum_context_window,
        maximum_cost_per_request=current_policy.maximum_cost_per_request,
        credential_selection_strategy=current_policy.credential_selection_strategy,
    )

    if payload.policy_overrides:
        ov = payload.policy_overrides
        if ov.routing_mode is not None:
            sim_policy.routing_mode = ov.routing_mode
        if ov.routing_preset is not None:
            sim_policy.routing_preset = ov.routing_preset
            if (
                ov.routing_preset != RoutingPreset.CUSTOM.value
                and ov.quality_weight is None
            ):
                pw = get_preset_weights(ov.routing_preset)
                sim_policy.quality_weight = Decimal(str(pw["quality"]))
                sim_policy.speed_weight = Decimal(str(pw["speed"]))
                sim_policy.availability_weight = Decimal(str(pw["availability"]))
                sim_policy.cost_weight = Decimal(str(pw["cost"]))
        if ov.quality_weight is not None:
            sim_policy.quality_weight = Decimal(str(ov.quality_weight))
        if ov.speed_weight is not None:
            sim_policy.speed_weight = Decimal(str(ov.speed_weight))
        if ov.availability_weight is not None:
            sim_policy.availability_weight = Decimal(str(ov.availability_weight))
        if ov.cost_weight is not None:
            sim_policy.cost_weight = Decimal(str(ov.cost_weight))
        if ov.model_access_profile is not None:
            sim_policy.model_access_profile = ov.model_access_profile
        if ov.required_capabilities is not None:
            sim_policy.required_capabilities = ov.required_capabilities
        if ov.allowed_providers is not None:
            sim_policy.allowed_providers = ov.allowed_providers
        if ov.excluded_providers is not None:
            sim_policy.excluded_providers = ov.excluded_providers
        if ov.allowed_models is not None:
            sim_policy.allowed_models = ov.allowed_models
        if ov.excluded_models is not None:
            sim_policy.excluded_models = ov.excluded_models
        if ov.preferred_provider is not None:
            sim_policy.preferred_provider = ov.preferred_provider
        if ov.preferred_credential_id is not None:
            sim_policy.preferred_credential_id = ov.preferred_credential_id
        if ov.minimum_context_window is not None:
            sim_policy.minimum_context_window = ov.minimum_context_window
        if ov.maximum_cost_per_request is not None:
            sim_policy.maximum_cost_per_request = Decimal(
                str(ov.maximum_cost_per_request)
            )
        if ov.credential_selection_strategy is not None:
            sim_policy.credential_selection_strategy = ov.credential_selection_strategy

    raw_model = payload.model.strip()
    clean_model = raw_model.lower()
    is_explicit = ":" in raw_model

    valid_aliases = {"auto", "fast", "smart", "cheap"}
    if is_explicit:
        parts = raw_model.split(":", 1)
        exp_provider = parts[0].strip().lower()
        exp_model_id = parts[1].strip()
        alias = None
    elif clean_model in valid_aliases:
        exp_provider = None
        exp_model_id = None
        alias = clean_model
    else:
        is_explicit = True
        exp_provider = None
        exp_model_id = raw_model
        alias = None

    ctx = RoutingContext(
        user=user,
        key=key_record,
        policy=sim_policy,
        requested_model=payload.model,
        is_explicit=is_explicit,
        explicit_provider=exp_provider,
        explicit_provider_model_id=exp_model_id,
        alias=alias,
        requires_streaming=payload.stream,
        requires_tools=bool(payload.tools),
        requires_vision=False,
        requires_structured_output=False,
        estimated_input_tokens=payload.estimated_tokens,
    )

    discovery = await discovery_service.discover_candidates(db, ctx)
    metrics_map = await metrics_service.get_metrics_for_candidates(db, user.id)

    weights = scorer.resolve_effective_weights(
        routing_mode=sim_policy.routing_mode,
        routing_preset=sim_policy.routing_preset,
        quality_weight=sim_policy.quality_weight,
        speed_weight=sim_policy.speed_weight,
        availability_weight=sim_policy.availability_weight,
        cost_weight=sim_policy.cost_weight,
        alias_override=ctx.alias,
    )

    ranked_items: list[CandidatePreviewItem] = []
    all_missing: set[str] = set()
    overall_confidence = "none"

    if discovery.eligible:
        ranked = scorer.rank_candidates(discovery.eligible, metrics_map, weights)
        for idx, rc in enumerate(ranked, start=1):
            cand = rc.candidate
            m = metrics_map.get(
                (cand.provider, cand.provider_model_id, cand.credential_id)
            )
            if m is None:
                m = metrics_map.get((cand.provider, cand.provider_model_id, None))
            lat = m.avg_latency_ms if m else None
            all_missing.update(rc.score_breakdown.missing_measurements)
            if rc.score_breakdown.data_confidence != "none":
                overall_confidence = rc.score_breakdown.data_confidence

            item = CandidatePreviewItem(
                rank=idx,
                provider=cand.provider,
                provider_model_id=cand.provider_model_id,
                gateway_model_id=cand.gateway_model_id,
                canonical_name=cand.canonical_name,
                credential_id=cand.credential_id,
                credential_display_name=cand.credential_display_name,
                score=rc.score_breakdown.final_score,
                score_breakdown=rc.score_breakdown.to_dict(),
                observed_latency_ms=lat,
                input_price_per_million=float(cand.input_price_per_million)
                if cand.input_price_per_million is not None
                else None,
                output_price_per_million=float(cand.output_price_per_million)
                if cand.output_price_per_million is not None
                else None,
                context_window=cand.context_window,
                supports_streaming=cand.supports_streaming,
                supports_tools=cand.supports_tools,
                supports_vision=cand.supports_vision,
                supports_reasoning=cand.supports_reasoning,
            )
            ranked_items.append(item)

    selected_preview = None
    if ranked_items and ranked:
        top_provider = ranked[0].candidate.provider
        top_model_id = ranked[0].candidate.provider_model_id
        top_model_candidates = [
            rc.candidate
            for rc in ranked
            if rc.candidate.provider == top_provider
            and rc.candidate.provider_model_id == top_model_id
        ]
        strategy = routing_engine.credential_pool.get_strategy(
            sim_policy.credential_selection_strategy
        )
        selected_cand, _ = await strategy.select_candidate(
            db=db,
            candidates=top_model_candidates,
            policy=sim_policy,
            metrics_map=metrics_map,
        )
        for item in ranked_items:
            if (
                item.provider == selected_cand.provider
                and item.provider_model_id == selected_cand.provider_model_id
                and item.credential_id == selected_cand.credential_id
            ):
                selected_preview = item
                break
        if selected_preview is None:
            selected_preview = ranked_items[0]

    selected_strategy = str(sim_policy.credential_selection_strategy)
    response = RoutingPreviewResponse(
        virtual_api_key_id=key_id,
        selected_candidate=selected_preview,
        ranked_candidates=ranked_items,
        excluded_candidates=discovery.excluded,
        effective_weights=weights,
        data_confidence=overall_confidence,
        missing_measurements=sorted(all_missing),
        selection_strategy=selected_strategy,
    )

    # Ensure snapshot preview never leaves uncommitted state changes in session
    await db.rollback()
    return response
