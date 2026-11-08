"""Scope-aware Circuit Breaker Engine for AI providers, models, and credentials.

Manages CLOSED, OPEN, and HALF-OPEN states, protects against thundering herds with
strict probe concurrency limits, enforces observation windows, and prevents cascade
failures across unrelated models or providers.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reliability import CircuitBreakerState, CircuitState
from app.services.reliability.event_recorder import (
    EventRecorder,
    get_event_recorder,
)

logger = logging.getLogger(__name__)


class CircuitBreakerEngine:
    """PostgreSQL-backed and memory-synchronized circuit breaker with probe concurrency control."""

    def __init__(
        self,
        failure_threshold: int = 5,
        observation_window_seconds: float = 60.0,
        open_duration_seconds: float = 30.0,
        half_open_success_threshold: int = 2,
        probe_concurrency_limit: int = 1,
        event_recorder: EventRecorder | None = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.observation_window_seconds = observation_window_seconds
        self.open_duration_seconds = open_duration_seconds
        self.half_open_success_threshold = half_open_success_threshold
        self.probe_concurrency_limit = probe_concurrency_limit
        self.event_recorder = event_recorder or get_event_recorder()

        # In-memory fast cache to sync states across calls
        self._in_memory_states: dict[tuple[str, str], CircuitBreakerState] = {}

    def _get_key(self, scope_type: str, scope_id: str) -> tuple[str, str]:
        return (scope_type.lower().strip(), str(scope_id).strip())

    async def get_or_create_state(
        self,
        db: AsyncSession | None,
        scope_type: str,
        scope_id: str,
    ) -> CircuitBreakerState:
        """Fetch existing CircuitBreakerState or initialize default CLOSED state."""
        key = self._get_key(scope_type, scope_id)

        if db is not None:
            stmt = select(CircuitBreakerState).where(
                CircuitBreakerState.scope_type == key[0],
                CircuitBreakerState.scope_id == key[1],
            )
            res = await db.execute(stmt)
            state = res.scalars().first()

            if state is None:
                state = CircuitBreakerState(
                    scope_type=key[0],
                    scope_id=key[1],
                    state=CircuitState.CLOSED,
                    failure_count=0,
                    success_count=0,
                    probe_requests_in_flight=0,
                    last_state_change=datetime.now(UTC),
                )
                db.add(state)
                await db.flush()

            self._in_memory_states[key] = state
            return state

        # In-memory path when db is None
        if key not in self._in_memory_states:
            self._in_memory_states[key] = CircuitBreakerState(
                scope_type=key[0],
                scope_id=key[1],
                state=CircuitState.CLOSED,
                failure_count=0,
                success_count=0,
                probe_requests_in_flight=0,
                last_state_change=datetime.now(UTC),
            )
        return self._in_memory_states[key]

    async def allow_request(
        self,
        db: AsyncSession | None,
        scope_type: str,
        scope_id: str,
        provider: str | None = None,
    ) -> bool:
        """Check if request execution is permitted through the circuit breaker.

        Handles:
        - CLOSED: permits immediately.
        - OPEN: permits only after open_duration_seconds has elapsed, transitioning to HALF_OPEN.
        - HALF_OPEN: enforces probe_concurrency_limit to prevent thundering herd.
        """
        state = await self.get_or_create_state(db, scope_type, scope_id)
        now = datetime.now(UTC)

        if state.state == CircuitState.CLOSED:
            return True

        if state.state == CircuitState.OPEN:
            elapsed = (now - state.last_state_change).total_seconds()
            if elapsed >= self.open_duration_seconds:
                # Transition from OPEN to HALF_OPEN upon observation expiry
                state.state = CircuitState.HALF_OPEN
                state.last_state_change = now
                state.success_count = 0
                state.probe_requests_in_flight = 0

                if db is not None and self.event_recorder:
                    prov = provider or (
                        scope_id if scope_type == "provider" else "unknown"
                    )
                    await self.event_recorder.record_circuit_half_open(
                        db=db,
                        provider=prov,
                        scope_type=scope_type,
                        scope_id=scope_id,
                    )

                # Check if probe concurrency limit permits this request
                if state.probe_requests_in_flight < self.probe_concurrency_limit:
                    state.probe_requests_in_flight += 1
                    if db is not None:
                        await db.flush()
                    return True
                else:
                    if db is not None:
                        await db.flush()
                    return False
            else:
                # Still within open duration: block execution
                return False

        if state.state == CircuitState.HALF_OPEN:
            # Enforce probe concurrency limit
            if state.probe_requests_in_flight < self.probe_concurrency_limit:
                state.probe_requests_in_flight += 1
                if db is not None:
                    await db.flush()
                return True
            else:
                # Active probe concurrency limit reached
                return False

        return False

    async def can_execute_candidate(
        self,
        db: AsyncSession | None,
        provider: str,
        credential_id: uuid.UUID | str | None = None,
        model_id: str | None = None,
    ) -> bool:
        """Scope-aware evaluation across model, credential, and provider levels.

        Returns True only if all relevant scopes permit the request.
        Does not mutate probe counters (pre-flight check).
        """
        scopes_to_check: list[tuple[str, str]] = []

        if model_id:
            scopes_to_check.append(("model", f"{provider}:{model_id}"))
        if credential_id:
            scopes_to_check.append(("credential", str(credential_id)))
        if provider:
            scopes_to_check.append(("provider", provider.lower().strip()))

        now = datetime.now(UTC)
        for s_type, s_id in scopes_to_check:
            state = await self.get_or_create_state(db, s_type, s_id)
            if state.state == CircuitState.OPEN:
                elapsed = (now - state.last_state_change).total_seconds()
                if elapsed < self.open_duration_seconds:
                    return False
            elif state.state == CircuitState.HALF_OPEN:
                if state.probe_requests_in_flight >= self.probe_concurrency_limit:
                    return False

        return True

    async def record_success(
        self,
        db: AsyncSession | None,
        scope_type: str,
        scope_id: str,
        provider: str | None = None,
        credential_id: uuid.UUID | None = None,
        model_id: str | None = None,
    ) -> CircuitBreakerState:
        """Record successful execution. Closes circuit if in HALF_OPEN and threshold met."""
        state = await self.get_or_create_state(db, scope_type, scope_id)
        now = datetime.now(UTC)

        if state.state == CircuitState.HALF_OPEN:
            state.probe_requests_in_flight = max(0, state.probe_requests_in_flight - 1)
            state.success_count += 1

            if state.success_count >= self.half_open_success_threshold:
                # Circuit successfully closed and recovered
                state.state = CircuitState.CLOSED
                state.failure_count = 0
                state.success_count = 0
                state.last_state_change = now

                if db is not None and self.event_recorder:
                    prov = provider or (
                        scope_id if scope_type == "provider" else "unknown"
                    )
                    await self.event_recorder.record_candidate_recovered(
                        db=db,
                        provider=prov,
                        scope_type=scope_type,
                        scope_id=scope_id,
                        credential_id=credential_id,
                        model_id=model_id,
                    )
        elif state.state == CircuitState.CLOSED:
            # Reset failure count after healthy execution
            state.failure_count = 0
            state.success_count += 1

        if db is not None:
            await db.flush()

        return state

    async def record_failure(
        self,
        db: AsyncSession | None,
        scope_type: str,
        scope_id: str,
        provider: str | None = None,
        credential_id: uuid.UUID | None = None,
        model_id: str | None = None,
    ) -> CircuitBreakerState:
        """Record execution failure. Trips to OPEN if failure_threshold reached or probe failed."""
        state = await self.get_or_create_state(db, scope_type, scope_id)
        now = datetime.now(UTC)

        if state.state == CircuitState.HALF_OPEN:
            # Probe failed in HALF_OPEN: immediately trip back to OPEN
            state.probe_requests_in_flight = max(0, state.probe_requests_in_flight - 1)
            state.state = CircuitState.OPEN
            state.last_state_change = now
            state.failure_count = self.failure_threshold
            state.success_count = 0

            if db is not None and self.event_recorder:
                prov = provider or (scope_id if scope_type == "provider" else "unknown")
                await self.event_recorder.record_circuit_opened(
                    db=db,
                    provider=prov,
                    scope_type=scope_type,
                    scope_id=scope_id,
                    credential_id=credential_id,
                    model_id=model_id,
                    failure_count=state.failure_count,
                )
        elif state.state == CircuitState.CLOSED:
            elapsed = (now - state.last_state_change).total_seconds()
            if elapsed > self.observation_window_seconds and state.failure_count > 0:
                # Reset counter if previous failure was outside observation window
                state.failure_count = 1
                state.last_state_change = now
            else:
                state.failure_count += 1

            if state.failure_count >= self.failure_threshold:
                # Failure threshold reached: trip to OPEN
                state.state = CircuitState.OPEN
                state.last_state_change = now
                state.success_count = 0

                if db is not None and self.event_recorder:
                    prov = provider or (
                        scope_id if scope_type == "provider" else "unknown"
                    )
                    await self.event_recorder.record_circuit_opened(
                        db=db,
                        provider=prov,
                        scope_type=scope_type,
                        scope_id=scope_id,
                        credential_id=credential_id,
                        model_id=model_id,
                        failure_count=state.failure_count,
                    )

        if db is not None:
            await db.flush()

        return state

    async def release_probe(
        self,
        db: AsyncSession | None,
        scope_type: str,
        scope_id: str,
    ) -> None:
        """Decrement in-flight probe counter when a probe request completes or errors out."""
        state = await self.get_or_create_state(db, scope_type, scope_id)
        if state.probe_requests_in_flight > 0:
            state.probe_requests_in_flight -= 1
            if db is not None:
                await db.flush()

    async def record_candidate_success(
        self,
        db: AsyncSession | None,
        provider: str,
        credential_id: uuid.UUID | str | None = None,
        model_id: str | None = None,
    ) -> None:
        """Record success across all relevant candidate scopes."""
        if model_id:
            await self.record_success(
                db=db,
                scope_type="model",
                scope_id=f"{provider}:{model_id}",
                provider=provider,
                model_id=model_id,
            )
        if credential_id:
            await self.record_success(
                db=db,
                scope_type="credential",
                scope_id=str(credential_id),
                provider=provider,
                credential_id=uuid.UUID(str(credential_id)),
            )
        if provider:
            await self.record_success(
                db=db,
                scope_type="provider",
                scope_id=provider.lower().strip(),
                provider=provider,
            )

    async def record_candidate_failure(
        self,
        db: AsyncSession | None,
        provider: str,
        credential_id: uuid.UUID | str | None = None,
        model_id: str | None = None,
        is_provider_wide: bool = False,
    ) -> None:
        """Record failure at the narrowest appropriate scope.

        If failure is model-specific, trips model-scoped breaker without opening provider.
        If is_provider_wide is True (e.g. 502/503 outage), also increments provider-wide breaker.
        """
        cred_uuid = uuid.UUID(str(credential_id)) if credential_id else None

        if model_id:
            await self.record_failure(
                db=db,
                scope_type="model",
                scope_id=f"{provider}:{model_id}",
                provider=provider,
                credential_id=cred_uuid,
                model_id=model_id,
            )
        if credential_id:
            await self.record_failure(
                db=db,
                scope_type="credential",
                scope_id=str(credential_id),
                provider=provider,
                credential_id=cred_uuid,
                model_id=model_id,
            )
        if is_provider_wide and provider:
            await self.record_failure(
                db=db,
                scope_type="provider",
                scope_id=provider.lower().strip(),
                provider=provider,
                credential_id=cred_uuid,
                model_id=model_id,
            )

    async def release_candidate_probe(
        self,
        db: AsyncSession | None,
        provider: str,
        credential_id: uuid.UUID | str | None = None,
        model_id: str | None = None,
    ) -> None:
        """Safely release probe in-flight counter across relevant scopes."""
        if model_id:
            await self.release_probe(db, "model", f"{provider}:{model_id}")
        if credential_id:
            await self.release_probe(db, "credential", str(credential_id))
        if provider:
            await self.release_probe(db, "provider", provider.lower().strip())


# Singleton instance
_circuit_breaker_engine: CircuitBreakerEngine | None = None


def get_circuit_breaker_engine() -> CircuitBreakerEngine:
    """Dependency getter for CircuitBreakerEngine."""
    global _circuit_breaker_engine
    if _circuit_breaker_engine is None:
        _circuit_breaker_engine = CircuitBreakerEngine()
    return _circuit_breaker_engine
