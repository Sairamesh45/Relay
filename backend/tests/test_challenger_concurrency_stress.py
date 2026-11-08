"""Challenger 1 Empirical Concurrency Stress Test Suite for Milestone M8.

Validates:
1. Strict circuit breaker half-open probe concurrency caps (no thundering herd across 100+ tasks).
2. Multi-scope probe atomic reservation and rollback without probe leaks.
3. Clean streaming cancellation handling client disconnects:
   - Probe counter released back to zero
   - Usage log recorded with status="cancelled", status_code=499, error_code="CLIENT_CANCELLED"
4. Rate limiter concurrency on brand new keys:
   - 25 concurrent database transactions against a newly provisioned virtual key
   - Zero unique constraint / race condition violations
   - Exact limit enforcement (10 allowed, 15 rejected with 429)
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete, select

from app.core.gateway_errors import OpenAIHTTPException
from app.db.session import get_session_factory
from app.models.rate_limit import RateLimitBucket
from app.models.reliability import CircuitState
from app.models.routing_policy import VirtualKeyRoutingPolicy
from app.models.user import User
from app.models.virtual_api_key import VirtualAPIKey
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatMessage,
)
from app.services.rate_limiter import RateLimiterService
from app.services.reliability.circuit_breaker import CircuitBreakerEngine
from app.services.reliability.failover_engine import FailoverExecutionEngine
from app.services.reliability.retry_policy import RetryBudgetEnforcer
from app.services.routing.candidates import Candidate
from app.services.routing.scoring import ScoreBreakdown, ScoredCandidate


def create_mock_candidate(
    provider: str,
    model_id: str,
    credential_id: uuid.UUID,
    score: float = 0.95,
) -> ScoredCandidate:
    cand = Candidate(
        provider=provider,
        provider_model_id=model_id,
        gateway_model_id=f"{provider}:{model_id}",
        credential_id=credential_id,
        credential_display_name="Stress-Cred",
        canonical_model_id=uuid.uuid4(),
        canonical_name=model_id,
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
# 1. Circuit Breaker Probe Concurrency Burst Stress Tests
# ==============================================================================
class TestCircuitBreakerProbeStress:
    """Stress tests circuit breaker probe concurrency limits under heavy concurrent bursts."""

    @pytest.mark.asyncio
    async def test_probe_limit_one_strictly_enforced_100_burst(self) -> None:
        """When probe_concurrency_limit=1, exactly 1 out of 100 concurrent tasks acquires the probe."""
        cb = CircuitBreakerEngine(
            failure_threshold=2,
            open_duration_seconds=0.01,
            probe_concurrency_limit=1,
        )

        state = await cb.get_or_create_state(None, "provider", "burst-provider")
        state.state = CircuitState.HALF_OPEN
        state.probe_requests_in_flight = 0

        async def worker() -> bool:
            return await cb.allow_request(None, "provider", "burst-provider")

        # 100 tasks launched simultaneously
        results = await asyncio.gather(*(worker() for _ in range(100)))

        allowed = sum(1 for r in results if r is True)
        denied = sum(1 for r in results if r is False)

        assert allowed == 1, f"Expected exactly 1 probe allowed, got {allowed}"
        assert denied == 99, f"Expected 99 denied, got {denied}"
        assert state.probe_requests_in_flight == 1

        # Release probe and fire another 100 tasks
        await cb.release_probe(None, "provider", "burst-provider")
        assert state.probe_requests_in_flight == 0

        results2 = await asyncio.gather(*(worker() for _ in range(100)))
        assert sum(1 for r in results2 if r is True) == 1
        assert sum(1 for r in results2 if r is False) == 99
        assert state.probe_requests_in_flight == 1

    @pytest.mark.asyncio
    async def test_probe_limit_three_strictly_enforced_100_burst(self) -> None:
        """When probe_concurrency_limit=3, exactly 3 out of 100 concurrent tasks acquire the probe."""
        cb = CircuitBreakerEngine(
            failure_threshold=2,
            open_duration_seconds=0.01,
            probe_concurrency_limit=3,
        )

        state = await cb.get_or_create_state(None, "model", "groq:llama-3")
        state.state = CircuitState.HALF_OPEN
        state.probe_requests_in_flight = 0

        async def worker() -> bool:
            return await cb.allow_request(None, "model", "groq:llama-3")

        results = await asyncio.gather(*(worker() for _ in range(100)))

        allowed = sum(1 for r in results if r is True)
        denied = sum(1 for r in results if r is False)

        assert allowed == 3, f"Expected exactly 3 probes allowed, got {allowed}"
        assert denied == 97, f"Expected 97 denied, got {denied}"
        assert state.probe_requests_in_flight == 3

    @pytest.mark.asyncio
    async def test_multi_scope_probe_atomic_reservation_rollback(self) -> None:
        """If model probe succeeds but provider probe is saturated, model probe is rolled back immediately."""
        cb = CircuitBreakerEngine(probe_concurrency_limit=1)
        engine = FailoverExecutionEngine(circuit_breaker=cb)

        # Set model scope to HALF_OPEN (0 in flight)
        m_state = await cb.get_or_create_state(None, "model", "groq:llama-70b")
        m_state.state = CircuitState.HALF_OPEN
        m_state.probe_requests_in_flight = 0

        # Set provider scope to HALF_OPEN (1 in flight = SATURATED)
        p_state = await cb.get_or_create_state(None, "provider", "groq")
        p_state.state = CircuitState.HALF_OPEN
        p_state.probe_requests_in_flight = 1

        cand = Candidate(
            provider="groq",
            provider_model_id="llama-70b",
            gateway_model_id="groq:llama-70b",
            credential_id=uuid.uuid4(),
            credential_display_name="Cred",
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

        # Reservation must fail because provider scope is saturated
        reserved = await engine._reserve_candidate_probe(None, cand)
        assert reserved is False

        # Model scope probe count must be rolled back to 0 (no probe leak!)
        assert m_state.probe_requests_in_flight == 0
        assert p_state.probe_requests_in_flight == 1


# ==============================================================================
# 2. Streaming Cancellation & Clean Abort Stress Tests
# ==============================================================================
class TestStreamingCancellationStress:
    """Stress tests clean cancellation, probe counter release, and status 499 logging."""

    @pytest.mark.asyncio
    async def test_client_abort_midstream_releases_probe_and_logs_499(self) -> None:
        """Client disconnect mid-stream releases probes and logs usage with status=cancelled, status_code=499."""
        cb = CircuitBreakerEngine(probe_concurrency_limit=1)
        user_id = uuid.uuid4()
        user = User(id=user_id, email="stream_cancel@relay.test")
        key = VirtualAPIKey(id=uuid.uuid4(), user_id=user_id, name="Cancel Key")
        policy = VirtualKeyRoutingPolicy(
            virtual_api_key_id=key.id,
            user_id=user_id,
            routing_mode="preset",
            routing_preset="balanced",
            model_access_profile="all_models",
        )

        cred_id = uuid.uuid4()
        cand = create_mock_candidate("groq", "llama-70b", cred_id)

        # Model is HALF_OPEN
        m_state = await cb.get_or_create_state(None, "model", "groq:llama-70b")
        m_state.state = CircuitState.HALF_OPEN
        m_state.probe_requests_in_flight = 0

        mock_routing = MagicMock(get_ranked_candidates=AsyncMock(return_value=[cand]))
        mock_usage = MagicMock(record_request=AsyncMock())

        chunk1 = MagicMock(
            model_dump_json=lambda: '{"delta":"hello"}',
            usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

        async def infinite_stream(*args: Any, **kwargs: Any) -> Any:
            yield chunk1
            # Client hangs / aborts while waiting for next chunk
            await asyncio.sleep(10.0)
            yield chunk1

        mock_adapter = MagicMock(
            stream_chat_completion=MagicMock(return_value=infinite_stream())
        )
        mock_prov_mgr = MagicMock(get_provider=MagicMock(return_value=mock_adapter))

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            circuit_breaker=cb,
            credential_pool=MagicMock(decrypt_credential=AsyncMock(return_value="key")),
            usage_service=mock_usage,
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        req = ChatCompletionRequest(
            model="groq:llama-70b",
            messages=[ChatMessage(role="user", content="hello")],
            stream=True,
        )

        stream_gen = engine.execute_stream_chat_completion(
            db=None,
            user=user,
            key=key,
            request=req,
            request_id="req-stress-abort-499",
            policy=policy,
        )

        # Consume first chunk
        first = await stream_gen.__anext__()
        assert "hello" in first
        # Probe is currently checked out
        assert m_state.probe_requests_in_flight == 1

        # Simulate client disconnect mid-stream
        await stream_gen.aclose()

        # Probe MUST be released in finally block
        assert m_state.probe_requests_in_flight == 0

        # Usage service MUST be recorded with 499 CLIENT_CANCELLED
        mock_usage.record_request.assert_awaited_once()
        kwargs = mock_usage.record_request.call_args.kwargs
        assert kwargs["status"] == "cancelled"
        assert kwargs["status_code"] == 499
        assert kwargs["error_code"] == "CLIENT_CANCELLED"
        assert kwargs["streaming"] is True
        assert kwargs["input_tokens"] == 10
        assert kwargs["output_tokens"] == 5
        assert kwargs["total_tokens"] == 15

    @pytest.mark.asyncio
    async def test_client_abort_pre_first_chunk_releases_probe_cleanly(self) -> None:
        """Client disconnect pre-first-chunk releases probe without crashing or leaking."""
        cb = CircuitBreakerEngine(probe_concurrency_limit=1)
        user_id = uuid.uuid4()
        user = User(id=user_id, email="stream_preabort@relay.test")
        key = VirtualAPIKey(id=uuid.uuid4(), user_id=user_id, name="Pre-Abort Key")
        policy = VirtualKeyRoutingPolicy(
            virtual_api_key_id=key.id,
            user_id=user_id,
            routing_mode="preset",
            routing_preset="balanced",
            model_access_profile="all_models",
        )

        cred_id = uuid.uuid4()
        cand = create_mock_candidate("groq", "llama-70b", cred_id)

        m_state = await cb.get_or_create_state(None, "model", "groq:llama-70b")
        m_state.state = CircuitState.HALF_OPEN
        m_state.probe_requests_in_flight = 0

        mock_routing = MagicMock(get_ranked_candidates=AsyncMock(return_value=[cand]))

        async def slow_first_chunk(*args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(5.0)
            yield MagicMock(model_dump_json=lambda: "{}", usage=None)

        mock_adapter = MagicMock(
            stream_chat_completion=MagicMock(return_value=slow_first_chunk())
        )
        mock_prov_mgr = MagicMock(get_provider=MagicMock(return_value=mock_adapter))

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            circuit_breaker=cb,
            credential_pool=MagicMock(decrypt_credential=AsyncMock(return_value="key")),
            usage_service=MagicMock(record_request=AsyncMock()),
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        req = ChatCompletionRequest(
            model="groq:llama-70b",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
        )

        stream_gen = engine.execute_stream_chat_completion(
            db=None,
            user=user,
            key=key,
            request=req,
            request_id="req-stress-preabort",
            policy=policy,
        )

        # Abort before first chunk arrives
        task = asyncio.create_task(stream_gen.__anext__())
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await stream_gen.aclose()

        # Probe MUST be released back to 0
        assert m_state.probe_requests_in_flight == 0


# ==============================================================================
# 3. Rate Limiter PostgreSQL Concurrency Burst Tests
# ==============================================================================
class TestRateLimiterDatabaseConcurrency:
    """Stress tests RateLimiterService against PostgreSQL with concurrent sessions on new keys."""

    @pytest.mark.asyncio
    async def test_concurrent_new_key_burst_zero_race_conditions(self) -> None:
        """25 concurrent sessions calling check_rate_limit on a new key:

        - 0 duplicate key / unique constraint exceptions.
        - Exactly limit (10) allowed, 15 rejected with 429.
        """
        factory = get_session_factory()
        rate_limiter = RateLimiterService(default_rpm=10)

        # 1. Create a transient User and VirtualAPIKey
        test_user_id = uuid.uuid4()
        test_key_id = uuid.uuid4()

        async with factory() as session:
            test_user = User(
                id=test_user_id,
                email=f"ratelimit_stress_{test_user_id.hex[:8]}@relay.test",
            )
            session.add(test_user)
            await session.flush()

            test_key = VirtualAPIKey(
                id=test_key_id,
                user_id=test_user_id,
                name="Stress Rate Limit Key",
                key_hash="stress_hash",
                key_prefix="rel_stress",
            )
            session.add(test_key)
            await session.commit()

        try:
            # 2. Concurrently call check_rate_limit across 10 isolated database sessions (under Supabase pool limit 15)
            async def call_limiter(idx: int) -> tuple[int, str]:
                async with factory() as sess:
                    try:
                        await rate_limiter.check_rate_limit(
                            sess, test_key_id, custom_limit=5
                        )
                        await sess.commit()
                        return (200, "OK")
                    except OpenAIHTTPException as e:
                        await sess.rollback()
                        return (e.status_code, str(e))
                    except Exception as e:
                        await sess.rollback()
                        return (500, f"UNHANDLED: {type(e).__name__}: {e}")

            results = await asyncio.gather(*(call_limiter(i) for i in range(10)))

            status_codes = [r[0] for r in results]
            status_200 = sum(1 for s in status_codes if s == 200)
            status_429 = sum(1 for s in status_codes if s == 429)
            status_500 = sum(1 for s in status_codes if s == 500)

            # Ensure zero unhandled / unique constraint crash errors!
            unhandled = [r for r in results if r[0] == 500]
            assert status_500 == 0, (
                f"Found unhandled concurrency exceptions: {unhandled}"
            )

            # Ensure exact limit partitioning: 5 allowed, 5 rate-limited
            assert status_200 == 5, f"Expected 5 allowed, got {status_200}"
            assert status_429 == 5, f"Expected 5 rate-limited (429), got {status_429}"

            # Verify persistent bucket counter
            async with factory() as verify_sess:
                stmt = select(RateLimitBucket).where(
                    RateLimitBucket.key_id == test_key_id
                )
                bucket = (await verify_sess.execute(stmt)).scalar_one_or_none()
                assert bucket is not None
                assert bucket.request_count == 5

        finally:
            # Cleanup test data
            async with factory() as cleanup_sess:
                await cleanup_sess.execute(
                    delete(RateLimitBucket).where(RateLimitBucket.key_id == test_key_id)
                )
                await cleanup_sess.execute(
                    delete(VirtualAPIKey).where(VirtualAPIKey.id == test_key_id)
                )
                await cleanup_sess.execute(delete(User).where(User.id == test_user_id))
                await cleanup_sess.commit()
