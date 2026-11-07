"""Tests for routing policies, presets, weight normalization, and validation."""

import math
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.routing.policies import (
    RoutingPreset,
    get_preset_weights,
    is_modality_compatible,
    validate_and_normalize_weights,
)
from app.services.virtual_key_service import VirtualKeyService


def test_preset_canonical_weights() -> None:
    """Verify standard presets resolve to documented normalized weights."""
    balanced = get_preset_weights(RoutingPreset.BALANCED)
    assert balanced == {
        "quality": 0.25,
        "speed": 0.25,
        "availability": 0.25,
        "cost": 0.25,
    }
    assert sum(balanced.values()) == 1.0

    quality = get_preset_weights(RoutingPreset.QUALITY_FIRST)
    assert quality["quality"] == 0.60
    assert sum(quality.values()) == 1.0

    speed = get_preset_weights(RoutingPreset.SPEED_FIRST)
    assert speed["speed"] == 0.60
    assert sum(speed.values()) == 1.0

    cost = get_preset_weights(RoutingPreset.COST_OPTIMIZED)
    assert cost["cost"] == 0.60
    assert sum(cost.values()) == 1.0


def test_custom_preset_requires_explicit_weights() -> None:
    """Verify get_preset_weights rejects CUSTOM since custom weights must be explicitly specified."""
    with pytest.raises(ValueError, match="Custom preset requires"):
        get_preset_weights(RoutingPreset.CUSTOM)


def test_validate_and_normalize_weights_success() -> None:
    """Verify valid weights are normalized so their sum equals 1.0."""
    res = validate_and_normalize_weights(
        quality=0.5, speed=0.5, availability=0.0, cost=0.0
    )
    assert res["quality"] == 0.5
    assert res["speed"] == 0.5
    assert res["availability"] == 0.0
    assert res["cost"] == 0.0
    assert math.isclose(sum(res.values()), 1.0, rel_tol=1e-3)

    # Sliders 1.0, 1.0, 1.0, 1.0 -> 0.25 each
    res4 = validate_and_normalize_weights(1.0, 1.0, 1.0, 1.0)
    assert res4["quality"] == 0.25
    assert res4["speed"] == 0.25
    assert res4["availability"] == 0.25
    assert res4["cost"] == 0.25


def test_validate_and_normalize_weights_invalid_rejection() -> None:
    """Verify rejection of NaN, infinity, negative values, and zero sums."""
    # NaN
    with pytest.raises(ValueError, match="cannot be NaN"):
        validate_and_normalize_weights(float("nan"), 0.5, 0.5, 0.5)

    # Inf
    with pytest.raises(ValueError, match="cannot be NaN or infinite"):
        validate_and_normalize_weights(float("inf"), 0.5, 0.5, 0.5)

    # Negative
    with pytest.raises(ValueError, match="must be between 0.0 and 1.0"):
        validate_and_normalize_weights(-0.1, 0.5, 0.5, 0.5)

    # Greater than 1.0
    with pytest.raises(ValueError, match="must be between 0.0 and 1.0"):
        validate_and_normalize_weights(1.5, 0.5, 0.5, 0.5)

    # All zeros
    with pytest.raises(ValueError, match="At least one routing priority weight"):
        validate_and_normalize_weights(0.0, 0.0, 0.0, 0.0)


def test_modality_compatibility_profiles() -> None:
    """Verify model access profiles correctly filter supported vs incompatible input modalities."""
    # Text-only permits strictly text
    assert is_modality_compatible("text_only", ["text"]) is True
    assert is_modality_compatible("text_only", ["text", "image"]) is False

    # Text+Image permits text and text+image
    assert is_modality_compatible("text_image", ["text"]) is True
    assert is_modality_compatible("text_image", ["text", "image"]) is True
    assert is_modality_compatible("text_image", ["text", "audio"]) is False

    # Text+Audio
    assert is_modality_compatible("text_audio", ["text", "audio"]) is True
    assert is_modality_compatible("text_audio", ["text", "image"]) is False

    # Text+Video
    assert is_modality_compatible("text_video", ["text", "video"]) is True
    assert is_modality_compatible("text_video", ["text", "audio"]) is False

    # All models / All modalities permits anything
    assert (
        is_modality_compatible("all_models", ["text", "image", "audio", "video"])
        is True
    )
    assert is_modality_compatible("all_modalities", ["text", "video"]) is True


@pytest.mark.asyncio
async def test_virtual_key_creation_generates_default_routing_policy(
    db_session: AsyncSession,
) -> None:
    """Verify that generating a new virtual API key automatically persists a default routing policy."""
    user = User(id=uuid.uuid4(), email=f"vk_policy_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.flush()

    key_record, _ = await VirtualKeyService().create_key(
        db_session, user, "Test Policy Key"
    )

    # Policy should exist and be associated with this key
    assert key_record.routing_policy is not None
    assert key_record.routing_policy.virtual_api_key_id == key_record.id
    assert key_record.routing_policy.user_id == user.id
    assert key_record.routing_policy.routing_mode == "preset"
    assert key_record.routing_policy.routing_preset == "balanced"
    assert key_record.routing_policy.quality_weight == Decimal("0.2500")
    assert key_record.routing_policy.speed_weight == Decimal("0.2500")
    assert key_record.routing_policy.availability_weight == Decimal("0.2500")
    assert key_record.routing_policy.cost_weight == Decimal("0.2500")
    assert key_record.routing_policy.model_access_profile == "all_models"
    assert key_record.routing_policy.credential_selection_strategy == "round_robin"


@pytest.mark.asyncio
async def test_per_virtual_key_policy_isolation(
    db_session: AsyncSession,
) -> None:
    """Verify two keys owned by the same user maintain completely independent routing policies."""
    user = User(
        id=uuid.uuid4(), email=f"multi_policy_{uuid.uuid4().hex[:8]}@example.com"
    )
    db_session.add(user)
    await db_session.flush()

    key_service = VirtualKeyService()
    key1, _ = await key_service.create_key(db_session, user, "Support Bot Key")
    key2, _ = await key_service.create_key(db_session, user, "Coding Agent Key")

    # Modify policy on key1
    policy1 = key1.routing_policy
    policy1.routing_preset = "speed_first"
    policy1.speed_weight = Decimal("0.6000")
    policy1.quality_weight = Decimal("0.1000")
    policy1.model_access_profile = "text_only"
    await db_session.commit()

    # Refresh key2 and verify policy2 is untouched
    await db_session.refresh(key2.routing_policy)
    policy2 = key2.routing_policy

    assert policy1.routing_preset == "speed_first"
    assert policy1.model_access_profile == "text_only"

    assert policy2.routing_preset == "balanced"
    assert policy2.model_access_profile == "all_models"
    assert policy2.speed_weight == Decimal("0.2500")
