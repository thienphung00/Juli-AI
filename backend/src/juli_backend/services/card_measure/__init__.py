"""Đo lường on both platforms (forecast decision F10): ADR-077's reader
(``shopee_recommendations.impact``) behind a platform series seam.

:mod:`.reader` -- the platform-neutral measurement (window, verdict, forecast check,
calibration gate) and the :class:`~.reader.SeriesSource` protocol; :mod:`.tiktok_series` --
TikTok's source; :mod:`.noise` -- the one F3 noise-band seam.
"""

from __future__ import annotations

from juli_backend.services.card_measure.reader import (
    CALIBRATING_TIERS,
    VERDICT_DOWN,
    VERDICT_FLAT,
    VERDICT_UP,
    VERDICT_VI,
    Forecast,
    Measurement,
    SeriesBundle,
    SeriesSource,
    forecast_hit,
    is_fresh,
    measure,
    measure_card,
    verdict_of,
)

__all__ = [
    "CALIBRATING_TIERS",
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
