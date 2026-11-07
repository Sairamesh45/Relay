"""Service managing Virtual API Key generation, cryptographic hashing, rotation, and authentication."""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.routing_policy import VirtualKeyRoutingPolicy
from app.models.user import User
from app.models.virtual_api_key import VirtualAPIKey

settings = get_settings()


class VirtualKeyError(Exception):
    """Base exception for virtual key operations."""

    def __init__(self, message: str, code: str = "invalid_api_key") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class VirtualKeyNotFoundError(VirtualKeyError):
    """Key with specified identifier not found or unowned by user."""

    def __init__(self, message: str = "Virtual API key not found") -> None:
        super().__init__(message, code="key_not_found")


class InvalidVirtualKeyError(VirtualKeyError):
    """Key format invalid or hash mismatch."""

    def __init__(self, message: str = "Invalid API key provided") -> None:
        super().__init__(message, code="invalid_api_key")


class RevokedVirtualKeyError(VirtualKeyError):
    """Key has been revoked."""

    def __init__(self, message: str = "API key has been revoked") -> None:
        super().__init__(message, code="revoked_api_key")


class ExpiredVirtualKeyError(VirtualKeyError):
    """Key has passed its expiration time."""

    def __init__(self, message: str = "API key has expired") -> None:
        super().__init__(message, code="expired_api_key")


class VirtualKeyService:
    """Core cryptographic management of virtual API keys."""

    KEY_PREFIX = "uag_live_"
    PREFIX_LENGTH = 16  # "uag_live_" (9 chars) + 7 chars

    @classmethod
    def _generate_raw_key(cls) -> str:
        """Generate high-entropy random key string using secrets."""
        # 32 bytes of secure entropy base64-urlsafe encoded (~43 chars)
        entropy = secrets.token_urlsafe(32)
        return f"{cls.KEY_PREFIX}{entropy}"

    @classmethod
    def hash_key(cls, raw_key: str) -> str:
        """Compute keyed HMAC-SHA256 hex digest of the raw virtual key."""
        secret_bytes = settings.VIRTUAL_KEY_HMAC_SECRET.encode("utf-8")
        key_bytes = raw_key.strip().encode("utf-8")
        return hmac.new(secret_bytes, key_bytes, hashlib.sha256).hexdigest()

    async def create_key(
        self,
        db: AsyncSession,
        user: User,
        name: str,
        expires_at: datetime | None = None,
        permissions: dict[str, Any] | None = None,
    ) -> tuple[VirtualAPIKey, str]:
        """Generate, securely hash, and store a new virtual API key for the user.

        Returns (VirtualAPIKey model, raw_key plaintext).
        Plaintext raw_key is never stored and must be displayed only once.
        """
        raw_key = self._generate_raw_key()
        key_prefix = raw_key[: self.PREFIX_LENGTH]
        key_hash = self.hash_key(raw_key)

        key_record = VirtualAPIKey(
            user_id=user.id,
            name=name.strip(),
            key_prefix=key_prefix,
            key_hash=key_hash,
            permissions=permissions or {},
            is_active=True,
            expires_at=expires_at,
            created_at=datetime.now(UTC),
        )
        db.add(key_record)
        await db.flush()

        routing_policy = VirtualKeyRoutingPolicy(
            virtual_api_key_id=key_record.id,
            user_id=user.id,
            routing_mode="preset",
            routing_preset="balanced",
            quality_weight=Decimal("0.2500"),
            speed_weight=Decimal("0.2500"),
            availability_weight=Decimal("0.2500"),
            cost_weight=Decimal("0.2500"),
            model_access_profile="all_models",
            credential_selection_strategy="round_robin",
        )
        db.add(routing_policy)
        key_record.routing_policy = routing_policy
        await db.commit()
        return key_record, raw_key

    async def list_keys(
        self,
        db: AsyncSession,
        user: User,
    ) -> list[VirtualAPIKey]:
        """Retrieve all virtual keys belonging to the user."""
        stmt = (
            select(VirtualAPIKey)
            .where(VirtualAPIKey.user_id == user.id)
            .order_by(VirtualAPIKey.created_at.desc())
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    async def get_key(
        self,
        db: AsyncSession,
        user: User,
        key_id: uuid.UUID,
    ) -> VirtualAPIKey:
        """Retrieve a specific virtual key with strict ownership verification."""
        stmt = select(VirtualAPIKey).where(
            VirtualAPIKey.id == key_id,
            VirtualAPIKey.user_id == user.id,
        )
        res = await db.execute(stmt)
        key = res.scalar_one_or_none()
        if not key:
            raise VirtualKeyNotFoundError(
                f"Virtual key {key_id} not found or not owned by user."
            )
        return key

    async def revoke_key(
        self,
        db: AsyncSession,
        user: User,
        key_id: uuid.UUID,
    ) -> VirtualAPIKey:
        """Revoke a virtual key immediately."""
        key = await self.get_key(db, user, key_id)
        if key.is_active:
            now = datetime.now(UTC)
            key.is_active = False
            key.revoked_at = now
            await db.commit()
            await db.refresh(key)
        return key

    async def rotate_key(
        self,
        db: AsyncSession,
        user: User,
        key_id: uuid.UUID,
    ) -> tuple[VirtualAPIKey, str]:
        """Rotate key secret entropy while maintaining key configuration and identity."""
        key = await self.get_key(db, user, key_id)

        new_raw_key = self._generate_raw_key()
        key.key_prefix = new_raw_key[: self.PREFIX_LENGTH]
        key.key_hash = self.hash_key(new_raw_key)
        key.is_active = True
        key.revoked_at = None
        key.last_used_at = None

        await db.commit()
        await db.refresh(key)
        return key, new_raw_key

    async def authenticate_key(
        self,
        db: AsyncSession,
        raw_key: str,
    ) -> tuple[VirtualAPIKey, User]:
        """Authenticate an incoming Bearer virtual key and resolve its owner.

        Validates key structure, constant-time HMAC digest, revocation, and expiration.
        Updates last_used_at asynchronously.
        """
        clean_key = raw_key.strip()
        if not clean_key.startswith(self.KEY_PREFIX) or len(clean_key) < 30:
            raise InvalidVirtualKeyError("Invalid API key format.")

        computed_hash = self.hash_key(clean_key)

        # Lookup key by hash with eager-loaded user
        stmt = (
            select(VirtualAPIKey)
            .where(VirtualAPIKey.key_hash == computed_hash)
            .options(
                selectinload(VirtualAPIKey.user),
                selectinload(VirtualAPIKey.routing_policy),
            )
        )
        res = await db.execute(stmt)
        key = res.scalar_one_or_none()

        if key is None:
            raise InvalidVirtualKeyError("Invalid API key provided.")

        # Constant-time comparison
        if not hmac.compare_digest(key.key_hash, computed_hash):
            raise InvalidVirtualKeyError("Invalid API key provided.")

        if not key.is_active or key.revoked_at is not None:
            raise RevokedVirtualKeyError("API key has been revoked.")

        now = datetime.now(UTC)
        if key.expires_at is not None and key.expires_at < now:
            raise ExpiredVirtualKeyError("API key has expired.")

        # Update last_used_at safely
        key.last_used_at = now
        await db.commit()

        return key, key.user


# Singleton service instance
virtual_key_service = VirtualKeyService()


def get_virtual_key_service() -> VirtualKeyService:
    """FastAPI dependency provider for VirtualKeyService."""
    return virtual_key_service
