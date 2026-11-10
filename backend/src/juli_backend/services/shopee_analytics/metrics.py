"""ShopMetrics: the one read model every Shopee screen takes its core numbers from (P97 D85.2).

Before this module Tổng quan, Phân tích, Sản phẩm, Luồng, the builder's catalogue, the cards and
Kế hoạch each picked their own GMV, window and AOV. Now:

- **Headline GMV and Đơn** are Shopee's shop totals (``PeriodView.shop_gmv`` / ``shop_orders``:
  the daily totals the Connector reads, the file period as fallback, the order lines only when
  neither exists). Nothing else is called "GMV" on a screen.
- **Splits** (per product GMV, units, đơn có sản phẩm) come from the order lines **scaled to the
  totals**: ``line GMV x (shop GMV / line GMV)``, allocated in whole đồng by largest remainder so
  the products add up to the shop GMV exactly. Without order lines the product-period totals stand
  in, scaled the same way -- except on one day of a longer period: then the period is spread
  over its days by the shop's daily shares (P99, :mod:`.period_spread`), never stamped on the day.
- **One AOV** = shop GMV ÷ shop đơn. The Seller Centre AOV (lines, minus the shop voucher) is a
  labelled second line, never the headline.
- **Funnel** (lượt xem, CTR, CTOR) from the stored source funnel when the window has its rows
  (P98 / ADR-122 d.2, :mod:`.funnel`), else the shop flow table; CTOR = shop đơn ÷ lượt nhấp, so
  CTOR x CTR x views x AOV is the headline GMV.
- **One window**: the screens resolve their window from :func:`windows.choose_anchor` (30 days
  ending on the last complete day every live daily dataset posted); the payload names that day.

Pure over a :class:`PeriodView`; no I/O.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.fmt import num, pct, ratio
from juli_backend.services.shopee_analytics.funnel import (
    BASIS_SOURCES,
    CTOR_NOTE,
    base_from_rows,
    known_total,
)
from juli_backend.services.shopee_analytics.loaders import product_totals_for
from juli_backend.services.shopee_analytics.stored import StoredWindow
from juli_backend.services.shopee_analytics.windows import Anchor, Window
from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div

if TYPE_CHECKING:
    from juli_backend.services.shopee_analytics.period_spread import SpreadDay

BASIS_SHOP_TOTALS = "shop_totals"
BASIS_ORDER_LINES = "order_lines"
SPLIT_SCALED_LINES = "scaled_order_lines"
SPLIT_PRODUCT_PERIOD = "scaled_product_period"
#: P99: a period total spread over its days by the shop's daily shares (:mod:`.period_spread`)
SPLIT_SPREAD_PERIOD = "spread_product_period"
SPLIT_LINES = "order_lines"

GMV_LABEL = "GMV shop (Shopee)"
AOV_LABEL = "AOV = GMV shop ÷ đơn shop"
AOV_SC_LABEL = "AOV theo Seller Centre (GMV trừ voucher shop ÷ đơn)"
SPLIT_NOTE = (
    "Sản phẩm: dòng đơn hàng nhân với (GMV shop ÷ GMV dòng đơn) nên cộng lại đúng bằng GMV shop."
)


def allocate(total: Decimal, parts: dict[str, Decimal]) -> dict[str, Decimal]:
    """Split ``total`` (rounded to whole đồng) over ``parts`` in proportion to their weights,
    largest remainder first, so the pieces add up to the total exactly. Ties break on the key."""
    whole = total.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    weight = sum(parts.values(), ZERO)
    if weight <= 0 or not parts:
        return {k: ZERO for k in parts}
    raw = {k: whole * v / weight for k, v in parts.items()}
    floors = {k: v.to_integral_value(rounding="ROUND_FLOOR") for k, v in raw.items()}
    left = int(whole - sum(floors.values(), ZERO))
    order = sorted(parts, key=lambda k: (-(raw[k] - floors[k]), k))
    for k in order[: max(left, 0)]:
        floors[k] += 1
    return floors


@dataclass(frozen=True)
class ProductSplit:
    """One product's share of the shop totals (see the module docstring)."""

    item_id: str
    gmv: Decimal
    orders: int
    units: int
    line_gmv: Decimal
    line_orders: int
    basis: str


@dataclass(frozen=True)
class ShopMetrics:
    window: Window
    gmv: Decimal | None
    orders: int | None
    gmv_basis: str
    views: int | None
    clicks: int | None
    ad_spend: Decimal
    ads_roas_placed: Decimal | None
    profit: Decimal | None
    profit_is_partial: bool
    margin_pct: Decimal | None
    aov_seller_centre: Decimal | None
    line_gmv: Decimal
    line_orders: int
    gmv_scale: Decimal | None
    splits: dict[str, ProductSplit] = field(default_factory=dict)
    anchor: Anchor | None = None
    #: the part of the shop GMV no order line explains (stored, never spread over the products)
    unattributed_gmv: Decimal = ZERO
    #: "tables" = summed from the materialized daily rows, "raw" = computed from the raw tables
    read_from: str = "raw"
    sources: dict[str, str] = field(default_factory=dict)
    #: where views / clicks come from (P98 / ADR-122 d.2): "source_funnel" = the stored funnel
    #: per source, "flow_tables" = the traffic tables (before the source rows exist)
    funnel_basis: str = "flow_tables"

    # ------------------------------------------------------------------ derived
    @property
    def aov(self) -> Decimal | None:
        """The one AOV: shop GMV ÷ shop đơn."""
        if self.gmv is None or not self.orders:
            return None
        return self.gmv / Decimal(self.orders)

    @property
    def ctr(self) -> Decimal | None:
        if self.views is None or self.clicks is None:
            return None
        return safe_div(Decimal(self.clicks), Decimal(self.views))

    @property
    def ctor(self) -> Decimal | None:
        if self.clicks is None or self.orders is None:
            return None
        return safe_div(Decimal(self.orders), Decimal(self.clicks))

    @property
    def units(self) -> int:
        return sum(s.units for s in self.splits.values())

    def split(self, item_id: str) -> ProductSplit | None:
        return self.splits.get(item_id)

    def gmv_of(self, item_id: str) -> Decimal | None:
        s = self.splits.get(item_id)
        return None if s is None else s.gmv

    # --------------------------------------------------------------------- json
    def json(self) -> dict[str, Any]:
        return {
            "window": self.window.json(),
            "anchor": None if self.anchor is None else self.anchor.json(),
            "gmv": num(self.gmv),
            "gmv_label": GMV_LABEL,
            "gmv_basis": self.gmv_basis,
            "orders": self.orders,
            "aov": num(self.aov),
            "aov_label": AOV_LABEL,
            "aov_seller_centre": num(self.aov_seller_centre),
            "aov_seller_centre_label": AOV_SC_LABEL,
            "units": self.units or None,
            "views": self.views,
            "clicks": self.clicks,
            "ctr": ratio(self.ctr),
            "ctor": ratio(self.ctor),
            "ctor_note": CTOR_NOTE,
            "funnel_basis": self.funnel_basis,
            "ad_spend": num(self.ad_spend),
            "ads_roas_placed": ratio(self.ads_roas_placed, 2),
            "profit": num(self.profit),
            "profit_is_partial": self.profit_is_partial,
            "margin_pct": pct(self.margin_pct),
            "line_gmv": num(self.line_gmv),
            "line_orders": self.line_orders,
            "gmv_scale": ratio(self.gmv_scale),
            "unattributed_gmv": num(self.unattributed_gmv),
            "read_from": self.read_from,
            "sources": dict(self.sources),
            "split_note": SPLIT_NOTE,
        }


def _spread_splits(spread: Mapping[str, SpreadDay], gmv: Decimal | None) -> dict[str, ProductSplit]:
    """A day's splits from its spread period totals (P99): đơn as spread; GMV = the spread
    period Doanh số, fitted inside the shop's GMV of the day (scaled down, never up, so every
    product keeps about its period AOV and the rest stays unattributed)."""
    picked = {i: s for i, s in spread.items() if s.orders is not None and s.gmv is not None}
    expected = {i: s.gmv for i, s in picked.items() if s.gmv is not None and s.gmv > 0}
    total = sum(expected.values(), ZERO)
    target = total if gmv is None else min(max(gmv, ZERO), total)
    shares = allocate(target, expected) if total > 0 else {}
    return {
        i: ProductSplit(i, shares.get(i, ZERO), s.orders or 0, 0, ZERO, 0, SPLIT_SPREAD_PERIOD)
        for i, s in picked.items()
        if s.orders or i in expected
    }


def _splits(
    view: PeriodView,
    gmv: Decimal | None,
    orders: int | None,
    spread: Mapping[str, SpreadDay] | None = None,
) -> tuple[dict[str, ProductSplit], Decimal | None, Decimal | None]:
    """Per product: order lines (all listings, excluded ones too, so the shop adds up) scaled to
    the shop totals. Returns the splits and the GMV / đơn scale factors. ``spread`` = the day's
    share of the product period totals (P99), used instead of the totals on a day without
    order lines."""
    line_gmv: dict[str, Decimal] = defaultdict(lambda: ZERO)
    units: dict[str, int] = defaultdict(int)
    order_ids: dict[str, set[str]] = defaultdict(set)
    for ln, _ in view.pairs:
        line_gmv[ln.product_id] += ln.order_value
        units[ln.product_id] += ln.qty
        order_ids[ln.product_id].add(ln.order_id)
    total_line_gmv = sum(line_gmv.values(), ZERO)
    total_line_orders = view.line_orders
    if total_line_gmv > 0:
        scale = (gmv / total_line_gmv) if gmv is not None else None
        o_scale = (
            Decimal(orders) / Decimal(total_line_orders)
            if orders is not None and total_line_orders
            else None
        )
        shares = allocate(gmv, dict(line_gmv)) if gmv is not None else dict(line_gmv)
        out = {
            i: ProductSplit(
                i,
                shares[i],
                _round(Decimal(len(order_ids[i])) * (o_scale or Decimal(1))),
                _round(Decimal(units[i]) * (scale or Decimal(1))),
                line_gmv[i],
                len(order_ids[i]),
                SPLIT_SCALED_LINES if scale is not None else SPLIT_LINES,
            )
            for i in line_gmv
        }
        return out, scale, o_scale
    if spread and any(s.orders is not None for s in spread.values()):
        return _spread_splits(spread, gmv), None, None
    # no order lines: Shopee's own per-product totals stand in, scaled the same way
    shopee = product_totals_for(view.data.product_flows, view.data.lines)
    if not shopee:
        return {}, None, None
    weights = {i: g for i, (g, _) in shopee.items() if g > 0}
    total = sum(weights.values(), ZERO)
    if total <= 0:
        return {}, None, None
    shares = allocate(gmv, weights) if gmv is not None else weights
    out = {
        i: ProductSplit(
            i, shares[i], int(shopee[i][1]), 0, weights[i], int(shopee[i][1]), SPLIT_PRODUCT_PERIOD
        )
        for i in weights
    }
    return out, (gmv / total if gmv is not None else None), None


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _funnel(view: PeriodView) -> tuple[int | None, int | None]:
    table = view.flows.shop if view.flows else None
    if table is None:
        return None, None
    flows = [r for r in table.rows if not r.is_residual]
    views = sum((r.views for r in flows if r.views is not None), 0)
    clicks = sum((r.clicks for r in flows if r.clicks is not None), 0)
    return views or None, clicks or None


def _aov_seller_centre(view: PeriodView) -> Decimal | None:
    orders = view.line_orders
    if not orders:
        return None
    gmv = sum((ln.order_value for ln, _ in view.pairs), ZERO)
    voucher = sum((ln.shop_voucher_share for ln, _ in view.pairs), ZERO)
    return (gmv - voucher) / Decimal(orders)


def shop_metrics(
    view: PeriodView,
    anchor: Anchor | None = None,
    *,
    spread: Mapping[str, SpreadDay] | None = None,
) -> ShopMetrics:
    """The window's core numbers, once. Every screen's headline comes from here. ``spread``: the
    rebuild's per-day share of longer Shopee periods (P99, :mod:`.period_spread`)."""
    gmv, orders = view.shop_gmv, view.shop_orders
    splits, scale, _ = _splits(view, gmv, orders, spread)
    views, clicks = _funnel(view)
    daily = view.data.ads_daily
    p = view.profit
    profit = p.profit if p.profit is not None else p.profit_on_covered
    if profit is not None and scale is not None and view.line_gmv > 0:
        profit = profit * scale
    totals_ok = view.data.totals.gmv is not None and gmv == view.data.totals.gmv
    gmv_tag = "shop_totals" if totals_ok else "order_lines"
    return ShopMetrics(
        window=view.window,
        gmv=gmv,
        orders=orders,
        gmv_basis=BASIS_SHOP_TOTALS if totals_ok else BASIS_ORDER_LINES,
        views=views,
        clicks=clicks,
        ad_spend=view.ads.total_spend,
        ads_roas_placed=safe_div(daily.gmv, daily.spend) if daily.spend else None,
        profit=profit,
        profit_is_partial=p.margin_is_partial or p.profit is None,
        margin_pct=p.margin_pct,
        aov_seller_centre=_aov_seller_centre(view),
        line_gmv=view.line_gmv,
        line_orders=view.line_orders,
        gmv_scale=scale,
        splits=splits,
        anchor=anchor,
        unattributed_gmv=(gmv - sum((x.gmv for x in splits.values()), ZERO))
        if gmv is not None
        else ZERO,
        sources={
            "gmv": gmv_tag,
            "orders": gmv_tag,
            "splits": SPLIT_SPREAD_PERIOD
            if any(s.basis == SPLIT_SPREAD_PERIOD for s in splits.values())
            else "order_lines",
        },
    )


def from_stored(view: PeriodView, stored: StoredWindow) -> ShopMetrics:
    """The same read model summed from the materialized daily rows (D85.2)."""
    gmv = stored.gmv
    line_gmv = stored.line_gmv or ZERO
    splits = {
        i: ProductSplit(
            i,
            p.gmv,
            p.orders,
            p.units,
            p.line_gmv,
            p.line_orders,
            SPLIT_SCALED_LINES if p.scaled else p.source,
        )
        for i, p in stored.products.items()
    }
    margin = (
        pct_points(safe_div(stored.margin_profit, stored.buyer_paid_known))
        if stored.margin_profit is not None and stored.buyer_paid_known
        else None
    )
    line_orders = stored.line_orders or 0
    return ShopMetrics(
        window=stored.window,
        gmv=gmv,
        orders=stored.orders,
        gmv_basis=BASIS_SHOP_TOTALS,
        views=stored.views,
        clicks=stored.clicks,
        ad_spend=stored.ads_spend or ZERO,
        ads_roas_placed=safe_div(stored.ads_gmv, stored.ads_spend)
        if stored.ads_gmv is not None and stored.ads_spend
        else None,
        profit=stored.profit,
        profit_is_partial=stored.profit_partial,
        margin_pct=margin,
        aov_seller_centre=(stored.aov_sc_net_gmv / Decimal(line_orders))
        if stored.aov_sc_net_gmv is not None and line_orders
        else None,
        line_gmv=line_gmv,
        line_orders=line_orders,
        gmv_scale=(gmv / line_gmv) if gmv is not None and line_gmv > 0 else None,
        splits=splits,
        unattributed_gmv=stored.residual_gmv,
        read_from="tables",
        sources=dict(stored.sources),
    )


def metrics_of(view: PeriodView) -> ShopMetrics:
    """What ``view.metrics`` returns: the stored daily rows when every day of the window is
    complete, else the window computed from the raw tables."""
    stored = view.data.stored
    base = from_stored(view, stored) if stored is not None and stored.usable else shop_metrics(view)
    rows = getattr(view.data, "funnel", None)
    if rows is None or not rows.available:
        return base
    # P98 / ADR-122 d.2: lượt xem / lượt nhấp from the stored funnel; CTOR = this đơn ÷ lượt nhấp
    funnel = base_from_rows(rows, "")
    views, clicks = known_total(funnel, "views"), known_total(funnel, "clicks")
    return replace(
        base,
        views=None if views is None else int(views),
        clicks=None if clicks is None else int(clicks),
        funnel_basis=BASIS_SOURCES,
        sources={**base.sources, "views": BASIS_SOURCES, "clicks": BASIS_SOURCES},
    )


__all__ = [
    "from_stored",
    "metrics_of",
    "AOV_LABEL",
    "AOV_SC_LABEL",
    "SPLIT_SPREAD_PERIOD",
    "ProductSplit",
    "ShopMetrics",
    "allocate",
    "shop_metrics",
]
