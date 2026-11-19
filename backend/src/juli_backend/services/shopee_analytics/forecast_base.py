"""F2 (owner, 2026-11-16): the forecast base of a Shopee scope. Pure.

The builder's "before" used to be the plain sums of one fixed 30-day window, every calendar day
counted, a day after the newest data as a zero. Here, as on TikTok (``optimize_product.volatility``,
D29.1):

* **Adaptive window per metric.** The shortest of :data:`WINDOWS` (14 / 30 / 60 days) holding at
  least :data:`MIN_EVENTS` events (clicks for CTR; orders for CTOR, AOV, GMV). None qualifies:
  the 60-day window is used anyway (owner 2026-11-16) and the wide F3 band decides (F5); only a
  metric with no event in 60 days is "ít dữ liệu" (``FunnelBase.low_data``).
  Lượt xem is never low-data and reads the shortest window. The numbers are the same as
  ``DiagTunables`` defaults on TikTok (windows 14/30/60, 30 events); they are repeated here because
  a Shopee module does not read TikTok's per-shop rules row.
* **Missing is not zero.** A day after a dataset's last data day (orders, traffic, ads) is missing:
  every rate divides by the days up to that last day, never by the calendar window. The base is
  then written as sums over 30 days at those rates, so Lượt xem x CTR x CTOR = đơn and đơn x AOV =
  GMV hold and the engine's scaling by days / 30 stays right.
* **Stale.** The newest data older than its expected lag + :data:`STALE_GRACE_DAYS` days: the base
  carries a :class:`StaleMarker` (dataset, data-through day) and the engine gives no numbers.

* **A day without product traffic rows is missing, not 0 (C1, owner 2026-11-19).** For a product
  scope, a day on which none of its products has a traffic row (views / clicks not ``None``, in
  ``sources`` or ``product_days``) leaves views, CTR and CTOR like an unavailable day: rates are
  taken over the days that do have rows, numerator and denominator on the same days (orders of a
  day without traffic rows never enter CTOR), then scaled to the window. A row with views 0 is a
  real 0. Fewer than :data:`MIN_TRAFFIC_DAYS` such days: views and clicks stay unknown.
  The order rate keeps the order dataset's own days. The shop scope is unchanged.
* **Unavailable is not zero either.** For a product scope, a day on which any product of the scope
  was out of stock or unlisted (``rows.unavailable``, from the stock history, see
  :mod:`unavailable_days`) leaves the base like a missing day: its rows leave every numerator, the
  day leaves every day count and the F3 daily series. A day without a stock read counts as
  available. The shop scope is unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from juli_backend.services.shopee_analytics import funnel
from juli_backend.services.shopee_analytics.unavailable_days import scope_unavailable
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_builder.engine.contract import (
    RESIDUAL,
    AdShare,
    FunnelBase,
    SourceFunnel,
    StaleMarker,
)

#: Same numbers as ``optimize_product.tunables.DiagTunables`` (windows, min_events).
WINDOWS: tuple[int, ...] = (14, 30, 60)
MIN_EVENTS = 30
#: The base is written as sums over this many days (the engine's default horizon).
BASE_DAYS = 30
#: No forecast when the newest data is older than its expected lag + this many days.
STALE_GRACE_DAYS = 2
#: A product scope needs at least this many days WITH product-level traffic rows in its window;
#: fewer and views / CTR / CTOR are not estimable (never a low number). Same number as
#: ``shopee_builder.engine_families.common.MIN_MEASURE_DAYS``, repeated because analytics must not
#: import the builder.
MIN_TRAFFIC_DAYS = 5

#: Days a dataset normally trails today, per (platform, dataset). Shopee's Phân tích bán hàng
#: shows yesterday, so traffic and ads trail by 1; orders arrive the same day. TikTok's analytics
#: trail by 2: ``card_measure.tiktok_series`` reads its lag from the ``("tiktok", "analytics")``
#: entry.
EXPECTED_LAG_DAYS: dict[tuple[str, str], int] = {
    ("shopee", "orders"): 0,
    ("shopee", "traffic"): 1,
    ("shopee", "ads"): 1,
    ("tiktok", "analytics"): 2,
}

ZERO = Decimal(0)


def _traffic_missing(
    rows: funnel.FunnelRows, items: tuple[str, ...], last: date | None
) -> frozenset[date]:
    """Days up to ``last`` (from the window start) on which no product of the scope has a traffic
    row; empty for the shop scope."""
    if not items or last is None:
        return frozenset()
    wanted = set(items)
    present = {
        r.day
        for r in rows.sources
        if r.item_id in wanted and (r.views is not None or r.clicks is not None)
    }
    present |= {
        d.day
        for d in rows.product_days
        if d.item_id in wanted and (d.views is not None or d.clicks is not None)
    }
    n = (last - rows.window.start).days + 1
    return frozenset(
        day
        for i in range(max(n, 0))
        if (day := rows.window.start + timedelta(days=i)) not in present
    )


def _span(start: date, end: date, floor: date, skip: frozenset[date] = frozenset()) -> int:
    """Calendar days of ``start..end`` that the rows cover (never before ``floor``), less the
    ``skip`` days (unavailable days of a product scope)."""
    first = max(start, floor)
    n = max(0, (end - first).days + 1)
    return n - sum(1 for d in skip if first <= d <= end)


@dataclass(frozen=True)
class _Last:
    orders: date | None
    traffic: date | None
    ads: date | None


def last_days(rows: funnel.FunnelRows) -> _Last:
    """The newest day each dataset has data for."""
    orders = [d.day for d in rows.shop_days if d.orders or d.gmv]
    orders += [r.day for r in rows.sources if r.orders or r.gmv]
    orders += [d.day for d in rows.product_days if d.orders or d.gmv]
    traffic = [r.day for r in rows.sources if r.views or r.clicks]
    traffic += [d.day for d in rows.product_days if d.views or d.clicks]
    ads = [r.day for r in rows.sources if r.ads_spend is not None]
    ads += [d.day for d in rows.product_days if d.ads_spend is not None]
    return _Last(max(orders, default=None), max(traffic, default=None), max(ads, default=None))


def stale_marker(last: _Last, today: date | None, platform: str = "shopee") -> StaleMarker | None:
    """The first dataset (orders, then traffic) whose newest day is too old; ``None`` when fresh
    or when ``today`` is unknown."""
    if today is None:
        return None
    for dataset, through in (("orders", last.orders), ("traffic", last.traffic)):
        if through is None:
            continue
        limit = EXPECTED_LAG_DAYS[(platform, dataset)] + STALE_GRACE_DAYS
        if (today - through).days > limit:
            return StaleMarker(dataset, through)
    return None


def _slice(
    rows: funnel.FunnelRows,
    start: date,
    end: date,
    ads_end: date | None,
    skip: frozenset[date] = frozenset(),
) -> funnel.FunnelRows:
    """The rows of ``start..end`` without the ``skip`` days; ads figures after ``ads_end`` are
    unknown, not zero."""

    def ads_ok(day: date) -> bool:
        return ads_end is not None and day <= ads_end

    sources = tuple(
        r
        if ads_ok(r.day)
        else replace(
            r, ads_views=None, ads_clicks=None, ads_orders=None, ads_gmv=None, ads_spend=None
        )
        for r in rows.sources
        if start <= r.day <= end and r.day not in skip
    )
    product_days = tuple(
        d if ads_ok(d.day) else replace(d, ads_spend=None)
        for d in rows.product_days
        if start <= d.day <= end and d.day not in skip
    )
    shop_days = tuple(d for d in rows.shop_days if start <= d.day <= end and d.day not in skip)
    return funnel.FunnelRows(Window(start, end), sources, shop_days, product_days, rows.unavailable)


def _by_source(base: FunnelBase) -> dict[str, SourceFunnel]:
    return {s.source: s for s in base.sources}


def _events(base: FunnelBase, kind: str) -> int:
    if kind == "click":
        total = funnel.known_total(base, "clicks")
    else:
        total = base.total("orders")
    return 0 if total is None else int(total)


def adaptive_base(
    rows: funnel.FunnelRows,
    shop_id: str,
    *,
    item_ids: Sequence[str] = (),
    contribution_rate: Decimal | None = None,
    today: date | None = None,
    platform: str = "shopee",
) -> FunnelBase:
    """The F2 base of the shop (``item_ids`` empty) or of those products."""
    items = tuple(item_ids)
    last = last_days(rows)
    plain = funnel.base_from_rows(
        rows, shop_id, item_ids=items, contribution_rate=contribution_rate
    )
    if last.orders is None:  # no order data at all: nothing to adapt
        return plain
    end = rows.window.end
    floor = rows.window.start
    ol = min(last.orders, end)
    tl = None if last.traffic is None else min(last.traffic, end)
    al = None if last.ads is None else min(last.ads, end)
    stale = stale_marker(last, today, platform)
    skip = scope_unavailable(rows.unavailable, items)
    skip_t = skip | _traffic_missing(rows, items, tl)
    min_days = MIN_TRAFFIC_DAYS if items else 0

    def base_of(cap: date, length: int, sk: frozenset[date] = skip) -> tuple[FunnelBase, int]:
        start = cap - timedelta(days=length - 1)
        sl = _slice(rows, start, cap, al, sk)
        n = _span(start, cap, floor, sk)
        return (
            funnel.base_from_rows(sl, shop_id, item_ids=items, contribution_rate=contribution_rate),
            n,
        )

    def pick(
        cap: date | None, kind: str | None, sk: frozenset[date] = skip, need: int = 0
    ) -> tuple[int, bool]:
        if cap is None:
            return WINDOWS[0], False
        if kind is None:
            for length in WINDOWS:
                if _span(cap - timedelta(days=length - 1), cap, floor, sk) >= need:
                    return length, False
            return WINDOWS[-1], False
        events = 0
        for length in WINDOWS:
            b, n_days = base_of(cap, length, sk)
            events = _events(b, kind)
            if events >= MIN_EVENTS and n_days >= need:
                return length, False
        # Owner 2026-11-16 (F2 amendment): no window holds MIN_EVENTS -> use the 60-day window
        # anyway; its wide F3 noise band (F5) blanks any effect that does not clear it. Only a
        # metric with no event at all in 60 days is "ít dữ liệu".
        return WINDOWS[-1], events == 0

    both = ol if tl is None else min(ol, tl)
    w_views, _ = pick(tl, None, skip_t, min_days)
    w_ctr, ctr_low = pick(tl, "click", skip_t, min_days)
    w_ctor, ctor_low = pick(both, "order", skip_t, min_days)
    # C1: too few days with product traffic rows even in the widest window -> not estimable
    thin_traffic = (
        min_days > 0
        and tl is not None
        and _span(tl - timedelta(days=WINDOWS[-1] - 1), tl, floor, skip_t) < min_days
    )
    if thin_traffic:
        tl = None
    w_ord, ord_low = pick(ol, "order")
    bv, nv = base_of(tl, w_views, skip_t) if tl is not None else (plain, 0)
    bc, _ = base_of(tl, w_ctr, skip_t) if tl is not None else (plain, 0)
    bt, _ = base_of(both, w_ctor, skip_t)
    bo, n_o = base_of(ol, w_ord)
    b_views = _by_source(bv)
    b_ctr = _by_source(bc)
    b_ctor = _by_source(bt)
    scale = Decimal(BASE_DAYS)
    ads_days = 0 if al is None else _span(ol - timedelta(days=w_ord - 1), min(al, ol), floor, skip)

    out: list[SourceFunnel] = []
    for so in bo.sources:
        key = so.source
        views_rate = None
        ctr = ctor = None
        if tl is not None and key != RESIDUAL:
            sv = b_views.get(key)
            if sv is not None and sv.views is not None and nv > 0:
                views_rate = sv.views / nv
            sc = b_ctr.get(key)
            if sc is not None and sc.views and sc.clicks is not None:
                ctr = sc.clicks / sc.views
            st = b_ctor.get(key)
            if st is not None and st.clicks and st.clicks > 0:
                ctor = st.orders / st.clicks
        orders_rate = so.orders * scale / max(n_o, 1)
        views: Decimal | None = None
        clicks: Decimal | None = None
        orders = orders_rate
        if views_rate is not None and ctr is not None:
            views = views_rate * scale
            clicks = views * ctr
            if ctor is not None:
                orders = clicks * ctor
        elif views_rate is not None:
            views, clicks = views_rate * scale, None
            # a source with no views and no clicks in the window (a shop without Live) has a known
            # zero of clicks, not an unknown: an unknown would blank the shop's whole CTR / CTOR
            sc0 = b_ctr.get(key)
            if sc0 is not None and not sc0.views and sc0.clicks == 0:
                clicks = Decimal(0)
        aov = so.gmv / so.orders if so.orders > 0 else None
        gmv = orders * aov if aov is not None else so.gmv * scale / max(n_o, 1)
        factor = orders / orders_rate if orders_rate > 0 else Decimal(1)
        k_prof = scale / max(n_o, 1) * factor
        ads = so.ads
        if ads is not None and ads_days > 0:
            k_ads = scale / ads_days

            def sc_(x: Decimal | None, k: Decimal = k_ads) -> Decimal | None:
                return None if x is None else x * k

            ads = AdShare(
                sc_(ads.views), sc_(ads.clicks), sc_(ads.orders), sc_(ads.gmv), sc_(ads.spend)
            )
        elif ads is not None:
            ads = None
        out.append(
            replace(
                so,
                views=views,
                clicks=clicks,
                orders=orders,
                gmv=gmv,
                profit=None if so.profit is None else so.profit * k_prof,
                profit_orders=so.profit_orders * k_prof,
                ads=ads,
            )
        )
    low: list[str] = []
    if (ctr_low and tl is not None) or thin_traffic:
        low.append("ctr")
    if ctor_low or thin_traffic:
        low.append("ctor")
    if ord_low:
        low.append("aov")
    return replace(
        bo,
        window_start=end - timedelta(days=BASE_DAYS - 1),
        window_end=end,
        sources=tuple(out),
        low_data=tuple(low),
        stale=stale,
        windows=(("views", w_views), ("ctr", w_ctr), ("ctor", w_ctor), ("aov", w_ord)),
        daily=_daily(rows, items, ol - timedelta(days=w_ord - 1), ol, floor, skip),
    )


def _daily(
    rows: funnel.FunnelRows,
    items: tuple[str, ...],
    start: date,
    end: date,
    floor: date,
    skip: frozenset[date] = frozenset(),
) -> tuple[tuple[str, tuple[float | None, ...]], ...]:
    """Daily orders / GMV / profit of the scope from ``start`` to its newest order day."""
    first = max(start, floor)
    days = [
        day for i in range((end - first).days + 1) if (day := first + timedelta(days=i)) not in skip
    ]
    orders: dict[date, float] = {}
    gmv: dict[date, float] = {}
    profit: dict[date, float | None] = {}
    wanted = set(items)
    src = rows.product_days if wanted else rows.shop_days
    for d in src:
        if wanted and d.item_id not in wanted:
            continue
        orders[d.day] = orders.get(d.day, 0.0) + d.orders
        gmv[d.day] = gmv.get(d.day, 0.0) + float(d.gmv)
        if d.profit is not None:
            profit[d.day] = (profit.get(d.day) or 0.0) + float(d.profit)
        else:
            profit.setdefault(d.day, None)
    return (
        ("orders", tuple(orders.get(day, 0.0) for day in days)),
        ("gmv", tuple(gmv.get(day, 0.0) for day in days)),
        ("profit", tuple(profit.get(day) for day in days)),
    )


__all__ = [
    "BASE_DAYS",
    "EXPECTED_LAG_DAYS",
    "MIN_EVENTS",
    "MIN_TRAFFIC_DAYS",
    "STALE_GRACE_DAYS",
    "WINDOWS",
    "adaptive_base",
    "last_days",
    "stale_marker",
]
