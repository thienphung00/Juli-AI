"""One window's worth of stored data -> profit, flows and ads in the shapes the builders share.

``PeriodData`` is what the loaders returned for a window; :func:`compute_view` turns it into a
:class:`PeriodView` (order lines through the profit waterfall, ads allocated, flow tables built).
Both the overview, the matrix, the product page, the critical list and the rankings read the same
view of the same window, so one product shows one set of numbers on every screen.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

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
    AD_LIVESTREAM,
    AD_SHOP_PLUS,
    AD_UNKNOWN,
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
    ad_type_class,
)
from juli_backend.services.shopee_analytics.product_ads import (
    CampaignDayRow,
    ProductAdRule,
    ProductAdsInput,
    ReportRow,
)
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.ads_sources import AdSpendResult
from juli_backend.services.shopee_profit.flows import (
    FlowRow,
    FlowSource,
    FlowTables,
    build_flow_tables,
)
from juli_backend.services.shopee_profit.money import ZERO, safe_div
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    ProfitBreakdown,
    counts_in_sales,
)
from juli_backend.services.shopee_profit.shop_profit import (
    AdCampaign,
    AdsFigures,
    ShopProfit,
    shop_profit,
)
from juli_backend.services.shopee_profit.sources import SourceMatrix, build_source_matrix
from juli_backend.services.shopee_profit.vat import vat_label
from juli_backend.services.shopee_profit.vouchers import VoucherJoin

if TYPE_CHECKING:
    from juli_backend.services.shopee_analytics.metrics import ShopMetrics

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
    #: the one product ad cost's inputs (:mod:`product_ads`); None = the report rows alone
    product_ads: ProductAdsInput | None = None
    voucher_join: VoucherJoin | None = None
    #: the materialized daily rows of the window (P97 D85.2); None = not loaded / not built
    stored: Any = None
    #: the window's stored funnel rows (P98 / ADR-122 d.2, ``funnel.FunnelRows``); None = not
    #: loaded (the rebuild path and callers that do not show Lượt xem / CTR / CTOR)
    funnel: Any = None
    #: P99b: how a window without stored daily rows is treated -- "require" (a screen's window:
    #: :class:`stored.RowsNotMaterialized`), "soft" (a comparison window: the raw tables, but it
    #: is not comparable), "raw" (the metrics rebuild and direct callers: the raw tables)
    rows_policy: str = "raw"
    #: the window's data days (``stored.data_days_in``); None = not loaded
    data_days: frozenset[Any] | None = None


SOURCE_DAILY = "daily"  # every figure is the Connector's own days
SOURCE_MIXED = "mixed"  # Connector days + the report's share of the days it did not read
SOURCE_REPORT = "report"  # the period report alone
_COUNTS = ("gmv", "direct_gmv", "orders", "clicks", "impressions")
#: the Connector's ``state`` of a campaign that runs
_ONGOING = "ongoing"


@dataclass
class CampaignAlloc:
    key: str
    name: str
    spend: Decimal
    #: ``None`` = the campaign's row of some day the Connector read lacks the count (never 0)
    gmv: Decimal | None
    direct_gmv: Decimal | None
    orders: Decimal | None
    clicks: Decimal | None
    impressions: Decimal | None
    running: bool | None
    products: dict[str, Decimal]  # item -> spend
    source: str = SOURCE_REPORT  # daily | mixed | report
    #: the report segments of this campaign (its key, or title hashes joined to it)
    report_keys: frozenset[str] = frozenset()

    @property
    def roas(self) -> Decimal | None:
        """0 when it spent and sold nothing; ``None`` when it spent nothing or GMV is unknown."""
        return None if self.gmv is None else safe_div(self.gmv, self.spend)

    @property
    def roas_direct(self) -> Decimal | None:
        return None if self.direct_gmv is None else safe_div(self.direct_gmv, self.spend)


@dataclass
class AdsAllocation:
    """Ad spend of the window per campaign, plus the ``remainder`` no listed campaign explains
    (Shop+, spend the campaigns' own figures do not reach); together the one daily ads total."""

    total_spend: Decimal
    product_spend: dict[str, Decimal]
    product_figures: dict[str, AdsFigures]
    campaigns: list[CampaignAlloc]
    scale: Decimal  # always 1 since C2: no figure is stretched
    #: connector_daily | daily_and_report | report_exact | report_prorated | daily_only | none
    basis: str
    report_windows: tuple[tuple[date, date], ...]
    exact_window: bool
    daily_total: Decimal | None
    report_total_raw: Decimal
    label: str
    #: total_spend - the campaigns' spend (negative when their estimated days exceed the total)
    remainder: Decimal = ZERO
    remainder_gmv: Decimal | None = None

    @property
    def known_spend(self) -> Decimal | None:
        """The window's ad cost; ``None`` when there is no ad-cost data for it (no daily rows, no
        report): missing is never 0 (owner #99). A read day that spent 0 is 0."""
        return None if self.basis == "none" else self.total_spend

    def ad_campaigns(self) -> list[AdCampaign]:
        out = [AdCampaign(c.key, c.spend, c.gmv, c.name, c.direct_gmv) for c in self.campaigns]
        if self.remainder != 0:
            out.append(AdCampaign(REMAINDER_KEY, self.remainder, self.remainder_gmv))
        return out


REMAINDER_KEY = "__remainder__"


def campaign_of(campaigns: Iterable[CampaignAlloc], key: str | None) -> CampaignAlloc | None:
    """The campaign of ``key`` (a saved card may still carry a report's own key)."""
    if not key:
        return None
    rows = list(campaigns)
    return next((c for c in rows if c.key == key), None) or next(
        (c for c in rows if key in getattr(c, "report_keys", ())), None
    )


def known_sum(values: list[Decimal | None]) -> Decimal | None:
    """The sum; ``None`` when one of the values is unknown."""
    known = [v for v in values if v is not None]
    return sum(known, ZERO) if len(known) == len(values) else None


def _row_factor(window: Window, period: tuple[date, date], covered: frozenset[date]) -> Decimal:
    """Share of a report row that falls on the window's days the Connector did not read."""
    span = (period[1] - period[0]).days + 1
    free = sum(1 for d in _window_days(window) if period[0] <= d <= period[1] and d not in covered)
    return Decimal(free) / Decimal(span)


def _window_days(window: Window) -> list[date]:
    return [window.start + timedelta(days=i) for i in range(window.days)]


@dataclass
class _ReportPart:
    """A campaign's report rows over its one best report window."""

    name: str
    running: bool | None
    factor: Decimal
    raw_spend: Decimal
    figures: dict[str, Decimal]  # spend + _COUNTS, the whole report
    products: dict[str, Decimal]


def _report_part(
    window: Window, key: str, rows: list[AdsRow], covered: frozenset[date]
) -> _ReportPart:
    def rank(period: tuple[date, date]) -> tuple[Decimal, int, int, date]:
        own = any(r.key == key for r in rows if r.period == period)
        span = (period[1] - period[0]).days
        free = _row_factor(window, period, covered) * (span + 1)
        return free, int(own), -span, period[1]

    period = max({r.period for r in rows}, key=rank)
    mine = [r for r in rows if r.period == period]
    if any(r.key == key for r in mine):  # the same report posted by id and by title: count it once
        mine = [r for r in mine if r.key == key]
    by_segment: dict[str, list[AdsRow]] = defaultdict(list)
    for r in mine:
        by_segment[r.key].append(r)
    figures = dict.fromkeys(("spend", *_COUNTS), ZERO)
    products: dict[str, Decimal] = defaultdict(lambda: ZERO)
    first: AdsRow | None = None
    for items in by_segment.values():
        head = next((r for r in items if r.item_id == ""), None)
        product_rows = [r for r in items if r.item_id]
        first = first or head or items[0]
        for attr in figures:
            for r in [head] if head is not None else product_rows:
                figures[attr] += getattr(r, attr)
        for r in product_rows:
            products[r.item_id] += r.spend
    assert first is not None
    factor = _row_factor(window, period, covered)
    return _ReportPart(
        first.campaign, first.running, factor, figures["spend"], figures, dict(products)
    )


def _campaign_allocs(
    window: Window, rows: list[AdsRow], inp: ProductAdsInput
) -> tuple[list[CampaignAlloc], Decimal]:
    """The listed campaigns, each from its Connector days (covered days) and its report's share of
    the other days; and the reports' raw spend."""
    covered = frozenset(d for d in _window_days(window) if d in inp.covered_days)
    newest = max(covered, default=None)
    join = inp.joiner()
    by_report: dict[str, list[AdsRow]] = defaultdict(list)
    for r in rows:
        by_report[join(r.key, r.campaign)].append(r)
    splits: dict[str, list[ReportRow]] = defaultdict(list)
    for split in inp.report_rows:
        splits[split.key].append(split)
    by_day: dict[str, dict[date, CampaignDayRow]] = defaultdict(dict)
    for key, day in inp.campaign_days:
        found = inp.day_row(key, day)
        if day in covered and found is not None:
            by_day[key][day] = found
    raw_total = ZERO
    out: list[CampaignAlloc] = []
    for key in [*by_report, *sorted(k for k in by_day if k not in by_report)]:
        days = by_day.get(key, {})
        report = _report_part(window, key, by_report[key], covered) if key in by_report else None
        raw_total += report.raw_spend if report else ZERO
        latest = days[max(days)] if days else None
        listed_type = ad_type_class(latest.ad_type) if latest is not None else AD_UNKNOWN
        if report is None and listed_type in (AD_SHOP_PLUS, AD_LIVESTREAM):
            continue  # no product campaign: its spend is in the remainder
        spend = sum((d.spend for d in days.values()), ZERO)
        counts: dict[str, Decimal | None] = {
            a: known_sum([getattr(d, a) for d in days.values()]) for a in _COUNTS
        }
        share = report.factor if report else ZERO
        if report is not None:
            spend += report.figures["spend"] * share
            for a, have in counts.items():
                counts[a] = None if have is None else have + report.figures[a] * share
        today = days.get(newest) if newest is not None else None
        ran = today is not None and today.state == _ONGOING
        if spend == 0 and not ran and (days or share == 0):
            continue  # it spent nothing and does not run (an ended campaign)
        products: dict[str, Decimal] = {}
        if days:  # decision #39's split of its Connector days; its other days are the report's
            own_days = ProductAdsInput(
                {(key, d): row.spend for d, row in days.items()},
                frozenset(_window_days(window)),
                splits.get(key, []),
            )
            products = ProductAdRule(own_days).window_spend(window.start, window.end)
        for item, value in (report.products if report else {}).items():
            products[item] = products.get(item, ZERO) + value * share
        source = SOURCE_REPORT
        if days or (covered and not share):
            source = SOURCE_MIXED if share else SOURCE_DAILY
        running = report.running if report else None
        if latest is not None and latest.state is not None:
            running = ran
        out.append(
            CampaignAlloc(
                key,
                (latest.name if latest and latest.name else report.name if report else "") or key,
                spend,
                counts["gmv"],
                counts["direct_gmv"],
                counts["orders"],
                counts["clicks"],
                counts["impressions"],
                running,
                products,
                source,
                frozenset(r.key for r in by_report.get(key, ())),
            )
        )
    return out, raw_total


def allocate_ads(
    window: Window,
    daily: AdsDaily,
    reports: AdsReports,
    resolved: AdSpendResult | None = None,
    product_ads: ProductAdsInput | None = None,
) -> AdsAllocation:
    rows: list[AdsRow] = reports.campaign_rows
    daily_total: Decimal | None
    if daily.days_covered > 0 and daily.spend > 0:
        # P100 A.5: the one per-day spend (Connector day, else the daily report, else the period
        # report spread over its days); days with no source are not in it
        daily_total = daily.spend
    elif resolved is not None and resolved.total > 0:
        daily_total = resolved.total
    elif daily.days_covered > 0 and daily.days_covered >= daily.window_days:
        daily_total = ZERO  # the days were read and nothing was spent: 0 is data
    else:
        daily_total = None
    camps, raw_total = _campaign_allocs(window, rows, product_ads or ProductAdsInput())
    read_days = product_ads.covered_days if product_ads is not None else frozenset()
    exact = reports.campaign_choice.basis == "exact" and not (
        read_days.intersection(_window_days(window))
    )
    spent = sum((c.spend for c in camps), ZERO)
    total = spent if daily_total is None else daily_total
    remainder = total - spent
    sources = {c.source for c in camps}
    if not camps and not rows:
        if daily_total is None:
            basis, label = "none", "Chưa có dữ liệu quảng cáo cho kỳ này."
        else:
            basis = "daily_only"
            label = (
                "Chỉ có chi phí quảng cáo theo ngày; chưa có báo cáo theo chiến dịch / sản phẩm."
            )
        exact = False
    elif sources == {SOURCE_REPORT}:
        basis = "report_exact" if exact else "report_prorated"
        label = (
            "Báo cáo chiến dịch (đơn đã đặt) đúng kỳ."
            if exact
            else "Báo cáo chiến dịch khác kỳ, chia theo số ngày trùng (ước tính)."
        )
    elif sources <= {SOURCE_DAILY}:
        basis, label = "connector_daily", "Số liệu chiến dịch theo ngày của Connector (đơn đã đặt)."
    else:
        basis = "daily_and_report"
        label = (
            "Số liệu chiến dịch theo ngày của Connector (đơn đã đặt); ngày Connector chưa đọc "
            "chia theo báo cáo chiến dịch (ước tính)."
        )
    product_spend, figures = _product_figures(window, rows, resolved, product_ads)
    return AdsAllocation(
        total,
        product_spend,
        figures,
        camps,
        Decimal(1),
        basis,
        reports.campaign_choice.periods,
        exact,
        daily_total,
        raw_total,
        label,
        remainder,
        daily.gmv if not camps else None,
    )


def _product_figures(
    window: Window,
    rows: list[AdsRow],
    resolved: AdSpendResult | None,
    product_ads: ProductAdsInput | None,
) -> tuple[dict[str, Decimal], dict[str, AdsFigures]]:
    """Each product's ad cost (decision #39) and the report's GMV at the same ratio."""
    product_spend: dict[str, Decimal] = defaultdict(lambda: ZERO)
    # owner #99: a product's ads GMV (and ROAS) only from a report whose period IS the window;
    # a report of another period gives no GMV (None, never 0 and never prorated)
    own = (window.start, window.end)
    product_gmv: dict[str, Decimal] = {}
    product_direct: dict[str, Decimal] = {}
    for r in rows:
        if r.item_id:
            f = _row_factor(window, r.period, frozenset())
            product_spend[r.item_id] += r.spend * f
            if r.period == own:
                product_gmv[r.item_id] = product_gmv.get(r.item_id, ZERO) + r.gmv
                product_direct[r.item_id] = product_direct.get(r.item_id, ZERO) + r.direct_gmv
    wanted_by_item: dict[str, Decimal] | None = None
    if product_ads is not None:
        # decision #39: one ad cost per product = the Connector's campaign days x the product's
        # share in the ads report by product (:mod:`product_ads`); the window is its day sum
        wanted_by_item = ProductAdRule(product_ads).window_spend(window.start, window.end)
    elif resolved is not None and resolved.products and rows:
        # per-product spend only from the per-product CSV rows (Step 6); the rest is unattributed
        wanted_by_item = resolved.products
    if wanted_by_item is not None:
        for item, wanted in wanted_by_item.items():
            product_spend[item] = wanted
        for item in [i for i in product_spend if i not in wanted_by_item]:
            del product_spend[item]
    figures = {
        i: AdsFigures(product_spend[i], product_gmv.get(i), product_direct.get(i))
        for i in product_spend
    }
    return dict(product_spend), figures


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
    #: ``shop_gmv`` is Shopee's own shop total (else the window's sale lines). Shopee's total
    #: still holds the refund orders the lines leave out (``counts_in_sales``).
    gmv_from_totals: bool = False
    names: dict[str, str] = field(default_factory=dict)
    #: item id -> exclusion reason (P92 B-1). Excluded listings stay in every shop total and leave
    #: the product lists, rankings and Phân tích flags.
    excluded: dict[str, str] = field(default_factory=dict)
    #: item id -> (current price, list price) from the newest catalogue snapshot (P92 B-9).
    item_prices: dict[str, tuple[Decimal | None, Decimal | None]] = field(default_factory=dict)
    #: active, non-excluded catalogue listings (item id -> name), sold or not (P92 B-9).
    active_items: dict[str, str] = field(default_factory=dict)
    _metrics: Any = field(default=None, repr=False, compare=False)

    @property
    def metrics(self) -> ShopMetrics:
        """The window's core numbers (D85.2), computed once per view: every screen reads this."""
        if self._metrics is None:
            from juli_backend.services.shopee_analytics.metrics import metrics_of

            self._metrics = metrics_of(self)
        return cast("ShopMetrics", self._metrics)

    @property
    def window(self) -> Window:
        return self.data.window

    @property
    def line_gmv(self) -> Decimal:
        return sum((ln.order_value for ln, _ in self.pairs if counts_in_sales(ln)), ZERO)

    @property
    def line_orders(self) -> int:
        return len({ln.order_id for ln, _ in self.pairs if counts_in_sales(ln)})

    @property
    def comparable_as_previous(self) -> bool:
        """This (previous) window has enough order lines to compare a period against: the export
        spans it and at least half of its days have orders. Otherwise every delta is withheld."""
        if self.rows_missing:  # P99b: no stored daily rows -> never compared against
            return False
        return self.line_orders > 0 and self.data.lines.usable_as_previous

    @property
    def rows_missing(self) -> bool:
        """P99b: some data day of this window has no stored daily row (the raw tables would be
        the old unspread period split)."""
        d = self.data
        if d.data_days is None or d.rows_policy == "raw":
            return False
        if d.stored is not None and d.stored.usable:
            return False
        stored_days = frozenset() if d.stored is None else d.stored.days
        return any(day not in stored_days for day in d.data_days)


def _active_items(ctx: ShopContext) -> dict[str, str]:
    """Active (not unlisted / banned / deleted) listings that are not excluded."""
    from juli_backend.services.shopee_builder.catalogue import is_active

    return {
        i: ctx.catalog.name(i)
        for i, info in ctx.catalog.items.items()
        if not i.startswith("sku:")
        and is_active(info.status, info.name)
        and i not in ctx.rules.excluded
    }


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
    fees = build_fee_context(item_ids, ctx.catalog, ctx.db_schedules(item_ids), ctx.service_rate)
    pairs = profit_pairs(lines, costs, fees)
    sales = [(ln, pb) for ln, pb in pairs if counts_in_sales(ln)]  # a returned order is no sale
    ads = allocate_ads(
        data.window, data.ads_daily, data.ads_reports, data.ad_spend, data.product_ads
    )
    profit = shop_profit(
        pairs,
        campaigns=ads.ad_campaigns(),
        product_ad_spend=ads.product_spend,
        export_gmv=data.totals.gmv if data.totals.complete else None,
        product_ads=ads.product_figures,
    )
    matrix = build_source_matrix(pairs)

    # Totals from only some days of the window (the file upload trails the Connector's sync)
    # would understate the shop: when the order lines span the whole window they stand in.
    lines_stand_in = (
        bool(pairs) and data.totals.basis == "partial_daily" and data.lines.covers_window
    )
    use_totals = data.totals.gmv is not None and not lines_stand_in
    shop_gmv = (
        data.totals.gmv
        if use_totals
        else (sum((ln.order_value for ln, _ in sales), ZERO) if pairs else None)
    )
    shop_orders = (
        data.totals.orders
        if data.totals.orders is not None and not lines_stand_in
        else (len({ln.order_id for ln, _ in sales}) if pairs else None)
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
        gmv_from_totals=use_totals,
        names={i: ctx.catalog.name(i) for i in item_ids},
        excluded=dict(ctx.rules.excluded),
        item_prices={
            i: (info.current_price, info.list_price) for i, info in ctx.catalog.items.items()
        },
        active_items=_active_items(ctx),
    )
