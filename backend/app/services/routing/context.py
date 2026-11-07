"""Typed routing context capturing incoming request requirements, policy, and caller identity."""

from dataclasses import dataclass, field
from typing import Any

from app.models.routing_policy import VirtualKeyRoutingPolicy
from app.models.user import User
from app.models.virtual_api_key import VirtualAPIKey
from app.schemas.chat import ChatCompletionRequest


@dataclass
class RoutingContext:
    """Encapsulates all inputs, requirements, and policy configurations for a routing decision."""

    user: User
    key: VirtualAPIKey
    policy: VirtualKeyRoutingPolicy
    requested_model: str
    is_explicit: bool
    explicit_provider: str | None = None
    explicit_provider_model_id: str | None = None
    alias: str | None = None
    requires_streaming: bool = False
    requires_tools: bool = False
    requires_vision: bool = False
    requires_structured_output: bool = False
    estimated_input_tokens: int = 0
    request_params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_request(
        cls,
        user: User,
        key: VirtualAPIKey,
        policy: VirtualKeyRoutingPolicy,
        request: ChatCompletionRequest,
    ) -> "RoutingContext":
        """Construct a validated RoutingContext from an OpenAI-compatible chat completion request."""
        raw_model = request.model.strip()
        clean_model = raw_model.lower()
        is_explicit = ":" in raw_model

        explicit_provider = None
        explicit_model_id = None
        alias = None

        valid_aliases = {"auto", "fast", "smart", "cheap"}

        if is_explicit:
            parts = raw_model.split(":", 1)
            explicit_provider = parts[0].strip().lower()
            explicit_model_id = parts[1].strip()
        elif clean_model in valid_aliases:
            alias = clean_model
        else:
            # Bare model ID without provider prefix (e.g. 'llama-3.3-70b-versatile' or canonical ID)
            is_explicit = True
            explicit_provider = None
            explicit_model_id = raw_model

        # Infer required capabilities from request payload
        requires_streaming = bool(getattr(request, "stream", False))
        requires_tools = bool(getattr(request, "tools", None))
        resp_fmt = getattr(request, "response_format", None)
        fmt_type = None
        if resp_fmt:
            if isinstance(resp_fmt, dict):
                fmt_type = resp_fmt.get("type")
            else:
                fmt_type = getattr(resp_fmt, "type", None)
        requires_structured_output = bool(fmt_type in ("json_object", "json_schema"))

        # Infer vision requirement if messages have multimodal content (future-proof)
        requires_vision = False
        total_chars = 0
        for msg in request.messages:
            if isinstance(msg.content, str):
                total_chars += len(msg.content)
            elif isinstance(msg.content, list):
                for part in msg.content:
                    if isinstance(part, dict) and part.get("type") in (
                        "image_url",
                        "image",
                    ):
                        requires_vision = True
                    if isinstance(part, dict) and "text" in part:
                        total_chars += len(str(part["text"]))

        # Rough token estimate: ~4 chars per token
        estimated_input_tokens = max(1, total_chars // 4)

        return cls(
            user=user,
            key=key,
            policy=policy,
            requested_model=request.model,
            is_explicit=is_explicit,
            explicit_provider=explicit_provider,
            explicit_provider_model_id=explicit_model_id,
            alias=alias,
            requires_streaming=requires_streaming,
            requires_tools=requires_tools,
            requires_vision=requires_vision,
            requires_structured_output=requires_structured_output,
            estimated_input_tokens=estimated_input_tokens,
            request_params={
                "temperature": request.temperature,
                "top_p": request.top_p,
                "max_tokens": request.max_tokens,
            },
        )
