"""The card's forecast numbers on the TikTok engine (forecast grill 2026-11-16). Pure.

One block per card (``CardForecast``), additive to the payload:

* **F2 freshness.** TikTok's daily analytics lag by
  :data:`~.tunables.TIKTOK_ANALYTICS_EXPECTED_LAG_DAYS`; a card whose data-through day
  is older than that lag plus :data:`~.tunables.FORECAST_STALE_GRACE_DAYS` carries no
  numbers and a ``stale`` marker with the data-through day ("Đơn hàng đến dd/mm").
  Days after the data-through day are missing, never zero: every window ends on it.
* **F3 noise band.** Every use of the card's noise band goes through
  :func:`noise_band_for_card` (the one seam), fed the metric's daily series
  (:func:`daily_history`, ``None`` = missing). Today it is the window-mean band of
  :mod:`.volatility`; S1's shared period band replaces it. The KPI target keeps the
  window-mean band on its own.
* **F5 within noise.** A metric whose effect P90 is below its noise band gets no number
  (``None``, the screen shows "—"); the card itself is still proposed.
* **F8 one scenario.** Δorders and ΔGMV come from the same P50 lift on the card's
  target metric through the funnel identity GMV = orders × AOV: a traffic / rate lever
  (impressions, CTR, CTOR) moves orders at today's AOV; an AOV lever moves AOV at
  today's orders (Δorders 0). TikTok has no profit, so the middle scenario is ΔGMV's.
* **F9.** Δprofit is ``None`` until the TikTok profit adapter exists (no caption).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from juli_backend.services.optimize_product.daily_funnel import ProductDay
from juli_backend.services.optimize_product.prediction import DAYS_PER_MONTH, Prediction
from juli_backend.services.optimize_product.tunables import (
    FORECAST_STALE_GRACE_DAYS,
    TIKTOK_ANALYTICS_EXPECTED_LAG_DAYS,
)
from juli_backend.services.optimize_product.volatility import window_band_pct

#: The metric a GMV-linear lift acts on through AOV rather than through orders.
AOV_METRIC = "aov"
#: Forecast metrics with their own noise band (the target metric has one too).
METRIC_ORDERS = "orders"
METRIC_GMV = "gmv"


#: F3: the card's period length in days -- a TikTok card is judged at day 14 (Đo lường).
CARD_DAYS = 14
#: F5: kinds that follow their own rule, not the within-noise one. Every TikTok card
#: lever is an uplift lever today. TODO(F3): use S1's ``NON_UPLIFT_KINDS`` from
#: ``juli_backend.services.forecast.noise`` when it lands.
NON_UPLIFT_KINDS: frozenset[str] = frozenset()


def daily_history(
    rows: Sequence[ProductDay], *, as_of: date, metric: str, window_days: int
) -> list[float | None]:
    """The metric's DAILY series over the F2 window ending ``as_of``, oldest first.

    ``None`` for a day with no row, an out-of-stock / unlisted day (F2) or a ratio
    without its denominator -- the shape the shared period band reads.
    """
    by_day = {r.day: r for r in rows}
    out: list[float | None] = []
    for offset in range(window_days - 1, -1, -1):
        row = by_day.get(as_of - timedelta(days=offset))
        if row is None or row.available is False:
            out.append(None)
            continue
        impressions, clicks = float(row.impressions), float(row.clicks)
        orders, gmv = float(row.sku_orders), float(row.gmv)
        value: float | None
        if metric == METRIC_ORDERS:
            value = orders
        elif metric == METRIC_GMV:
            value = gmv
        elif metric == "impressions":
            value = impressions
        elif metric == "ctr":
            value = clicks / impressions if impressions > 0 else None
        elif metric == "ctor":
            value = orders / clicks if clicks > 0 else None
        elif metric == AOV_METRIC:
            value = gmv / orders if orders > 0 else None
        else:
            raise KeyError(metric)
        out.append(value)
    return out


def noise_band_for_card(
    totals_by_window: Sequence[float | None], window_days: int = CARD_DAYS
) -> float | None:
    """The card's noise band, in % of the metric's level (``None``: too little history).

    The ONE seam every card-band reader goes through. ``totals_by_window`` is the
    metric's daily series (:func:`daily_history`), ``window_days`` the card length.

    TODO(F3): replace the body with the shared period band (S1, both platforms):
    ``return period_band(totals_by_window, window_days).band_pct`` from
    ``juli_backend.services.forecast.noise.period_band(totals_by_window, window_days,
    coverage=0.8, min_pct=0.01)``. Until then: volatility.py's window-mean band of the
    observed days (the card length does not enter it). The KPI target keeps its own
    window-mean band either way.
    """
    return window_band_pct([v for v in totals_by_window if v is not None])


def stale_before(today: date) -> date:
    """The oldest data-through day still fresh (F2 against TikTok's expected lag)."""
    return today - timedelta(days=TIKTOK_ANALYTICS_EXPECTED_LAG_DAYS + FORECAST_STALE_GRACE_DAYS)


def is_stale(data_through: date, today: date | None) -> bool:
    """F2: data-through older than the platform's lag plus grace; ``today`` None: fresh."""
    return today is not None and data_through < stale_before(today)


def within_noise(
    effect_p90: float,
    history: Sequence[float | None],
    window_days: int = CARD_DAYS,
    kind: str | None = None,
) -> bool:
    """F5: the effect's P90 (relative) is below the metric's noise band.

    Same shape as S1's shared ``within_noise(effect_p90, history, window_days, kind)``;
    a kind in :data:`NON_UPLIFT_KINDS` follows its own rule (never "within noise"), and
    no band (too little history) is not within noise.
    """
    if kind is not None and kind in NON_UPLIFT_KINDS:
        return False
    band_pct = noise_band_for_card(history, window_days)
    if band_pct is None:
        return False
    return effect_p90 < band_pct / 100


@dataclass(frozen=True)
class CardForecast:
    """The card's shown numbers per month (``None`` = "—") and how they were made."""

    data_through: date
    stale: bool
    source: str
    target_metric: str
    #: The target metric's own P50 relative lift (``None``: within noise or stale).
    target_lift: float | None
    orders_per_month: float | None
    gmv_per_month: float | None
    #: F9: no profit model on TikTok yet.
    profit_per_month: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "data_through": self.data_through.isoformat(),
            "stale": ({"data_through": self.data_through.isoformat()} if self.stale else None),
            "source": self.source,
            "scenario": "gmv_p50",
            "target_metric": self.target_metric,
            "target_lift": None if self.target_lift is None else round(self.target_lift, 4),
            "orders_per_month": (
                None if self.orders_per_month is None else round(self.orders_per_month, 2)
            ),
            "gmv_per_month": None if self.gmv_per_month is None else round(self.gmv_per_month),
            "profit_per_month": self.profit_per_month,
        }


def card_forecast(
    prediction: Prediction,
    *,
    target_metric: str,
    data_through: date,
    today: date | None,
    gmv_per_day: float,
    aov: float | None,
    histories: dict[str, list[float | None]],
    card_days: int = CARD_DAYS,
    kind: str | None = None,
) -> CardForecast:
    """F2 / F5 / F8 / F9 for one card. ``histories``: metric -> its daily series
    (:func:`daily_history`; the target metric, ``orders`` and ``gmv``). ``aov``: the
    product's AOV over its window; orders are GMV ÷ AOV, so the two always add up."""
    stale = is_stale(data_through, today)
    if stale:
        return CardForecast(
            data_through=data_through,
            stale=True,
            source=prediction.source,
            target_metric=target_metric,
            target_lift=None,
            orders_per_month=None,
            gmv_per_month=None,
        )
    p50 = prediction.lift_mid
    p90 = max(prediction.lift_high, p50)
    moves_orders = target_metric != AOV_METRIC
    # F8: one scenario (the P50 lift) through GMV = orders × AOV.
    gmv = gmv_per_day * p50 * DAYS_PER_MONTH
    orders: float | None = None
    if not moves_orders:
        orders = 0.0
    elif aov is not None and aov > 0:
        orders = gmv / aov
    orders_p90 = p90 if moves_orders else 0.0
    if within_noise(orders_p90, histories.get(METRIC_ORDERS, []), card_days, kind):
        orders = None
    return CardForecast(
        data_through=data_through,
        stale=False,
        source=prediction.source,
        target_metric=target_metric,
        target_lift=(
            None if within_noise(p90, histories.get(target_metric, []), card_days, kind) else p50
        ),
        orders_per_month=orders,
        gmv_per_month=(
            None if within_noise(p90, histories.get(METRIC_GMV, []), card_days, kind) else gmv
        ),
    )


__all__ = [
    "CARD_DAYS",
    "NON_UPLIFT_KINDS",
    "CardForecast",
    "card_forecast",
    "daily_history",
    "is_stale",
    "noise_band_for_card",
    "stale_before",
    "within_noise",
]
