"""A group's design numbers for Ops: the weekly-drift floor and the traffic needed (D45.4). Pure.

Fast track P36 (D45.4, G4B; source: ``juli-sim-pilot`` funnel research run
``20261015-212942`` §3d). A product's metric drifts from week to week with nothing
changed (Fujiwa CTR: σ ≈ 0.15 per week on the log scale, D41). A D34 group reads
each product's 14 days after launch against its own 14 days before, so that drift
does not shrink with more impressions -- it puts a **floor** under the 90 %
interval's half-width however much traffic the group gets::

    floor (whole group, before vs after)   = z · √(2 σ² / (weeks · n))           n = n_t + n_c
    floor (treated − control)              = z · √(2 σ² / weeks · (1/n_t + 1/n_c))

with ``z`` = 1.645 (90 %, two-sided). The first is the research's number (6
products × 2 weeks ±10.1 %, 26 × 2 weeks ±4.8 %); the second is the same drift
read as the difference the verdict reports (4 + 2 × 2 weeks ±21.4 %), always wider.

**Traffic needed** per arm for a ±``hw`` (10 %) half-width, as the research's
``impressions_needed``: ``req = 2 z² / hw²`` without drift, ``2 z² / (hw² − floor²)``
with the whole-group floor (unreachable when the floor alone is ≥ ``hw``); times the
metric's variance per unit of traffic:

- CTR: impressions = req · (1 − ctr) / ctr;
- CTOR: clicks = req · (1 − ctor) / ctor, shown as impressions (÷ ctr);
- AOV: orders = req · CV², CV of one order's value = :data:`ORDER_VALUE_CV` (0.6,
  the research's assumption -- daily totals do not give per-order values);
- items per order / impressions: no formula (``None``).

Shown in Ops next to each other, with no label and no gate (D45.4).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: z of a two-sided 90 % interval.
Z90 = 1.6448536269514722
#: D41 / D45.4: Fujiwa's week-to-week drift of a product's log CTR with nothing changed.
DRIFT_SIGMA_WEEK = 0.15
#: The half-width the traffic is sized for (±10 %).
TARGET_HALF_WIDTH = 0.10
#: CV of one order's value (the research's assumption for AOV).
ORDER_VALUE_CV = 0.6

UNIT_IMPRESSIONS = "impressions"
UNIT_ORDERS = "orders"


@dataclass(frozen=True)
class DriftFloor:
    """The 90 % half-width floor from weekly drift (fractions, e.g. 0.101 = ±10.1 %)."""

    pooled: float
    difference: float | None

    def to_json(self) -> dict[str, Any]:
        return {
            "pooled_pct": round(self.pooled * 100, 1),
            "difference_pct": None if self.difference is None else round(self.difference * 100, 1),
        }


def drift_floor(
    n_treated: int, n_control: int, weeks: float, sigma: float = DRIFT_SIGMA_WEEK
) -> DriftFloor | None:
    """The floor for a group of ``n_treated`` + ``n_control`` products read over ``weeks``."""
    n = n_treated + n_control
    if n <= 0 or weeks <= 0 or sigma < 0:
        return None
    var_change = 2 * sigma**2 / weeks
    pooled = Z90 * math.sqrt(var_change / n)
    difference = (
        Z90 * math.sqrt(var_change * (1 / n_treated + 1 / n_control))
        if n_treated > 0 and n_control > 0
        else None
    )
    return DriftFloor(pooled, difference)


def _per_unit_variance(metric: str, totals: Mapping[str, float]) -> tuple[str, float] | None:
    """(traffic unit, variance factor per unit of that traffic) for ``metric``."""
    impressions = float(totals.get("impressions") or 0)
    clicks = float(totals.get("clicks") or 0)
    orders = float(totals.get("orders") or 0)
    if metric == "ctr":
        if impressions <= 0 or clicks <= 0 or clicks >= impressions:
            return None
        p = clicks / impressions
        return UNIT_IMPRESSIONS, (1 - p) / p
    if metric == "ctor":
        if impressions <= 0 or clicks <= 0 or orders <= 0 or orders >= clicks:
            return None
        c = orders / clicks
        return UNIT_IMPRESSIONS, (1 - c) / c / (clicks / impressions)
    if metric == "aov":
        return UNIT_ORDERS, ORDER_VALUE_CV**2
    return None


def traffic_needed(
    metric: str,
    totals: Mapping[str, float],
    *,
    floor: DriftFloor | None,
    half_width: float = TARGET_HALF_WIDTH,
) -> dict[str, Any] | None:
    """Traffic per arm for a ±``half_width`` interval (module docstring), else ``None``.

    ``totals``: the group's ``impressions`` / ``clicks`` / ``orders`` (any period; only
    the rates are used).
    """
    spec = _per_unit_variance(metric, totals)
    if spec is None or half_width <= 0:
        return None
    unit, factor = spec
    req0 = 2 * Z90**2 / half_width**2
    floor2 = (floor.pooled**2) if floor is not None else 0.0
    reachable = floor2 < half_width**2
    with_drift = 2 * Z90**2 / (half_width**2 - floor2) if reachable else None
    return {
        "unit": unit,
        "half_width_pct": round(half_width * 100, 1),
        "no_drift": math.ceil(req0 * factor),
        "with_drift": math.ceil(with_drift * factor) if with_drift is not None else None,
        "reachable": reachable,
    }


__all__ = [
    "DRIFT_SIGMA_WEEK",
    "ORDER_VALUE_CV",
    "TARGET_HALF_WIDTH",
    "UNIT_IMPRESSIONS",
    "UNIT_ORDERS",
    "Z90",
    "DriftFloor",
    "drift_floor",
    "traffic_needed",
]
