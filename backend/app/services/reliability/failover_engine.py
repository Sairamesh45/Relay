"""3-Level Automatic Failover & Execution Engine.

Consumes ranked candidate offering pipeline, implements strict 3-level failover hierarchy:
  Level 1: Same model, different credential
  Level 2: Different compatible model, same provider
  Level 3: Different compatible model, different provider
Enforces capability matching, policy constraints, health & cooldown gating, circuit breakers,
retry budgets, total deadlines, and streaming failure semantics.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gateway_errors import (
    openai_model_not_found_error,
    openai_provider_error,
)
from app.models.routing_decision_log import RoutingDecisionLog
from app.models.routing_policy import VirtualKeyRoutingPolicy
from app.models.user import User
from app.models.virtual_api_key import VirtualAPIKey
from app.providers.manager import ProviderManager, get_provider_manager
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
)
from app.services.gateway_usage import GatewayUsageService, get_gateway_usage_service
from app.services.reliability.circuit_breaker import (
    CircuitBreakerEngine,
    get_circuit_breaker_engine,
)
from app.services.reliability.cooldown_manager import (
    CooldownManager,
    get_cooldown_manager,
)
from app.services.reliability.error_classifier import (
    ClassifiedError,
    ErrorCategory,
    classify_provider_error,
)
from app.services.reliability.event_recorder import (
    EventRecorder,
    get_event_recorder,
)
from app.services.reliability.health_service import (
    HealthService,
    get_health_service,
)
from app.services.reliability.quota_service import (
    QuotaService,
    get_quota_service,
)
from app.services.reliability.retry_policy import (
    AttemptRecord,
    ExecutionTrace,
    RetryBudgetEnforcer,
    RetryPolicy,
    get_retry_budget_enforcer,
)
from app.services.routing.candidates import Candidate
from app.services.routing.context import RoutingContext
from app.services.routing.credential_pool import (
    CredentialPoolManager,
    get_credential_pool_manager,
)
from app.services.routing.engine import RoutingEngine, get_routing_engine
from app.services.routing.scoring import ScoredCandidate

logger = logging.getLogger(__name__)


class FailoverExecutionEngine:
    """Executes chat requests with automatic 3-level failover, health checks, and circuit breaking."""

    def __init__(
        self,
        routing_engine: RoutingEngine | None = None,
        provider_manager: ProviderManager | None = None,
        health_service: HealthService | None = None,
        cooldown_manager: CooldownManager | None = None,
        circuit_breaker: CircuitBreakerEngine | None = None,
        credential_pool: CredentialPoolManager | None = None,
        event_recorder: EventRecorder | None = None,
        quota_service: QuotaService | None = None,
        retry_budget_enforcer: RetryBudgetEnforcer | None = None,
        usage_service: GatewayUsageService | None = None,
    ) -> None:
        self.routing_engine = routing_engine or get_routing_engine()
        self.provider_manager = provider_manager or get_provider_manager()
        self.cooldown_manager = cooldown_manager or get_cooldown_manager()
        self.health_service = health_service or get_health_service()
        self.circuit_breaker = circuit_breaker or get_circuit_breaker_engine()
        self.credential_pool = credential_pool or get_credential_pool_manager()
        self.event_recorder = event_recorder or get_event_recorder()
        self.quota_service = quota_service or get_quota_service()
        self.retry_budget_enforcer = (
            retry_budget_enforcer or get_retry_budget_enforcer()
        )
        self.usage_service = usage_service or get_gateway_usage_service()

    async def _reserve_candidate_probe(
        self,
        db: AsyncSession | None,
        candidate: Candidate,
    ) -> bool:
        """Reserve a probe for candidate scopes if in HALF_OPEN (or eligible OPEN).

        Atomically checks all relevant scopes. If any scope denies the probe,
        releases any previously reserved probes in this check and returns False.
        """
        if not hasattr(self.circuit_breaker, "allow_request"):
            return True

        scopes: list[tuple[str, str]] = []
        if candidate.provider_model_id:
            scopes.append(
                ("model", f"{candidate.provider}:{candidate.provider_model_id}")
            )
        if candidate.credential_id:
            scopes.append(("credential", str(candidate.credential_id)))
        if candidate.provider:
            scopes.append(("provider", candidate.provider.lower().strip()))

        reserved_scopes: list[tuple[str, str]] = []
        for s_type, s_id in scopes:
            try:
                allowed = await self.circuit_breaker.allow_request(
                    db=db,
                    scope_type=s_type,
                    scope_id=s_id,
                    provider=candidate.provider,
                )
            except Exception as e:
                logger.warning(
                    "Error checking circuit breaker for %s/%s: %s", s_type, s_id, e
                )
                allowed = True

            if not allowed:
                # Release any probes that were reserved in this candidate evaluation
                for r_type, r_id in reserved_scopes:
                    try:
                        await self.circuit_breaker.release_probe(
                            db=db, scope_type=r_type, scope_id=r_id
                        )
                    except Exception:
                        pass
                return False
            reserved_scopes.append((s_type, s_id))

        return True

    def organize_failover_candidates(
        self,
        ranked_candidates: list[ScoredCandidate],
        ctx: RoutingContext,
        policy: VirtualKeyRoutingPolicy,
    ) -> list[tuple[Candidate, int]]:
        """Organize eligible candidates into the 3-level failover hierarchy.

        Returns list of (Candidate, failover_level) ordered by:
          Level 0: Primary top-ranked candidate
          Level 1: Same model, different credential
          Level 2: Different compatible model, same provider
          Level 3: Different compatible model, different provider
        Respects model access policy: if model is pinned/single and request is explicit,
        rejects Level 2 and Level 3 alternatives.
        """
        if not ranked_candidates:
            return []

        primary_scored = ranked_candidates[0]
        primary = primary_scored.candidate

        # Check whether alternative models are permitted
        allow_model_failover = True
        if ctx.is_explicit and not ctx.alias:
            # If user explicitly requested a specific model (e.g. 'groq:llama-3.3-70b-versatile')
            # check policy restrictions
            profile = getattr(policy, "model_access_profile", "all_models")
            if profile in ("single", "pinned"):
                allow_model_failover = False

        level0_cands: list[tuple[Candidate, int]] = [(primary, 0)]
        level1_cands: list[tuple[Candidate, int]] = []
        level2_cands: list[tuple[Candidate, int]] = []
        level3_cands: list[tuple[Candidate, int]] = []

        seen_combinations: set[tuple[str, str, uuid.UUID]] = {
            (primary.provider, primary.provider_model_id, primary.credential_id)
        }

        for sc in ranked_candidates[1:]:
            cand = sc.candidate
            key = (cand.provider, cand.provider_model_id, cand.credential_id)
            if key in seen_combinations:
                continue
            seen_combinations.add(key)

            # Modality and capability verification
            if ctx.requires_streaming and cand.supports_streaming is False:
                continue
            if ctx.requires_tools and cand.supports_tools is False:
                continue
            if ctx.requires_vision and cand.supports_vision is False:
                continue
            if (
                ctx.estimated_input_tokens > 0
                and cand.context_window is not None
                and cand.context_window < ctx.estimated_input_tokens
            ):
                continue

            # Classify into 3 explicit failover levels
            if (
                cand.provider == primary.provider
                and cand.provider_model_id == primary.provider_model_id
                and cand.credential_id != primary.credential_id
            ):
                # Level 1: Same model, different credential
                level1_cands.append((cand, 1))
            elif (
                cand.provider == primary.provider
                and cand.provider_model_id != primary.provider_model_id
            ):
                # Level 2: Different model, same provider
                if allow_model_failover:
                    level2_cands.append((cand, 2))
            elif cand.provider != primary.provider:
                # Level 3: Different model, different provider
                if allow_model_failover:
                    level3_cands.append((cand, 3))

        # Concatenate in strict hierarchical order
        ordered: list[tuple[Candidate, int]] = (
            level0_cands + level1_cands + level2_cands + level3_cands
        )
        return ordered

    async def execute_chat_completion(
        self,
        db: AsyncSession,
        user: User,
        key: VirtualAPIKey,
        request: ChatCompletionRequest,
        request_id: str,
        policy: VirtualKeyRoutingPolicy,
        retry_policy: RetryPolicy | None = None,
    ) -> tuple[ChatCompletionResponse, ExecutionTrace]:
        """Execute non-streaming chat completion with automatic 3-level failover."""
        effective_retry_policy = retry_policy or RetryPolicy()
        start_time = time.perf_counter()

        trace = ExecutionTrace(request_id=request_id)
        self.retry_budget_enforcer.record_request()

        # 1. Discover candidates and evaluate hard constraints
        ctx = RoutingContext.from_request(
            user=user, key=key, policy=policy, request=request
        )
        ranked = await self.routing_engine.get_ranked_candidates(db, ctx)

        if not ranked:
            raise openai_model_not_found_error(model_id=request.model)

        # 2. Organize candidates into 3-level failover hierarchy
        candidate_pipeline = self.organize_failover_candidates(ranked, ctx, policy)
        max_attempts = min(
            effective_retry_policy.max_attempts,
            len(candidate_pipeline),
            effective_retry_policy.max_failover_candidates + 1,
        )

        all_circuits_open = True
        attempt_number = 0
        last_classified_error: ClassifiedError | None = None
        last_error_summary: str | None = None
        last_status_code: int = 502
        last_cand: Candidate | None = None

        for cand, failover_level in candidate_pipeline:
            if attempt_number >= max_attempts:
                break

            # Check total request deadline
            elapsed_total = time.perf_counter() - start_time
            remaining_total_time = effective_retry_policy.total_timeout - elapsed_total
            if remaining_total_time <= 0:
                logger.warning(
                    "Total request deadline (%.1fs) exceeded for %s",
                    effective_retry_policy.total_timeout,
                    request_id,
                )
                break

            # 3. Check Health, Cooldown, and Circuit Breaker
            try:
                health = await self.health_service.get_health(db, cand.credential_id)
            except Exception:
                health = None

            if not self.health_service.is_candidate_eligible(
                health, cand.provider_model_id
            ):
                record = AttemptRecord(
                    attempt_number=attempt_number + 1,
                    candidate_id=f"{cand.provider}:{cand.provider_model_id}:{cand.credential_id}",
                    provider=cand.provider,
                    model_id=cand.provider_model_id,
                    credential_id=cand.credential_id,
                    failover_level=failover_level,
                    status="skipped",
                    error_category="HEALTH_INELIGIBLE",
                    error_message="Candidate credential health state or cooldown is ineligible",
                )
                trace.record_attempt(record)
                continue

            try:
                can_execute = await self.circuit_breaker.can_execute_candidate(
                    db=db,
                    provider=cand.provider,
                    credential_id=cand.credential_id,
                    model_id=cand.provider_model_id,
                )
            except Exception:
                can_execute = True

            if not can_execute:
                record = AttemptRecord(
                    attempt_number=attempt_number + 1,
                    candidate_id=f"{cand.provider}:{cand.provider_model_id}:{cand.credential_id}",
                    provider=cand.provider,
                    model_id=cand.provider_model_id,
                    credential_id=cand.credential_id,
                    failover_level=failover_level,
                    status="skipped",
                    error_category="CIRCUIT_OPEN",
                    error_message="Circuit breaker is OPEN or probe concurrency limit reached",
                )
                trace.record_attempt(record)
                continue

            # At least one candidate circuit is accessible
            all_circuits_open = False
            attempt_number += 1
            last_cand = cand

            # Check retry budget for attempts > 1
            if attempt_number > 1:
                if not self.retry_budget_enforcer.can_retry():
                    logger.warning(
                        "Retry budget depleted, rejecting attempt %d for %s",
                        attempt_number,
                        request_id,
                    )
                    record = AttemptRecord(
                        attempt_number=attempt_number,
                        candidate_id=f"{cand.provider}:{cand.provider_model_id}:{cand.credential_id}",
                        provider=cand.provider,
                        model_id=cand.provider_model_id,
                        credential_id=cand.credential_id,
                        failover_level=failover_level,
                        status="skipped",
                        error_category="BUDGET_DEPLETED",
                        error_message="Retry budget exhausted across rolling window",
                    )
                    trace.record_attempt(record)
                    break
                self.retry_budget_enforcer.record_retry()

            # Reserve probe if candidate is in HALF_OPEN (enforces probe concurrency limit)
            probe_reserved = await self._reserve_candidate_probe(db=db, candidate=cand)
            if not probe_reserved:
                record = AttemptRecord(
                    attempt_number=attempt_number,
                    candidate_id=f"{cand.provider}:{cand.provider_model_id}:{cand.credential_id}",
                    provider=cand.provider,
                    model_id=cand.provider_model_id,
                    credential_id=cand.credential_id,
                    failover_level=failover_level,
                    status="skipped",
                    error_category="CIRCUIT_OPEN",
                    error_message="Circuit breaker probe concurrency limit reached for half-open circuit",
                )
                trace.record_attempt(record)
                continue

            # Record attempt start
            record = AttemptRecord(
                attempt_number=attempt_number,
                candidate_id=f"{cand.provider}:{cand.provider_model_id}:{cand.credential_id}",
                provider=cand.provider,
                model_id=cand.provider_model_id,
                credential_id=cand.credential_id,
                failover_level=failover_level,
                status="executing",
            )
            trace.record_attempt(record)

            attempt_start = time.perf_counter()
            per_attempt_timeout = min(
                effective_retry_policy.per_attempt_timeout,
                remaining_total_time,
            )

            try:
                # Decrypt credential
                raw_key = await self.credential_pool.decrypt_credential(
                    db=db, credential_id=cand.credential_id
                )
                adapter = self.provider_manager.get_provider(cand.provider)

                # Dispatch with timeout
                response = await asyncio.wait_for(
                    adapter.create_chat_completion(
                        api_key=raw_key,
                        request=request,
                        provider_model_id=cand.provider_model_id,
                    ),
                    timeout=per_attempt_timeout,
                )

                latency_ms = (time.perf_counter() - attempt_start) * 1000
                record.finish(
                    status="success",
                    latency_ms=latency_ms,
                    status_code=200,
                )

                # Success state updates
                try:
                    await self.health_service.record_success(
                        db=db,
                        credential_id=cand.credential_id,
                        model_id=cand.provider_model_id,
                    )
                    await self.circuit_breaker.record_candidate_success(
                        db=db,
                        provider=cand.provider,
                        credential_id=cand.credential_id,
                        model_id=cand.provider_model_id,
                    )

                    # Emit failover succeeded event if attempt > 1
                    if attempt_number > 1:
                        await self.event_recorder.record_failover_succeeded(
                            db=db,
                            provider=cand.provider,
                            candidate={
                                "provider": cand.provider,
                                "model_id": cand.provider_model_id,
                                "credential_id": str(cand.credential_id),
                            },
                            attempts=attempt_number,
                            level=failover_level,
                        )

                    # Record gateway usage
                    input_tokens = (
                        response.usage.prompt_tokens if response.usage else None
                    )
                    output_tokens = (
                        response.usage.completion_tokens if response.usage else None
                    )
                    total_tokens = (
                        response.usage.total_tokens if response.usage else None
                    )

                    await self.usage_service.record_request(
                        db=db,
                        user_id=user.id,
                        virtual_api_key_id=key.id,
                        provider_credential_id=cand.credential_id,
                        provider=cand.provider,
                        provider_model_id=cand.provider_model_id,
                        gateway_model_id=cand.gateway_model_id,
                        request_id=request_id,
                        status="success",
                        status_code=200,
                        latency_ms=int((time.perf_counter() - start_time) * 1000),
                        streaming=False,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                    )

                    routing_mode = ctx.alias or (
                        "explicit" if ctx.is_explicit else "auto"
                    )
                    cand_score_map = {
                        (
                            sc.candidate.provider,
                            sc.candidate.provider_model_id,
                            sc.candidate.credential_id,
                        ): (
                            sc.score_breakdown.to_dict()
                            if hasattr(sc.score_breakdown, "to_dict")
                            else sc.score_breakdown
                        )
                        for sc in ranked
                        if getattr(sc, "score_breakdown", None)
                    }
                    candidate_score_breakdown = cand_score_map.get(
                        (cand.provider, cand.provider_model_id, cand.credential_id),
                        (
                            ranked[0].score_breakdown.to_dict()
                            if hasattr(ranked[0].score_breakdown, "to_dict")
                            else ranked[0].score_breakdown
                        )
                        if (ranked and getattr(ranked[0], "score_breakdown", None))
                        else {},
                    )
                    decision_log = RoutingDecisionLog(
                        request_id=request_id,
                        user_id=user.id,
                        virtual_api_key_id=key.id,
                        routing_mode=routing_mode,
                        routing_preset=policy.routing_preset,
                        selected_provider=cand.provider,
                        selected_model=cand.provider_model_id,
                        selected_credential_id=cand.credential_id,
                        candidate_count=len(ranked),
                        selection_strategy=f"failover_level_{failover_level}",
                        score_breakdown=candidate_score_breakdown,
                        explanation=f"Selected candidate at failover level {failover_level} (attempt {attempt_number})",
                        decision_latency_ms=round(
                            (time.perf_counter() - start_time) * 1000, 2
                        ),
                    )
                    db.add(decision_log)
                    await db.commit()
                except Exception as e:
                    logger.warning("Failed to record success state or audit log: %s", e)

                trace.finish(
                    final_status="success",
                    selected_candidate_id=record.candidate_id,
                    failover_level=failover_level,
                )
                return response, trace

            except TimeoutError as exc:
                latency_ms = (time.perf_counter() - attempt_start) * 1000
                classified = classify_provider_error(error=exc, provider=cand.provider)
                last_classified_error = classified
                last_error_summary = (
                    f"Request timed out after {per_attempt_timeout:.1f}s"
                )
                last_status_code = 504

                record.finish(
                    status="timeout",
                    latency_ms=latency_ms,
                    status_code=504,
                    error_category=classified.category.value,
                    error_message=last_error_summary,
                )

                await self.health_service.record_failure(
                    db=db,
                    credential_id=cand.credential_id,
                    error=classified,
                    model_id=cand.provider_model_id,
                )
                await self.circuit_breaker.record_candidate_failure(
                    db=db,
                    provider=cand.provider,
                    credential_id=cand.credential_id,
                    model_id=cand.provider_model_id,
                )
                await self.circuit_breaker.release_candidate_probe(
                    db=db,
                    provider=cand.provider,
                    credential_id=cand.credential_id,
                    model_id=cand.provider_model_id,
                )

            except Exception as exc:
                latency_ms = (time.perf_counter() - attempt_start) * 1000
                classified = classify_provider_error(
                    error=exc,
                    provider=cand.provider,
                    status_code=getattr(exc, "status_code", None),
                )
                last_classified_error = classified
                last_error_summary = classified.message or str(exc)
                last_status_code = classified.status_code or 502

                record.finish(
                    status="failed",
                    latency_ms=latency_ms,
                    status_code=last_status_code,
                    error_category=classified.category.value,
                    error_message=last_error_summary,
                )

                # State machine updates
                try:
                    await self.health_service.record_failure(
                        db=db,
                        credential_id=cand.credential_id,
                        error=classified,
                        model_id=cand.provider_model_id,
                    )
                    await self.circuit_breaker.record_candidate_failure(
                        db=db,
                        provider=cand.provider,
                        credential_id=cand.credential_id,
                        model_id=cand.provider_model_id,
                        is_provider_wide=(
                            classified.category == ErrorCategory.PROVIDER_UNAVAILABLE
                        ),
                    )
                    await self.circuit_breaker.release_candidate_probe(
                        db=db,
                        provider=cand.provider,
                        credential_id=cand.credential_id,
                        model_id=cand.provider_model_id,
                    )

                    # Emit specific events
                    if classified.category == ErrorCategory.RATE_LIMITED:
                        await self.event_recorder.record_rate_limit(
                            db=db,
                            provider=cand.provider,
                            credential_id=cand.credential_id,
                            model_id=cand.provider_model_id,
                            retry_after=classified.retry_after,
                            details={"status_code": last_status_code},
                        )
                    elif classified.category == ErrorCategory.AUTHENTICATION_FAILED:
                        await self.event_recorder.record_auth_failed(
                            db=db,
                            provider=cand.provider,
                            credential_id=cand.credential_id,
                            error_message=last_error_summary,
                        )
                    elif classified.category == ErrorCategory.PROVIDER_UNAVAILABLE:
                        await self.event_recorder.record_provider_unavailable(
                            db=db,
                            provider=cand.provider,
                            credential_id=cand.credential_id,
                            model_id=cand.provider_model_id,
                            status_code=last_status_code,
                            error_message=last_error_summary,
                        )
                except Exception as e:
                    logger.warning(
                        "Failed to record failure state or audit event: %s", e
                    )

                # Non-retryable check: halt immediately on client or auth errors
                if not effective_retry_policy.is_retryable(classified.category):
                    if classified.category == ErrorCategory.QUOTA_EXHAUSTED:
                        logger.info(
                            "Candidate %s quota/credit exhausted; attempting failover to next candidate.",
                            cand.provider,
                        )
                    else:
                        logger.info(
                            "Non-retryable error '%s' encountered; stopping failover pipeline.",
                            classified.category,
                        )
                        break

            # Backoff before next attempt
            if attempt_number < max_attempts:
                backoff = effective_retry_policy.calculate_backoff(attempt_number)
                remaining_total = max(
                    0.0,
                    effective_retry_policy.total_timeout
                    - (time.perf_counter() - start_time),
                )
                sleep_duration = min(backoff, max(0.0, remaining_total - 0.5))
                if sleep_duration > 0:
                    await asyncio.sleep(sleep_duration)

        # 4. Pipeline Exhaustion or Circuit Block
        trace.finish(final_status="failed")

        if all_circuits_open:
            raise openai_provider_error(
                message="All provider circuits are currently open or unavailable.",
                status_code=503,
            )

        if attempt_number > 1:
            await self.event_recorder.record_failover_exhausted(
                db=db,
                provider=last_cand.provider if last_cand else "unknown",
                total_attempts=attempt_number,
                reason=last_error_summary,
            )

        # Record error usage log
        total_latency_ms = int((time.perf_counter() - start_time) * 1000)
        cred_id = last_cand.credential_id if last_cand else uuid.uuid4()
        prov = last_cand.provider if last_cand else "unknown"
        p_model = last_cand.provider_model_id if last_cand else request.model
        g_model = last_cand.gateway_model_id if last_cand else request.model

        await self.usage_service.record_request(
            db=db,
            user_id=user.id,
            virtual_api_key_id=key.id,
            provider_credential_id=cred_id,
            provider=prov,
            provider_model_id=p_model,
            gateway_model_id=g_model,
            request_id=request_id,
            status="error",
            status_code=last_status_code,
            latency_ms=total_latency_ms,
            streaming=False,
            error_code=last_classified_error.category.value
            if last_classified_error
            else "GATEWAY_ERROR",
            error_summary=last_error_summary,
        )

        raise openai_provider_error(
            message=f"Upstream provider error: {last_error_summary}",
            status_code=last_status_code,
        )

    async def execute_stream_chat_completion(
        self,
        db: AsyncSession,
        user: User,
        key: VirtualAPIKey,
        request: ChatCompletionRequest,
        request_id: str,
        policy: VirtualKeyRoutingPolicy,
        retry_policy: RetryPolicy | None = None,
    ) -> AsyncGenerator[str, None]:
        """Execute streaming chat completion with pre-chunk failover and post-chunk terminal SSE semantics."""
        effective_retry_policy = retry_policy or RetryPolicy()
        start_time = time.perf_counter()

        # Rate limiting check
        self.retry_budget_enforcer.record_request()

        ctx = RoutingContext.from_request(
            user=user, key=key, policy=policy, request=request
        )
        ranked = await self.routing_engine.get_ranked_candidates(db, ctx)

        if not ranked:
            raise openai_model_not_found_error(model_id=request.model)

        candidate_pipeline = self.organize_failover_candidates(ranked, ctx, policy)
        max_attempts = min(
            effective_retry_policy.max_attempts,
            len(candidate_pipeline),
            effective_retry_policy.max_failover_candidates + 1,
        )

        all_circuits_open = True
        attempt_number = 0
        first_chunk_yielded = False
        last_classified_error: ClassifiedError | None = None
        last_error_summary: str | None = None
        last_status_code: int = 502
        last_cand: Candidate | None = None

        input_tokens: int | None = None
        output_tokens: int | None = None
        total_tokens: int | None = None

        for cand, failover_level in candidate_pipeline:
            if attempt_number >= max_attempts:
                break

            # If chunks have already started streaming to the client, failover is STRICTLY FORBIDDEN
            if first_chunk_yielded:
                break

            # Check health, cooldown, and circuit breaker
            try:
                health = await self.health_service.get_health(db, cand.credential_id)
            except Exception:
                health = None

            if not self.health_service.is_candidate_eligible(
                health, cand.provider_model_id
            ):
                continue

            try:
                can_execute = await self.circuit_breaker.can_execute_candidate(
                    db=db,
                    provider=cand.provider,
                    credential_id=cand.credential_id,
                    model_id=cand.provider_model_id,
                )
            except Exception:
                can_execute = True

            if not can_execute:
                continue

            all_circuits_open = False
            attempt_number += 1
            last_cand = cand

            if attempt_number > 1:
                if not self.retry_budget_enforcer.can_retry():
                    break
                self.retry_budget_enforcer.record_retry()

            # Reserve probe if candidate has half-open circuit scopes
            probe_reserved = await self._reserve_candidate_probe(db=db, candidate=cand)
            if not probe_reserved:
                continue

            cand_probe_reserved = True
            stream_completed = False
            usage_recorded = False

            try:
                raw_key = await self.credential_pool.decrypt_credential(
                    db=db, credential_id=cand.credential_id
                )
                adapter = self.provider_manager.get_provider(cand.provider)

                stream_generator = adapter.stream_chat_completion(
                    api_key=raw_key,
                    request=request,
                    provider_model_id=cand.provider_model_id,
                )

                async for chunk in stream_generator:
                    if not first_chunk_yielded:
                        first_chunk_yielded = True
                        # Chunk 1 yielded! Failover window is now CLOSED.
                        if attempt_number > 1:
                            await self.event_recorder.record_failover_succeeded(
                                db=db,
                                provider=cand.provider,
                                candidate={
                                    "provider": cand.provider,
                                    "model_id": cand.provider_model_id,
                                    "credential_id": str(cand.credential_id),
                                },
                                attempts=attempt_number,
                                level=failover_level,
                            )

                    if chunk.usage:
                        input_tokens = chunk.usage.prompt_tokens
                        output_tokens = chunk.usage.completion_tokens
                        total_tokens = chunk.usage.total_tokens

                    yield f"data: {chunk.model_dump_json()}\n\n"

                # Successful complete stream
                yield "data: [DONE]\n\n"

                # Success state updates
                try:
                    await self.health_service.record_success(
                        db=db,
                        credential_id=cand.credential_id,
                        model_id=cand.provider_model_id,
                    )
                    await self.circuit_breaker.record_candidate_success(
                        db=db,
                        provider=cand.provider,
                        credential_id=cand.credential_id,
                        model_id=cand.provider_model_id,
                    )

                    await self.usage_service.record_request(
                        db=db,
                        user_id=user.id,
                        virtual_api_key_id=key.id,
                        provider_credential_id=cand.credential_id,
                        provider=cand.provider,
                        provider_model_id=cand.provider_model_id,
                        gateway_model_id=cand.gateway_model_id,
                        request_id=request_id,
                        status="success",
                        status_code=200,
                        latency_ms=int((time.perf_counter() - start_time) * 1000),
                        streaming=True,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total_tokens,
                    )

                    routing_mode = ctx.alias or (
                        "explicit" if ctx.is_explicit else "auto"
                    )
                    cand_score_map = {
                        (
                            sc.candidate.provider,
                            sc.candidate.provider_model_id,
                            sc.candidate.credential_id,
                        ): (
                            sc.score_breakdown.to_dict()
                            if hasattr(sc.score_breakdown, "to_dict")
                            else sc.score_breakdown
                        )
                        for sc in ranked
                        if getattr(sc, "score_breakdown", None)
                    }
                    candidate_score_breakdown = cand_score_map.get(
                        (cand.provider, cand.provider_model_id, cand.credential_id),
                        (
                            ranked[0].score_breakdown.to_dict()
                            if hasattr(ranked[0].score_breakdown, "to_dict")
                            else ranked[0].score_breakdown
                        )
                        if (ranked and getattr(ranked[0], "score_breakdown", None))
                        else {},
                    )
                    decision_log = RoutingDecisionLog(
                        request_id=request_id,
                        user_id=user.id,
                        virtual_api_key_id=key.id,
                        routing_mode=routing_mode,
                        routing_preset=policy.routing_preset,
                        selected_provider=cand.provider,
                        selected_model=cand.provider_model_id,
                        selected_credential_id=cand.credential_id,
                        candidate_count=len(ranked),
                        selection_strategy=f"failover_level_{failover_level}",
                        score_breakdown=candidate_score_breakdown,
                        explanation=f"Selected candidate at failover level {failover_level} (attempt {attempt_number})",
                        decision_latency_ms=round(
                            (time.perf_counter() - start_time) * 1000, 2
                        ),
                    )
                    db.add(decision_log)
                    await db.commit()
                except Exception as e:
                    logger.warning(
                        "Failed to record streaming success state or audit log: %s", e
                    )

                stream_completed = True
                usage_recorded = True
                return

            except (asyncio.CancelledError, GeneratorExit):
                logger.info(
                    "Streaming request %s cancelled or closed mid-stream (first_chunk_yielded=%s)",
                    request_id,
                    first_chunk_yielded,
                )
                raise

            except Exception as exc:
                classified = classify_provider_error(
                    error=exc,
                    provider=cand.provider,
                    status_code=getattr(exc, "status_code", None),
                )
                last_classified_error = classified
                last_error_summary = classified.message or str(exc)
                last_status_code = classified.status_code or 502

                try:
                    await self.health_service.record_failure(
                        db=db,
                        credential_id=cand.credential_id,
                        error=classified,
                        model_id=cand.provider_model_id,
                    )
                    await self.circuit_breaker.record_candidate_failure(
                        db=db,
                        provider=cand.provider,
                        credential_id=cand.credential_id,
                        model_id=cand.provider_model_id,
                        is_provider_wide=(
                            classified.category == ErrorCategory.PROVIDER_UNAVAILABLE
                        ),
                    )
                    await self.circuit_breaker.release_candidate_probe(
                        db=db,
                        provider=cand.provider,
                        credential_id=cand.credential_id,
                        model_id=cand.provider_model_id,
                    )
                except Exception as e:
                    logger.warning("Failed to record streaming failure state: %s", e)

                if first_chunk_yielded:
                    # Post-First-Chunk failure: never restart with a different model.
                    # Yield terminal normalized SSE error event
                    logger.error(
                        "Streaming interrupted post-first-chunk for provider %s: %s",
                        cand.provider,
                        last_error_summary,
                    )
                    error_payload = {
                        "error": {
                            "message": f"Upstream stream interrupted: {last_error_summary}",
                            "type": "stream_error",
                            "code": "stream_interrupted",
                        }
                    }
                    yield f"data: {json.dumps(error_payload)}\n\n"
                    yield "data: [DONE]\n\n"

                    # Record partial stream audit log
                    try:
                        await self.usage_service.record_request(
                            db=db,
                            user_id=user.id,
                            virtual_api_key_id=key.id,
                            provider_credential_id=cand.credential_id,
                            provider=cand.provider,
                            provider_model_id=cand.provider_model_id,
                            gateway_model_id=cand.gateway_model_id,
                            request_id=request_id,
                            status="partial_error",
                            status_code=last_status_code,
                            latency_ms=int((time.perf_counter() - start_time) * 1000),
                            streaming=True,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            total_tokens=total_tokens,
                            error_code="STREAM_INTERRUPTED",
                            error_summary=last_error_summary,
                        )
                        usage_recorded = True
                    except Exception as e:
                        logger.warning(
                            "Failed to record streaming partial error usage: %s", e
                        )
                    return

                # Pre-first-chunk failure: safe failover window!
                logger.info(
                    "Pre-chunk failure on %s (%s). Attempting safe failover to next candidate.",
                    cand.provider,
                    last_error_summary,
                )

                if not effective_retry_policy.is_retryable(classified.category):
                    if classified.category == ErrorCategory.QUOTA_EXHAUSTED:
                        logger.info(
                            "Pre-chunk quota exhausted on %s; attempting failover to next candidate.",
                            cand.provider,
                        )
                    else:
                        break

            finally:
                if cand_probe_reserved and not stream_completed:
                    try:
                        await self.circuit_breaker.release_candidate_probe(
                            db=db,
                            provider=cand.provider,
                            credential_id=cand.credential_id,
                            model_id=cand.provider_model_id,
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to release candidate probe in finally: %s", e
                        )

                if first_chunk_yielded and not usage_recorded:
                    try:
                        await self.usage_service.record_request(
                            db=db,
                            user_id=user.id,
                            virtual_api_key_id=key.id,
                            provider_credential_id=cand.credential_id,
                            provider=cand.provider,
                            provider_model_id=cand.provider_model_id,
                            gateway_model_id=cand.gateway_model_id,
                            request_id=request_id,
                            status="cancelled",
                            status_code=499,
                            latency_ms=int((time.perf_counter() - start_time) * 1000),
                            streaming=True,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            total_tokens=total_tokens,
                            error_code="CLIENT_CANCELLED",
                            error_summary="Client cancelled or disconnected mid-stream",
                        )
                        usage_recorded = True
                    except Exception as e:
                        logger.warning(
                            "Failed to record cancelled stream usage in finally: %s", e
                        )

        # If we reach here without yielding any chunks, emit terminal SSE error event
        if last_classified_error:
            logger.info(
                "Streaming terminated with classified error %s for provider %s",
                last_classified_error.category,
                last_cand.provider if last_cand else "unknown",
            )

        err_msg = (
            "All provider circuits are currently open or unavailable."
            if all_circuits_open
            else f"Upstream provider streaming error: {last_error_summary}"
        )
        status_c = 503 if all_circuits_open else last_status_code
        error_payload = {
            "error": {
                "message": err_msg,
                "type": "stream_error",
                "code": (
                    last_classified_error.category.value
                    if last_classified_error
                    else "provider_error"
                ),
                "status_code": status_c,
            }
        }
        yield f"data: {json.dumps(error_payload)}\n\n"
        yield "data: [DONE]\n\n"
        return


# Singleton instance
_failover_engine: FailoverExecutionEngine | None = None


def get_failover_engine() -> FailoverExecutionEngine:
    """Dependency getter for FailoverExecutionEngine."""
    global _failover_engine
    if _failover_engine is None:
        _failover_engine = FailoverExecutionEngine()
    return _failover_engine
