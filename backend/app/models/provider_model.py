"""Provider-specific offering model linking canonical models to provider credentials."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.provider_credential import ProviderCredential
    from app.models.unified_model import UnifiedModel


class ProviderModel(Base):
    """Represents a specific offering of a canonical model by a provider.

    Tracks availability, capabilities, pricing, and provenance scoped to either
    a connected user credential or global provider offering.
    """

    __tablename__ = "provider_models"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    unified_model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("unified_models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    provider_model_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_credentials.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Context & Token Capacity
    context_window: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    max_output_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Pricing per 1,000,000 tokens (USD)
    input_price_per_million: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 6),
        nullable=True,
    )
    output_price_per_million: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 6),
        nullable=True,
    )

    # Functional Capabilities
    supports_streaming: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    supports_tools: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    supports_structured_output: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    supports_vision: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
    supports_reasoning: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    # Operational status & metadata provenance
    availability_status: Mapped[str] = mapped_column(
        String(20),
        default="available",
        server_default="available",
        nullable=False,
        index=True,
    )
    metadata_source: Mapped[str] = mapped_column(
        String(30),
        default="provider_api",
        server_default="provider_api",
        nullable=False,
    )

    # Provenance tracking: confirmed vs. inferred vs. unknown per capability
    capability_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )

    # Observability & sync timestamps
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
    unified_model: Mapped["UnifiedModel"] = relationship(
        "UnifiedModel",
        back_populates="provider_models",
        lazy="selectin",
    )
    credential: Mapped["ProviderCredential | None"] = relationship(
        "ProviderCredential",
        back_populates="provider_models",
    )

    __table_args__ = (
        UniqueConstraint(
            "credential_id",
            "provider",
            "provider_model_id",
            name="uq_provider_models_cred_prov_model",
        ),
        Index("ix_provider_models_provider_status", "provider", "availability_status"),
        Index("ix_provider_models_cred_prov", "credential_id", "provider"),
        Index(
            "uq_provider_models_global_prov_model",
            "provider",
            "provider_model_id",
            unique=True,
            postgresql_where=text("credential_id IS NULL"),
        ),
        Index(
            "ix_provider_models_cred_avail_unified",
            "credential_id",
            "availability_status",
            "unified_model_id",
        ),
    )

