"""Groq provider adapter integrating with Groq's high-throughput LPU Inference Engine API."""

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


class GroqProvider(BaseProvider):
    """Adapter for Groq LPU models via OpenAI-compatible REST API."""

    BASE_URL = "https://api.groq.com/openai/v1"

    @property
    def provider_id(self) -> str:
        return "groq"

    @property
    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            id="groq",
            name="Groq",
            description="Ultra-fast LPU inference engine for open-weights models (Llama, Gemma, Whisper, Mixtral).",
            website_url="https://groq.com",
            docs_url="https://console.groq.com/docs/api-reference",
        )

    def _get_headers(self, api_key: str) -> dict[str, str]:
        """Return official Groq authorization bearer header."""
        return {
            "Authorization": f"Bearer {api_key.strip()}",
            "Accept": "application/json",
        }

    async def validate_credentials(self, api_key: str) -> bool:
        """Validate Groq API key by querying models endpoint."""
        clean_key = api_key.strip()
        if settings.APP_ENV.lower() == "development" and clean_key.startswith(
            ("test_", "mock_", "dev_")
        ):
            return True

        url = f"{self.BASE_URL}/models"
        headers = self._get_headers(clean_key)

        response = await self._execute_request("GET", url, headers=headers)

        if response.status_code == 200:
            return True

        if response.status_code in (401, 403):
            raise InvalidCredentialsError(
                "Groq API key is invalid or unauthorized",
                provider=self.provider_id,
                status_code=response.status_code,
            )

        raise ProviderRequestError(
            f"Unexpected status code {response.status_code} during Groq validation",
            provider=self.provider_id,
            status_code=response.status_code,
        )

    def _get_dev_mock_models(self) -> list[UnifiedModel]:
        return [
            UnifiedModel(
                id="llama-3.3-70b-versatile",
                provider=self.provider_id,
                name="Llama 3.3 70B Versatile",
                context_window=128000,
                input_modalities=["text"],
                output_modalities=["text"],
                supports_streaming=True,
                supports_tools=True,
                capabilities_confidence={
                    "context_window": "confirmed",
                    "streaming": "confirmed",
                    "tools": "confirmed",
                },
                pricing=None,
                metadata={"description": "State-of-the-art open weights model on Groq LPUs."},
            ),
            UnifiedModel(
                id="llama-3.1-8b-instant",
                provider=self.provider_id,
                name="Llama 3.1 8B Instant",
                context_window=128000,
                input_modalities=["text"],
                output_modalities=["text"],
                supports_streaming=True,
                supports_tools=True,
                capabilities_confidence={
                    "context_window": "confirmed",
                    "streaming": "confirmed",
                    "tools": "confirmed",
                },
                pricing=None,
                metadata={"description": "Ultra fast sub-second inference open model on Groq."},
            ),
            UnifiedModel(
                id="mixtral-8x7b-32768",
                provider=self.provider_id,
                name="Mixtral 8x7B",
                context_window=32768,
                input_modalities=["text"],
                output_modalities=["text"],
                supports_streaming=True,
                supports_tools=False,
                capabilities_confidence={
                    "context_window": "confirmed",
                    "streaming": "confirmed",
                    "tools": "confirmed",
                },
                pricing=None,
                metadata={"description": "Mistral AI MoE model running on Groq LPUs."},
            ),
        ]

    async def list_models(self, api_key: str) -> list[UnifiedModel]:
        """Fetch and normalize all available models on Groq."""
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
                f"Groq model discovery returned unexpected status {response.status_code}",
                provider=self.provider_id,
                status_code=response.status_code,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderRequestError(
                "Failed to parse Groq model list JSON response",
                provider=self.provider_id,
            ) from exc

        raw_models = data.get("data")
        if not isinstance(raw_models, list):
            raise ProviderRequestError(
                "Malformed response from Groq: 'data' field is missing or not a list",
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
        """Map raw Groq model metadata to UnifiedModel schema."""
        model_id = str(raw.get("id", "unknown"))
        model_id_lower = model_id.lower()

        # Groq exposes context_window directly on model objects
        context_window = raw.get("context_window")
        if context_window is not None:
            try:
                context_window = int(context_window)
            except (ValueError, TypeError):
                context_window = None

        # Modalities
        if "whisper" in model_id_lower:
            input_modalities = ["audio"]
            output_modalities = ["text"]
            supports_streaming = False
            supports_tools = False
        elif "vision" in model_id_lower or "llava" in model_id_lower:
            input_modalities = ["text", "image"]
            output_modalities = ["text"]
            supports_streaming = True
            supports_tools = "tool" in model_id_lower or "versatile" in model_id_lower
        else:
            input_modalities = ["text"]
            output_modalities = ["text"]
            supports_streaming = True
            supports_tools = any(
                family in model_id_lower
                for family in ["llama-3", "llama3", "mixtral", "tool", "versatile"]
            )

        # Distinguish confirmed, inferred, and unknown capabilities
        confidence: dict[str, str] = {
            "context_window": "confirmed" if context_window is not None else "unknown",
            "streaming": "confirmed" if supports_streaming else "unknown",
            "tools": "inferred"
            if supports_tools is True
            else ("confirmed" if supports_tools is False else "unknown"),
            "vision": "inferred" if "image" in input_modalities else "unknown",
            "audio": "inferred" if "audio" in input_modalities else "unknown",
        }

        metadata: dict[str, Any] = {
            "owned_by": raw.get("owned_by"),
            "created": raw.get("created"),
            "active": raw.get("active"),
            "max_completion_tokens": raw.get("max_completion_tokens"),
        }

        return UnifiedModel(
            id=model_id,
            provider=self.provider_id,
            name=model_id,
            context_window=context_window,
            input_modalities=input_modalities,
            output_modalities=output_modalities,
            supports_streaming=supports_streaming,
            supports_tools=supports_tools,
            capabilities_confidence=confidence,
            pricing=None,  # Groq does not expose dynamic pricing via this endpoint
            metadata=metadata,
        )

    def _build_openai_payload(
        self,
        request: ChatCompletionRequest,
        provider_model_id: str,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Translate ChatCompletionRequest into OpenAI-compatible wire payload."""
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
        """Execute a non-streaming chat completion request against Groq."""
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
                "Failed to parse Groq chat completion JSON response",
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
        """Stream chat completion chunks from Groq via Server-Sent Events."""
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
