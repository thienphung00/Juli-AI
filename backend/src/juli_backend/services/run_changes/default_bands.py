"""D29.9: the default hold threshold of every non-target metric = its window-mean band.

"Đặt ngưỡng giữ ổn định" used to need a seller-set ``stability_band`` per metric
(no band, no day-7 check). D29.9 gives every metric a default: ``guard_band_mult``
(D29.11, default 1) × the D28.1 band of its window MEAN over the 14 days before
the change, in ± %. A seller-set band still wins (:func:`effective_bands`). Pure.

Metric keys are the impact reader's (``shop_rules.BAND_METRICS``): ``impressions``,
``ctr``, ``conversion_rate`` (CTOR), ``items_sold``, ``gmv``, ``sku_orders``,
``gmv_per_order`` (AOV).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal

from juli_backend.services.optimize_product.volatility import window_band_pct

#: The impact reader's metric key -> the D29 metric name it is (for card targets).
D29_METRIC: Mapping[str, str] = {
    "impressions": "impressions",
    "ctr": "ctr",
    "conversion_rate": "ctor",
    "gmv_per_order": "aov",
}
#: And back: a card's target metric -> the impact reader's key.
BAND_METRIC_OF: Mapping[str, str] = {v: k for k, v in D29_METRIC.items()}


def default_bands(
    series: Mapping[str, Iterable[float | None]], *, guard_band_mult: float = 1.0
) -> dict[str, Decimal]:
    """metric -> ± % (two decimals) from each metric's daily values; no band → left out."""
    out: dict[str, Decimal] = {}
    for metric, values in series.items():
        clean = [float(v) for v in values if v is not None]
        pct = window_band_pct(clean)
        if pct is None:
            continue
        out[metric] = Decimal(str(pct * guard_band_mult)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return out


def effective_bands(
    seller: Mapping[str, Decimal], defaults: Mapping[str, Decimal]
) -> dict[str, tuple[Decimal, str]]:
    """metric -> (band %, ``"seller"`` | ``"default"``); a seller edit wins."""
    out: dict[str, tuple[Decimal, str]] = {k: (v, "default") for k, v in defaults.items()}
    out.update({k: (v, "seller") for k, v in seller.items()})
    return out


__all__ = ["BAND_METRIC_OF", "D29_METRIC", "default_bands", "effective_bands"]
