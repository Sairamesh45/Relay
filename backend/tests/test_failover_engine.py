"""Unit and integration tests for 3-Level Automatic Failover Engine.

Tests 3 explicit failover levels (Level 1: same model diff credential, Level 2: diff model same provider,
Level 3: diff model diff provider), non-retryable error rules, health/cooldown skips, circuit breaker skips,
retry budgets, execution tracing, and streaming failure semantics (pre-chunk failover vs post-chunk terminal SSE).
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gateway_errors import OpenAIHTTPException
from app.models.routing_policy import VirtualKeyRoutingPolicy
from app.models.user import User
from app.models.virtual_api_key import VirtualAPIKey
from app.providers.exceptions import (
    InvalidCredentialsError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.schemas.chat import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
)
from app.services.reliability.failover_engine import FailoverExecutionEngine
from app.services.reliability.retry_policy import (
    RetryBudgetEnforcer,
)
from app.services.routing.candidates import Candidate
from app.services.routing.context import RoutingContext
from app.services.routing.scoring import ScoreBreakdown, ScoredCandidate


def make_dummy_scored_candidate(
    provider: str,
    provider_model_id: str,
    credential_id: uuid.UUID,
    score: float = 0.9,
    supports_streaming: bool = True,
) -> ScoredCandidate:
    """Helper to build a ScoredCandidate for testing."""
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
        supports_streaming=supports_streaming,
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


class TestFailoverEngine:
    """Test suite for FailoverExecutionEngine."""

    @pytest.fixture
    def test_context(self) -> tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy]:
        """Generate test user, virtual key, and routing policy."""
        user = User(
            id=uuid.uuid4(), email=f"failover_{uuid.uuid4().hex[:8]}@example.com"
        )
        key = VirtualAPIKey(id=uuid.uuid4(), user_id=user.id, name="Failover Test Key")
        policy = VirtualKeyRoutingPolicy(
            virtual_api_key_id=key.id,
            user_id=user.id,
            routing_mode="preset",
            routing_preset="balanced",
            model_access_profile="all_models",
        )
        return user, key, policy

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        """Create an AsyncSession mock with proper result chains for scalars and scalar_one."""
        db = AsyncMock(spec=AsyncSession)
        mock_res = MagicMock()
        mock_res.scalars.return_value.first.return_value = None
        mock_res.scalars.return_value.all.return_value = []
        mock_res.scalar_one_or_none.return_value = None
        mock_res.scalar_one.return_value = 0
        mock_res.all.return_value = []
        db.execute = AsyncMock(return_value=mock_res)
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.add = MagicMock()
        return db

    # --------------------------------------------------------------------------
    # 1. 3-Level Failover Hierarchy Organization
    # --------------------------------------------------------------------------
    def test_candidate_organization_hierarchy(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
    ) -> None:
        """Verify strict 3-level ordering: Level 1 (same model diff cred), Level 2 (same provider diff model), Level 3 (diff provider)."""
        user, key, policy = test_context
        engine = FailoverExecutionEngine(retry_budget_enforcer=RetryBudgetEnforcer())

        cred_a1 = uuid.uuid4()
        cred_a2 = uuid.uuid4()
        cred_b = uuid.uuid4()
        cred_c = uuid.uuid4()

        # Primary: Groq llama-70b (cred_a1)
        c0 = make_dummy_scored_candidate("groq", "llama-70b", cred_a1, score=0.95)
        # Level 3: Gemini gemini-flash (cred_c)
        c_diff_prov = make_dummy_scored_candidate(
            "gemini", "gemini-flash", cred_c, score=0.90
        )
        # Level 2: Groq llama-8b (cred_b)
        c_diff_model = make_dummy_scored_candidate(
            "groq", "llama-8b", cred_b, score=0.85
        )
        # Level 1: Groq llama-70b (cred_a2)
        c_same_model_diff_cred = make_dummy_scored_candidate(
            "groq", "llama-70b", cred_a2, score=0.80
        )

        # Shuffle input
        ranked = [c0, c_diff_prov, c_diff_model, c_same_model_diff_cred]
        chat_req = ChatCompletionRequest(
            model="auto", messages=[ChatMessage(role="user", content="Hi")]
        )
        ctx = RoutingContext.from_request(
            user=user, key=key, policy=policy, request=chat_req
        )

        pipeline = engine.organize_failover_candidates(ranked, ctx, policy)

        # Assert hierarchy ordering
        assert len(pipeline) == 4
        assert pipeline[0][1] == 0  # Primary
        assert pipeline[1][1] == 1  # Level 1: same model diff cred
        assert pipeline[2][1] == 2  # Level 2: same provider diff model
        assert pipeline[3][1] == 3  # Level 3: diff provider

        assert pipeline[0][0].credential_id == cred_a1
        assert pipeline[1][0].credential_id == cred_a2
        assert pipeline[2][0].provider_model_id == "llama-8b"
        assert pipeline[3][0].provider == "gemini"

    # --------------------------------------------------------------------------
    # 2. Level 1 Failover Execution: Rate Limit on Credential 1 -> Credential 2 Succeeds
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_level1_failover_credential_recovery(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
        mock_db: AsyncMock,
    ) -> None:
        """Level 1 failover: Credential 1 returns 429 RateLimitError -> Credential 2 succeeds -> HTTP 200, 2 attempts."""
        user, key, policy = test_context
        cred1 = uuid.uuid4()
        cred2 = uuid.uuid4()

        c1 = make_dummy_scored_candidate("groq", "llama-70b", cred1, score=0.95)
        c2 = make_dummy_scored_candidate("groq", "llama-70b", cred2, score=0.90)

        mock_routing = MagicMock()
        mock_routing.get_ranked_candidates = AsyncMock(return_value=[c1, c2])

        mock_cred_pool = MagicMock()
        mock_cred_pool.decrypt_credential = AsyncMock(
            side_effect=["key-for-cred1", "key-for-cred2"]
        )

        mock_adapter = MagicMock()
        mock_resp = MagicMock(spec=ChatCompletionResponse)
        mock_resp.usage = None
        mock_resp.model = "groq:llama-70b"

        # 1st attempt: RateLimitError; 2nd attempt: Success
        mock_adapter.create_chat_completion = AsyncMock(
            side_effect=[
                RateLimitError(message="RPM exceeded", status_code=429),
                mock_resp,
            ]
        )

        mock_prov_mgr = MagicMock()
        mock_prov_mgr.get_provider = MagicMock(return_value=mock_adapter)

        mock_usage = MagicMock()
        mock_usage.record_request = AsyncMock()

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            credential_pool=mock_cred_pool,
            usage_service=mock_usage,
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        chat_req = ChatCompletionRequest(
            model="groq:llama-70b", messages=[ChatMessage(role="user", content="Hi")]
        )

        response, trace = await engine.execute_chat_completion(
            db=mock_db,
            user=user,
            key=key,
            request=chat_req,
            request_id="req-lvl1-test",
            policy=policy,
        )

        assert response == mock_resp
        assert trace.total_attempts == 2
        assert trace.final_status == "success"
        assert trace.failover_level == 1
        assert trace.attempts[0].status == "failed"
        assert trace.attempts[0].error_category.lower() == "rate_limited"
        assert trace.attempts[1].status == "success"

    # --------------------------------------------------------------------------
    # 3. Level 2 Failover Execution: Model Unavailable -> Compatible Model Same Provider
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_level2_failover_compatible_model_same_provider(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
        mock_db: AsyncMock,
    ) -> None:
        """Level 2 failover: Model A 503 ProviderUnavailable -> Model B on same provider succeeds."""
        user, key, policy = test_context
        cred = uuid.uuid4()

        c1 = make_dummy_scored_candidate("groq", "llama-70b", cred, score=0.95)
        c2 = make_dummy_scored_candidate("groq", "llama-8b", cred, score=0.90)

        mock_routing = MagicMock()
        mock_routing.get_ranked_candidates = AsyncMock(return_value=[c1, c2])

        mock_cred_pool = MagicMock()
        mock_cred_pool.decrypt_credential = AsyncMock(return_value="groq-secret")

        mock_adapter = MagicMock()
        mock_resp = MagicMock(spec=ChatCompletionResponse)
        mock_resp.usage = None
        mock_adapter.create_chat_completion = AsyncMock(
            side_effect=[
                ProviderUnavailableError(
                    message="llama-70b capacity overload", status_code=503
                ),
                mock_resp,
            ]
        )

        mock_prov_mgr = MagicMock()
        mock_prov_mgr.get_provider = MagicMock(return_value=mock_adapter)

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            credential_pool=mock_cred_pool,
            usage_service=MagicMock(record_request=AsyncMock()),
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        chat_req = ChatCompletionRequest(
            model="auto", messages=[ChatMessage(role="user", content="Hi")]
        )

        response, trace = await engine.execute_chat_completion(
            db=mock_db,
            user=user,
            key=key,
            request=chat_req,
            request_id="req-lvl2-test",
            policy=policy,
        )

        assert response == mock_resp
        assert trace.total_attempts == 2
        assert trace.failover_level == 2
        assert trace.attempts[1].model_id == "llama-8b"

    # --------------------------------------------------------------------------
    # 4. Level 3 Failover Execution: Provider Outage -> Different Provider
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_level3_failover_cross_provider_fallback(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
        mock_db: AsyncMock,
    ) -> None:
        """Level 3 failover: Groq 502 Bad Gateway -> Gemini succeeds."""
        user, key, policy = test_context
        cred_groq = uuid.uuid4()
        cred_gemini = uuid.uuid4()

        c1 = make_dummy_scored_candidate("groq", "llama-70b", cred_groq, score=0.95)
        c2 = make_dummy_scored_candidate(
            "gemini", "gemini-flash", cred_gemini, score=0.90
        )

        mock_routing = MagicMock()
        mock_routing.get_ranked_candidates = AsyncMock(return_value=[c1, c2])

        mock_cred_pool = MagicMock()
        mock_cred_pool.decrypt_credential = AsyncMock(
            side_effect=["groq-key", "gemini-key"]
        )

        groq_adapter = MagicMock()
        groq_adapter.create_chat_completion = AsyncMock(
            side_effect=ProviderUnavailableError(
                message="Groq upstream outage", status_code=502
            )
        )
        gemini_adapter = MagicMock()
        mock_resp = MagicMock(spec=ChatCompletionResponse)
        mock_resp.usage = None
        gemini_adapter.create_chat_completion = AsyncMock(return_value=mock_resp)

        mock_prov_mgr = MagicMock()
        mock_prov_mgr.get_provider = MagicMock(
            side_effect=lambda p: groq_adapter if p == "groq" else gemini_adapter
        )

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            credential_pool=mock_cred_pool,
            usage_service=MagicMock(record_request=AsyncMock()),
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        chat_req = ChatCompletionRequest(
            model="auto", messages=[ChatMessage(role="user", content="Hi")]
        )

        response, trace = await engine.execute_chat_completion(
            db=mock_db,
            user=user,
            key=key,
            request=chat_req,
            request_id="req-lvl3-test",
            policy=policy,
        )

        assert response == mock_resp
        assert trace.total_attempts == 2
        assert trace.failover_level == 3
        assert trace.attempts[0].provider == "groq"
        assert trace.attempts[1].provider == "gemini"

    # --------------------------------------------------------------------------
    # 5. Non-Retryable Error Rule: 401 Auth Failure Halts Execution
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_non_retryable_auth_failure_halts_immediately(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
        mock_db: AsyncMock,
    ) -> None:
        """AUTHENTICATION_FAILED (401) is non-retryable; engine halts immediately without retry storm."""
        user, key, policy = test_context
        cred = uuid.uuid4()
        c1 = make_dummy_scored_candidate("groq", "llama-70b", cred, score=0.95)

        mock_routing = MagicMock()
        mock_routing.get_ranked_candidates = AsyncMock(return_value=[c1])

        mock_adapter = MagicMock()
        mock_adapter.create_chat_completion = AsyncMock(
            side_effect=InvalidCredentialsError(
                message="API key revoked", status_code=401
            )
        )
        mock_prov_mgr = MagicMock(get_provider=MagicMock(return_value=mock_adapter))

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            credential_pool=MagicMock(
                decrypt_credential=AsyncMock(return_value="bad-key")
            ),
            usage_service=MagicMock(record_request=AsyncMock()),
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        chat_req = ChatCompletionRequest(
            model="groq:llama-70b", messages=[ChatMessage(role="user", content="Hi")]
        )

        with pytest.raises(OpenAIHTTPException) as exc_info:
            await engine.execute_chat_completion(
                db=mock_db,
                user=user,
                key=key,
                request=chat_req,
                request_id="req-auth-fail",
                policy=policy,
            )

        assert exc_info.value.status_code == 401

    # --------------------------------------------------------------------------
    # 6. Health & Circuit Breaker Gating: Ineligible Candidates Skipped
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_ineligible_health_and_open_circuits_skipped(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
        mock_db: AsyncMock,
    ) -> None:
        """Candidates in cooldown or with OPEN circuit breakers are skipped before network dispatch."""
        user, key, policy = test_context
        cred1 = uuid.uuid4()
        cred2 = uuid.uuid4()

        c1 = make_dummy_scored_candidate("groq", "llama-70b", cred1, score=0.95)
        c2 = make_dummy_scored_candidate("groq", "llama-70b", cred2, score=0.90)

        mock_routing = MagicMock(get_ranked_candidates=AsyncMock(return_value=[c1, c2]))

        # HealthService marks c1 ineligible, c2 eligible
        mock_health = MagicMock()
        mock_health.get_health = AsyncMock(return_value=None)
        mock_health.is_candidate_eligible = MagicMock(side_effect=[False, True])
        mock_health.record_success = AsyncMock()

        # Adapter only invoked for c2
        mock_resp = MagicMock(spec=ChatCompletionResponse, usage=None)
        mock_adapter = MagicMock(
            create_chat_completion=AsyncMock(return_value=mock_resp)
        )
        mock_prov_mgr = MagicMock(get_provider=MagicMock(return_value=mock_adapter))

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            health_service=mock_health,
            credential_pool=MagicMock(
                decrypt_credential=AsyncMock(return_value="valid-key")
            ),
            usage_service=MagicMock(record_request=AsyncMock()),
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        chat_req = ChatCompletionRequest(
            model="groq:llama-70b", messages=[ChatMessage(role="user", content="Hi")]
        )

        response, trace = await engine.execute_chat_completion(
            db=mock_db,
            user=user,
            key=key,
            request=chat_req,
            request_id="req-health-gate",
            policy=policy,
        )

        assert response == mock_resp
        # Candidate 1 was skipped without dispatch, candidate 2 executed
        assert trace.attempts[0].status == "skipped"
        assert trace.attempts[1].status == "success"
        # Only 1 network call occurred
        assert mock_adapter.create_chat_completion.call_count == 1

    # --------------------------------------------------------------------------
    # 7. Streaming Failure Semantics: Pre-Chunk Failover vs Post-Chunk Terminal Error
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_streaming_pre_chunk_safe_failover(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
        mock_db: AsyncMock,
    ) -> None:
        """Pre-first chunk failure cleanly fails over to next candidate without breaking client stream."""
        user, key, policy = test_context
        cred1 = uuid.uuid4()
        cred2 = uuid.uuid4()

        c1 = make_dummy_scored_candidate("groq", "llama-70b", cred1, score=0.95)
        c2 = make_dummy_scored_candidate("groq", "llama-70b", cred2, score=0.90)

        mock_routing = MagicMock(get_ranked_candidates=AsyncMock(return_value=[c1, c2]))

        # Mock adapter generator 1 raises before first chunk
        async def failing_gen(*args: Any, **kwargs: Any) -> Any:
            raise ProviderUnavailableError(
                message="Groq connection dropped", status_code=503
            )
            yield  # pragma: no cover

        # Mock adapter generator 2 yields clean chunks
        chunk1 = MagicMock(
            model_dump_json=lambda: '{"choices":[{"delta":{"content":"Hello"}}]}',
            usage=None,
        )
        chunk2 = MagicMock(
            model_dump_json=lambda: '{"choices":[{"delta":{"content":" world"}}]}',
            usage=None,
        )

        async def success_gen(*args: Any, **kwargs: Any) -> Any:
            yield chunk1
            yield chunk2

        mock_adapter = MagicMock()
        mock_adapter.stream_chat_completion = MagicMock(
            side_effect=[failing_gen(), success_gen()]
        )
        mock_prov_mgr = MagicMock(get_provider=MagicMock(return_value=mock_adapter))

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            credential_pool=MagicMock(
                decrypt_credential=AsyncMock(return_value="valid-key")
            ),
            usage_service=MagicMock(record_request=AsyncMock()),
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        chat_req = ChatCompletionRequest(
            model="groq:llama-70b",
            messages=[ChatMessage(role="user", content="Hi")],
            stream=True,
        )

        received_chunks: list[str] = []
        async for chunk in engine.execute_stream_chat_completion(
            db=mock_db,
            user=user,
            key=key,
            request=chat_req,
            request_id="req-stream-prechunk",
            policy=policy,
        ):
            received_chunks.append(chunk)

        assert len(received_chunks) == 3
        assert "Hello" in received_chunks[0]
        assert "world" in received_chunks[1]
        assert received_chunks[2] == "data: [DONE]\n\n"

    @pytest.mark.asyncio
    async def test_streaming_post_chunk_terminal_error_event(
        self,
        test_context: tuple[User, VirtualAPIKey, VirtualKeyRoutingPolicy],
        mock_db: AsyncMock,
    ) -> None:
        """Post-first chunk failure terminates immediately with normalized SSE error event; never restarts or mixes models."""
        user, key, policy = test_context
        cred1 = uuid.uuid4()
        cred2 = uuid.uuid4()

        c1 = make_dummy_scored_candidate("groq", "llama-70b", cred1, score=0.95)
        c2 = make_dummy_scored_candidate("groq", "llama-70b", cred2, score=0.90)

        mock_routing = MagicMock(get_ranked_candidates=AsyncMock(return_value=[c1, c2]))

        chunk1 = MagicMock(
            model_dump_json=lambda: '{"choices":[{"delta":{"content":"First chunk"}}]}',
            usage=None,
        )

        async def midstream_fail_gen(*args: Any, **kwargs: Any) -> Any:
            yield chunk1
            # Fails after yielding first chunk
            raise ProviderUnavailableError(
                message="Connection lost mid-stream", status_code=502
            )

        mock_adapter = MagicMock()
        mock_adapter.stream_chat_completion = MagicMock(
            return_value=midstream_fail_gen()
        )
        mock_prov_mgr = MagicMock(get_provider=MagicMock(return_value=mock_adapter))

        engine = FailoverExecutionEngine(
            routing_engine=mock_routing,
            provider_manager=mock_prov_mgr,
            credential_pool=MagicMock(
                decrypt_credential=AsyncMock(return_value="valid-key")
            ),
            usage_service=MagicMock(record_request=AsyncMock()),
            retry_budget_enforcer=RetryBudgetEnforcer(),
        )

        chat_req = ChatCompletionRequest(
            model="groq:llama-70b",
            messages=[ChatMessage(role="user", content="Hi")],
            stream=True,
        )

        received_chunks: list[str] = []
        async for chunk in engine.execute_stream_chat_completion(
            db=mock_db,
            user=user,
            key=key,
            request=chat_req,
            request_id="req-stream-postchunk",
            policy=policy,
        ):
            received_chunks.append(chunk)

        # Must have: 1) first chunk, 2) terminal error chunk, 3) data: [DONE]
        assert len(received_chunks) == 3
        assert "First chunk" in received_chunks[0]
        assert "stream_interrupted" in received_chunks[1]
        assert received_chunks[2] == "data: [DONE]\n\n"
        # Candidate 2 was NEVER invoked
        assert mock_adapter.stream_chat_completion.call_count == 1
