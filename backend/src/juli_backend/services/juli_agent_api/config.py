"""The Juli tab's switches and limits, read from the environment on every call.

``JULI_AGENT_ENABLED`` follows the repo's fail-closed flag reading (``core/config/runtime.py``,
``is_production_write_enabled``): unset or anything unknown is OFF. Two ON forms:

- ``true`` / ``1`` / ``yes`` -- every shop;
- a comma list of shop UUIDs -- only those shops (the owner's "sample shop first" rollout). The
  ids live in the environment, never in source.

Limits per shop (owner, juli-tab grill): 30 asks per rolling hour, 200 per rolling day.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

ENABLED_ENV = "JULI_AGENT_ENABLED"
PER_HOUR_ENV = "JULI_AGENT_LIMIT_PER_HOUR"
PER_DAY_ENV = "JULI_AGENT_LIMIT_PER_DAY"

DEFAULT_PER_HOUR = 30
DEFAULT_PER_DAY = 200

_TRUTHY = frozenset({"true", "1", "yes"})


@dataclass(frozen=True)
class FlagState:
    """``on``: the tab exists at all. ``shops``: None = every shop, else only these."""

    on: bool
    shops: frozenset[uuid.UUID] | None = None

    def allows(self, shop_id: uuid.UUID) -> bool:
        return self.on and (self.shops is None or shop_id in self.shops)


def flag_state() -> FlagState:
    raw = os.environ.get(ENABLED_ENV, "").strip().lower()
    if raw in _TRUTHY:
        return FlagState(on=True)
    shops: set[uuid.UUID] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            shops.add(uuid.UUID(part))
        except ValueError:
            return FlagState(on=False)  # an unreadable value is OFF, never "every shop"
    return FlagState(on=bool(shops), shops=frozenset(shops) or None)


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def limit_per_hour() -> int:
    return _positive_int(PER_HOUR_ENV, DEFAULT_PER_HOUR)


def limit_per_day() -> int:
    return _positive_int(PER_DAY_ENV, DEFAULT_PER_DAY)


__all__ = [
    "DEFAULT_PER_DAY",
    "DEFAULT_PER_HOUR",
    "ENABLED_ENV",
    "FlagState",
    "flag_state",
    "limit_per_day",
    "limit_per_hour",
]
