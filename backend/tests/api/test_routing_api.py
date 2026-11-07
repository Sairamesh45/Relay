"""API tests for routing configuration endpoints, presets catalog, and routing preview."""

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import get_settings

settings = get_settings()


@pytest.fixture
def user_headers() -> dict[str, str]:
    u_id = str(uuid.uuid4())
    return {
        "X-Dev-User-Id": u_id,
        "X-Dev-User-Email": f"user_routing_{u_id[:8]}@example.com",
    }


@pytest.fixture
def other_user_headers() -> dict[str, str]:
    u_id = str(uuid.uuid4())
    return {
        "X-Dev-User-Id": u_id,
        "X-Dev-User-Email": f"other_user_{u_id[:8]}@example.com",
    }


@pytest.mark.asyncio
async def test_get_routing_presets_and_capabilities(
    async_client: AsyncClient,
) -> None:
    """Verify public metadata endpoints for routing presets and capabilities."""
    # 1. Presets
    presets_resp = await async_client.get(f"{settings.API_V1_PREFIX}/routing/presets")
    assert presets_resp.status_code == 200
    presets_data = presets_resp.json()["presets"]
    assert "balanced" in presets_data
    assert "quality_first" in presets_data
    assert "speed_first" in presets_data
    assert "cost_optimized" in presets_data
    assert presets_data["balanced"]["weights"]["quality"] == 0.25

    # 2. Capabilities
    caps_resp = await async_client.get(f"{settings.API_V1_PREFIX}/routing/capabilities")
    assert caps_resp.status_code == 200
    caps_data = caps_resp.json()
    assert "all_models" in caps_data["modality_profiles"]
    assert "text_only" in caps_data["modality_profiles"]
    assert "round_robin" in caps_data["credential_selection_strategies"]
    assert "streaming" in caps_data["supported_capabilities"]


@pytest.mark.asyncio
async def test_routing_policy_crud_and_validation(
    async_client: AsyncClient,
    user_headers: dict[str, str],
    other_user_headers: dict[str, str],
) -> None:
    """Test policy retrieval, updates, invalid weight rejection, and cross-user isolation."""
    # 1. Create a virtual key
    key_resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/keys",
        json={"name": "Routing Test Key"},
        headers=user_headers,
    )
    assert key_resp.status_code == 201
    key_id = key_resp.json()["id"]

    # 2. GET routing policy (defaults should be balanced)
    get_resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/keys/{key_id}/routing",
        headers=user_headers,
    )
    assert get_resp.status_code == 200
    policy_data = get_resp.json()
    assert policy_data["virtual_api_key_id"] == key_id
    assert policy_data["routing_preset"] == "balanced"
    assert policy_data["quality_weight"] == 0.25
    assert policy_data["model_access_profile"] == "all_models"

    # 3. Update preset to quality_first
    update_resp = await async_client.put(
        f"{settings.API_V1_PREFIX}/keys/{key_id}/routing",
        json={"routing_preset": "quality_first"},
        headers=user_headers,
    )
    assert update_resp.status_code == 200
    updated_data = update_resp.json()
    assert updated_data["routing_preset"] == "quality_first"
    assert updated_data["quality_weight"] == 0.60
    assert updated_data["speed_weight"] == 0.15

    # 4. Update custom weights (0.4, 0.4, 0.2, 0.0)
    custom_resp = await async_client.put(
        f"{settings.API_V1_PREFIX}/keys/{key_id}/routing",
        json={
            "quality_weight": 0.4,
            "speed_weight": 0.4,
            "availability_weight": 0.2,
            "cost_weight": 0.0,
        },
        headers=user_headers,
    )
    assert custom_resp.status_code == 200
    custom_data = custom_resp.json()
    assert custom_data["routing_mode"] == "custom"
    assert custom_data["quality_weight"] == 0.40
    assert custom_data["cost_weight"] == 0.0

    # 5. Invalid weight rejection (negative weight)
    bad_resp = await async_client.put(
        f"{settings.API_V1_PREFIX}/keys/{key_id}/routing",
        json={"quality_weight": -0.5},
        headers=user_headers,
    )
    assert bad_resp.status_code == 422

    # 6. Invalid weight rejection (all zeros)
    zeros_resp = await async_client.put(
        f"{settings.API_V1_PREFIX}/keys/{key_id}/routing",
        json={
            "quality_weight": 0.0,
            "speed_weight": 0.0,
            "availability_weight": 0.0,
            "cost_weight": 0.0,
        },
        headers=user_headers,
    )
    assert zeros_resp.status_code == 422

    # 7. Cross-user isolation: User B cannot view User A's policy
    cross_get = await async_client.get(
        f"{settings.API_V1_PREFIX}/keys/{key_id}/routing",
        headers=other_user_headers,
    )
    assert cross_get.status_code == 404

    # 8. Cross-user isolation: User B cannot modify User A's policy
    cross_put = await async_client.put(
        f"{settings.API_V1_PREFIX}/keys/{key_id}/routing",
        json={"routing_preset": "speed_first"},
        headers=other_user_headers,
    )
    assert cross_put.status_code == 404


@pytest.mark.asyncio
async def test_routing_preview_endpoint(
    async_client: AsyncClient,
    user_headers: dict[str, str],
) -> None:
    """Verify routing preview computes ranked candidates without persisting modifications."""
    # 1. Create virtual key
    key_resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/keys",
        json={"name": "Preview Key"},
        headers=user_headers,
    )
    key_id = key_resp.json()["id"]

    # 2. Preview endpoint with overrides
    preview_resp = await async_client.post(
        f"{settings.API_V1_PREFIX}/keys/{key_id}/routing/preview",
        json={
            "model": "auto",
            "policy_overrides": {
                "routing_preset": "speed_first",
                "model_access_profile": "text_only",
            },
        },
        headers=user_headers,
    )
    assert preview_resp.status_code == 200
    data = preview_resp.json()
    assert data["virtual_api_key_id"] == key_id
    assert "disclaimer" in data
    assert data["effective_weights"]["speed"] == 0.60
    assert "excluded_candidates" in data

    # 3. Verify preview did NOT modify persisted policy!
    get_resp = await async_client.get(
        f"{settings.API_V1_PREFIX}/keys/{key_id}/routing",
        headers=user_headers,
    )
    persisted = get_resp.json()
    # Still balanced, NOT speed_first!
    assert persisted["routing_preset"] == "balanced"
    assert persisted["model_access_profile"] == "all_models"
