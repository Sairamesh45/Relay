"""Explainable, multi-factor scoring engine evaluating Quality, Speed, Availability, and Cost."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.services.routing.candidates import Candidate
from app.services.routing.metrics import CandidateMetrics
from app.services.routing.policies import (
    RoutingPreset,
    get_preset_weights,
    validate_and_normalize_weights,
)


@dataclass
class ScoreBreakdown:
    """Detailed explainable breakdown of a candidate's scoring evaluation."""

    final_score: float
    quality_score: float
    speed_score: float
    availability_score: float
    cost_score: float
    effective_weights: dict[str, float]
    data_confidence: str
    missing_measurements: list[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert breakdown to serialized dictionary for audit and API responses."""
        return {
            "final_score": round(self.final_score, 4),
            "quality_score": round(self.quality_score, 4),
            "speed_score": round(self.speed_score, 4),
            "availability_score": round(self.availability_score, 4),
            "cost_score": round(self.cost_score, 4),
            "effective_weights": self.effective_weights,
            "data_confidence": self.data_confidence,
            "missing_measurements": self.missing_measurements,
            "explanation": self.explanation,
        }


@dataclass
class ScoredCandidate:
    """Candidate paired with its verified score breakdown."""

    candidate: Candidate
    score_breakdown: ScoreBreakdown


class ModelScorer:
    """Computes verified, explainable scores without fabricating intelligence metrics."""

    def resolve_effective_weights(
        self,
        routing_mode: str,
        routing_preset: str,
        quality_weight: Decimal | float,
        speed_weight: Decimal | float,
        availability_weight: Decimal | float,
        cost_weight: Decimal | float,
        alias_override: str | None = None,
    ) -> dict[str, float]:
        """Resolve normalized priority weights based on presets, custom sliders, or alias overrides."""
        # 1. Aliases override presets directly
        if alias_override == "fast":
            return get_preset_weights(RoutingPreset.SPEED_FIRST)
        if alias_override == "cheap":
            return get_preset_weights(RoutingPreset.COST_OPTIMIZED)
        if alias_override == "smart":
            return get_preset_weights(RoutingPreset.QUALITY_FIRST)

        # 2. Preset vs Custom policy mode
        if routing_mode == "custom" or routing_preset == "custom":
            return validate_and_normalize_weights(
                quality=quality_weight,
                speed=speed_weight,
                availability=availability_weight,
                cost=cost_weight,
            )

        return get_preset_weights(routing_preset)

    def score_candidate(
        self,
        candidate: Candidate,
        metrics: CandidateMetrics | None,
        weights: dict[str, float],
    ) -> ScoreBreakdown:
        """Evaluate a single candidate against verified capability evidence and observed telemetry."""
        missing: list[str] = []
        conf = "none"

        # 1. Quality dimension: Derived from verified model capabilities and capacity
        # Baseline text generation = 0.40
        quality = 0.40
        if candidate.supports_tools:
            quality += 0.20
        if candidate.supports_structured_output:
            quality += 0.15
        if candidate.supports_reasoning:
            quality += 0.15
        if candidate.supports_vision:
            quality += 0.10
        if candidate.context_window and candidate.context_window >= 128_000:
            quality += 0.05
        quality_score = min(1.0, quality)

        # 2. Speed dimension: Derived from observed historical latency (prefer non-streaming)
        lat = None
        if metrics:
            if metrics.non_streaming_avg_latency_ms is not None:
                lat = metrics.non_streaming_avg_latency_ms
                conf = metrics.data_confidence
            elif metrics.avg_latency_ms is not None:
                lat = metrics.avg_latency_ms
                conf = metrics.data_confidence
                missing.append("non_streaming_latency")

        if lat is not None:
            # Scale: <= 200ms -> 1.0; >= 5000ms -> 0.0
            speed_score = max(0.0, min(1.0, 1.0 - ((lat - 200.0) / 4800.0)))
        else:
            missing.append("observed_latency")
            speed_score = 0.50  # Neutral proxy for unmeasured models

        # 3. Availability dimension: Derived from operational success rate
        if metrics and metrics.sample_count > 0:
            availability_score = max(0.0, min(1.0, metrics.success_rate))
        else:
            missing.append("historical_availability")
            availability_score = 0.75  # Verified available in provider model catalog

        # 4. Cost dimension: Derived from verified input/output token pricing
        if (
            candidate.input_price_per_million is not None
            and candidate.output_price_per_million is not None
        ):
            avg_price = float(
                (candidate.input_price_per_million + candidate.output_price_per_million)
                / 2
            )
            # Scale: $0/M (free) -> 1.0; $20/M -> 0.0
            cost_score = max(0.0, min(1.0, 1.0 - (avg_price / 20.0)))
        else:
            missing.append("pricing_metadata")
            cost_score = 0.50  # Neutral proxy when pricing is unlisted

        # 5. Composite weighted final score
        final_score = (
            quality_score * weights["quality"]
            + speed_score * weights["speed"]
            + availability_score * weights["availability"]
            + cost_score * weights["cost"]
        )

        # Explanation synthesis
        reasons: list[str] = [
            f"Quality ({quality_score:.2f} * {weights['quality']:.2f})",
            f"Speed ({speed_score:.2f} * {weights['speed']:.2f})",
            f"Availability ({availability_score:.2f} * {weights['availability']:.2f})",
            f"Cost ({cost_score:.2f} * {weights['cost']:.2f})",
        ]
        if missing:
            reasons.append(f"Unmeasured: {', '.join(missing)}")

        explanation = f"Score {final_score:.4f} derived from {'; '.join(reasons)}."

        return ScoreBreakdown(
            final_score=final_score,
            quality_score=quality_score,
            speed_score=speed_score,
            availability_score=availability_score,
            cost_score=cost_score,
            effective_weights=weights,
            data_confidence=conf,
            missing_measurements=missing,
            explanation=explanation,
        )

    def rank_candidates(
        self,
        candidates: list[Candidate],
        metrics_map: dict[tuple[str, str, Any], CandidateMetrics],
        weights: dict[str, float],
    ) -> list[ScoredCandidate]:
        """Score and deterministically rank candidates.

        Tie-breaking order:
        1. final_score (descending)
        2. observed average latency (ascending)
        3. provider name (alphabetical)
        4. provider model ID (alphabetical)
        5. credential ID (uuid string)
        """
        scored_list: list[ScoredCandidate] = []
        for c in candidates:
            m = metrics_map.get((c.provider, c.provider_model_id, c.credential_id))
            if m is None:
                # Fallback to model-level metric without credential scoping
                m = metrics_map.get((c.provider, c.provider_model_id, None))
            breakdown = self.score_candidate(c, m, weights)
            scored_list.append(ScoredCandidate(candidate=c, score_breakdown=breakdown))

        def sort_key(sc: ScoredCandidate) -> tuple[float, float, str, str, str]:
            lat = 999999.0
            m = metrics_map.get(
                (
                    sc.candidate.provider,
                    sc.candidate.provider_model_id,
                    sc.candidate.credential_id,
                )
            )
            if m:
                if m.non_streaming_avg_latency_ms is not None:
                    lat = m.non_streaming_avg_latency_ms
                elif m.avg_latency_ms is not None:
                    lat = m.avg_latency_ms
            return (
                -sc.score_breakdown.final_score,
                lat,
                sc.candidate.provider,
                sc.candidate.provider_model_id,
                str(sc.candidate.credential_id),
            )

        scored_list.sort(key=sort_key)
        return scored_list


model_scorer = ModelScorer()


def get_model_scorer() -> ModelScorer:
    """Dependency getter for ModelScorer."""
    return model_scorer
