"""Routing decision audit log capturing candidate evaluation and explainability."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.provider_credential import ProviderCredential
    from app.models.user import User
    from app.models.virtual_api_key import VirtualAPIKey


class RoutingDecisionLog(Base):
    """Audit log tracking why a specific model offering and credential was selected for a gateway request."""

    __tablename__ = "routing_decision_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    request_id: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    virtual_api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("virtual_api_keys.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    routing_mode: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    routing_preset: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    selected_provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    selected_model: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    selected_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_credentials.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    candidate_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    selection_strategy: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    decision_latency_ms: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User")
    virtual_api_key: Mapped["VirtualAPIKey | None"] = relationship("VirtualAPIKey")
    selected_credential: Mapped["ProviderCredential | None"] = relationship(
        "ProviderCredential"
    )

    __table_args__ = (
        Index("ix_routing_decision_user_created", "user_id", "created_at"),
        Index("ix_routing_decision_key_created", "virtual_api_key_id", "created_at"),
    )
