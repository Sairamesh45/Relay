"""Explainability generator translating scoring and filtering decisions into human-readable narratives."""

from app.services.routing.candidates import Candidate
from app.services.routing.scoring import ScoreBreakdown


def generate_routing_explanation(
    selected: Candidate,
    score_breakdown: ScoreBreakdown | None,
    candidate_count: int,
    selection_strategy: str,
    strategy_explanation: str,
    routing_mode: str,
) -> str:
    """Generate a concise, auditable narrative explaining why Relay routed the request to the selected candidate."""
    if routing_mode == "explicit":
        return (
            f"Explicit request for '{selected.gateway_model_id}'. "
            f"{strategy_explanation}"
        )

    score_text = (
        f"Ranked #1 with composite score {score_breakdown.final_score:.4f} "
        f"across {candidate_count} eligible candidates. "
        if score_breakdown
        else ""
    )

    return (
        f"{score_text}"
        f"Offering on provider '{selected.provider}' chosen. "
        f"{strategy_explanation}"
    )
