"""Đo lường on both platforms (F10): ADR-077's reader behind a platform series seam.

The effect is Shopee's reader, :func:`shopee_recommendations.impact.read_effect`, unchanged:
before/after corrected by the K = 5 most pre-correlated untouched products (at least 3, mean
r ≥ 0.2), else plain before/after at the lowest tier (``thap``). What differs per platform is
only where the daily series come from: a :class:`SeriesSource` returns a
:class:`SeriesBundle` (treated series, untouched controls, days to drop, newest stored day)
and :func:`measure` does the rest. ``card_measure.tiktok_series`` is the TikTok source.

On top of the reading (pure, no I/O in this module but :func:`measure_card`):

- **Window** -- the run's days after ``t`` against the same number of days before.
- **Verdict** -- ``tang`` / ``khong_doi`` / ``giam`` (Tăng / Không đổi / Giảm); ``khong_doi``
  when the effect is inside the F3 noise band (:mod:`.noise`). On Δprofit when profit is known,
  else ΔGMV (TikTok: ΔGMV until its profit adapter exists, F9). No verdict for a suppressed
  reading.
- **Forecast check** -- Dự kiến (the card's P50) against Thực tế (the reading's incremental
  per day); ``forecast_hit`` when Thực tế lies inside the card's internal P10–P90 (never
  shown, F4).
- **Calibration gate** -- only a medium / high tier reading (``trung_binh`` / ``cao``) on
  fresh data feeds calibration (F6); the lowest tier is shown, never calibrates. Fresh: the
  newest stored day covers the window's end, or is within the platform's expected lag + 2
  days of today (F2 amendment).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.card_measure.noise import period_band_pct
from juli_backend.services.shopee_recommendations import impact

VERDICT_UP = "tang"
VERDICT_FLAT = "khong_doi"
VERDICT_DOWN = "giam"
VERDICT_VI: Mapping[str, str] = {
    VERDICT_UP: "Tăng",
    VERDICT_FLAT: "Không đổi",
    VERDICT_DOWN: "Giảm",
}
#: ADR-077 tiers that may calibrate (F10); ``thap`` and ``suppressed`` never do.
CALIBRATING_TIERS = frozenset({"cao", "trung_binh"})
#: F2 amendment: stale = newest data older than the expected lag + this many days.
STALE_GRACE_DAYS = 2
METHOD = "adr077_ratio_did"


@dataclass(frozen=True)
class SeriesBundle:
    """One card's daily series, as a platform loaded them."""

    treated: impact.Series
    controls: Mapping[str, impact.Series]
    #: Days dropped everywhere: other changes on the product, sale days, days not stored.
    excluded: frozenset[date] = frozenset()
    #: The newest day the platform has stored for the shop (freshness).
    newest_day: date | None = None


class SeriesSource(Protocol):
    """A platform's daily-series loader for the reader (the F10 platform seam)."""

    @property
    def platform(self) -> str: ...
    @property
    def expected_lag_days(self) -> int: ...

    async def load(
        self,
        session: AsyncSession,
        shop_id: uuid.UUID,
        subject_ids: Sequence[str],
        first: date,
        last: date,
        *,
        run_id: uuid.UUID | None = None,
    ) -> SeriesBundle: ...


@dataclass(frozen=True)
class Forecast:
    """The card's internal forecast of the measured metric, per day (F4: only P50 shown)."""

    p50: float | None = None
    p10: float | None = None
    p90: float | None = None


@dataclass(frozen=True)
class Measurement:
    platform: str
    metric: str  # "profit" | "gmv"
    run_days: int
    reading: impact.Reading
    band_pct: float | None
    verdict: str | None
    expected_per_day: float | None  # Dự kiến (P50)
    actual_per_day: float | None  # Thực tế (incremental per day)
    forecast_hit: bool | None  # Đúng dự báo (internal)
    fresh: bool
    calibrates: bool

    def to_json(self) -> dict[str, Any]:
        r = self.reading
        return {
            "method": METHOD,
            "platform": self.platform,
            "metric": self.metric,
            "run_days": self.run_days,
            "confidence": r.confidence,
            "reason": r.reason,
            "fallback": r.fallback,
            "controls": list(r.controls),
            "impact_pct": r.impact_pct,
            "band_pct": self.band_pct,
            "verdict": self.verdict,
            "verdict_vi": VERDICT_VI.get(self.verdict or ""),
            "expected_per_day": self.expected_per_day,
            "actual_per_day": self.actual_per_day,
            "forecast_hit": self.forecast_hit,
            "fresh": self.fresh,
            "calibrates": self.calibrates,
        }


def verdict_of(reading: impact.Reading, band_pct: float | None) -> str | None:
    """Tăng / Không đổi / Giảm; ``khong_doi`` inside the noise band; None when suppressed."""
    if reading.confidence == "suppressed" or reading.impact_pct is None:
        return None
    effect_pct = reading.impact_pct * 100
    band = band_pct if band_pct is not None else 0.0
    if abs(effect_pct) <= band:
        return VERDICT_FLAT
    return VERDICT_UP if effect_pct > 0 else VERDICT_DOWN


def forecast_hit(actual: float | None, forecast: Forecast | None) -> bool | None:
    """Đúng dự báo: Thực tế inside the internal P10–P90; None without both bounds."""
    if actual is None or forecast is None or forecast.p10 is None or forecast.p90 is None:
        return None
    lo, hi = sorted((forecast.p10, forecast.p90))
    return lo <= actual <= hi


def is_fresh(
    newest_day: date | None, today: date, window_end: date, expected_lag_days: int
) -> bool:
    """The data the reading used was fresh (F2): it covers the window's end, or it is no
    older than the expected lag + :data:`STALE_GRACE_DAYS`."""
    if newest_day is None:
        return False
    limit = today - timedelta(days=expected_lag_days + STALE_GRACE_DAYS)
    return newest_day >= min(limit, window_end)


def measure(
    bundle: SeriesBundle,
    t: date,
    run_days: int,
    *,
    today: date,
    expected_lag_days: int,
    platform: str,
    metric: str,
    forecast: Forecast | None = None,
    volume_floor_per_day: float = 0.0,
) -> Measurement:
    """The F10 Đo lường of one card that changed on day ``t`` and ran ``run_days`` days."""
    reading = impact.read_effect(
        bundle.treated,
        bundle.controls,
        t,
        post_days=run_days,
        pre_days=run_days,
        excluded=bundle.excluded,
        volume_floor_per_day=volume_floor_per_day,
    )
    # The F3 history: the daily series before the change, None for a dropped day.
    history: list[float | None] = [
        None if day in bundle.excluded else bundle.treated.get(day, 0.0)
        for day in (t - timedelta(days=i) for i in range(run_days, 0, -1))
    ]
    known = sum(v is not None for v in history)
    band = period_band_pct(history, run_days) if known > 1 else None
    fresh = is_fresh(bundle.newest_day, today, t + timedelta(days=run_days), expected_lag_days)
    actual = reading.incremental
    return Measurement(
        platform=platform,
        metric=metric,
        run_days=run_days,
        reading=reading,
        band_pct=band,
        verdict=verdict_of(reading, band),
        expected_per_day=forecast.p50 if forecast is not None else None,
        actual_per_day=actual,
        forecast_hit=forecast_hit(actual, forecast),
        fresh=fresh,
        calibrates=fresh and reading.confidence in CALIBRATING_TIERS,
    )


async def measure_card(
    session: AsyncSession,
    source: SeriesSource,
    shop_id: uuid.UUID,
    subject_ids: Sequence[str],
    t: date,
    run_days: int,
    *,
    today: date,
    metric: str,
    forecast: Forecast | None = None,
    run_id: uuid.UUID | None = None,
) -> Measurement:
    """Load the card's series from ``source`` over the two windows, then :func:`measure`."""
    first, last = t - timedelta(days=run_days), t + timedelta(days=run_days)
    bundle = await source.load(session, shop_id, subject_ids, first, last, run_id=run_id)
    return measure(
        bundle,
        t,
        run_days,
        today=today,
        expected_lag_days=source.expected_lag_days,
        platform=source.platform,
        metric=metric,
        forecast=forecast,
    )


__all__ = [
    "CALIBRATING_TIERS",
    "METHOD",
    "STALE_GRACE_DAYS",
    "VERDICT_DOWN",
    "VERDICT_FLAT",
    "VERDICT_UP",
    "VERDICT_VI",
    "Forecast",
    "Measurement",
    "SeriesBundle",
    "SeriesSource",
    "forecast_hit",
    "is_fresh",
    "measure",
    "measure_card",
    "verdict_of",
]
