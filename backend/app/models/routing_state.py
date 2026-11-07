"""State tracking model for multi-worker concurrency-safe credential pool selection."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.provider_credential import ProviderCredential
    from app.models.user import User


class CredentialPoolState(Base):
    """Database-backed state for multi-worker concurrency-safe credential selection strategies (e.g. round robin)."""

    __tablename__ = "credential_pool_states"

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
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    provider_model_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    last_selected_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_credentials.id", ondelete="SET NULL"),
        nullable=True,
    )
    selection_counter: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User")
    last_selected_credential: Mapped["ProviderCredential | None"] = relationship(
        "ProviderCredential"
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            "provider_model_id",
            name="uq_pool_state_user_prov_model",
        ),
    )
