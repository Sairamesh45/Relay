"""Tests for Phase 6 Reliability Models.

Verifies instantiation, default values, aliases, serialization, DB persistence,
and migration readiness for CredentialHealth, QuotaState, CircuitBreakerState, and ReliabilityEvent.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt_api_key, generate_credential_fingerprint
from app.models.provider_credential import ProviderCredential
from app.models.reliability import (
    CircuitBreakerState,
    CircuitState,
    CredentialHealth,
    HealthStatus,
    QuotaConfidence,
    QuotaResourceType,
    QuotaScope,
    QuotaState,
    ReliabilityEvent,
    ReliabilityEventType,
)
from app.models.user import User


@pytest.fixture
async def sample_credential(db_session: AsyncSession) -> ProviderCredential:
    """Create a verified test provider credential in the database."""
    user = User(
        id=uuid.uuid4(),
        email=f"rel_user_{uuid.uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    raw_key = f"sk-test-{uuid.uuid4().hex[:12]}"
    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key(raw_key),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint(raw_key),
        status="active",
        display_name="Test Reliability Credential",
    )
    db_session.add(cred)
    await db_session.commit()
    await db_session.refresh(cred)
    return cred


# -----------------------------------------------------------------------------
# CredentialHealth Unit & Integration Tests
# -----------------------------------------------------------------------------


def test_credential_health_instantiation_defaults() -> None:
    """Verify CredentialHealth default values and attribute behaviors."""
    cred_id = uuid.uuid4()
    health = CredentialHealth(credential_id=cred_id)

    assert health.credential_id == cred_id
    assert health.health_status == HealthStatus.HEALTHY
    assert health.failure_count == 0
    assert health.consecutive_failures == 0
    assert health.last_success_at is None
    assert health.last_failure_at is None
    assert health.cooldown_until is None
    assert health.cooldown_expires_at is None
    assert health.is_cooling_down is False
    assert health.last_error_category is None
    assert health.error_details == {}


def test_credential_health_aliases_and_serialization() -> None:
    """Verify cooldown alias, cooling down detection, and dictionary serialization."""
    cred_id = uuid.uuid4()
    cooldown_target = datetime.now(UTC) + timedelta(minutes=5)
    health = CredentialHealth(
        credential_id=cred_id,
        status="cooling_down",
        consecutive_failures=3,
        cooldown_expires_at=cooldown_target,
        last_error_category="RATE_LIMITED",
        error_details={"status_code": 429, "retry_after": 300},
    )

    assert health.health_status == HealthStatus.COOLING_DOWN
    assert health.cooldown_until == cooldown_target
    assert health.is_cooling_down is True

    serialized = health.to_dict()
    assert serialized["credential_id"] == str(cred_id)
    assert serialized["health_status"] == "cooling_down"
    assert serialized["consecutive_failures"] == 3
    assert serialized["last_error_category"] == "RATE_LIMITED"
    assert serialized["error_details"]["status_code"] == 429


@pytest.mark.asyncio
async def test_credential_health_db_persistence(
    db_session: AsyncSession, sample_credential: ProviderCredential
) -> None:
    """Verify persisting CredentialHealth to database and querying it back."""
    now = datetime.now(UTC)
    health = CredentialHealth(
        credential_id=sample_credential.id,
        health_status=HealthStatus.RATE_LIMITED,
        failure_count=5,
        consecutive_failures=2,
        last_success_at=now - timedelta(hours=1),
        last_failure_at=now,
        cooldown_until=now + timedelta(seconds=60),
        last_error_category="RATE_LIMITED",
        error_details={"reason": "rpm_exceeded"},
    )
    db_session.add(health)
    await db_session.commit()

    stmt = select(CredentialHealth).where(
        CredentialHealth.credential_id == sample_credential.id
    )
    res = await db_session.execute(stmt)
    persisted = res.scalar_one_or_none()

    assert persisted is not None
    assert persisted.health_status == HealthStatus.RATE_LIMITED
    assert persisted.failure_count == 5
    assert persisted.consecutive_failures == 2
    assert persisted.last_error_category == "RATE_LIMITED"
    assert persisted.error_details == {"reason": "rpm_exceeded"}


@pytest.mark.asyncio
async def test_credential_health_unique_constraint(
    db_session: AsyncSession, sample_credential: ProviderCredential
) -> None:
    """Verify unique constraint on credential_id prevents duplicate health records."""
    h1 = CredentialHealth(
        credential_id=sample_credential.id, health_status=HealthStatus.HEALTHY
    )
    db_session.add(h1)
    await db_session.commit()

    h2 = CredentialHealth(
        credential_id=sample_credential.id, health_status=HealthStatus.DEGRADED
    )
    db_session.add(h2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# -----------------------------------------------------------------------------
# QuotaState Unit & Integration Tests
# -----------------------------------------------------------------------------


def test_quota_state_instantiation_defaults() -> None:
    """Verify QuotaState default values and aliases."""
    quota = QuotaState(
        provider="groq",
        quota_scope=QuotaScope.CREDENTIAL.value,
        resource_type=QuotaResourceType.TOKENS.value,
    )
    assert quota.provider == "groq"
    assert quota.quota_scope == "credential"
    assert quota.resource_type == "tokens"
    assert quota.limit is None
    assert quota.remaining is None
    assert quota.limit_value is None
    assert quota.remaining_value is None
    assert quota.confidence == "unknown"
    assert quota.source == "header"


def test_quota_state_aliases_and_serialization() -> None:
    """Verify QuotaState alias getters/setters and to_dict serialization."""
    reset_time = datetime.now(UTC) + timedelta(minutes=1)
    quota = QuotaState(
        provider="groq",
        quota_scope="model",
        model_id="llama-3.3-70b-versatile",
        resource_type="requests",
        limit_value=1000,
        remaining_value=850,
        reset_at=reset_time,
        retry_after_seconds=45,
        confidence=QuotaConfidence.CONFIRMED.value,
        source="header",
    )

    assert quota.limit == 1000
    assert quota.remaining == 850
    assert quota.retry_after == 45

    serialized = quota.to_dict()
    assert serialized["provider"] == "groq"
    assert serialized["limit"] == 1000
    assert serialized["remaining"] == 850
    assert serialized["retry_after"] == 45
    assert serialized["confidence"] == "confirmed"


@pytest.mark.asyncio
async def test_quota_state_db_persistence(
    db_session: AsyncSession, sample_credential: ProviderCredential
) -> None:
    """Verify saving QuotaState to database and supporting large BigInteger token limits."""
    large_limit = 50_000_000_000  # 50 Billion tokens (tests BigInteger capacity)
    large_remaining = 49_998_500_000

    quota = QuotaState(
        credential_id=sample_credential.id,
        provider="groq",
        quota_scope="credential",
        resource_type="tokens",
        limit=large_limit,
        remaining=large_remaining,
        confidence="confirmed",
        source="header",
    )
    db_session.add(quota)
    await db_session.commit()

    stmt = select(QuotaState).where(QuotaState.id == quota.id)
    res = await db_session.execute(stmt)
    persisted = res.scalar_one_or_none()

    assert persisted is not None
    assert persisted.limit == large_limit
    assert persisted.remaining == large_remaining
    assert persisted.provider == "groq"


# -----------------------------------------------------------------------------
# CircuitBreakerState Unit & Integration Tests
# -----------------------------------------------------------------------------


def test_circuit_breaker_state_defaults_and_aliases() -> None:
    """Verify CircuitBreakerState defaults, aliases, and transitions."""
    cb = CircuitBreakerState(
        scope_type="provider",
        scope_id="openrouter",
    )
    assert cb.scope_type == "provider"
    assert cb.scope_id == "openrouter"
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0
    assert cb.consecutive_failures == 0
    assert cb.success_count == 0
    assert cb.probe_requests_in_flight == 0
    assert cb.probe_in_flight is False

    cb.consecutive_failures = 4
    assert cb.failure_count == 4
    cb.probe_requests_in_flight = 1
    assert cb.probe_in_flight is True


@pytest.mark.asyncio
async def test_circuit_breaker_db_persistence(db_session: AsyncSession) -> None:
    """Verify persisting and unique constraint on (scope_type, scope_id)."""
    scope_id = f"test-scope-{uuid.uuid4().hex[:8]}"
    cb = CircuitBreakerState(
        scope_type="model",
        scope_id=scope_id,
        state=CircuitState.HALF_OPEN,
        failure_count=3,
        success_count=1,
        probe_requests_in_flight=1,
    )
    db_session.add(cb)
    await db_session.commit()

    stmt = select(CircuitBreakerState).where(
        CircuitBreakerState.scope_type == "model",
        CircuitBreakerState.scope_id == scope_id,
    )
    persisted = (await db_session.execute(stmt)).scalar_one_or_none()
    assert persisted is not None
    assert persisted.state == CircuitState.HALF_OPEN
    assert persisted.probe_in_flight is True

    # Unique constraint test
    duplicate_cb = CircuitBreakerState(
        scope_type="model",
        scope_id=scope_id,
        state=CircuitState.OPEN,
    )
    db_session.add(duplicate_cb)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# -----------------------------------------------------------------------------
# ReliabilityEvent Unit & Integration Tests
# -----------------------------------------------------------------------------


def test_reliability_event_metadata_handling() -> None:
    """Verify metadata and metadata_json kwarg handling without DeclarativeBase collision."""
    event1 = ReliabilityEvent(
        event_type=ReliabilityEventType.RATE_LIMIT_DETECTED,
        provider="groq",
        metadata={"status_code": 429, "attempt": 1},
    )
    assert event1.event_type == "RATE_LIMIT_DETECTED"
    assert event1.metadata_json == {"status_code": 429, "attempt": 1}

    event2 = ReliabilityEvent(
        event_type="CIRCUIT_OPENED",
        provider="gemini",
        metadata_json={"consecutive_failures": 5},
    )
    assert event2.event_type == "CIRCUIT_OPENED"
    assert event2.metadata_json == {"consecutive_failures": 5}


@pytest.mark.asyncio
async def test_reliability_event_db_persistence(
    db_session: AsyncSession, sample_credential: ProviderCredential
) -> None:
    """Verify saving ReliabilityEvent to database and querying JSONB metadata."""
    event = ReliabilityEvent(
        event_type=ReliabilityEventType.FAILOVER_STARTED.value,
        provider="groq",
        credential_id=sample_credential.id,
        model_id="llama-3.3-70b-versatile",
        metadata={
            "failed_candidate": "groq/cred1",
            "next_candidate": "groq/cred2",
            "error_category": "RATE_LIMITED",
        },
    )
    db_session.add(event)
    await db_session.commit()

    stmt = select(ReliabilityEvent).where(ReliabilityEvent.id == event.id)
    persisted = (await db_session.execute(stmt)).scalar_one_or_none()
    assert persisted is not None
    assert persisted.event_type == "FAILOVER_STARTED"
    assert persisted.provider == "groq"
    assert persisted.model_id == "llama-3.3-70b-versatile"
    assert persisted.credential_id == sample_credential.id
    assert persisted.metadata_json["error_category"] == "RATE_LIMITED"
