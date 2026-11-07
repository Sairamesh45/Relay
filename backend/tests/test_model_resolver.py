"""Tests for gateway model identifier resolution and credential retrieval."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import encrypt_api_key, generate_credential_fingerprint
from app.core.gateway_errors import OpenAIHTTPException
from app.models.provider_credential import ProviderCredential
from app.models.provider_model import ProviderModel
from app.models.unified_model import UnifiedModel
from app.models.user import User
from app.services.model_resolver import ModelResolverService


@pytest.mark.asyncio
async def test_resolve_model_success_and_decryption(db_session: AsyncSession) -> None:
    """Verify resolution of 'provider:model_id' and correct in-memory credential decryption."""
    resolver = ModelResolverService()
    user = User(id=uuid.uuid4(), email=f"res_test_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    raw_secret = "gemini-plain-secret-key-12345"
    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="gemini",
        encrypted_api_key=encrypt_api_key(raw_secret),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint(raw_secret),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    m_suffix = uuid.uuid4().hex[:8]
    um = UnifiedModel(
        canonical_id=f"test-vendor/gemini-model-{m_suffix}",
        display_name="Gemini Test Flash",
    )
    db_session.add(um)
    await db_session.flush()

    pm = ProviderModel(
        unified_model_id=um.id,
        provider="gemini",
        provider_model_id=f"gemini-test-{m_suffix}",
        credential_id=cred.id,
        availability_status="available",
    )
    db_session.add(pm)
    await db_session.commit()

    resolved = await resolver.resolve_model(
        db_session, user, f"gemini:gemini-test-{m_suffix}"
    )

    assert resolved.provider == "gemini"
    assert resolved.provider_model_id == f"gemini-test-{m_suffix}"
    assert resolved.raw_api_key == raw_secret
    assert resolved.credential_id == str(cred.id)


@pytest.mark.asyncio
async def test_resolve_model_invalid_format_and_unknown(
    db_session: AsyncSession,
) -> None:
    """Verify malformed model strings and unknown models return appropriate OpenAI error codes."""
    resolver = ModelResolverService()
    user = User(id=uuid.uuid4(), email=f"res_err_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.commit()

    # 1. Missing colon separator
    with pytest.raises(OpenAIHTTPException) as exc_info:
        await resolver.resolve_model(db_session, user, "gemini-without-prefix")
    assert exc_info.value.status_code == 400

    # 2. Unknown model for user (no credentials connected)
    with pytest.raises(OpenAIHTTPException) as exc_info:
        await resolver.resolve_model(db_session, user, "groq:llama-3.3-70b-versatile")
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["error"]["code"] == "model_not_found"


@pytest.mark.asyncio
async def test_resolve_model_unavailable_rejected(db_session: AsyncSession) -> None:
    """Verify that models marked 'unavailable' return a clear model_unavailable error."""
    resolver = ModelResolverService()
    user = User(id=uuid.uuid4(), email=f"unavail_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="groq",
        encrypted_api_key=encrypt_api_key("key"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("key"),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    m_suffix = uuid.uuid4().hex[:8]
    um = UnifiedModel(canonical_id=f"test-llama/llama-decomm-{m_suffix}")
    db_session.add(um)
    await db_session.flush()

    pm = ProviderModel(
        unified_model_id=um.id,
        provider="groq",
        provider_model_id=f"llama-decomm-{m_suffix}",
        credential_id=cred.id,
        availability_status="unavailable",
    )
    db_session.add(pm)
    await db_session.commit()

    with pytest.raises(OpenAIHTTPException) as exc_info:
        await resolver.resolve_model(db_session, user, f"groq:llama-decomm-{m_suffix}")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error"]["code"] == "model_unavailable"


@pytest.mark.asyncio
async def test_list_gateway_models_for_user(db_session: AsyncSession) -> None:
    """Verify GET /v1/models catalog formatting strictly scoped to user credentials."""
    resolver = ModelResolverService()
    user = User(id=uuid.uuid4(), email=f"cat_test_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    cred = ProviderCredential(
        id=uuid.uuid4(),
        user_id=user.id,
        provider="openrouter",
        encrypted_api_key=encrypt_api_key("key"),
        key_version=1,
        credential_fingerprint=generate_credential_fingerprint("or_key"),
        status="active",
    )
    db_session.add(cred)
    await db_session.flush()

    cat_suffix = uuid.uuid4().hex[:8]
    um = UnifiedModel(canonical_id=f"test-openai/gpt-4o-{cat_suffix}")
    db_session.add(um)
    await db_session.flush()

    pm = ProviderModel(
        unified_model_id=um.id,
        provider="openrouter",
        provider_model_id=f"openai/gpt-4o-{cat_suffix}",
        credential_id=cred.id,
        availability_status="available",
    )
    db_session.add(pm)
    await db_session.commit()

    models = await resolver.list_user_models(db_session, user)
    assert len(models) == 1
    assert models[0].id == f"openrouter:openai/gpt-4o-{cat_suffix}"
    assert models[0].owned_by == "openrouter"
    assert models[0].object == "model"
