"""Tests for QuotaService, header extraction, duration parsing, and database state tracking."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt_api_key, generate_credential_fingerprint
from app.models.provider_credential import ProviderCredential
from app.models.reliability import (
    QuotaConfidence,
    QuotaResourceType,
    QuotaScope,
)
from app.models.user import User
from app.services.reliability.quota_service import (
    QuotaService,
    get_quota_service,
    parse_reset_duration,
    parse_retry_after,
)


@pytest.fixture
async def sample_user_and_credential(
    db_session: AsyncSession,
) -> tuple[User, ProviderCredential]:
    """Create test user and credential for quota testing."""
    user = User(
        id=uuid.uuid4(),
        email=f"quota_user_{uuid.uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    raw_key = f"sk-quota-{uuid.uuid4().hex[:12]}"
    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key(raw_key),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint(raw_key),
        status="active",
        display_name="Quota Test Credential",
    )
    db_session.add(cred)
    await db_session.commit()
    await db_session.refresh(cred)
    return user, cred


def test_parse_reset_duration_various_formats() -> None:
    """Verify parsing durations like 2ms, 6s, 1m30s, 2h, numeric."""
    assert parse_reset_duration("2ms") == 0.002
    assert parse_reset_duration("500ms") == 0.5
    assert parse_reset_duration("6s") == 6.0
    assert parse_reset_duration("1m") == 60.0
    assert parse_reset_duration("1m30s") == 90.0
    assert parse_reset_duration("2h") == 7200.0
    assert parse_reset_duration("1h30m15s") == 5415.0
    assert parse_reset_duration("42") == 42.0
    assert parse_reset_duration("12.5") == 12.5
    assert parse_reset_duration("") is None
    assert parse_reset_duration(None) is None
    assert parse_reset_duration("invalid-format") is None


def test_parse_retry_after_numeric_and_http_date() -> None:
    """Verify Retry-After parser handles delta seconds and HTTP-date strings."""
    # Numeric seconds
    sec, dt = parse_retry_after("30")
    assert sec == 30
    assert dt is not None
    assert dt > datetime.now(UTC)

    # Float numeric seconds
    sec_float, dt_float = parse_retry_after("15.2")
    assert sec_float == 15
    assert dt_float is not None

    # Missing or invalid: never invent reset times
    sec_none, dt_none = parse_retry_after(None)
    assert sec_none is None
    assert dt_none is None

    sec_bad, dt_bad = parse_retry_after("not-a-date-or-number")
    assert sec_bad is None
    assert dt_bad is None


def test_extract_quota_observations_groq_headers() -> None:
    """Verify extracting RPM and TPM quota observations from Groq headers."""
    headers = {
        "x-ratelimit-limit-requests": "14400",
        "x-ratelimit-remaining-requests": "14398",
        "x-ratelimit-reset-requests": "1m30s",
        "x-ratelimit-limit-tokens": "100000",
        "x-ratelimit-remaining-tokens": "98500",
        "x-ratelimit-reset-tokens": "6s",
    }
    cred_id = uuid.uuid4()
    obs = QuotaService.extract_quota_observations_from_headers(
        provider="groq",
        headers=headers,
        credential_id=cred_id,
        model_id="llama-3.3-70b-versatile",
    )

    assert len(obs) == 2

    # Requests quota
    req_obs = next(
        o for o in obs if o["resource_type"] == QuotaResourceType.REQUESTS.value
    )
    assert req_obs["limit"] == 14400
    assert req_obs["remaining"] == 14398
    assert req_obs["retry_after"] == 90
    assert req_obs["model_id"] == "llama-3.3-70b-versatile"
    assert req_obs["quota_scope"] == QuotaScope.MODEL.value
    assert req_obs["confidence"] == QuotaConfidence.CONFIRMED.value

    # Tokens quota
    tok_obs = next(
        o for o in obs if o["resource_type"] == QuotaResourceType.TOKENS.value
    )
    assert tok_obs["limit"] == 100000
    assert tok_obs["remaining"] == 98500
    assert tok_obs["retry_after"] == 6
    assert tok_obs["reset_at"] is not None


def test_extract_quota_observations_openrouter_credits() -> None:
    """Verify OpenRouter credits header extraction."""
    headers = {
        "x-ratelimit-limit-credits": "5000",
        "x-ratelimit-remaining-credits": "4250",
    }
    obs = QuotaService.extract_quota_observations_from_headers(
        provider="openrouter",
        headers=headers,
        credential_id=uuid.uuid4(),
    )
    assert len(obs) == 1
    assert obs[0]["resource_type"] == QuotaResourceType.CREDITS.value
    assert obs[0]["limit"] == 5000
    assert obs[0]["remaining"] == 4250


def test_extract_quota_observations_standalone_retry_after() -> None:
    """Verify standalone Retry-After produces remaining=0 observation."""
    headers = {"Retry-After": "45"}
    obs = QuotaService.extract_quota_observations_from_headers(
        provider="gemini",
        headers=headers,
        credential_id=uuid.uuid4(),
    )
    assert len(obs) == 1
    assert obs[0]["remaining"] == 0
    assert obs[0]["retry_after"] == 45
    assert obs[0]["reset_at"] is not None


@pytest.mark.asyncio
async def test_record_quota_observation_upsert(
    db_session: AsyncSession,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify QuotaService.record_quota_observation creates then updates in-place."""
    _, cred = sample_user_and_credential
    service = get_quota_service()

    obs1 = {
        "credential_id": cred.id,
        "provider": "groq",
        "quota_scope": QuotaScope.MODEL.value,
        "model_id": "llama-3.3-70b",
        "resource_type": QuotaResourceType.REQUESTS.value,
        "limit": 1000,
        "remaining": 999,
        "reset_at": datetime.now(UTC) + timedelta(minutes=1),
        "retry_after": 60,
        "confidence": QuotaConfidence.CONFIRMED.value,
        "source": "header",
    }
    record1 = await service.record_quota_observation(db_session, obs1)
    await db_session.commit()

    assert record1.id is not None
    assert record1.remaining == 999

    # Second observation: update remaining to 950
    obs2 = dict(obs1)
    obs2["remaining"] = 950
    record2 = await service.record_quota_observation(db_session, obs2)
    await db_session.commit()

    assert record2.id == record1.id  # Same row updated
    assert record2.remaining == 950


@pytest.mark.asyncio
async def test_process_response_headers_and_query_states(
    db_session: AsyncSession,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify processing headers, persisting to DB, and querying with user scoping."""
    user, cred = sample_user_and_credential
    service = get_quota_service()

    headers = {
        "x-ratelimit-limit-requests": "5000",
        "x-ratelimit-remaining-requests": "4500",
        "x-ratelimit-reset-requests": "10s",
    }
    saved = await service.process_response_headers(
        db=db_session,
        provider="groq",
        headers=headers,
        credential_id=cred.id,
        model_id="llama-3.1-8b",
    )
    await db_session.commit()

    assert len(saved) == 1
    assert saved[0].remaining == 4500

    # Query with user_id filter
    items, total = await service.get_quota_states(
        db=db_session,
        user_id=user.id,
        provider="groq",
    )
    assert total >= 1
    assert any(i.credential_id == cred.id for i in items)


@pytest.mark.asyncio
async def test_check_quota_availability(
    db_session: AsyncSession,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify check_quota_availability detects exhausted capacity with future reset."""
    _, cred = sample_user_and_credential
    service = get_quota_service()

    # Case 1: Healthy capacity
    obs_healthy = {
        "credential_id": cred.id,
        "provider": "groq",
        "quota_scope": QuotaScope.MODEL.value,
        "model_id": "llama-3.3-70b",
        "resource_type": QuotaResourceType.REQUESTS.value,
        "limit": 1000,
        "remaining": 500,
        "reset_at": datetime.now(UTC) + timedelta(minutes=1),
        "confidence": QuotaConfidence.CONFIRMED.value,
    }
    await service.record_quota_observation(db_session, obs_healthy)
    await db_session.commit()

    is_avail, reason = await service.check_quota_availability(
        db_session, credential_id=cred.id, model_id="llama-3.3-70b"
    )
    assert is_avail is True
    assert reason is None

    # Case 2: Exhausted capacity (remaining=0 with future reset_at)
    obs_exhausted = dict(obs_healthy)
    obs_exhausted["remaining"] = 0
    obs_exhausted["reset_at"] = datetime.now(UTC) + timedelta(seconds=45)
    await service.record_quota_observation(db_session, obs_exhausted)
    await db_session.commit()

    is_avail_ex, reason_ex = await service.check_quota_availability(
        db_session, credential_id=cred.id, model_id="llama-3.3-70b"
    )
    assert is_avail_ex is False
    assert "Quota exhausted" in str(reason_ex)
