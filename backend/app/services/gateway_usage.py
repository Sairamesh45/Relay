"""Service for recording request audit logs and computing user-scoped usage metrics."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import case, func, select
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
        base_filter = [GatewayRequestLog.user_id == user.id]
        if provider:
            base_filter.append(GatewayRequestLog.provider == provider.strip().lower())

        # 1. Overall totals using func.count(), func.sum(), func.avg()
        totals_stmt = select(
            func.count(GatewayRequestLog.id).label("total_requests"),
            func.sum(
                case((GatewayRequestLog.status == "success", 1), else_=0)
            ).label("successful_requests"),
            func.sum(
                case((GatewayRequestLog.status != "success", 1), else_=0)
            ).label("failed_requests"),
            func.coalesce(func.sum(GatewayRequestLog.input_tokens), 0).label(
                "total_input_tokens"
            ),
            func.coalesce(func.sum(GatewayRequestLog.output_tokens), 0).label(
                "total_output_tokens"
            ),
            func.coalesce(func.sum(GatewayRequestLog.total_tokens), 0).label(
                "total_tokens"
            ),
            func.coalesce(func.avg(GatewayRequestLog.latency_ms), 0.0).label("avg_lat"),
        ).where(*base_filter)

        totals_res = await db.execute(totals_stmt)
        totals_row = totals_res.one()

        total_requests = int(totals_row.total_requests or 0)
        successful = int(totals_row.successful_requests or 0)
        failed = int(totals_row.failed_requests or 0)
        total_in = int(totals_row.total_input_tokens or 0)
        total_out = int(totals_row.total_output_tokens or 0)
        total_tok = int(totals_row.total_tokens or 0)
        avg_lat = float(totals_row.avg_lat or 0.0)

        # 2. Provider breakdown using GROUP BY GatewayRequestLog.provider
        prov_stmt = (
            select(
                GatewayRequestLog.provider,
                func.count(GatewayRequestLog.id).label("total_requests"),
                func.coalesce(func.sum(GatewayRequestLog.total_tokens), 0).label(
                    "total_tokens"
                ),
                func.coalesce(func.sum(GatewayRequestLog.input_tokens), 0).label(
                    "input_tokens"
                ),
                func.coalesce(func.sum(GatewayRequestLog.output_tokens), 0).label(
                    "output_tokens"
                ),
            )
            .where(*base_filter)
            .group_by(GatewayRequestLog.provider)
        )
        prov_res = await db.execute(prov_stmt)
        provider_metrics = {
            p_row.provider: ProviderUsageMetrics(
                total_requests=int(p_row.total_requests or 0),
                total_tokens=int(p_row.total_tokens or 0),
                input_tokens=int(p_row.input_tokens or 0),
                output_tokens=int(p_row.output_tokens or 0),
            )
            for p_row in prov_res.all()
        }

        # 3. Model breakdown using GROUP BY GatewayRequestLog.gateway_model_id
        model_stmt = (
            select(
                GatewayRequestLog.gateway_model_id,
                func.count(GatewayRequestLog.id).label("total_requests"),
            )
            .where(*base_filter)
            .group_by(GatewayRequestLog.gateway_model_id)
        )
        model_res = await db.execute(model_stmt)
        by_model = {
            m_row.gateway_model_id: int(m_row.total_requests or 0)
            for m_row in model_res.all()
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
