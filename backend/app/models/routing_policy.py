"""Virtual API Key Routing Policy model for intelligent candidate selection."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.provider_credential import ProviderCredential
    from app.models.user import User
    from app.models.virtual_api_key import VirtualAPIKey


class VirtualKeyRoutingPolicy(Base):
    """Per-virtual-key routing configuration dictating candidate discovery, scoring, and credential selection."""

    __tablename__ = "virtual_key_routing_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    virtual_api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("virtual_api_keys.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Routing mode & preset
    routing_mode: Mapped[str] = mapped_column(
        String(30),
        default="preset",
        server_default="preset",
        nullable=False,
    )
    routing_preset: Mapped[str] = mapped_column(
        String(50),
        default="balanced",
        server_default="balanced",
        nullable=False,
    )

    # Normalized component weights (sum to 1.0)
    quality_weight: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        default=Decimal("0.2500"),
        server_default="0.2500",
        nullable=False,
    )
    speed_weight: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        default=Decimal("0.2500"),
        server_default="0.2500",
        nullable=False,
    )
    availability_weight: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        default=Decimal("0.2500"),
        server_default="0.2500",
        nullable=False,
    )
    cost_weight: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        default=Decimal("0.2500"),
        server_default="0.2500",
        nullable=False,
    )

    # Model Access Profile & Modality Restrictions
    model_access_profile: Mapped[str] = mapped_column(
        String(50),
        default="all_models",
        server_default="all_models",
        nullable=False,
    )
    required_capabilities: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )

    # Provider and Model Whitelists/Blacklists
    allowed_providers: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )
    excluded_providers: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )
    allowed_models: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )
    excluded_models: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )

    # Provider & Credential Preferences
    preferred_provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    preferred_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_credentials.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Constraints & Capacity Thresholds
    minimum_context_window: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    maximum_cost_per_request: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 6),
        nullable=True,
    )

    # Strategy for selecting among eligible credentials offering the target model
    credential_selection_strategy: Mapped[str] = mapped_column(
        String(50),
        default="round_robin",
        server_default="round_robin",
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

    # Relationships
    virtual_api_key: Mapped["VirtualAPIKey"] = relationship(
        "VirtualAPIKey",
        back_populates="routing_policy",
    )
    user: Mapped["User"] = relationship("User")
    preferred_credential: Mapped["ProviderCredential | None"] = relationship(
        "ProviderCredential"
    )

    __table_args__ = (
        UniqueConstraint(
            "virtual_api_key_id",
            name="uq_virtual_key_routing_policies_key",
        ),
        Index("ix_vk_routing_policies_user", "user_id"),
    )
