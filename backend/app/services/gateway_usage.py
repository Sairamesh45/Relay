"""Service for recording request audit logs and computing user-scoped usage metrics."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gateway_request_log import GatewayRequestLog
from app.models.user import User
from app.schemas.gateway_usage import (
    GatewayRequestLogsListResponse,
    GatewayUsageSummaryResponse,
    ProviderUsageMetrics,
)


class GatewayUsageService:
    """Audit logging and usage analytics service."""

    async def record_request(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        virtual_api_key_id: uuid.UUID | None,
        provider_credential_id: uuid.UUID | None,
        provider: str,
        provider_model_id: str,
        gateway_model_id: str,
        request_id: str,
        status: str,
        status_code: int,
        latency_ms: int,
        streaming: bool = False,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> GatewayRequestLog:
        """Record an immutable gateway request log entry without storing sensitive prompt content."""
        if (
            total_tokens is None
            and input_tokens is not None
            and output_tokens is not None
        ):
            total_tokens = input_tokens + output_tokens

        log = GatewayRequestLog(
            user_id=user_id,
            virtual_api_key_id=virtual_api_key_id,
            provider_credential_id=provider_credential_id,
            provider=provider,
            provider_model_id=provider_model_id,
            gateway_model_id=gateway_model_id,
            request_id=request_id,
            status=status,
            status_code=status_code,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            streaming=streaming,
            error_code=error_code,
            error_summary=error_summary,
            created_at=datetime.now(UTC),
        )
        db.add(log)
        await db.commit()
        return log

    async def get_usage_summary(
        self,
        db: AsyncSession,
        user: User,
        provider: str | None = None,
    ) -> GatewayUsageSummaryResponse:
        """Compute aggregated usage statistics strictly for the authenticated user."""
        stmt = select(GatewayRequestLog).where(GatewayRequestLog.user_id == user.id)
        if provider:
            stmt = stmt.where(GatewayRequestLog.provider == provider.strip().lower())

        res = await db.execute(stmt)
        logs = list(res.scalars().all())

        total_requests = len(logs)
        successful = sum(1 for log in logs if log.status == "success")
        failed = sum(1 for log in logs if log.status != "success")
        total_in = sum(log.input_tokens or 0 for log in logs)
        total_out = sum(log.output_tokens or 0 for log in logs)
        total_tok = sum(log.total_tokens or 0 for log in logs)
        avg_lat = (
            sum(log.latency_ms for log in logs) / total_requests
            if total_requests > 0
            else 0.0
        )

        by_prov: dict[str, dict[str, int]] = {}
        by_model: dict[str, int] = {}

        for log in logs:
            p = log.provider
            if p not in by_prov:
                by_prov[p] = {
                    "total_requests": 0,
                    "total_tokens": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
            by_prov[p]["total_requests"] += 1
            by_prov[p]["total_tokens"] += log.total_tokens or 0
            by_prov[p]["input_tokens"] += log.input_tokens or 0
            by_prov[p]["output_tokens"] += log.output_tokens or 0

            m = log.gateway_model_id
            by_model[m] = by_model.get(m, 0) + 1

        provider_metrics = {
            p: ProviderUsageMetrics(**data) for p, data in by_prov.items()
        }

        return GatewayUsageSummaryResponse(
            total_requests=total_requests,
            successful_requests=successful,
            failed_requests=failed,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_tokens=total_tok,
            average_latency_ms=round(avg_lat, 2),
            by_provider=provider_metrics,
            by_model=by_model,
        )

    async def get_request_logs(
        self,
        db: AsyncSession,
        user: User,
        limit: int = 50,
        offset: int = 0,
        provider: str | None = None,
        status: str | None = None,
    ) -> GatewayRequestLogsListResponse:
        """Fetch paginated request logs scoped to the authenticated user."""
        query = select(GatewayRequestLog).where(GatewayRequestLog.user_id == user.id)
        if provider:
            query = query.where(GatewayRequestLog.provider == provider.strip().lower())
        if status:
            query = query.where(GatewayRequestLog.status == status.strip().lower())

        # Count total
        count_stmt = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_stmt)).scalar() or 0

        # Fetch records
        paged_stmt = (
            query.order_by(GatewayRequestLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        res = await db.execute(paged_stmt)
        records = list(res.scalars().all())

        return GatewayRequestLogsListResponse(
            total=total,
            limit=limit,
            offset=offset,
            logs=records,
        )


# Singleton instance
gateway_usage_service = GatewayUsageService()


def get_gateway_usage_service() -> GatewayUsageService:
    """FastAPI dependency provider for GatewayUsageService."""
    return gateway_usage_service
