"""Adversarial Challenge Verification Suite for Milestone M8 (Challenger 2).

Empirically verifies:
1. Multi-Tenant Isolation:
   - Provider credentials (list, health, validate, revalidate, delete)
   - Virtual keys (list, get, rotate, delete)
   - Routing policies (get, update, preview, credential hijacking prevention)
   - Reliability telemetry (health list, quotas, reliability events, summary)
2. Security Boundaries & Dev Auth Gating:
   - Rejection with HTTP 401 when ENABLE_DEV_AUTH=False
   - Rejection with HTTP 401 when APP_ENV="production"
   - Rejection of invalid/tampered Bearer tokens
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from tests.e2e.conftest import MockProviderController

settings = get_settings()


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
class TestMultiTenantIsolationAdversarial:
    """Stress tests proving that User A and User B cannot access, modify, or hijack each other's resources."""

    async def test_provider_credentials_tenant_isolation(
        self,
        client: AsyncClient,
        mock_providers: MockProviderController,
    ) -> None:
        """User B cannot read, validate, revalidate, or delete User A's credentials."""
        user_a_id = str(uuid.uuid4())
        user_b_id = str(uuid.uuid4())

        headers_a = {
            "X-Dev-User-Id": user_a_id,
            "X-Dev-User-Email": f"tenant_a_{user_a_id[:8]}@relay.test",
        }
        headers_b = {
            "X-Dev-User-Id": user_b_id,
            "X-Dev-User-Email": f"tenant_b_{user_b_id[:8]}@relay.test",
        }

        # 1. User A creates a credential
        res_a = await client.post(
            f"{settings.API_V1_PREFIX}/providers/groq/credentials",
            json={
                "api_key": f"gsk-tenant-a-isolated-{user_a_id[:8]}",
                "display_name": "Tenant A Secret Key",
            },
            headers=headers_a,
        )
        assert res_a.status_code == 201, res_a.text
        cred_a_id = res_a.json()["id"]

        # 2. User B lists credentials - User A's credential MUST NOT be visible
        res_b_list = await client.get(
            f"{settings.API_V1_PREFIX}/providers/credentials",
            headers=headers_b,
        )
        assert res_b_list.status_code == 200
        b_cred_ids = [c["id"] for c in res_b_list.json()]
        assert cred_a_id not in b_cred_ids

        # 3. User B attempts to read health of User A's credential -> 404
        res_b_health = await client.get(
            f"{settings.API_V1_PREFIX}/providers/credentials/{cred_a_id}/health",
            headers=headers_b,
        )
        assert res_b_health.status_code == 404

        # 4. User B attempts to validate User A's credential -> 404
        res_b_validate = await client.post(
            f"{settings.API_V1_PREFIX}/providers/credentials/{cred_a_id}/validate",
            headers=headers_b,
        )
        assert res_b_validate.status_code == 404

        # 5. User B attempts to revalidate User A's credential -> 404
        res_b_revalidate = await client.post(
            f"{settings.API_V1_PREFIX}/providers/credentials/{cred_a_id}/revalidate",
            headers=headers_b,
        )
        assert res_b_revalidate.status_code == 404

        # 6. User B attempts to delete User A's credential -> 404
        res_b_delete = await client.delete(
            f"{settings.API_V1_PREFIX}/providers/credentials/{cred_a_id}",
            headers=headers_b,
        )
        assert res_b_delete.status_code == 404

        # 7. User A verifies their credential was NOT deleted
        res_a_check = await client.get(
            f"{settings.API_V1_PREFIX}/providers/credentials",
            headers=headers_a,
        )
        assert res_a_check.status_code == 200
        a_cred_ids = [c["id"] for c in res_a_check.json()]
        assert cred_a_id in a_cred_ids

    async def test_virtual_keys_tenant_isolation(
        self,
        client: AsyncClient,
    ) -> None:
        """User B cannot read, rotate, or delete User A's virtual keys."""
        user_a_id = str(uuid.uuid4())
        user_b_id = str(uuid.uuid4())

        headers_a = {"X-Dev-User-Id": user_a_id}
        headers_b = {"X-Dev-User-Id": user_b_id}

        # 1. User A creates a virtual key
        res_a_key = await client.post(
            f"{settings.API_V1_PREFIX}/keys",
            json={"name": "Tenant A Production Key"},
            headers=headers_a,
        )
        assert res_a_key.status_code == 201, res_a_key.text
        key_a_id = res_a_key.json()["id"]

        # 2. User B lists keys - User A's key MUST NOT be visible
        res_b_keys = await client.get(
            f"{settings.API_V1_PREFIX}/keys",
            headers=headers_b,
        )
        assert res_b_keys.status_code == 200
        b_key_ids = [k["id"] for k in res_b_keys.json()["keys"]]
        assert key_a_id not in b_key_ids

        # 3. User B attempts to retrieve User A's key metadata -> 404
        res_b_get = await client.get(
            f"{settings.API_V1_PREFIX}/keys/{key_a_id}",
            headers=headers_b,
        )
        assert res_b_get.status_code == 404

        # 4. User B attempts to rotate User A's key -> 404
        res_b_rotate = await client.post(
            f"{settings.API_V1_PREFIX}/keys/{key_a_id}/rotate",
            headers=headers_b,
        )
        assert res_b_rotate.status_code == 404

        # 5. User B attempts to delete User A's key -> 404
        res_b_delete = await client.delete(
            f"{settings.API_V1_PREFIX}/keys/{key_a_id}",
            headers=headers_b,
        )
        assert res_b_delete.status_code == 404

        # 6. User A confirms key is intact and still active
        res_a_get = await client.get(
            f"{settings.API_V1_PREFIX}/keys/{key_a_id}",
            headers=headers_a,
        )
        assert res_a_get.status_code == 200
        assert res_a_get.json()["is_active"] is True

    async def test_routing_policies_isolation_and_credential_hijack_prevention(
        self,
        client: AsyncClient,
        mock_providers: MockProviderController,
    ) -> None:
        """User B cannot read/modify User A's routing policy and cannot attach User A's credential."""
        user_a_id = str(uuid.uuid4())
        user_b_id = str(uuid.uuid4())

        headers_a = {"X-Dev-User-Id": user_a_id}
        headers_b = {"X-Dev-User-Id": user_b_id}

        # 1. User A creates a credential and virtual key
        res_cred_a = await client.post(
            f"{settings.API_V1_PREFIX}/providers/groq/credentials",
            json={"api_key": f"gsk-a-policy-{user_a_id[:8]}", "display_name": "Cred A"},
            headers=headers_a,
        )
        assert res_cred_a.status_code == 201
        cred_a_id = res_cred_a.json()["id"]

        res_key_a = await client.post(
            f"{settings.API_V1_PREFIX}/keys",
            json={"name": "Key A"},
            headers=headers_a,
        )
        assert res_key_a.status_code == 201
        key_a_id = res_key_a.json()["id"]

        # 2. User B attempts to GET User A's key routing policy -> 404
        res_b_get_policy = await client.get(
            f"{settings.API_V1_PREFIX}/keys/{key_a_id}/routing",
            headers=headers_b,
        )
        assert res_b_get_policy.status_code == 404

        # 3. User B attempts to PUT User A's key routing policy -> 404
        res_b_put_policy = await client.put(
            f"{settings.API_V1_PREFIX}/keys/{key_a_id}/routing",
            json={"routing_preset": "cost_optimized"},
            headers=headers_b,
        )
        assert res_b_put_policy.status_code == 404

        # 4. User B attempts to POST preview on User A's key -> 404
        res_b_preview = await client.post(
            f"{settings.API_V1_PREFIX}/keys/{key_a_id}/routing/preview",
            json={"prompt": "Test preview"},
            headers=headers_b,
        )
        assert res_b_preview.status_code == 404

        # 5. User B creates their own key Key B
        res_key_b = await client.post(
            f"{settings.API_V1_PREFIX}/keys",
            json={"name": "Key B"},
            headers=headers_b,
        )
        assert res_key_b.status_code == 201
        key_b_id = res_key_b.json()["id"]

        # 6. HIJACK ATTEMPT: User B attempts to set preferred_credential_id = cred_a_id (User A's credential)
        res_hijack = await client.put(
            f"{settings.API_V1_PREFIX}/keys/{key_b_id}/routing",
            json={"preferred_credential_id": cred_a_id},
            headers=headers_b,
        )
        # Must strictly fail with HTTP 400 Bad Request
        assert res_hijack.status_code == 400, res_hijack.text
        assert "not found or not owned" in res_hijack.json()["detail"].lower()

    async def test_reliability_telemetry_and_quotas_tenant_isolation(
        self,
        client: AsyncClient,
        mock_providers: MockProviderController,
    ) -> None:
        """User B cannot see User A's quotas, credential health, or reliability events."""
        user_a_id = str(uuid.uuid4())
        user_b_id = str(uuid.uuid4())

        headers_a = {"X-Dev-User-Id": user_a_id}
        headers_b = {"X-Dev-User-Id": user_b_id}

        # 1. User A creates credential
        res_cred_a = await client.post(
            f"{settings.API_V1_PREFIX}/providers/groq/credentials",
            json={
                "api_key": f"gsk-telemetry-{user_a_id[:8]}",
                "display_name": "Telemetry A",
            },
            headers=headers_a,
        )
        assert res_cred_a.status_code == 201
        cred_a_id = res_cred_a.json()["id"]

        # 2. User B calls GET /api/v1/providers/credentials/health
        res_b_health = await client.get(
            f"{settings.API_V1_PREFIX}/providers/credentials/health",
            headers=headers_b,
        )
        assert res_b_health.status_code == 200
        b_health_items = res_b_health.json()["items"]
        assert all(item["credential_id"] != cred_a_id for item in b_health_items)

        # 3. User B calls GET /api/v1/quotas?credential_id={cred_a_id}
        res_b_quota = await client.get(
            f"{settings.API_V1_PREFIX}/quotas?credential_id={cred_a_id}",
            headers=headers_b,
        )
        assert res_b_quota.status_code == 200
        assert len(res_b_quota.json()["items"]) == 0

        # 4. User B calls GET /api/v1/reliability/events?credential_id={cred_a_id}
        res_b_events = await client.get(
            f"{settings.API_V1_PREFIX}/reliability/events?credential_id={cred_a_id}",
            headers=headers_b,
        )
        assert res_b_events.status_code == 200
        assert len(res_b_events.json()["items"]) == 0


@pytest.mark.asyncio
class TestSecurityBoundariesAndDevAuthGating:
    """Stress tests proving that development authentication headers cannot bypass security boundaries."""

    async def test_x_dev_user_id_strictly_rejected_when_dev_auth_disabled(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When ENABLE_DEV_AUTH=False, X-Dev-User-Id header is rejected with HTTP 401."""
        monkeypatch.setattr(settings, "ENABLE_DEV_AUTH", False)

        res = await client.get(
            f"{settings.API_V1_PREFIX}/providers/credentials",
            headers={"X-Dev-User-Id": str(uuid.uuid4())},
        )
        assert res.status_code == 401
        assert "Authentication required" in res.json()["detail"]

    async def test_x_dev_user_id_strictly_rejected_in_production_environment(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When APP_ENV='production', X-Dev-User-Id header is rejected with HTTP 401 even if ENABLE_DEV_AUTH=True."""
        monkeypatch.setattr(settings, "APP_ENV", "production")
        monkeypatch.setattr(settings, "ENABLE_DEV_AUTH", True)

        res = await client.get(
            f"{settings.API_V1_PREFIX}/providers/credentials",
            headers={"X-Dev-User-Id": str(uuid.uuid4())},
        )
        assert res.status_code == 401
        assert "Authentication required" in res.json()["detail"]

    async def test_unauthenticated_request_rejected(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When neither Bearer token nor valid dev auth is provided, request is rejected with 401."""
        monkeypatch.setattr(settings, "ENABLE_DEV_AUTH", False)

        res = await client.get(f"{settings.API_V1_PREFIX}/providers/credentials")
        assert res.status_code == 401

    async def test_invalid_bearer_token_rejected_in_production(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """In production environment, a malformed or forged Bearer token is rejected with HTTP 401."""
        monkeypatch.setattr(settings, "APP_ENV", "production")

        res = await client.get(
            f"{settings.API_V1_PREFIX}/providers/credentials",
            headers={"Authorization": "Bearer invalid.forged.token"},
        )
        assert res.status_code == 401
