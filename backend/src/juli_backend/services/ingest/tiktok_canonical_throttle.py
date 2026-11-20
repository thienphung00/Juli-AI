"""Per-shop 429 bookkeeping around one TikTok Partner call (P101 W2, B-3b).

The rate limiter (``integrations/tiktok/rate_limiter.py``, B-3) keeps a per-shop backoff:
``note_throttled(app_id, shop_id)`` after a TikTok ``RateLimitError`` (100005) starts or doubles
it, and ``acquire`` refuses that shop until it ends; ``note_success(app_id, shop_id)`` resets
the strike count. :func:`noted_call` is the one place a poll / order-cost / analytics call for a
shop reports its outcome: a ``RateLimitError`` is noted and re-raised unchanged (every caller
keeps its own handling of it), a call that returned is noted as a success. Any other error is
neither (it says nothing about the shop's quota).

A limiter without these methods (an older limiter or a test double) is left alone.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from juli_backend.integrations.tiktok import RateLimitError

_T = TypeVar("_T")


def note_throttled(rate_limiter: Any, app_id: str, shop_id: str) -> None:
    note = getattr(rate_limiter, "note_throttled", None)
    if callable(note):
        note(app_id, shop_id)


def note_success(rate_limiter: Any, app_id: str, shop_id: str) -> None:
    note = getattr(rate_limiter, "note_success", None)
    if callable(note):
        note(app_id, shop_id)


def noted_call(
    rate_limiter: Any, app_id: str, shop_id: str, fn: Callable[..., _T], *args: Any, **kwargs: Any
) -> _T:
    """``fn(*args, **kwargs)``, with the shop's 429 backoff noted (see the module docstring)."""
    try:
        result = fn(*args, **kwargs)
    except RateLimitError:
        note_throttled(rate_limiter, app_id, shop_id)
        raise
    note_success(rate_limiter, app_id, shop_id)
    return result


__all__ = ["note_success", "note_throttled", "noted_call"]
