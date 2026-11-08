"""Shared fixtures and mock providers for Relay E2E Test Suite (Tiers 1-4)."""

import json
import uuid
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.providers.adapters.gemini import GeminiProvider
from app.providers.adapters.groq import GroqProvider
from app.providers.adapters.openrouter import OpenRouterProvider
from app.providers.manager import get_provider_manager

settings = get_settings()


@dataclass
class RecordedRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: Any


@dataclass
class QueuedResponse:
    status_code: int = 200
    json_data: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    stream_chunks: list[bytes] | None = None


class MockProviderController:
    """Controllable mock upstream server for Groq, Gemini, and OpenRouter."""

    def __init__(self) -> None:
        self.recorded_requests: list[RecordedRequest] = []
        self.response_queue: dict[str, list[QueuedResponse]] = {
            "groq": [],
            "gemini": [],
            "openrouter": [],
        }
        self.custom_handlers: dict[
            str, Callable[[httpx.Request], httpx.Response | None]
        ] = {}

    def reset(self) -> None:
        self.recorded_requests.clear()
        self.response_queue = {"groq": [], "gemini": [], "openrouter": []}
        self.custom_handlers.clear()

    def queue_response(
        self,
        provider: str,
        status_code: int = 200,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        stream_chunks: list[bytes] | None = None,
    ) -> None:
        p_key = provider.lower()
        if p_key not in self.response_queue:
            self.response_queue[p_key] = []
        self.response_queue[p_key].append(
            QueuedResponse(
                status_code=status_code,
                json_data=json_data,
                headers=headers or {},
                stream_chunks=stream_chunks,
            )
        )

    def set_custom_handler(
        self, provider: str, handler: Callable[[httpx.Request], httpx.Response | None]
    ) -> None:
        self.custom_handlers[provider.lower()] = handler

    def handle_request(self, provider: str, request: httpx.Request) -> httpx.Response:
        p_key = provider.lower()
        body_content = None
        try:
            body_content = (
                json.loads(request.content.decode("utf-8")) if request.content else None
            )
        except Exception:
            body_content = request.content

        self.recorded_requests.append(
            RecordedRequest(
                method=request.method,
                url=str(request.url),
                headers=dict(request.headers),
                body=body_content,
            )
        )

        # Check custom handler first
        if p_key in self.custom_handlers:
            resp = self.custom_handlers[p_key](request)
            if resp is not None:
                return resp

        # Check queued responses
        if self.response_queue.get(p_key):
            queued = self.response_queue[p_key].pop(0)
            if queued.stream_chunks:
                return httpx.Response(
                    status_code=queued.status_code,
                    headers=queued.headers,
                    content=b"".join(queued.stream_chunks),
                )
            return httpx.Response(
                status_code=queued.status_code,
                headers=queued.headers,
                json=queued.json_data if queued.json_data is not None else {},
            )

        # Fallback default responses
        url_str = str(request.url)
        if p_key == "groq":
            if "/models" in url_str:
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {"id": "llama-3.3-70b-versatile", "context_window": 131072},
                            {"id": "mixtral-8x7b-32768", "context_window": 32768},
                        ]
                    },
                )
            elif "/chat/completions" in url_str:
                return httpx.Response(
                    200,
                    json={
                        "id": f"chatcmpl-mock-groq-{uuid.uuid4().hex[:6]}",
                        "object": "chat.completion",
                        "created": 1700000000,
                        "model": "llama-3.3-70b-versatile",
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": "Mock response from Groq",
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 8,
                            "total_tokens": 18,
                        },
                    },
                )
        elif p_key == "gemini":
            if "/models" in url_str and request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "models": [
                            {
                                "name": "models/gemini-1.5-pro",
                                "supportedGenerationMethods": ["generateContent"],
                                "inputTokenLimit": 1000000,
                            },
                            {
                                "name": "models/gemini-1.5-flash",
                                "supportedGenerationMethods": ["generateContent"],
                                "inputTokenLimit": 1000000,
                            },
                        ]
                    },
                )
            elif "generateContent" in url_str:
                return httpx.Response(
                    200,
                    json={
                        "candidates": [
                            {
                                "content": {
                                    "parts": [{"text": "Mock response from Gemini"}],
                                    "role": "model",
                                },
                                "finishReason": "STOP",
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 12,
                            "candidatesTokenCount": 6,
                            "totalTokenCount": 18,
                        },
                    },
                )
        elif p_key == "openrouter":
            if "/auth/key" in url_str:
                return httpx.Response(
                    200, json={"data": {"label": "E2E Key", "limit": 1000, "usage": 0}}
                )
            elif "/models" in url_str:
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "id": "meta-llama/llama-3.3-70b-instruct",
                                "context_length": 131072,
                            }
                        ]
                    },
                )
            elif "/chat/completions" in url_str:
                return httpx.Response(
                    200,
                    json={
                        "id": f"chatcmpl-mock-or-{uuid.uuid4().hex[:6]}",
                        "object": "chat.completion",
                        "created": 1700000000,
                        "model": "meta-llama/llama-3.3-70b-instruct",
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": "Mock response from OpenRouter",
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 15,
                            "completion_tokens": 10,
                            "total_tokens": 25,
                        },
                    },
                )

        return httpx.Response(
            404, json={"error": f"Unhandled mock request for {provider}: {request.url}"}
        )


@pytest.fixture
def mock_controller() -> MockProviderController:
    controller = MockProviderController()
    return controller


@pytest.fixture
def dev_headers() -> dict[str, str]:
    u_id = str(uuid.uuid4())
    return {
        "X-Dev-User-Id": u_id,
        "X-Dev-User-Email": f"e2e_user_{u_id[:8]}@relay-gateway.internal",
    }


@pytest.fixture
async def e2e_client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def mock_providers(
    mock_controller: MockProviderController,
) -> AsyncGenerator[MockProviderController, None]:
    """Mount mock HTTP transports on Groq, Gemini, and OpenRouter providers."""
    pm = get_provider_manager()
    orig_groq = pm.get_provider("groq") if pm.is_supported("groq") else None
    orig_gemini = pm.get_provider("gemini") if pm.is_supported("gemini") else None
    orig_openrouter = (
        pm.get_provider("openrouter") if pm.is_supported("openrouter") else None
    )

    groq_transport = httpx.MockTransport(
        lambda req: mock_controller.handle_request("groq", req)
    )
    gemini_transport = httpx.MockTransport(
        lambda req: mock_controller.handle_request("gemini", req)
    )
    or_transport = httpx.MockTransport(
        lambda req: mock_controller.handle_request("openrouter", req)
    )

    async with httpx.AsyncClient(transport=groq_transport) as groq_http:
        async with httpx.AsyncClient(transport=gemini_transport) as gemini_http:
            async with httpx.AsyncClient(transport=or_transport) as or_http:
                pm.register_provider(GroqProvider(http_client=groq_http))
                pm.register_provider(GeminiProvider(http_client=gemini_http))
                pm.register_provider(OpenRouterProvider(http_client=or_http))
                try:
                    yield mock_controller
                finally:
                    if orig_groq:
                        pm.register_provider(orig_groq)
                    if orig_gemini:
                        pm.register_provider(orig_gemini)
                    if orig_openrouter:
                        pm.register_provider(orig_openrouter)


@pytest.fixture
async def e2e_user_and_key(
    e2e_client: AsyncClient,
    mock_providers: MockProviderController,
    dev_headers: dict[str, str],
) -> dict[str, Any]:
    """Helper fixture providing an established dev user with Groq credentials and a virtual key."""
    # 1. Register Groq credential
    cred_res = await e2e_client.post(
        f"{settings.API_V1_PREFIX}/providers/groq/credentials",
        json={
            "api_key": "gsk-mock-e2e-suite-key-1",
            "display_name": "E2E Groq Credential",
        },
        headers=dev_headers,
    )
    assert cred_res.status_code == 201, cred_res.text
    cred_data = cred_res.json()

    # 2. Sync models
    sync_res = await e2e_client.post(
        f"{settings.API_V1_PREFIX}/models/sync",
        json={"provider": "groq"},
        headers=dev_headers,
    )
    assert sync_res.status_code == 200, sync_res.text

    # 3. Create virtual API key
    key_res = await e2e_client.post(
        f"{settings.API_V1_PREFIX}/keys",
        json={"name": "E2E Master Virtual Key"},
        headers=dev_headers,
    )
    assert key_res.status_code == 201, key_res.text
    key_data = key_res.json()

    return {
        "user_headers": dev_headers,
        "credential": cred_data,
        "key_id": key_data["id"],
        "virtual_key": key_data["key"],
        "model": "groq:llama-3.3-70b-versatile",
    }
