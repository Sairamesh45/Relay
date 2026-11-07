"""Canonical UnifiedModel database model representing provider-agnostic model identities."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.provider_model import ProviderModel


class UnifiedModel(Base):
    """Canonical model identity representing a unique underlying AI model.

    Separates the abstract identity of a model from provider-specific offerings,
    ensuring multiple providers can offer the same model without false merging.
    """

    __tablename__ = "unified_models"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    canonical_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    provider_model_family: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    modality: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )
    input_modalities: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )
    output_modalities: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )
    model_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default="{}",
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

    provider_models: Mapped[list["ProviderModel"]] = relationship(
        "ProviderModel",
        back_populates="unified_model",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_unified_models_modality_family", "modality", "provider_model_family"),
    )
