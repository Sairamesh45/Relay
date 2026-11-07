"""OpenAI-compatible request and response schemas for Chat Completions."""

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Individual chat message supporting standard roles."""

    role: Literal["system", "developer", "user", "assistant", "tool"] = Field(
        ..., description="Message author role"
    )
    content: str | list[Any] = Field(..., description="Message contents")
    name: str | None = Field(None, description="Optional name author identifier")


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request schema."""

    model: str = Field(
        ...,
        description="Gateway model identifier in 'provider:model_id' format (e.g. 'gemini:gemini-2.5-flash')",
    )
    messages: list[ChatMessage] = Field(
        ..., min_length=1, description="List of messages comprising the conversation"
    )
    temperature: float | None = Field(
        None, ge=0.0, le=2.0, description="Sampling temperature between 0 and 2"
    )
    top_p: float | None = Field(
        None, ge=0.0, le=1.0, description="Nucleus sampling probability"
    )
    max_tokens: int | None = Field(
        None, ge=1, description="Maximum number of tokens to generate"
    )
    max_completion_tokens: int | None = Field(
        None, ge=1, description="Alias for max_tokens supported by newer models"
    )
    stream: bool = Field(
        False, description="Whether to stream partial message deltas via SSE"
    )
    stop: str | list[str] | None = Field(
        None, description="Up to 4 sequences where the API will stop generating"
    )
    presence_penalty: float | None = Field(
        None, ge=-2.0, le=2.0, description="Presence penalty between -2.0 and 2.0"
    )
    frequency_penalty: float | None = Field(
        None, ge=-2.0, le=2.0, description="Frequency penalty between -2.0 and 2.0"
    )
    seed: int | None = Field(
        None, description="Random seed for deterministic generation"
    )
    tools: list[dict[str, Any]] | None = Field(
        None, description="A list of tools the model may call"
    )
    tool_choice: str | dict[str, Any] | None = Field(
        None, description="Controls which tool is called"
    )
    response_format: dict[str, Any] | None = Field(
        None, description="Output format specification"
    )

    def effective_max_tokens(self) -> int | None:
        """Resolve max_tokens taking into account max_completion_tokens."""
        return self.max_completion_tokens or self.max_tokens

    def effective_stop_sequences(self) -> list[str]:
        """Normalize stop sequences into a list of strings."""
        if self.stop is None:
            return []
        if isinstance(self.stop, str):
            return [self.stop]
        return list(self.stop)[:4]


class CompletionUsage(BaseModel):
    """Token usage metrics reported by provider."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponseMessage(BaseModel):
    """Generated assistant message in non-streaming response."""

    role: str = "assistant"
    content: str | None = None


class ChatChoice(BaseModel):
    """Individual completion choice."""

    index: int = 0
    message: ChatResponseMessage
    finish_reason: str | None = "stop"


class ChatCompletionResponse(BaseModel):
    """Standard non-streaming OpenAI chat completion response."""

    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:24]}")
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[ChatChoice]
    usage: CompletionUsage | None = None
    system_fingerprint: str | None = None


class ChatChunkDelta(BaseModel):
    """Incremental chunk content delta."""

    role: str | None = None
    content: str | None = None


class ChatChunkChoice(BaseModel):
    """Incremental choice in SSE stream."""

    index: int = 0
    delta: ChatChunkDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    """Standard OpenAI streaming chunk emitted via SSE."""

    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:24]}")
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[ChatChunkChoice]
    usage: CompletionUsage | None = None


class OpenAIModelListItem(BaseModel):
    """Item in OpenAI GET /v1/models response."""

    id: str
    object: Literal["model"] = "model"
    created: int = 0
    owned_by: str


class OpenAIModelListResponse(BaseModel):
    """OpenAI standard GET /v1/models response."""

    object: Literal["list"] = "list"
    data: list[OpenAIModelListItem]
