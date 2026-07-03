"""Token encryption helpers for sensitive database credentials."""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.fernet import Fernet

ENCRYPTED_TOKEN_PREFIX = "enc:v1:"


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
    secret = (
        os.environ.get("TIKTOK_TOKEN_ENCRYPTION_KEY")
        or os.environ.get("TOKEN_ENCRYPTION_KEY")
        or os.environ.get("TIKTOK_APP_SECRET")
    )
    if not secret:
        raise RuntimeError("Token encryption key is not configured")
    return secret


@lru_cache(maxsize=8)
def _fernet_for_secret(secret: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def _fernet() -> Fernet:
    return _fernet_for_secret(_encryption_secret())
