"""Routing policy definitions, presets, weights normalization, and capability definitions."""

import math
from decimal import Decimal
from enum import StrEnum


class RoutingPreset(StrEnum):
    """Supported routing presets."""

    BALANCED = "balanced"
    QUALITY_FIRST = "quality_first"
    SPEED_FIRST = "speed_first"
    COST_OPTIMIZED = "cost_optimized"
    CUSTOM = "custom"


class ModelAccessProfile(StrEnum):
    """Permitted model modality access profiles."""

    ALL_MODELS = "all_models"
    TEXT_ONLY = "text_only"
    TEXT_IMAGE = "text_image"
    TEXT_AUDIO = "text_audio"
    TEXT_VIDEO = "text_video"
    ALL_MODALITIES = "all_modalities"


class CredentialSelectionStrategy(StrEnum):
    """Supported strategies for selecting a credential from a pool offering the same model."""

    ROUND_ROBIN = "round_robin"
    LEAST_RECENTLY_USED = "least_recently_used"
    PREFERRED = "preferred"
    LOWEST_LATENCY = "lowest_latency"
    DETERMINISTIC_DEFAULT = "deterministic_default"


PRESET_WEIGHTS: dict[RoutingPreset, dict[str, float]] = {
    RoutingPreset.BALANCED: {
        "quality": 0.25,
        "speed": 0.25,
        "availability": 0.25,
        "cost": 0.25,
    },
    RoutingPreset.QUALITY_FIRST: {
        "quality": 0.60,
        "speed": 0.15,
        "availability": 0.15,
        "cost": 0.10,
    },
    RoutingPreset.SPEED_FIRST: {
        "quality": 0.10,
        "speed": 0.60,
        "availability": 0.20,
        "cost": 0.10,
    },
    RoutingPreset.COST_OPTIMIZED: {
        "quality": 0.10,
        "speed": 0.10,
        "availability": 0.20,
        "cost": 0.60,
    },
}

SUPPORTED_CAPABILITIES: list[str] = [
    "streaming",
    "tools",
    "structured_output",
    "vision",
    "reasoning",
]


def validate_and_normalize_weights(
    quality: float | Decimal,
    speed: float | Decimal,
    availability: float | Decimal,
    cost: float | Decimal,
) -> dict[str, float]:
    """Validate and normalize user-defined priority weights.

    Ensures weights are finite numbers between 0 and 1, not NaN, not negative,
    and that at least one weight is positive.
    Returns dictionary with normalized floats summing to 1.0.
    """
    raw_weights = {
        "quality": float(quality),
        "speed": float(speed),
        "availability": float(availability),
        "cost": float(cost),
    }

    for name, w in raw_weights.items():
        if math.isnan(w) or math.isinf(w):
            raise ValueError(f"Weight '{name}' cannot be NaN or infinite.")
        if w < 0.0 or w > 1.0:
            raise ValueError(
                f"Weight '{name}' must be between 0.0 and 1.0 (received {w})."
            )

    total = sum(raw_weights.values())
    if total <= 0.0:
        raise ValueError(
            "At least one routing priority weight must be greater than zero."
        )

    return {name: round(w / total, 4) for name, w in raw_weights.items()}


def get_preset_weights(preset: str | RoutingPreset) -> dict[str, float]:
    """Retrieve canonical normalized weights for a standard routing preset."""
    try:
        enum_preset = RoutingPreset(preset)
    except ValueError as exc:
        raise ValueError(f"Unknown routing preset '{preset}'.") from exc

    if enum_preset == RoutingPreset.CUSTOM:
        raise ValueError(
            "Custom preset requires explicitly specified priority weights."
        )

    return dict(PRESET_WEIGHTS[enum_preset])


def is_modality_compatible(
    profile: str | ModelAccessProfile,
    input_modalities: list[str] | None,
    output_modalities: list[str] | None = None,
) -> bool:
    """Evaluate whether candidate model modalities satisfy the configured model access profile."""
    try:
        enum_profile = ModelAccessProfile(profile)
    except ValueError:
        return True

    if enum_profile in (
        ModelAccessProfile.ALL_MODELS,
        ModelAccessProfile.ALL_MODALITIES,
    ):
        return True

    inputs = set(input_modalities or ["text"])

    if enum_profile == ModelAccessProfile.TEXT_ONLY:
        # Text-only profile permits only models requiring strictly text input
        return inputs.issubset({"text"})

    if enum_profile == ModelAccessProfile.TEXT_IMAGE:
        # Permits models using text and/or image inputs
        return inputs.issubset({"text", "image"})

    if enum_profile == ModelAccessProfile.TEXT_AUDIO:
        return inputs.issubset({"text", "audio"})

    if enum_profile == ModelAccessProfile.TEXT_VIDEO:
        return inputs.issubset({"text", "video"})

    return True
