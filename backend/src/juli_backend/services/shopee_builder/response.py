"""P92 B-3: how the shop's orders answered a price cut in its own history.

Per product, from its order counts per day and the discount depth its listing carried on that day
(the snapshot history: ``1 - current price / list price``): orders per day on days with a cut of at
least ``MIN_DEPTH`` against days without one. The relative orders lift per 1 % of cut, with an
80 % band from the order counts (Poisson), is what ``prediction.predict_lift`` uses in place of the
preset price elasticity: first this product's own response (``product_history``), then the median
of the other products' (``shop_products``).

A product needs ``MIN_DAYS`` days of each kind and ``MIN_ORDERS`` orders on its base days, else it
has no response of its own. The band's lower end never goes below 0 (a cut is not assumed to lose
orders). Pure: the caller passes the day series.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from juli_backend.services.shopee_recommendations.model import DiscountResponse

MIN_DEPTH = 0.03
MIN_DAYS = 5
MIN_ORDERS = 10
Z80 = 1.2815515655446004
MIN_PRODUCTS_FOR_SHOP = 3
SOURCE_PRODUCT = "product_history"
SOURCE_SHOP = "shop_products"


def covered_span(
    bounds: tuple[date, date] | None, start: date, end: date
) -> tuple[date, date] | None:
    """The part of ``start..end`` the order export speaks for (its first to last day), or ``None``
    when it speaks for none of it. A day outside the export is unknown, not a day with 0 orders, so
    the series is cut to this span instead of being dropped when the export does not reach all 90
    days (it used to need the whole window, which left every product on the preset prior)."""
    if bounds is None:
        return None
    lo, hi = max(bounds[0], start), min(bounds[1], end)
    return (lo, hi) if lo <= hi else None


def depth_by_day(
    snapshots: list[tuple[date, Decimal | None, Decimal | None]], start: date, end: date
) -> dict[date, float]:
    """Discount depth per day from the snapshot history (``(day, list, current)`` ascending): a
    day takes the newest snapshot on or before it; days before the first snapshot are unknown."""
    out: dict[date, float] = {}
    ordered = sorted(snapshots, key=lambda s: s[0])
    day = start
    i = -1
    while day <= end:
        while i + 1 < len(ordered) and ordered[i + 1][0] <= day:
            i += 1
        if i >= 0:
            _, listed, current = ordered[i]
            if listed and current and listed > 0:
                out[day] = max(0.0, float(1 - current / listed))
        day += timedelta(days=1)
    return out


def product_response(
    orders_by_day: Mapping[date, int], depth: Mapping[date, float], start: date, end: date
) -> DiscountResponse | None:
    """This product's own orders lift per 1 % of cut, or ``None`` when its history cannot say."""
    cut_days = base_days = 0
    cut_orders = base_orders = 0
    cut_depth = 0.0
    day = start
    while day <= end:
        d = depth.get(day)
        if d is not None:
            n = orders_by_day.get(day, 0)
            if d >= MIN_DEPTH:
                cut_days += 1
                cut_orders += n
                cut_depth += d
            else:
                base_days += 1
                base_orders += n
        day += timedelta(days=1)
    if cut_days < MIN_DAYS or base_days < MIN_DAYS or base_orders < MIN_ORDERS:
        return None
    rate_cut, rate_base = cut_orders / cut_days, base_orders / base_days
    ratio = rate_cut / rate_base
    mean_depth_pct = cut_depth / cut_days * 100
    if mean_depth_pct <= 0:
        return None
    rel_se = math.sqrt(1 / max(cut_orders, 1) + 1 / base_orders)
    mid = ratio - 1
    low = max(0.0, (mid - Z80 * ratio * rel_se)) / mean_depth_pct
    high = max(0.0, (mid + Z80 * ratio * rel_se)) / mean_depth_pct
    if high <= 0:
        return None
    return DiscountResponse(low, high, SOURCE_PRODUCT, cut_days, base_days, 1)


def shop_response(responses: Mapping[str, DiscountResponse]) -> DiscountResponse | None:
    """The other products' median response; ``None`` below ``MIN_PRODUCTS_FOR_SHOP`` of them."""
    if len(responses) < MIN_PRODUCTS_FOR_SHOP:
        return None
    return DiscountResponse(
        median(r.per_pct_low for r in responses.values()),
        median(r.per_pct_high for r in responses.values()),
        SOURCE_SHOP,
        sum(r.discount_days for r in responses.values()),
        sum(r.base_days for r in responses.values()),
        len(responses),
    )


__all__ = [
    "MIN_DAYS",
    "SOURCE_PRODUCT",
    "SOURCE_SHOP",
    "covered_span",
    "depth_by_day",
    "product_response",
    "shop_response",
]
