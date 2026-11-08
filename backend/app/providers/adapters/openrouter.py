"""OpenRouter provider adapter integrating with OpenRouter's aggregated multi-model catalog."""

import json
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from app.core.config import get_settings
from app.providers.base import BaseProvider
from app.providers.exceptions import (
    InvalidCredentialsError,
    ProviderRequestError,
)
from app.providers.schemas.model import UnifiedModel
from app.providers.schemas.provider import ProviderInfo
from app.schemas.chat import (
    ChatChoice,
    ChatChunkChoice,
    ChatChunkDelta,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatResponseMessage,
    CompletionUsage,
)

settings = get_settings()


class OpenRouterProvider(BaseProvider):
    """Adapter for OpenRouter aggregator API providing unified access to hundreds of AI models."""

    BASE_URL = "https://openrouter.ai/api/v1"

    @property
    def provider_id(self) -> str:
        return "openrouter"

    @property
    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            id="openrouter",
            name="OpenRouter",
            description="Unified gateway to frontier, open-source, and specialized models with dynamic pricing.",
            website_url="https://openrouter.ai",
            docs_url="https://openrouter.ai/docs",
        )

    def _get_headers(self, api_key: str) -> dict[str, str]:
        """Return authorization and gateway identification headers for OpenRouter."""
        return {
            "Authorization": f"Bearer {api_key.strip()}",
            "HTTP-Referer": "https://unified-ai-gateway.local",
            "X-Title": "Unified AI Gateway",
            "Accept": "application/json",
        }

    async def validate_credentials(self, api_key: str) -> bool:
        """Validate OpenRouter API key via official key-management endpoint (/api/v1/auth/key).

        Consults the authenticated key inspection endpoint rather than the public model list.
        """
        clean_key = api_key.strip()
        if settings.APP_ENV.lower() == "development" and clean_key.startswith(
            ("test_", "mock_", "dev_")
        ):
            return True

        url = f"{self.BASE_URL}/auth/key"
        headers = self._get_headers(clean_key)

        response = await self._execute_request("GET", url, headers=headers)

        if response.status_code == 200:
            return True

        if response.status_code in (401, 403):
            raise InvalidCredentialsError(
                "OpenRouter API key is invalid or unauthorized",
                provider=self.provider_id,
                status_code=response.status_code,
            )

        raise ProviderRequestError(
            f"Unexpected status code {response.status_code} during OpenRouter key validation",
            provider=self.provider_id,
            status_code=response.status_code,
        )

    def _get_dev_mock_models(self) -> list[UnifiedModel]:
        return [
            UnifiedModel(
                id="anthropic/claude-3.5-sonnet",
                provider=self.provider_id,
                name="Anthropic: Claude 3.5 Sonnet",
                context_window=200000,
                input_modalities=["text", "image"],
                output_modalities=["text"],
                supports_streaming=True,
                supports_tools=True,
                capabilities_confidence={
                    "context_window": "confirmed",
                    "streaming": "confirmed",
                    "tools": "confirmed",
                    "vision": "confirmed",
                },
                pricing=None,
                metadata={"description": "Anthropic flagship model available via OpenRouter."},
            ),
            UnifiedModel(
                id="openai/gpt-4o",
                provider=self.provider_id,
                name="OpenAI: GPT-4o",
                context_window=128000,
                input_modalities=["text", "image"],
                output_modalities=["text"],
                supports_streaming=True,
                supports_tools=True,
                capabilities_confidence={
                    "context_window": "confirmed",
                    "streaming": "confirmed",
                    "tools": "confirmed",
                    "vision": "confirmed",
                },
                pricing=None,
                metadata={"description": "OpenAI flagship omni intelligence via OpenRouter."},
            ),
        ]

    async def list_models(self, api_key: str) -> list[UnifiedModel]:
        """Fetch and normalize all available models on OpenRouter."""
        clean_key = api_key.strip()
        if settings.APP_ENV.lower() == "development" and clean_key.startswith(
            ("test_", "mock_", "dev_")
        ):
            return self._get_dev_mock_models()

        url = f"{self.BASE_URL}/models"
        headers = self._get_headers(clean_key)

        response = await self._execute_request("GET", url, headers=headers)

        if response.status_code != 200:
            raise ProviderRequestError(
                f"OpenRouter model discovery returned unexpected status {response.status_code}",
                provider=self.provider_id,
                status_code=response.status_code,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderRequestError(
                "Failed to parse OpenRouter model list JSON response",
                provider=self.provider_id,
            ) from exc

        raw_models = data.get("data")
        if not isinstance(raw_models, list):
            raise ProviderRequestError(
                "Malformed response from OpenRouter: 'data' field is missing or not a list",
                provider=self.provider_id,
            )

        models: list[UnifiedModel] = []
        seen_ids: set[str] = set()
        for raw_model in raw_models:
            if not isinstance(raw_model, dict):
                continue
            normalized = self._normalize_model(raw_model)
            if normalized.id not in seen_ids:
                seen_ids.add(normalized.id)
                models.append(normalized)

        return models

    def _normalize_model(self, raw: dict[str, Any]) -> UnifiedModel:
        """Map raw OpenRouter model item to standardized UnifiedModel schema."""
        model_id = str(raw.get("id", "unknown"))
        name = raw.get("name")

        # Context length
        context_window = raw.get("context_length")
        if context_window is not None:
            try:
                context_window = int(context_window)
            except (ValueError, TypeError):
                context_window = None

        # Modalities extraction from architecture
        architecture = raw.get("architecture") or {}
        modality_str = architecture.get("modality", "")
        input_modalities: list[str] = []
        output_modalities: list[str] = []

        if "->" in modality_str:
            in_part, out_part = modality_str.split("->", 1)
            input_modalities = [m.strip() for m in in_part.split("+") if m.strip()]
            output_modalities = [m.strip() for m in out_part.split("+") if m.strip()]
        else:
            input_modalities = ["text"]
            output_modalities = ["text"]

        # Capabilities from supported_parameters
        supported_parameters = raw.get("supported_parameters") or []
        supports_tools = (
            "tools" in supported_parameters or "tool_choice" in supported_parameters
        )
        supports_streaming = True  # Standard across OpenRouter chat models

        # Pricing normalization and free model classification
        raw_pricing = raw.get("pricing") or {}
        pricing_normalized: dict[str, Any] | None = None
        if raw_pricing:
            prompt_str = str(raw_pricing.get("prompt", "0"))
            completion_str = str(raw_pricing.get("completion", "0"))
            request_str = str(raw_pricing.get("request", "0"))
            image_str = str(raw_pricing.get("image", "0"))

            is_free = False
            try:
                prompt_val = float(prompt_str)
                completion_val = float(completion_str)
                is_free = (
                    prompt_val == 0.0 and completion_val == 0.0
                ) or model_id.endswith(":free")
            except (ValueError, TypeError):
                is_free = model_id.endswith(":free")

            pricing_normalized = {
                "prompt": prompt_str,
                "completion": completion_str,
                "request": request_str,
                "image": image_str,
                "is_free": is_free,
            }

        # OpenRouter explicitly declares modalities, parameters, and pricing in its API
        confidence: dict[str, str] = {
            "context_window": "confirmed" if context_window is not None else "unknown",
            "streaming": "confirmed",
            "tools": "confirmed" if bool(supported_parameters) else "unknown",
            "vision": "confirmed" if "modality" in architecture else "unknown",
            "pricing": "confirmed" if pricing_normalized is not None else "unknown",
        }

        metadata: dict[str, Any] = {
            "description": raw.get("description"),
            "top_provider": raw.get("top_provider"),
            "per_request_limits": raw.get("per_request_limits"),
            "supported_parameters": supported_parameters,
            "architecture": architecture,
        }

        return UnifiedModel(
            id=model_id,
            provider=self.provider_id,
            name=name,
            context_window=context_window,
            input_modalities=input_modalities,
            output_modalities=output_modalities,
            supports_streaming=supports_streaming,
            supports_tools=supports_tools,
            capabilities_confidence=confidence,
            pricing=pricing_normalized,
            metadata=metadata,
        )

    def _build_openai_payload(
        self,
        request: ChatCompletionRequest,
        provider_model_id: str,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Translate ChatCompletionRequest into OpenRouter wire payload."""
        messages: list[dict[str, Any]] = []
        for m in request.messages:
            msg: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.name:
                msg["name"] = m.name
            messages.append(msg)

        payload: dict[str, Any] = {
            "model": provider_model_id,
            "messages": messages,
            "stream": stream,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.effective_max_tokens() is not None:
            payload["max_tokens"] = request.effective_max_tokens()
        if request.stop is not None:
            payload["stop"] = request.effective_stop_sequences()
        if request.presence_penalty is not None:
            payload["presence_penalty"] = request.presence_penalty
        if request.frequency_penalty is not None:
            payload["frequency_penalty"] = request.frequency_penalty
        if request.seed is not None:
            payload["seed"] = request.seed

        return payload

    async def create_chat_completion(
        self,
        api_key: str,
        request: ChatCompletionRequest,
        provider_model_id: str,
    ) -> ChatCompletionResponse:
        """Execute non-streaming chat completion request against OpenRouter."""
        url = f"{self.BASE_URL}/chat/completions"
        headers = self._get_headers(api_key)
        payload = self._build_openai_payload(request, provider_model_id, stream=False)

        response = await self._execute_request(
            "POST", url, headers=headers, json_data=payload
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderRequestError(
                "Failed to parse OpenRouter chat completion JSON response",
                provider=self.provider_id,
            ) from exc

        choices: list[ChatChoice] = []
        for i, c in enumerate(data.get("choices", [])):
            msg_data = c.get("message") or {}
            choices.append(
                ChatChoice(
                    index=c.get("index", i),
                    message=ChatResponseMessage(
                        role=msg_data.get("role", "assistant"),
                        content=msg_data.get("content", ""),
                    ),
                    finish_reason=c.get("finish_reason", "stop"),
                )
            )

        usage: CompletionUsage | None = None
        raw_usage = data.get("usage")
        if raw_usage and isinstance(raw_usage, dict):
            usage = CompletionUsage(
                prompt_tokens=int(raw_usage.get("prompt_tokens", 0)),
                completion_tokens=int(raw_usage.get("completion_tokens", 0)),
                total_tokens=int(raw_usage.get("total_tokens", 0)),
            )

        return ChatCompletionResponse(
            id=data.get("id", f"chatcmpl-{uuid.uuid4().hex[:24]}"),
            created=data.get("created", int(time.time())),
            model=request.model,
            choices=choices,
            usage=usage,
            system_fingerprint=data.get("system_fingerprint"),
        )

    async def stream_chat_completion(
        self,
        api_key: str,
        request: ChatCompletionRequest,
        provider_model_id: str,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """Stream chat completion chunks from OpenRouter via Server-Sent Events."""
        url = f"{self.BASE_URL}/chat/completions"
        headers = self._get_headers(api_key)
        payload = self._build_openai_payload(request, provider_model_id, stream=True)

        async with self._stream_request(
            "POST", url, headers=headers, json_data=payload
        ) as response:
            async for line in response.aiter_lines():
                clean_line = line.strip()
                if not clean_line or not clean_line.startswith("data:"):
                    continue

                raw_data = clean_line.removeprefix("data:").strip()
                if raw_data == "[DONE]":
                    break

                try:
                    chunk_dict = json.loads(raw_data)
                except json.JSONDecodeError:
                    continue

                choices: list[ChatChunkChoice] = []
                for i, c in enumerate(chunk_dict.get("choices", [])):
                    delta_data = c.get("delta") or {}
                    choices.append(
                        ChatChunkChoice(
                            index=c.get("index", i),
                            delta=ChatChunkDelta(
                                role=delta_data.get("role"),
                                content=delta_data.get("content"),
                            ),
                            finish_reason=c.get("finish_reason"),
                        )
                    )

                usage: CompletionUsage | None = None
                raw_usage = chunk_dict.get("usage")
                if raw_usage and isinstance(raw_usage, dict):
                    usage = CompletionUsage(
                        prompt_tokens=int(raw_usage.get("prompt_tokens", 0)),
                        completion_tokens=int(raw_usage.get("completion_tokens", 0)),
                        total_tokens=int(raw_usage.get("total_tokens", 0)),
                    )

                yield ChatCompletionChunk(
                    id=chunk_dict.get("id", f"chatcmpl-{uuid.uuid4().hex[:24]}"),
                    created=chunk_dict.get("created", int(time.time())),
                    model=request.model,
                    choices=choices,
                    usage=usage,
                )
