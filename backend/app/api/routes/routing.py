"""Routing metadata endpoints for supported presets and capabilities."""

from fastapi import APIRouter

from app.schemas.routing import (
    RoutingCapabilitiesResponse,
    RoutingPresetsResponse,
)
from app.services.routing.policies import (
    PRESET_WEIGHTS,
    SUPPORTED_CAPABILITIES,
    CredentialSelectionStrategy,
    ModelAccessProfile,
    RoutingPreset,
)

router = APIRouter()


@router.get(
    "/presets",
    response_model=RoutingPresetsResponse,
    summary="Get supported routing presets and canonical weights",
)
async def get_routing_presets() -> RoutingPresetsResponse:
    """Retrieve all supported routing presets and their canonical priority weights."""
    presets_catalog = {
        RoutingPreset.BALANCED.value: {
            "name": "Balanced",
            "description": "Equally balances quality, speed, availability, and cost (25% each).",
            "weights": PRESET_WEIGHTS[RoutingPreset.BALANCED],
        },
        RoutingPreset.QUALITY_FIRST.value: {
            "name": "Quality First",
            "description": "Prioritizes demonstrated model capability and reasoning capacity.",
            "weights": PRESET_WEIGHTS[RoutingPreset.QUALITY_FIRST],
        },
        RoutingPreset.SPEED_FIRST.value: {
            "name": "Speed First",
            "description": "Prioritizes low observed latency and high throughput.",
            "weights": PRESET_WEIGHTS[RoutingPreset.SPEED_FIRST],
        },
        RoutingPreset.COST_OPTIMIZED.value: {
            "name": "Cost Optimized",
            "description": "Prioritizes the lowest known input/output token pricing.",
            "weights": PRESET_WEIGHTS[RoutingPreset.COST_OPTIMIZED],
        },
        RoutingPreset.CUSTOM.value: {
            "name": "Custom",
            "description": "Allows independent priority sliders between 0.0 and 1.0.",
            "weights": None,
        },
    }
    return RoutingPresetsResponse(presets=presets_catalog)


@router.get(
    "/capabilities",
    response_model=RoutingCapabilitiesResponse,
    summary="Get supported modality profiles, capability flags, and pool strategies",
)
async def get_routing_capabilities() -> RoutingCapabilitiesResponse:
    """Retrieve catalog of supported model access profiles, capability flags, and selection strategies."""
    return RoutingCapabilitiesResponse(
        modality_profiles=[p.value for p in ModelAccessProfile],
        supported_capabilities=SUPPORTED_CAPABILITIES,
        credential_selection_strategies=[s.value for s in CredentialSelectionStrategy],
    )
