"""The Juli tab's switches and limits, read from the environment on every call.

``JULI_AGENT_ENABLED`` follows the repo's fail-closed flag reading (``core/config/runtime.py``,
``is_production_write_enabled``): unset or anything unknown is OFF. Two ON forms:

- ``true`` / ``1`` / ``yes`` -- every shop;
- a comma list of shop UUIDs -- only those shops (the owner's "sample shop first" rollout). The
  ids live in the environment, never in source.

Limits per shop (owner, juli-tab grill): 30 asks per rolling hour, 200 per rolling day. Per
process: a run's time limit (120 s) and the runs in flight at once (20).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

ENABLED_ENV = "JULI_AGENT_ENABLED"
PER_HOUR_ENV = "JULI_AGENT_LIMIT_PER_HOUR"
PER_DAY_ENV = "JULI_AGENT_LIMIT_PER_DAY"

RUN_TIMEOUT_ENV = "JULI_AGENT_RUN_TIMEOUT_S"
MAX_RUNS_ENV = "JULI_AGENT_MAX_CONCURRENT_RUNS"

DEFAULT_PER_HOUR = 30
DEFAULT_PER_DAY = 200
#: one answer's whole run (parse, Jev, reads, writer); past it the answer ends ``error: busy``
DEFAULT_RUN_TIMEOUT_S = 120.0
#: runs in flight in ONE API process; past it a new ask answers 429 ``juli_busy_system``
DEFAULT_MAX_CONCURRENT_RUNS = 20

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


def run_timeout_s() -> float:
    try:
        value = float(os.environ.get(RUN_TIMEOUT_ENV, "").strip())
    except ValueError:
        return DEFAULT_RUN_TIMEOUT_S
    return value if value > 0 else DEFAULT_RUN_TIMEOUT_S


def max_concurrent_runs() -> int:
    return _positive_int(MAX_RUNS_ENV, DEFAULT_MAX_CONCURRENT_RUNS)


#: USD per million tokens (input, output). Haiku 5.5 and Sonnet 5.5 are the prototype's prices
#: (p1/agent2.py MODELS); an unknown model is priced like Haiku, never free.
LLM_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}
DEFAULT_LLM_USD_PER_MTOK = LLM_USD_PER_MTOK["claude-haiku-5-5"]
#: Jev (TypeSafe System One): USD per million input tokens, output is free
JEV_INPUT_USD_PER_MTOK = 0.042


def llm_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = LLM_USD_PER_MTOK.get(model, DEFAULT_LLM_USD_PER_MTOK)
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def jev_cost_usd(input_tokens: int) -> float:
    return input_tokens * JEV_INPUT_USD_PER_MTOK / 1_000_000


__all__ = [
    "DEFAULT_PER_DAY",
    "DEFAULT_PER_HOUR",
    "ENABLED_ENV",
    "JEV_INPUT_USD_PER_MTOK",
    "LLM_USD_PER_MTOK",
    "FlagState",
    "jev_cost_usd",
    "llm_cost_usd",
    "flag_state",
    "limit_per_day",
    "limit_per_hour",
    "max_concurrent_runs",
    "run_timeout_s",
]
