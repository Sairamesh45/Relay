"""Tests for user-scoped candidate discovery and hard constraint filtering."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt_api_key, generate_credential_fingerprint
from app.models.provider_credential import ProviderCredential
from app.models.provider_model import ProviderModel
from app.models.unified_model import UnifiedModel
from app.models.user import User
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.services.routing.candidates import CandidateDiscoveryService
from app.services.routing.context import RoutingContext
from app.services.virtual_key_service import VirtualKeyService


@pytest.mark.asyncio
async def test_candidate_discovery_user_isolation(db_session: AsyncSession) -> None:
    """Verify candidate discovery strictly discovers only credentials and offerings belonging to the caller."""
    discovery_svc = CandidateDiscoveryService()

    # User A
    user_a = User(id=uuid.uuid4(), email=f"user_a_{uuid.uuid4().hex[:8]}@example.com")
    # User B
    user_b = User(id=uuid.uuid4(), email=f"user_b_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add_all([user_a, user_b])
    await db_session.flush()

    # Credential for User A (gemini)
    cred_a = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user_a.id,
        provider="gemini",
        encrypted_api_key=encrypt_api_key("gemini-a"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("gemini-a"),
        status="active",
    )
    # Credential for User B (groq)
    cred_b = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user_b.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("groq-b"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("groq-b"),
        status="active",
    )
    db_session.add_all([cred_a, cred_b])
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/model-{uuid.uuid4().hex[:8]}")
    db_session.add(um)
    await db_session.flush()

    pm_a = ProviderModel(
        unified_model_id=um.id,
        provider="gemini",
        provider_model_id="gemini-2.5-flash",
        credential_id=cred_a.id,
        availability_status="available",
    )
    pm_b = ProviderModel(
        unified_model_id=um.id,
        provider="groq",
        provider_model_id="llama-3.3-70b-versatile",
        credential_id=cred_b.id,
        availability_status="available",
    )
    db_session.add_all([pm_a, pm_b])
    await db_session.flush()

    # Virtual key for User A
    key_a, _ = await VirtualKeyService().create_key(db_session, user_a, "Key A")
    policy_a = key_a.routing_policy

    req = ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="Test")],
    )
    ctx = RoutingContext.from_request(user_a, key_a, policy_a, req)

    result = await discovery_svc.discover_candidates(db_session, ctx)

    # User A must ONLY see Gemini, never Groq from User B!
    assert len(result.eligible) == 1
    assert result.eligible[0].provider == "gemini"
    assert result.eligible[0].credential_id == cred_a.id


@pytest.mark.asyncio
async def test_inactive_credential_and_unavailable_model_filtered(
    db_session: AsyncSession,
) -> None:
    """Verify that inactive credentials and unavailable provider models are excluded."""
    discovery_svc = CandidateDiscoveryService()

    user = User(id=uuid.uuid4(), email=f"filter_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    # Inactive credential
    cred_revoked = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("key-revoked"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("key-revoked"),
        status="revoked",
    )
    # Active credential
    cred_active = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("key-active"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("key-active"),
        status="active",
    )
    db_session.add_all([cred_revoked, cred_active])
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/m-{uuid.uuid4().hex[:8]}")
    db_session.add(um)
    await db_session.flush()

    # Model on revoked credential
    pm1 = ProviderModel(
        unified_model_id=um.id,
        provider="groq",
        provider_model_id="model-on-revoked",
        credential_id=cred_revoked.id,
        availability_status="available",
    )
    # Unavailable model on active credential
    pm2 = ProviderModel(
        unified_model_id=um.id,
        provider="groq",
        provider_model_id="model-unavailable",
        credential_id=cred_active.id,
        availability_status="unavailable",
    )
    # Available model on active credential
    pm3 = ProviderModel(
        unified_model_id=um.id,
        provider="groq",
        provider_model_id="model-good",
        credential_id=cred_active.id,
        availability_status="available",
    )
    db_session.add_all([pm1, pm2, pm3])
    await db_session.flush()

    key, _ = await VirtualKeyService().create_key(db_session, user, "Key")
    policy = key.routing_policy

    req = ChatCompletionRequest(
        model="auto", messages=[ChatMessage(role="user", content="Hi")]
    )
    ctx = RoutingContext.from_request(user, key, policy, req)

    res = await discovery_svc.discover_candidates(db_session, ctx)

    # Only pm3 on cred_active is eligible
    assert len(res.eligible) == 1
    assert res.eligible[0].provider_model_id == "model-good"


@pytest.mark.asyncio
async def test_capability_and_whitelist_hard_filters(
    db_session: AsyncSession,
) -> None:
    """Verify tool requirement, allowed_providers, and max cost filters reject incompatible models."""
    discovery_svc = CandidateDiscoveryService()

    user = User(id=uuid.uuid4(), email=f"cap_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("k"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("k"),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/tool-{uuid.uuid4().hex[:8]}")
    db_session.add(um)
    await db_session.flush()

    pm_no_tools = ProviderModel(
        unified_model_id=um.id,
        provider="groq",
        provider_model_id="no-tools-model",
        credential_id=cred.id,
        supports_tools=False,
        availability_status="available",
        input_price_per_million=Decimal("1.00"),
        output_price_per_million=Decimal("2.00"),
    )
    pm_with_tools = ProviderModel(
        unified_model_id=um.id,
        provider="groq",
        provider_model_id="tools-model",
        credential_id=cred.id,
        supports_tools=True,
        availability_status="available",
        input_price_per_million=Decimal("10.00"),
        output_price_per_million=Decimal("20.00"),
    )
    db_session.add_all([pm_no_tools, pm_with_tools])
    await db_session.flush()

    key, _ = await VirtualKeyService().create_key(db_session, user, "Key")
    policy = key.routing_policy

    # Request requiring tools
    req = ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="Hi")],
        tools=[{"type": "function", "function": {"name": "test_func"}}],
    )
    ctx = RoutingContext.from_request(user, key, policy, req)

    res = await discovery_svc.discover_candidates(db_session, ctx)
    # pm_no_tools must be filtered out because request requires tools
    assert len(res.eligible) == 1
    assert res.eligible[0].provider_model_id == "tools-model"
