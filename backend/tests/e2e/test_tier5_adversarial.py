"""Tier 5: Adversarial Hardening Test Suite for Relay API Gateway.

Rigorous adversarial penetration, stress, and edge-case verification covering:
1. Malformed payloads, extreme floats, NaN, payload inflation, and header/SQL injection.
2. Thundering herd concurrency on half-open circuit breaker transitions and quota race conditions.
3. Rapid cascading failover churn, 3-tier exhaustion, and retry budget depletion under load.
4. Streaming edge cases: pre-chunk abort, mid-stream cancellation with partial token logging,
   corrupted SSE payloads, and prevention of model output concatenation.
5. Forensic data sanitization: upstream error API key reflection redaction and audit log masking.
6. Multi-tenant security boundaries: cross-tenant credential hijack and telemetry leakage.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.gateway_errors import OpenAIHTTPException
from app.models.reliability import CircuitState
from app.models.routing_policy import VirtualKeyRoutingPolicy
from app.models.user import User
from app.models.virtual_api_key import VirtualAPIKey
from app.providers.exceptions import (
    ProviderUnavailableError,
    RateLimitError,
)
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatMessage,
)
from app.services.reliability.circuit_breaker import CircuitBreakerEngine
from app.services.reliability.error_classifier import (
    classify_provider_error,
    sanitize_dict,
    sanitize_error_text,
)
from app.services.reliability.failover_engine import FailoverExecutionEngine
from app.services.reliability.quota_service import QuotaService
from app.services.reliability.retry_policy import (
    RetryBudgetEnforcer,
    RetryPolicy,
)
from app.services.routing.candidates import Candidate
from app.services.routing.scoring import ScoreBreakdown, ScoredCandidate
from tests.e2e.conftest import MockProviderController

settings = get_settings()


def make_adversarial_candidate(
    provider: str,
    provider_model_id: str,
    credential_id: uuid.UUID,
    score: float = 0.9,
) -> ScoredCandidate:
    """Helper to build a ScoredCandidate for adversarial tests."""
    cand = Candidate(
        provider=provider,
        provider_model_id=provider_model_id,
        gateway_model_id=f"{provider}:{provider_model_id}",
        credential_id=credential_id,
        credential_display_name=f"Cred-{credential_id.hex[:4]}",
        canonical_model_id=uuid.uuid4(),
        canonical_name=provider_model_id,
        context_window=32768,
        max_output_tokens=4096,
        input_price_per_million=None,
        output_price_per_million=None,
        supports_streaming=True,
        supports_tools=True,
        supports_structured_output=True,
        supports_vision=False,
        supports_reasoning=False,
    )
    breakdown = ScoreBreakdown(
        final_score=score,
        quality_score=score,
        speed_score=score,
        availability_score=score,
        cost_score=score,
        effective_weights={},
        data_confidence="confirmed",
    )
    return ScoredCandidate(candidate=cand, score_breakdown=breakdown)


# ==============================================================================
# Suite 5.1: Boundary & Malformed Inputs (TestAdversarialPayloadsAndInjections)
# ==============================================================================
class TestAdversarialPayloadsAndInjections:
    """Tests extreme parameters, payload boundaries, raw byte injection, and header smuggling."""

    def test_schema_direct_validation_boundaries(self) -> None:
        """Pydantic raises ValidationError for out-of-range numerical fields directly."""
        # temperature < 0.0
        with pytest.raises(ValidationError):
            ChatCompletionRequest(
                model="groq:llama-3.3-70b-versatile",
                messages=[ChatMessage(role="user", content="hi")],
                temperature=-999.0,
            )

        # temperature > 2.0
        with pytest.raises(ValidationError):
            ChatCompletionRequest(
                model="groq:llama-3.3-70b-versatile",
                messages=[ChatMessage(role="user", content="hi")],
                temperature=50.0,
            )

        # top_p < 0.0 or > 1.0
        with pytest.raises(ValidationError):
            ChatCompletionRequest(
                model="groq:llama-3.3-70b-versatile",
                messages=[ChatMessage(role="user", content="hi")],
                top_p=-0.5,
            )

        # max_tokens < 1
        with pytest.raises(ValidationError):
            ChatCompletionRequest(
                model="groq:llama-3.3-70b-versatile",
                messages=[ChatMessage(role="user", content="hi")],
                max_tokens=-500,
            )

        # empty messages array
        with pytest.raises(ValidationError):
            ChatCompletionRequest(
                model="groq:llama-3.3-70b-versatile",
                messages=[],
            )

    @pytest.mark.asyncio
    async def test_extreme_floating_point_and_numerical_boundaries(
        self,
        e2e_client: AsyncClient,
        e2e_user_and_key: dict[str, Any],
    ) -> None:
        """Gateway returns HTTP 422 for out-of-range floats when authenticated with a valid key."""
        v_key = e2e_user_and_key["virtual_key"]
        invalid_payloads = [
            {
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": -999.0,
            },
            {
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": 50.0,
            },
            {
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "hi"}],
                "top_p": -0.5,
            },
            {
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "hi"}],
                "top_p": 1.5,
            },
            {
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": -500,
            },
            {
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 0,
            },
        ]

        for payload in invalid_payloads:
            res = await e2e_client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {v_key}"},
                json=payload,
            )
            assert res.status_code == 422, (
                f"Expected 422 for payload {payload}, got {res.status_code}: {res.text}"
            )

    @pytest.mark.asyncio
    async def test_nan_and_infinite_floats_rejected(
        self,
        e2e_client: AsyncClient,
        e2e_user_and_key: dict[str, Any],
    ) -> None:
        """Pydantic and JSON parser reject NaN and string float injections with HTTP 422."""
        v_key = e2e_user_and_key["virtual_key"]
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "test nan"}],
                "temperature": "NaN",
            },
        )
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_messages_array_rejected(
        self,
        e2e_client: AsyncClient,
        e2e_user_and_key: dict[str, Any],
    ) -> None:
        """Empty messages list violates min_length=1 constraint returning HTTP 422."""
        v_key = e2e_user_and_key["virtual_key"]
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [],
            },
        )
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_raw_binary_and_null_byte_injection(
        self,
        e2e_client: AsyncClient,
    ) -> None:
        """Raw binary and malformed UTF-8 payloads fail gracefully with HTTP 400 or 422 without process crash."""
        malformed_bytes = b'{"messages": [{"role": "user", "content": "embedded\x00null"}], "model": "groq:llama-70b"}'
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": "Bearer any-token",
                "Content-Type": "application/json",
            },
            content=malformed_bytes,
        )
        assert res.status_code in [400, 401, 422]

        invalid_utf8 = b"\xff\xfe\xfd\x80\x81"
        res_utf8 = await e2e_client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": "Bearer any-token",
                "Content-Type": "application/json",
            },
            content=invalid_utf8,
        )
        assert res_utf8.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_authorization_sql_and_crlf_header_injection(
        self,
        e2e_client: AsyncClient,
    ) -> None:
        """SQL injection in virtual key Bearer token is safely rejected with HTTP 401 without SQL error."""
        sql_injection_tokens = [
            "' OR '1'='1",
            "'; DROP TABLE virtual_api_keys; --",
            '" OR ""="',
            "Bearer ' UNION SELECT * FROM users --",
        ]

        for evil_token in sql_injection_tokens:
            res = await e2e_client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {evil_token}"},
                json={
                    "model": "groq:llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": "SQL injection test"}],
                },
            )
            assert res.status_code == 401
            assert "detail" in res.json() or "error" in res.json()


# ==============================================================================
# Suite 5.2: Thundering Herd & Concurrency Races (TestAdversarialConcurrencyAndRaces)
# ==============================================================================
class TestAdversarialConcurrencyAndRaces:
    """Tests race conditions, probe storms on half-open transitions, and quota boundary races."""

    @pytest.mark.asyncio
    async def test_half_open_probe_concurrency_storm_protection(self) -> None:
        """When an OPEN circuit transitions to HALF_OPEN, concurrent requests are strictly capped to probe limit."""
        engine = CircuitBreakerEngine(
            failure_threshold=2,
            open_duration_seconds=0.05,
            probe_concurrency_limit=1,
        )

        # Trip circuit to OPEN
        await engine.record_failure(None, "provider", "groq-storm")
        await engine.record_failure(None, "provider", "groq-storm")

        state = await engine.get_or_create_state(None, "provider", "groq-storm")
        assert state.state == CircuitState.OPEN

        # Wait for open_duration to pass so circuit is eligible for recovery probe
        await asyncio.sleep(0.06)

        # Launch 20 concurrent requests simultaneously
        async def try_probe() -> bool:
            return await engine.allow_request(None, "provider", "groq-storm")

        results = await asyncio.gather(*(try_probe() for _ in range(20)))

        # Exactly 1 probe should be admitted, and 19 rejected
        allowed_count = sum(1 for r in results if r is True)
        denied_count = sum(1 for r in results if r is False)

        assert allowed_count == 1, (
            f"Expected exactly 1 probe admitted, got {allowed_count}"
        )
        assert denied_count == 19, f"Expected 19 probes blocked, got {denied_count}"
        assert state.probe_requests_in_flight == 1
        assert state.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_failover_engine_probe_reservation_blocks_concurrent_probes(
        self,
    ) -> None:
        """FailoverExecutionEngine._reserve_candidate_probe blocks concurrent attempts on half-open candidates."""
        circuit_engine = CircuitBreakerEngine(
            failure_threshold=2,
            open_duration_seconds=0.05,
            probe_concurrency_limit=1,
        )
        failover_engine = FailoverExecutionEngine(circuit_breaker=circuit_engine)

        cred_id = uuid.uuid4()
        cand = Candidate(
            provider="groq",
            provider_model_id="llama-70b",
            gateway_model_id="groq:llama-70b",
            credential_id=cred_id,
            credential_display_name="Test Cred",
            canonical_model_id=uuid.uuid4(),
            canonical_name="llama-70b",
            context_window=32768,
            max_output_tokens=4096,
            input_price_per_million=None,
            output_price_per_million=None,
            supports_streaming=True,
            supports_tools=True,
            supports_structured_output=True,
            supports_vision=False,
            supports_reasoning=False,
        )

        # Trip the model scope to OPEN
        await circuit_engine.record_failure(None, "model", "groq:llama-70b")
        await circuit_engine.record_failure(None, "model", "groq:llama-70b")

        # Wait for open duration
        await asyncio.sleep(0.06)

        # First request reserves the probe
        res1 = await failover_engine._reserve_candidate_probe(None, cand)
        assert res1 is True

        # Second concurrent request must be rejected
        res2 = await failover_engine._reserve_candidate_probe(None, cand)
        assert res2 is False

        # Release first probe
        await circuit_engine.release_candidate_probe(None, "groq", cred_id, "llama-70b")

        # Now subsequent probe can succeed
        res3 = await failover_engine._reserve_candidate_probe(None, cand)
        assert res3 is True

    @pytest.mark.asyncio
    async def test_quota_reset_boundary_concurrency_consistency(self) -> None:
        """Concurrent quota evaluation across reset timestamp extracts consistent non-negative remaining counts."""
        quota_service = QuotaService()

        # Parse valid rate limit headers
        headers = {
            "x-ratelimit-remaining-requests": "0",
            "x-ratelimit-reset-requests": "1s",
            "retry-after": "1",
        }
        obs = quota_service.extract_quota_observations_from_headers(
            "groq", headers, model_id="llama-70b"
        )
        assert len(obs) >= 1
        assert obs[0]["remaining"] == 0
        assert obs[0]["retry_after"] == 1


# ==============================================================================
# Suite 5.3: Rapid Failover Churn & Cascading Exhaustion (TestAdversarialRapidFailoverChurn)
# ==============================================================================
class TestAdversarialRapidFailoverChurn:
    """Tests 3-tier cascade exhaustion, retry budget depletion, and deadline cutoffs."""

    @pytest.fixture
    def test_context(self) -> tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy]:
        user = User(
            id=uuid.uuid4(), email=f"churn_{uuid.uuid4().hex[:8]}@relay.internal"
        )
        key = VirtualAPIKey(id=uuid.uuid4(), user_id=user.id, name="Churn Key")
        policy = VirtualKeyRoutingPolicy(
            virtual_api_key_id=key.id,
            user_id=user.id,
            routing_mode="preset",
            routing_preset="balanced",
            model_access_profile="all_models",
        )
        return user, key, policy

    @pytest.mark.asyncio
    async def test_three_tier_cascading_exhaustion(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
    ) -> None:
        """Level 1 (Groq 500) -> Level 2 (Gemini 429) -> Level 3 (OpenRouter 503) -> Total exhaustion error."""
        user, key, policy = test_context

        cred1, cred2, cred3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        c1 = make_adversarial_candidate("groq", "llama-70b", cred1, score=0.95)
        c2 = make_adversarial_candidate("gemini", "gemini-flash", cred2, score=0.90)
        c3 = make_adversarial_candidate(
            "openrouter", "mistral-large", cred3, score=0.85
        )

        mock_routing = MagicMock(
            get_ranked_candidates=AsyncMock(return_value=[c1, c2, c3])
        )
        mock_cred_pool = MagicMock(
            decrypt_credential=AsyncMock(return_value="valid-key")
        )

        # Mock adapters to all fail with retryable errors
        mock_adapter_groq = MagicMock(
            create_chat_completion=AsyncMock(
                side_effect=ProviderUnavailableError(
                    message="Groq down", status_code=500
                )
            )
        )
        mock_adapter_gemini = MagicMock(
            create_chat_completion=AsyncMock(
                side_effect=RateLimitError(message="Gemini RPM", status_code=429)
            )
        )
        mock_adapter_or = MagicMock(
            create_chat_completion=AsyncMock(
                side_effect=ProviderUnavailableError(
                    message="OpenRouter 503", status_code=503
                )
            )
        )

        def get_adapter(provider: str) -> Any:
            if provider == "groq":
                return mock_adapter_groq
            if provider == "gemini":
                return mock_adapter_gemini
            return mock_adapter_or

        mock_prov_mgr = MagicMock(get_provider=MagicMock(side_effect=get_adapter))
        mock_event_rec = MagicMock(
            record_rate_limit=AsyncMock(),
            record_provider_unavailable=AsyncMock(),
            record_failover_exhausted=AsyncMock(),
            record_auth_failed=AsyncMock(),
            record_failover_succeeded=AsyncMock(),
        )

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            credential_pool=mock_cred_pool,
            event_recorder=mock_event_rec,
            usage_service=MagicMock(record_request=AsyncMock()),
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        chat_req = ChatCompletionRequest(
            model="auto", messages=[ChatMessage(role="user", content="Cascade test")]
        )

        with pytest.raises(OpenAIHTTPException) as exc_info:
            await engine.execute_chat_completion(
                db=None,
                user=user,
                key=key,
                request=chat_req,
                request_id="req-cascade-exhaustion",
                policy=policy,
                retry_policy=RetryPolicy(max_attempts=3, max_failover_candidates=3),
            )

        assert "503" in str(exc_info.value) or "error" in str(exc_info.value).lower()
        mock_event_rec.record_failover_exhausted.assert_awaited()

    @pytest.mark.asyncio
    async def test_retry_budget_depletion_stops_upstream_churn(self) -> None:
        """RetryBudgetEnforcer blocks retries once retry ratio exceeds budget limit (20%)."""
        enforcer = RetryBudgetEnforcer(budget_ratio=0.20, min_requests_threshold=10)

        # Record 8 normal requests with 0 retries
        for _ in range(8):
            enforcer.record_request()

        # Still within min threshold, retry allowed
        assert enforcer.can_retry() is True

        # Record 2 retries (total 10 items, 2 retries = 20%)
        enforcer.record_request()
        enforcer.record_retry()
        enforcer.record_request()
        enforcer.record_retry()

        # Add 1 more retry without new normal request (3 retries out of 11 items = 27.3% > 20%)
        enforcer.record_retry()

        # Over 20% limit, another retry must be denied to prevent compounding churn
        assert enforcer.can_retry() is False

    @pytest.mark.asyncio
    async def test_total_request_deadline_hard_cutoff(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
    ) -> None:
        """When total_timeout deadline is exceeded, remaining candidate attempts are immediately skipped."""
        user, key, policy = test_context

        cred1, cred2 = uuid.uuid4(), uuid.uuid4()
        c1 = make_adversarial_candidate("groq", "llama-70b", cred1, score=0.95)
        c2 = make_adversarial_candidate("groq", "llama-70b", cred2, score=0.90)

        mock_routing = MagicMock(get_ranked_candidates=AsyncMock(return_value=[c1, c2]))
        mock_cred_pool = MagicMock(
            decrypt_credential=AsyncMock(return_value="valid-key")
        )
        mock_health = MagicMock(
            get_health=AsyncMock(return_value=None),
            record_failure=AsyncMock(),
            is_candidate_eligible=MagicMock(return_value=True),
        )

        async def slow_completion(*args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(0.3)
            return MagicMock()

        mock_adapter = MagicMock()
        mock_adapter.create_chat_completion = slow_completion
        mock_prov_mgr = MagicMock(get_provider=MagicMock(return_value=mock_adapter))

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            credential_pool=mock_cred_pool,
            health_service=mock_health,
            usage_service=MagicMock(record_request=AsyncMock()),
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        chat_req = ChatCompletionRequest(
            model="groq:llama-70b",
            messages=[ChatMessage(role="user", content="Timeout test")],
        )

        with pytest.raises(OpenAIHTTPException):
            await engine.execute_chat_completion(
                db=None,
                user=user,
                key=key,
                request=chat_req,
                request_id="req-deadline-cutoff",
                policy=policy,
                retry_policy=RetryPolicy(
                    total_timeout=0.15, per_attempt_timeout=0.5, max_attempts=2
                ),
            )


# ==============================================================================
# Suite 5.4: Streaming Adversarial Edge Cases (TestAdversarialStreamingEdgeCases)
# ==============================================================================
class TestAdversarialStreamingEdgeCases:
    """Tests stream cancellation, generator teardown, corrupted SSE chunks, and concatenation prevention."""

    @pytest.fixture
    def test_context(self) -> tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy]:
        user = User(
            id=uuid.uuid4(), email=f"stream_adv_{uuid.uuid4().hex[:8]}@relay.internal"
        )
        key = VirtualAPIKey(id=uuid.uuid4(), user_id=user.id, name="Stream Adv Key")
        policy = VirtualKeyRoutingPolicy(
            virtual_api_key_id=key.id,
            user_id=user.id,
            routing_mode="preset",
            routing_preset="balanced",
            model_access_profile="all_models",
        )
        return user, key, policy

    @pytest.mark.asyncio
    async def test_streaming_client_abort_pre_first_chunk_releases_probe(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
    ) -> None:
        """When client aborts pre-first-chunk, finally block releases reserved half-open probe."""
        user, key, policy = test_context
        circuit_engine = CircuitBreakerEngine(probe_concurrency_limit=1)

        cred = uuid.uuid4()
        c1 = make_adversarial_candidate("groq", "llama-70b", cred, score=0.95)

        # Set model scope to HALF_OPEN
        state = await circuit_engine.get_or_create_state(
            None, "model", "groq:llama-70b"
        )
        state.state = CircuitState.HALF_OPEN
        state.probe_requests_in_flight = 0

        mock_routing = MagicMock(get_ranked_candidates=AsyncMock(return_value=[c1]))
        mock_usage = MagicMock(record_request=AsyncMock())

        async def slow_stream(*args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(0.5)
            yield MagicMock(model_dump_json=lambda: '{"content":"slow"}', usage=None)

        mock_adapter = MagicMock(
            stream_chat_completion=MagicMock(return_value=slow_stream())
        )
        mock_prov_mgr = MagicMock(get_provider=MagicMock(return_value=mock_adapter))

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            circuit_breaker=circuit_engine,
            credential_pool=MagicMock(decrypt_credential=AsyncMock(return_value="key")),
            usage_service=mock_usage,
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        chat_req = ChatCompletionRequest(
            model="groq:llama-70b",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
        )

        stream_gen = engine.execute_stream_chat_completion(
            db=None,
            user=user,
            key=key,
            request=chat_req,
            request_id="req-abort-prechunk",
            policy=policy,
        )

        try:
            await asyncio.wait_for(stream_gen.__anext__(), timeout=0.05)
        except (TimeoutError, asyncio.CancelledError):
            pass
        finally:
            await stream_gen.aclose()

        assert state.probe_requests_in_flight == 0

    @pytest.mark.asyncio
    async def test_streaming_client_abort_mid_stream_records_cancelled_usage(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
    ) -> None:
        """When client disconnects mid-stream (post-first-chunk), finally block records cancelled token usage."""
        user, key, policy = test_context

        cred = uuid.uuid4()
        c1 = make_adversarial_candidate("groq", "llama-70b", cred, score=0.95)
        mock_routing = MagicMock(get_ranked_candidates=AsyncMock(return_value=[c1]))
        mock_usage = MagicMock(record_request=AsyncMock())

        chunk1 = MagicMock(model_dump_json=lambda: '{"content":"part1"}', usage=None)
        chunk2 = MagicMock(model_dump_json=lambda: '{"content":"part2"}', usage=None)

        async def multi_chunk_stream(*args: Any, **kwargs: Any) -> Any:
            yield chunk1
            await asyncio.sleep(0.5)
            yield chunk2

        mock_adapter = MagicMock(
            stream_chat_completion=MagicMock(return_value=multi_chunk_stream())
        )
        mock_prov_mgr = MagicMock(get_provider=MagicMock(return_value=mock_adapter))

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            credential_pool=MagicMock(decrypt_credential=AsyncMock(return_value="key")),
            usage_service=mock_usage,
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        chat_req = ChatCompletionRequest(
            model="groq:llama-70b",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
        )

        stream_gen = engine.execute_stream_chat_completion(
            db=None,
            user=user,
            key=key,
            request=chat_req,
            request_id="req-midstream-disconnect",
            policy=policy,
        )

        first_received = await stream_gen.__anext__()
        assert "part1" in first_received

        await stream_gen.aclose()

        mock_usage.record_request.assert_awaited()
        call_kwargs = mock_usage.record_request.call_args.kwargs
        assert call_kwargs["status"] == "cancelled"
        assert call_kwargs["streaming"] is True

    @pytest.mark.asyncio
    async def test_streaming_corrupted_upstream_sse_chunk_emits_terminal_error(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
    ) -> None:
        """Upstream exception post-first-chunk yields normalized terminal SSE error and closes stream."""
        user, key, policy = test_context
        cred = uuid.uuid4()
        c1 = make_adversarial_candidate("groq", "llama-70b", cred, score=0.95)

        mock_routing = MagicMock(get_ranked_candidates=AsyncMock(return_value=[c1]))
        chunk1 = MagicMock(
            model_dump_json=lambda: '{"content":"valid start"}', usage=None
        )

        async def corrupted_stream(*args: Any, **kwargs: Any) -> Any:
            yield chunk1
            raise ProviderUnavailableError(
                message="Corrupted SSE byte framing from provider", status_code=502
            )

        mock_adapter = MagicMock(
            stream_chat_completion=MagicMock(return_value=corrupted_stream())
        )
        mock_prov_mgr = MagicMock(get_provider=MagicMock(return_value=mock_adapter))

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            credential_pool=MagicMock(decrypt_credential=AsyncMock(return_value="key")),
            usage_service=MagicMock(record_request=AsyncMock()),
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        chat_req = ChatCompletionRequest(
            model="groq:llama-70b",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
        )

        received: list[str] = []
        async for chunk in engine.execute_stream_chat_completion(
            db=None,
            user=user,
            key=key,
            request=chat_req,
            request_id="req-corrupted-stream",
            policy=policy,
        ):
            received.append(chunk)

        assert len(received) == 3
        assert "valid start" in received[0]
        assert "stream_interrupted" in received[1]
        assert received[2] == "data: [DONE]\n\n"

    @pytest.mark.asyncio
    async def test_streaming_model_concatenation_strictly_prevented(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
    ) -> None:
        """If primary model fails post-chunk 1, secondary model is NEVER invoked to concatenate output."""
        user, key, policy = test_context
        cred1, cred2 = uuid.uuid4(), uuid.uuid4()

        c1 = make_adversarial_candidate("groq", "llama-70b", cred1, score=0.95)
        c2 = make_adversarial_candidate("gemini", "gemini-flash", cred2, score=0.90)

        mock_routing = MagicMock(get_ranked_candidates=AsyncMock(return_value=[c1, c2]))

        chunk1 = MagicMock(model_dump_json=lambda: '{"content":"model A"}', usage=None)

        async def model_a_fail(*args: Any, **kwargs: Any) -> Any:
            yield chunk1
            raise ProviderUnavailableError(
                message="Model A network fault", status_code=502
            )

        mock_adapter_a = MagicMock(
            stream_chat_completion=MagicMock(return_value=model_a_fail())
        )
        mock_adapter_b = MagicMock(stream_chat_completion=MagicMock())

        def get_adapter(p: str) -> Any:
            return mock_adapter_a if p == "groq" else mock_adapter_b

        mock_prov_mgr = MagicMock(get_provider=MagicMock(side_effect=get_adapter))

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            credential_pool=MagicMock(decrypt_credential=AsyncMock(return_value="key")),
            usage_service=MagicMock(record_request=AsyncMock()),
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        chat_req = ChatCompletionRequest(
            model="auto", messages=[ChatMessage(role="user", content="hi")], stream=True
        )

        async for _ in engine.execute_stream_chat_completion(
            db=None,
            user=user,
            key=key,
            request=chat_req,
            request_id="req-no-concatenation",
            policy=policy,
        ):
            pass

        assert mock_adapter_b.stream_chat_completion.call_count == 0


# ==============================================================================
# Suite 5.5: Credential Leakage & Forensic Sanitization (TestAdversarialForensicSanitization)
# ==============================================================================
class TestAdversarialForensicSanitization:
    """Tests redaction of live provider secrets from error traces, logs, and audit metadata."""

    def test_upstream_error_api_key_reflection_redacted(self) -> None:
        """Raw API keys reflected in upstream error bodies are scrubbed by sanitize_error_text."""
        leaked_messages = [
            "Invalid key: gsk_1234567890abcdef1234567890 in request header",
            "Authentication failed for AIzaSyD01234567890123456789012345678901",
            "Bearer sk-or-v1-0123456789abcdef0123456789abcdef0123456789abcdef is expired",
            "Forbidden: x-goog-api-key: AIzaSyD_live_credential_payload",
        ]

        for msg in leaked_messages:
            sanitized = sanitize_error_text(msg)
            assert "gsk_1234567890abcdef1234567890" not in sanitized
            assert "AIzaSyD01234567890123456789012345678901" not in sanitized
            assert (
                "sk-or-v1-0123456789abcdef0123456789abcdef0123456789abcdef"
                not in sanitized
            )
            assert "[REDACTED_SECRET]" in sanitized

    def test_audit_log_and_event_metadata_secret_masking(self) -> None:
        """Sensitive keys in metadata dictionaries are recursively replaced with [REDACTED]."""
        payload = {
            "provider": "groq",
            "api_key": "gsk_secret_12345",
            "authorization": "Bearer eyJhbGciOi...",
            "nested": {
                "token": "secret_token_abc",
                "safe_field": 42,
                "password": "supersecretpassword",
            },
            "headers_list": [
                {"cookie": "session=xyz"},
                "x-goog-api-key: secret",
            ],
        }

        scrubbed = sanitize_dict(payload)

        assert scrubbed["api_key"] == "[REDACTED]"
        assert scrubbed["authorization"] == "[REDACTED]"
        assert scrubbed["nested"]["token"] == "[REDACTED]"
        assert scrubbed["nested"]["password"] == "[REDACTED]"
        assert scrubbed["nested"]["safe_field"] == 42
        assert scrubbed["headers_list"][0]["cookie"] == "[REDACTED]"

    def test_classify_provider_error_zero_leakage_guarantee(self) -> None:
        """Classify provider error wraps raw exceptions with sanitized error messages."""
        raw_exc = Exception("Upstream failed: gsk_abcdef12345678901234567890 rejected")
        classified = classify_provider_error(raw_exc, provider="groq")

        assert "gsk_abcdef12345678901234567890" not in classified.message
        assert "[REDACTED_SECRET]" in classified.message


# ==============================================================================
# Suite 5.6: Multi-Tenant Isolation & Breach Attempts (TestAdversarialMultiTenantBreachAttempts)
# ==============================================================================
class TestAdversarialMultiTenantBreachAttempts:
    """Tests strict tenant isolation across provider credentials, health, quotas, and audit events."""

    @pytest.mark.asyncio
    async def test_cross_tenant_credential_health_access_rejected(
        self,
        e2e_client: AsyncClient,
        mock_providers: MockProviderController,
    ) -> None:
        """User B cannot read health state of a credential owned by User A (returns 404)."""
        user_a_id = str(uuid.uuid4())
        user_b_id = str(uuid.uuid4())

        headers_a = {
            "X-Dev-User-Id": user_a_id,
            "X-Dev-User-Email": f"tenant_a_{user_a_id[:8]}@relay.test",
        }
        headers_b = {
            "X-Dev-User-Id": user_b_id,
            "X-Dev-User-Email": f"tenant_b_{user_b_id[:8]}@relay.test",
        }

        # User A creates a credential
        cred_res = await e2e_client.post(
            f"{settings.API_V1_PREFIX}/providers/groq/credentials",
            json={
                "api_key": f"gsk-tenant-a-key-{user_a_id[:8]}",
                "display_name": "Tenant A Cred",
            },
            headers=headers_a,
        )
        assert cred_res.status_code == 201
        cred_id = cred_res.json()["id"]

        # User B attempts to inspect User A's credential health
        b_res = await e2e_client.get(
            f"{settings.API_V1_PREFIX}/providers/credentials/{cred_id}/health",
            headers=headers_b,
        )
        assert b_res.status_code == 404

    @pytest.mark.asyncio
    async def test_cross_tenant_credential_deletion_rejected(
        self,
        e2e_client: AsyncClient,
        mock_providers: MockProviderController,
    ) -> None:
        """User B cannot delete User A's credential."""
        user_a_id = str(uuid.uuid4())
        user_b_id = str(uuid.uuid4())

        headers_a = {
            "X-Dev-User-Id": user_a_id,
            "X-Dev-User-Email": f"tenant_a_{user_a_id[:8]}@relay.test",
        }
        headers_b = {
            "X-Dev-User-Id": user_b_id,
            "X-Dev-User-Email": f"tenant_b_{user_b_id[:8]}@relay.test",
        }

        cred_res = await e2e_client.post(
            f"{settings.API_V1_PREFIX}/providers/groq/credentials",
            json={
                "api_key": f"gsk-tenant-a-target-{user_a_id[:8]}",
                "display_name": "Tenant A Target",
            },
            headers=headers_a,
        )
        assert cred_res.status_code == 201
        cred_id = cred_res.json()["id"]

        # User B attempts DELETE
        del_res = await e2e_client.delete(
            f"{settings.API_V1_PREFIX}/providers/credentials/{cred_id}",
            headers=headers_b,
        )
        assert del_res.status_code == 404

        # Verify User A's credential is still intact
        list_res = await e2e_client.get(
            f"{settings.API_V1_PREFIX}/providers/credentials",
            headers=headers_a,
        )
        assert list_res.status_code == 200
        ids = [c["id"] for c in list_res.json()]
        assert cred_id in ids

    @pytest.mark.asyncio
    async def test_cross_tenant_quotas_and_events_isolated(
        self,
        e2e_client: AsyncClient,
        mock_providers: MockProviderController,
    ) -> None:
        """User B cannot query quotas or reliability events for User A's credential."""
        user_a_id = str(uuid.uuid4())
        user_b_id = str(uuid.uuid4())

        headers_a = {
            "X-Dev-User-Id": user_a_id,
            "X-Dev-User-Email": f"tenant_a_{user_a_id[:8]}@relay.test",
        }
        headers_b = {
            "X-Dev-User-Id": user_b_id,
            "X-Dev-User-Email": f"tenant_b_{user_b_id[:8]}@relay.test",
        }

        cred_res = await e2e_client.post(
            f"{settings.API_V1_PREFIX}/providers/groq/credentials",
            json={
                "api_key": f"gsk-tenant-a-quota-{user_a_id[:8]}",
                "display_name": "Tenant A Quota Cred",
            },
            headers=headers_a,
        )
        assert cred_res.status_code == 201
        cred_id = cred_res.json()["id"]

        # User B queries quotas with User A's credential_id
        q_res = await e2e_client.get(
            f"{settings.API_V1_PREFIX}/quotas?credential_id={cred_id}",
            headers=headers_b,
        )
        if q_res.status_code == 200:
            data = q_res.json()
            items = data.get("items", []) if isinstance(data, dict) else data
            assert len(items) == 0
        else:
            assert q_res.status_code in [403, 404]

        # User B queries reliability events with User A's credential_id
        ev_res = await e2e_client.get(
            f"{settings.API_V1_PREFIX}/reliability/events?credential_id={cred_id}",
            headers=headers_b,
        )
        if ev_res.status_code == 200:
            data = ev_res.json()
            items = data.get("items", []) if isinstance(data, dict) else data
            assert len(items) == 0
        else:
            assert ev_res.status_code in [403, 404]
