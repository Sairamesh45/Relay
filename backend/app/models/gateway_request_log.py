"""Gateway request audit log capturing usage metrics, latency, and status without logging prompt secrets."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.provider_credential import ProviderCredential
    from app.models.user import User
    from app.models.virtual_api_key import VirtualAPIKey


class GatewayRequestLog(Base):
    """Immutable audit record of each request processed through the unified gateway.

    Captures latency, token counts, and operational status without recording prompt bodies,
    completion text, or API key secrets.
    """

    __tablename__ = "gateway_request_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
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
    provider_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_credentials.id", ondelete="SET NULL"),
        nullable=True,
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
    )
    gateway_model_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    request_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )
    status_code: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    input_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    output_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    total_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    latency_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    streaming: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    error_code: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    error_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="gateway_request_logs",
    )
    virtual_api_key: Mapped["VirtualAPIKey | None"] = relationship(
        "VirtualAPIKey",
        back_populates="request_logs",
    )
    provider_credential: Mapped["ProviderCredential | None"] = relationship(
        "ProviderCredential",
    )

    __table_args__ = (
        Index("ix_gateway_logs_user_created", "user_id", "created_at"),
        Index("ix_gateway_logs_key_created", "virtual_api_key_id", "created_at"),
        Index(
            "ix_gateway_logs_user_provider_created",
            "user_id",
            "provider",
            "created_at",
        ),
        Index(
            "ix_gateway_logs_user_status_created",
            "user_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_gateway_logs_user_cred_created",
            "user_id",
            "provider_credential_id",
            "created_at",
        ),
    )

