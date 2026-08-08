"""Decision emission/surfacing budget tunables (#716, B-4, ADR-038 §6).

Config, not hardcoded product law: every default below is overridable via an
environment variable so ops can retune the Demo active surfaced set without a
code change. Defaults mirror the ADR-038 §6 starting values named in the
issue: max 5 active, 7-day per-workflow cooldown after a terminal action,
soft weekly novelty cap of 3.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_MAX_ACTIVE_ENV_VAR = "CDP_DECISION_EMISSION_MAX_ACTIVE"
_COOLDOWN_DAYS_ENV_VAR = "CDP_DECISION_EMISSION_COOLDOWN_DAYS"
_WEEKLY_NOVELTY_CAP_ENV_VAR = "CDP_DECISION_EMISSION_WEEKLY_NOVELTY_CAP"

_DEFAULT_MAX_ACTIVE = 5
_DEFAULT_COOLDOWN_DAYS = 7
_DEFAULT_WEEKLY_NOVELTY_CAP = 3


@dataclass(frozen=True, slots=True)
class DecisionEmissionConfig:
    """Tunable defaults for ``services.action_cards.emission_budget``."""

    max_active: int
    cooldown_days: int
    weekly_novelty_cap: int


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def decision_emission_config() -> DecisionEmissionConfig:
    """Read the emission budget tunables from the environment.

    Defaults (ADR-038 §6): ``max_active=5``, ``cooldown_days=7``,
    ``weekly_novelty_cap=3``. Override via ``CDP_DECISION_EMISSION_MAX_ACTIVE``,
    ``CDP_DECISION_EMISSION_COOLDOWN_DAYS``, ``CDP_DECISION_EMISSION_WEEKLY_NOVELTY_CAP``.
    """
    return DecisionEmissionConfig(
        max_active=_int_env(_MAX_ACTIVE_ENV_VAR, _DEFAULT_MAX_ACTIVE),
        cooldown_days=_int_env(_COOLDOWN_DAYS_ENV_VAR, _DEFAULT_COOLDOWN_DAYS),
        weekly_novelty_cap=_int_env(_WEEKLY_NOVELTY_CAP_ENV_VAR, _DEFAULT_WEEKLY_NOVELTY_CAP),
    )
