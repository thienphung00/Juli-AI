"""The metric registry: one id, one formula, one rounding rule per number Juli shows.

Design: ``docs/architecture/metric-registry.md`` (draft 2, owner decisions §11). A change to a
formula here is a change to every screen, export and agent tool that shows the metric, so it
bumps :data:`DERIVATION_VERSION`.

Formulas are data, not Python: an expression is either a bare id (a component of
:mod:`.components` when one exists by that id, else another metric) or a tuple whose first
element is an operator:

==============  ==================================================================
``("sum", *e)``     Σ of the operands
``("sub", a, *b)``  a − Σ b
``("mul", a, b)``   a × b
``("div", a, b)``   a ÷ b; ``None`` when b is 0 or ``None``
``("min", a, b)``   the smaller operand
``("clamp0", a)``   max(a, 0)
``("const", "n")``  a decimal constant (string, so it stays exact)
``("param", name)`` a shop rule with a registry default (:data:`PARAMS`)
``("date_offset", a)``  ``as_of`` + ⌊a⌋ days (a date, for ``runs_out_on``)
``("helper", name)``    not a formula: a named pure helper in :mod:`.compute` computes it
==============  ==================================================================

Every operand that is ``None`` makes the result ``None`` (missing is not zero, rule 3).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

#: 2026-11-25.1 (batch-1124-c-data, decisions #62-#66): components carry ``sums_across`` (F4);
#: ``affiliate_commission`` is the one AFF basis (A1); the ads-by-product period rule (A6);
#: ``margin_before_marketing`` names Biên đóng góp (A9); cost shares ÷ net_revenue_known (L3);
#: ``profit`` deducts the covered-order ads / AFF cost (A2, #71).
#: Stored rows of an older version are
#: rebuilt in the background (``materialize.rebuild_outdated``).
DERIVATION_VERSION = "2026-11-25.1"

#: an expression: a bare id, or ``(operator, *operands)``
Expr = str | tuple[Any, ...]

OPERATORS = frozenset(
    {"sum", "sub", "mul", "div", "min", "clamp0", "const", "param", "date_offset", "helper"}
)
#: operators that keep a formula a sum of summable parts
LINEAR_OPERATORS = frozenset({"sum", "sub"})


class Unit(StrEnum):
    vnd = "vnd"
    items = "count"
    ratio = "ratio"
    pct_points = "pct_points"
    days = "days"
    x = "x"
    date = "date"
    status = "status"


class Rounding(StrEnum):
    """Rules of ``services/shopee_profit/money.py``: đồng half up, % 0.1, x 0.1."""

    dong = "dong"
    whole = "whole"
    units_ceil = "units_ceil"
    one_decimal = "one_decimal"
    pct_0_1 = "pct_0_1"
    x_0_1 = "x_0_1"
    ratio_0_001 = "ratio_0_001"
    days_floor = "days_floor"
    none = "none"


class Window(StrEnum):
    #: the last complete day of the platform's shop totals, and the days before it
    anchor_day = "anchor_day"
    #: the same length before the window
    previous = "previous"
    #: the calendar month ("vs tháng trước")
    month = "month"


class Comparison(StrEnum):
    """What every KPI is compared with (§5 Comparisons); not metrics."""

    prev = "prev"
    month_prev = "month_prev"
    target = "target"


class Level(StrEnum):
    shop = "shop"
    product = "product"
    sku = "sku"
    channel = "channel"
    kol = "kol"
    business = "business"


class Basis(StrEnum):
    platform = "platform"
    juli = "juli"
    estimated = "estimated"


class NoneRule(StrEnum):
    #: any missing operand makes the metric ``None``
    propagate = "propagate"
    #: as ``propagate``, and the value carries its cost coverage; ``partial`` below 100 %
    coverage = "coverage"


class OrderBasis(StrEnum):
    #: has a payment time (contract 14)
    confirmed = "confirmed"
    #: Shopee's placed-order basis (ads reports)
    placed = "placed"
    #: confirmed lines whose cost is known (``known_cost_profit``)
    known_cost = "known_cost"
    none = "none"


class Platform(StrEnum):
    shopee = "shopee"
    tiktok = "tiktok"


#: The platform's name as a screen says it (one place; page builders still write "Shopee")
PLATFORM_NAMES: Mapping[Platform, str] = MappingProxyType(
    {Platform.shopee: "Shopee", Platform.tiktok: "TikTok Shop"}
)


@dataclass(frozen=True)
class SourceSpec:
    """Where a platform's number comes from: the dataset, its order basis and its field."""

    dataset: str
    order_basis: OrderBasis
    field: str | None = None
    note: str = ""
    #: platforms that have this source at all; an unavailable source is "—" (``None``), never 0
    available_on: frozenset[Platform] = frozenset(Platform)


@dataclass(frozen=True)
class MetricDef:
    id: str
    label_vi: str
    unit: Unit
    rounding: Rounding
    formula: Expr
    components: tuple[str, ...]
    summable: bool
    window: Window
    levels: tuple[Level, ...]
    sources: Mapping[Platform, SourceSpec]
    basis: Basis
    none_rule: NoneRule = NoneRule.propagate
    #: the metric whose value is this metric's ``coverage`` (cost-dependent metrics)
    coverage: str | None = None
    note: str = ""


#: shop rules a formula may read, with the registry default (owner decision 3)
PARAMS: Mapping[str, Decimal] = MappingProxyType(
    {"lead_time_days": Decimal(7), "cover_days": Decimal(14)}
)


def refs(expr: Expr) -> Iterator[str]:
    """The ids an expression reads directly (components or metrics), in order."""
    if isinstance(expr, str):
        yield expr
        return
    op, *args = expr
    if op in ("const", "param", "helper"):
        return
    for arg in args:
        yield from refs(arg)


def ops(expr: Expr) -> Iterator[str]:
    """Every operator an expression uses."""
    if isinstance(expr, str):
        return
    op, *args = expr
    yield op
    if op in ("const", "param", "helper"):
        return
    for arg in args:
        yield from ops(arg)


# -- formula constructors (they only build tuples) -------------------------------------------


def s(*e: Expr) -> Expr:
    return ("sum", *e)


def sub(a: Expr, *b: Expr) -> Expr:
    return ("sub", a, *b)


def mul(a: Expr, b: Expr) -> Expr:
    return ("mul", a, b)


def div(a: Expr, b: Expr) -> Expr:
    return ("div", a, b)


def lo(a: Expr, b: Expr) -> Expr:
    return ("min", a, b)


def clamp0(a: Expr) -> Expr:
    return ("clamp0", a)


def const(n: str) -> Expr:
    return ("const", n)


def param(name: str) -> Expr:
    return ("param", name)


# -- sources ---------------------------------------------------------------------------------

_SC = OrderBasis.confirmed
DERIVED = SourceSpec("derived", OrderBasis.none, None, "computed from its components")


def _src(dataset: str, basis: OrderBasis, fld: str | None = None, note: str = "") -> SourceSpec:
    return SourceSpec(dataset, basis, fld, note)


_SHOPEE_ONLY = frozenset({Platform.shopee})
_BOTH = frozenset(Platform)

#: Traffic sources (the funnel splits of ``views`` / ``clicks`` / ``ads_*``). TikTok (W3 decision
#: #7, A-34): Thẻ sản phẩm, Video, LIVE (Organic) and Tiếp thị liên kết (TTLK) are the shop total;
#: Tab cửa hàng (``trang_shop``) is its own row, excluded from every sum (:func:`counts_in_total`),
#: with no orders / CTOR / AOV (:data:`SOURCE_METRIC_GAPS`). Quảng cáo is "—" until the Business
#: API scope exists (:data:`SOURCE_REASONS`). W3.1: ``chenh_lech_nguon`` is on TikTok too: the
#: day's total of a day without stored A-34 blocks, which has no source breakdown.
TRAFFIC_SOURCES: Mapping[str, SourceSpec] = MappingProxyType(
    {
        "the_san_pham_khac": SourceSpec(
            "traffic_overview", OrderBasis.none, "views", "product card", _BOTH
        ),
        "trang_shop": SourceSpec("traffic_overview", OrderBasis.none, "views", "shop page", _BOTH),
        "live": SourceSpec("traffic_overview", OrderBasis.none, "views", "LIVE", _BOTH),
        "video": SourceSpec("traffic_overview", OrderBasis.none, "views", "video", _BOTH),
        "lien_ket": SourceSpec("traffic_overview", OrderBasis.none, "views", "affiliate", _BOTH),
        "ads": SourceSpec("traffic_overview", OrderBasis.none, "ads_views", "ads", _SHOPEE_ONLY),
        "chenh_lech_nguon": SourceSpec(
            "traffic_overview", OrderBasis.none, "views", "source residual", _BOTH
        ),
    }
)

#: Reason codes of a "—" (a ``None`` value, never 0); the screens map a code to its words.
REASON_ADS_SCOPE_MISSING = "ads_scope_missing"
REASON_SOURCE_NOT_ON_PLATFORM = "source_not_on_platform"
#: W3.1 (decision #28 Q2): a source of a TikTok window whose days have no stored A-34 blocks
REASON_SOURCE_BREAKDOWN_MISSING = "source_breakdown_missing"
REASON_TAB_REPORTS_NO_ORDERS = "tab_reports_no_orders"

#: (platform, source) -> why the whole source is "—" there
SOURCE_REASONS: Mapping[tuple[Platform, str], str] = MappingProxyType(
    {
        (Platform.tiktok, "ads"): REASON_ADS_SCOPE_MISSING,
    }
)

#: (platform, source) -> metric ids that are "—" inside an available source, with the reason
SOURCE_METRIC_GAPS: Mapping[tuple[Platform, str], tuple[frozenset[str], str]] = MappingProxyType(
    {
        (Platform.tiktok, "trang_shop"): (
            frozenset({"orders", "ctor", "aov"}),
            REASON_TAB_REPORTS_NO_ORDERS,
        )
    }
)

#: (platform, source) -> the source is shown but never added into the shop total
SOURCES_OUTSIDE_TOTAL: frozenset[tuple[Platform, str]] = frozenset(
    {(Platform.tiktok, "trang_shop")}
)


def source_available(platform: Platform, source: str) -> bool:
    """Is ``source`` a traffic split on ``platform``? An unknown source raises ``KeyError``."""
    return platform in TRAFFIC_SOURCES[source].available_on


def counts_in_total(platform: Platform, source: str) -> bool:
    """Is ``source`` added into ``platform``'s shop total? Tab cửa hàng on TikTok is not."""
    return source_available(platform, source) and (platform, source) not in SOURCES_OUTSIDE_TOTAL


def source_reason(platform: Platform, source: str) -> str | None:
    """The reason code when the whole source is "—" on ``platform``, else ``None``."""
    if source_available(platform, source):
        return None
    return SOURCE_REASONS.get((platform, source), REASON_SOURCE_NOT_ON_PLATFORM)


def metric_reason(platform: Platform, source: str, metric_id: str) -> str | None:
    """The reason code when ``metric_id`` is "—" for ``source`` on ``platform``, else ``None``
    (the value is then whatever the data says, possibly missing for a data reason)."""
    whole = source_reason(platform, source)
    if whole is not None:
        return whole
    gap = SOURCE_METRIC_GAPS.get((platform, source))
    return gap[1] if gap is not None and metric_id in gap[0] else None


SHOP_LEVELS = (Level.shop, Level.product, Level.sku)
SHOP_PRODUCT = (Level.shop, Level.product)
CHANNEL = (Level.channel,)


@dataclass
class _Builder:
    defs: dict[str, MetricDef] = field(default_factory=dict)

    def add(
        self,
        id: str,
        label_vi: str,
        unit: Unit,
        rounding: Rounding,
        formula: Expr,
        *,
        summable: bool,
        levels: tuple[Level, ...] = SHOP_LEVELS,
        shopee: SourceSpec = DERIVED,
        basis: Basis = Basis.juli,
        known: bool = False,
        note: str = "",
    ) -> None:
        """``known``: a cost-dependent metric (on known-cost orders, carries coverage)."""
        if id in self.defs:
            raise ValueError(f"duplicate metric id {id}")
        self.defs[id] = MetricDef(
            id=id,
            label_vi=label_vi,
            unit=unit,
            rounding=rounding,
            formula=formula,
            components=tuple(dict.fromkeys(refs(formula))),
            summable=summable,
            window=Window.anchor_day,
            levels=levels,
            sources=MappingProxyType({Platform.shopee: shopee}),
            basis=basis,
            none_rule=NoneRule.coverage if known else NoneRule.propagate,
            coverage="cost_coverage" if known else None,
            note=note,
        )


def _build() -> dict[str, MetricDef]:
    b = _Builder()
    V, C, PP, X, R = Unit.vnd, Unit.items, Unit.pct_points, Unit.x, Unit.ratio
    D, P1, X1 = Rounding.dong, Rounding.pct_0_1, Rounding.x_0_1

    # Volume (platform-reported headline, T8)
    b.add(
        "gmv",
        "GMV",
        V,
        D,
        "gmv",
        summable=True,
        basis=Basis.platform,
        shopee=_src("shop_overview", _SC, "gmv", "Seller Centre shop totals"),
    )
    b.add(
        "orders",
        "Đơn hàng",
        C,
        Rounding.whole,
        "orders",
        summable=True,
        basis=Basis.platform,
        shopee=_src("shop_overview", _SC, "orders"),
    )
    b.add(
        "units",
        "Sản phẩm bán",
        C,
        Rounding.whole,
        "units",
        summable=True,
        basis=Basis.platform,
        shopee=_src("shop_overview", _SC, "units"),
    )
    b.add("aov", "AOV", V, D, div("gmv", "orders"), summable=False, basis=Basis.platform)
    b.add(
        "net_revenue",
        "Doanh thu thực",
        V,
        D,
        "net_revenue",
        summable=True,
        shopee=_src("order_lines", _SC, "buyer_paid", "deal×qty − seller voucher − combo − VAT"),
    )

    # Profit ladder (decision #44): Doanh thu thực -> Lợi nhuận gộp -> Lợi nhuận đóng góp (the card
    # basis, before ads and affiliate) -> Lợi nhuận ròng; three margins, all ÷ doanh thu thực
    b.add(
        "cost_coverage",
        "Độ phủ giá vốn",
        R,
        Rounding.ratio_0_001,
        div("cogs_known_gmv", "line_gmv"),
        summable=False,
        shopee=_src("order_lines", _SC, "cogs_coverage", "known-cost GMV ÷ line GMV"),
    )
    b.add(
        "gross_profit",
        "Lợi nhuận gộp",
        V,
        D,
        sub("net_revenue_known", "cogs", "packaging"),
        summable=True,
        known=True,
    )
    b.add(
        "contribution",
        "Lợi nhuận đóng góp",
        V,
        D,
        sub("gross_profit", "fees", "shipping_net"),
        summable=True,
        known=True,
        note="before ads, affiliate and other marketing: the card basis (#42 / #44)",
    )
    b.add(
        "profit",
        "Lợi nhuận ròng",
        V,
        D,
        # A2 (#71): like with like: the ads and AFF cost of the same covered orders the
        # contribution is counted on (KNOWN_SHARE_RULE)
        sub("contribution", "ads_spend_known", "affiliate_commission_known", "other_marketing"),
        summable=True,
        known=True,
        shopee=_src(
            "order_lines",
            OrderBasis.known_cost,
            "known_cost_profit",
            "shared.shop_profit_of; ads and other marketing are shop-level",
        ),
    )
    b.add(
        "margin_gross",
        "Biên gộp",
        PP,
        P1,
        div("gross_profit", "net_revenue_known"),
        summable=False,
        known=True,
    )
    b.add(
        "margin_contribution",
        "Biên đóng góp",
        PP,
        P1,
        div("contribution", "net_revenue_known"),
        summable=False,
        known=True,
        note="the margin before marketing (A9, #65/#66): every product-level layer shows it; "
        "Ưu đãi is kept (it is in the order lines), ads and AFF are not deducted",
    )
    b.add(
        "margin",
        "Biên lợi nhuận",
        PP,
        P1,
        div("profit", "net_revenue_known"),
        summable=False,
        known=True,
    )
    b.add(
        "margin_sale",
        "Biên ở giá bán",
        PP,
        P1,
        div(
            sub("sale_revenue_after_vat", "sale_fees", "sale_cogs", "sale_packaging"),
            "sale_revenue_after_vat",
        ),
        summable=False,
        levels=(Level.product, Level.sku),
        shopee=_src("catalog", OrderBasis.none, "price_margin", "one unit at the selling price"),
    )
    b.add(
        "contribution_rate",
        "Tỷ lệ đóng góp",
        PP,
        P1,
        div("contribution", "net_revenue_known"),
        summable=False,
        note="margin_contribution as a fraction: the rate channel profit uses (§6)",
    )

    # Costs (ask 2)
    cost_parts = {
        "cost_cogs": ("Giá vốn", "cogs", _src("order_lines", OrderBasis.known_cost, "cogs")),
        "cost_packaging": (
            "Đóng gói",
            "packaging",
            _src(
                "shop_rules",
                OrderBasis.known_cost,
                "packaging",
                "no rule = 0, flagged 'chưa nhập chi phí đóng gói'",
            ),
        ),
        "cost_fees": (
            "Phí sàn",
            "fees",
            _src("order_income", _SC, "fees", "actual fee wins, else fee_table formula"),
        ),
        "cost_shipping": ("Vận chuyển", "shipping_net", _src("order_income", _SC, "shipping_net")),
        "cost_ads": (
            "Quảng cáo",
            "ads_spend",
            _src("ads_report", OrderBasis.none, "expense", "one resolver: ads days"),
        ),
        "cost_affiliate": (
            "Hoa hồng tiếp thị liên kết",
            "affiliate_commission",
            _src(
                "affiliate_lines",
                _SC,
                "commission",
                "commission of the affiliate lines in the profit basis (delivered / settled, "
                "every cost known): one sum, channel_split.affiliate_cost",
            ),
        ),
        "cost_offer_promo": (
            "Khuyến mãi",
            "offer_promo",
            _src("order_lines", _SC, "promo", "non-cancelled confirmed lines"),
        ),
        "cost_offer_voucher": (
            "Voucher",
            "offer_voucher",
            _src("order_lines", _SC, "seller_voucher"),
        ),
        "cost_offer_combo": ("Combo", "offer_combo", _src("order_lines", _SC, "combo")),
        "cost_other": (
            "Chi phí marketing khác",
            "other_marketing",
            _src("shop_rules", OrderBasis.none, "other_marketing_costs"),
        ),
    }
    for cid, (label, comp, src) in cost_parts.items():
        b.add(cid, label, V, D, comp, summable=True, shopee=src)
    b.add(
        "cost_ads_product",
        "Chi phí quảng cáo của sản phẩm",
        V,
        D,
        "ads_spend_product",
        summable=True,
        levels=(Level.product,),
        shopee=_src(
            "ads_report_by_product",
            OrderBasis.none,
            "expense",
            "campaign spend per day x the product's share in the ads report by product "
            "(shopee_analytics.product_ads); no basis = None, never 0",
        ),
    )
    b.add(
        "cost_offers",
        "Ưu đãi",
        V,
        D,
        s("cost_offer_promo", "cost_offer_voucher", "cost_offer_combo"),
        summable=True,
    )
    b.add(
        "cost_marketing",
        "Chi phí marketing",
        V,
        D,
        s("cost_ads", "cost_affiliate", "cost_offers"),
        summable=True,
    )
    b.add(
        "cost_total",
        "Tổng chi phí",
        V,
        D,
        s(
            "cost_cogs",
            "cost_packaging",
            "cost_fees",
            "cost_shipping",
            "cost_ads",
            "cost_affiliate",
            "cost_offers",
            "cost_other",
        ),
        summable=True,
    )
    for cid in (
        "cost_cogs",
        "cost_packaging",
        "cost_fees",
        "cost_shipping",
        "cost_ads",
        "cost_affiliate",
        "cost_offers",
        "cost_other",
        "cost_total",
        "cost_marketing",
    ):
        label = b.defs[cid].label_vi
        b.add(
            f"{cid}_pct",
            f"{label} (% doanh thu thực)",
            PP,
            P1,
            # L3 (contract §6): every share of doanh thu thực divides by the covered base
            div(cid, "net_revenue_known"),
            summable=False,
        )

    # Returns on cost
    b.add(
        "roi",
        "ROI",
        X,
        X1,
        div("profit", "cost_total"),
        summable=False,
        levels=(Level.shop, Level.product, Level.channel),
        known=True,
    )
    b.add(
        "roas",
        "ROAS",
        X,
        X1,
        div("ads_gmv_platform", "cost_ads"),
        summable=False,
        basis=Basis.platform,
        shopee=_src("ads_report", OrderBasis.placed, "gmv", "broad, placed — labelled"),
    )
    b.add(
        "roas_direct",
        "ROAS trực tiếp",
        X,
        X1,
        div("ads_gmv_direct", "cost_ads"),
        summable=False,
        basis=Basis.platform,
        shopee=_src("ads_report", OrderBasis.placed, "direct_gmv"),
    )
    b.add(
        "roas_break_even",
        "ROAS hoà vốn",
        X,
        X1,
        div("net_revenue_known", "contribution"),
        summable=False,
        known=True,
    )
    b.add(
        "roi_kol",
        "ROI KOL",
        X,
        X1,
        div(sub("kol_net", "samples_cost"), s("kol_commission", "samples_cost")),
        summable=False,
        levels=(Level.kol,),
    )
    b.add(
        "card_return",
        "ΔGMV / chi phí",
        X,
        X1,
        div("card_delta_gmv", "card_cost"),
        summable=False,
        levels=SHOP_PRODUCT,
        basis=Basis.estimated,
        shopee=_src("measurement", OrderBasis.confirmed, "delta_gmv", "a card's ΔGMV"),
    )

    # Funnel
    b.add(
        "views",
        "Lượt xem",
        C,
        Rounding.whole,
        "views",
        summable=True,
        basis=Basis.platform,
        shopee=_src("traffic_overview", OrderBasis.none, "views", "per source"),
    )
    b.add(
        "clicks",
        "Lượt click",
        C,
        Rounding.whole,
        "clicks",
        summable=True,
        basis=Basis.platform,
        shopee=_src("traffic_overview", OrderBasis.none, "product_clicks", "per source"),
    )
    b.add("ctr", "CTR", PP, P1, div("clicks", "views"), summable=False, basis=Basis.platform)
    b.add("ctor", "CTOR", PP, P1, div("orders", "clicks"), summable=False, basis=Basis.platform)
    b.add(
        "ctr_ads",
        "CTR quảng cáo",
        PP,
        P1,
        div("ads_clicks", "ads_views"),
        summable=False,
        basis=Basis.platform,
        note="days with both counts (#2294)",
    )
    b.add(
        "ctor_ads",
        "CTOR quảng cáo",
        PP,
        P1,
        div("ads_orders", "ads_clicks"),
        summable=False,
        basis=Basis.platform,
        note="days with both counts (#2294)",
    )

    # Channels (§6): affiliate first, ads capped at gmv − affiliate, organic the rest
    b.add(
        "channel_gmv_affiliate",
        "GMV Tiếp thị liên kết",
        V,
        D,
        lo("affiliate_gmv", "gmv"),
        summable=False,
        levels=CHANNEL,
        basis=Basis.estimated,
        note="a partition of the window, so not summed over days",
    )
    b.add(
        "channel_gmv_ads",
        "GMV Quảng cáo",
        V,
        D,
        lo("ads_gmv_confirmed", clamp0(sub("gmv", "channel_gmv_affiliate"))),
        summable=False,
        levels=CHANNEL,
        basis=Basis.estimated,
    )
    b.add(
        "channel_gmv_organic",
        "GMV Organic",
        V,
        D,
        clamp0(sub("gmv", "channel_gmv_affiliate", "channel_gmv_ads")),
        summable=False,
        levels=CHANNEL,
        basis=Basis.estimated,
    )
    own_cost = {"organic": const("0"), "ads": "ads_spend", "affiliate": "affiliate_commission"}
    label_of = {"organic": "Organic", "ads": "Quảng cáo", "affiliate": "Tiếp thị liên kết"}
    for ch in ("organic", "ads", "affiliate"):
        gmv_id = f"channel_gmv_{ch}"
        b.add(
            f"channel_share_{ch}",
            f"Tỷ trọng {label_of[ch]}",
            PP,
            P1,
            div(gmv_id, "gmv"),
            summable=False,
            levels=CHANNEL,
            basis=Basis.estimated,
        )
        b.add(
            f"channel_net_revenue_{ch}",
            f"Doanh thu thực {label_of[ch]}",
            V,
            D,
            mul("net_revenue_known", div(gmv_id, "gmv")),
            summable=False,
            levels=CHANNEL,
            basis=Basis.estimated,
        )
        net = f"channel_net_revenue_{ch}"
        profit_expr = mul(net, "contribution_rate")
        if ch != "organic":
            profit_expr = sub(profit_expr, own_cost[ch])
        b.add(
            f"channel_profit_{ch}",
            f"Lợi nhuận {label_of[ch]}",
            V,
            D,
            profit_expr,
            summable=False,
            levels=CHANNEL,
            basis=Basis.estimated,
        )
        b.add(
            f"channel_cost_pct_{ch}",
            f"Chi phí {label_of[ch]} (%)",
            PP,
            P1,
            div(own_cost[ch], net),
            summable=False,
            levels=CHANNEL,
            basis=Basis.estimated,
        )

    # Stock (the stock-alert forecast is the only forecast)
    stock_src = _src("stock_history", OrderBasis.none, "stock")
    b.add(
        "units_per_day",
        "Bán / ngày",
        C,
        Rounding.one_decimal,
        div("units", "window_days"),
        summable=False,
        levels=(Level.product, Level.sku),
    )
    b.add(
        "days_left",
        "Còn bán được (ngày)",
        Unit.days,
        Rounding.days_floor,
        div("stock_units", "units_per_day"),
        summable=False,
        levels=(Level.product, Level.sku),
        basis=Basis.estimated,
        shopee=stock_src,
    )
    b.add(
        "runs_out_on",
        "Hết hàng khoảng",
        Unit.date,
        Rounding.none,
        ("date_offset", "days_left"),
        summable=False,
        levels=(Level.product, Level.sku),
        basis=Basis.estimated,
    )
    b.add(
        "restock_units",
        "Cần nhập thêm",
        C,
        Rounding.units_ceil,
        clamp0(
            sub(
                mul("units_per_day", s(param("lead_time_days"), param("cover_days"))), "stock_units"
            )
        ),
        summable=False,
        levels=(Level.product, Level.sku),
        basis=Basis.estimated,
        shopee=stock_src,
    )

    # KOL
    kol_src = _src("affiliate_lines", _SC, None, "KOL conversion report join")
    b.add("kol_gmv", "GMV KOL", V, D, "kol_gmv", summable=True, levels=(Level.kol,), shopee=kol_src)
    b.add(
        "kol_share",
        "Tỷ trọng KOL",
        PP,
        P1,
        div("kol_gmv", "gmv"),
        summable=False,
        levels=(Level.kol,),
        note="of the shop GMV (ask 8)",
    )
    b.add(
        "kol_commission",
        "Hoa hồng KOL",
        V,
        D,
        "kol_commission",
        summable=True,
        levels=(Level.kol,),
        shopee=kol_src,
    )
    b.add(
        "kol_net",
        "Lợi nhuận ròng KOL",
        V,
        D,
        "kol_net",
        summable=True,
        levels=(Level.kol,),
        shopee=kol_src,
    )
    b.add(
        "kol_status",
        "Hiệu quả KOL",
        Unit.status,
        Rounding.none,
        ("helper", "kol_status"),
        summable=False,
        levels=(Level.kol,),
        note="90 % interval of roi_kol from order-level profits: compute.kol_status",
    )
    return b.defs


METRICS: Mapping[str, MetricDef] = MappingProxyType(_build())

#: A9 (owner #65 / #66): the names a surface may use for one registry metric. Ads and AFF are
#: deducted only on Tổng quan and Kế hoạch (``profit``, ``margin``); every product-level layer
#: (product cards, Phân tích product level, Đề xuất cards, Chat per-product answers) shows the
#: margin before them, which IS Biên đóng góp -- an alias, never a second formula.
METRIC_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "margin_before_marketing": "margin_contribution",
        "contribution_before_marketing": "contribution",
    }
)


def metric_id(name: str) -> str:
    """The registry id behind ``name`` (an id, or an alias of :data:`METRIC_ALIASES`)."""
    return METRIC_ALIASES.get(name, name)


#: A6: how the ads report by product (``ads_campaign_period``) becomes days. Shopee posts one
#: campaign x product over overlapping windows (a single day, then a 3-day and a 9-day window
#: that run past the read). Per campaign x product, windows are taken shortest first; a window
#: gives each of its days not yet covered by a shorter one an equal share of what is left of it
#: (its total minus the days the shorter windows already gave, never below 0). Each day is
#: counted once; a window's days outside the asked window are dropped, never piled onto the days
#: inside. Spend keeps decision #39 (the Connector's campaign day x the product's share,
#: ``shopee_analytics.product_ads``). Code: ``metrics.allocation.deoverlap_periods``.
ADS_PERIOD_RULE = "shortest_first_remainder_spread"

#: A2 / contract §6: the ads cost of the covered orders of a scope-day (shop or product):
#: ``ads_spend_known = ads_spend x min(1, cogs_known_gmv / gmv)``; a day with ad spend and no sale
#: (gmv 0) keeps the whole spend (no order, no cost gap; decision #39). AFF needs no share:
#: ``affiliate_commission`` is already the covered lines' commission (A1), so
#: ``affiliate_commission_known`` equals it. Every margin divides by ``net_revenue_known`` (L3).
KNOWN_SHARE_RULE = "ads_spend_x_covered_gmv_share"
