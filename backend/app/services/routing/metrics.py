"""Operational historical metrics service aggregating latency and availability from gateway logs."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gateway_request_log import GatewayRequestLog


@dataclass
class CandidateMetrics:
    """Historical telemetry for a provider model / credential combination."""

    sample_count: int = 0
    avg_latency_ms: float | None = None
    success_rate: float = 1.0
    streaming_avg_latency_ms: float | None = None
    non_streaming_avg_latency_ms: float | None = None
    data_confidence: Literal["high", "medium", "low", "none"] = "none"


class RoutingMetricsService:
    """Computes bounded operational metrics from immutable gateway request logs."""

    def __init__(self, observation_window_days: int = 7) -> None:
        self.observation_window_days = observation_window_days

    async def get_metrics_for_candidates(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> dict[tuple[str, str, uuid.UUID | None], CandidateMetrics]:
        """Aggregate observed performance metrics grouped by (provider, provider_model_id, credential_id)."""
        cutoff = datetime.now(UTC) - timedelta(days=self.observation_window_days)

        # Aggregate overall counts, latency, and successes
        stmt = (
            select(
                GatewayRequestLog.provider,
                GatewayRequestLog.provider_model_id,
                GatewayRequestLog.provider_credential_id,
                GatewayRequestLog.streaming,
                func.count().label("req_count"),
                func.avg(GatewayRequestLog.latency_ms).label("avg_lat"),
                func.count()
                .filter(GatewayRequestLog.status == "success")
                .label("success_count"),
            )
            .where(
                GatewayRequestLog.user_id == user_id,
                GatewayRequestLog.created_at >= cutoff,
            )
            .group_by(
                GatewayRequestLog.provider,
                GatewayRequestLog.provider_model_id,
                GatewayRequestLog.provider_credential_id,
                GatewayRequestLog.streaming,
            )
        )
        res = await db.execute(stmt)
        rows = res.all()

        results: dict[tuple[str, str, uuid.UUID | None], CandidateMetrics] = {}

        # First pass: collect per streaming mode
        grouped: dict[tuple[str, str, uuid.UUID | None], dict[str, Any]] = {}
        for r in rows:
            key = (r.provider, r.provider_model_id, r.provider_credential_id)
            if key not in grouped:
                grouped[key] = {
                    "total_count": 0,
                    "success_count": 0,
                    "latency_sum": 0.0,
                    "streaming_lat": None,
                    "non_streaming_lat": None,
                }
            count = r.req_count
            avg_lat = float(r.avg_lat) if r.avg_lat is not None else 0.0
            grouped[key]["total_count"] += count
            grouped[key]["success_count"] += r.success_count
            grouped[key]["latency_sum"] += avg_lat * count
            if r.streaming:
                grouped[key]["streaming_lat"] = avg_lat
            else:
                grouped[key]["non_streaming_lat"] = avg_lat

        for key, data in grouped.items():
            tot = data["total_count"]
            succ = data["success_count"]
            avg = round(data["latency_sum"] / tot, 1) if tot > 0 else None
            succ_rate = round(succ / tot, 4) if tot > 0 else 1.0

            if tot >= 20:
                conf: Literal["high", "medium", "low", "none"] = "high"
            elif tot >= 5:
                conf = "medium"
            elif tot >= 1:
                conf = "low"
            else:
                conf = "none"

            results[key] = CandidateMetrics(
                sample_count=tot,
                avg_latency_ms=avg,
                success_rate=succ_rate,
                streaming_avg_latency_ms=data["streaming_lat"],
                non_streaming_avg_latency_ms=data["non_streaming_lat"],
                data_confidence=conf,
            )

        return results


routing_metrics_service = RoutingMetricsService()


def get_routing_metrics_service() -> RoutingMetricsService:
    """Dependency getter for RoutingMetricsService."""
    return routing_metrics_service
