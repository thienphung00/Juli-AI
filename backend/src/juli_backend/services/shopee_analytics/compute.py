"""One window's worth of stored data -> profit, flows and ads in the shapes the builders share.

``PeriodData`` is what the loaders returned for a window; :func:`compute_view` turns it into a
:class:`PeriodView` (order lines through the profit waterfall, ads allocated, flow tables built).
Both the overview, the matrix, the product page, the critical list and the rankings read the same
view of the same window, so one product shows one set of numbers on every screen.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from juli_backend.services.shopee_analytics.engine import (
    CostCoverage,
    Costs,
    FeeContext,
    IncomeCoverage,
    ShopLine,
    build_fee_context,
    cost_coverage,
    income_coverage,
    profit_pairs,
    resolve_costs,
    to_shop_lines,
)
from juli_backend.services.shopee_analytics.loaders import (
    AdsDaily,
    AdsReports,
    AdsRow,
    AffiliateLoad,
    OrderLinesLoad,
    ProductFlows,
    PromotionsLoad,
    ShopContext,
    ShopTotals,
    ShopTraffic,
    VouchersLoad,
)
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.ads_sources import AdSpendResult
from juli_backend.services.shopee_profit.flows import (
    FlowRow,
    FlowSource,
    FlowTables,
    build_flow_tables,
)
from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_profit.order_profit import OrderLine, ProfitBreakdown
from juli_backend.services.shopee_profit.shop_profit import (
    AdCampaign,
    AdsFigures,
    ShopProfit,
    shop_profit,
)
from juli_backend.services.shopee_profit.sources import SourceMatrix, build_source_matrix
from juli_backend.services.shopee_profit.vat import vat_label
from juli_backend.services.shopee_profit.vouchers import VoucherJoin

SHOP_KEY = "__shop__"


@dataclass
class PeriodData:
    window: Window
    lines: OrderLinesLoad
    totals: ShopTotals
    traffic: ShopTraffic
    ads_daily: AdsDaily
    product_flows: ProductFlows
    ads_reports: AdsReports
    vouchers: VouchersLoad
    promotions: PromotionsLoad
    affiliate: AffiliateLoad
    ad_spend: AdSpendResult | None = None  # services/shopee_profit/ads_sources (Step 6)
    voucher_join: VoucherJoin | None = None


@dataclass
class CampaignAlloc:
    key: str
    name: str
    spend: Decimal
    gmv: Decimal
    direct_gmv: Decimal
    orders: Decimal
    clicks: Decimal
    impressions: Decimal
    running: bool | None
    products: dict[str, Decimal]  # item -> spend


@dataclass
class AdsAllocation:
    """Ad spend of the window, split like the ads report, totalling the daily ads figures."""

    total_spend: Decimal
    product_spend: dict[str, Decimal]
    product_figures: dict[str, AdsFigures]
    campaigns: list[CampaignAlloc]
    scale: Decimal
    basis: str  # daily_scaled | report_prorated | daily_only | none
    report_windows: tuple[tuple[date, date], ...]
    exact_window: bool
    daily_total: Decimal | None
    report_total_raw: Decimal
    label: str

    def ad_campaigns(self) -> list[AdCampaign]:
        return [AdCampaign(c.key, c.spend, c.gmv, c.name, c.direct_gmv) for c in self.campaigns]


def _row_factor(window: Window, period: tuple[date, date]) -> Decimal:
    """Share of a report row that falls in the window (1 when the report is the window)."""
    if period == (window.start, window.end):
        return Decimal(1)
    days = (period[1] - period[0]).days + 1
    return Decimal(window.overlap_days(*period)) / Decimal(days)


def allocate_ads(
    window: Window,
    daily: AdsDaily,
    reports: AdsReports,
    resolved: AdSpendResult | None = None,
) -> AdsAllocation:
    rows: list[AdsRow] = reports.campaign_rows
    if resolved is not None and resolved.total > 0:
        daily_total = resolved.total  # Connector days first, CSV windows for the rest
    else:
        daily_total = daily.spend if daily.complete else None
    by_campaign: dict[str, list[AdsRow]] = defaultdict(list)
    for r in rows:
        by_campaign[r.key].append(r)
    raw: list[CampaignAlloc] = []
    raw_total = ZERO
    for key, items in by_campaign.items():
        head = next((r for r in items if r.item_id == ""), None)
        product_rows = [r for r in items if r.item_id]
        base = head
        f = _row_factor(window, items[0].period)

        def pick(attr: str) -> Decimal:
            if base is not None:
                return getattr(base, attr)
            return sum((getattr(r, attr) for r in product_rows), ZERO)

        spend_by_item: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for r in product_rows:
            spend_by_item[r.item_id] += r.spend * f
        raw_total += pick("spend")
        raw.append(
            CampaignAlloc(
                key,
                (base or items[0]).campaign,
                pick("spend") * f,
                pick("gmv") * f,
                pick("direct_gmv") * f,
                pick("orders") * f,
                pick("clicks") * f,
                pick("impressions") * f,
                (base or items[0]).running,
                dict(spend_by_item),
            )
        )
    exact = reports.campaign_choice.basis == "exact"
    periods = reports.campaign_choice.periods

    if not raw:
        if daily_total is not None and daily_total > 0:
            only = CampaignAlloc(
                "daily",
                "Tổng chi quảng cáo (theo ngày)",
                daily_total,
                daily.gmv,
                ZERO,
                daily.orders,
                ZERO,
                ZERO,
                None,
                {},
            )
            return AdsAllocation(
                daily_total,
                {},
                {},
                [only],
                Decimal(1),
                "daily_only",
                (),
                False,
                daily_total,
                ZERO,
                "Chỉ có chi phí quảng cáo theo ngày; chưa có báo cáo theo chiến dịch / sản phẩm.",
            )
        return AdsAllocation(
            ZERO,
            {},
            {},
            [],
            Decimal(1),
            "none",
            (),
            False,
            daily_total,
            ZERO,
            "Chưa có dữ liệu quảng cáo cho kỳ này.",
        )

    prorated_total = sum((c.spend for c in raw), ZERO)
    if daily_total is not None and prorated_total > 0:
        k = daily_total / prorated_total
        basis = "daily_scaled"
        source = (
            "chi phí đã chốt (Connector theo ngày, ngày còn lại theo báo cáo CSV)"
            if resolved is not None and resolved.total > 0
            else "chi phí quảng cáo theo ngày"
        )
        label = (
            f"Báo cáo chiến dịch (đơn đã đặt) đúng kỳ, tổng khớp {source}."
            if exact
            else "Báo cáo chiến dịch (đơn đã đặt) chia theo số ngày trùng và tỷ trọng; "
            f"tổng khớp {source}."
        )
    else:
        k = Decimal(1)
        basis = "report_exact" if exact else "report_prorated"
        label = (
            "Báo cáo chiến dịch (đơn đã đặt) đúng kỳ."
            if exact
            else "Báo cáo chiến dịch khác kỳ, chia theo số ngày trùng (ước tính)."
        )
    camps = [
        CampaignAlloc(
            c.key,
            c.name,
            c.spend * k,
            c.gmv * k,
            c.direct_gmv * k,
            c.orders * k,
            c.clicks * k,
            c.impressions * k,
            c.running,
            {i: s * k for i, s in c.products.items()},
        )
        for c in raw
    ]
    product_spend: dict[str, Decimal] = defaultdict(lambda: ZERO)
    product_gmv: dict[str, Decimal] = defaultdict(lambda: ZERO)
    product_direct: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for r in rows:
        if r.item_id:
            f = _row_factor(window, r.period) * k
            product_spend[r.item_id] += r.spend * f
            product_gmv[r.item_id] += r.gmv * f
            product_direct[r.item_id] += r.direct_gmv * f
    if resolved is not None and resolved.products:
        # per-product spend only from the per-product CSV rows (Step 6); the rest is unattributed
        for item, wanted in resolved.products.items():
            have = product_spend.get(item, ZERO)
            ratio = wanted / have if have > 0 else ZERO
            product_gmv[item] = product_gmv.get(item, ZERO) * ratio
            product_direct[item] = product_direct.get(item, ZERO) * ratio
            product_spend[item] = wanted
        for item in [i for i in product_spend if i not in resolved.products]:
            del product_spend[item]
    figures = {
        i: AdsFigures(product_spend[i], product_gmv[i], product_direct[i]) for i in product_spend
    }
    total = sum((c.spend for c in camps), ZERO)
    return AdsAllocation(
        total,
        dict(product_spend),
        figures,
        camps,
        k,
        basis,
        periods,
        exact,
        daily_total,
        raw_total,
        label,
    )


@dataclass
class PeriodView:
    data: PeriodData
    lines: list[ShopLine]
    costs: Costs
    fees: FeeContext
    pairs: list[tuple[OrderLine, ProfitBreakdown]]
    coverage: CostCoverage
    income_coverage: IncomeCoverage
    vat: dict[str, object]
    ads: AdsAllocation
    profit: ShopProfit
    matrix: SourceMatrix
    flows: FlowTables | None
    flow_totals_source: str
    shop_gmv: Decimal | None
    shop_orders: int | None
    names: dict[str, str] = field(default_factory=dict)

    @property
    def window(self) -> Window:
        return self.data.window

    @property
    def line_gmv(self) -> Decimal:
        return sum((ln.order_value for ln, _ in self.pairs), ZERO)

    @property
    def line_orders(self) -> int:
        return len({ln.order_id for ln, _ in self.pairs})


def shop_flow_rows(traffic: ShopTraffic) -> list[FlowRow]:
    rows: list[FlowRow] = []
    for source, agg in traffic.sources.items():
        if (
            source is FlowSource.TRANG_SHOP
            and agg.views is None
            and agg.orders == 0
            and agg.gmv == 0
        ):
            continue
        rows.append(
            FlowRow(
                SHOP_KEY,
                source,
                int(agg.orders),
                agg.gmv,
                None if agg.views is None else int(agg.views),
                None if agg.clicks is None else int(agg.clicks),
            )
        )
    return rows


def compute_view(ctx: ShopContext, data: PeriodData) -> PeriodView:
    lines = to_shop_lines(data.lines.lines, ctx.catalog, ctx.rules, data.lines.income)
    costs = resolve_costs(lines, ctx.rules)
    item_ids = sorted({sl.product_id for sl in lines} | set(data.product_flows.totals))
    fees = build_fee_context(item_ids, ctx.catalog, ctx.db_schedules(item_ids))
    pairs = profit_pairs(lines, costs, fees)
    ads = allocate_ads(data.window, data.ads_daily, data.ads_reports, data.ad_spend)
    profit = shop_profit(
        pairs,
        campaigns=ads.ad_campaigns(),
        product_ad_spend=ads.product_spend,
        export_gmv=data.totals.gmv if data.totals.complete else None,
        product_ads=ads.product_figures,
    )
    matrix = build_source_matrix(pairs)

    shop_gmv = (
        data.totals.gmv
        if data.totals.gmv is not None
        else (sum((ln.order_value for ln, _ in pairs), ZERO) if pairs else None)
    )
    shop_orders = (
        data.totals.orders
        if data.totals.orders is not None
        else (len({ln.order_id for ln, _ in pairs}) if pairs else None)
    )
    flow_rows = shop_flow_rows(data.traffic) + data.product_flows.rows
    tables: FlowTables | None = None
    totals_source = "none"
    if data.traffic.basis != "none" and shop_gmv is not None:
        # shop table from the shop traffic rows; per-product tables from product rows
        shop_only = build_flow_tables(
            shop_flow_rows(data.traffic), shop_gmv=shop_gmv, shop_orders=shop_orders
        )
        prod_only = build_flow_tables(
            data.product_flows.rows,
            shop_gmv=shop_gmv,
            shop_orders=shop_orders,
            product_totals=data.product_flows.flow_totals,
        )
        tables = FlowTables(shop_only.shop, prod_only.products)
        totals_source = data.totals.basis
    elif flow_rows and shop_gmv is not None:
        tables = build_flow_tables(
            data.product_flows.rows,
            shop_gmv=shop_gmv,
            shop_orders=shop_orders,
            product_totals=data.product_flows.flow_totals,
        )
        totals_source = "product_flows"
    return PeriodView(
        data=data,
        lines=lines,
        costs=costs,
        fees=fees,
        pairs=pairs,
        coverage=cost_coverage(pairs, costs),
        income_coverage=income_coverage(pairs),
        vat=vat_label(ctx.rules.prices_include_vat, ctx.rules.cost_includes_vat),
        ads=ads,
        profit=profit,
        matrix=matrix,
        flows=tables,
        flow_totals_source=totals_source,
        shop_gmv=shop_gmv,
        shop_orders=shop_orders,
        names={i: ctx.catalog.name(i) for i in item_ids},
    )
