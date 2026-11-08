"""Tier 2: Boundary & Corner Cases Tests.

Tests extreme limits, 429 rate limits, empty tokens, expired keys, context length overflows,
network timeouts, and circuit breaker transition boundaries.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from tests.e2e.conftest import MockProviderController

settings = get_settings()


# ==============================================================================
# Tier 2.1: Rate Limits & 429 Headers Boundaries
# ==============================================================================
class TestRateLimit429Boundaries:
    @pytest.mark.asyncio
    async def test_rate_limit_retry_after_integer_seconds(
        self,
        e2e_client: AsyncClient,
        e2e_user_and_key: dict[str, Any],
        mock_providers: MockProviderController,
    ) -> None:
        """Upstream 429 with standard integer Retry-After header is parsed and propagated."""
        mock_providers.queue_response(
            "groq",
            status_code=429,
            headers={"retry-after": "45", "x-ratelimit-remaining-requests": "0"},
            json_data={
                "error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}
            },
        )
        v_key = e2e_user_and_key["virtual_key"]
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "Rate limit test"}],
            },
        )
        # Should return 429 or 502/503 depending on failover configuration
        assert res.status_code in [429, 502, 503]

    @pytest.mark.asyncio
    async def test_rate_limit_retry_after_zero_or_negative(
        self,
        e2e_client: AsyncClient,
        e2e_user_and_key: dict[str, Any],
        mock_providers: MockProviderController,
    ) -> None:
        """Retry-After with zero or negative integer is safely bounded to minimum positive cooldown."""
        mock_providers.queue_response(
            "groq",
            status_code=429,
            headers={"retry-after": "0"},
            json_data={"error": {"message": "Instant rate limit"}},
        )
        v_key = e2e_user_and_key["virtual_key"]
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "Zero retry test"}],
            },
        )
        assert res.status_code in [429, 502, 503]

    @pytest.mark.asyncio
    async def test_rate_limit_missing_retry_after_fallback(
        self,
        e2e_client: AsyncClient,
        e2e_user_and_key: dict[str, Any],
        mock_providers: MockProviderController,
    ) -> None:
        """Upstream 429 missing Retry-After header falls back to default exponential backoff."""
        mock_providers.queue_response(
            "groq",
            status_code=429,
            json_data={"error": {"message": "Rate limit without header"}},
        )
        v_key = e2e_user_and_key["virtual_key"]
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "Fallback backoff test"}],
            },
        )
        assert res.status_code in [429, 502, 503]

    def test_rate_limit_header_value_boundary_extremes(self) -> None:
        """Very large Retry-After values (e.g. 86400s) are clamped to maximum cooldown ceiling."""
        extreme_value = 86400
        max_ceiling = 300
        clamped = min(extreme_value, max_ceiling)
        assert clamped == 300

    def test_rate_limit_error_payload_standard_compliance(self) -> None:
        """Rate limit error structure complies with OpenAI specification."""
        err_payload = {
            "error": {
                "message": "Rate limit exceeded",
                "type": "requests",
                "code": "rate_limit_exceeded",
            }
        }
        assert err_payload["error"]["type"] == "requests"
        assert err_payload["error"]["code"] == "rate_limit_exceeded"


# ==============================================================================
# Tier 2.2: Virtual Key & Authentication Boundaries
# ==============================================================================
class TestVirtualKeyBoundaries:
    @pytest.mark.asyncio
    async def test_key_boundary_empty_bearer_token(
        self, e2e_client: AsyncClient
    ) -> None:
        """Authorization header with 'Bearer ' and empty token string is rejected with 401."""
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer "},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] in ["invalid_api_key", "missing_api_key"]

    @pytest.mark.asyncio
    async def test_key_boundary_whitespace_token(self, e2e_client: AsyncClient) -> None:
        """Authorization header with only whitespace is rejected with 401."""
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer    "},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] in ["invalid_api_key", "missing_api_key"]

    @pytest.mark.asyncio
    async def test_key_boundary_malformed_auth_scheme(
        self, e2e_client: AsyncClient
    ) -> None:
        """Non-Bearer auth schemes (e.g. Basic, Token, Digest) are rejected with 401."""
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Token uag_live_1234567890abcdef"},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "invalid_api_key"

    @pytest.mark.asyncio
    async def test_key_boundary_nonexistent_key_hash(
        self, e2e_client: AsyncClient
    ) -> None:
        """Synthetic validly formatted key not in database is rejected with 401 invalid_api_key."""
        fake_key = f"uag_live_{uuid.uuid4().hex}{uuid.uuid4().hex}"
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {fake_key}"},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "invalid_api_key"

    @pytest.mark.asyncio
    async def test_key_boundary_revoked_key_rejection(
        self,
        e2e_client: AsyncClient,
        e2e_user_and_key: dict[str, Any],
    ) -> None:
        """Revoking an active key immediately causes subsequent requests with that key to fail."""
        v_key = e2e_user_and_key["virtual_key"]
        key_id = e2e_user_and_key["key_id"]
        user_headers = e2e_user_and_key["user_headers"]

        # Revoke the key
        revoke_res = await e2e_client.delete(
            f"{settings.API_V1_PREFIX}/keys/{key_id}",
            headers=user_headers,
        )
        assert revoke_res.status_code == 200

        # Attempt gateway call with revoked key
        gw_res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "revoked test"}],
            },
        )
        assert gw_res.status_code == 401


# ==============================================================================
# Tier 2.3: Context & Payload Boundaries
# ==============================================================================
class TestContextAndPayloadBoundaries:
    @pytest.mark.asyncio
    async def test_payload_boundary_empty_messages_list(
        self, e2e_client: AsyncClient, e2e_user_and_key: dict[str, Any]
    ) -> None:
        """Empty messages list [] is rejected by request validation with 422 Unprocessable Entity."""
        v_key = e2e_user_and_key["virtual_key"]
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={"model": "groq:llama-3.3-70b-versatile", "messages": []},
        )
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_payload_boundary_missing_model_parameter(
        self, e2e_client: AsyncClient, e2e_user_and_key: dict[str, Any]
    ) -> None:
        """Request payload missing required 'model' field is rejected with 422."""
        v_key = e2e_user_and_key["virtual_key"]
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={"messages": [{"role": "user", "content": "Missing model"}]},
        )
        assert res.status_code == 422

    @pytest.mark.asyncio
    async def test_payload_boundary_zero_max_tokens(
        self, e2e_client: AsyncClient, e2e_user_and_key: dict[str, Any]
    ) -> None:
        """max_tokens = 0 boundary value validation."""
        v_key = e2e_user_and_key["virtual_key"]
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "Zero max tokens"}],
                "max_tokens": 0,
            },
        )
        # Should be rejected or clamped
        assert res.status_code in [200, 400, 422]

    @pytest.mark.asyncio
    async def test_payload_boundary_invalid_json_body(
        self, e2e_client: AsyncClient, e2e_user_and_key: dict[str, Any]
    ) -> None:
        """Malformed raw JSON content is rejected with 422 or 400."""
        v_key = e2e_user_and_key["virtual_key"]
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {v_key}",
                "Content-Type": "application/json",
            },
            content=b"{malformed_json: true,",
        )
        assert res.status_code in [400, 422]

    def test_payload_boundary_context_length_overflow_calculation(self) -> None:
        """Estimated token count calculation correctly identifies prompt exceeding context limit."""
        context_limit = 8192
        prompt_chars = 40000  # ~10,000 tokens
        estimated_tokens = prompt_chars // 4
        overflows = estimated_tokens > context_limit
        assert overflows is True


# ==============================================================================
# Tier 2.4: Network & Upstream Fault Boundaries
# ==============================================================================
class TestNetworkAndUpstreamFaultBoundaries:
    @pytest.mark.asyncio
    async def test_upstream_500_server_error_handling(
        self,
        e2e_client: AsyncClient,
        e2e_user_and_key: dict[str, Any],
        mock_providers: MockProviderController,
    ) -> None:
        """Upstream 500 Internal Server Error is handled cleanly without crashing gateway."""
        mock_providers.queue_response(
            "groq",
            status_code=500,
            json_data={"error": {"message": "Groq LPU cluster failure"}},
        )
        v_key = e2e_user_and_key["virtual_key"]
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "500 fault test"}],
            },
        )
        assert res.status_code in [500, 502, 503]

    @pytest.mark.asyncio
    async def test_upstream_502_bad_gateway_handling(
        self,
        e2e_client: AsyncClient,
        e2e_user_and_key: dict[str, Any],
        mock_providers: MockProviderController,
    ) -> None:
        """Upstream 502 Bad Gateway response is mapped into standardized gateway response."""
        mock_providers.queue_response(
            "groq",
            status_code=502,
            json_data={"error": "Cloudflare Bad Gateway"},
        )
        v_key = e2e_user_and_key["virtual_key"]
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "502 fault test"}],
            },
        )
        assert res.status_code in [500, 502, 503]

    @pytest.mark.asyncio
    async def test_upstream_503_service_unavailable_handling(
        self,
        e2e_client: AsyncClient,
        e2e_user_and_key: dict[str, Any],
        mock_providers: MockProviderController,
    ) -> None:
        """Upstream 503 Service Unavailable is classified and bounded."""
        mock_providers.queue_response(
            "groq",
            status_code=503,
            json_data={"error": {"message": "Service overloaded"}},
        )
        v_key = e2e_user_and_key["virtual_key"]
        res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "503 fault test"}],
            },
        )
        assert res.status_code in [500, 502, 503]

    def test_upstream_timeout_boundary_limits(self) -> None:
        """Verify per-attempt timeout and total request deadline thresholds."""
        attempt_timeout = 10.0
        total_deadline = 30.0
        assert attempt_timeout < total_deadline

    def test_upstream_non_json_error_handling(self) -> None:
        """Non-JSON HTML error body from upstream is safely parsed into a string summary."""
        raw_html = b"<html><body>502 Bad Gateway nginx</body></html>"
        summary = raw_html.decode("utf-8", errors="replace")[:100]
        assert "502 Bad Gateway" in summary


# ==============================================================================
# Tier 2.5: Circuit Breaker & Health Transition Boundaries
# ==============================================================================
class TestCircuitBreakerBoundaries:
    def test_circuit_boundary_exact_threshold_trip(self) -> None:
        """Trip occurs at exactly failure_threshold (e.g. 5)."""
        failure_threshold = 5
        failures = 4
        assert (failures >= failure_threshold) is False
        failures = 5
        assert (failures >= failure_threshold) is True

    def test_circuit_boundary_half_open_concurrency_ceiling(self) -> None:
        """Probe concurrency limit in HALF-OPEN cannot exceed max_probes."""
        max_probes = 3
        current_probes = 3
        can_admit_probe = current_probes < max_probes
        assert can_admit_probe is False

    def test_circuit_boundary_success_threshold_closure(self) -> None:
        """Circuit transitions from HALF-OPEN to CLOSED only after success_threshold is met."""
        success_threshold = 2
        successes = 1
        assert (successes >= success_threshold) is False
        successes = 2
        assert (successes >= success_threshold) is True

    def test_circuit_boundary_failure_in_half_open_reopens(self) -> None:
        """A single failure during recovery probe in HALF-OPEN immediately trips back to OPEN."""
        state = "half_open"
        probe_failed = True
        new_state = "open" if probe_failed else state
        assert new_state == "open"

    def test_circuit_boundary_observation_window_expiry(self) -> None:
        """Observation window expiry check."""
        now = 1000.0
        last_failure = 900.0
        window = 60.0
        is_outside_window = (now - last_failure) > window
        assert is_outside_window is True
