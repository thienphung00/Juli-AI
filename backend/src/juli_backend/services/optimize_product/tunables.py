"""Per-shop tunables of the volatility-aware diagnosis and KPI (D29.11). Pure.

Juli Ops Admins tune every level per shop before the seller uses the app
(D29.11, 17.5A): the adaptive windows, the data minimum, the KPI range
multipliers, the guard-band multiplier and the CV above which a product is
volatile. The values live in one team-set ``shop_rules`` row
(``services.shop_rules.diag_tunables``) and are edited through the Ops settings
route (``services.ops.settings``); this module only holds the shape, the
defaults and the validation, so the pure diagnosis can read it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: Setting keys, as Ops and the API name them.
DIAG_WINDOWS = "diag_windows"
DIAG_MIN_EVENTS = "diag_min_events"
KPI_MIN_BAND_MULT = "kpi_min_band_mult"
KPI_MAX_BAND_MULT = "kpi_max_band_mult"
GUARD_BAND_MULT = "guard_band_mult"
VOLATILE_CV = "volatile_cv"
#: D33 (P28): the per-shop "many cards" quota mode -- opt-in, off by default.
CARD_QUOTA_MODE = "card_quota_mode"
CARD_QUOTA_PER_CELL = "card_quota_per_cell"
CARD_QUOTA_MAX_OPEN = "card_quota_max_open"

#: The D33 quota keys (stored in the same team row as the D29 tunables).
QUOTA_KEYS: tuple[str, ...] = (CARD_QUOTA_MODE, CARD_QUOTA_PER_CELL, CARD_QUOTA_MAX_OPEN)
#: D39.1 (N1A): what opens a card -- any funnel metric falling beyond its own band
#: (``metric_first``, the default since P30) or the product's GMV (``gmv_first``,
#: D29.2, kept per shop for rollback).
DIAG_TRIGGER = "diag_trigger"
TRIGGER_METRIC_FIRST = "metric_first"
TRIGGER_GMV_FIRST = "gmv_first"
DIAG_TRIGGERS: tuple[str, ...] = (TRIGGER_METRIC_FIRST, TRIGGER_GMV_FIRST)
#: D34 / D39.3 (P30): group A/B with a randomised delayed control. Unset (``None``)
#: follows ``card_quota_mode`` -- on only when the quota mode is on.
CARD_GROUPS = "card_groups"

TUNABLE_KEYS: tuple[str, ...] = (
    DIAG_WINDOWS,
    DIAG_MIN_EVENTS,
    KPI_MIN_BAND_MULT,
    KPI_MAX_BAND_MULT,
    GUARD_BAND_MULT,
    VOLATILE_CV,
    *QUOTA_KEYS,
    DIAG_TRIGGER,
    CARD_GROUPS,
)

#: Bounds an Admin may set (inclusive).
WINDOW_RANGE = (7, 90)
MIN_EVENTS_RANGE = (5, 1000)
BAND_MULT_RANGE = (0.5, 10.0)
CV_RANGE = (0.05, 2.0)
#: D33: open cards per cell (target metric × channel) and the overall open cap.
QUOTA_PER_CELL_RANGE = (1, 20)
QUOTA_MAX_OPEN_RANGE = (5, 100)


class TunableError(ValueError):
    """An invalid tunable value."""


@dataclass(frozen=True)
class DiagTunables:
    """D29 defaults: windows 14/30/60, 30 events, KPI 1–3 bands, guard 1 band, CV 0.30.

    D33 (P28): ``card_quota_mode`` (off by default) switches the shop from the
    D24.21 daily slots to ``card_quota_per_cell`` (5) open cards per cell --
    target metric × KPI channel, content kinds their own cells -- under an
    overall open cap of ``card_quota_max_open`` (40); in that mode the nightly
    planner also proposes price levers from stored facts, adds the "below shop
    level" branch (S28B) and drops the Quality-Score lever weight.

    D39.1 (P30): ``diag_trigger`` -- ``metric_first`` (default) opens a card when
    any funnel metric falls beyond its own band on its channel, even when GMV
    holds; ``gmv_first`` keeps the D29.2 GMV gate (per-shop rollback).
    """

    windows: tuple[int, ...] = (14, 30, 60)
    min_events: int = 30
    kpi_min_band_mult: float = 1.0
    kpi_max_band_mult: float = 3.0
    guard_band_mult: float = 1.0
    volatile_cv: float = 0.30
    card_quota_mode: bool = False
    card_quota_per_cell: int = 5
    card_quota_max_open: int = 40
    #: D39.1: ``metric_first`` (default) or ``gmv_first`` (the D29.2 gate, rollback).
    diag_trigger: str = TRIGGER_METRIC_FIRST
    #: D34 / D39.3: ``None`` = follow ``card_quota_mode``; ``True`` / ``False`` = set.
    card_groups: bool | None = None

    @property
    def metric_first(self) -> bool:
        return self.diag_trigger == TRIGGER_METRIC_FIRST

    @property
    def groups_enabled(self) -> bool:
        """Group A/B on: the explicit switch, else the D33 quota mode."""
        return self.card_quota_mode if self.card_groups is None else self.card_groups

    def to_json(self) -> dict[str, Any]:
        return {
            DIAG_WINDOWS: list(self.windows),
            DIAG_MIN_EVENTS: self.min_events,
            KPI_MIN_BAND_MULT: self.kpi_min_band_mult,
            KPI_MAX_BAND_MULT: self.kpi_max_band_mult,
            GUARD_BAND_MULT: self.guard_band_mult,
            VOLATILE_CV: self.volatile_cv,
            CARD_QUOTA_MODE: self.card_quota_mode,
            CARD_QUOTA_PER_CELL: self.card_quota_per_cell,
            CARD_QUOTA_MAX_OPEN: self.card_quota_max_open,
            DIAG_TRIGGER: self.diag_trigger,
            CARD_GROUPS: self.card_groups,
        }

    @classmethod
    def from_overrides(cls, overrides: Mapping[str, Any] | None) -> DiagTunables:
        """Defaults with every valid override applied; an invalid stored value is ignored."""
        base = cls()
        if not overrides:
            return base
        values = base.to_json()
        for key in TUNABLE_KEYS:
            if overrides.get(key) is None:
                continue
            try:
                values[key] = validate_tunable(key, overrides[key])
            except TunableError:
                continue
        if values[KPI_MAX_BAND_MULT] < values[KPI_MIN_BAND_MULT]:
            values[KPI_MAX_BAND_MULT] = values[KPI_MIN_BAND_MULT]
        return cls(
            windows=tuple(values[DIAG_WINDOWS]),
            min_events=int(values[DIAG_MIN_EVENTS]),
            kpi_min_band_mult=float(values[KPI_MIN_BAND_MULT]),
            kpi_max_band_mult=float(values[KPI_MAX_BAND_MULT]),
            guard_band_mult=float(values[GUARD_BAND_MULT]),
            volatile_cv=float(values[VOLATILE_CV]),
            card_quota_mode=bool(values[CARD_QUOTA_MODE]),
            card_quota_per_cell=int(values[CARD_QUOTA_PER_CELL]),
            card_quota_max_open=int(values[CARD_QUOTA_MAX_OPEN]),
            diag_trigger=str(values[DIAG_TRIGGER]),
            card_groups=None if values[CARD_GROUPS] is None else bool(values[CARD_GROUPS]),
        )


def _number(name: str, value: Any, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TunableError(f"{name} must be a number")
    if not low <= float(value) <= high:
        raise TunableError(f"{name} must be between {low:g} and {high:g}")
    return float(value)


def _whole(name: str, value: Any, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TunableError(f"{name} must be a whole number")
    if not low <= value <= high:
        raise TunableError(f"{name} must be between {low} and {high}")
    return value


def validate_tunable(name: str, value: Any) -> Any:
    """The clean value for one key, or :class:`TunableError`."""
    if name in (CARD_QUOTA_MODE, CARD_GROUPS):
        if not isinstance(value, bool):
            raise TunableError(f"{name} must be true or false")
        return value
    if name == DIAG_TRIGGER:
        if value not in DIAG_TRIGGERS:
            raise TunableError(f"{name} must be one of {', '.join(DIAG_TRIGGERS)}")
        return value
    if name == CARD_QUOTA_PER_CELL:
        return _whole(name, value, *QUOTA_PER_CELL_RANGE)
    if name == CARD_QUOTA_MAX_OPEN:
        return _whole(name, value, *QUOTA_MAX_OPEN_RANGE)
    if name == DIAG_WINDOWS:
        if not isinstance(value, list | tuple) or not value or len(value) > 5:
            raise TunableError(f"{name} must be a list of 1 to 5 day counts")
        days: list[int] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int):
                raise TunableError(f"{name} must hold whole numbers of days")
            low, high = WINDOW_RANGE
            if not low <= item <= high:
                raise TunableError(f"{name}: each window must be {low}–{high} days")
            days.append(item)
        return sorted(set(days))
    if name == DIAG_MIN_EVENTS:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TunableError(f"{name} must be a whole number")
        low_e, high_e = MIN_EVENTS_RANGE
        if not low_e <= value <= high_e:
            raise TunableError(f"{name} must be between {low_e} and {high_e}")
        return value
    if name in (KPI_MIN_BAND_MULT, KPI_MAX_BAND_MULT, GUARD_BAND_MULT):
        return _number(name, value, *BAND_MULT_RANGE)
    if name == VOLATILE_CV:
        return _number(name, value, *CV_RANGE)
    raise TunableError(f"unknown tunable {name!r}")


__all__ = [
    "CARD_GROUPS",
    "CARD_QUOTA_MAX_OPEN",
    "CARD_QUOTA_MODE",
    "CARD_QUOTA_PER_CELL",
    "DIAG_MIN_EVENTS",
    "DIAG_TRIGGER",
    "DIAG_TRIGGERS",
    "DIAG_WINDOWS",
    "GUARD_BAND_MULT",
    "KPI_MAX_BAND_MULT",
    "KPI_MIN_BAND_MULT",
    "QUOTA_KEYS",
    "TRIGGER_GMV_FIRST",
    "TRIGGER_METRIC_FIRST",
    "TUNABLE_KEYS",
    "VOLATILE_CV",
    "DiagTunables",
    "TunableError",
    "validate_tunable",
]
