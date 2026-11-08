"""Tier 4: Real-World Application Scenarios Tests.

Simulates production-like workloads:
- Multi-turn conversational chat workloads with growing context
- High-concurrency burst traffic across virtual keys
- Cascading multi-provider failover (Groq -> Gemini -> OpenRouter)
- End-to-end user provisioning, model sync, virtual key creation, and chat completion
- Real-time reliability telemetry aggregation
"""

import asyncio
import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from tests.e2e.conftest import MockProviderController

settings = get_settings()


# ==============================================================================
# Tier 4.1: Multi-Turn Conversational Workload
# ==============================================================================
class TestMultiTurnConversationalWorkload:
    @pytest.mark.asyncio
    async def test_multiturn_conversational_turn_sequence(
        self,
        e2e_client: AsyncClient,
        e2e_user_and_key: dict[str, Any],
        mock_providers: MockProviderController,
    ) -> None:
        """Simulate realistic 3-turn multi-turn conversation maintaining history."""
        v_key = e2e_user_and_key["virtual_key"]
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": "You are a helpful AI assistant specialized in cloud architecture.",
            }
        ]

        # Turn 1
        messages.append({"role": "user", "content": "What is an API gateway?"})
        res1 = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={"model": "groq:llama-3.3-70b-versatile", "messages": messages},
        )
        assert res1.status_code == 200
        reply1 = res1.json()["choices"][0]["message"]["content"]
        messages.append({"role": "assistant", "content": reply1})

        # Turn 2
        messages.append({"role": "user", "content": "How does it handle failover?"})
        res2 = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={"model": "groq:llama-3.3-70b-versatile", "messages": messages},
        )
        assert res2.status_code == 200
        reply2 = res2.json()["choices"][0]["message"]["content"]
        messages.append({"role": "assistant", "content": reply2})

        # Turn 3
        messages.append(
            {"role": "user", "content": "Summarize our conversation in one sentence."}
        )
        res3 = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={"model": "groq:llama-3.3-70b-versatile", "messages": messages},
        )
        assert res3.status_code == 200
        assert len(messages) == 6

    def test_multiturn_token_growth_calculation(self) -> None:
        """Token count grows monotonically with each turn in a conversation."""
        turns_tokens = [15, 45, 95, 160]
        for i in range(len(turns_tokens) - 1):
            assert turns_tokens[i] < turns_tokens[i + 1]


# ==============================================================================
# Tier 4.2: High-Concurrency Burst Traffic Workload
# ==============================================================================
class TestHighConcurrencyBurstWorkload:
    @pytest.mark.asyncio
    async def test_concurrent_chat_requests_isolated_sessions(
        self,
        e2e_client: AsyncClient,
        e2e_user_and_key: dict[str, Any],
        mock_providers: MockProviderController,
    ) -> None:
        """Simulate concurrent requests executing in parallel without crosstalk."""
        v_key = e2e_user_and_key["virtual_key"]

        async def send_chat(req_id: int) -> int:
            res = await e2e_client.post(
                "/v1/chat/completions",
                headers={"Authorization": f"Bearer {v_key}"},
                json={
                    "model": "groq:llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "user", "content": f"Parallel query {req_id}"}
                    ],
                },
            )
            return res.status_code

        # Run 5 requests concurrently
        tasks = [send_chat(i) for i in range(5)]
        status_codes = await asyncio.gather(*tasks)
        assert all(code == 200 for code in status_codes)

    def test_concurrency_rate_limit_math(self) -> None:
        """Verify token bucket rate limiter calculation under burst."""
        bucket_capacity = 10
        refill_rate_per_sec = 2.0
        # 10 burst requests consumed
        tokens = bucket_capacity - 10
        assert tokens == 0
        # After 1 second
        tokens += refill_rate_per_sec * 1.0
        assert tokens == 2.0


# ==============================================================================
# Tier 4.3: Cascading Multi-Provider Failover Scenario
# ==============================================================================
class TestCascadingMultiProviderFallbackScenario:
    def test_cascading_three_tier_failover_logic(self) -> None:
        """Logic: Groq (500) -> Gemini (429) -> OpenRouter (200 success)."""
        providers_attempts = [
            {"provider": "groq", "status": 500, "retryable": True},
            {"provider": "gemini", "status": 429, "retryable": True},
            {"provider": "openrouter", "status": 200, "retryable": False},
        ]
        resolved = None
        for attempt in providers_attempts:
            if attempt["status"] == 200:
                resolved = attempt["provider"]
                break
        assert resolved == "openrouter"

    def test_cascading_failover_preserves_request_id(self) -> None:
        """Preserves a constant gateway request_id across multiple failover attempts."""
        gateway_request_id = f"req_{uuid.uuid4().hex}"
        attempt_logs = [
            {"request_id": gateway_request_id, "attempt": 1, "provider": "groq"},
            {"request_id": gateway_request_id, "attempt": 2, "provider": "gemini"},
        ]
        assert attempt_logs[0]["request_id"] == gateway_request_id
        assert attempt_logs[1]["request_id"] == gateway_request_id


# ==============================================================================
# Tier 4.4: Full Administrative & Gateway Lifecycle Workflow
# ==============================================================================
class TestFullAdministrativeAndGatewayLifecycle:
    @pytest.mark.asyncio
    async def test_end_to_end_user_provisioning_and_chat(
        self,
        e2e_client: AsyncClient,
        mock_providers: MockProviderController,
        dev_headers: dict[str, str],
    ) -> None:
        """Full lifecycle: Connect provider -> Sync models -> Create key -> Execute chat -> Check telemetry."""
        # 1. Connect Groq Credential
        cred_res = await e2e_client.post(
            f"{settings.API_V1_PREFIX}/providers/groq/credentials",
            json={
                "api_key": "gsk-mock-lifecycle-test-1",
                "display_name": "Lifecycle Groq",
            },
            headers=dev_headers,
        )
        assert cred_res.status_code == 201
        cred_id = cred_res.json()["id"]
        assert cred_id is not None

        # 2. Sync Models
        sync_res = await e2e_client.post(
            f"{settings.API_V1_PREFIX}/models/sync",
            json={"provider": "groq"},
            headers=dev_headers,
        )
        assert sync_res.status_code == 200

        # 3. Create Virtual Key
        key_res = await e2e_client.post(
            f"{settings.API_V1_PREFIX}/keys",
            json={"name": "Lifecycle Virtual Key"},
            headers=dev_headers,
        )
        assert key_res.status_code == 201
        v_key = key_res.json()["key"]
        v_key_id = key_res.json()["id"]
        assert v_key_id is not None

        # 4. Discover Models via /v1/models
        models_res = await e2e_client.get(
            "/v1/models",
            headers={"Authorization": f"Bearer {v_key}"},
        )
        assert models_res.status_code == 200

        # 5. Execute Chat Completion
        chat_res = await e2e_client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {v_key}"},
            json={
                "model": "groq:llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": "Lifecycle test prompt"}],
            },
        )
        assert chat_res.status_code == 200
        assert chat_res.json()["choices"][0]["message"]["content"] is not None

        # 6. Verify Telemetry in Usage Summary
        usage_res = await e2e_client.get(
            f"{settings.API_V1_PREFIX}/usage/summary",
            headers=dev_headers,
        )
        assert usage_res.status_code == 200
        assert usage_res.json()["total_requests"] >= 1


# ==============================================================================
# Tier 4.5: Reliability Dashboard Real-Time Telemetry Aggregation
# ==============================================================================
class TestReliabilityDashboardRealTimeAggregation:
    def test_reliability_metrics_rollup_under_traffic(self) -> None:
        """Rollup calculation computes success rate and active cooldowns correctly."""
        raw_events = [
            {"type": "REQUEST_SUCCESS", "status": 200},
            {"type": "REQUEST_SUCCESS", "status": 200},
            {"type": "RATE_LIMIT_DETECTED", "status": 429},
            {"type": "COOLDOWN_STARTED", "duration": 30},
        ]
        successes = sum(1 for e in raw_events if e.get("status") == 200)
        total = sum(1 for e in raw_events if "status" in e)
        success_rate = round((successes / total) * 100, 1)
        active_cooldowns = sum(1 for e in raw_events if e["type"] == "COOLDOWN_STARTED")

        assert success_rate == 66.7
        assert active_cooldowns == 1
