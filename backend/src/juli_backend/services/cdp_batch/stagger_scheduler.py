"""Deterministic daily reconcile window assignment for CDP batch fleet (#615)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

MINUTES_PER_UTC_DAY = 1440


@dataclass(frozen=True, slots=True)
class ReconcileWindow:
    """One shop's UTC-day reconcile slot."""

    shop_id: str
    day: date
    minute_of_day: int


def window_minute_for_shop(shop_id: str) -> int:
    """Map ``shop_id`` to a stable minute-of-day in ``[0, 1439]``.

    Uses SHA-256 over UTF-8 bytes — not Python's randomized ``hash()``.
    """
    digest = hashlib.sha256(shop_id.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return value % MINUTES_PER_UTC_DAY


def assign_window(shop_id: str, day: date) -> ReconcileWindow:
    """Assign the reconcile window for ``shop_id`` on UTC calendar ``day``."""
    return ReconcileWindow(
        shop_id=shop_id,
        day=day,
        minute_of_day=window_minute_for_shop(shop_id),
    )


class StaggerScheduler:
    """Deterministic shop→window assignment for daily batch reconcile."""

    def assign_window(self, shop_id: str, day: date) -> ReconcileWindow:
        return assign_window(shop_id, day)
