"""Canonical components: the sums every metric formula is built from (doc §4).

A component is one platform-neutral quantity per platform, per day, per scope (shop, product,
SKU, channel, KOL). Components are sums, so a window's component is the sum of its days and a
shop's the sum of its products -- metrics are never summed, components are.

This module only declares them. The stored daily rows (``shop_metrics_daily``,
``product_metrics_daily``, ``campaign_metrics_daily``, migration 140) hold them as columns of the
same ids; a caller hands :class:`Components` (id -> ``Decimal`` or ``None``) to
:func:`~juli_backend.services.metrics.compute.evaluate`. ``None`` means "no data", never 0.

**Sums (F4, decision #62).** A component says the dimensions it may be summed over
(``sums_across``, of :class:`Dim`). Money and units add over every dimension. A count that is not
additive across rows is stored where it is true and refused elsewhere: đơn are distinct orders,
so product đơn never add up to the shop's đơn (one order holds several products), and a
campaign's products' contribution never adds over campaigns (two campaigns advertise one
product). :func:`check_sum` refuses any other sum (:class:`InvalidSum`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import TypeVar

from juli_backend.services.metrics.registry import (
    OrderBasis,
    Platform,
    SourceSpec,
    Unit,
    source_available,
)

T = TypeVar("T")

#: one scope's components for one window: id -> value, ``None`` (or absent) = no data
Components = Mapping[str, Decimal | None]


class Dim(StrEnum):
    """The dimensions a stored component row is keyed by (and so may be summed over)."""

    day = "day"
    #: the product (summing over it = the products of the shop)
    item = "item"
    #: Organic / Quảng cáo / TTLK
    channel = "channel"
    #: purchases with / without a shop discount (A9)
    discounted = "discounted"
    campaign = "campaign"


#: what money and units add over: everything
ALL_DIMS: frozenset[Dim] = frozenset(Dim)
#: distinct orders: over days, channels and the discount split (an order counts once per
#: product x channel x discount state), never over products or campaigns
ORDER_DIMS: frozenset[Dim] = frozenset({Dim.day, Dim.channel, Dim.discounted})


class InvalidSum(ValueError):
    """A sum the registry refuses (``sums_across``): the result would not be the number."""

    def __init__(self, component_id: str, refused: frozenset[Dim] | frozenset[str]) -> None:
        self.component_id = component_id
        self.refused = refused
        dims = ", ".join(sorted(str(getattr(d, "value", d)) for d in refused))
        super().__init__(f"{component_id} may not be summed over {dims}")


_C = OrderBasis.confirmed
_K = OrderBasis.known_cost
_N = OrderBasis.none


@dataclass(frozen=True)
class ComponentDef:
    id: str
    unit: Unit
    description: str
    sources: Mapping[Platform, SourceSpec] = field(default_factory=dict)
    summable: bool = True
    #: the components this one stands in for on a platform that lacks them (a reported lump)
    lump_of: tuple[str, ...] = ()
    #: in doc §4 (``False``: added by the registry for a §5 metric; see MODULE.md)
    in_doc: bool = True
    #: the dimensions it may be summed over (F4); a non-summable component sums over none
    sums_across: frozenset[Dim] = ALL_DIMS


def _c(
    id: str,
    unit: Unit,
    description: str,
    dataset: str,
    basis: OrderBasis,
    fld: str | None = None,
    *,
    summable: bool = True,
    in_doc: bool = True,
    sums_across: frozenset[Dim] | None = None,
) -> ComponentDef:
    if sums_across is None:
        sums_across = ALL_DIMS if summable else frozenset()
    return ComponentDef(
        id=id,
        unit=unit,
        description=description,
        sources=MappingProxyType({Platform.shopee: SourceSpec(dataset, basis, fld)}),
        summable=summable,
        in_doc=in_doc,
        sums_across=sums_across,
    )


V, N = Unit.vnd, Unit.items

#: TikTok reports only the seller-funded discount lump, not promo / voucher / combo apart.
_OFFER_LUMP = ComponentDef(
    id="offer_seller_total",
    unit=V,
    description="seller-funded discount lump (platform gives no promo / voucher / combo split)",
    sources=MappingProxyType(
        {Platform.tiktok: SourceSpec("order_lines", _C, "seller_discount", "lump")}
    ),
    lump_of=("offer_promo", "offer_voucher", "offer_combo"),
    in_doc=False,
)

_ALL = (
    # platform shop totals (T8)
    _c("gmv", V, "platform-reported shop GMV", "shop_overview", _C, "gmv"),
    _c(
        "orders",
        N,
        "platform-reported orders (a product's: Shopee's product report)",
        "shop_overview",
        _C,
        "orders",
        sums_across=ORDER_DIMS,
    ),
    _c("units", N, "platform-reported units sold", "shop_overview", _C, "units"),
    # order lines, confirmed, GMT+7 day
    _c("line_gmv", V, "GMV of confirmed order lines", "order_lines", _C, "gmv"),
    _c(
        "line_orders",
        N,
        "distinct confirmed orders in the lines",
        "order_lines",
        _C,
        "order_id",
        sums_across=ORDER_DIMS,
    ),
    _c("line_units", N, "units in confirmed order lines", "order_lines", _C, "qty"),
    _c(
        "net_revenue",
        V,
        "buyer paid: deal×qty − seller voucher − combo − output VAT; 0 for an accepted refund",
        "order_lines",
        _C,
        "buyer_paid",
    ),
    _c(
        "net_revenue_known",
        V,
        "net_revenue of the known-cost orders (the profit base)",
        "order_lines",
        _K,
        "buyer_paid_known",
        in_doc=False,
    ),
    _c("cogs", V, "cost of goods of the known-cost lines", "order_lines", _K, "cogs"),
    _c("cogs_known_gmv", V, "line GMV whose cost is known", "order_lines", _C, "gmv"),
    _c("packaging", V, "packaging (no rule: 0, flagged)", "shop_rules", _K, "packaging"),
    _c("fees", V, "platform fees (actual, else formula)", "order_income", _C, "fees"),
    _c("shipping_net", V, "shipping paid by the seller, net", "order_income", _C, "shipping"),
    _c("ads_spend", V, "ads spend, one resolver (ads days)", "ads_report", _N, "expense"),
    _c(
        "ads_spend_product",
        V,
        "a product's ad cost: the campaigns that advertise it, from the ads report by product",
        "ads_report_by_product",
        _N,
        "expense",
    ),
    _c("ads_gmv_platform", V, "ads GMV, broad, placed", "ads_report", OrderBasis.placed, "gmv"),
    _c(
        "ads_gmv_direct",
        V,
        "ads GMV, direct",
        "ads_report",
        OrderBasis.placed,
        "direct_gmv",
        in_doc=False,
    ),
    _c(
        "ads_gmv_confirmed",
        V,
        "ads-attributed confirmed GMV (overlay / confirmed share)",
        "traffic_overview",
        _C,
        "ads_overlay.gmv",
        in_doc=False,
    ),
    _c(
        "ads_views",
        N,
        "ads views (days with both counts)",
        "traffic_overview",
        _N,
        "ads_views",
        in_doc=False,
    ),
    _c(
        "ads_clicks",
        N,
        "ads clicks (days with both counts)",
        "traffic_overview",
        _N,
        "ads_clicks",
        in_doc=False,
    ),
    _c(
        "ads_orders",
        N,
        "ads orders (days with both counts)",
        "traffic_overview",
        _C,
        "ads_orders",
        in_doc=False,
        sums_across=ORDER_DIMS | {Dim.campaign},
    ),
    _c(
        "affiliate_commission",
        V,
        "THE AFF cost (A1, decision #55 Q2): the commission of the affiliate lines in the profit "
        "basis (delivered / settled, every cost known), ``shopee_profit.ladder.affiliate_cost``; "
        "the AFF row, Lợi nhuận ròng, Chi phí marketing, Tổng chi phí and the channel split",
        "order_lines",
        _K,
        "commission",
    ),
    _c(
        "affiliate_gmv",
        V,
        "GMV of the affiliate-flagged confirmed sale lines (A7 source: the order-line flag the "
        "conversion report sets; the traffic report's TTLK is its own funnel figure, never added)",
        "order_lines",
        _C,
        "gmv",
        in_doc=False,
    ),
    _c(
        "offer_promo",
        V,
        "seller promotion on non-cancelled confirmed lines",
        "order_lines",
        _C,
        "promo",
    ),
    _c("offer_voucher", V, "seller voucher", "order_lines", _C, "seller_voucher"),
    _c("offer_combo", V, "combo discount", "order_lines", _C, "combo"),
    _c(
        "other_marketing",
        V,
        "other marketing costs (shop rules)",
        "shop_rules",
        _N,
        "other_marketing_costs",
    ),
    _c("views", N, "product views (per source)", "traffic_overview", _N, "views"),
    _c("clicks", N, "product clicks (per source)", "traffic_overview", _N, "product_clicks"),
    _c("samples_cost", V, "KOL sample cost", "kol_samples", _N, "sample_cost"),
    _c(
        "stock_units",
        N,
        "stock on hand on the anchor day (sums over products, not over days)",
        "stock_history",
        _N,
        "stock",
        sums_across=frozenset({Dim.item}),
    ),
    _c("kol_gmv", V, "GMV of a KOL's orders", "affiliate_lines", _C, "gmv", in_doc=False),
    _c(
        "kol_commission",
        V,
        "commission paid to a KOL",
        "affiliate_lines",
        _C,
        "commission",
        in_doc=False,
    ),
    _c(
        "kol_net",
        V,
        "net profit of a KOL's orders after commission",
        "affiliate_lines",
        _K,
        "net_profit",
        in_doc=False,
    ),
    _c("card_delta_gmv", V, "a card's measured ΔGMV", "measurement", _C, "delta_gmv", in_doc=False),
    _c("card_cost", V, "a card's cost", "measurement", _N, "cost", in_doc=False),
    _c(
        "window_days",
        Unit.days,
        "days in the window",
        "derived",
        _N,
        None,
        in_doc=False,
        sums_across=frozenset(),
    ),
    _c(
        "affiliate_commission_known",
        V,
        "A2: the AFF cost of the covered orders = affiliate_commission (A1: THE AFF cost is "
        "already the covered lines'), stored beside it so a window compares like with like",
        "order_lines",
        _K,
        "commission",
        in_doc=False,
    ),
    _c(
        "ads_spend_known",
        V,
        "A2 (registry KNOWN_SHARE_RULE): a scope-day's ads spend x min(1, cogs_known_gmv / gmv); "
        "a day with ad spend and no sale keeps the whole spend",
        "ads_report_by_product",
        _K,
        "expense",
        in_doc=False,
    ),
    _c(
        "ads_gmv",
        V,
        "a product-day's ads-by-product GMV the channel split uses (direct sales, else broad), "
        "de-overlapped (A6, ADS_PERIOD_RULE)",
        "ads_report_by_product",
        OrderBasis.placed,
        "direct_gmv",
        in_doc=False,
    ),
    _c(
        "capped_gmv",
        V,
        "A7: what a channel's source said beyond the cap of the channel partition (recorded, "
        "never added to the channel)",
        "derived",
        _N,
        None,
        in_doc=False,
    ),
    _c(
        "daily_budget",
        V,
        "a campaign's daily budget that day (Connector ads_campaign_daily); budget-days add up",
        "ads_campaign_daily",
        _N,
        "daily_budget",
        in_doc=False,
        sums_across=frozenset({Dim.day, Dim.campaign}),
    ),
    _c(
        "contribution_products",
        V,
        "a campaign-day: the contribution (before ads) of the products it advertises",
        "campaign_metrics_daily",
        _K,
        "contribution_products",
        in_doc=False,
        sums_across=frozenset({Dim.day}),
    ),
    # one unit at the selling price (margin_sale): per-unit values, never summed
    _c(
        "sale_revenue_after_vat",
        V,
        "one unit: selling price after VAT",
        "catalog",
        _N,
        "price",
        summable=False,
        in_doc=False,
    ),
    _c(
        "sale_fees",
        V,
        "one unit: platform fees",
        "fee_table",
        _N,
        None,
        summable=False,
        in_doc=False,
    ),
    _c(
        "sale_cogs",
        V,
        "one unit: cost of goods",
        "catalog",
        _N,
        "cost",
        summable=False,
        in_doc=False,
    ),
    _c(
        "sale_packaging",
        V,
        "one unit: packaging",
        "shop_rules",
        _N,
        "packaging",
        summable=False,
        in_doc=False,
    ),
)

COMPONENTS: Mapping[str, ComponentDef] = MappingProxyType({c.id: c for c in (*_ALL, _OFFER_LUMP)})


def check_sum(component_id: str, dims: Iterable[Dim | str]) -> None:
    """Refuse a sum of ``component_id``'s stored rows over ``dims`` the registry does not allow
    (``sums_across``): raises :class:`InvalidSum`. The read function (Track QUERY) calls it for
    every component it adds up, so "Σ product đơn = shop đơn" can never be computed."""
    asked = frozenset(Dim(d) for d in dims)
    refused = asked - COMPONENTS[component_id].sums_across
    if refused:
        raise InvalidSum(component_id, refused)


#: A2 (#71): ``profit`` deducts the covered orders' ads / AFF cost. A caller that hands
#: components without the known part (a window ladder already built on the covered lines) is
#: read through its plain cost; the stored rows carry both. Absent key only: an explicit None
#: stays None (missing is not zero).
KNOWN_FALLBACK: Mapping[str, str] = MappingProxyType(
    {"ads_spend_known": "ads_spend", "affiliate_commission_known": "affiliate_commission"}
)

#: a platform report's total row beside its breakdown rows (e.g. ``traffic_overview`` stream
#: ``affiliate``: ``all`` = ``aff_live`` + ``aff_video``)
TOTAL_SEGMENT = "all"


class InvalidSegmentSum(ValueError):
    """A sum over a report's total segment AND its parts (it would count the parts twice)."""


def check_segments(segments: Iterable[str]) -> None:
    """Refuse adding a report's total segment to its own parts (:class:`InvalidSegmentSum`)."""
    seen = set(segments)
    if TOTAL_SEGMENT in seen and len(seen) > 1:
        parts = ", ".join(sorted(seen - {TOTAL_SEGMENT}))
        raise InvalidSegmentSum(f"'{TOTAL_SEGMENT}' already holds {parts}")


def one_segment_basis(rows: Iterable[T], segment: Callable[[T], str]) -> list[T]:
    """The rows of one scope (one day, one stream) on ONE basis: the total row when the report
    posted it, else its parts; never both."""
    rows = list(rows)
    total = [r for r in rows if segment(r) == TOTAL_SEGMENT]
    picked = total or rows
    check_segments(segment(r) for r in picked)
    return picked


def can_sum(component_id: str, dims: Iterable[Dim | str]) -> bool:
    """:func:`check_sum` as a test."""
    try:
        check_sum(component_id, dims)
    except InvalidSum:
        return False
    return True


def component_available(platform: Platform, component_id: str) -> bool:
    """Does ``platform`` have a source for this component? (No source: "—", never 0.)"""
    return platform in COMPONENTS[component_id].sources


def resolve_components(platform: Platform, components: Components) -> Components:
    """The components to hand ``evaluate`` for ``platform``: a lump replaces the parts it stands in
    for when the platform has none of them (``cost_offers`` = ``offer_seller_total`` on TikTok).

    The lump is carried in the first part and the others are 0, so their sum is the lump; a
    missing lump leaves the parts missing (``None``). Nothing changes on a platform that has the
    parts (Shopee).
    """
    out = dict(components)
    for lump in COMPONENTS.values():
        if not lump.lump_of or not component_available(platform, lump.id):
            continue
        if any(component_available(platform, part) for part in lump.lump_of):
            continue
        total = components.get(lump.id)
        first, *rest = lump.lump_of
        out[first] = total
        for part in rest:
            out[part] = None if total is None else Decimal(0)
    return out


def gate_source(platform: Platform, source: str, components: Components) -> Components:
    """One traffic source's components: all ``None`` when the platform has no such source.

    ``evaluate`` over the result gives ``None`` (rendered "—"), never 0.
    """
    if source_available(platform, source):
        return components
    return {cid: None for cid in components}
