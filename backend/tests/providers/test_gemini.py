"""Tests for Google Gemini provider adapter using mocked HTTP responses."""

import httpx
import pytest

from app.providers.adapters.gemini import GeminiProvider
from app.providers.exceptions import (
    InvalidCredentialsError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)


@pytest.mark.asyncio
async def test_gemini_validate_credentials_success() -> None:
    """Verify successful credential validation when Gemini API returns 200."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-goog-api-key") == "valid-gemini-key"
        assert "models" in str(request.url)
        return httpx.Response(
            200, json={"models": [{"name": "models/gemini-1.5-flash"}]}
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GeminiProvider(http_client=client)
        is_valid = await adapter.validate_credentials("valid-gemini-key")
        assert is_valid is True


@pytest.mark.asyncio
async def test_gemini_validate_credentials_invalid_key_400() -> None:
    """Verify that Gemini's 400 API_KEY_INVALID error is normalized to InvalidCredentialsError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": 400,
                    "message": "API key not valid. Please pass a valid API key.",
                    "status": "INVALID_ARGUMENT",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                            "reason": "API_KEY_INVALID",
                        }
                    ],
                }
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GeminiProvider(http_client=client)
        with pytest.raises(InvalidCredentialsError) as exc_info:
            await adapter.validate_credentials("invalid-bad-key")
        assert "invalid API key" in str(exc_info.value)
        assert "invalid-bad-key" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_gemini_validate_credentials_forbidden_403() -> None:
    """Verify that HTTP 403 Forbidden raises InvalidCredentialsError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"code": 403, "message": "Method not allowed for API key"}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GeminiProvider(http_client=client)
        with pytest.raises(InvalidCredentialsError):
            await adapter.validate_credentials("forbidden-key")


@pytest.mark.asyncio
async def test_gemini_list_models_normalization() -> None:
    """Verify model discovery and normalization of fields, context window, and modalities."""
    mock_response = {
        "models": [
            {
                "name": "models/gemini-1.5-pro",
                "version": "001",
                "displayName": "Gemini 1.5 Pro",
                "description": "Mid-size multimodal model that scales across a wide range of tasks",
                "inputTokenLimit": 2097152,
                "outputTokenLimit": 8192,
                "supportedGenerationMethods": ["generateContent", "countTokens"],
                "temperature": 1.0,
                "topP": 0.95,
                "topK": 64,
            },
            {
                "name": "models/text-embedding-004",
                "version": "004",
                "displayName": "Text Embedding 004",
                "description": "Generates embeddings for input text",
                "inputTokenLimit": 2048,
                "outputTokenLimit": 768,
                "supportedGenerationMethods": ["embedContent"],
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=mock_response)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GeminiProvider(http_client=client)
        models = await adapter.list_models("test-key")

        assert len(models) == 2

        # 1. Gemini 1.5 Pro
        gemini = models[0]
        assert gemini.id == "gemini-1.5-pro"
        assert gemini.provider == "gemini"
        assert gemini.name == "Gemini 1.5 Pro"
        assert gemini.context_window == 2097152
        assert "text" in gemini.input_modalities
        assert "image" in gemini.input_modalities
        assert "audio" in gemini.input_modalities
        assert "video" in gemini.input_modalities
        assert gemini.output_modalities == ["text"]
        assert gemini.supports_streaming is True
        assert gemini.supports_tools is True
        assert gemini.capabilities_confidence["streaming"] == "confirmed"
        assert gemini.capabilities_confidence["tools"] == "inferred"
        assert gemini.capabilities_confidence["vision"] == "inferred"
        assert gemini.is_confirmed("streaming") is True
        assert gemini.is_inferred("tools") is True
        assert gemini.is_inferred("vision") is True
        assert gemini.pricing is None
        assert gemini.metadata["output_token_limit"] == 8192

        # 2. Embedding Model
        embed = models[1]
        assert embed.id == "text-embedding-004"
        assert embed.context_window == 2048
        assert embed.input_modalities == ["text"]
        assert embed.output_modalities == ["embeddings"]
        assert embed.supports_streaming is False


@pytest.mark.asyncio
async def test_gemini_list_models_pagination() -> None:
    """Verify that the Gemini adapter follows nextPageToken across multiple pages."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        page_token = request.url.params.get("pageToken")

        if not page_token:
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-1.5-flash",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ],
                    "nextPageToken": "token-for-page-2",
                },
            )
        elif page_token == "token-for-page-2":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-1.5-pro",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ],
                },
            )
        return httpx.Response(400, json={"error": "Unexpected token"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GeminiProvider(http_client=client)
        models = await adapter.list_models("test-key")

        assert call_count == 2
        assert len(models) == 2
        assert models[0].id == "gemini-1.5-flash"
        assert models[1].id == "gemini-1.5-pro"


@pytest.mark.asyncio
async def test_gemini_rate_limit_429() -> None:
    """Verify that HTTP 429 raises RateLimitError with retry-after header parsed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "60"},
            json={"error": {"code": 429, "message": "Resource exhausted"}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GeminiProvider(http_client=client)
        with pytest.raises(RateLimitError) as exc_info:
            await adapter.list_models("test-key")
        assert exc_info.value.status_code == 429
        assert exc_info.value.retry_after == 60.0


@pytest.mark.asyncio
async def test_gemini_provider_unavailable_503() -> None:
    """Verify that HTTP 503 Service Unavailable raises ProviderUnavailableError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GeminiProvider(http_client=client)
        with pytest.raises(ProviderUnavailableError):
            await adapter.list_models("test-key")


@pytest.mark.asyncio
async def test_gemini_malformed_response() -> None:
    """Verify that non-JSON or malformed payload raises ProviderRequestError safely."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="Not valid JSON {}}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GeminiProvider(http_client=client)
        with pytest.raises(ProviderRequestError):
            await adapter.list_models("test-key")


@pytest.mark.asyncio
async def test_gemini_request_timeout() -> None:
    """Verify that network timeouts raise ProviderTimeoutError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GeminiProvider(http_client=client)
        with pytest.raises(ProviderTimeoutError):
            await adapter.list_models("test-key")


@pytest.mark.asyncio
async def test_gemini_list_models_pagination_deduplication() -> None:
    """Verify that models appearing on multiple pages are deduplicated."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        page_token = request.url.params.get("pageToken")

        if not page_token:
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-1.5-flash",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ],
                    "nextPageToken": "token-for-page-2",
                },
            )
        elif page_token == "token-for-page-2":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-1.5-flash",  # duplicate from page 1
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/gemini-1.5-pro",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                    ],
                },
            )
        return httpx.Response(400, json={"error": "Unexpected token"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GeminiProvider(http_client=client)
        models = await adapter.list_models("test-key")

        assert call_count == 2
        assert len(models) == 2
        assert [m.id for m in models] == ["gemini-1.5-flash", "gemini-1.5-pro"]


@pytest.mark.asyncio
async def test_gemini_list_models_pagination_cyclic_token() -> None:
    """Verify that circular nextPageToken references terminate cleanly without an infinite loop."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        page_token = request.url.params.get("pageToken")

        if not page_token:
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-1.5-flash",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ],
                    "nextPageToken": "cyclic-token-1",
                },
            )
        elif page_token == "cyclic-token-1":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-1.5-pro",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ],
                    "nextPageToken": "cyclic-token-1",  # Same token repeated
                },
            )
        return httpx.Response(400, json={"error": "Unexpected token"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GeminiProvider(http_client=client)
        models = await adapter.list_models("test-key")

        assert call_count == 2
        assert len(models) == 2


@pytest.mark.asyncio
async def test_gemini_list_models_pagination_failure_does_not_return_partial() -> None:
    """Verify that a failure on page 2 raises an exception and does not return partial models."""

    def handler(request: httpx.Request) -> httpx.Response:
        page_token = request.url.params.get("pageToken")
        if not page_token:
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-1.5-flash",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ],
                    "nextPageToken": "page-2-token",
                },
            )
        # Page 2 fails with 500
        return httpx.Response(500, json={"error": "Internal server error"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = GeminiProvider(http_client=client)
        with pytest.raises(ProviderUnavailableError):
            await adapter.list_models("test-key")
