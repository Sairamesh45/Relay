"""Unit and integration tests for Circuit Breaker Engine.

Tests CLOSED, OPEN, HALF_OPEN state transitions, observation windows, probe concurrency limits,
thundering herd protection, scope isolation, recovery thresholds, and event emission.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reliability import (
    CircuitBreakerState,
    CircuitState,
    ReliabilityEvent,
    ReliabilityEventType,
)
from app.services.reliability.circuit_breaker import (
    CircuitBreakerEngine,
)


class TestCircuitBreakerEngine:
    """Test suite covering all operational aspects of CircuitBreakerEngine."""

    @pytest.fixture
    def engine(self) -> CircuitBreakerEngine:
        """Create a standalone CircuitBreakerEngine with strict thresholds for fast testing."""
        return CircuitBreakerEngine(
            failure_threshold=5,
            observation_window_seconds=60.0,
            open_duration_seconds=5.0,
            half_open_success_threshold=2,
            probe_concurrency_limit=1,
        )

    # --------------------------------------------------------------------------
    # 1. State Initializations & CLOSED Behavior
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self, engine: CircuitBreakerEngine) -> None:
        """New circuit breaker initializes in CLOSED state with 0 failures."""
        state = await engine.get_or_create_state(None, "provider", "groq")
        assert state.state == CircuitState.CLOSED
        assert state.failure_count == 0
        assert state.success_count == 0
        assert state.probe_requests_in_flight == 0

    @pytest.mark.asyncio
    async def test_closed_state_allows_request(
        self, engine: CircuitBreakerEngine
    ) -> None:
        """CLOSED circuit always allows incoming requests."""
        allowed = await engine.allow_request(None, "provider", "groq")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_failures_below_threshold_remain_closed(
        self, engine: CircuitBreakerEngine
    ) -> None:
        """Failures below failure_threshold keep circuit in CLOSED state."""
        for _ in range(4):
            state = await engine.record_failure(None, "provider", "groq")
            assert state.state == CircuitState.CLOSED

        assert state.failure_count == 4
        assert await engine.allow_request(None, "provider", "groq") is True

    # --------------------------------------------------------------------------
    # 2. Trip to OPEN State
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_trip_to_open_at_threshold(
        self, engine: CircuitBreakerEngine
    ) -> None:
        """At exactly 5 consecutive failures, circuit trips to OPEN."""
        for _i in range(5):
            state = await engine.record_failure(None, "provider", "groq")

        assert state.state == CircuitState.OPEN
        assert state.failure_count == 5

    @pytest.mark.asyncio
    async def test_open_circuit_blocks_requests(
        self, engine: CircuitBreakerEngine
    ) -> None:
        """OPEN circuit immediately fast-fails / blocks requests without network calls."""
        for _ in range(5):
            await engine.record_failure(None, "provider", "groq")

        allowed = await engine.allow_request(None, "provider", "groq")
        assert allowed is False

    # --------------------------------------------------------------------------
    # 3. Observation Window & Transition to HALF_OPEN
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_open_duration_expiry_transitions_to_half_open(
        self, engine: CircuitBreakerEngine
    ) -> None:
        """After open_duration_seconds has elapsed, circuit transitions to HALF_OPEN on next check."""
        for _ in range(5):
            await engine.record_failure(None, "provider", "groq")

        state = await engine.get_or_create_state(None, "provider", "groq")
        assert state.state == CircuitState.OPEN

        # Simulate time passage beyond 5-second open duration
        state.last_state_change = datetime.now(UTC) - timedelta(seconds=6.0)

        # allow_request should detect expiration and admit probe
        allowed = await engine.allow_request(None, "provider", "groq")
        assert allowed is True
        assert state.state == CircuitState.HALF_OPEN
        assert state.probe_requests_in_flight == 1

    # --------------------------------------------------------------------------
    # 4. Probe Concurrency Limit (Thundering Herd Protection)
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_half_open_limits_probe_concurrency(
        self, engine: CircuitBreakerEngine
    ) -> None:
        """HALF_OPEN circuit rejects concurrent probes when probe_requests_in_flight reaches ceiling."""
        state = await engine.get_or_create_state(None, "provider", "groq")
        state.state = CircuitState.HALF_OPEN
        state.probe_requests_in_flight = 0

        # First probe admitted
        allowed_1 = await engine.allow_request(None, "provider", "groq")
        assert allowed_1 is True
        assert state.probe_requests_in_flight == 1

        # Second concurrent probe must be blocked (probe limit = 1)
        allowed_2 = await engine.allow_request(None, "provider", "groq")
        assert allowed_2 is False
        assert state.probe_requests_in_flight == 1

    # --------------------------------------------------------------------------
    # 5. Recovery & Reopen Transitions from HALF_OPEN
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_failure_in_half_open_immediately_reopens_circuit(
        self, engine: CircuitBreakerEngine
    ) -> None:
        """A single probe failure in HALF_OPEN immediately trips circuit back to OPEN."""
        state = await engine.get_or_create_state(None, "provider", "groq")
        state.state = CircuitState.HALF_OPEN
        state.probe_requests_in_flight = 1

        new_state = await engine.record_failure(None, "provider", "groq")
        assert new_state.state == CircuitState.OPEN
        assert new_state.probe_requests_in_flight == 0

    @pytest.mark.asyncio
    async def test_half_open_success_threshold_closes_circuit(
        self, engine: CircuitBreakerEngine
    ) -> None:
        """Circuit transitions from HALF_OPEN to CLOSED only after success threshold (2) is met."""
        state = await engine.get_or_create_state(None, "provider", "groq")
        state.state = CircuitState.HALF_OPEN
        state.probe_requests_in_flight = 1

        # 1st success: still HALF_OPEN (threshold is 2)
        s1 = await engine.record_success(None, "provider", "groq")
        assert s1.state == CircuitState.HALF_OPEN
        assert s1.success_count == 1
        assert s1.probe_requests_in_flight == 0

        # Simulate 2nd probe admitted and succeeded
        s1.probe_requests_in_flight = 1
        s2 = await engine.record_success(None, "provider", "groq")
        assert s2.state == CircuitState.CLOSED
        assert s2.success_count == 0
        assert s2.failure_count == 0
        assert s2.probe_requests_in_flight == 0

    # --------------------------------------------------------------------------
    # 6. Scope Isolation: Provider vs Model vs Credential
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_model_circuit_trip_does_not_open_provider_circuit(
        self, engine: CircuitBreakerEngine
    ) -> None:
        """Tripping a model-scoped circuit does not trip the provider-wide circuit or unrelated models."""
        for _ in range(5):
            await engine.record_failure(None, "model", "groq:llama-3.3-70b-versatile")

        # The 70b model circuit is tripped
        m70_allowed = await engine.allow_request(
            None, "model", "groq:llama-3.3-70b-versatile"
        )
        assert m70_allowed is False

        # Provider-wide circuit remains CLOSED
        provider_allowed = await engine.allow_request(None, "provider", "groq")
        assert provider_allowed is True

        # Unrelated model on the same provider remains CLOSED
        m8_allowed = await engine.allow_request(
            None, "model", "groq:llama-3.1-8b-instant"
        )
        assert m8_allowed is True

    @pytest.mark.asyncio
    async def test_can_execute_candidate_multi_scope_check(
        self, engine: CircuitBreakerEngine
    ) -> None:
        """can_execute_candidate checks all relevant scopes (provider, credential, model)."""
        cred_id = uuid.uuid4()

        # Initially all scopes permit execution
        can_exec = await engine.can_execute_candidate(
            None,
            provider="gemini",
            credential_id=cred_id,
            model_id="gemini-2.5-pro",
        )
        assert can_exec is True

        # Trip only the credential scope
        for _ in range(5):
            await engine.record_failure(None, "credential", str(cred_id))

        can_exec_after = await engine.can_execute_candidate(
            None,
            provider="gemini",
            credential_id=cred_id,
            model_id="gemini-2.5-pro",
        )
        assert can_exec_after is False

        # Different credential for same model is still allowed
        other_cred = uuid.uuid4()
        other_exec = await engine.can_execute_candidate(
            None,
            provider="gemini",
            credential_id=other_cred,
            model_id="gemini-2.5-pro",
        )
        assert other_exec is True

    # --------------------------------------------------------------------------
    # 7. Observation Window Counter Reset in CLOSED
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_observation_window_resets_old_failures(
        self, engine: CircuitBreakerEngine
    ) -> None:
        """Failures occurring outside observation window reset failure count to 1."""
        state = await engine.get_or_create_state(None, "provider", "openrouter")
        state.failure_count = 3
        # Simulate last failure 90 seconds ago (window is 60s)
        state.last_state_change = datetime.now(UTC) - timedelta(seconds=90.0)

        new_state = await engine.record_failure(None, "provider", "openrouter")
        # Should reset and count as 1 failure, NOT 4
        assert new_state.failure_count == 1
        assert new_state.state == CircuitState.CLOSED

    # --------------------------------------------------------------------------
    # 8. Database Persistence Integration
    # --------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_circuit_breaker_db_roundtrip_and_event_emission(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Verify DB persistence of CircuitBreakerState and emission of CIRCUIT_OPENED event."""
        test_engine = CircuitBreakerEngine(
            failure_threshold=3, open_duration_seconds=10.0
        )
        unique_scope = f"test-prov-{uuid.uuid4().hex[:8]}"

        # Trip circuit in DB
        for _ in range(3):
            await test_engine.record_failure(db_session, "provider", unique_scope)

        # Check DB row
        stmt = select(CircuitBreakerState).where(
            CircuitBreakerState.scope_type == "provider",
            CircuitBreakerState.scope_id == unique_scope,
        )
        res = await db_session.execute(stmt)
        persisted = res.scalars().first()

        assert persisted is not None
        assert persisted.state == CircuitState.OPEN
        assert persisted.failure_count == 3

        # Check that CIRCUIT_OPENED event was emitted
        ev_stmt = select(ReliabilityEvent).where(
            ReliabilityEvent.event_type == ReliabilityEventType.CIRCUIT_OPENED.value,
            ReliabilityEvent.provider == unique_scope,
        )
        ev_res = await db_session.execute(ev_stmt)
        event = ev_res.scalars().first()
        assert event is not None
        assert event.event_metadata["failure_count"] == 3
