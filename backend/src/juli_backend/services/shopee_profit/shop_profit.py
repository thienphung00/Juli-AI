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
from decimal import Decimal

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
