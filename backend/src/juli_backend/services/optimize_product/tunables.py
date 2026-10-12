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

TUNABLE_KEYS: tuple[str, ...] = (
    DIAG_WINDOWS,
    DIAG_MIN_EVENTS,
    KPI_MIN_BAND_MULT,
    KPI_MAX_BAND_MULT,
    GUARD_BAND_MULT,
    VOLATILE_CV,
)

#: Bounds an Admin may set (inclusive).
WINDOW_RANGE = (7, 90)
MIN_EVENTS_RANGE = (5, 1000)
BAND_MULT_RANGE = (0.5, 10.0)
CV_RANGE = (0.05, 2.0)


class TunableError(ValueError):
    """An invalid tunable value."""


@dataclass(frozen=True)
class DiagTunables:
    """D29 defaults: windows 14/30/60, 30 events, KPI 1–3 bands, guard 1 band, CV 0.30."""

    windows: tuple[int, ...] = (14, 30, 60)
    min_events: int = 30
    kpi_min_band_mult: float = 1.0
    kpi_max_band_mult: float = 3.0
    guard_band_mult: float = 1.0
    volatile_cv: float = 0.30

    def to_json(self) -> dict[str, Any]:
        return {
            DIAG_WINDOWS: list(self.windows),
            DIAG_MIN_EVENTS: self.min_events,
            KPI_MIN_BAND_MULT: self.kpi_min_band_mult,
            KPI_MAX_BAND_MULT: self.kpi_max_band_mult,
            GUARD_BAND_MULT: self.guard_band_mult,
            VOLATILE_CV: self.volatile_cv,
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
        )


def _number(name: str, value: Any, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TunableError(f"{name} must be a number")
    if not low <= float(value) <= high:
        raise TunableError(f"{name} must be between {low:g} and {high:g}")
    return float(value)


def validate_tunable(name: str, value: Any) -> Any:
    """The clean value for one key, or :class:`TunableError`."""
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
    "DIAG_MIN_EVENTS",
    "DIAG_WINDOWS",
    "GUARD_BAND_MULT",
    "KPI_MAX_BAND_MULT",
    "KPI_MIN_BAND_MULT",
    "TUNABLE_KEYS",
    "VOLATILE_CV",
    "DiagTunables",
    "TunableError",
    "validate_tunable",
]
