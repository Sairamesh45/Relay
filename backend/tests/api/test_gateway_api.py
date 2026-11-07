"""End-to-end API tests for Virtual Keys, OpenAI Gateway endpoints (/v1), and Usage Tracking."""

import uuid

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.providers.adapters.groq import GroqProvider
from app.providers.manager import get_provider_manager

settings = get_settings()


@pytest.fixture
def dev_headers() -> dict[str, str]:
    u_id = str(uuid.uuid4())
    return {
        "X-Dev-User-Id": u_id,
        "X-Dev-User-Email": f"gw_user_{u_id[:8]}@example.com",
    }


@pytest.mark.asyncio
async def test_virtual_keys_crud_endpoints(
    async_client: AsyncClient, dev_headers: dict[str, str]
) -> None:
    """Test virtual key creation, listing, retrieval, rotation, and revocation via API."""
    # 1. Create key
    create_res = await async_client.post(
        f"{settings.API_V1_PREFIX}/keys",
        json={"name": "Client App Key"},
        headers=dev_headers,
    )
    assert create_res.status_code == 201
    created_data = create_res.json()
    assert "key" in created_data
    raw_key = created_data["key"]
    key_id = created_data["id"]
    assert raw_key.startswith("uag_live_")

    # 2. List keys (raw secret must NOT be in list output)
    list_res = await async_client.get(
        f"{settings.API_V1_PREFIX}/keys",
        headers=dev_headers,
    )
    assert list_res.status_code == 200
    keys = list_res.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["id"] == key_id
    assert "key" not in keys[0]
    assert keys[0]["is_active"] is True

    # 3. Get key metadata
    get_res = await async_client.get(
        f"{settings.API_V1_PREFIX}/keys/{key_id}",
        headers=dev_headers,
    )
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Client App Key"

    # 4. Rotate key
    rotate_res = await async_client.post(
        f"{settings.API_V1_PREFIX}/keys/{key_id}/rotate",
        headers=dev_headers,
    )
    assert rotate_res.status_code == 200
    rotated_data = rotate_res.json()
    new_raw_key = rotated_data["key"]
    assert new_raw_key != raw_key
    assert rotated_data["id"] == key_id

    # 5. Revoke key
    revoke_res = await async_client.delete(
        f"{settings.API_V1_PREFIX}/keys/{key_id}",
        headers=dev_headers,
    )
    assert revoke_res.status_code == 200
    assert revoke_res.json()["is_active"] is False


@pytest.mark.asyncio
async def test_gateway_chat_completions_auth_errors(async_client: AsyncClient) -> None:
    """Verify standard OpenAI error payloads for missing, invalid, or malformed virtual keys."""
    # 1. Missing Authorization header
    res_no_auth = await async_client.post(
        "/v1/chat/completions",
        json={
            "model": "groq:llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert res_no_auth.status_code == 401
    err = res_no_auth.json()["error"]
    assert err["type"] == "authentication_error"
    assert err["code"] == "missing_api_key"

    # 2. Malformed token (not Bearer)
    res_bad_fmt = await async_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
        json={
            "model": "groq:llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert res_bad_fmt.status_code == 401
    assert res_bad_fmt.json()["error"]["code"] == "invalid_api_key"

    # 3. Invalid key hash
    res_invalid_key = await async_client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": "Bearer uag_live_completely_fake_and_unregistered_key_123456789"
        },
        json={
            "model": "groq:llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert res_invalid_key.status_code == 401
    assert res_invalid_key.json()["error"]["code"] == "invalid_api_key"


@pytest.mark.asyncio
async def test_gateway_chat_completions_e2e_non_streaming(
    async_client: AsyncClient, dev_headers: dict[str, str]
) -> None:
    """End-to-end test of POST /v1/chat/completions with connected credential and virtual key."""
    mock_response = {
        "id": "chatcmpl-e2e-mock-1",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "llama-3.3-70b-versatile",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "E2E response"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "/models" in url_str:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "llama-3.3-70b-versatile",
                            "context_window": 131072,
                        }
                    ]
                },
            )
        elif "/chat/completions" in url_str:
            return httpx.Response(200, json=mock_response)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_client:
        pm_instance = get_provider_manager()
        original_groq = pm_instance.get_provider("groq")
        groq_prov = GroqProvider(http_client=mock_client)
        pm_instance.register_provider(groq_prov)

        try:
            # 1. Create credential for Groq
            cred_res = await async_client.post(
                f"{settings.API_V1_PREFIX}/providers/groq/credentials",
                json={"api_key": "gsk-e2e-test-key", "display_name": "Groq Key"},
                headers=dev_headers,
            )
            assert cred_res.status_code == 201

            # 2. Trigger sync to populate provider_models
            sync_res = await async_client.post(
                f"{settings.API_V1_PREFIX}/models/sync",
                json={"provider": "groq"},
                headers=dev_headers,
            )
            assert sync_res.status_code == 200

            # 3. Create virtual key
            key_res = await async_client.post(
                f"{settings.API_V1_PREFIX}/keys",
                json={"name": "E2E Key"},
                headers=dev_headers,
            )
            assert key_res.status_code == 201
            virtual_key = key_res.json()["key"]

            # 4. Call /v1/models
            v1_models_res = await async_client.get(
                "/v1/models",
                headers={"Authorization": f"Bearer {virtual_key}"},
            )
            assert v1_models_res.status_code == 200
            models_data = v1_models_res.json()
            assert models_data["object"] == "list"
            assert any(
                m["id"] == "groq:llama-3.3-70b-versatile" for m in models_data["data"]
            )

            # 5. Call /v1/chat/completions non-streaming
            chat_res = await async_client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {virtual_key}"},
                json={
                    "model": "groq:llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )
            assert chat_res.status_code == 200
            chat_data = chat_res.json()
            assert chat_data["choices"][0]["message"]["content"] == "E2E response"
            assert chat_data["usage"]["total_tokens"] == 8

            # 6. Verify usage summary endpoint
            usage_res = await async_client.get(
                f"{settings.API_V1_PREFIX}/usage/summary",
                headers=dev_headers,
            )
            assert usage_res.status_code == 200
            u_summary = usage_res.json()
            assert u_summary["total_requests"] >= 1
            assert u_summary["total_tokens"] >= 8
        finally:
            if original_groq:
                pm_instance.register_provider(original_groq)
