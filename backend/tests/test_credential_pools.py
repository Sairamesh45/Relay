"""Tests for multiple-account credential pool management and selection strategies."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import (
    encrypt_api_key,
    generate_credential_fingerprint,
)
from app.models.gateway_request_log import GatewayRequestLog
from app.models.provider_credential import ProviderCredential
from app.models.provider_model import ProviderModel
from app.models.routing_policy import VirtualKeyRoutingPolicy
from app.models.unified_model import UnifiedModel
from app.models.user import User
from app.models.virtual_api_key import VirtualAPIKey
from app.services.routing.candidates import Candidate
from app.services.routing.credential_pool import CredentialPoolManager
from app.services.routing.policies import CredentialSelectionStrategy


@pytest.mark.asyncio
async def test_round_robin_selection_across_multiple_credentials(
    db_session: AsyncSession,
) -> None:
    """Verify concurrency-safe round robin cycles through multiple credentials offering the same model."""
    pool_mgr = CredentialPoolManager()

    user = User(id=uuid.uuid4(), email=f"rr_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    # 3 credentials for Gemini: Key A, Key B, Key C
    raw_keys = ["gemini-key-a", "gemini-key-b", "gemini-key-c"]
    creds: list[ProviderCredential] = []
    for k in raw_keys:
        c = ProviderCredential(
            id=uuid.uuid4(),
            user_id=user.id,
            provider="gemini",
            encrypted_api_key=encrypt_api_key(k),
            key_version=1,
            credential_fingerprint=generate_credential_fingerprint(k),
            display_name=f"Google Account {k[-1].upper()}",
            status="active",
        )
        creds.append(c)
        db_session.add(c)
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/gemini-flash-{uuid.uuid4().hex[:8]}")
    db_session.add(um)
    await db_session.flush()

    candidates: list[Candidate] = []
    for c in creds:
        pm = ProviderModel(
            unified_model_id=um.id,
            provider="gemini",
            provider_model_id="gemini-2.5-flash",
            credential_id=c.id,
            availability_status="available",
        )
        db_session.add(pm)
        candidates.append(
            Candidate(
                provider="gemini",
                provider_model_id="gemini-2.5-flash",
                gateway_model_id="gemini:gemini-2.5-flash",
                credential_id=c.id,
                credential_display_name=c.display_name,
                canonical_model_id=um.id,
                canonical_name="Gemini 2.5 Flash",
                context_window=1000000,
                max_output_tokens=8192,
                input_price_per_million=Decimal("0.10"),
                output_price_per_million=Decimal("0.40"),
                supports_streaming=True,
                supports_tools=True,
                supports_structured_output=True,
                supports_vision=True,
                supports_reasoning=True,
            )
        )
    await db_session.commit()

    key = VirtualAPIKey(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Key",
        key_prefix="uag_live_1234567",
        key_hash=f"hash_rr_{uuid.uuid4().hex}",
        is_active=True,
    )
    db_session.add(key)
    await db_session.flush()

    policy = VirtualKeyRoutingPolicy(
        virtual_api_key_id=key.id,
        user_id=user.id,
        credential_selection_strategy="round_robin",
    )
    db_session.add(policy)
    await db_session.commit()

    # Call select_from_pool 3 consecutive times: should cycle through all 3 credentials!
    cands_sorted = sorted(candidates, key=lambda c: str(c.credential_id))

    sel1, strat1, _ = await pool_mgr.select_from_pool(
        db_session, candidates, policy, {}
    )
    sel2, strat2, _ = await pool_mgr.select_from_pool(
        db_session, candidates, policy, {}
    )
    sel3, strat3, _ = await pool_mgr.select_from_pool(
        db_session, candidates, policy, {}
    )
    sel4, strat4, _ = await pool_mgr.select_from_pool(
        db_session, candidates, policy, {}
    )

    assert strat1 == "round_robin"
    assert sel1.credential_id == cands_sorted[0].credential_id
    assert sel2.credential_id == cands_sorted[1].credential_id
    assert sel3.credential_id == cands_sorted[2].credential_id
    # Wraps around on 4th call
    assert sel4.credential_id == cands_sorted[0].credential_id


@pytest.mark.asyncio
async def test_preferred_credential_strategy(db_session: AsyncSession) -> None:
    """Verify PreferredCredentialStrategy chooses the designated preferred credential if eligible."""
    pool_mgr = CredentialPoolManager()

    user = User(id=uuid.uuid4(), email=f"pref_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    cred1 = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("key-1"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("key-1"),
        status="active",
    )
    cred2 = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("key-2"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("key-2"),
        status="active",
    )
    db_session.add_all([cred1, cred2])
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/groq-{uuid.uuid4().hex[:8]}")
    db_session.add(um)
    await db_session.flush()

    cands = [
        Candidate(
            provider="groq",
            provider_model_id="llama-3.3-70b-versatile",
            gateway_model_id="groq:llama-3.3-70b-versatile",
            credential_id=cred1.id,
            credential_display_name="Key 1",
            canonical_model_id=um.id,
            canonical_name="Llama 3.3 70B",
            context_window=128000,
            max_output_tokens=8192,
            input_price_per_million=None,
            output_price_per_million=None,
            supports_streaming=True,
            supports_tools=True,
            supports_structured_output=True,
            supports_vision=False,
            supports_reasoning=False,
        ),
        Candidate(
            provider="groq",
            provider_model_id="llama-3.3-70b-versatile",
            gateway_model_id="groq:llama-3.3-70b-versatile",
            credential_id=cred2.id,
            credential_display_name="Key 2",
            canonical_model_id=um.id,
            canonical_name="Llama 3.3 70B",
            context_window=128000,
            max_output_tokens=8192,
            input_price_per_million=None,
            output_price_per_million=None,
            supports_streaming=True,
            supports_tools=True,
            supports_structured_output=True,
            supports_vision=False,
            supports_reasoning=False,
        ),
    ]

    key = VirtualAPIKey(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Key",
        key_prefix="uag_live_1234567",
        key_hash=f"hash_pref_{uuid.uuid4().hex}",
        is_active=True,
    )
    db_session.add(key)
    await db_session.flush()

    # Policy explicitly designates cred2 as preferred
    policy = VirtualKeyRoutingPolicy(
        virtual_api_key_id=key.id,
        user_id=user.id,
        preferred_credential_id=cred2.id,
        credential_selection_strategy=CredentialSelectionStrategy.PREFERRED.value,
    )
    db_session.add(policy)
    await db_session.commit()

    sel, strat, expl = await pool_mgr.select_from_pool(db_session, cands, policy, {})
    assert sel.credential_id == cred2.id
    assert "Selected preferred credential" in expl


@pytest.mark.asyncio
async def test_least_recently_used_strategy(db_session: AsyncSession) -> None:
    """Verify LeastRecentlyUsedStrategy selects the credential with the oldest execution log."""
    pool_mgr = CredentialPoolManager()

    user = User(id=uuid.uuid4(), email=f"lru_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    cred_used = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("used"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("used"),
        status="active",
    )
    cred_fresh = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("fresh"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("fresh"),
        status="active",
    )
    db_session.add_all([cred_used, cred_fresh])
    await db_session.flush()

    # Add a recent request log for cred_used
    log = GatewayRequestLog(
        user_id=user.id,
        provider_credential_id=cred_used.id,
        provider="groq",
        provider_model_id="llama-3.3-70b-versatile",
        gateway_model_id="groq:llama-3.3-70b-versatile",
        request_id=f"req_{uuid.uuid4().hex}",
        status="success",
        status_code=200,
        latency_ms=150,
    )
    db_session.add(log)
    await db_session.flush()

    um = UnifiedModel(canonical_id=f"test/lru-{uuid.uuid4().hex[:8]}")
    db_session.add(um)
    await db_session.flush()

    cands = [
        Candidate(
            provider="groq",
            provider_model_id="llama-3.3-70b-versatile",
            gateway_model_id="groq:llama-3.3-70b-versatile",
            credential_id=cred_used.id,
            credential_display_name="Used Cred",
            canonical_model_id=um.id,
            canonical_name="Llama",
            context_window=10000,
            max_output_tokens=1000,
            input_price_per_million=None,
            output_price_per_million=None,
            supports_streaming=True,
            supports_tools=True,
            supports_structured_output=True,
            supports_vision=False,
            supports_reasoning=False,
        ),
        Candidate(
            provider="groq",
            provider_model_id="llama-3.3-70b-versatile",
            gateway_model_id="groq:llama-3.3-70b-versatile",
            credential_id=cred_fresh.id,
            credential_display_name="Fresh Cred",
            canonical_model_id=um.id,
            canonical_name="Llama",
            context_window=10000,
            max_output_tokens=1000,
            input_price_per_million=None,
            output_price_per_million=None,
            supports_streaming=True,
            supports_tools=True,
            supports_structured_output=True,
            supports_vision=False,
            supports_reasoning=False,
        ),
    ]

    key = VirtualAPIKey(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Key",
        key_prefix="uag_live_1234567",
        key_hash=f"hash_lru_{uuid.uuid4().hex}",
        is_active=True,
    )
    db_session.add(key)
    await db_session.flush()

    policy = VirtualKeyRoutingPolicy(
        virtual_api_key_id=key.id,
        user_id=user.id,
        credential_selection_strategy=CredentialSelectionStrategy.LEAST_RECENTLY_USED.value,
    )
    db_session.add(policy)
    await db_session.commit()

    sel, _, _ = await pool_mgr.select_from_pool(db_session, cands, policy, {})
    # Should choose cred_fresh since it has never been used
    assert sel.credential_id == cred_fresh.id


@pytest.mark.asyncio
async def test_deferred_credential_decryption(db_session: AsyncSession) -> None:
    """Verify credentials remain encrypted in database and are decrypted only when selected."""
    pool_mgr = CredentialPoolManager()

    user = User(id=uuid.uuid4(), email=f"dec_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    raw_secret = "sk-super-secret-production-key"
    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="openrouter",
        encrypted_api_key=encrypt_api_key(raw_secret),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint(raw_secret),
        status="active",
    )
    db_session.add(cred)
    await db_session.commit()

    # DB field is ciphertext
    assert cred.encrypted_api_key != raw_secret
    assert "sk-super" not in cred.encrypted_api_key

    # Deferred decryption yields plaintext exactly
    decrypted = await pool_mgr.decrypt_credential(db_session, cred.id)
    assert decrypted == raw_secret
