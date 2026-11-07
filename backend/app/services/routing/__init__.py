"""Routing subsystem package."""

from app.services.routing.candidates import Candidate, CandidateDiscoveryService
from app.services.routing.context import RoutingContext
from app.services.routing.credential_pool import CredentialPoolManager
from app.services.routing.engine import (
    RoutingDecision,
    RoutingEngine,
    get_routing_engine,
)
from app.services.routing.policies import (
    ModelAccessProfile,
    RoutingPreset,
    get_preset_weights,
    validate_and_normalize_weights,
)
from app.services.routing.scoring import ModelScorer, ScoreBreakdown

__all__ = [
    "RoutingEngine",
    "get_routing_engine",
    "RoutingDecision",
    "RoutingContext",
    "Candidate",
    "CandidateDiscoveryService",
    "CredentialPoolManager",
    "RoutingPreset",
    "ModelAccessProfile",
    "get_preset_weights",
    "validate_and_normalize_weights",
    "ModelScorer",
    "ScoreBreakdown",
]
