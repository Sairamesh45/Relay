"""Model normalization and canonical identity resolution service.

Translates disparate provider model metadata into standardized canonical identities
and offerings with strict provenance tracking (confirmed, inferred, unknown).
"""

from decimal import Decimal
from typing import Any

from app.providers.schemas.model import CapabilityConfidence, UnifiedModel


class ModelNormalizationResult:
    """Container holding normalized canonical model data and provider offering attributes."""

    def __init__(
        self,
        canonical_id: str,
        display_name: str | None,
        description: str | None,
        provider_model_family: str | None,
        modality: str,
        input_modalities: list[str],
        output_modalities: list[str],
        # Offering attributes
        provider: str,
        provider_model_id: str,
        context_window: int | None,
        max_output_tokens: int | None,
        input_price_per_million: Decimal | None,
        output_price_per_million: Decimal | None,
        supports_streaming: bool | None,
        supports_tools: bool | None,
        supports_structured_output: bool | None,
        supports_vision: bool | None,
        supports_reasoning: bool | None,
        availability_status: str,
        metadata_source: str,
        capability_metadata: dict[str, Any],
        raw_metadata: dict[str, Any],
    ) -> None:
        self.canonical_id = canonical_id
        self.display_name = display_name
        self.description = description
        self.provider_model_family = provider_model_family
        self.modality = modality
        self.input_modalities = input_modalities
        self.output_modalities = output_modalities

        self.provider = provider
        self.provider_model_id = provider_model_id
        self.context_window = context_window
        self.max_output_tokens = max_output_tokens
        self.input_price_per_million = input_price_per_million
        self.output_price_per_million = output_price_per_million
        self.supports_streaming = supports_streaming
        self.supports_tools = supports_tools
        self.supports_structured_output = supports_structured_output
        self.supports_vision = supports_vision
        self.supports_reasoning = supports_reasoning
        self.availability_status = availability_status
        self.metadata_source = metadata_source
        self.capability_metadata = capability_metadata
        self.raw_metadata = raw_metadata


class ModelNormalizer:
    """Service to normalize provider-discovered models and resolve canonical identities."""

    # Known architecture / family prefixes for resolving vendor namespaces
    KNOWN_FAMILIES: dict[str, str] = {
        "llama": "meta-llama",
        "meta-llama": "meta-llama",
        "mistral": "mistralai",
        "mixtral": "mistralai",
        "codestral": "mistralai",
        "gemma": "google",
        "gemini": "google",
        "qwen": "qwen",
        "deepseek": "deepseek-ai",
        "whisper": "openai",
        "gpt": "openai",
        "claude": "anthropic",
    }

    def resolve_canonical_id(self, provider: str, raw_model_id: str) -> str:
        """Derive a stable, vendor-scoped canonical model identity.

        Rules:
        1. Never merge models across providers unless exact vendor namespace and model name match.
        2. Gemini models: strip leading 'models/' prefix and scope to 'google/{name}'.
        3. OpenRouter models: already vendor-scoped (e.g. 'google/gemini-2.5-flash', 'openai/gpt-4o').
           Strip provider variant routing suffixes (':free', ':nitro', ':extended', ':exact')
           for the canonical identity while retaining provider_model_id in the offering.
        4. Groq models:
           - If prefixed with namespace (e.g. 'openai/gpt-oss-20b', 'qwen/qwen3.8-27b'), preserve namespace.
           - If recognizable model family (e.g. 'llama-3.3-70b-versatile', 'whisper-large-v3-turbo'),
             map to canonical vendor namespace (e.g. 'meta-llama/llama-3.3-70b-versatile').
           - Otherwise, scope to 'groq/{name}'.
        """
        clean_id = raw_model_id.strip()
        provider_key = provider.strip().lower()

        if provider_key == "gemini":
            if clean_id.startswith("models/"):
                clean_id = clean_id[len("models/") :]
            return f"google/{clean_id.lower()}"

        elif provider_key == "openrouter":
            # Strip routing tier suffixes for canonical identity
            base_id = clean_id.split(":")[0].strip().lower()
            if "/" in base_id:
                return base_id
            return f"openrouter/{base_id}"

        elif provider_key == "groq":
            clean_id_lower = clean_id.lower()
            if "/" in clean_id_lower:
                return clean_id_lower

            # Check known model prefix
            first_part = clean_id_lower.split("-")[0]
            if first_part in self.KNOWN_FAMILIES:
                vendor = self.KNOWN_FAMILIES[first_part]
                return f"{vendor}/{clean_id_lower}"

            return f"groq/{clean_id_lower}"

        else:
            # Fallback for other providers: scope to provider unless namespace exists
            clean_id_lower = clean_id.lower()
            if "/" in clean_id_lower:
                return clean_id_lower
            return f"{provider_key}/{clean_id_lower}"

    def extract_family(self, canonical_id: str) -> str | None:
        """Extract the model family from canonical ID."""
        parts = canonical_id.split("/")
        model_name = parts[-1] if len(parts) > 1 else parts[0]

        for prefix in [
            "llama",
            "gemini",
            "gemma",
            "qwen",
            "deepseek",
            "whisper",
            "gpt",
            "claude",
            "mistral",
            "mixtral",
        ]:
            if model_name.startswith(prefix):
                return prefix
        return None

    def determine_modality(
        self,
        input_modalities: list[str],
        output_modalities: list[str],
        canonical_id: str,
    ) -> str:
        """Classify primary operational modality."""
        inputs = {m.lower() for m in input_modalities}
        outputs = {m.lower() for m in output_modalities}

        if "audio" in inputs or "audio" in outputs or "whisper" in canonical_id:
            return "audio"
        if "embedding" in canonical_id:
            return "embedding"
        if ("image" in inputs or "video" in inputs) and "text" in outputs:
            return "multimodal"
        if "image" in outputs:
            return "image"
        if "text" in inputs and "text" in outputs:
            return "text->text"
        if inputs or outputs:
            return "multimodal"
        return "text->text"

    def normalize(
        self,
        model: UnifiedModel,
        availability_status: str = "available",
    ) -> ModelNormalizationResult:
        """Normalize a provider-discovered UnifiedModel into database-ready structures."""
        canonical_id = self.resolve_canonical_id(model.provider, model.id)
        family = self.extract_family(canonical_id)
        modality = self.determine_modality(
            model.input_modalities, model.output_modalities, canonical_id
        )

        # Build capability provenance dictionary
        # Capabilities: streaming, tools, structured_output, vision, reasoning
        cap_meta: dict[str, Any] = {}

        # 1. Streaming
        streaming_conf = model.get_capability_confidence("supports_streaming")
        if streaming_conf == CapabilityConfidence.CONFIRMED.value:
            cap_meta["streaming"] = {
                "supported": model.supports_streaming,
                "confidence": CapabilityConfidence.CONFIRMED.value,
                "source": "provider_api",
            }
        elif model.supports_streaming is not None:
            cap_meta["streaming"] = {
                "supported": model.supports_streaming,
                "confidence": CapabilityConfidence.INFERRED.value,
                "source": "heuristics",
            }
        else:
            cap_meta["streaming"] = {
                "supported": None,
                "confidence": CapabilityConfidence.UNKNOWN.value,
                "source": "unknown",
            }

        # 2. Tools
        tools_conf = model.get_capability_confidence("supports_tools")
        if tools_conf == CapabilityConfidence.CONFIRMED.value:
            cap_meta["tools"] = {
                "supported": model.supports_tools,
                "confidence": CapabilityConfidence.CONFIRMED.value,
                "source": "provider_api",
            }
        elif model.supports_tools is not None:
            cap_meta["tools"] = {
                "supported": model.supports_tools,
                "confidence": CapabilityConfidence.INFERRED.value,
                "source": "heuristics",
            }
        else:
            cap_meta["tools"] = {
                "supported": None,
                "confidence": CapabilityConfidence.UNKNOWN.value,
                "source": "unknown",
            }

        # 3. Vision
        has_image_input = "image" in [m.lower() for m in model.input_modalities]
        vision_conf = model.get_capability_confidence("supports_vision")
        if vision_conf == CapabilityConfidence.CONFIRMED.value:
            supports_vision = True
            cap_meta["vision"] = {
                "supported": True,
                "confidence": CapabilityConfidence.CONFIRMED.value,
                "source": "provider_api",
            }
        elif vision_conf == CapabilityConfidence.INFERRED.value:
            supports_vision = True
            cap_meta["vision"] = {
                "supported": True,
                "confidence": CapabilityConfidence.INFERRED.value,
                "source": "heuristics",
            }
        elif has_image_input:
            supports_vision = True
            cap_meta["vision"] = {
                "supported": True,
                "confidence": CapabilityConfidence.CONFIRMED.value,
                "source": "provider_api",
            }
        elif "vision" in model.id.lower() or "vl" in model.id.lower():
            supports_vision = True
            cap_meta["vision"] = {
                "supported": True,
                "confidence": CapabilityConfidence.INFERRED.value,
                "source": "heuristics",
            }
        else:
            supports_vision = False if model.input_modalities else None
            cap_meta["vision"] = {
                "supported": supports_vision,
                "confidence": (
                    CapabilityConfidence.CONFIRMED.value
                    if model.input_modalities
                    else CapabilityConfidence.UNKNOWN.value
                ),
                "source": "provider_api" if model.input_modalities else "unknown",
            }

        # 4. Structured Output
        so_conf = model.get_capability_confidence("supports_structured_output")
        if so_conf == CapabilityConfidence.CONFIRMED.value:
            supports_so = True
            cap_meta["structured_output"] = {
                "supported": True,
                "confidence": CapabilityConfidence.CONFIRMED.value,
                "source": "provider_api",
            }
        else:
            supports_so = None
            cap_meta["structured_output"] = {
                "supported": None,
                "confidence": CapabilityConfidence.UNKNOWN.value,
                "source": "unknown",
            }

        # 5. Reasoning
        reasoning_conf = model.get_capability_confidence("supports_reasoning")
        if reasoning_conf == CapabilityConfidence.CONFIRMED.value:
            supports_reasoning = True
            cap_meta["reasoning"] = {
                "supported": True,
                "confidence": CapabilityConfidence.CONFIRMED.value,
                "source": "provider_api",
            }
        elif any(
            k in model.id.lower() for k in ["deepseek-r1", "reasoner", "o1-", "o3-"]
        ):
            supports_reasoning = True
            cap_meta["reasoning"] = {
                "supported": True,
                "confidence": CapabilityConfidence.INFERRED.value,
                "source": "heuristics",
            }
        else:
            supports_reasoning = None
            cap_meta["reasoning"] = {
                "supported": None,
                "confidence": CapabilityConfidence.UNKNOWN.value,
                "source": "unknown",
            }

        # Pricing normalization: Convert per-token or raw pricing to per-million-tokens
        input_price_per_m: Decimal | None = None
        output_price_per_m: Decimal | None = None

        if model.pricing:
            # Check prompt/completion pricing
            prompt_p = model.pricing.get("prompt")
            completion_p = model.pricing.get("completion")
            if prompt_p is not None:
                try:
                    # OpenRouter gives per-token pricing (e.g. 0.000002)
                    input_price_per_m = Decimal(str(prompt_p)) * Decimal(1_000_000)
                except Exception:
                    input_price_per_m = None
            if completion_p is not None:
                try:
                    output_price_per_m = Decimal(str(completion_p)) * Decimal(1_000_000)
                except Exception:
                    output_price_per_m = None

        # Max output tokens from metadata if exposed
        max_output_tokens: int | None = None
        if "max_output_tokens" in model.metadata:
            try:
                max_output_tokens = int(model.metadata["max_output_tokens"])
            except (ValueError, TypeError):
                max_output_tokens = None
        elif "output_token_limit" in model.metadata:
            try:
                max_output_tokens = int(model.metadata["output_token_limit"])
            except (ValueError, TypeError):
                max_output_tokens = None

        # Determine primary metadata source
        metadata_source = "provider_api"

        return ModelNormalizationResult(
            canonical_id=canonical_id,
            display_name=model.name or canonical_id.split("/")[-1],
            description=model.metadata.get("description"),
            provider_model_family=family,
            modality=modality,
            input_modalities=model.input_modalities or ["text"],
            output_modalities=model.output_modalities or ["text"],
            provider=model.provider,
            provider_model_id=model.id,
            context_window=model.context_window,
            max_output_tokens=max_output_tokens,
            input_price_per_million=input_price_per_m,
            output_price_per_million=output_price_per_m,
            supports_streaming=model.supports_streaming,
            supports_tools=model.supports_tools,
            supports_structured_output=supports_so,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
            availability_status=availability_status,
            metadata_source=metadata_source,
            capability_metadata=cap_meta,
            raw_metadata=model.metadata,
        )


# Singleton normalizer instance
model_normalizer = ModelNormalizer()


def get_model_normalizer() -> ModelNormalizer:
    """Dependency provider for ModelNormalizer."""
    return model_normalizer
