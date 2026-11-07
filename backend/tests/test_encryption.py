"""Tests for AES-256-GCM encryption, HMAC fingerprinting, and key masking."""

import base64
import secrets

import pytest

from app.core.encryption import (
    DecryptionFailedError,
    InvalidEncryptionKeyError,
    MissingEncryptionKeyError,
    decrypt_api_key,
    encrypt_api_key,
    generate_credential_fingerprint,
    mask_api_key,
    resolve_encryption_key,
)


@pytest.fixture
def sample_key() -> str:
    """Provide a dedicated 32-byte hexadecimal test key."""
    return secrets.token_hex(32)


def test_encryption_decryption_round_trip(sample_key: str) -> None:
    """Verify that encrypting and decrypting returns the exact original plaintext."""
    plaintext = "sk-ant-api03-test-secret-key-123456789"
    encrypted = encrypt_api_key(plaintext, key=sample_key)

    assert encrypted != plaintext
    assert plaintext not in encrypted

    decrypted = decrypt_api_key(encrypted, key=sample_key)
    assert decrypted == plaintext


def test_different_ciphertexts_for_identical_plaintexts_due_to_random_nonces(
    sample_key: str,
) -> None:
    """Verify that encrypting identical plaintexts produces distinct ciphertexts due to fresh nonces."""
    plaintext = "super-secret-provider-api-key"
    c1 = encrypt_api_key(plaintext, key=sample_key)
    c2 = encrypt_api_key(plaintext, key=sample_key)
    c3 = encrypt_api_key(plaintext, key=sample_key)

    assert c1 != c2
    assert c2 != c3
    assert c1 != c3

    # All should decrypt to the same plaintext
    assert decrypt_api_key(c1, key=sample_key) == plaintext
    assert decrypt_api_key(c2, key=sample_key) == plaintext
    assert decrypt_api_key(c3, key=sample_key) == plaintext


def test_tampered_ciphertext_rejected(sample_key: str) -> None:
    """Verify that tampering with any bit of the ciphertext or tag raises DecryptionFailedError."""
    plaintext = "sensitive-api-token-value"
    encrypted = encrypt_api_key(plaintext, key=sample_key)

    prefix, b64_part = encrypted.split(":", 1)
    raw_bytes = bytearray(base64.urlsafe_b64decode(b64_part))
    # Flip the last byte (part of authentication tag)
    raw_bytes[-1] ^= 0x01
    tampered = f"{prefix}:{base64.urlsafe_b64encode(raw_bytes).decode('utf-8')}"

    with pytest.raises(DecryptionFailedError, match="tampered with or key is invalid"):
        decrypt_api_key(tampered, key=sample_key)


def test_tampered_nonce_rejected(sample_key: str) -> None:
    """Verify that tampering with the nonce fails decryption authentication."""
    plaintext = "another-token"
    encrypted = encrypt_api_key(plaintext, key=sample_key)

    prefix, b64_part = encrypted.split(":", 1)
    raw_bytes = bytearray(base64.urlsafe_b64decode(b64_part))
    # Flip first byte (part of nonce)
    raw_bytes[0] ^= 0x01
    tampered = f"{prefix}:{base64.urlsafe_b64encode(raw_bytes).decode('utf-8')}"

    with pytest.raises(DecryptionFailedError):
        decrypt_api_key(tampered, key=sample_key)


def test_missing_encryption_key_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that missing encryption key causes immediate failure without unencrypted fallback."""
    from app.core import config

    # Mock settings with no key
    monkeypatch.setattr(config.settings, "CREDENTIAL_ENCRYPTION_KEY", None)

    with pytest.raises(MissingEncryptionKeyError):
        encrypt_api_key("some-key", key=None)

    with pytest.raises(MissingEncryptionKeyError):
        decrypt_api_key("some-ciphertext", key=None)


def test_invalid_encryption_key_length_rejected() -> None:
    """Verify that keys shorter or longer than 32 bytes are rejected."""
    short_key = "too-short-key"
    with pytest.raises(InvalidEncryptionKeyError):
        resolve_encryption_key(short_key)

    short_bytes = b"short_bytes"
    with pytest.raises(InvalidEncryptionKeyError):
        resolve_encryption_key(short_bytes)


def test_duplicate_credential_detection_via_keyed_hmac(sample_key: str) -> None:
    """Verify that credential fingerprints are deterministic for identical keys and different for distinct keys."""
    key_a = "sk-test-key-alpha"
    key_b = "sk-test-key-beta"

    fp_a1 = generate_credential_fingerprint(key_a, key=sample_key)
    fp_a2 = generate_credential_fingerprint(key_a, key=sample_key)
    fp_b = generate_credential_fingerprint(key_b, key=sample_key)

    assert fp_a1 == fp_a2
    assert fp_a1 != fp_b
    assert len(fp_a1) == 64  # SHA-256 hex string


def test_credential_fingerprint_keyed_isolation() -> None:
    """Verify that identical plaintexts produce different fingerprints with different vault keys."""
    key_1 = secrets.token_hex(32)
    key_2 = secrets.token_hex(32)
    secret = "shared-secret-value"

    fp1 = generate_credential_fingerprint(secret, key=key_1)
    fp2 = generate_credential_fingerprint(secret, key=key_2)

    assert fp1 != fp2


def test_key_masking_various_lengths() -> None:
    """Verify that key masking protects secret credentials while retaining identifiable prefix/suffix."""
    assert mask_api_key("") == ""
    assert mask_api_key("ab") == "***ab"
    assert mask_api_key("abcde") == "***de"
    assert mask_api_key("12345678") == "12...678"
    assert mask_api_key("sk-1234567890abcdef") == "sk-1...cdef"
    assert mask_api_key("gsk_ultra_long_provider_secret_9988") == "gsk_...9988"


def test_key_versioning_and_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify multi-key ring resolution, versioned envelopes, and rotation without access loss."""
    from app.core import config

    key_v1 = secrets.token_hex(32)
    key_v2 = secrets.token_hex(32)

    # Configure key ring with v1 and v2
    monkeypatch.setattr(config.settings, "CREDENTIAL_ENCRYPTION_KEY", key_v1)
    monkeypatch.setattr(
        config.settings,
        "CREDENTIAL_ENCRYPTION_KEY_RING",
        {1: key_v1, 2: key_v2},
    )
    monkeypatch.setattr(config.settings, "CREDENTIAL_ENCRYPTION_ACTIVE_VERSION", 1)

    plaintext = "sk-live-rotation-test-credential-secret"

    # 1. Encrypt with version 1
    enc_v1 = encrypt_api_key(plaintext, key_version=1)
    assert enc_v1.startswith("v1:")
    assert decrypt_api_key(enc_v1) == plaintext

    # 2. Switch active version to 2
    monkeypatch.setattr(config.settings, "CREDENTIAL_ENCRYPTION_ACTIVE_VERSION", 2)

    # Decrypting old v1 payload still works seamlessly using key ring
    assert decrypt_api_key(enc_v1) == plaintext

    # 3. Rotate / re-encrypt under version 2
    enc_v2 = encrypt_api_key(plaintext, key_version=2)
    assert enc_v2.startswith("v2:")
    assert enc_v2 != enc_v1
    assert decrypt_api_key(enc_v2) == plaintext

    # 4. Fingerprint remains stable across key rotation
    fp_v1 = generate_credential_fingerprint(plaintext)
    fp_v2 = generate_credential_fingerprint(plaintext)
    assert fp_v1 == fp_v2
