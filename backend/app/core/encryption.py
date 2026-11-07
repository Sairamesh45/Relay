"""Cryptographic vault utilities for versioned AES-256-GCM credential encryption and HMAC fingerprinting."""

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


class EncryptionError(Exception):
    """Base exception for cryptographic operations."""

    pass


class MissingEncryptionKeyError(EncryptionError):
    """Raised when an encryption key is unset or missing from the key ring."""

    pass


class InvalidEncryptionKeyError(EncryptionError):
    """Raised when an encryption key is not a valid 32-byte key."""

    pass


class DecryptionFailedError(EncryptionError):
    """Raised when ciphertext is corrupted, tampered with, or key is wrong."""

    pass


def resolve_encryption_key(key: bytes | str | None = None) -> bytes:
    """Resolve and validate a 32-byte AES-256 encryption key.

    Supports:
    - 64-character hexadecimal string
    - 32-byte standard/URL-safe base64 string
    - Raw 32 bytes or 32-character UTF-8 string
    Fails closed if the key is missing, empty, or wrong length.
    """
    if key is None:
        settings = get_settings()
        key = settings.CREDENTIAL_ENCRYPTION_KEY

    if not key:
        raise MissingEncryptionKeyError(
            "CREDENTIAL_ENCRYPTION_KEY is not configured. "
            "Set a 32-byte key in environment variables."
        )

    if isinstance(key, str):
        clean_key = key.strip()
        # 1. 64-character hex string (most common for 32-byte secrets)
        if len(clean_key) == 64:
            try:
                hex_bytes = bytes.fromhex(clean_key)
                if len(hex_bytes) == 32:
                    return hex_bytes
            except ValueError:
                pass

        # 2. Base64 encoded 32-byte string (typically 43-44 chars)
        if 42 <= len(clean_key) <= 46:
            for decoder in (base64.b64decode, base64.urlsafe_b64decode):
                try:
                    b64_bytes = decoder(clean_key)
                    if len(b64_bytes) == 32:
                        return b64_bytes
                except Exception:
                    pass

        # 3. Direct 32-byte UTF-8 string
        raw_bytes = clean_key.encode("utf-8")
        if len(raw_bytes) == 32:
            return raw_bytes

        raise InvalidEncryptionKeyError(
            f"Encryption key must resolve to exactly 32 bytes (got {len(raw_bytes)} bytes). "
            "Provide 64 hex characters or a 32-byte base64-encoded string."
        )

    if isinstance(key, (bytes, bytearray)):
        if len(key) != 32:
            raise InvalidEncryptionKeyError(
                f"Encryption key must be exactly 32 bytes (got {len(key)} bytes)."
            )
        return bytes(key)

    raise InvalidEncryptionKeyError("Encryption key must be a string or bytes.")


def resolve_key_ring() -> dict[int, bytes]:
    """Resolve all configured encryption keys indexed by version."""
    settings = get_settings()
    ring: dict[int, bytes] = {}

    # 1. Default primary key mapped as version 1
    if settings.CREDENTIAL_ENCRYPTION_KEY:
        try:
            ring[1] = resolve_encryption_key(settings.CREDENTIAL_ENCRYPTION_KEY)
        except Exception:
            pass

    # 2. Key ring entries if configured in settings
    if settings.CREDENTIAL_ENCRYPTION_KEY_RING:
        for ver, k_val in settings.CREDENTIAL_ENCRYPTION_KEY_RING.items():
            ring[int(ver)] = resolve_encryption_key(k_val)

    return ring


def resolve_encryption_key_for_version(
    version: int | None = None, key: bytes | str | None = None
) -> tuple[int, bytes]:
    """Resolve key bytes and version number for encryption or decryption."""
    if key is not None:
        return (version or 1, resolve_encryption_key(key))

    settings = get_settings()
    ring = resolve_key_ring()

    target_ver = (
        version
        if version is not None
        else settings.CREDENTIAL_ENCRYPTION_ACTIVE_VERSION
    )

    if target_ver in ring:
        return (target_ver, ring[target_ver])

    if target_ver == 1 and settings.CREDENTIAL_ENCRYPTION_KEY:
        return (1, resolve_encryption_key(settings.CREDENTIAL_ENCRYPTION_KEY))

    raise MissingEncryptionKeyError(
        f"Encryption key for version {target_ver} is not configured in the key ring."
    )


def extract_key_version(encrypted_payload: str) -> int:
    """Extract key version from self-describing payload format 'v<ver>:<data>'."""
    if encrypted_payload.startswith("v") and ":" in encrypted_payload[:8]:
        prefix, _ = encrypted_payload.split(":", 1)
        try:
            return int(prefix[1:])
        except ValueError:
            pass
    return 1


def encrypt_api_key(
    api_key: str,
    key_version: int | None = None,
    key: bytes | str | None = None,
) -> str:
    """Encrypt an API key using AES-256-GCM under the designated key version.

    Returns a self-describing string format: 'v<ver>:<base64_payload>'
    with fresh random 12-byte nonce for each encryption operation.
    """
    if not api_key:
        raise ValueError("Cannot encrypt an empty API key.")

    ver, key_bytes = resolve_encryption_key_for_version(key_version, key)
    aesgcm = AESGCM(key_bytes)
    nonce = os.urandom(12)

    ciphertext_and_tag = aesgcm.encrypt(nonce, api_key.encode("utf-8"), None)
    combined = nonce + ciphertext_and_tag
    b64_payload = base64.urlsafe_b64encode(combined).decode("utf-8")
    return f"v{ver}:{b64_payload}"


def decrypt_api_key(
    encrypted_payload: str,
    key_version: int | None = None,
    key: bytes | str | None = None,
) -> str:
    """Decrypt an AES-256-GCM encrypted payload, resolving key version from envelope.

    Supports:
    - Versioned envelopes: 'v<ver>:<base64>'
    - Legacy unversioned base64 payloads (defaults to version 1)
    """
    if not encrypted_payload:
        raise DecryptionFailedError("Ciphertext payload cannot be empty.")

    payload_to_decrypt = encrypted_payload
    ver = key_version

    if encrypted_payload.startswith("v") and ":" in encrypted_payload[:8]:
        prefix, remainder = encrypted_payload.split(":", 1)
        try:
            ver = int(prefix[1:])
            payload_to_decrypt = remainder
        except ValueError:
            pass

    if ver is None:
        ver = 1

    _, key_bytes = resolve_encryption_key_for_version(ver, key)

    try:
        combined = base64.urlsafe_b64decode(payload_to_decrypt.encode("utf-8"))
    except Exception as exc:
        raise DecryptionFailedError("Malformed base64 ciphertext payload.") from exc

    if len(combined) < 29:
        raise DecryptionFailedError("Ciphertext payload is truncated or invalid.")

    nonce = combined[:12]
    ciphertext_and_tag = combined[12:]
    aesgcm = AESGCM(key_bytes)

    try:
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext_and_tag, None)
        return decrypted_bytes.decode("utf-8")
    except InvalidTag as exc:
        raise DecryptionFailedError(
            f"Decryption authentication failed for key version {ver}: data was tampered with or key is invalid."
        ) from exc
    except UnicodeDecodeError as exc:
        raise DecryptionFailedError("Decrypted data is not valid UTF-8.") from exc


def generate_credential_fingerprint(
    api_key: str, key: bytes | str | None = None
) -> str:
    """Generate a deterministic keyed HMAC-SHA256 fingerprint for duplicate detection.

    Uses a stable key version (version 1) by default so rotating encryption keys does not
    alter the credential fingerprint or produce duplicate collisions.
    """
    if not api_key:
        raise ValueError("Cannot fingerprint an empty API key.")

    if key is not None:
        key_bytes = resolve_encryption_key(key)
    else:
        _, key_bytes = resolve_encryption_key_for_version(1)

    return hmac.new(
        key_bytes, api_key.strip().encode("utf-8"), hashlib.sha256
    ).hexdigest()


def mask_api_key(api_key: str) -> str:
    """Mask an API key for safe display in UI/API responses without leaking credentials."""
    if not api_key:
        return ""
    length = len(api_key)
    if length <= 6:
        return f"***{api_key[-2:]}" if length >= 2 else "***"
    if length <= 12:
        return f"{api_key[:2]}...{api_key[-3:]}"
    return f"{api_key[:4]}...{api_key[-4:]}"
