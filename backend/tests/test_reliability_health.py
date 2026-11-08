"""Comprehensive tests for Credential Health State Machine, Cooldown Manager, and REST API Endpoints."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.encryption import encrypt_api_key, generate_credential_fingerprint
from app.models.provider_credential import ProviderCredential
from app.models.reliability import HealthStatus
from app.models.user import User
from app.services.credential_service import CredentialService
from app.services.reliability.cooldown_manager import (
    CooldownManager,
    CooldownScope,
)
from app.services.reliability.error_classifier import (
    ClassifiedError,
    ErrorCategory,
)
from app.services.reliability.health_service import (
    get_health_service,
)

settings = get_settings()


@pytest.fixture
async def sample_user_and_credential(
    db_session: AsyncSession,
) -> tuple[User, ProviderCredential]:
    """Create verified test user and provider credential."""
    user = User(
        id=uuid.uuid4(),
        email=f"health_user_{uuid.uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    raw_key = f"sk-health-{uuid.uuid4().hex[:12]}"
    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key(raw_key),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint(raw_key),
        status="active",
        display_name="Health Test Credential",
    )
    db_session.add(cred)
    await db_session.commit()
    await db_session.refresh(cred)
    return user, cred


# -----------------------------------------------------------------------------
# 1. Credential Health State Machine & Transitions
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_health_initializes_healthy(
    db_session: AsyncSession,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify new credential health record defaults to HEALTHY state with zero failures."""
    _, cred = sample_user_and_credential
    health_service = get_health_service()

    health = await health_service.get_or_create_health(db_session, cred.id)
    assert health.credential_id == cred.id
    assert health.health_status == HealthStatus.HEALTHY
    assert health.failure_count == 0
    assert health.consecutive_failures == 0
    assert health.cooldown_until is None


@pytest.mark.asyncio
async def test_record_success_resets_failures_and_cooldown(
    db_session: AsyncSession,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify record_success clears failures and active cooldown."""
    _, cred = sample_user_and_credential
    health_service = get_health_service()

    # Pre-populate degraded state with failures
    health = await health_service.get_or_create_health(db_session, cred.id)
    health.consecutive_failures = 4
    health.failure_count = 5
    health.health_status = HealthStatus.TEMP_UNAVAILABLE
    health.cooldown_until = datetime.now(UTC) + timedelta(minutes=5)
    await db_session.commit()

    # Record success
    updated = await health_service.record_success(db_session, cred.id)
    await db_session.commit()

    assert updated.consecutive_failures == 0
    assert updated.health_status == HealthStatus.HEALTHY
    assert updated.cooldown_until is None
    assert updated.last_success_at is not None


@pytest.mark.asyncio
async def test_non_auto_recovery_rule_for_auth_and_perm_failures(
    db_session: AsyncSession,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify AUTH_FAILED, PERM_DENIED, and DISABLED NEVER auto-recover via standard record_success."""
    _, cred = sample_user_and_credential
    health_service = get_health_service()

    for terminal_status in (
        HealthStatus.AUTH_FAILED,
        HealthStatus.PERM_DENIED,
        HealthStatus.DISABLED,
    ):
        health = await health_service.get_or_create_health(db_session, cred.id)
        health.health_status = terminal_status
        await db_session.commit()

        # Attempt to record success
        res = await health_service.record_success(db_session, cred.id)
        assert res.health_status == terminal_status  # Must NOT transition to HEALTHY


@pytest.mark.asyncio
async def test_record_failure_transitions_to_auth_failed(
    db_session: AsyncSession,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify 401 AUTHENTICATION_FAILED moves state to AUTH_FAILED without cooldown timer."""
    _, cred = sample_user_and_credential
    health_service = get_health_service()

    auth_err = ClassifiedError(
        category=ErrorCategory.AUTHENTICATION_FAILED,
        retryable=False,
        provider="groq",
        status_code=401,
        message="Invalid API Key",
    )
    health = await health_service.record_failure(db_session, cred.id, auth_err)
    await db_session.commit()

    assert health.health_status == HealthStatus.AUTH_FAILED
    assert health.consecutive_failures == 1
    assert health.last_error_category == ErrorCategory.AUTHENTICATION_FAILED.value
    assert health.cooldown_until is None  # Terminal until revalidation


@pytest.mark.asyncio
async def test_record_failure_rate_limited_and_consecutive_degradation(
    db_session: AsyncSession,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify rate limit transitions to RATE_LIMITED with cooldown, and repeated 500s transition to TEMP_UNAVAILABLE."""
    _, cred = sample_user_and_credential
    health_service = get_health_service()

    # Rate limit failure
    rl_err = ClassifiedError(
        category=ErrorCategory.RATE_LIMITED,
        retryable=True,
        provider="groq",
        status_code=429,
        retry_after=10.0,
    )
    health = await health_service.record_failure(db_session, cred.id, rl_err)
    await db_session.commit()

    assert health.health_status == HealthStatus.RATE_LIMITED
    assert health.cooldown_until is not None
    assert health.consecutive_failures == 1

    # Consecutive 500 errors
    server_err = ClassifiedError(
        category=ErrorCategory.SERVER_ERROR,
        retryable=True,
        provider="groq",
        status_code=500,
    )
    # 2nd failure -> DEGRADED or COOLING_DOWN
    health = await health_service.record_failure(db_session, cred.id, server_err)
    assert health.consecutive_failures == 2

    # 3rd failure -> TEMP_UNAVAILABLE
    health = await health_service.record_failure(db_session, cred.id, server_err)
    await db_session.commit()
    assert health.consecutive_failures == 3
    assert health.health_status == HealthStatus.TEMP_UNAVAILABLE


# -----------------------------------------------------------------------------
# 2. Cooldown Manager & Scope Awareness
# -----------------------------------------------------------------------------


def test_cooldown_exponential_backoff_and_jitter() -> None:
    """Verify exponential backoff calculation increases with failures and bounds to max."""
    mgr = CooldownManager(initial_backoff=2.0, max_cooldown=60.0)

    # Consecutive failure 1 -> ~2.0s
    cd1 = mgr.calculate_cooldown(consecutive_failures=1, jitter=False)
    assert cd1 == 2.0

    # Consecutive failure 2 -> 4.0s
    cd2 = mgr.calculate_cooldown(consecutive_failures=2, jitter=False)
    assert cd2 == 4.0

    # Consecutive failure 4 -> 16.0s
    cd4 = mgr.calculate_cooldown(consecutive_failures=4, jitter=False)
    assert cd4 == 16.0

    # High failures clamped to max 60.0s
    cd_high = mgr.calculate_cooldown(consecutive_failures=10, jitter=False)
    assert cd_high == 60.0

    # Provider Retry-After overrides exponential calculation
    cd_ra = mgr.calculate_cooldown(consecutive_failures=1, retry_after=18.5)
    assert cd_ra == 18.5


@pytest.mark.asyncio
async def test_scope_aware_cooldowns(
    db_session: AsyncSession,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify model-scoped failures only cool down the target model, keeping other models eligible."""
    _, cred = sample_user_and_credential
    health_service = get_health_service()
    cd_mgr = health_service.cooldown_manager

    health = await health_service.get_or_create_health(db_session, cred.id)

    # Model unavailable on llama-3.3-70b
    model_err = ClassifiedError(
        category=ErrorCategory.MODEL_UNAVAILABLE,
        retryable=False,
        provider="groq",
        status_code=404,
    )
    expiry, scope = await cd_mgr.apply_cooldown(
        db=db_session,
        health=health,
        error=model_err,
        model_id="llama-3.3-70b",
    )

    assert scope == CooldownScope.MODEL
    # Model 70b is cooling down
    assert cd_mgr.is_cooling_down(health, model_id="llama-3.3-70b") is True
    # Other model on same credential (llama-3.1-8b) is NOT cooling down!
    assert cd_mgr.is_cooling_down(health, model_id="llama-3.1-8b") is False
    # Credential as a whole is eligible
    assert health_service.is_candidate_eligible(health, model_id="llama-3.1-8b") is True
    # Target model is ineligible
    assert (
        health_service.is_candidate_eligible(health, model_id="llama-3.3-70b") is False
    )


# -----------------------------------------------------------------------------
# 3. Candidate Filtering & Revalidation
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filter_eligible_credentials(
    db_session: AsyncSession,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify filter_eligible_credentials excludes credentials in active cooldown or auth failure."""
    user, cred1 = sample_user_and_credential
    health_service = get_health_service()

    # Create second credential for same user
    raw_key2 = f"sk-h2-{uuid.uuid4().hex[:12]}"
    cred2 = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key(raw_key2),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint(raw_key2),
        status="active",
        display_name="Cred 2",
    )
    db_session.add(cred2)
    await db_session.commit()

    # Cred 1 is cooling down
    h1 = await health_service.get_or_create_health(db_session, cred1.id)
    h1.cooldown_until = datetime.now(UTC) + timedelta(minutes=5)

    # Cred 2 is healthy
    h2 = await health_service.get_or_create_health(db_session, cred2.id)
    h2.health_status = HealthStatus.HEALTHY
    h2.cooldown_until = None
    await db_session.commit()

    eligible = await health_service.filter_eligible_credentials(
        db_session, [cred1.id, cred2.id]
    )
    assert cred1.id not in eligible
    assert cred2.id in eligible


@pytest.mark.asyncio
async def test_revalidate_credential_health_recovery(
    db_session: AsyncSession,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify revalidate_credential_health recovers AUTH_FAILED credential to HEALTHY."""
    _, cred = sample_user_and_credential
    health_service = get_health_service()

    health = await health_service.get_or_create_health(db_session, cred.id)
    health.health_status = HealthStatus.AUTH_FAILED
    health.consecutive_failures = 5
    await db_session.commit()

    # Force revalidation with is_valid=True
    recovered = await health_service.revalidate_credential_health(
        db_session, cred.id, is_valid=True
    )
    await db_session.commit()

    assert recovered.health_status == HealthStatus.HEALTHY
    assert recovered.consecutive_failures == 0
    assert recovered.cooldown_until is None


# -----------------------------------------------------------------------------
# 4. REST API Endpoint Tests
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_get_provider_health_matrix(
    async_client: AsyncClient,
) -> None:
    """Verify GET /api/v1/health/providers returns operational status matrix for providers."""
    resp = await async_client.get(f"{settings.API_V1_PREFIX}/health/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    assert "gemini" in data["providers"]
    assert "groq" in data["providers"]
    assert "openrouter" in data["providers"]


@pytest.mark.asyncio
async def test_api_list_credential_health(
    async_client: AsyncClient,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify GET /api/v1/providers/credentials/health returns user's credential health."""
    user, cred = sample_user_and_credential

    headers = {"X-Dev-User-Id": str(user.id)}
    resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/providers/credentials/health",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_api_get_single_credential_health(
    async_client: AsyncClient,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify GET /api/v1/providers/credentials/{credential_id}/health returns specific health state."""
    user, cred = sample_user_and_credential

    headers = {"X-Dev-User-Id": str(user.id)}
    resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/providers/credentials/{cred.id}/health",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["credential_id"] == str(cred.id)
    assert data["provider"] == "groq"
    assert "health_status" in data


@pytest.mark.asyncio
async def test_api_get_single_credential_health_404_for_other_user(
    async_client: AsyncClient,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify accessing another user's credential health returns 404."""
    _, cred = sample_user_and_credential
    other_user_id = str(uuid.uuid4())

    headers = {"X-Dev-User-Id": other_user_id}
    resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/providers/credentials/{cred.id}/health",
        headers=headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_revalidate_credential_endpoint(
    async_client: AsyncClient,
    sample_user_and_credential: tuple[User, ProviderCredential],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify POST /api/v1/providers/credentials/{id}/revalidate probes and updates health."""
    user, cred = sample_user_and_credential

    async def mock_validate(
        self: CredentialService, db: AsyncSession, user: User, credential_id: uuid.UUID
    ) -> tuple[ProviderCredential, bool]:
        return cred, True

    monkeypatch.setattr(CredentialService, "validate_stored_credential", mock_validate)

    headers = {"X-Dev-User-Id": str(user.id)}
    resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/credentials/{cred.id}/revalidate",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["credential_id"] == str(cred.id)
    assert data["is_valid"] is True
    assert data["health_status"] == HealthStatus.HEALTHY.value


@pytest.mark.asyncio
async def test_api_list_quotas_endpoint(
    async_client: AsyncClient,
    sample_user_and_credential: tuple[User, ProviderCredential],
) -> None:
    """Verify GET /api/v1/quotas returns paginated quota observations."""
    user, _ = sample_user_and_credential

    headers = {"X-Dev-User-Id": str(user.id)}
    resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/quotas",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data
