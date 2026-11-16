"""The one noise-band seam of Đo lường (F10 -> F3): ``services/forecast/noise.period_band``.

F3: the noise band is the PERIOD band -- how much the metric's total over a period of the
card's length normally varies, 80 % level, +-1 % minimum. "Không đổi" equals F3's
``within_noise`` for the measured effect.
"""

from __future__ import annotations

from collections.abc import Iterable

from juli_backend.services.forecast.noise import MIN_PCT, period_band

#: The minimum band, in percent (F3: never below 1 %).
MIN_BAND_PCT = MIN_PCT * 100


def period_band_pct(daily: Iterable[float | None], window_days: int) -> float:
    """+- % band of the metric's total over ``window_days`` (the card length) from its daily
    history (None = missing day); at least :data:`MIN_BAND_PCT`."""
    band = period_band(list(daily), window_days).band_pct
    return MIN_BAND_PCT if band is None else max(band, MIN_BAND_PCT)


__all__ = ["MIN_BAND_PCT", "period_band_pct"]
