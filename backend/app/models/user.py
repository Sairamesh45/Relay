"""User identity model for credential ownership and future OAuth integration."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.gateway_request_log import GatewayRequestLog
    from app.models.provider_credential import ProviderCredential
    from app.models.virtual_api_key import VirtualAPIKey


class User(Base):
    """Minimum internal user identity needed for credential ownership.

    Designed to support seamless future Google OAuth integration.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # Future OAuth provider hooks (e.g. 'google')
    oauth_provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    oauth_sub: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
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

    credentials: Mapped[list["ProviderCredential"]] = relationship(
        "ProviderCredential",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    virtual_api_keys: Mapped[list["VirtualAPIKey"]] = relationship(
        "VirtualAPIKey",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    gateway_request_logs: Mapped[list["GatewayRequestLog"]] = relationship(
        "GatewayRequestLog",
        back_populates="user",
        cascade="all, delete-orphan",
    )
