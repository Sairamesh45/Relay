"""Tests for Groq provider adapter using mocked HTTP responses."""

import httpx
import pytest

from app.providers.adapters.groq import GroqProvider
from app.providers.exceptions import (
    InvalidCredentialsError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)


@pytest.mark.asyncio
async def test_groq_validate_credentials_success() -> None:
    """Verify that a valid Groq API key returns True."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer gsk_valid_key"
        assert str(request.url).endswith("/models")
        return httpx.Response(
            200, json={"object": "list", "data": [{"id": "llama-3.3-70b-versatile"}]}
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GroqProvider(http_client=client)
        assert await adapter.validate_credentials("gsk_valid_key") is True


@pytest.mark.asyncio
async def test_groq_validate_credentials_invalid_key_401() -> None:
    """Verify that HTTP 401 raises InvalidCredentialsError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {"message": "Invalid API Key", "type": "invalid_request_error"}
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GroqProvider(http_client=client)
        with pytest.raises(InvalidCredentialsError):
            await adapter.validate_credentials("gsk_invalid_key")


@pytest.mark.asyncio
async def test_groq_list_models_normalization() -> None:
    """Verify model discovery and normalization of context_window, owner, and modalities."""
    mock_response = {
        "object": "list",
        "data": [
            {
                "id": "llama-3.3-70b-versatile",
                "object": "model",
                "created": 1731363600,
                "owned_by": "Meta",
                "active": True,
                "context_window": 131072,
                "max_completion_tokens": 32768,
            },
            {
                "id": "whisper-large-v3",
                "object": "model",
                "created": 1700000000,
                "owned_by": "OpenAI",
                "active": True,
                "context_window": 448,
            },
            {
                "id": "llama-3.2-11b-vision-preview",
                "object": "model",
                "created": 1720000000,
                "owned_by": "Meta",
                "active": True,
                "context_window": 131072,
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_response)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GroqProvider(http_client=client)
        models = await adapter.list_models("gsk_test")

        assert len(models) == 3

        # 1. Llama 3.3
        llama = models[0]
        assert llama.id == "llama-3.3-70b-versatile"
        assert llama.provider == "groq"
        assert llama.context_window == 131072
        assert llama.input_modalities == ["text"]
        assert llama.output_modalities == ["text"]
        assert llama.supports_streaming is True
        assert llama.supports_tools is True
        assert llama.capabilities_confidence["context_window"] == "confirmed"
        assert llama.capabilities_confidence["tools"] == "inferred"
        assert llama.is_confirmed("context_window") is True
        assert llama.is_inferred("tools") is True
        assert llama.metadata["owned_by"] == "Meta"
        assert llama.metadata["active"] is True

        # 2. Whisper
        whisper = models[1]
        assert whisper.id == "whisper-large-v3"
        assert whisper.input_modalities == ["audio"]
        assert whisper.output_modalities == ["text"]
        assert whisper.supports_streaming is False
        assert whisper.supports_tools is False

        # 3. Vision
        vision = models[2]
        assert vision.id == "llama-3.2-11b-vision-preview"
        assert "text" in vision.input_modalities
        assert "image" in vision.input_modalities
        assert vision.output_modalities == ["text"]


@pytest.mark.asyncio
async def test_groq_rate_limit_429() -> None:
    """Verify that HTTP 429 raises RateLimitError with retry-after metadata."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "45"},
            json={"error": {"message": "Rate limit reached for requests"}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GroqProvider(http_client=client)
        with pytest.raises(RateLimitError) as exc_info:
            await adapter.list_models("gsk_test")
        assert exc_info.value.retry_after == 45.0


@pytest.mark.asyncio
async def test_groq_server_error_500() -> None:
    """Verify that HTTP 500 raises ProviderUnavailableError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "Internal Groq Error"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GroqProvider(http_client=client)
        with pytest.raises(ProviderUnavailableError):
            await adapter.list_models("gsk_test")


@pytest.mark.asyncio
async def test_groq_timeout() -> None:
    """Verify that connection timeout raises ProviderTimeoutError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Connection to api.groq.com timed out")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GroqProvider(http_client=client)
        with pytest.raises(ProviderTimeoutError):
            await adapter.list_models("gsk_test")


@pytest.mark.asyncio
async def test_groq_malformed_json() -> None:
    """Verify that malformed data payload raises ProviderRequestError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected_key": "no data array"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GroqProvider(http_client=client)
        with pytest.raises(ProviderRequestError):
            await adapter.list_models("gsk_test")
