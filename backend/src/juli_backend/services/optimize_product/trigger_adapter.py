"""F11: TikTok's adapter for the shared trigger detector (``services.forecast.triggers``). Pure.

The detector is platform-free; this module is the TikTok side of it:

* **Rows.** P1's daily :class:`~.daily_funnel.ProductDay` rows become ``triggers.DayRow``:
  TikTok's ``impressions`` are the detector's ``views``, ``sku_orders`` its ``orders``. A day
  with no row stays missing (F2, never zero), and so does a day the product was out of stock
  or unlisted (``available is False``).
* **Metric names.** The detector splits GMV over views / CTR / CTOR / AOV; the TikTok card
  code names the first one ``impressions``. :data:`TO_TIKTOK` / :data:`FROM_TIKTOK` are the
  one place the two names meet.
* **Reference.** The shop median of GMV per day (``triggers.shop_median`` over the products
  that are not excluded) and the category benchmark of GMV per day, when the ``benchmarks``
  input carries one (key ``gmv``).
* **Levers per metric.** Given by the caller (``decision_cards.TRIGGER_LEVERS``, built from
  the card code's own metric -> funnel stage -> angle mapping).
* **Profit.** Unknown on TikTok (F9): :meth:`TikTokTriggerAdapter.profit_per_gmv` is ``None``,
  so every value is ΔGMV.
* **Forecasts.** One :class:`~juli_backend.services.forecast.triggers.LeverForecast` per
  lever the product could get a card for (the card path's own ``predict``): ΔGMV P50 over the
  card's period = GMV per day × the P50 lift × the period (F8, the same scenario
  ``forecast.card_forecast`` shows), Δprofit ``None``, history = the product's daily GMV in
  its F2 window (:func:`~.forecast.daily_history`). Stale data (F2) has no forecast.
* **Rules.** The TikTok card path has no platform-rule cards outside the forecast yet (no
  stock / listing_hide / voucher_cap card is built from the nightly input, and the D39.1
  growth seam returns nothing): :meth:`TikTokTriggerAdapter.rule_triggers` passes through
  whatever the caller hands it, by default nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from juli_backend.services.forecast.triggers import (
    DayRow,
    LeverForecast,
    ProductSeries,
    Reference,
    RuleTrigger,
    shop_median,
)
from juli_backend.services.optimize_product.daily_funnel import ProductDay
from juli_backend.services.optimize_product.forecast import (
    CARD_DAYS,
    METRIC_GMV,
    daily_history,
    is_stale,
)

#: The detector's metric -> the TikTok card code's metric (the one place they meet).
TO_TIKTOK: Mapping[str, str] = {"views": "impressions", "ctr": "ctr", "ctor": "ctor", "aov": "aov"}
FROM_TIKTOK: Mapping[str, str] = {v: k for k, v in TO_TIKTOK.items()}


def to_tiktok_metric(metric: str | None) -> str | None:
    return None if metric is None else TO_TIKTOK.get(metric, metric)


def from_tiktok_metric(metric: str) -> str:
    return FROM_TIKTOK.get(metric, metric)


def day_rows(rows: Sequence[ProductDay]) -> tuple[DayRow, ...]:
    """TikTok's daily rows as the detector's; unavailable days are left out (missing)."""
    return tuple(
        DayRow(
            day=r.day,
            views=float(r.impressions),
            clicks=float(r.clicks),
            orders=float(r.sku_orders),
            gmv=float(r.gmv),
        )
        for r in sorted(rows, key=lambda r: r.day)
        if r.available is not False
    )


def product_series(product_id: str, rows: Sequence[ProductDay]) -> ProductSeries:
    return ProductSeries(product_id=product_id, days=day_rows(rows))


def gmv_per_day(rows: Sequence[ProductDay], *, as_of: date, window_days: int) -> float | None:
    """GMV per observed day over the window ending ``as_of`` (missing days left out)."""
    first = as_of - timedelta(days=window_days - 1)
    seen = [float(r.gmv) for r in rows if first <= r.day <= as_of and r.available is not False]
    return sum(seen) / len(seen) if seen else None


@dataclass(frozen=True)
class LeverCandidate:
    """A lever the card path could propose for the product, with its P50 lift."""

    lever: str
    #: The TikTok metric the lever's card targets (impressions / ctr / ctor / aov).
    metric: str
    lift_p50: float


@dataclass(frozen=True)
class ProductInputs:
    """What the adapter knows about one product (built by the card planner)."""

    rows: tuple[ProductDay, ...]
    #: GMV per day the forecast scales (the card's own figure).
    gmv_per_day: float
    #: The F2 window the GMV history (the F3 band) is read over.
    gmv_window_days: int
    candidates: tuple[LeverCandidate, ...] = ()
    benchmark_gmv_per_day: float | None = None


@dataclass(frozen=True)
class TikTokTriggerAdapter:
    """``triggers.TriggerAdapter`` for TikTok (see the module docstring)."""

    products: Mapping[str, ProductInputs]
    levers_by_metric: Mapping[str, tuple[str, ...]]
    as_of: date
    today: date | None = None
    period_days: int = CARD_DAYS
    shop_median_gmv: float | None = None
    rules: tuple[RuleTrigger, ...] = field(default=())

    def series(self) -> list[ProductSeries]:
        return [product_series(pid, inputs.rows) for pid, inputs in self.products.items()]

    def reference(self, product_id: str) -> Reference:
        inputs = self.products.get(product_id)
        return Reference(
            shop_median=self.shop_median_gmv,
            benchmark=inputs.benchmark_gmv_per_day if inputs is not None else None,
        )

    def levers_for(self, metric: str) -> tuple[str, ...]:
        return tuple(self.levers_by_metric.get(to_tiktok_metric(metric) or metric, ()))

    def profit_per_gmv(self, product_id: str) -> float | None:
        return None  # F9: no TikTok profit model yet

    def forecasts(self, product_id: str) -> list[LeverForecast]:
        inputs = self.products.get(product_id)
        if inputs is None:
            return []
        stale = is_stale(self.as_of, self.today)
        history = daily_history(
            inputs.rows, as_of=self.as_of, metric=METRIC_GMV, window_days=inputs.gmv_window_days
        )
        return [
            LeverForecast(
                product_id=product_id,
                lever=c.lever,
                target_metric=from_tiktok_metric(c.metric),
                dgmv_p50=None if stale else inputs.gmv_per_day * c.lift_p50 * self.period_days,
                dprofit_p50=None,
                period_days=self.period_days,
                gmv_history=history,
                detail={"lift_p50": c.lift_p50, "gmv_per_day": inputs.gmv_per_day},
            )
            for c in inputs.candidates
        ]

    def rule_triggers(self) -> tuple[RuleTrigger, ...]:
        return self.rules


def shop_median_gmv(
    rows_by_product: Mapping[str, Sequence[ProductDay]], *, as_of: date, window_days: int
) -> float | None:
    """``triggers.shop_median`` of the products' GMV per observed day over ``window_days``."""
    values = [
        v
        for rows in rows_by_product.values()
        if (v := gmv_per_day(rows, as_of=as_of, window_days=window_days)) is not None
    ]
    return shop_median(values)


__all__ = [
    "FROM_TIKTOK",
    "TO_TIKTOK",
    "LeverCandidate",
    "ProductInputs",
    "TikTokTriggerAdapter",
    "day_rows",
    "from_tiktok_metric",
    "gmv_per_day",
    "product_series",
    "shop_median_gmv",
    "to_tiktok_metric",
]
