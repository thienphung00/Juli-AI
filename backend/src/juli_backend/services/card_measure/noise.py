"""The one noise-band seam of Đo lường (F10 → F3).

F3 decides the noise band is the PERIOD band: how much the metric's total over a period of
the card's length normally varies, 80 % level, ±1 % minimum. Its shared function will be
``services/forecast/noise.py::period_band`` (built on the forecast-core branches, not in this
base).

TODO(F3): swap the body of :func:`period_band_pct` for S1's shared function, one line:
``band = period_band(daily, window_days)`` from ``services.forecast.noise`` (signature
``period_band(totals_by_window, window_days, coverage=0.8, min_pct=0.01) -> Band(p10, p90,
mean, band_pct, days)``: band = z80 × sd × √n around n × mean, n = the card length;
``band_pct`` in %, None with < 2 days or mean ≤ 0). The arguments here already match: the
metric's DAILY series over the history window (None for a missing day) and the card length.
"Không đổi" then equals F3's ``within_noise(...)`` for the measured effect.

Today: the D28.1 window-mean band (``optimize_product.volatility.window_band_pct``) of the
daily values the reader used before the change, already lifted to the ±1 % minimum. F10's
history window is as long as the run, so n = the card length and the two formulas agree
(z80 × sd × √n ÷ (n × mean) = z80 × sd ÷ (√n × mean)).
"""

from __future__ import annotations

from collections.abc import Iterable

from juli_backend.services.optimize_product.volatility import MIN_BAND_PCT, window_band_pct


def period_band_pct(daily: Iterable[float | None], window_days: int) -> float:
    """± % band of the metric's total over ``window_days`` (the card length) from its daily
    history (None = missing day); at least :data:`MIN_BAND_PCT`.

    ``window_days`` is unused until F3's ``period_band`` replaces the body (the history
    window is the card length today, see the module docstring)."""
    del window_days
    band = window_band_pct([float(v) for v in daily if v is not None])
    return MIN_BAND_PCT if band is None else band


__all__ = ["MIN_BAND_PCT", "period_band_pct"]
