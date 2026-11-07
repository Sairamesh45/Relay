"""Tests for OpenRouter provider adapter using mocked HTTP responses."""

import httpx
import pytest

from app.providers.adapters.openrouter import OpenRouterProvider
from app.providers.exceptions import (
    InvalidCredentialsError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)


@pytest.mark.asyncio
async def test_openrouter_validate_credentials_success() -> None:
    """Verify that OpenRouter validates keys via official key-management API (/auth/key)."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer sk-or-v1-valid-key"
        assert str(request.url).endswith("/auth/key")
        return httpx.Response(
            200,
            json={
                "data": {
                    "label": "My Key",
                    "usage": 1.25,
                    "limit": 100.0,
                    "is_free_tier": False,
                }
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenRouterProvider(http_client=client)
        assert await adapter.validate_credentials("sk-or-v1-valid-key") is True


@pytest.mark.asyncio
async def test_openrouter_validate_credentials_invalid_key_401() -> None:
    """Verify that HTTP 401 on /auth/key raises InvalidCredentialsError."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/auth/key")
        return httpx.Response(
            401,
            json={"error": {"code": 401, "message": "Invalid API key"}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenRouterProvider(http_client=client)
        with pytest.raises(InvalidCredentialsError):
            await adapter.validate_credentials("sk-or-invalid")


@pytest.mark.asyncio
async def test_openrouter_list_models_normalization() -> None:
    """Verify model discovery, modality parsing, tools detection, and free vs paid pricing."""
    mock_response = {
        "data": [
            {
                "id": "meta-llama/llama-3.3-70b-instruct",
                "name": "Meta: Llama 3.3 70B Instruct",
                "context_length": 131072,
                "architecture": {
                    "modality": "text->text",
                    "tokenizer": "Llama3",
                    "instruct_type": "llama3",
                },
                "pricing": {
                    "prompt": "0.0000004",
                    "completion": "0.0000016",
                    "image": "0",
                    "request": "0",
                },
                "supported_parameters": [
                    "tools",
                    "tool_choice",
                    "max_tokens",
                    "temperature",
                ],
                "description": "State of the art open model.",
            },
            {
                "id": "google/gemini-2.0-flash-exp:free",
                "name": "Google: Gemini 2.0 Flash Experimental (free)",
                "context_length": 1048576,
                "architecture": {
                    "modality": "text+image->text",
                    "tokenizer": "Gemini",
                },
                "pricing": {
                    "prompt": "0",
                    "completion": "0",
                    "image": "0",
                    "request": "0",
                },
                "supported_parameters": [
                    "tools",
                    "temperature",
                ],
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/models")
        return httpx.Response(200, json=mock_response)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenRouterProvider(http_client=client)
        models = await adapter.list_models("sk-or-test")

        assert len(models) == 2

        # 1. Paid text model
        llama = models[0]
        assert llama.id == "meta-llama/llama-3.3-70b-instruct"
        assert llama.provider == "openrouter"
        assert llama.name == "Meta: Llama 3.3 70B Instruct"
        assert llama.context_window == 131072
        assert llama.input_modalities == ["text"]
        assert llama.output_modalities == ["text"]
        assert llama.supports_tools is True
        assert llama.supports_streaming is True
        assert llama.pricing is not None
        assert llama.pricing["is_free"] is False
        assert llama.pricing["prompt"] == "0.0000004"
        assert llama.pricing["completion"] == "0.0000016"

        # 2. Free multimodal model
        gemini = models[1]
        assert gemini.id == "google/gemini-2.0-flash-exp:free"
        assert gemini.context_window == 1048576
        assert "text" in gemini.input_modalities
        assert "image" in gemini.input_modalities
        assert gemini.output_modalities == ["text"]
        assert gemini.supports_tools is True
        assert gemini.pricing is not None
        assert gemini.pricing["is_free"] is True


@pytest.mark.asyncio
async def test_openrouter_rate_limit_429() -> None:
    """Verify rate limit error handling for OpenRouter."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "30"},
            json={"error": {"code": 429, "message": "Key rate limit exceeded"}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenRouterProvider(http_client=client)
        with pytest.raises(RateLimitError) as exc_info:
            await adapter.list_models("sk-or-test")
        assert exc_info.value.retry_after == 30.0


@pytest.mark.asyncio
async def test_openrouter_server_error_502() -> None:
    """Verify that HTTP 502 Bad Gateway raises ProviderUnavailableError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="Bad Gateway")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenRouterProvider(http_client=client)
        with pytest.raises(ProviderUnavailableError):
            await adapter.list_models("sk-or-test")


@pytest.mark.asyncio
async def test_openrouter_timeout() -> None:
    """Verify timeout handling for OpenRouter requests."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timeout waiting for OpenRouter")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = OpenRouterProvider(http_client=client)
        with pytest.raises(ProviderTimeoutError):
            await adapter.list_models("sk-or-test")
