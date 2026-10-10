"""Decision emission/surfacing budget tunables (#716, B-4, ADR-038 §6; fasttrack D24.17).

Config, not hardcoded product law: every default below is overridable via an
environment variable so ops can retune the surfaced set without a code change.

Defaults are the owner's D24.17 card limits (2026-10-10, trial phase), one
limit for every shop:

- at most ``daily_new_cap`` (5) cards surfaced for the first time per shop day,
  ``weekly_new_cap`` (25) per shop week, and ``max_open`` (30) open at once;
- a surfaced card is valid ``validity_days`` (7) and then expires;
- once surfaced it stays at least ``min_stay_days`` (3), withdrawn earlier only
  when it is no longer valid;
- after a terminal action (or expiry) the same action on the same subject may
  return after ``cooldown_days`` (7);
- the first day a shop is ever shown cards is mixed by who carries the action
  out (``first_day_mix``: ~3 Juli, 1 Seller Center, 1 content).

These replace the #716 "max 5 active / weekly novelty 3" defaults and the
Optimize Product per-workflow cap of 5. See
``services.action_cards.emission_budget.apply_emission_budget`` for the gate
order this config feeds.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_DAILY_NEW_CAP_ENV_VAR = "CDP_DECISION_EMISSION_DAILY_NEW_CAP"
_WEEKLY_NEW_CAP_ENV_VAR = "CDP_DECISION_EMISSION_WEEKLY_NEW_CAP"
_MAX_OPEN_ENV_VAR = "CDP_DECISION_EMISSION_MAX_OPEN"
_COOLDOWN_DAYS_ENV_VAR = "CDP_DECISION_EMISSION_COOLDOWN_DAYS"
_VALIDITY_DAYS_ENV_VAR = "CDP_DECISION_EMISSION_VALIDITY_DAYS"
_MIN_STAY_DAYS_ENV_VAR = "CDP_DECISION_EMISSION_MIN_STAY_DAYS"
_FIRST_DAY_MIX_ENV_VAR = "CDP_DECISION_EMISSION_FIRST_DAY_MIX"

_DEFAULT_DAILY_NEW_CAP = 5
_DEFAULT_WEEKLY_NEW_CAP = 25
_DEFAULT_MAX_OPEN = 30
_DEFAULT_COOLDOWN_DAYS = 7
_DEFAULT_VALIDITY_DAYS = 7
_DEFAULT_MIN_STAY_DAYS = 3

#: Executor slots of a shop's first surfaced day, in fill order (D24.17):
#: ``juli`` covers ``juli`` and ``juli_with_photo`` cards, ``seller_center`` the
#: promotion levers, ``content`` the video / LIVE cards. A slot with no card is
#: filled by the next best card of any type.
EXECUTOR_JULI = "juli"
EXECUTOR_SELLER_CENTER = "seller_center"
EXECUTOR_CONTENT = "content"
_DEFAULT_FIRST_DAY_MIX: tuple[tuple[str, int], ...] = (
    (EXECUTOR_JULI, 3),
    (EXECUTOR_SELLER_CENTER, 1),
    (EXECUTOR_CONTENT, 1),
)


@dataclass(frozen=True, slots=True)
class DecisionEmissionConfig:
    """Tunable defaults for ``services.action_cards.emission_budget``."""

    daily_new_cap: int = _DEFAULT_DAILY_NEW_CAP
    weekly_new_cap: int = _DEFAULT_WEEKLY_NEW_CAP
    max_open: int = _DEFAULT_MAX_OPEN
    cooldown_days: int = _DEFAULT_COOLDOWN_DAYS
    validity_days: int = _DEFAULT_VALIDITY_DAYS
    min_stay_days: int = _DEFAULT_MIN_STAY_DAYS
    first_day_mix: tuple[tuple[str, int], ...] = _DEFAULT_FIRST_DAY_MIX


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _pairs_env(name: str, default: tuple[tuple[str, int], ...]) -> tuple[tuple[str, int], ...]:
    """``key=n,key=n``; an unparseable value keeps the default."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    pairs: list[tuple[str, int]] = []
    for part in raw.split(","):
        key, sep, value = part.partition("=")
        if not sep or not key.strip():
            return default
        try:
            pairs.append((key.strip(), int(value)))
        except ValueError:
            return default
    return tuple(pairs)


def decision_emission_config() -> DecisionEmissionConfig:
    """Read the emission budget tunables from the environment.

    Defaults (D24.17): 5 new/day, 25 new/week, 30 open, 7-day cooldown, 7-day
    validity, 3-day minimum stay, first day 3 Juli + 1 Seller Center + 1 content.
    Override via ``CDP_DECISION_EMISSION_DAILY_NEW_CAP``, ``…_WEEKLY_NEW_CAP``,
    ``…_MAX_OPEN``, ``…_COOLDOWN_DAYS``, ``…_VALIDITY_DAYS``, ``…_MIN_STAY_DAYS``
    and ``…_FIRST_DAY_MIX`` (``juli=3,seller_center=1,content=1``).
    """
    return DecisionEmissionConfig(
        daily_new_cap=_int_env(_DAILY_NEW_CAP_ENV_VAR, _DEFAULT_DAILY_NEW_CAP),
        weekly_new_cap=_int_env(_WEEKLY_NEW_CAP_ENV_VAR, _DEFAULT_WEEKLY_NEW_CAP),
        max_open=_int_env(_MAX_OPEN_ENV_VAR, _DEFAULT_MAX_OPEN),
        cooldown_days=_int_env(_COOLDOWN_DAYS_ENV_VAR, _DEFAULT_COOLDOWN_DAYS),
        validity_days=_int_env(_VALIDITY_DAYS_ENV_VAR, _DEFAULT_VALIDITY_DAYS),
        min_stay_days=_int_env(_MIN_STAY_DAYS_ENV_VAR, _DEFAULT_MIN_STAY_DAYS),
        first_day_mix=_pairs_env(_FIRST_DAY_MIX_ENV_VAR, _DEFAULT_FIRST_DAY_MIX),
    )
