"""F3: the period noise band, shared by Shopee and TikTok. Pure: no DB, no platform imports.

Owner decision F3 (2026-11-16): the noise band of a metric is how much its TOTAL over a period of
the card's length (7 / 14 / 30 days) normally varies, read from the product's own daily history
in its F2 window, at the 80 % level, never below 1 %.

Method: with daily values of mean ``m`` and sample standard deviation ``s`` (days independent),
the total of ``n`` days has mean ``n x m`` and standard deviation ``s x sqrt(n)``, so the
two-sided ``coverage`` band is ``z x s x sqrt(n)`` around ``n x m``, i.e. ``z x s / (m x sqrt(n))``
of it. It is the same maths as ``ops.simulation.mean_band`` (the band of a window MEAN, which
TikTok keeps inside its KPI target until F10) with the period length ``n`` in place of the length
of the history, so a long history does not narrow the band of a 7-day card.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import NormalDist

#: F3: the band is never narrower than this share of the period total.
MIN_PCT = 0.01
COVERAGE = 0.8


@dataclass(frozen=True)
class Band:
    """The period band: ``p10`` / ``p90`` bound the period total, ``mean`` is its expected value;
    ``band_pct`` is the half width in percent of ``mean`` (None = not measurable: fewer than two
    days of history or a mean <= 0), ``days`` the days of history used."""

    p10: float
    p90: float
    mean: float
    band_pct: float | None
    days: int


def period_band(
    totals_by_window: Sequence[float | None],
    window_days: int,
    coverage: float = COVERAGE,
    min_pct: float = MIN_PCT,
) -> Band:
    """The ``coverage`` band of the metric's total over ``window_days`` days.

    ``totals_by_window`` is the metric's per-day total over the history window (one value per
    day; ``None`` = a missing day, skipped: F2 never counts a missing day as zero).
    """
    clean = [float(v) for v in totals_by_window if v is not None and math.isfinite(float(v))]
    n = max(1, int(window_days))
    if not clean:
        return Band(0.0, 0.0, 0.0, None, 0)
    mean_day = statistics.fmean(clean)
    mean = mean_day * n
    if len(clean) < 2 or mean_day <= 0:
        return Band(mean, mean, mean, None, len(clean))
    z = NormalDist().inv_cdf(0.5 + coverage / 2)
    half = z * statistics.stdev(clean) * math.sqrt(n)
    half = max(half, abs(mean) * min_pct)
    return Band(mean - half, mean + half, mean, half / mean * 100.0, len(clean))
