"""Decision emission/surfacing budget tunables (#716, B-4, ADR-038 §6).

Config, not hardcoded product law: every default below is overridable via an
environment variable so ops can retune the Demo active surfaced set without a
code change. Defaults mirror the ADR-038 §6 starting values named in the
issue: max 5 active, 7-day per-workflow cooldown after a terminal action,
soft weekly novelty cap of 3.

"Soft" (operator decision, #716 B-4 cycle 2): the weekly novelty cap is a
churn *target*, not a supply ceiling — ``max_active`` is the only hard
ceiling on surfacing. See
``services.action_cards.emission_budget.apply_emission_budget`` for the
fill-to-cap gate order this config feeds.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_MAX_ACTIVE_ENV_VAR = "CDP_DECISION_EMISSION_MAX_ACTIVE"
_COOLDOWN_DAYS_ENV_VAR = "CDP_DECISION_EMISSION_COOLDOWN_DAYS"
_WEEKLY_NOVELTY_CAP_ENV_VAR = "CDP_DECISION_EMISSION_WEEKLY_NOVELTY_CAP"
_WORKFLOW_MAX_ACTIVE_ENV_VAR = "CDP_DECISION_EMISSION_WORKFLOW_MAX_ACTIVE"

_DEFAULT_MAX_ACTIVE = 5
_DEFAULT_COOLDOWN_DAYS = 7
_DEFAULT_WEEKLY_NOVELTY_CAP = 3
#: Workflows that may surface several cards (one per subject) while taking a
#: single ``max_active`` slot. Optimize Product: up to 5 open product cards per
#: shop (ADR-106 decision 6; fasttrack DECISIONS "Defaults taken" raises the
#: one-card limit).
_DEFAULT_WORKFLOW_MAX_ACTIVE: tuple[tuple[str, int], ...] = (("optimize_product_2", 5),)


@dataclass(frozen=True, slots=True)
class DecisionEmissionConfig:
    """Tunable defaults for ``services.action_cards.emission_budget``."""

    max_active: int
    cooldown_days: int
    weekly_novelty_cap: int
    #: ``(workflow_key, cap)`` pairs. A listed workflow's cards share ONE of
    #: the ``max_active`` slots and surface up to ``cap`` of them; any other
    #: workflow takes one slot per card, as before.
    workflow_max_active: tuple[tuple[str, int], ...] = _DEFAULT_WORKFLOW_MAX_ACTIVE

    def cap_for(self, workflow_key: str) -> int | None:
        """The per-workflow surfacing cap, or ``None`` for a one-slot-per-card workflow."""
        for key, cap in self.workflow_max_active:
            if key == workflow_key:
                return cap
        return None


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _workflow_caps_env(
    name: str, default: tuple[tuple[str, int], ...]
) -> tuple[tuple[str, int], ...]:
    """``key=cap,key=cap``; an unparseable value keeps the default."""
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

    Defaults (ADR-038 §6): ``max_active=5``, ``cooldown_days=7``,
    ``weekly_novelty_cap=3``. Override via ``CDP_DECISION_EMISSION_MAX_ACTIVE``,
    ``CDP_DECISION_EMISSION_COOLDOWN_DAYS``, ``CDP_DECISION_EMISSION_WEEKLY_NOVELTY_CAP``.
    """
    return DecisionEmissionConfig(
        max_active=_int_env(_MAX_ACTIVE_ENV_VAR, _DEFAULT_MAX_ACTIVE),
        cooldown_days=_int_env(_COOLDOWN_DAYS_ENV_VAR, _DEFAULT_COOLDOWN_DAYS),
        weekly_novelty_cap=_int_env(_WEEKLY_NOVELTY_CAP_ENV_VAR, _DEFAULT_WEEKLY_NOVELTY_CAP),
        workflow_max_active=_workflow_caps_env(
            _WORKFLOW_MAX_ACTIVE_ENV_VAR, _DEFAULT_WORKFLOW_MAX_ACTIVE
        ),
    )
