"""Reliability event recorder and audit history persistence service.

Records and queries immutable audit events for rate limits, circuit breaker transitions,
cooldown periods, failover attempts, recoveries, and authentication failures with
strict redaction of sensitive credentials.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.gateway_request_log import GatewayRequestLog
from app.models.provider_credential import ProviderCredential
from app.models.reliability import (
    CircuitBreakerState,
    CircuitState,
    CredentialHealth,
    ReliabilityEvent,
    ReliabilityEventType,
)
from app.services.reliability.error_classifier import sanitize_dict

logger = logging.getLogger(__name__)


class EventRecorder:
    """Manages the creation and retrieval of reliability audit events."""

    async def record_event(
        self,
        db: AsyncSession,
        event_type: str | ReliabilityEventType,
        provider: str,
        credential_id: uuid.UUID | None = None,
        model_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReliabilityEvent:
        """Create and persist an immutable reliability event with sanitized metadata."""
        type_str = (
            event_type.value
            if isinstance(event_type, ReliabilityEventType)
            else str(event_type)
        )

        clean_metadata = sanitize_dict(metadata or {})
        # Extra safeguard: ensure never logging raw prompt or auth
        clean_metadata.pop("prompt", None)
        clean_metadata.pop("messages", None)
        clean_metadata.pop("authorization", None)
        clean_metadata.pop("api_key", None)

        event = ReliabilityEvent(
            event_type=type_str,
            provider=provider.lower() if provider else "unknown",
            credential_id=credential_id,
            model_id=model_id,
            event_metadata=clean_metadata,
            timestamp=datetime.now(UTC),
        )

        db.add(event)
        try:
            await db.flush()
        except Exception as exc:
            logger.warning("Failed to flush reliability event to database: %s", exc)

        return event

    async def record_rate_limit(
        self,
        db: AsyncSession,
        provider: str,
        credential_id: uuid.UUID | None = None,
        model_id: str | None = None,
        retry_after: float | int | None = None,
        details: dict[str, Any] | None = None,
    ) -> ReliabilityEvent:
        """Record a RATE_LIMIT_DETECTED event."""
        meta = details.copy() if details else {}
        if retry_after is not None:
            meta["retry_after"] = retry_after
        return await self.record_event(
            db=db,
            event_type=ReliabilityEventType.RATE_LIMIT_DETECTED,
            provider=provider,
            credential_id=credential_id,
            model_id=model_id,
            metadata=meta,
        )

    async def record_cooldown_started(
        self,
        db: AsyncSession,
        provider: str,
        credential_id: uuid.UUID | None = None,
        model_id: str | None = None,
        cooldown_seconds: float | None = None,
        reason: str | None = None,
    ) -> ReliabilityEvent:
        """Record a COOLDOWN_STARTED event."""
        meta: dict[str, Any] = {}
        if cooldown_seconds is not None:
            meta["cooldown_seconds"] = cooldown_seconds
        if reason:
            meta["reason"] = reason
        return await self.record_event(
            db=db,
            event_type=ReliabilityEventType.COOLDOWN_STARTED,
            provider=provider,
            credential_id=credential_id,
            model_id=model_id,
            metadata=meta,
        )

    async def record_circuit_opened(
        self,
        db: AsyncSession,
        provider: str,
        scope_type: str,
        scope_id: str,
        credential_id: uuid.UUID | None = None,
        model_id: str | None = None,
        failure_count: int | None = None,
    ) -> ReliabilityEvent:
        """Record a CIRCUIT_OPENED event."""
        return await self.record_event(
            db=db,
            event_type=ReliabilityEventType.CIRCUIT_OPENED,
            provider=provider,
            credential_id=credential_id,
            model_id=model_id,
            metadata={
                "scope_type": scope_type,
                "scope_id": scope_id,
                "failure_count": failure_count,
            },
        )

    async def record_circuit_half_open(
        self,
        db: AsyncSession,
        provider: str,
        scope_type: str,
        scope_id: str,
        credential_id: uuid.UUID | None = None,
        model_id: str | None = None,
    ) -> ReliabilityEvent:
        """Record a CIRCUIT_HALF_OPEN event."""
        return await self.record_event(
            db=db,
            event_type=ReliabilityEventType.CIRCUIT_HALF_OPEN,
            provider=provider,
            credential_id=credential_id,
            model_id=model_id,
            metadata={
                "scope_type": scope_type,
                "scope_id": scope_id,
            },
        )

    async def record_failover_started(
        self,
        db: AsyncSession,
        provider: str,
        from_candidate: dict[str, Any],
        to_candidate: dict[str, Any],
        level: int,
        reason: str | None = None,
    ) -> ReliabilityEvent:
        """Record a FAILOVER_STARTED event."""
        cred_id = to_candidate.get("credential_id")
        if isinstance(cred_id, str):
            try:
                cred_id = uuid.UUID(cred_id)
            except ValueError:
                cred_id = None

        return await self.record_event(
            db=db,
            event_type=ReliabilityEventType.FAILOVER_STARTED,
            provider=provider,
            credential_id=cred_id,
            model_id=to_candidate.get("model_id"),
            metadata={
                "failover_level": level,
                "from_candidate": sanitize_dict(from_candidate),
                "to_candidate": sanitize_dict(to_candidate),
                "reason": reason,
            },
        )

    async def record_failover_succeeded(
        self,
        db: AsyncSession,
        provider: str,
        candidate: dict[str, Any],
        attempts: int,
        level: int,
    ) -> ReliabilityEvent:
        """Record a FAILOVER_SUCCEEDED event."""
        cred_id = candidate.get("credential_id")
        if isinstance(cred_id, str):
            try:
                cred_id = uuid.UUID(cred_id)
            except ValueError:
                cred_id = None

        return await self.record_event(
            db=db,
            event_type=ReliabilityEventType.FAILOVER_SUCCEEDED,
            provider=provider,
            credential_id=cred_id,
            model_id=candidate.get("model_id"),
            metadata={
                "attempts": attempts,
                "failover_level": level,
                "candidate": sanitize_dict(candidate),
            },
        )

    async def record_failover_exhausted(
        self,
        db: AsyncSession,
        provider: str,
        total_attempts: int,
        reason: str | None = None,
    ) -> ReliabilityEvent:
        """Record a FAILOVER_EXHAUSTED event."""
        return await self.record_event(
            db=db,
            event_type=ReliabilityEventType.FAILOVER_EXHAUSTED,
            provider=provider,
            metadata={
                "total_attempts": total_attempts,
                "reason": reason,
            },
        )

    async def record_candidate_recovered(
        self,
        db: AsyncSession,
        provider: str,
        scope_type: str,
        scope_id: str,
        credential_id: uuid.UUID | None = None,
        model_id: str | None = None,
    ) -> ReliabilityEvent:
        """Record a CANDIDATE_RECOVERED event."""
        return await self.record_event(
            db=db,
            event_type=ReliabilityEventType.CANDIDATE_RECOVERED,
            provider=provider,
            credential_id=credential_id,
            model_id=model_id,
            metadata={
                "scope_type": scope_type,
                "scope_id": scope_id,
            },
        )

    async def record_auth_failed(
        self,
        db: AsyncSession,
        provider: str,
        credential_id: uuid.UUID | None = None,
        error_message: str | None = None,
    ) -> ReliabilityEvent:
        """Record a CREDENTIAL_AUTH_FAILED event."""
        return await self.record_event(
            db=db,
            event_type=ReliabilityEventType.CREDENTIAL_AUTH_FAILED,
            provider=provider,
            credential_id=credential_id,
            metadata={
                "error": error_message,
            },
        )

    async def record_provider_unavailable(
        self,
        db: AsyncSession,
        provider: str,
        credential_id: uuid.UUID | None = None,
        model_id: str | None = None,
        status_code: int | None = None,
        error_message: str | None = None,
    ) -> ReliabilityEvent:
        """Record a PROVIDER_UNAVAILABLE event."""
        return await self.record_event(
            db=db,
            event_type=ReliabilityEventType.PROVIDER_UNAVAILABLE,
            provider=provider,
            credential_id=credential_id,
            model_id=model_id,
            metadata={
                "status_code": status_code,
                "error": error_message,
            },
        )

    async def get_events(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        event_type: str | None = None,
        provider: str | None = None,
        credential_id: uuid.UUID | None = None,
        model_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ReliabilityEvent], int]:
        """Fetch paginated reliability events filtered by current user's credentials."""
        # Find user's credential IDs for authorization scoping
        user_cred_stmt = select(ProviderCredential.id).where(
            ProviderCredential.user_id == user_id
        )
        user_cred_res = await db.execute(user_cred_stmt)
        user_cred_ids = list(user_cred_res.scalars().all())

        # Base query for events
        stmt = select(ReliabilityEvent)
        count_stmt = select(func.count(ReliabilityEvent.id))

        conditions = []
        if user_cred_ids:
            # Match events linked to user's credentials or provider-wide events without credentials
            conditions.append(
                (ReliabilityEvent.credential_id.in_(user_cred_ids))
                | (ReliabilityEvent.credential_id.is_(None))
            )

        if event_type:
            conditions.append(ReliabilityEvent.event_type == event_type.strip().upper())
        if provider:
            conditions.append(ReliabilityEvent.provider == provider.strip().lower())
        if credential_id:
            conditions.append(ReliabilityEvent.credential_id == credential_id)
        if model_id:
            conditions.append(ReliabilityEvent.model_id == model_id)

        if conditions:
            from sqlalchemy import and_

            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))

        total_res = await db.execute(count_stmt)
        total = total_res.scalar_one() or 0

        stmt = (
            stmt.order_by(desc(ReliabilityEvent.timestamp)).limit(limit).offset(offset)
        )
        res = await db.execute(stmt)
        events = list(res.scalars().all())

        return events, total

    async def get_summary(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Aggregate reliability metrics and KPIs for the authenticated user."""
        # User credentials
        user_cred_stmt = select(ProviderCredential.id).where(
            ProviderCredential.user_id == user_id
        )
        user_cred_res = await db.execute(user_cred_stmt)
        user_cred_ids = list(user_cred_res.scalars().all())

        # Total requests from GatewayRequestLog
        req_count_stmt = select(func.count(GatewayRequestLog.id)).where(
            GatewayRequestLog.user_id == user_id
        )
        req_res = await db.execute(req_count_stmt)
        total_requests = req_res.scalar_one() or 0

        # Event counts
        event_cond = []
        if user_cred_ids:
            event_cond.append(
                (ReliabilityEvent.credential_id.in_(user_cred_ids))
                | (ReliabilityEvent.credential_id.is_(None))
            )

        events_stmt = select(
            ReliabilityEvent.event_type,
            ReliabilityEvent.provider,
            func.count(ReliabilityEvent.id),
        )
        if event_cond:
            events_stmt = events_stmt.where(*event_cond)
        events_stmt = events_stmt.group_by(
            ReliabilityEvent.event_type, ReliabilityEvent.provider
        )

        events_res = await db.execute(events_stmt)
        event_rows = events_res.all()

        failover_success_count = 0
        failover_started_count = 0
        circuit_trip_count = 0
        provider_counts: dict[str, int] = {}

        for ev_type, prov, cnt in event_rows:
            provider_counts[prov] = provider_counts.get(prov, 0) + cnt
            if ev_type == ReliabilityEventType.FAILOVER_SUCCEEDED.value:
                failover_success_count += cnt
            if ev_type == ReliabilityEventType.FAILOVER_STARTED.value:
                failover_started_count += cnt
            if ev_type == ReliabilityEventType.CIRCUIT_OPENED.value:
                circuit_trip_count += cnt

        # Active cooldowns count
        now = datetime.now(UTC)
        cooldown_stmt = select(func.count(CredentialHealth.id)).where(
            CredentialHealth.credential_id.in_(user_cred_ids)
            if user_cred_ids
            else False,
            CredentialHealth.cooldown_until > now,
        )
        cd_res = await db.execute(cooldown_stmt)
        active_cooldowns_count = cd_res.scalar_one() if user_cred_ids else 0

        # Open circuits count
        circuit_stmt = select(func.count(CircuitBreakerState.id)).where(
            CircuitBreakerState.state == CircuitState.OPEN
        )
        circ_res = await db.execute(circuit_stmt)
        open_circuits_count = circ_res.scalar_one() or 0

        # Calculate failover success rate
        failover_events_count = failover_started_count + failover_success_count
        failover_success_rate = (
            round((failover_success_count / failover_started_count) * 100, 1)
            if failover_started_count > 0
            else 100.0
        )

        return {
            "total_requests": total_requests,
            "failover_success_count": failover_success_count,
            "failover_started_count": failover_started_count,
            "failover_events_count": failover_events_count,
            "failover_success_rate": failover_success_rate,
            "circuit_trip_count": circuit_trip_count,
            "active_cooldowns_count": active_cooldowns_count,
            "open_circuits_count": open_circuits_count,
            "provider_stats": provider_counts,
        }


# Singleton instance
_event_recorder: EventRecorder | None = None


def get_event_recorder() -> EventRecorder:
    """Dependency getter for EventRecorder."""
    global _event_recorder
    if _event_recorder is None:
        _event_recorder = EventRecorder()
    return _event_recorder
