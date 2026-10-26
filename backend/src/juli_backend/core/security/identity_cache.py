"""A short-lived, bounded, per-process cache of IDENTITY facts (fast track P69).

Production pays ~197 ms per database round trip (VPS -> Supabase via Supavisor,
measured 2026-10-26), and a partner reviewer's request used to spend most of its
latency re-reading facts that change at most a few times a month: its reviewer
account, its ``users`` row, the pinned shop's row and sandbox classification.
This module is the one cache shape those facts share.

What it is for, and what it never holds:

- identity facts only, each keyed by the VERIFIED subject it describes (a JWT
  ``sub``, or the configured pin's shop id) -- never a response, never seller data,
  never a token;
- never a decision that bypasses the database: tenant scope (``SET LOCAL`` of the
  shop / user GUCs) is still applied on every request, so RLS narrows every query;
- writes are never cached: the once-per-session sign-in claim, audits and every
  route write go to the database exactly as before.

TTL (P69 decision, owner brief 2026-10-26): :func:`reviewer_identity_ttl_seconds`,
30 s by default, ``REVIEWER_ACCOUNT_CACHE_SECONDS`` to override (0 disables every
reviewer identity cache -- the unit tests that flip state between requests use
that). A revoked reviewer is refused on every API worker within that window; an
expiry is checked against the clock on every request, so it is exact. Bounded
(:data:`DEFAULT_MAX_ENTRIES`, least-recently-stored evicted first) so a flood of
distinct subjects cannot grow the process.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Generic, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")

#: The default TTL of every reviewer identity cache (P69; was 15 s for the account).
DEFAULT_REVIEWER_IDENTITY_TTL_SECONDS = 30.0
#: Entries kept per cache; there are a handful of reviewer accounts and one pin.
DEFAULT_MAX_ENTRIES = 256


def reviewer_identity_ttl_seconds() -> float:
    """``REVIEWER_ACCOUNT_CACHE_SECONDS`` (>= 0), else 30 s; read on every lookup."""
    raw = os.getenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "").strip()
    if not raw:
        return DEFAULT_REVIEWER_IDENTITY_TTL_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_REVIEWER_IDENTITY_TTL_SECONDS


class IdentityCache(Generic[K, V]):
    """Thread-safe TTL + size-bounded map. A value is served only while younger than the TTL."""

    def __init__(
        self,
        *,
        ttl_seconds: Callable[[], float] = reviewer_identity_ttl_seconds,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max(1, max_entries)
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def get(self, key: K) -> V | None:
        ttl = self._ttl()
        with self._lock:
            hit = self._entries.get(key)
            if hit is None:
                return None
            stored_at, value = hit
            if ttl <= 0 or self._clock() - stored_at > ttl:
                del self._entries[key]
                return None
            return value

    def put(self, key: K, value: V) -> None:
        if self._ttl() <= 0:
            return
        with self._lock:
            self._entries.pop(key, None)
            self._entries[key] = (self._clock(), value)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def pop(self, key: K) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_REVIEWER_IDENTITY_TTL_SECONDS",
    "IdentityCache",
    "reviewer_identity_ttl_seconds",
]
