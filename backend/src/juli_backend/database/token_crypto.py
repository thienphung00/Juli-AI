"""Token encryption helpers for sensitive database credentials."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from functools import lru_cache

from cryptography.fernet import Fernet

ENCRYPTED_TOKEN_PREFIX = "enc:v1:"
#: A value sealed for one named purpose (``encrypt_for_purpose``), e.g. the
#: per-shop pseudonym keys (ADR-116 §4): ``enc:p1:<purpose>:<fernet token>``.
PURPOSE_PREFIX = "enc:p1:"


def encrypt_token(raw_token: str) -> str:
    """Encrypt a token for storage, leaving already-encrypted values unchanged."""
    if raw_token.startswith(ENCRYPTED_TOKEN_PREFIX):
        return raw_token

    encrypted = _fernet().encrypt(raw_token.encode()).decode()
    return f"{ENCRYPTED_TOKEN_PREFIX}{encrypted}"


def decrypt_token(stored_token: str) -> str:
    """Decrypt a stored token, accepting legacy plaintext values for reads."""
    if not stored_token.startswith(ENCRYPTED_TOKEN_PREFIX):
        return stored_token

    encrypted = stored_token.removeprefix(ENCRYPTED_TOKEN_PREFIX)
    return _fernet().decrypt(encrypted.encode()).decode()


def _encryption_secret() -> str:
    secret = os.environ.get("TIKTOK_TOKEN_ENCRYPTION_KEY")
    if not secret:
        raise RuntimeError("TIKTOK_TOKEN_ENCRYPTION_KEY must be configured")
    return secret


@lru_cache(maxsize=8)
def _fernet_for_secret(secret: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def _fernet() -> Fernet:
    return _fernet_for_secret(_encryption_secret())


def encrypt_for_purpose(raw: str, *, purpose: str) -> str:
    """Encrypt ``raw`` under a key derived for ``purpose`` only.

    Same secret as the token helpers (``TIKTOK_TOKEN_ENCRYPTION_KEY``), different
    key: ``HMAC-SHA256(secret, "juli:" + purpose)``. A ciphertext sealed for one
    purpose does not decrypt under another, nor under ``decrypt_token``.
    """
    token = _fernet_for_purpose(_encryption_secret(), purpose).encrypt(raw.encode()).decode()
    return f"{PURPOSE_PREFIX}{purpose}:{token}"


def decrypt_for_purpose(stored: str, *, purpose: str) -> str:
    """Inverse of :func:`encrypt_for_purpose`; refuses a value sealed for another purpose."""
    prefix = f"{PURPOSE_PREFIX}{purpose}:"
    if not stored.startswith(prefix):
        raise ValueError(f"value is not sealed for purpose {purpose!r}")
    token = stored.removeprefix(prefix)
    return _fernet_for_purpose(_encryption_secret(), purpose).decrypt(token.encode()).decode()


@lru_cache(maxsize=8)
def _fernet_for_purpose(secret: str, purpose: str) -> Fernet:
    digest = hmac.new(secret.encode(), f"juli:{purpose}".encode(), hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(digest))
