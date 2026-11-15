"""Canonical components: the sums every metric formula is built from (doc §4).

A component is one platform-neutral quantity per platform, per day, per scope (shop, product,
SKU, channel, KOL). Components are sums, so a window's component is the sum of its days and a
shop's the sum of its products -- metrics are never summed, components are.

This module only declares them. Reading them from the layer-4 tables is a later step; until
then a caller hands :class:`Components` (id -> ``Decimal`` or ``None``) to
:func:`~juli_backend.services.metrics.compute.evaluate`. ``None`` means "no data", never 0.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from juli_backend.services.metrics.registry import (
    OrderBasis,
    Platform,
    SourceSpec,
    Unit,
    source_available,
)

#: one scope's components for one window: id -> value, ``None`` (or absent) = no data
Components = Mapping[str, Decimal | None]

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
) -> ComponentDef:
    return ComponentDef(
        id=id,
        unit=unit,
        description=description,
        sources=MappingProxyType({Platform.shopee: SourceSpec(dataset, basis, fld)}),
        summable=summable,
        in_doc=in_doc,
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
    _c("orders", N, "platform-reported orders", "shop_overview", _C, "orders"),
    _c("units", N, "platform-reported units sold", "shop_overview", _C, "units"),
    # order lines, confirmed, GMT+7 day
    _c("line_gmv", V, "GMV of confirmed order lines", "order_lines", _C, "gmv"),
    _c("line_orders", N, "distinct confirmed orders in the lines", "order_lines", _C, "order_id"),
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
    ),
    _c("affiliate_commission", V, "affiliate commission", "affiliate_lines", _C, "commission"),
    _c(
        "affiliate_gmv",
        V,
        "GMV of affiliate-attributed confirmed lines, scaled to shop totals",
        "affiliate_lines",
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
    _c("window_days", Unit.days, "days in the window", "derived", _N, None, in_doc=False),
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
