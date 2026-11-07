"""Unit and service tests for Virtual API Key generation, hashing, lifecycle, and isolation."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.virtual_api_key import VirtualAPIKey
from app.services.virtual_key_service import (
    ExpiredVirtualKeyError,
    InvalidVirtualKeyError,
    RevokedVirtualKeyError,
    VirtualKeyNotFoundError,
    VirtualKeyService,
)


@pytest.mark.asyncio
async def test_virtual_key_generation_and_storage(db_session: AsyncSession) -> None:
    """Verify cryptographically secure key generation and that raw key is never stored."""
    service = VirtualKeyService()
    user = User(id=uuid.uuid4(), email=f"vk_test_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.commit()

    key_record, raw_key = await service.create_key(
        db=db_session,
        user=user,
        name="Production Bot Key",
        permissions={"models": ["gemini:*"]},
    )

    # 1. Format and entropy
    assert raw_key.startswith("uag_live_")
    assert len(raw_key) > 40
    assert key_record.key_prefix == raw_key[:16]

    # 2. Key hash stored, not raw key
    assert raw_key != key_record.key_hash
    assert len(key_record.key_hash) == 64  # SHA256 hex length
    assert key_record.is_active is True
    assert key_record.name == "Production Bot Key"

    # 3. Direct DB lookup confirms plaintext secret is NOT present in table
    stored = (
        await db_session.execute(
            select(VirtualAPIKey).where(VirtualAPIKey.id == key_record.id)
        )
    ).scalar_one()
    assert stored.key_hash == VirtualKeyService.hash_key(raw_key)


@pytest.mark.asyncio
async def test_virtual_key_authentication_success_and_last_used(
    db_session: AsyncSession,
) -> None:
    """Verify valid key authenticates and asynchronously updates last_used_at."""
    service = VirtualKeyService()
    user = User(id=uuid.uuid4(), email=f"auth_test_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.commit()

    key_record, raw_key = await service.create_key(
        db=db_session, user=user, name="App Key"
    )
    assert key_record.last_used_at is None

    auth_key, auth_user = await service.authenticate_key(db_session, raw_key)
    assert auth_key.id == key_record.id
    assert auth_user.id == user.id
    assert auth_key.last_used_at is not None


@pytest.mark.asyncio
async def test_virtual_key_revocation_and_rejection(db_session: AsyncSession) -> None:
    """Verify revoked key is immediately rejected during authentication."""
    service = VirtualKeyService()
    user = User(id=uuid.uuid4(), email=f"revoke_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.commit()

    key_record, raw_key = await service.create_key(
        db=db_session, user=user, name="To Revoke"
    )

    # Revoke
    revoked = await service.revoke_key(db_session, user, key_record.id)
    assert revoked.is_active is False
    assert revoked.revoked_at is not None

    # Authenticate revoked key
    with pytest.raises(RevokedVirtualKeyError):
        await service.authenticate_key(db_session, raw_key)


@pytest.mark.asyncio
async def test_virtual_key_expiration(db_session: AsyncSession) -> None:
    """Verify expired key raises ExpiredVirtualKeyError during authentication."""
    service = VirtualKeyService()
    user = User(id=uuid.uuid4(), email=f"exp_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.commit()

    # Created with past expiration
    past_time = datetime.now(UTC) - timedelta(hours=1)
    key_record, raw_key = await service.create_key(
        db=db_session, user=user, name="Expired Key", expires_at=past_time
    )

    with pytest.raises(ExpiredVirtualKeyError):
        await service.authenticate_key(db_session, raw_key)


@pytest.mark.asyncio
async def test_virtual_key_rotation(db_session: AsyncSession) -> None:
    """Verify key rotation generates new secret, invalidating the old secret immediately."""
    service = VirtualKeyService()
    user = User(id=uuid.uuid4(), email=f"rotate_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    await db_session.commit()

    key_record, old_raw_key = await service.create_key(
        db=db_session, user=user, name="Rotating Key"
    )
    old_id = key_record.id

    # Rotate
    rotated_record, new_raw_key = await service.rotate_key(
        db_session, user, key_record.id
    )

    assert rotated_record.id == old_id
    assert new_raw_key != old_raw_key

    # Old key rejected
    with pytest.raises(InvalidVirtualKeyError):
        await service.authenticate_key(db_session, old_raw_key)

    # New key succeeds
    auth_key, _ = await service.authenticate_key(db_session, new_raw_key)
    assert auth_key.id == old_id


@pytest.mark.asyncio
async def test_virtual_key_cross_user_isolation(db_session: AsyncSession) -> None:
    """Verify User B cannot access, list, revoke, or rotate User A's keys."""
    service = VirtualKeyService()
    user_a = User(id=uuid.uuid4(), email=f"user_a_{uuid.uuid4().hex[:8]}@example.com")
    user_b = User(id=uuid.uuid4(), email=f"user_b_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add_all([user_a, user_b])
    await db_session.commit()

    key_a, _ = await service.create_key(db=db_session, user=user_a, name="User A Key")

    # User B listing keys sees 0
    b_keys = await service.list_keys(db_session, user_b)
    assert len(b_keys) == 0

    # User B attempting get, revoke, rotate on key_a fails with VirtualKeyNotFoundError
    with pytest.raises(VirtualKeyNotFoundError):
        await service.get_key(db_session, user_b, key_a.id)

    with pytest.raises(VirtualKeyNotFoundError):
        await service.revoke_key(db_session, user_b, key_a.id)

    with pytest.raises(VirtualKeyNotFoundError):
        await service.rotate_key(db_session, user_b, key_a.id)
