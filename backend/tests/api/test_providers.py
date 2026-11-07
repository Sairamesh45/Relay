"""End-to-end API tests for Provider routes, credential vault, authentication boundary, and user isolation."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.models.provider_credential import ProviderCredential
from app.providers.base import BaseProvider
from app.providers.exceptions import InvalidCredentialsError
from app.providers.manager import get_provider_manager
from app.providers.schemas.model import UnifiedModel
from app.providers.schemas.provider import ProviderInfo

settings = get_settings()


class DummyTestProvider(BaseProvider):
    """Mock provider injected into ProviderManager for fast, isolated API tests."""

    @property
    def provider_id(self) -> str:
        return "dummy_test"

    @property
    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            id="dummy_test",
            name="Dummy Test Provider",
            description="Provider for API isolation testing",
            website_url="https://test.example.com",
            docs_url="https://test.example.com/docs",
        )

    async def validate_credentials(self, api_key: str) -> bool:
        if api_key.startswith("valid-"):
            return True
        raise InvalidCredentialsError(
            "Dummy API key rejected", provider=self.provider_id
        )

    async def list_models(self, api_key: str) -> list[UnifiedModel]:
        return [
            UnifiedModel(
                id="dummy-gpt-v1",
                provider="dummy_test",
                name="Dummy GPT v1",
                context_window=32768,
                input_modalities=["text"],
                output_modalities=["text"],
                supports_streaming=True,
                supports_tools=True,
            )
        ]


@pytest.fixture(autouse=True)
def setup_dummy_provider() -> None:
    """Register dummy_test provider before tests."""
    mgr = get_provider_manager()
    dummy = DummyTestProvider()
    mgr.register_provider(dummy)


@pytest.fixture
def user_a_headers() -> dict[str, str]:
    user_id = str(uuid.uuid4())
    return {
        "X-Dev-User-Id": user_id,
        "X-Dev-User-Email": f"user_a_{user_id[:8]}@test.local",
    }


@pytest.fixture
def user_b_headers() -> dict[str, str]:
    user_id = str(uuid.uuid4())
    return {
        "X-Dev-User-Id": user_id,
        "X-Dev-User-Email": f"user_b_{user_id[:8]}@test.local",
    }


@pytest.mark.asyncio
async def test_list_providers_endpoint(async_client: AsyncClient) -> None:
    """Verify GET /api/v1/providers returns supported provider metadata."""
    response = await async_client.get(f"{settings.API_V1_PREFIX}/providers")
    assert response.status_code == 200
    data = response.json()
    assert "providers" in data
    provider_ids = [p["id"] for p in data["providers"]]
    assert "gemini" in provider_ids
    assert "groq" in provider_ids
    assert "openrouter" in provider_ids
    assert "dummy_test" in provider_ids


@pytest.mark.asyncio
async def test_create_credential_success(
    async_client: AsyncClient, user_a_headers: dict[str, str]
) -> None:
    """Verify POST /api/v1/providers/{provider}/credentials encrypts and stores credentials."""
    raw_api_key = "valid-secret-key-1234567890abcdef"
    payload = {
        "api_key": raw_api_key,
        "display_name": "Primary Test Key",
    }
    response = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/dummy_test/credentials",
        json=payload,
        headers=user_a_headers,
    )
    assert response.status_code == 201
    data = response.json()

    assert data["provider"] == "dummy_test"
    assert data["display_name"] == "Primary Test Key"
    assert data["status"] == "active"
    assert "masked_key" in data
    assert data["masked_key"] != raw_api_key
    assert "..." in data["masked_key"]
    # Verify plaintext is never returned
    assert raw_api_key not in str(data)

    credential_id = uuid.UUID(data["id"])

    # Verify directly in database that plaintext is NOT stored
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(ProviderCredential).where(ProviderCredential.id == credential_id)
        )
        stored_cred = result.scalar_one_or_none()
        assert stored_cred is not None
        assert stored_cred.encrypted_api_key != raw_api_key
        assert raw_api_key not in stored_cred.encrypted_api_key


@pytest.mark.asyncio
async def test_create_credential_invalid_key_rejected(
    async_client: AsyncClient, user_a_headers: dict[str, str]
) -> None:
    """Verify that submitting an invalid API key returns 400 Bad Request."""
    payload = {
        "api_key": "invalid-key-that-fails",
        "display_name": "Bad Key",
    }
    response = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/dummy_test/credentials",
        json=payload,
        headers=user_a_headers,
    )
    assert response.status_code == 400
    assert "validation failed" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_credential_unsupported_provider_rejected(
    async_client: AsyncClient, user_a_headers: dict[str, str]
) -> None:
    """Verify that submitting credentials for an unknown provider returns 400 Bad Request."""
    payload = {"api_key": "valid-key-xyz"}
    response = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/unknown_ai_provider/credentials",
        json=payload,
        headers=user_a_headers,
    )
    assert response.status_code == 400
    assert "not supported" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_duplicate_credential_conflict_409(
    async_client: AsyncClient, user_a_headers: dict[str, str]
) -> None:
    """Verify that duplicate active credentials with identical API keys return 409 Conflict."""
    raw_api_key = "valid-duplicate-test-key-9999"
    payload = {"api_key": raw_api_key, "display_name": "Key 1"}

    resp1 = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/dummy_test/credentials",
        json=payload,
        headers=user_a_headers,
    )
    assert resp1.status_code == 201

    resp2 = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/dummy_test/credentials",
        json={"api_key": raw_api_key, "display_name": "Key 2"},
        headers=user_a_headers,
    )
    assert resp2.status_code == 409
    assert "already active" in resp2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_credentials_masked_and_user_scoped(
    async_client: AsyncClient,
    user_a_headers: dict[str, str],
    user_b_headers: dict[str, str],
) -> None:
    """Verify GET /api/v1/providers/credentials lists only the caller's credentials with masked keys."""
    # Create for User A
    await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/dummy_test/credentials",
        json={"api_key": "valid-user-a-key-1111", "display_name": "User A Key"},
        headers=user_a_headers,
    )

    # Create for User B
    await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/dummy_test/credentials",
        json={"api_key": "valid-user-b-key-2222", "display_name": "User B Key"},
        headers=user_b_headers,
    )

    # List for User A
    resp_a = await async_client.get(
        f"{settings.API_V1_PREFIX}/providers/credentials",
        headers=user_a_headers,
    )
    assert resp_a.status_code == 200
    creds_a = resp_a.json()
    assert any(c["display_name"] == "User A Key" for c in creds_a)
    assert not any(c["display_name"] == "User B Key" for c in creds_a)

    for c in creds_a:
        assert "encrypted_api_key" not in c
        assert "api_key" not in c
        assert "masked_key" in c


@pytest.mark.asyncio
async def test_revalidate_credential_endpoint(
    async_client: AsyncClient, user_a_headers: dict[str, str]
) -> None:
    """Verify POST /api/v1/providers/credentials/{id}/validate re-checks stored credentials."""
    resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/dummy_test/credentials",
        json={"api_key": "valid-revalidate-key-777", "display_name": "Revalidate Key"},
        headers=user_a_headers,
    )
    cred_id = resp.json()["id"]

    val_resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/credentials/{cred_id}/validate",
        headers=user_a_headers,
    )
    assert val_resp.status_code == 200
    val_data = val_resp.json()
    assert val_data["id"] == cred_id
    assert val_data["is_valid"] is True
    assert val_data["status"] == "active"
    assert val_data["last_validated_at"] is not None


@pytest.mark.asyncio
async def test_rotate_credential_endpoint(
    async_client: AsyncClient, user_a_headers: dict[str, str]
) -> None:
    """Verify POST /api/v1/providers/credentials/{id}/rotate rotates encryption key."""
    resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/dummy_test/credentials",
        json={"api_key": "valid-rotate-key-888", "display_name": "Rotate Test Key"},
        headers=user_a_headers,
    )
    cred_id = resp.json()["id"]

    rot_resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/credentials/{cred_id}/rotate",
        headers=user_a_headers,
    )
    assert rot_resp.status_code == 200
    rot_data = rot_resp.json()
    assert rot_data["id"] == cred_id
    assert rot_data["key_version"] == 1
    assert "rotated successfully" in rot_data["message"]


@pytest.mark.asyncio
async def test_discover_models_for_credential(
    async_client: AsyncClient, user_a_headers: dict[str, str]
) -> None:
    """Verify GET /api/v1/providers/credentials/{id}/models returns normalized models."""
    resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/dummy_test/credentials",
        json={"api_key": "valid-discovery-key-555"},
        headers=user_a_headers,
    )
    cred_id = resp.json()["id"]

    models_resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/providers/credentials/{cred_id}/models",
        headers=user_a_headers,
    )
    assert models_resp.status_code == 200
    models = models_resp.json()
    assert len(models) == 1
    assert models[0]["id"] == "dummy-gpt-v1"
    assert models[0]["provider"] == "dummy_test"
    assert models[0]["context_window"] == 32768
    assert models[0]["supports_streaming"] is True


@pytest.mark.asyncio
async def test_delete_credential_endpoint(
    async_client: AsyncClient, user_a_headers: dict[str, str]
) -> None:
    """Verify DELETE /api/v1/providers/credentials/{id} deletes the credential."""
    resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/dummy_test/credentials",
        json={"api_key": "valid-to-delete-key-888"},
        headers=user_a_headers,
    )
    cred_id = resp.json()["id"]

    del_resp = await async_client.delete(
        f"{settings.API_V1_PREFIX}/providers/credentials/{cred_id}",
        headers=user_a_headers,
    )
    assert del_resp.status_code == 204

    # Subsequent validate returns 404
    get_resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/credentials/{cred_id}/validate",
        headers=user_a_headers,
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_cross_user_isolation_prevented(
    async_client: AsyncClient,
    user_a_headers: dict[str, str],
    user_b_headers: dict[str, str],
) -> None:
    """Verify User B cannot access, validate, or delete User A's credential."""
    resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/dummy_test/credentials",
        json={"api_key": "valid-isolated-key-333"},
        headers=user_a_headers,
    )
    cred_id = resp.json()["id"]

    # User B attempts to validate User A's credential
    val_b = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/credentials/{cred_id}/validate",
        headers=user_b_headers,
    )
    assert val_b.status_code == 404

    # User B attempts to discover models using User A's credential
    mod_b = await async_client.get(
        f"{settings.API_V1_PREFIX}/providers/credentials/{cred_id}/models",
        headers=user_b_headers,
    )
    assert mod_b.status_code == 404

    # User B attempts to delete User A's credential
    del_b = await async_client.delete(
        f"{settings.API_V1_PREFIX}/providers/credentials/{cred_id}",
        headers=user_b_headers,
    )
    assert del_b.status_code == 404


@pytest.mark.asyncio
async def test_auth_boundary_rejects_when_dev_auth_disabled(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    user_a_headers: dict[str, str],
) -> None:
    """Verify that when ENABLE_DEV_AUTH is False, all credential requests are rejected with 401."""
    monkeypatch.setattr(settings, "ENABLE_DEV_AUTH", False)

    response = await async_client.get(
        f"{settings.API_V1_PREFIX}/providers/credentials",
        headers=user_a_headers,
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_boundary_rejects_in_production_environment(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    user_a_headers: dict[str, str],
) -> None:
    """Verify that in production (APP_ENV=production), development identity headers are rejected with 401."""
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ENABLE_DEV_AUTH", True)

    response = await async_client.get(
        f"{settings.API_V1_PREFIX}/providers/credentials",
        headers=user_a_headers,
    )
    assert response.status_code == 401
