"""Unified model schema normalizing model discovery and capability confidence across AI providers."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CapabilityConfidence(StrEnum):
    """Classification of capability certainty for intelligent routing decisions."""

    CONFIRMED = "confirmed"  # Explicitly declared in upstream provider API metadata
    INFERRED = "inferred"  # Inferred via model naming conventions or family heuristics
    UNKNOWN = "unknown"  # Unknown or unexposed by the provider API


class UnifiedModel(BaseModel):
    """Standardized representation of an AI model across disparate providers."""

    id: str = Field(
        ..., description="Unique model identifier as recognized by the provider"
    )
    provider: str = Field(
        ..., description="Provider identifier (e.g., 'gemini', 'groq', 'openrouter')"
    )
    name: str | None = Field(
        None, description="Human-readable model name or display name"
    )

    context_window: int | None = Field(
        None, description="Maximum total context window token capacity"
    )

    input_modalities: list[str] = Field(
        default_factory=list,
        description="Supported input modalities (e.g., 'text', 'image', 'audio')",
    )
    output_modalities: list[str] = Field(
        default_factory=list,
        description="Supported output modalities (e.g., 'text', 'image', 'audio')",
    )

    supports_streaming: bool | None = Field(
        None, description="Whether the model supports streaming responses"
    )
    supports_tools: bool | None = Field(
        None, description="Whether the model supports tool/function calling"
    )

    capabilities_confidence: dict[str, str] = Field(
        default_factory=dict,
        description="Certainty classification ('confirmed', 'inferred', 'unknown') for specific model capabilities.",
    )

    pricing: dict[str, Any] | None = Field(
        None, description="Normalized pricing information if exposed by the provider"
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw provider-specific metadata and parameters",
    )

    def _resolve_cap_key(self, capability: str) -> str:
        """Resolve capability key matching either 'supports_xyz' or 'xyz'."""
        if capability in self.capabilities_confidence:
            return capability
        short = capability.removeprefix("supports_")
        if short in self.capabilities_confidence:
            return short
        prefixed = f"supports_{capability}"
        if prefixed in self.capabilities_confidence:
            return prefixed
        return capability

    def is_confirmed(self, capability: str) -> bool:
        """Check if capability is directly confirmed by provider API metadata."""
        key = self._resolve_cap_key(capability)
        return (
            self.capabilities_confidence.get(key)
            == CapabilityConfidence.CONFIRMED.value
        )

    def is_inferred(self, capability: str) -> bool:
        """Check if capability is inferred via model heuristics."""
        key = self._resolve_cap_key(capability)
        return (
            self.capabilities_confidence.get(key) == CapabilityConfidence.INFERRED.value
        )

    def get_capability_confidence(self, capability: str) -> str:
        """Return confidence level ('confirmed', 'inferred', 'unknown')."""
        key = self._resolve_cap_key(capability)
        return self.capabilities_confidence.get(key, CapabilityConfidence.UNKNOWN.value)
