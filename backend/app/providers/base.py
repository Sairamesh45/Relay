"""Abstract Base Provider interface for AI provider integrations."""

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from app.core.config import get_settings
from app.providers.exceptions import (
    InvalidCredentialsError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    QuotaExhaustedError,
    RateLimitError,
)
from app.providers.schemas.model import UnifiedModel
from app.providers.schemas.provider import ProviderInfo
from app.schemas.chat import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
)

settings = get_settings()


class BaseProvider(ABC):
    """Abstract base class establishing the contract for all AI provider adapters."""

    def __init__(
        self,
        timeout: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.timeout = (
            timeout if timeout is not None else settings.PROVIDER_REQUEST_TIMEOUT
        )
        self._http_client = http_client

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique machine identifier for this provider (e.g., 'gemini')."""
        pass

    @property
    @abstractmethod
    def provider_info(self) -> ProviderInfo:
        """Metadata describing the provider."""
        pass

    @abstractmethod
    async def validate_credentials(self, api_key: str) -> bool:
        """Validate whether the supplied API key is valid with the provider."""
        pass

    @abstractmethod
    async def list_models(self, api_key: str) -> list[UnifiedModel]:
        """Fetch and return all available models normalized into UnifiedModel objects."""
        pass

    async def create_chat_completion(
        self,
        api_key: str,
        request: ChatCompletionRequest,
        provider_model_id: str,
    ) -> ChatCompletionResponse:
        """Execute a non-streaming chat completion request with the provider."""
        raise NotImplementedError(
            f"Provider '{self.provider_id}' does not implement create_chat_completion"
        )

    async def stream_chat_completion(
        self,
        api_key: str,
        request: ChatCompletionRequest,
        provider_model_id: str,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """Stream chat completion chunks via Server-Sent Events."""
        raise NotImplementedError(
            f"Provider '{self.provider_id}' does not implement stream_chat_completion"
        )
        yield  # pragma: no cover

    async def _execute_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_data: Any = None,
    ) -> httpx.Response:
        """Execute an asynchronous HTTP request with standardized provider error normalization.

        Ensures that secrets are never leaked into exception messages or logs.
        """
        client = self._http_client
        if client is not None:
            return await self._send_with_client(
                client, method, url, headers=headers, params=params, json_data=json_data
            )

        async with httpx.AsyncClient(timeout=self.timeout) as temporary_client:
            return await self._send_with_client(
                temporary_client,
                method,
                url,
                headers=headers,
                params=params,
                json_data=json_data,
            )

    async def _send_with_client(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_data: Any = None,
    ) -> httpx.Response:
        """Send the request using the given client and normalize network/HTTP errors."""
        try:
            response = await client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_data,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Request to provider timed out after {self.timeout}s",
                provider=self.provider_id,
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderUnavailableError(
                "Unable to establish network connection to provider service",
                provider=self.provider_id,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                f"Underlying HTTP transport error: {type(exc).__name__}",
                provider=self.provider_id,
            ) from exc

        # Parse HTTP status codes
        if response.status_code in (401, 403):
            raise InvalidCredentialsError(
                "Authentication failed: invalid or unauthorized API key",
                provider=self.provider_id,
                status_code=response.status_code,
            )

        if response.status_code == 402:
            body_msg = ""
            try:
                body_json = response.json()
                if isinstance(body_json, dict) and "error" in body_json:
                    err_obj = body_json["error"]
                    body_msg = (
                        err_obj.get("message", "")
                        if isinstance(err_obj, dict)
                        else str(err_obj)
                    )
            except Exception:
                pass
            msg = (
                body_msg
                or "Provider account credit balance is exhausted (HTTP 402 Payment Required)"
            )
            raise QuotaExhaustedError(
                msg,
                provider=self.provider_id,
                status_code=402,
            )

        if response.status_code in (400, 422):
            body_msg = ""
            try:
                body_json = response.json()
                if isinstance(body_json, dict) and "error" in body_json:
                    err_obj = body_json["error"]
                    body_msg = (
                        err_obj.get("message", "")
                        if isinstance(err_obj, dict)
                        else str(err_obj)
                    )
            except Exception:
                pass
            raise ProviderRequestError(
                body_msg or f"Bad request to provider: {response.status_code}",
                provider=self.provider_id,
                status_code=response.status_code,
            )

        if response.status_code == 404:
            raise ProviderRequestError(
                f"Requested model or resource not found on provider ({response.status_code})",
                provider=self.provider_id,
                status_code=404,
            )

        if response.status_code == 429:
            retry_after: float | None = None
            retry_header = response.headers.get("retry-after")
            if retry_header:
                try:
                    retry_after = float(retry_header)
                except ValueError:
                    pass
            raise RateLimitError(
                "Provider rate limit or quota exceeded",
                provider=self.provider_id,
                status_code=429,
                retry_after=retry_after,
            )

        if response.status_code >= 500:
            raise ProviderUnavailableError(
                f"Provider service returned server error {response.status_code}",
                provider=self.provider_id,
                status_code=response.status_code,
            )

        return response

    @asynccontextmanager
    async def _stream_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_data: Any = None,
    ) -> AsyncGenerator[httpx.Response, None]:
        """Execute a streaming HTTP request, validating status before streaming."""
        client = self._http_client
        if client is not None:
            async with client.stream(
                method, url, headers=headers, params=params, json=json_data
            ) as response:
                await self._validate_response_status(response)
                yield response
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as temporary_client:
                async with temporary_client.stream(
                    method, url, headers=headers, params=params, json=json_data
                ) as response:
                    await self._validate_response_status(response)
                    yield response

    async def _validate_response_status(self, response: httpx.Response) -> None:
        """Validate response status, raising normalized ProviderError subclasses on error."""
        if response.status_code in (200, 201):
            return

        if response.status_code in (401, 403):
            raise InvalidCredentialsError(
                "Authentication failed: invalid or unauthorized API key",
                provider=self.provider_id,
                status_code=response.status_code,
            )

        if response.status_code == 402:
            body_msg = ""
            try:
                content = await response.aread()
                body_json = json.loads(content)
                if isinstance(body_json, dict) and "error" in body_json:
                    err_obj = body_json["error"]
                    body_msg = (
                        err_obj.get("message", "")
                        if isinstance(err_obj, dict)
                        else str(err_obj)
                    )
            except Exception:
                pass
            msg = (
                body_msg
                or "Provider account credit balance is exhausted (HTTP 402 Payment Required)"
            )
            raise QuotaExhaustedError(
                msg,
                provider=self.provider_id,
                status_code=402,
            )

        if response.status_code in (400, 422):
            body_msg = ""
            try:
                content = await response.aread()
                body_json = json.loads(content)
                if isinstance(body_json, dict) and "error" in body_json:
                    err_obj = body_json["error"]
                    body_msg = (
                        err_obj.get("message", "")
                        if isinstance(err_obj, dict)
                        else str(err_obj)
                    )
            except Exception:
                pass
            raise ProviderRequestError(
                body_msg or f"Bad request to provider: {response.status_code}",
                provider=self.provider_id,
                status_code=response.status_code,
            )

        if response.status_code == 404:
            raise ProviderRequestError(
                f"Requested model or resource not found on provider ({response.status_code})",
                provider=self.provider_id,
                status_code=404,
            )

        if response.status_code == 429:
            retry_after: float | None = None
            retry_header = response.headers.get("retry-after")
            if retry_header:
                try:
                    retry_after = float(retry_header)
                except ValueError:
                    pass
            raise RateLimitError(
                "Provider rate limit or quota exceeded",
                provider=self.provider_id,
                status_code=429,
                retry_after=retry_after,
            )

        if response.status_code >= 500:
            raise ProviderUnavailableError(
                f"Provider service returned server error {response.status_code}",
                provider=self.provider_id,
                status_code=response.status_code,
            )

        raise ProviderUnavailableError(
            f"Provider returned unexpected status code {response.status_code}",
            provider=self.provider_id,
            status_code=response.status_code,
        )
