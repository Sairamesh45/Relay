"""Unit tests for ModelNormalizer service."""

from decimal import Decimal

from app.providers.schemas.model import CapabilityConfidence, UnifiedModel
from app.services.model_normalizer import ModelNormalizer


def test_resolve_canonical_id_gemini() -> None:
    normalizer = ModelNormalizer()

    # Strips models/ prefix and lowercases
    assert (
        normalizer.resolve_canonical_id("gemini", "models/gemini-2.5-flash")
        == "google/gemini-2.5-flash"
    )
    assert (
        normalizer.resolve_canonical_id("gemini", "gemini-1.5-pro")
        == "google/gemini-1.5-pro"
    )


def test_resolve_canonical_id_openrouter() -> None:
    normalizer = ModelNormalizer()

    # Preserves vendor namespace and strips routing tiers (:free, :extended)
    assert (
        normalizer.resolve_canonical_id("openrouter", "google/gemini-2.5-flash")
        == "google/gemini-2.5-flash"
    )
    assert (
        normalizer.resolve_canonical_id("openrouter", "liquid/lfm-3-1.7b:free")
        == "liquid/lfm-3-1.7b"
    )
    assert (
        normalizer.resolve_canonical_id("openrouter", "openai/gpt-4o:extended")
        == "openai/gpt-4o"
    )


def test_resolve_canonical_id_groq() -> None:
    normalizer = ModelNormalizer()

    # Vendor prefix if recognized
    assert (
        normalizer.resolve_canonical_id("groq", "llama-3.3-70b-versatile")
        == "meta-llama/llama-3.3-70b-versatile"
    )
    assert (
        normalizer.resolve_canonical_id("groq", "whisper-large-v3-turbo")
        == "openai/whisper-large-v3-turbo"
    )
    # Existing namespace preserved
    assert (
        normalizer.resolve_canonical_id("groq", "openai/gpt-oss-20b")
        == "openai/gpt-oss-20b"
    )
    # Unrecognized family scoped to groq/
    assert normalizer.resolve_canonical_id("groq", "allam-2-7b") == "groq/allam-2-7b"


def test_no_false_model_merging() -> None:
    normalizer = ModelNormalizer()

    # Different model versions must never resolve to the same canonical identity
    id1 = normalizer.resolve_canonical_id("gemini", "gemini-1.5-flash")
    id2 = normalizer.resolve_canonical_id("gemini", "gemini-2.5-flash")
    id3 = normalizer.resolve_canonical_id("groq", "llama-3.1-8b-instant")
    id4 = normalizer.resolve_canonical_id("groq", "llama-3.3-70b-versatile")

    assert id1 != id2
    assert id3 != id4


def test_modality_classification() -> None:
    normalizer = ModelNormalizer()

    assert (
        normalizer.determine_modality(["text"], ["text"], "meta-llama/llama-3.3-70b")
        == "text->text"
    )
    assert (
        normalizer.determine_modality(
            ["text", "image"], ["text"], "google/gemini-2.5-flash"
        )
        == "multimodal"
    )
    assert (
        normalizer.determine_modality(["audio"], ["text"], "openai/whisper-large-v3")
        == "audio"
    )
    assert (
        normalizer.determine_modality(["text"], ["text"], "text-embedding-3-small")
        == "embedding"
    )


def test_normalize_provenance_and_pricing() -> None:
    normalizer = ModelNormalizer()

    raw_model = UnifiedModel(
        id="google/gemini-2.5-flash",
        provider="openrouter",
        name="Google: Gemini 2.5 Flash",
        context_window=1048576,
        input_modalities=["text", "image"],
        output_modalities=["text"],
        supports_streaming=True,
        supports_tools=True,
        capabilities_confidence={
            "supports_streaming": CapabilityConfidence.CONFIRMED.value,
            "supports_tools": CapabilityConfidence.CONFIRMED.value,
            "supports_vision": CapabilityConfidence.CONFIRMED.value,
        },
        pricing={
            "prompt": 0.000000075,  # $0.075 / 1M tokens
            "completion": 0.0000003,  # $0.30 / 1M tokens
        },
        metadata={"description": "Fast multimodal model", "max_output_tokens": 8192},
    )

    result = normalizer.normalize(raw_model)

    assert result.canonical_id == "google/gemini-2.5-flash"
    assert result.modality == "multimodal"
    assert result.context_window == 1048576
    assert result.max_output_tokens == 8192
    assert result.supports_vision is True

    # Pricing per million tokens
    assert result.input_price_per_million == Decimal("0.075")
    assert result.output_price_per_million == Decimal("0.30")

    # Capability provenance
    assert result.capability_metadata["streaming"]["confidence"] == "confirmed"
    assert result.capability_metadata["streaming"]["source"] == "provider_api"
    assert result.capability_metadata["vision"]["confidence"] == "confirmed"
    assert result.capability_metadata["vision"]["source"] == "provider_api"


def test_normalize_preserves_inferred_capabilities() -> None:
    """Verify that adapter-inferred capabilities remain inferred and are not converted to confirmed."""
    normalizer = ModelNormalizer()

    # Model where vision is inferred by adapter heuristics (like Groq)
    raw_model = UnifiedModel(
        id="llama-3.2-11b-vision-preview",
        provider="groq",
        name="llama-3.2-11b-vision-preview",
        context_window=131072,
        input_modalities=["text", "image"],
        output_modalities=["text"],
        supports_streaming=True,
        supports_tools=True,
        capabilities_confidence={
            "streaming": CapabilityConfidence.CONFIRMED.value,
            "tools": CapabilityConfidence.INFERRED.value,
            "vision": CapabilityConfidence.INFERRED.value,
        },
        metadata={},
    )

    result = normalizer.normalize(raw_model)

    assert result.supports_vision is True
    assert result.capability_metadata["vision"]["confidence"] == "inferred"
    assert result.capability_metadata["vision"]["source"] == "heuristics"

    assert result.supports_tools is True
    assert result.capability_metadata["tools"]["confidence"] == "inferred"
    assert result.capability_metadata["tools"]["source"] == "heuristics"

    assert result.supports_streaming is True
    assert result.capability_metadata["streaming"]["confidence"] == "confirmed"
    assert result.capability_metadata["streaming"]["source"] == "provider_api"


def test_openrouter_variants_preserve_offering_and_canonical() -> None:
    """Verify OpenRouter variant suffixes preserve offering IDs while sharing canonical ID."""
    normalizer = ModelNormalizer()

    free_model = UnifiedModel(
        id="meta-llama/llama-3.3-70b-instruct:free",
        provider="openrouter",
        name="Llama 3.3 70B (free)",
        input_modalities=["text"],
        output_modalities=["text"],
        pricing={"prompt": 0.0, "completion": 0.0},
    )
    nitro_model = UnifiedModel(
        id="meta-llama/llama-3.3-70b-instruct:nitro",
        provider="openrouter",
        name="Llama 3.3 70B (nitro)",
        input_modalities=["text"],
        output_modalities=["text"],
        pricing={"prompt": 0.0000004, "completion": 0.0000016},
    )

    res_free = normalizer.normalize(free_model)
    res_nitro = normalizer.normalize(nitro_model)

    # Canonical identities are identical
    assert res_free.canonical_id == "meta-llama/llama-3.3-70b-instruct"
    assert res_nitro.canonical_id == "meta-llama/llama-3.3-70b-instruct"

    # Offering IDs and pricing remain distinct
    assert res_free.provider_model_id == "meta-llama/llama-3.3-70b-instruct:free"
    assert res_nitro.provider_model_id == "meta-llama/llama-3.3-70b-instruct:nitro"
    assert res_free.input_price_per_million == Decimal("0.0")
    assert res_nitro.input_price_per_million == Decimal("0.400000")


def test_cross_provider_identical_model_mapping() -> None:
    """Verify that identical underlying models from different providers resolve to the same canonical identity."""
    normalizer = ModelNormalizer()

    # Gemini native vs OpenRouter Gemini
    gemini_id = normalizer.resolve_canonical_id("gemini", "models/gemini-2.5-flash")
    openrouter_gemini_id = normalizer.resolve_canonical_id(
        "openrouter", "google/gemini-2.5-flash"
    )
    assert gemini_id == openrouter_gemini_id == "google/gemini-2.5-flash"

    # Groq Llama vs OpenRouter Llama
    groq_llama = normalizer.resolve_canonical_id("groq", "llama-3.3-70b-versatile")
    openrouter_llama = normalizer.resolve_canonical_id(
        "openrouter", "meta-llama/llama-3.3-70b-versatile"
    )
    assert groq_llama == openrouter_llama == "meta-llama/llama-3.3-70b-versatile"


def test_unknown_publisher_namespaces() -> None:
    """Verify unknown publisher namespaces are scoped safely without collisions."""
    normalizer = ModelNormalizer()

    # OpenRouter preserves multi-segment path even if vendor is unknown
    assert (
        normalizer.resolve_canonical_id("openrouter", "unknown-org/super-model-v1")
        == "unknown-org/super-model-v1"
    )
    # Groq without namespace and unknown prefix scopes to groq/{name}
    assert (
        normalizer.resolve_canonical_id("groq", "custom-experimental-model")
        == "groq/custom-experimental-model"
    )
    # Generic fallback
    assert (
        normalizer.resolve_canonical_id("anthropic", "claude-3-5-sonnet")
        == "anthropic/claude-3-5-sonnet"
    )


def test_key_resolution_supports_prefix_and_plain() -> None:
    """Verify UnifiedModel confidence lookup works interchangeably with or without supports_ prefix."""
    model = UnifiedModel(
        id="test-model",
        provider="gemini",
        capabilities_confidence={
            "streaming": "confirmed",
            "supports_tools": "inferred",
        },
    )

    assert model.get_capability_confidence("streaming") == "confirmed"
    assert model.get_capability_confidence("supports_streaming") == "confirmed"
    assert model.is_confirmed("streaming") is True
    assert model.is_confirmed("supports_streaming") is True

    assert model.get_capability_confidence("tools") == "inferred"
    assert model.get_capability_confidence("supports_tools") == "inferred"
    assert model.is_inferred("tools") is True
    assert model.is_inferred("supports_tools") is True
