"""API tests for Unified Model Registry endpoints, filtering, pagination, and user isolation."""

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.providers.base import BaseProvider
from app.providers.manager import get_provider_manager
from app.providers.schemas.model import CapabilityConfidence
from app.providers.schemas.model import UnifiedModel as RawModel
from app.providers.schemas.provider import ProviderInfo

settings = get_settings()


class DummyRegistryProvider(BaseProvider):
    """Mock provider registered for registry API tests."""

    @property
    def provider_id(self) -> str:
        return "api_test_prov"

    @property
    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(id="api_test_prov", name="API Test Provider")

    async def validate_credentials(self, api_key: str) -> bool:
        return True

    async def list_models(self, api_key: str) -> list[RawModel]:
        return [
            RawModel(
                id="api-model-text",
                provider="api_test_prov",
                name="API Model Text",
                context_window=32768,
                input_modalities=["text"],
                output_modalities=["text"],
                supports_streaming=True,
                supports_tools=True,
                capabilities_confidence={
                    "supports_streaming": CapabilityConfidence.CONFIRMED.value,
                    "supports_tools": CapabilityConfidence.CONFIRMED.value,
                },
            ),
            RawModel(
                id="api-model-vision",
                provider="api_test_prov",
                name="API Model Vision",
                context_window=65536,
                input_modalities=["text", "image"],
                output_modalities=["text"],
                supports_streaming=True,
                supports_tools=False,
                capabilities_confidence={
                    "supports_vision": CapabilityConfidence.CONFIRMED.value,
                },
            ),
        ]


@pytest.fixture(autouse=True)
def setup_dummy_provider() -> None:
    mgr = get_provider_manager()
    mgr.register_provider(DummyRegistryProvider())


@pytest.fixture
def user_a_headers() -> dict[str, str]:
    u_id = str(uuid.uuid4())
    return {
        "X-Dev-User-Id": u_id,
        "X-Dev-User-Email": f"user_a_{u_id[:8]}@models.test",
    }


@pytest.fixture
def user_b_headers() -> dict[str, str]:
    u_id = str(uuid.uuid4())
    return {
        "X-Dev-User-Id": u_id,
        "X-Dev-User-Email": f"user_b_{u_id[:8]}@models.test",
    }


@pytest.mark.asyncio
async def test_empty_registry_for_new_user(
    async_client: AsyncClient, user_a_headers: dict[str, str]
) -> None:
    """Verify that a user with no credentials sees an empty model catalog."""
    resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/models", headers=user_a_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_model_sync_and_list_endpoints(
    async_client: AsyncClient, user_a_headers: dict[str, str]
) -> None:
    """Register credential, trigger sync, and query models."""
    # 1. Register credential for api_test_prov
    cred_resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/api_test_prov/credentials",
        json={"api_key": "valid-api-test-key", "display_name": "Test Key"},
        headers=user_a_headers,
    )
    assert cred_resp.status_code == 201

    # 2. Trigger sync
    sync_resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/models/sync",
        json={"provider": "api_test_prov"},
        headers=user_a_headers,
    )
    assert sync_resp.status_code == 200
    sync_data = sync_resp.json()
    assert sync_data["status"] == "completed"
    assert sync_data["total_discovered"] == 2
    assert sync_data["total_added"] == 2

    # 3. Query models
    models_resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/models", headers=user_a_headers
    )
    assert models_resp.status_code == 200
    models_data = models_resp.json()
    assert models_data["total"] == 2
    assert len(models_data["items"]) == 2

    # 4. Filter by capability (vision)
    vis_resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/models?capability=vision",
        headers=user_a_headers,
    )
    assert vis_resp.status_code == 200
    vis_data = vis_resp.json()
    assert vis_data["total"] == 1
    assert "vision" in vis_data["items"][0]["canonical_id"]

    # 5. Filter by modality (multimodal)
    multi_resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/models?modality=multimodal",
        headers=user_a_headers,
    )
    assert multi_resp.status_code == 200
    multi_data = multi_resp.json()
    assert multi_data["total"] == 1

    # 6. Provider summary
    prov_summary_resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/models/providers",
        headers=user_a_headers,
    )
    assert prov_summary_resp.status_code == 200
    prov_data = prov_summary_resp.json()
    assert len(prov_data["providers"]) == 1
    assert prov_data["providers"][0]["provider"] == "api_test_prov"
    assert prov_data["providers"][0]["total_models"] == 2

    # 7. Check sync status log
    status_resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/models/sync/status",
        headers=user_a_headers,
    )
    assert status_resp.status_code == 200
    logs = status_resp.json()["logs"]
    assert len(logs) >= 1
    assert logs[0]["status"] == "completed"
    assert logs[0]["models_discovered"] == 2


@pytest.mark.asyncio
async def test_get_model_details_and_user_isolation(
    async_client: AsyncClient,
    user_a_headers: dict[str, str],
    user_b_headers: dict[str, str],
) -> None:
    """Ensure User B cannot see User A's models or offerings."""
    # User A registers and syncs
    await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/api_test_prov/credentials",
        json={"api_key": "valid-api-test-key-a", "display_name": "Key A"},
        headers=user_a_headers,
    )
    await async_client.post(
        f"{settings.API_V1_PREFIX}/models/sync",
        headers=user_a_headers,
    )

    # User A gets model details
    list_resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/models", headers=user_a_headers
    )
    items = list_resp.json()["items"]
    canonical_id = items[0]["canonical_id"]
    model_uuid = items[0]["id"]

    # User A gets details via canonical_id and UUID
    det_a = await async_client.get(
        f"{settings.API_V1_PREFIX}/models/{canonical_id}",
        headers=user_a_headers,
    )
    assert det_a.status_code == 200
    assert det_a.json()["canonical_id"] == canonical_id
    assert len(det_a.json()["provider_offerings"]) == 1

    det_uuid = await async_client.get(
        f"{settings.API_V1_PREFIX}/models/{model_uuid}",
        headers=user_a_headers,
    )
    assert det_uuid.status_code == 200

    # User B (no credentials) tries to query the same model
    det_b = await async_client.get(
        f"{settings.API_V1_PREFIX}/models/{canonical_id}",
        headers=user_b_headers,
    )
    # Strict isolation: User B gets 404 because they don't have access to this model!
    assert det_b.status_code == 404

    # User B tries to query models list
    b_list = await async_client.get(
        f"{settings.API_V1_PREFIX}/models", headers=user_b_headers
    )
    assert b_list.status_code == 200
    assert b_list.json()["total"] == 0


@pytest.mark.asyncio
async def test_sync_credential_ownership_check(
    async_client: AsyncClient,
    user_a_headers: dict[str, str],
    user_b_headers: dict[str, str],
) -> None:
    """Ensure User B cannot trigger sync on User A's credential."""
    # User A creates credential
    cred_resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/api_test_prov/credentials",
        json={"api_key": "valid-api-test-key-a", "display_name": "Key A"},
        headers=user_a_headers,
    )
    cred_id = cred_resp.json()["id"]

    # User B attempts to sync User A's credential
    sync_resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/models/sync",
        json={"credential_id": cred_id},
        headers=user_b_headers,
    )
    # Must fail with 404 Not Found (ownership boundary)
    assert sync_resp.status_code == 404


@pytest.mark.asyncio
async def test_multi_filter_combination_and_pagination(
    async_client: AsyncClient,
    user_a_headers: dict[str, str],
) -> None:
    """Verify simultaneous multi-criteria filtering and stable pagination."""
    # Register and sync
    await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/api_test_prov/credentials",
        json={"api_key": "valid-api-test-key-p", "display_name": "Key P"},
        headers=user_a_headers,
    )
    await async_client.post(
        f"{settings.API_V1_PREFIX}/models/sync",
        headers=user_a_headers,
    )

    # 1. Combined filters: provider=api_test_prov + modality=multimodal + capability=vision
    res = await async_client.get(
        f"{settings.API_V1_PREFIX}/models?provider=api_test_prov&modality=multimodal&capability=vision",
        headers=user_a_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["canonical_id"] == "api_test_prov/api-model-vision"

    # 2. Non-matching combination returns total = 0
    res_none = await async_client.get(
        f"{settings.API_V1_PREFIX}/models?provider=api_test_prov&modality=text->text&capability=vision",
        headers=user_a_headers,
    )
    assert res_none.status_code == 200
    assert res_none.json()["total"] == 0

    # 3. Pagination stability: limit=1
    page1 = await async_client.get(
        f"{settings.API_V1_PREFIX}/models?limit=1&offset=0",
        headers=user_a_headers,
    )
    assert page1.status_code == 200
    data_p1 = page1.json()
    assert len(data_p1["items"]) == 1

    page2 = await async_client.get(
        f"{settings.API_V1_PREFIX}/models?limit=1&offset=1",
        headers=user_a_headers,
    )
    assert page2.status_code == 200
    data_p2 = page2.json()
    assert len(data_p2["items"]) == 1

    # Pages 1 and 2 must have distinct canonical_id
    assert data_p1["items"][0]["canonical_id"] != data_p2["items"][0]["canonical_id"]

    # 4. Input validation: negative offset and zero limit rejected with 422
    err_limit = await async_client.get(
        f"{settings.API_V1_PREFIX}/models?limit=0",
        headers=user_a_headers,
    )
    assert err_limit.status_code == 422

    err_offset = await async_client.get(
        f"{settings.API_V1_PREFIX}/models?offset=-1",
        headers=user_a_headers,
    )
    assert err_offset.status_code == 422


@pytest.mark.asyncio
async def test_credentials_and_secrets_never_exposed_in_api_responses(
    async_client: AsyncClient,
    user_a_headers: dict[str, str],
) -> None:
    """Verify that credentials, ciphertexts, and keys are never present in model API responses."""
    secret_key = "super-confidential-api-key-999"

    # Register and sync
    await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/api_test_prov/credentials",
        json={"api_key": secret_key, "display_name": "Key Secrets"},
        headers=user_a_headers,
    )
    sync_res = await async_client.post(
        f"{settings.API_V1_PREFIX}/models/sync",
        headers=user_a_headers,
    )
    assert secret_key not in sync_res.text
    assert "encrypted_api_key" not in sync_res.text

    # List models
    list_res = await async_client.get(
        f"{settings.API_V1_PREFIX}/models",
        headers=user_a_headers,
    )
    assert secret_key not in list_res.text
    assert "encrypted_api_key" not in list_res.text

    # Model details
    items = list_res.json()["items"]
    canonical_id = items[0]["canonical_id"]
    det_res = await async_client.get(
        f"{settings.API_V1_PREFIX}/models/{canonical_id}",
        headers=user_a_headers,
    )
    assert secret_key not in det_res.text
    assert "encrypted_api_key" not in det_res.text

    # Sync status
    status_res = await async_client.get(
        f"{settings.API_V1_PREFIX}/models/sync/status",
        headers=user_a_headers,
    )
    assert secret_key not in status_res.text
    assert "encrypted_api_key" not in status_res.text


@pytest.mark.asyncio
async def test_sync_status_isolated_between_users(
    async_client: AsyncClient,
    user_a_headers: dict[str, str],
    user_b_headers: dict[str, str],
) -> None:
    """Verify sync logs generated by User A are invisible to User B."""
    await async_client.post(
        f"{settings.API_V1_PREFIX}/providers/api_test_prov/credentials",
        json={"api_key": "valid-api-test-key-iso", "display_name": "Key Iso"},
        headers=user_a_headers,
    )
    await async_client.post(
        f"{settings.API_V1_PREFIX}/models/sync",
        headers=user_a_headers,
    )

    # User A sees sync logs
    a_status = await async_client.get(
        f"{settings.API_V1_PREFIX}/models/sync/status",
        headers=user_a_headers,
    )
    assert len(a_status.json()["logs"]) >= 1

    # User B sees 0 logs
    b_status = await async_client.get(
        f"{settings.API_V1_PREFIX}/models/sync/status",
        headers=user_b_headers,
    )
    assert len(b_status.json()["logs"]) == 0
