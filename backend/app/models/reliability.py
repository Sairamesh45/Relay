"""Phase 6 Reliability and Automatic Failover Models.

Includes CredentialHealth, QuotaState, CircuitBreakerState, and ReliabilityEvent.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.provider_credential import ProviderCredential


class HealthStatus(enum.StrEnum):
    """Health states for provider credentials."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    COOLING_DOWN = "cooling_down"
    AUTH_FAILED = "auth_failed"
    PERM_DENIED = "perm_denied"
    TEMP_UNAVAILABLE = "temp_unavailable"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class CircuitState(enum.StrEnum):
    """Operational states for circuit breakers."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ReliabilityEventType(enum.StrEnum):
    """Discrete operational reliability audit event types."""

    RATE_LIMIT_DETECTED = "RATE_LIMIT_DETECTED"
    COOLDOWN_STARTED = "COOLDOWN_STARTED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CIRCUIT_OPENED = "CIRCUIT_OPENED"
    CIRCUIT_HALF_OPEN = "CIRCUIT_HALF_OPEN"
    FAILOVER_STARTED = "FAILOVER_STARTED"
    FAILOVER_SUCCEEDED = "FAILOVER_SUCCEEDED"
    FAILOVER_EXHAUSTED = "FAILOVER_EXHAUSTED"
    CANDIDATE_RECOVERED = "CANDIDATE_RECOVERED"
    CREDENTIAL_AUTH_FAILED = "CREDENTIAL_AUTH_FAILED"


class QuotaScope(enum.StrEnum):
    """Scope granularity for quota state observations."""

    CREDENTIAL = "credential"
    MODEL = "model"
    ORGANIZATION = "organization"


class QuotaResourceType(enum.StrEnum):
    """Resource types tracked in quota states."""

    REQUESTS = "requests"
    TOKENS = "tokens"
    CREDITS = "credits"


class QuotaConfidence(enum.StrEnum):
    """Confidence tier of quota state measurements."""

    CONFIRMED = "confirmed"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class CredentialHealth(Base):
    """Tracks operational health, consecutive failure counts, and cooldown windows for a provider credential."""

    __tablename__ = "credential_healths"
    __table_args__ = (
        Index("ix_credential_healths_status_updated", "health_status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    credential_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_credentials.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    health_status: Mapped[HealthStatus] = mapped_column(
        sa.Enum(
            HealthStatus,
            native_enum=False,
            length=50,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=HealthStatus.HEALTHY,
        nullable=False,
        index=True,
    )
    failure_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_error_category: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    error_details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    credential: Mapped[ProviderCredential] = relationship(
        "ProviderCredential",
        foreign_keys=[credential_id],
        lazy="joined",
    )

    def __init__(self, **kwargs: Any) -> None:
        # Handle aliases and normalize enum strings
        if "cooldown_expires_at" in kwargs and "cooldown_until" not in kwargs:
            kwargs["cooldown_until"] = kwargs.pop("cooldown_expires_at")
        if "status" in kwargs and "health_status" not in kwargs:
            kwargs["health_status"] = kwargs.pop("status")
        kwargs.setdefault("health_status", HealthStatus.HEALTHY)
        kwargs.setdefault("failure_count", 0)
        kwargs.setdefault("consecutive_failures", 0)
        kwargs.setdefault("error_details", {})
        super().__init__(**kwargs)

    @property
    def cooldown_expires_at(self) -> datetime | None:
        """Alias for cooldown_until."""
        return self.cooldown_until

    @cooldown_expires_at.setter
    def cooldown_expires_at(self, value: datetime | None) -> None:
        self.cooldown_until = value

    @property
    def is_cooling_down(self) -> bool:
        """Return True if currently in active cooldown window."""
        if not self.cooldown_until:
            return False
        return datetime.now(UTC) < self.cooldown_until

    def to_dict(self) -> dict[str, Any]:
        """Serialize health state to dict."""
        return {
            "id": str(self.id),
            "credential_id": str(self.credential_id),
            "health_status": (
                self.health_status.value
                if isinstance(self.health_status, enum.Enum)
                else str(self.health_status)
            ),
            "failure_count": self.failure_count,
            "consecutive_failures": self.consecutive_failures,
            "last_success_at": (
                self.last_success_at.isoformat() if self.last_success_at else None
            ),
            "last_failure_at": (
                self.last_failure_at.isoformat() if self.last_failure_at else None
            ),
            "cooldown_until": (
                self.cooldown_until.isoformat() if self.cooldown_until else None
            ),
            "last_error_category": self.last_error_category,
            "error_details": self.error_details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<CredentialHealth credential_id={self.credential_id} "
            f"status={self.health_status} failures={self.consecutive_failures}>"
        )


class QuotaState(Base):
    """Tracks observed rate-limit and quota metrics across credentials, models, and providers."""

    __tablename__ = "quota_states"
    __table_args__ = (
        Index(
            "ix_quota_states_lookup",
            "credential_id",
            "provider",
            "quota_scope",
            "resource_type",
            "model_id",
        ),
        Index("ix_quota_states_cred_observed", "credential_id", "observed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_credentials.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    quota_scope: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    model_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    resource_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    limit: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    remaining: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    retry_after: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    confidence: Mapped[str] = mapped_column(
        String(50),
        default="unknown",
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(100),
        default="header",
        nullable=False,
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    credential: Mapped[ProviderCredential | None] = relationship(
        "ProviderCredential",
        foreign_keys=[credential_id],
        lazy="select",
    )

    def __init__(self, **kwargs: Any) -> None:
        if "limit_value" in kwargs and "limit" not in kwargs:
            kwargs["limit"] = kwargs.pop("limit_value")
        if "remaining_value" in kwargs and "remaining" not in kwargs:
            kwargs["remaining"] = kwargs.pop("remaining_value")
        if "retry_after_seconds" in kwargs and "retry_after" not in kwargs:
            kwargs["retry_after"] = kwargs.pop("retry_after_seconds")
        kwargs.setdefault("confidence", "unknown")
        kwargs.setdefault("source", "header")
        super().__init__(**kwargs)

    @property
    def limit_value(self) -> int | None:
        """Alias for limit."""
        return self.limit

    @limit_value.setter
    def limit_value(self, value: int | None) -> None:
        self.limit = value

    @property
    def remaining_value(self) -> int | None:
        """Alias for remaining."""
        return self.remaining

    @remaining_value.setter
    def remaining_value(self, value: int | None) -> None:
        self.remaining = value

    @property
    def retry_after_seconds(self) -> int | None:
        """Alias for retry_after."""
        return self.retry_after

    @retry_after_seconds.setter
    def retry_after_seconds(self, value: int | None) -> None:
        self.retry_after = value

    def to_dict(self) -> dict[str, Any]:
        """Serialize quota state to dict."""
        return {
            "id": str(self.id),
            "credential_id": str(self.credential_id) if self.credential_id else None,
            "provider": self.provider,
            "quota_scope": self.quota_scope,
            "model_id": self.model_id,
            "resource_type": self.resource_type,
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_at": self.reset_at.isoformat() if self.reset_at else None,
            "retry_after": self.retry_after,
            "confidence": self.confidence,
            "source": self.source,
            "observed_at": (self.observed_at.isoformat() if self.observed_at else None),
        }

    def __repr__(self) -> str:
        return (
            f"<QuotaState provider={self.provider} scope={self.quota_scope} "
            f"type={self.resource_type} remaining={self.remaining}/{self.limit}>"
        )


class CircuitBreakerState(Base):
    """PostgreSQL-backed state tracking for circuit breakers across providers, models, or credentials."""

    __tablename__ = "circuit_breaker_states"
    __table_args__ = (
        UniqueConstraint(
            "scope_type",
            "scope_id",
            name="uq_circuit_breaker_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    scope_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    scope_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    state: Mapped[CircuitState] = mapped_column(
        sa.Enum(
            CircuitState,
            native_enum=False,
            length=20,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=CircuitState.CLOSED,
        nullable=False,
        index=True,
    )
    failure_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    success_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    last_state_change: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    probe_requests_in_flight: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    def __init__(self, **kwargs: Any) -> None:
        if "consecutive_failures" in kwargs and "failure_count" not in kwargs:
            kwargs["failure_count"] = kwargs.pop("consecutive_failures")
        if "consecutive_successes" in kwargs and "success_count" not in kwargs:
            kwargs["success_count"] = kwargs.pop("consecutive_successes")
        kwargs.setdefault("state", CircuitState.CLOSED)
        kwargs.setdefault("failure_count", 0)
        kwargs.setdefault("success_count", 0)
        kwargs.setdefault("probe_requests_in_flight", 0)
        super().__init__(**kwargs)

    @property
    def consecutive_failures(self) -> int:
        """Alias for failure_count."""
        return self.failure_count

    @consecutive_failures.setter
    def consecutive_failures(self, value: int) -> None:
        self.failure_count = value

    @property
    def consecutive_successes(self) -> int:
        """Alias for success_count."""
        return self.success_count

    @consecutive_successes.setter
    def consecutive_successes(self, value: int) -> None:
        self.success_count = value

    @property
    def probe_in_flight(self) -> bool:
        """True if any recovery probe request is currently executing."""
        return self.probe_requests_in_flight > 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize circuit breaker state to dict."""
        return {
            "id": str(self.id),
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "state": (
                self.state.value
                if isinstance(self.state, enum.Enum)
                else str(self.state)
            ),
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_state_change": (
                self.last_state_change.isoformat() if self.last_state_change else None
            ),
            "probe_requests_in_flight": self.probe_requests_in_flight,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<CircuitBreakerState scope={self.scope_type}:{self.scope_id} "
            f"state={self.state} failures={self.failure_count}>"
        )


class ReliabilityEvent(Base):
    """Immutable audit trail of reliability and automatic failover events."""

    __tablename__ = "reliability_events"
    __table_args__ = (
        Index("ix_reliability_events_cred_timestamp", "credential_id", "timestamp"),
        Index("ix_reliability_events_prov_timestamp", "provider", "timestamp"),
        Index("ix_reliability_events_type_timestamp", "event_type", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_credentials.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    model_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    credential: Mapped[ProviderCredential | None] = relationship(
        "ProviderCredential",
        foreign_keys=[credential_id],
        lazy="select",
    )

    def __init__(self, **kwargs: Any) -> None:
        # Handle 'metadata' or 'metadata_json' kwarg safely without colliding with DeclarativeBase.metadata
        if "metadata" in kwargs and "event_metadata" not in kwargs:
            kwargs["event_metadata"] = kwargs.pop("metadata")
        elif "metadata_json" in kwargs and "event_metadata" not in kwargs:
            kwargs["event_metadata"] = kwargs.pop("metadata_json")
        if "event_type" in kwargs and isinstance(kwargs["event_type"], enum.Enum):
            kwargs["event_type"] = kwargs["event_type"].value
        kwargs.setdefault("event_metadata", {})
        super().__init__(**kwargs)

    @property
    def metadata_json(self) -> dict[str, Any]:
        """Expose event metadata dictionary."""
        return self.event_metadata

    @metadata_json.setter
    def metadata_json(self, value: dict[str, Any]) -> None:
        self.event_metadata = value

    def to_dict(self) -> dict[str, Any]:
        """Serialize reliability event to dict."""
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "event_type": self.event_type,
            "provider": self.provider,
            "credential_id": str(self.credential_id) if self.credential_id else None,
            "model_id": self.model_id,
            "metadata": self.event_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<ReliabilityEvent id={self.id} type={self.event_type} "
            f"provider={self.provider} model={self.model_id}>"
        )
