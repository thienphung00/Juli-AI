"""Bounded job correlation tokens for Shared Compute (#627)."""

from __future__ import annotations

import hashlib
import uuid


def job_correlation_token(shop_id: uuid.UUID, idempotency_key: str) -> str:
    """Stable 16-char token for logs and bronze source_event_id (no raw idempotency_key)."""
    digest = hashlib.sha256(f"{shop_id}:{idempotency_key}".encode()).hexdigest()
    return digest[:16]
