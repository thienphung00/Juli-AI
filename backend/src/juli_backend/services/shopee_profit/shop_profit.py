"""Product profit and SHOP profit (contract section 4) from line contributions + ads report.

- Line contribution = buyer_paid - fees - COGS - packaging - affiliate commission
  (:mod:`.order_profit`; fixed per-order fees already charged once per order).
- **Product profit** = sum of the product's line contribution - the product's ad spend taken
  from the ads report by product (``product_ad_spend``). The line-level ad split in
  :class:`~.order_profit.ProfitBreakdown` is only a display aid; :func:`pools_from_product_spend`
  builds pools from the report spend so that it reconciles, and ``line_ads_gap`` shows what
  is left (rounding, products with no ad-attributed line).
- **Shop profit** = sum of contribution - TOTAL ad spend of ALL campaigns (including campaigns
  with no revenue) - other shop marketing costs not on orders (e.g. game prizes).
  ``unattributed_ad_spend`` = total campaign spend - sum of product ad spend ("QC khong gan
  san pham / khong ra don"), so ``sum(product profit) - unattributed - other == shop profit``.
  A negative unattributed amount (products claim more than the campaigns cost) sets
  ``ad_spend_consistent`` False -- surfaced, not hidden.
- **Margin** = profit / buyer_paid everywhere. **Cost coverage** = share of buyer_paid whose
  lines have every cost input known (giá vốn, packaging, fees, commission). Below 100 %
  (contract 9) margin = (covered contribution - (ad spend of covered products + unattributed
  ad spend x covered share of buyer_paid) - other costs x covered share) / covered buyer_paid,
  shown as "tren X % doanh thu co gia von"; a product's report spend counts in proportion to its
  covered share (so a fully covered product counts whole, an uncovered one not at all).
  Shop ``profit`` in dong is ``None`` unless coverage is 100 %; the components
  (``profit_on_covered``, ``covered_ad_charge``, ``covered_margin_profit``) stay available.
  Nothing is extrapolated. With no covered revenue the margin is ``None``.
- Break-even ROAS = buyer_paid / contribution before ads (covered lines); ``None`` when the
  contribution is <= 0. Product checks compare it with ROAS TRUC TIEP (direct GMV / cost);
  broad ROAS (Doanh so incl. other products bought within 7 days) is exposed next to it and
  is what shop-level ads use. Both come from :class:`AdsFigures` per product / campaign.
- Orders that carry no fee and no profit (cancelled, undelivered, refund "not received") stay
  in GMV and order counts (confirmed views) but are outside buyer_paid, coverage and profit;
  an accepted "Hoan tien ngay" keeps its fee (revenue 0).
- Reconciliation: sum of order-line GMV (deal x qty) vs the export's GMV; a gap above 2 % is
  a data warning, never hidden.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div
from juli_backend.services.shopee_profit.order_profit import AdsPool, OrderLine, ProfitBreakdown

GMV_WARN_RATE = Decimal("0.02")

Pairs = Sequence[tuple[OrderLine, ProfitBreakdown]]


@dataclass(frozen=True)
class AdsFigures:
    """Shopee ads report figures (a product row of a group campaign, or a whole campaign).

    ``gmv`` = "Doanh so" (the advertised product AND other products bought within 7 days of the
    click); ``direct_gmv`` = "Doanh so truc tiep" (the advertised product only)."""

    spend: Decimal
    gmv: Decimal | None = None
    direct_gmv: Decimal | None = None

    @property
    def roas_broad(self) -> Decimal | None:
        return None if self.gmv is None else safe_div(self.gmv, self.spend)

    @property
    def roas_direct(self) -> Decimal | None:
        return None if self.direct_gmv is None else safe_div(self.direct_gmv, self.spend)


@dataclass(frozen=True)
class AdCampaign:
    campaign_id: str
    spend: Decimal
    revenue: Decimal | None = None  # broad; None = unknown; ZERO = a campaign with no revenue
    name: str = ""
    direct_revenue: Decimal | None = None

    @property
    def roas_broad(self) -> Decimal | None:
        return None if self.revenue is None else safe_div(self.revenue, self.spend)

    @property
    def roas_direct(self) -> Decimal | None:
        return None if self.direct_revenue is None else safe_div(self.direct_revenue, self.spend)


@dataclass(frozen=True)
class ProductProfit:
    product_id: str
    orders: int
    gmv: Decimal
    buyer_paid: Decimal
    buyer_paid_covered: Decimal
    contribution: Decimal  # covered lines, before ads
    ad_spend: Decimal  # from the ads report by product
    profit: Decimal  # contribution - ad_spend (partial when coverage < 100 %)
    line_ads_display: Decimal  # display aid: sum of the line-level ad split
    excluded_orders: int = 0  # cancelled / undelivered: in ``gmv`` only, outside the profit base
    ads: AdsFigures | None = None  # the report row, when given
    missing: dict[str, int] = field(default_factory=dict)  # reason -> uncovered lines

    @property
    def cost_coverage_rate(self) -> Decimal | None:
        return safe_div(self.buyer_paid_covered, self.buyer_paid)

    @property
    def cost_coverage_pct(self) -> Decimal | None:
        return pct_points(self.cost_coverage_rate)

    @property
    def is_partial(self) -> bool:
        return self.buyer_paid_covered < self.buyer_paid

    @property
    def margin_rate(self) -> Decimal | None:
        return safe_div(self.profit, self.buyer_paid_covered)

    @property
    def margin_pct(self) -> Decimal | None:
        return pct_points(self.margin_rate)

    @property
    def break_even_roas(self) -> Decimal | None:
        if self.contribution <= 0:
            return None
        return safe_div(self.buyer_paid_covered, self.contribution)

    @property
    def roas_broad(self) -> Decimal | None:
        return self.ads.roas_broad if self.ads else None

    @property
    def roas_direct(self) -> Decimal | None:
        return self.ads.roas_direct if self.ads else None

    @property
    def ads_below_break_even(self) -> bool | None:
        """Break-even check uses ROAS truc tiep (contract 10); None when either is unknown."""
        be, direct = self.break_even_roas, self.roas_direct
        return None if be is None or direct is None else direct < be

    @property
    def line_ads_gap(self) -> Decimal:
        return self.ad_spend - self.line_ads_display


@dataclass(frozen=True)
class GmvReconciliation:
    line_gmv: Decimal
    export_gmv: Decimal | None
    gap: Decimal | None  # line - export
    gap_rate: Decimal | None  # gap / export
    warn: bool  # |gap| > 2 % of export


@dataclass(frozen=True)
class ShopProfit:
    orders: int
    gmv: Decimal
    buyer_paid: Decimal
    buyer_paid_covered: Decimal
    contribution: Decimal  # covered lines, before ads
    total_ad_spend: Decimal  # all campaigns
    product_ad_spend: Decimal  # sum of the by-product spend
    unattributed_ad_spend: Decimal  # total - sum(product); includes zero-revenue campaigns
    zero_revenue_campaign_spend: Decimal  # informational subset of the above
    ad_spend_consistent: bool  # False when products claim more than the campaigns cost
    other_marketing_costs: Decimal
    profit: Decimal | None  # dong, ONLY at 100 % cost coverage (contract 9); else None
    profit_on_covered: Decimal  # component: contribution - total ads - other (partial if < 100 %)
    covered_ad_charge: Decimal  # ads charged to covered lines (see module doc)
    covered_margin_profit: Decimal | None  # margin numerator (contract 9); None if no coverage
    reconciliation: GmvReconciliation
    missing: dict[str, int]
    products: dict[str, ProductProfit]

    @property
    def cost_coverage_rate(self) -> Decimal | None:
        return safe_div(self.buyer_paid_covered, self.buyer_paid)

    @property
    def cost_coverage_pct(self) -> Decimal | None:
        return pct_points(self.cost_coverage_rate)

    @property
    def margin_is_partial(self) -> bool:
        return self.buyer_paid_covered < self.buyer_paid

    @property
    def margin_rate(self) -> Decimal | None:
        """Margin on the covered lines (never extrapolated): covered_margin_profit / covered
        buyer_paid. At 100 % coverage it is profit / buyer_paid."""
        if self.covered_margin_profit is None:
            return None
        return safe_div(self.covered_margin_profit, self.buyer_paid_covered)

    @property
    def margin_pct(self) -> Decimal | None:
        return pct_points(self.margin_rate)

    @property
    def break_even_roas(self) -> Decimal | None:
        if self.contribution <= 0:
            return None
        return safe_div(self.buyer_paid_covered, self.contribution)


def reconcile_gmv(pairs: Pairs, export_gmv: Decimal | None) -> GmvReconciliation:
    line_gmv = sum((ln.order_value for ln, _ in pairs), ZERO)
    if export_gmv is None:
        return GmvReconciliation(line_gmv, None, None, None, False)
    gap = line_gmv - export_gmv
    rate = safe_div(gap, export_gmv)
    return GmvReconciliation(line_gmv, export_gmv, gap, rate, abs(rate or ZERO) > GMV_WARN_RATE)


def pools_from_product_spend(
    lines: Iterable[OrderLine], product_ad_spend: Mapping[str, Decimal]
) -> dict[str, AdsPool]:
    """SKU ad pools whose cost is the ads-report spend of the product, spread over its SKUs
    by the list value of their ad-attributed lines (feeds the display-only line ad split)."""
    sku_rev: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    prod_rev: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for ln in lines:
        if ln.ad_attributed:
            sku_rev[(ln.product_id, ln.sku)] += ln.list_value
            prod_rev[ln.product_id] += ln.list_value
    pools: dict[str, AdsPool] = {}
    for (product, sku), rev in sku_rev.items():
        spend = product_ad_spend.get(product)
        if spend is None or prod_rev[product] <= 0:
            continue
        pools[sku] = AdsPool(spend * rev / prod_rev[product], rev)
    return pools


def _product_rows(pairs: Pairs) -> dict[str, list[tuple[OrderLine, ProfitBreakdown]]]:
    out: dict[str, list[tuple[OrderLine, ProfitBreakdown]]] = defaultdict(list)
    for ln, pb in pairs:
        out[ln.product_id].append((ln, pb))
    return out


def product_profits(
    pairs: Pairs,
    product_ad_spend: Mapping[str, Decimal],
    product_ads: Mapping[str, AdsFigures] | None = None,
) -> dict[str, ProductProfit]:
    """Per product: sum of contribution - its ad spend. Products that only appear in the ads
    report (no orders) are included with zero revenue."""
    rows = _product_rows(pairs)
    out: dict[str, ProductProfit] = {}
    for product in [*rows, *(p for p in product_ad_spend if p not in rows)]:
        all_items = rows.get(product, [])
        items = [(ln, pb) for ln, pb in all_items if pb.excluded_reason is None]
        spend = product_ad_spend.get(product, ZERO)
        covered = [(ln, pb) for ln, pb in items if pb.contribution is not None]
        contribution = sum((pb.contribution or ZERO for _, pb in covered), ZERO)
        missing: dict[str, int] = defaultdict(int)
        for _, pb in items:
            if pb.contribution is None:
                for m in pb.missing:
                    if m != "ads_allocation":
                        missing[m] += 1
        out[product] = ProductProfit(
            product_id=product,
            orders=len({ln.order_id for ln, _ in all_items}),
            gmv=sum((ln.order_value for ln, _ in all_items), ZERO),
            buyer_paid=sum((pb.revenue for _, pb in items), ZERO),
            buyer_paid_covered=sum((pb.revenue for _, pb in covered), ZERO),
            contribution=contribution,
            ad_spend=spend,
            profit=contribution - spend,
            line_ads_display=sum((pb.ads or ZERO for _, pb in items), ZERO),
            missing=dict(missing),
            excluded_orders=len({ln.order_id for ln, pb in all_items if pb.excluded_reason}),
            ads=(product_ads or {}).get(product),
        )
    return out


def shop_profit(
    pairs: Pairs,
    *,
    campaigns: Sequence[AdCampaign],
    product_ad_spend: Mapping[str, Decimal],
    other_marketing_costs: Decimal = ZERO,
    export_gmv: Decimal | None = None,
    product_ads: Mapping[str, AdsFigures] | None = None,
) -> ShopProfit:
    products = product_profits(pairs, product_ad_spend, product_ads)
    total_ads = sum((c.spend for c in campaigns), ZERO)
    by_product = sum(product_ad_spend.values(), ZERO)
    unattributed = total_ads - by_product
    contribution = sum((p.contribution for p in products.values()), ZERO)
    missing: dict[str, int] = defaultdict(int)
    for p in products.values():
        for k, v in p.missing.items():
            missing[k] += v
    paid = sum((q.buyer_paid for q in products.values()), ZERO)
    paid_covered = sum((q.buyer_paid_covered for q in products.values()), ZERO)
    share = safe_div(paid_covered, paid)
    complete = paid > 0 and paid_covered == paid
    covered_ads = ZERO
    margin_num: Decimal | None = None
    if share is not None and paid_covered > 0:
        for q in products.values():
            cs = safe_div(q.buyer_paid_covered, q.buyer_paid)
            if cs is not None:  # a product's report spend follows its covered share
                covered_ads += q.ad_spend * cs
        covered_ads += unattributed * share
        margin_num = contribution - covered_ads - other_marketing_costs * share
    on_covered = contribution - total_ads - other_marketing_costs
    return ShopProfit(
        orders=len({ln.order_id for ln, _ in pairs}),
        gmv=sum((ln.order_value for ln, _ in pairs), ZERO),
        buyer_paid=sum((p.buyer_paid for p in products.values()), ZERO),
        buyer_paid_covered=sum((p.buyer_paid_covered for p in products.values()), ZERO),
        contribution=contribution,
        total_ad_spend=total_ads,
        product_ad_spend=by_product,
        unattributed_ad_spend=unattributed,
        zero_revenue_campaign_spend=sum((c.spend for c in campaigns if c.revenue == 0), ZERO),
        ad_spend_consistent=unattributed >= 0,
        other_marketing_costs=other_marketing_costs,
        profit=on_covered if complete else None,
        profit_on_covered=on_covered,
        covered_ad_charge=covered_ads,
        covered_margin_profit=margin_num,
        reconciliation=reconcile_gmv(pairs, export_gmv),
        missing=dict(missing),
        products=products,
    )


def scope_margin_pct(profit: ShopProfit, item_ids: Sequence[str] = ()) -> Decimal | None:
    """ADR-122 d.12, one margin math on every screen (P99): the shop's margin for ``()``, else the
    products' :attr:`ProductProfit.margin_pct` math -- (covered contribution - the products' ad
    spend from the ads report) ÷ covered buyer_paid, summed over the products. Luồng sản phẩm,
    the builder's product list, its "hôm nay" and Kế hoạch all read this; ``None`` when no
    product of the scope has covered revenue."""
    items = tuple(dict.fromkeys(i for i in item_ids if i))
    if not items:
        return profit.margin_pct
    rows = [profit.products[i] for i in items if i in profit.products]
    if len(rows) == 1:
        return rows[0].margin_pct
    covered = sum((p.buyer_paid_covered for p in rows), ZERO)
    return pct_points(safe_div(sum((p.profit for p in rows), ZERO), covered))


NO_KNOWN_COST_LABEL = "chưa có đơn nào có đủ chi phí"


def _money(value: Decimal | None) -> int | float | None:
    """Whole đồng as int, otherwise 2 decimals (the analytics ``fmt.num`` shape)."""
    if value is None:
        return None
    if value == value.to_integral_value():
        return int(value)
    return float(value.quantize(Decimal("0.01")))


def _vn_pct(value: Decimal) -> str:
    return f"{value:.1f}".replace(".", ",")


#: how the ads not tied to a product are charged to the known-cost orders
ADS_SHARE_DAILY = "daily"  # by those orders' share of each day's buyer paid (daily spend known)
ADS_SHARE_WINDOW = "window"  # by their share of the window's buyer paid (no daily spend)


@dataclass(frozen=True)
class KnownCostProfit:
    """P100 B.5: THE shop profit -- the profit of the ORDERS whose costs are all known, with its
    coverage ("trên N đơn có chi phí, X % GMV"). Tổng quan, Sản phẩm, Phân tích and Kế hoạch all
    show this one figure (:func:`known_cost_profit`); nothing is scaled to the shop GMV.

    The bridge on Tổng quan adds up exactly: ``product_profit`` (known orders' contribution minus
    the ads charged to the products) - ``ads_unattributed_charged`` - ``other_marketing_charged``
    = ``profit``, each part a whole đồng."""

    profit: Decimal | None  # known orders' contribution - their ads share - their other costs
    margin_pct: Decimal | None  # profit ÷ those orders' buyer paid (1 decimal)
    orders: int  # orders whose every counted line has its costs
    gmv: Decimal  # those orders' GMV
    gmv_share_pct: Decimal | None  # of the shop GMV (1 decimal)
    buyer_paid: Decimal = ZERO  # those orders' buyer paid (the margin base)
    ads_charged: Decimal = ZERO  # the ad spend charged to them
    ads_basis: str = ADS_SHARE_WINDOW
    product_profit: Decimal | None = None  # bridge: contribution - ads charged to products
    ads_unattributed_charged: Decimal = ZERO  # bridge: "QC không gắn sản phẩm" charged
    other_marketing_charged: Decimal = ZERO  # bridge: "chi marketing khác" charged
    ads_total: Decimal = ZERO  # all the ad spend of the window (charged or not)

    @property
    def label(self) -> str:
        if self.profit is None or self.orders == 0:
            return NO_KNOWN_COST_LABEL
        if self.gmv_share_pct is None:
            return f"trên {self.orders} đơn có chi phí"
        return f"trên {self.orders} đơn có chi phí, {_vn_pct(self.gmv_share_pct)} % GMV"

    @property
    def ads_label(self) -> str:
        """What the ads line charged (B.5): the spend of the days with known-cost orders."""
        charged, total = _vn_money(self.ads_charged), _vn_money(self.ads_total)
        if self.ads_basis == ADS_SHARE_DAILY:
            return f"QC tính trên ngày có đơn có chi phí: {charged}đ / tổng chi QC {total}đ"
        return f"QC tính theo tỷ lệ doanh thu đơn có chi phí: {charged}đ / tổng chi QC {total}đ"

    def json(self) -> dict[str, object]:
        return {
            "profit": _money(self.profit),
            "margin_pct": None if self.margin_pct is None else float(self.margin_pct),
            "orders": self.orders,
            "gmv": _money(self.gmv),
            "gmv_share_pct": None if self.gmv_share_pct is None else float(self.gmv_share_pct),
            "net_revenue": _money(self.buyer_paid),  # no "buyer" key in any payload
            "ads_charged": _money(self.ads_charged),
            "ads_basis": self.ads_basis,
            "label": self.label,
            "bridge": {
                "product_profit": _money(self.product_profit),
                "ads_unattributed": _money(self.ads_unattributed_charged),
                "other_marketing": _money(self.other_marketing_charged),
                "profit": _money(self.profit),
                "ads_charged": _money(self.ads_charged),
                "ads_total": _money(self.ads_total),
                "ads_label": self.ads_label,
            },
        }


def _vn_money(value: Decimal) -> str:
    return f"{int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP)):,}".replace(",", ".")


def _whole(value: Decimal) -> Decimal:
    return value.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def known_cost_profit(
    profit: ShopProfit,
    pairs: Pairs,
    shop_gmv: Decimal | None,
    daily_spend: Mapping[date, Decimal] | None = None,
) -> KnownCostProfit:
    """The one shop profit (P100 B.5), ORDER-based. An order is "có chi phí" only when every one
    of its counted lines (cancelled / undelivered ones are outside the profit base) has its
    costs; every line of any other order is left out of the profit, the margin base and the ads
    share, and counts against the coverage. ``None`` (never 0) without a known-cost order.

    Ads, with ``daily_spend`` (:data:`ADS_SHARE_DAILY`, the one per-day spend of
    :mod:`.ads_days`): each day's spend is charged by that day's known-cost GMV share -- a day
    whose orders all lack costs charges nothing, and a day with no order line at all (no order
    data) contributes no profit and no ads charge. The charged total is then split between the
    products' report spend and the spend not tied to a product in the window's proportion, so
    the bridge adds up. Without ``daily_spend`` each product's report spend follows the known
    orders' share of that product's buyer paid and the rest the window share
    (:data:`ADS_SHARE_WINDOW`). Other marketing costs always follow the window share."""
    counted = [(ln, pb) for ln, pb in pairs if pb.excluded_reason is None]
    unknown = {ln.order_id for ln, pb in counted if pb.contribution is None}
    known = [(ln, pb) for ln, pb in counted if ln.order_id not in unknown]
    known_orders = {ln.order_id for ln, _ in known}
    paid_all = sum((pb.revenue for _, pb in counted), ZERO)
    paid_known = sum((pb.revenue for _, pb in known), ZERO)
    contribution = sum((pb.contribution or ZERO for _, pb in known), ZERO)
    gmv = sum((ln.order_value for ln, _ in known), ZERO)
    share = safe_div(paid_known, paid_all) or ZERO

    spend_days = {d: s for d, s in (daily_spend or {}).items() if s > 0}
    spend_total = sum(spend_days.values(), ZERO)
    product_total = profit.product_ad_spend
    unattributed_total = profit.unattributed_ad_spend
    if spend_total > 0:
        basis = ADS_SHARE_DAILY
        day_all: dict[date, Decimal] = defaultdict(lambda: ZERO)
        day_known: dict[date, Decimal] = defaultdict(lambda: ZERO)
        for ln, _ in counted:
            day_all[ln.order_date] += ln.order_value
            if ln.order_id not in unknown:
                day_known[ln.order_date] += ln.order_value
        charged = ZERO
        for d, spent in spend_days.items():
            day_share = safe_div(day_known.get(d, ZERO), day_all.get(d, ZERO))
            charged += spent * (day_share or ZERO)  # no order data that day: no charge
        ads_total = spend_total
        pool = product_total + unattributed_total
        ads_products = charged * product_total / pool if pool > 0 else ZERO
        ads_unattributed = charged - ads_products
    else:
        basis = ADS_SHARE_WINDOW
        paid_by_product: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for ln, pb in known:
            paid_by_product[ln.product_id] += pb.revenue
        ads_products = ZERO
        for pid, pp in profit.products.items():
            part = safe_div(paid_by_product.get(pid, ZERO), pp.buyer_paid)
            if part is not None:
                ads_products += pp.ad_spend * part
        ads_unattributed = unattributed_total * share
        ads_total = profit.total_ad_spend
    other = profit.other_marketing_costs * share
    ads = ads_products + ads_unattributed
    value = None
    product_profit = None
    if known_orders:
        # whole đồng per bridge line, so the lines add up exactly to the figure every screen shows
        product_profit = _whole(contribution - ads_products)
        ads_unattributed, other = _whole(ads_unattributed), _whole(other)
        value = product_profit - ads_unattributed - other
    margin = None if value is None else pct_points(safe_div(value, paid_known))
    gmv_share = None
    if shop_gmv is not None and shop_gmv > 0:
        gmv_share = (gmv * 100 / shop_gmv).quantize(Decimal("0.1"))
    return KnownCostProfit(
        profit=value,
        margin_pct=None if margin is None else margin.quantize(Decimal("0.1")),
        orders=len(known_orders),
        gmv=gmv,
        gmv_share_pct=gmv_share,
        buyer_paid=paid_known,
        ads_charged=ads,
        ads_basis=basis,
        product_profit=product_profit,
        ads_unattributed_charged=ads_unattributed,
        other_marketing_charged=other,
        ads_total=ads_total,
    )
