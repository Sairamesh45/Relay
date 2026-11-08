"""Google Gemini provider adapter integrating with official Google AI Generative Language API."""

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


class GeminiProvider(BaseProvider):
    """Adapter for Google Gemini models via Generative Language API v1beta."""

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    @property
    def provider_id(self) -> str:
        return "gemini"

    @property
    def provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            id="gemini",
            name="Google Gemini",
            description="Google DeepMind foundation models supporting multimodal intelligence and large context windows.",
            website_url="https://ai.google.dev",
            docs_url="https://ai.google.dev/api/models",
        )

    def _get_headers(self, api_key: str) -> dict[str, str]:
        """Return official Google API key header without embedding secrets in URLs."""
        return {
            "x-goog-api-key": api_key.strip(),
            "Accept": "application/json",
        }

    async def validate_credentials(self, api_key: str) -> bool:
        """Validate Gemini API key by querying models endpoint with pageSize=1."""
        clean_key = api_key.strip()
        if settings.APP_ENV.lower() == "development" and clean_key.startswith(
            ("test_", "mock_", "dev_")
        ):
            return True

        url = f"{self.BASE_URL}/models"
        headers = self._get_headers(clean_key)
        params = {"pageSize": 1}

        response = await self._execute_request(
            "GET", url, headers=headers, params=params
        )

        if response.status_code == 200:
            return True

        # Google Gemini returns 400 INVALID_ARGUMENT for bad API keys
        if response.status_code == 400:
            try:
                error_body = response.json()
                msg = str(error_body.get("error", {}).get("message", ""))
                status = str(error_body.get("error", {}).get("status", ""))
                if (
                    "API_KEY_INVALID" in msg
                    or "API key not valid" in msg
                    or status == "INVALID_ARGUMENT"
                ):
                    raise InvalidCredentialsError(
                        "Google Gemini API key validation failed: invalid API key",
                        provider=self.provider_id,
                        status_code=400,
                    )
            except (ValueError, KeyError):
                pass
            raise ProviderRequestError(
                "Gemini API returned HTTP 400 Bad Request during credential validation",
                provider=self.provider_id,
                status_code=400,
            )

        if response.status_code in (401, 403):
            raise InvalidCredentialsError(
                "Google Gemini API key is unauthorized or forbidden",
                provider=self.provider_id,
                status_code=response.status_code,
            )

        raise ProviderRequestError(
            f"Unexpected status code {response.status_code} during Gemini validation",
            provider=self.provider_id,
            status_code=response.status_code,
        )

    def _get_dev_mock_models(self) -> list[UnifiedModel]:
        return [
            UnifiedModel(
                id="gemini-1.5-pro",
                provider=self.provider_id,
                name="Gemini 1.5 Pro",
                context_window=2097152,
                input_modalities=["text", "image", "audio", "video"],
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
                metadata={"description": "Flagship multimodal intelligence from Google DeepMind."},
            ),
            UnifiedModel(
                id="gemini-1.5-flash",
                provider=self.provider_id,
                name="Gemini 1.5 Flash",
                context_window=1048576,
                input_modalities=["text", "image", "audio", "video"],
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
                metadata={"description": "Fast workhorse multimodal model from Google DeepMind."},
            ),
            UnifiedModel(
                id="gemini-2.0-flash",
                provider=self.provider_id,
                name="Gemini 2.0 Flash",
                context_window=1048576,
                input_modalities=["text", "image", "audio", "video"],
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
                metadata={"description": "Next-gen multimodal model built for real-time agentic workflows."},
            ),
        ]

    async def list_models(self, api_key: str) -> list[UnifiedModel]:
        """Fetch and normalize all available Google Gemini models handling pagination."""
        clean_key = api_key.strip()
        if settings.APP_ENV.lower() == "development" and clean_key.startswith(
            ("test_", "mock_", "dev_")
        ):
            return self._get_dev_mock_models()

        url = f"{self.BASE_URL}/models"
        headers = self._get_headers(clean_key)

        models: list[UnifiedModel] = []
        seen_model_ids: set[str] = set()
        seen_tokens: set[str] = set()
        next_page_token: str | None = None

        while True:
            params: dict[str, Any] = {"pageSize": 100}
            if next_page_token:
                params["pageToken"] = next_page_token
                seen_tokens.add(next_page_token)

            response = await self._execute_request(
                "GET", url, headers=headers, params=params
            )

            # Check for bad key error encoded as 400
            if response.status_code == 400:
                try:
                    error_body = response.json()
                    msg = str(error_body.get("error", {}).get("message", ""))
                    if "API_KEY_INVALID" in msg or "API key not valid" in msg:
                        raise InvalidCredentialsError(
                            "Google Gemini API key validation failed: invalid API key",
                            provider=self.provider_id,
                            status_code=400,
                        )
                except (ValueError, KeyError):
                    pass
                raise ProviderRequestError(
                    "Google Gemini API returned 400 Bad Request",
                    provider=self.provider_id,
                    status_code=400,
                )

            if response.status_code != 200:
                raise ProviderRequestError(
                    f"Gemini model discovery returned unexpected status {response.status_code}",
                    provider=self.provider_id,
                    status_code=response.status_code,
                )

            try:
                data = response.json()
            except ValueError as exc:
                raise ProviderRequestError(
                    "Failed to parse Gemini model discovery JSON response",
                    provider=self.provider_id,
                ) from exc

            raw_models = data.get("models")
            if not isinstance(raw_models, list):
                raise ProviderRequestError(
                    "Malformed response from Gemini: 'models' field is missing or not a list",
                    provider=self.provider_id,
                )

            for raw_model in raw_models:
                if not isinstance(raw_model, dict):
                    continue
                normalized = self._normalize_model(raw_model)
                if normalized.id not in seen_model_ids:
                    seen_model_ids.add(normalized.id)
                    models.append(normalized)

            raw_token = data.get("nextPageToken")
            next_page_token = str(raw_token).strip() if raw_token else None
            if not next_page_token or next_page_token in seen_tokens:
                break

        return models

    def _normalize_model(self, raw: dict[str, Any]) -> UnifiedModel:
        """Map raw Gemini model metadata to the standardized UnifiedModel schema."""
        raw_name = raw.get("name", "")
        # Strip "models/" prefix if present
        model_id = raw_name.removeprefix("models/") if raw_name else "unknown"
        display_name = raw.get("displayName")
        input_token_limit = raw.get("inputTokenLimit")
        output_token_limit = raw.get("outputTokenLimit")
        gen_methods = raw.get("supportedGenerationMethods", [])

        # Determine modalities and capabilities based on official Google documentation
        supports_content_gen = "generateContent" in gen_methods
        supports_embeddings = "embedContent" in gen_methods

        input_modalities: list[str] = []
        output_modalities: list[str] = []

        if supports_embeddings:
            input_modalities = ["text"]
            output_modalities = ["embeddings"]
        elif supports_content_gen:
            if "imagen" in model_id.lower():
                input_modalities = ["text"]
                output_modalities = ["image"]
            elif "gemini" in model_id.lower():
                # Official Gemini multimodal capabilities
                input_modalities = ["text", "image", "audio", "video"]
                output_modalities = ["text"]
            else:
                input_modalities = ["text"]
                output_modalities = ["text"]
        else:
            input_modalities = ["text"]
            output_modalities = ["text"]

        supports_streaming = supports_content_gen if gen_methods else None
        supports_tools = (
            supports_content_gen and ("gemini" in model_id.lower())
            if gen_methods
            else None
        )

        # Distinguish confirmed, inferred, and unknown capabilities
        confidence: dict[str, str] = {
            "context_window": "confirmed"
            if input_token_limit is not None
            else "unknown",
            "streaming": "confirmed" if supports_content_gen else "unknown",
            "tools": "inferred"
            if supports_tools is True
            else ("confirmed" if supports_tools is False else "unknown"),
            "vision": "inferred" if "image" in input_modalities else "unknown",
            "audio": "inferred" if "audio" in input_modalities else "unknown",
        }

        metadata: dict[str, Any] = {
            "raw_name": raw_name,
            "version": raw.get("version"),
            "description": raw.get("description"),
            "supported_generation_methods": gen_methods,
            "output_token_limit": output_token_limit,
            "temperature": raw.get("temperature"),
            "top_p": raw.get("topP"),
            "top_k": raw.get("topK"),
        }

        return UnifiedModel(
            id=model_id,
            provider=self.provider_id,
            name=display_name,
            context_window=input_token_limit,
            input_modalities=input_modalities,
            output_modalities=output_modalities,
            supports_streaming=supports_streaming,
            supports_tools=supports_tools,
            capabilities_confidence=confidence,
            pricing=None,  # Gemini does not return dynamic pricing via models endpoint
            metadata=metadata,
        )

    def _map_finish_reason(self, reason: str | None) -> str:
        """Map Gemini finish reason to OpenAI finish reason."""
        if not reason:
            return "stop"
        r = reason.upper()
        if r in ("STOP", "FINISH_REASON_UNSPECIFIED"):
            return "stop"
        elif r == "MAX_TOKENS":
            return "length"
        elif r in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"):
            return "content_filter"
        return "stop"

    def _build_gemini_payload(self, request: ChatCompletionRequest) -> dict[str, Any]:
        """Translate OpenAI ChatCompletionRequest into Gemini generateContent payload."""
        system_parts: list[dict[str, str]] = []
        contents: list[dict[str, Any]] = []

        for msg in request.messages:
            text_content = (
                msg.content if isinstance(msg.content, str) else str(msg.content)
            )
            if msg.role in ("system", "developer"):
                system_parts.append({"text": text_content})
            else:
                role = "model" if msg.role == "assistant" else "user"
                contents.append(
                    {
                        "role": role,
                        "parts": [{"text": text_content}],
                    }
                )

        payload: dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["system_instruction"] = {"parts": system_parts}

        gen_config: dict[str, Any] = {}
        if request.temperature is not None:
            gen_config["temperature"] = request.temperature
        if request.top_p is not None:
            gen_config["topP"] = request.top_p
        if request.effective_max_tokens() is not None:
            gen_config["maxOutputTokens"] = request.effective_max_tokens()
        if request.stop is not None:
            gen_config["stopSequences"] = request.effective_stop_sequences()

        if gen_config:
            payload["generationConfig"] = gen_config

        return payload

    async def create_chat_completion(
        self,
        api_key: str,
        request: ChatCompletionRequest,
        provider_model_id: str,
    ) -> ChatCompletionResponse:
        """Execute a non-streaming chat completion with Gemini Generative Language API."""
        clean_model = provider_model_id.removeprefix("models/")
        url = f"{self.BASE_URL}/models/{clean_model}:generateContent"
        headers = self._get_headers(api_key)
        payload = self._build_gemini_payload(request)

        response = await self._execute_request(
            "POST", url, headers=headers, json_data=payload
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderRequestError(
                "Failed to parse Gemini generateContent JSON response",
                provider=self.provider_id,
            ) from exc

        candidates = data.get("candidates", [])
        choices: list[ChatChoice] = []

        for i, cand in enumerate(candidates):
            content_obj = cand.get("content") or {}
            parts = content_obj.get("parts") or []
            combined_text = "".join(
                p.get("text", "") for p in parts if isinstance(p, dict)
            )
            finish_reason = self._map_finish_reason(cand.get("finishReason"))

            choices.append(
                ChatChoice(
                    index=cand.get("index", i),
                    message=ChatResponseMessage(
                        role="assistant",
                        content=combined_text,
                    ),
                    finish_reason=finish_reason,
                )
            )

        if not choices:
            choices.append(
                ChatChoice(
                    index=0,
                    message=ChatResponseMessage(role="assistant", content=""),
                    finish_reason="stop",
                )
            )

        usage: CompletionUsage | None = None
        raw_usage = data.get("usageMetadata")
        if raw_usage and isinstance(raw_usage, dict):
            prompt_tok = int(raw_usage.get("promptTokenCount", 0))
            cand_tok = int(raw_usage.get("candidatesTokenCount", 0))
            total_tok = int(raw_usage.get("totalTokenCount", prompt_tok + cand_tok))
            usage = CompletionUsage(
                prompt_tokens=prompt_tok,
                completion_tokens=cand_tok,
                total_tokens=total_tok,
            )

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:24]}",
            created=int(time.time()),
            model=request.model,
            choices=choices,
            usage=usage,
        )

    async def stream_chat_completion(
        self,
        api_key: str,
        request: ChatCompletionRequest,
        provider_model_id: str,
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        """Stream chat completion chunks from Gemini via SSE streamGenerateContent."""
        clean_model = provider_model_id.removeprefix("models/")
        url = f"{self.BASE_URL}/models/{clean_model}:streamGenerateContent?alt=sse"
        headers = self._get_headers(api_key)
        payload = self._build_gemini_payload(request)
        stream_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created_ts = int(time.time())

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

                candidates = chunk_dict.get("candidates") or []
                text_part = ""
                finish_reason = None
                index = 0

                if candidates:
                    cand = candidates[0]
                    index = cand.get("index", 0)
                    content_obj = cand.get("content") or {}
                    parts = content_obj.get("parts") or []
                    text_part = "".join(
                        p.get("text", "") for p in parts if isinstance(p, dict)
                    )
                    raw_fr = cand.get("finishReason")
                    if raw_fr:
                        finish_reason = self._map_finish_reason(raw_fr)

                usage: CompletionUsage | None = None
                raw_usage = chunk_dict.get("usageMetadata")
                if raw_usage and isinstance(raw_usage, dict):
                    prompt_tok = int(raw_usage.get("promptTokenCount", 0))
                    cand_tok = int(raw_usage.get("candidatesTokenCount", 0))
                    usage = CompletionUsage(
                        prompt_tokens=prompt_tok,
                        completion_tokens=cand_tok,
                        total_tokens=int(
                            raw_usage.get("totalTokenCount", prompt_tok + cand_tok)
                        ),
                    )

                if text_part or finish_reason:
                    yield ChatCompletionChunk(
                        id=stream_id,
                        created=created_ts,
                        model=request.model,
                        choices=[
                            ChatChunkChoice(
                                index=index,
                                delta=ChatChunkDelta(
                                    content=text_part if text_part else None
                                ),
                                finish_reason=finish_reason,
                            )
                        ],
                        usage=usage,
                    )
