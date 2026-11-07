"""PostgreSQL-backed rate limit tracker model per virtual API key."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.virtual_api_key import VirtualAPIKey


class RateLimitBucket(Base):
    """Atomic fixed-window rate limiter state bucket stored in PostgreSQL per virtual API key."""

    __tablename__ = "rate_limit_buckets"

    key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("virtual_api_keys.id", ondelete="CASCADE"),
        primary_key=True,
    )
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    request_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    virtual_api_key: Mapped["VirtualAPIKey"] = relationship(
        "VirtualAPIKey",
        back_populates="rate_limit_bucket",
    )
