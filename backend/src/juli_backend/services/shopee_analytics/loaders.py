"""Stored data -> the plain inputs the builders compute on, per shop and window.

Every function reads through a repository (``repositories/shopee_analytics.py``) inside the
caller's shop scope and returns detached dataclasses; nothing here computes a metric. The
rules about WHICH stored rows stand in for a window live here, in one place:

- Shopee's own totals (GMV, orders, flows) come from day rows when they cover every day of the
  window, else from the period rows (:func:`windows.choose_periods`), else from the partial day
  rows -- and every result states its ``basis`` and how many days it covers.
- File exports outrank the connector for the same key (D-5); the connector's
  ``item_traffic_sources`` day rows fill product x source where no file period covers.
- Ads are the ads section's own "đơn đã đặt" figures; they are never added to confirmed totals.
- Order lines are read by order date; ``order_ref`` (a keyed hash) never leaves this package.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.repositories import (
    AdCampaignPurposesReadRepo,
    MarketKeywordMetricsReadRepo,
    PlatformDailyMetricsRepo,
    PlatformFeeFormulasReadRepo,
    PlatformItemSnapshotsRepo,
    PlatformItemsRepo,
    PlatformPeriodMetricsRepo,
    PlatformPromotionsRepo,
    ShopeeOrderLinesRepo,
    ShopKeywordSeedsReadRepo,
    ShopRulesReadRepo,
)
from juli_backend.repositories.shopee_analytics import ShopeeOrderIncomeRepo
from juli_backend.services.shopee_analytics import fee_table
from juli_backend.services.shopee_analytics.catalog import (
    Catalog,
    RawItem,
    RawSnapshot,
    build_catalog,
)
from juli_backend.services.shopee_analytics.engine import RawLine
from juli_backend.services.shopee_analytics.rules_view import (
    RULE_KEYS_READ,
    ProfitRules,
    RuleRow,
    read_rules,
    with_sku_aliases,
)
from juli_backend.services.shopee_analytics.windows import PeriodChoice, Window, choose_periods
from juli_backend.services.shopee_profit.ads_sources import (
    AdDay,
    AdSpendResult,
    AdWindow,
    resolve_ad_spend,
)
from juli_backend.services.shopee_profit.fees import FeeSchedule
from juli_backend.services.shopee_profit.flows import FlowRow, FlowSource
from juli_backend.services.shopee_profit.income import IncomeOrder
from juli_backend.services.shopee_profit.money import ZERO

CONFIRMED = "confirmed"
PLACED = "placed"
TRAFFIC_DAILY = "traffic_overview"
TRAFFIC_PERIOD = "traffic_overview_period"
ITEM_SOURCE_PERIOD = "item_by_source_period"
ITEM_SOURCE_DAILY = ("item_traffic_sources", "item_by_source")
PRODUCT_PERIOD = "product_period"
SHOP_OVERVIEW_DAILY = "shop_overview"
SHOP_OVERVIEW_PERIOD = "shop_overview_period"

STREAM_TO_SOURCE: dict[str, FlowSource] = {
    "product_card": FlowSource.THE_SAN_PHAM_TOTAL,
    "seller_live": FlowSource.LIVE,
    "seller_video": FlowSource.VIDEO,
    "affiliate": FlowSource.LIEN_KET,
}
#: Children of Thẻ sản phẩm (contract 2); ``shop_page`` is Trang shop, a flow of its own.
CARD_CHILDREN: tuple[str, ...] = ("search", "recommend", "cart", "my_orders", "promo", "other")
TRANG_SHOP_SEGMENT = "shop_page"


def _d(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _z(value: Any) -> Decimal:
    return ZERO if value is None else Decimal(str(value))


@dataclass
class Agg:
    """Summed counts of one source (None = the source reports none, never 0)."""

    views: Decimal | None = None
    clicks: Decimal | None = None
    orders: Decimal = ZERO
    gmv: Decimal = ZERO

    def add(self, views: Any, clicks: Any, orders: Any, gmv: Any) -> None:
        if views is not None:
            self.views = (self.views or ZERO) + Decimal(str(views))
        if clicks is not None:
            self.clicks = (self.clicks or ZERO) + Decimal(str(clicks))
        self.orders += _z(orders)
        self.gmv += _z(gmv)


def _int(value: Decimal | None) -> int | None:
    return None if value is None else int(value.to_integral_value())


# ---------------------------------------------------------------------------------------
# Shop context: catalogue, rules, fee schedules
# ---------------------------------------------------------------------------------------


@dataclass
class ShopContext:
    catalog: Catalog
    rules: ProfitRules
    formula_rows: list[fee_table.FormulaRow]
    purposes: dict[str, str] = field(default_factory=dict)  # campaign key -> purpose
    snapshot_times: dict[str, Any] = field(default_factory=dict)

    def db_schedules(self, item_ids: list[str]) -> dict[str, FeeSchedule]:
        out: dict[str, FeeSchedule] = {}
        if not self.formula_rows:
            return out
        for item_id in item_ids:
            info = self.catalog.items.get(item_id)
            schedule = fee_table.schedule_from_rows(
                self.formula_rows, info.category_path if info else None
            )
            if schedule is not None:
                out[item_id] = schedule
        return out


async def load_context(session: AsyncSession, shop_id: uuid.UUID) -> ShopContext:
    items = await PlatformItemsRepo(session).all_items(shop_id)
    snaps = await PlatformItemSnapshotsRepo(session).latest_per_item(shop_id)
    catalog = build_catalog(
        (
            RawItem(i.item_id, i.variation_id, i.name, i.variation_name, i.seller_sku, i.status)
            for i in items
        ),
        (
            RawSnapshot(
                s.item_id,
                s.variation_id,
                s.title,
                s.list_price,
                s.current_price,
                s.stock,
                tuple(s.category_path or ()),
                s.status,
            )
            for s in snaps
        ),
    )
    rule_rows = await ShopRulesReadRepo(session).current(shop_id, RULE_KEYS_READ)
    rules = read_rules(RuleRow(r.rule_key, r.scope_ref, r.value) for r in rule_rows)
    scope_to_sku = {
        (f"{i.item_id}:{i.variation_id}" if i.variation_id else i.item_id): i.seller_sku
        for i in items
        if i.seller_sku
    }
    rules = with_sku_aliases(rules, scope_to_sku)
    formulas = await PlatformFeeFormulasReadRepo(session).for_platform()
    formula_rows = [
        fee_table.FormulaRow(
            tuple(f.category_path or ()), f.effective_from, tuple(f.components or ())
        )
        for f in formulas
    ]
    purposes = {
        p.campaign_key: p.purpose for p in await AdCampaignPurposesReadRepo(session).latest(shop_id)
    }
    return ShopContext(catalog, rules, formula_rows, purposes)


# ---------------------------------------------------------------------------------------
# Order lines
# ---------------------------------------------------------------------------------------


@dataclass
class OrderLinesLoad:
    lines: list[RawLine]
    window: Window
    days_with_orders: int = 0
    export_bounds: tuple[date, date] | None = None
    #: order_ref -> the income export's actuals for that order (P91 D-12).
    income: dict[str, IncomeOrder] = field(default_factory=dict)

    @property
    def covers_window(self) -> bool:
        """The order export spans the whole window (its first to last day brackets it)."""
        b = self.export_bounds
        return b is not None and b[0] <= self.window.start and self.window.end <= b[1]


async def load_order_lines(
    session: AsyncSession, shop_id: uuid.UUID, window: Window
) -> OrderLinesLoad:
    repo = ShopeeOrderLinesRepo(session)
    rows = await repo.in_window(shop_id, window.start, window.end)
    raw = [
        RawLine(
            order_ref=r.order_ref,
            line_no=r.line_no,
            ordered_at=r.ordered_at,
            paid_at=r.paid_at,
            status=r.status,
            item_id=r.item_id,
            sku=r.sku,
            variation_sku=r.variation_sku,
            qty=r.qty,
            original_price=r.original_price,
            deal_price=r.deal_price,
            shop_voucher_share=r.shop_voucher_share,
            bundle_discount=r.bundle_discount,
            promo_kind=r.promo_kind,
            voucher_code=r.voucher_code,
            affiliate=bool(r.affiliate),
            commission=r.commission,
            fee_fixed=r.fee_fixed,
            fee_service=r.fee_service,
            fee_payment=r.fee_payment,
            fee_other=r.fee_other,
            buyer_shipping_fee=r.buyer_shipping_fee,
            bank_promo=r.bank_promo,
            ad_attributed=r.ad_attributed,
            variation_id=r.variation_id,
            variation_name=r.variation_name,
        )
        for r in rows
    ]
    days = await repo.days_with_lines(shop_id, window.start, window.end)
    income = await load_income(session, shop_id, {r.order_ref for r in raw})
    return OrderLinesLoad(raw, window, len(days), await repo.day_bounds(shop_id), income)


async def load_income(
    session: AsyncSession, shop_id: uuid.UUID, refs: set[str]
) -> dict[str, IncomeOrder]:
    """The income export's rows of these orders, detached (no buyer column exists)."""
    if not refs:
        return {}
    rows = await ShopeeOrderIncomeRepo(session).for_refs(shop_id, refs)
    return {
        r.order_ref: IncomeOrder(
            order_ref=r.order_ref,
            fee_fixed=r.fee_fixed,
            fee_service=r.fee_service,
            fee_payment=r.fee_payment,
            fee_piship=r.fee_piship,
            fee_nttd=r.fee_nttd,
            affiliate_commission=r.affiliate_commission,
            net_shipping_cost=r.net_shipping_cost,
            return_ship_refund=r.return_ship_refund,
            return_ship_failed=r.return_ship_failed,
            refund_amount=r.refund_amount,
            lost_compensation=r.lost_compensation,
            vat_withheld=r.vat_withheld,
            pit_withheld=r.pit_withheld,
            seller_coin_borne=r.seller_coin_borne,
            trade_in_bonus_seller=r.trade_in_bonus_seller,
            payout=r.payout,
        )
        for r in rows
    }


# ---------------------------------------------------------------------------------------
# Shop-level totals, flows and ads (Shopee's own numbers)
# ---------------------------------------------------------------------------------------


@dataclass
class ShopTotals:
    gmv: Decimal | None
    orders: int | None
    basis: str  # daily | period | partial_daily | none
    days_covered: int
    window_days: int
    period: tuple[date, date] | None = None

    @property
    def complete(self) -> bool:
        return self.basis in ("daily", "period")


async def load_shop_totals(session: AsyncSession, shop_id: uuid.UUID, window: Window) -> ShopTotals:
    daily = PlatformDailyMetricsRepo(session)
    rows = await daily.window(
        shop_id,
        datasets=[SHOP_OVERVIEW_DAILY],
        start=window.start,
        end=window.end,
        streams=["total"],
        order_types=[CONFIRMED],
    )
    by_day: dict[date, tuple[Decimal, Decimal]] = {}
    for r in rows:
        if r.segment == "all":
            by_day[r.day] = (_z(r.gmv), _z(r.orders))
    gmv = sum((v[0] for v in by_day.values()), ZERO)
    orders = sum((v[1] for v in by_day.values()), ZERO)
    if len(by_day) == window.days:
        return ShopTotals(gmv, _int(orders), "daily", len(by_day), window.days)
    period_repo = PlatformPeriodMetricsRepo(session)
    prows = await period_repo.overlapping(
        shop_id,
        datasets=[SHOP_OVERVIEW_PERIOD],
        start=window.start,
        end=window.end,
        order_types=[CONFIRMED],
    )
    exact = [p for p in prows if (p.period_start, p.period_end) == (window.start, window.end)]
    if exact:
        p = exact[0]
        return ShopTotals(
            _d(p.gmv),
            _int(_d(p.orders)),
            "period",
            window.days,
            window.days,
            (window.start, window.end),
        )
    if by_day:
        return ShopTotals(gmv, _int(orders), "partial_daily", len(by_day), window.days)
    return ShopTotals(None, None, "none", 0, window.days)


@dataclass
class ShopTraffic:
    """Shop flows as five sources (+ Thẻ sản phẩm children), summed over the window."""

    sources: dict[FlowSource, Agg]
    children: dict[str, Agg]
    basis: str  # daily | period | partial_daily | none
    days_covered: int
    window_days: int

    @property
    def complete(self) -> bool:
        return self.basis in ("daily", "period")


def _accumulate_traffic(rows: list[Any]) -> tuple[dict[FlowSource, Agg], dict[str, Agg]]:
    sources: dict[FlowSource, Agg] = {s: Agg() for s in FlowSource}
    children: dict[str, Agg] = {c: Agg() for c in CARD_CHILDREN}
    for r in rows:
        if r.item_id not in ("", None):
            continue
        if r.segment == "all" and r.stream in STREAM_TO_SOURCE:
            sources[STREAM_TO_SOURCE[r.stream]].add(r.impressions, r.clicks, r.orders, r.gmv)
        elif r.stream == "product_card" and r.segment == TRANG_SHOP_SEGMENT:
            sources[FlowSource.TRANG_SHOP].add(r.impressions, r.clicks, r.orders, r.gmv)
        elif r.stream == "product_card" and r.segment in children:
            children[r.segment].add(r.impressions, r.clicks, r.orders, r.gmv)
    return sources, children


async def load_shop_traffic(
    session: AsyncSession, shop_id: uuid.UUID, window: Window
) -> ShopTraffic:
    streams = [*STREAM_TO_SOURCE]
    rows = await PlatformDailyMetricsRepo(session).window(
        shop_id,
        datasets=[TRAFFIC_DAILY],
        start=window.start,
        end=window.end,
        streams=streams,
        order_types=[CONFIRMED],
    )
    days = {r.day for r in rows if r.stream == "product_card" and r.segment == "all"}
    if len(days) == window.days:
        sources, children = _accumulate_traffic(rows)
        return ShopTraffic(sources, children, "daily", len(days), window.days)
    prows = await PlatformPeriodMetricsRepo(session).overlapping(
        shop_id,
        datasets=[TRAFFIC_PERIOD],
        start=window.start,
        end=window.end,
        order_types=[CONFIRMED],
    )
    exact = [
        p
        for p in prows
        if (p.period_start, p.period_end) == (window.start, window.end) and p.item_id == ""
    ]
    if exact:
        sources, children = _accumulate_traffic(exact)
        return ShopTraffic(sources, children, "period", window.days, window.days)
    if rows:
        sources, children = _accumulate_traffic(rows)
        return ShopTraffic(sources, children, "partial_daily", len(days), window.days)
    return ShopTraffic(
        {s: Agg() for s in FlowSource}, {c: Agg() for c in CARD_CHILDREN}, "none", 0, window.days
    )


@dataclass
class AdsDaily:
    """The ads section's daily figures, placed-orders basis (never mixed with confirmed)."""

    spend: Decimal
    gmv: Decimal
    orders: Decimal
    by_type: dict[str, dict[str, Decimal]]
    days_covered: int
    window_days: int

    @property
    def complete(self) -> bool:
        return self.days_covered == self.window_days


async def load_ads_daily(session: AsyncSession, shop_id: uuid.UUID, window: Window) -> AdsDaily:
    rows = await PlatformDailyMetricsRepo(session).window(
        shop_id,
        datasets=[TRAFFIC_DAILY],
        start=window.start,
        end=window.end,
        streams=["ads"],
        order_types=[PLACED],
    )
    spend = gmv = orders = ZERO
    by_type: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"spend": ZERO, "gmv": ZERO, "orders": ZERO}
    )
    days: set[date] = set()
    for r in rows:
        days.add(r.day)
        cost = _z((r.extra or {}).get("ads_expense"))
        spend += cost
        gmv += _z(r.gmv)
        orders += _z(r.orders)
        cell = by_type[r.segment]
        cell["spend"] += cost
        cell["gmv"] += _z(r.gmv)
        cell["orders"] += _z(r.orders)
    return AdsDaily(spend, gmv, orders, dict(by_type), len(days), window.days)


# ---------------------------------------------------------------------------------------
# Product x flow aggregates, product totals
# ---------------------------------------------------------------------------------------


@dataclass
class ProductFlows:
    rows: list[FlowRow]
    children: dict[str, dict[str, Agg]]  # item -> Thẻ sản phẩm child -> counts
    totals: dict[str, tuple[Decimal, int]]  # item -> (Doanh số, confirmed orders), best period
    flow_totals: dict[str, tuple[Decimal, int]]  # same, over the flows' own period (residual)
    trang_shop_split: bool
    flows_basis: PeriodChoice
    totals_basis: PeriodChoice
    source: str  # item_traffic_sources | item_by_source_period | none


def _period_key(p: Any) -> tuple[date, date]:
    return (p.period_start, p.period_end)


async def load_product_flows(
    session: AsyncSession, shop_id: uuid.UUID, window: Window
) -> ProductFlows:
    daily = await PlatformDailyMetricsRepo(session).window(
        shop_id,
        datasets=ITEM_SOURCE_DAILY,
        start=window.start,
        end=window.end,
        streams=[*STREAM_TO_SOURCE],
        order_types=[CONFIRMED],
        any_item=True,
    )
    daily = [r for r in daily if r.item_id]
    by_item: dict[str, dict[Any, Agg]] = defaultdict(lambda: defaultdict(Agg))
    children: dict[str, dict[str, Agg]] = defaultdict(lambda: {c: Agg() for c in CARD_CHILDREN})
    daily_days = {r.day for r in daily}
    prows = await PlatformPeriodMetricsRepo(session).overlapping(
        shop_id,
        datasets=[ITEM_SOURCE_PERIOD, PRODUCT_PERIOD],
        start=window.start,
        end=window.end,
        order_types=[CONFIRMED],
    )
    src_rows = [p for p in prows if p.dataset == ITEM_SOURCE_PERIOD and p.item_id]
    total_rows = [
        p for p in prows if p.dataset == PRODUCT_PERIOD and p.item_id and p.variation_id == ""
    ]

    flows_choice = PeriodChoice((), "none", 0)
    source = "none"
    trang_split = False
    if daily and len(daily_days) >= max(1, window.days // 2):
        source = "item_traffic_sources"
        flows_choice = PeriodChoice(((min(daily_days), max(daily_days)),), "daily", len(daily_days))
        for r in daily:
            if r.segment == "all":
                by_item[r.item_id][STREAM_TO_SOURCE[r.stream]].add(
                    r.impressions, r.clicks, r.orders, r.gmv
                )
            elif r.stream == "product_card" and r.segment == TRANG_SHOP_SEGMENT:
                trang_split = True
                by_item[r.item_id][FlowSource.TRANG_SHOP].add(
                    r.impressions, r.clicks, r.orders, r.gmv
                )
            elif r.stream == "product_card" and r.segment in CARD_CHILDREN:
                children[r.item_id][r.segment].add(r.impressions, r.clicks, r.orders, r.gmv)
    else:
        flows_choice = choose_periods(window, {_period_key(p) for p in src_rows})
        if flows_choice.periods:
            source = "item_by_source_period"
            chosen = set(flows_choice.periods)
            for p in src_rows:
                if _period_key(p) not in chosen:
                    continue
                if p.segment == "all" and p.stream in STREAM_TO_SOURCE:
                    by_item[p.item_id][STREAM_TO_SOURCE[p.stream]].add(
                        p.impressions, p.clicks, p.orders, p.gmv
                    )
                elif p.stream == "product_card" and p.segment == TRANG_SHOP_SEGMENT:
                    trang_split = True
                    by_item[p.item_id][FlowSource.TRANG_SHOP].add(
                        p.impressions, p.clicks, p.orders, p.gmv
                    )
                elif p.stream == "product_card" and p.segment in CARD_CHILDREN:
                    children[p.item_id][p.segment].add(p.impressions, p.clicks, p.orders, p.gmv)

    flow_rows: list[FlowRow] = []
    for item, srcs in by_item.items():
        for flow_source, agg in srcs.items():
            flow_rows.append(
                FlowRow(
                    product_id=item,
                    source=flow_source,
                    orders=int(agg.orders),
                    gmv=agg.gmv,
                    views=_int(agg.views),
                    clicks=_int(agg.clicks),
                )
            )

    totals_choice = choose_periods(window, {_period_key(p) for p in total_rows})
    totals: dict[str, tuple[Decimal, int]] = {}
    chosen_t = set(totals_choice.periods)
    for p in total_rows:
        if _period_key(p) in chosen_t:
            g, o = totals.get(p.item_id, (ZERO, 0))
            totals[p.item_id] = (g + _z(p.gmv), o + int(_z(p.orders)))
    flow_totals = totals
    if source == "item_by_source_period" and set(flows_choice.periods) != chosen_t:
        flow_totals = {}
        wanted = set(flows_choice.periods)
        for p in total_rows:
            if _period_key(p) in wanted:
                g, o = flow_totals.get(p.item_id, (ZERO, 0))
                flow_totals[p.item_id] = (g + _z(p.gmv), o + int(_z(p.orders)))
    return ProductFlows(
        flow_rows,
        {k: v for k, v in children.items()},
        totals,
        flow_totals,
        trang_split,
        flows_choice,
        totals_choice,
        source,
    )


# ---------------------------------------------------------------------------------------
# Ads reports (campaign / per-product / keyword), vouchers, promotions, affiliate
# ---------------------------------------------------------------------------------------


@dataclass
class AdsRow:
    """One row of an ads report (placed orders): campaign x product, or a campaign's own total
    row (``item_id == ''``), or campaign x product x keyword."""

    campaign: str
    key: str  # segment hash
    item_id: str
    spend: Decimal
    gmv: Decimal
    direct_gmv: Decimal
    orders: Decimal
    clicks: Decimal
    impressions: Decimal
    running: bool | None
    period: tuple[date, date]


@dataclass
class AdsReports:
    campaign_rows: list[AdsRow]
    keyword_rows: list[AdsRow]
    campaign_choice: PeriodChoice
    keyword_choice: PeriodChoice


def _ads_row(p: Any) -> AdsRow:
    extra = p.extra or {}
    return AdsRow(
        campaign=p.platform_source or "",
        key=p.segment,
        item_id=p.item_id or "",
        spend=_z(extra.get("ads_expense")),
        gmv=_z(p.gmv),
        direct_gmv=_z(extra.get("direct_sales")),
        orders=_z(p.orders),
        clicks=_z(p.clicks),
        impressions=_z(p.impressions),
        running=extra.get("running"),
        period=(p.period_start, p.period_end),
    )


def _best_report_window(window: Window, periods: set[tuple[date, date]]) -> PeriodChoice:
    """Ads reports are ~3-month windows that overlap each other: use the single one that
    overlaps the window most (exact first; on a tie the shorter report, then the later)."""
    if (window.start, window.end) in periods:
        return PeriodChoice(((window.start, window.end),), "exact", window.days)
    best = max(
        periods,
        key=lambda p: (window.overlap_days(*p), -((p[1] - p[0]).days), p[1]),
        default=None,
    )
    if best is None or window.overlap_days(*best) == 0:
        return PeriodChoice((), "none", 0)
    return PeriodChoice((best,), "overlap", window.overlap_days(*best))


def _pick_report_rows(window: Window, rows: list[Any]) -> tuple[list[AdsRow], PeriodChoice]:
    """Per campaign (its segment hash) the one report window that fits best -- the campaigns of
    one shop live in different exports (group vs general), each with its own window."""
    periods_by_key: dict[str, set[tuple[date, date]]] = defaultdict(set)
    for p in rows:
        periods_by_key[p.segment].add(_period_key(p))
    chosen = {k: _best_report_window(window, ps) for k, ps in periods_by_key.items()}
    picked = [
        _ads_row(p)
        for p in rows
        if chosen[p.segment].periods and _period_key(p) == chosen[p.segment].periods[0]
    ]
    used = tuple(sorted({c.periods[0] for c in chosen.values() if c.periods}))
    if not used:
        return picked, PeriodChoice((), "none", 0)
    exact = all(c.basis == "exact" for c in chosen.values() if c.periods)
    return picked, PeriodChoice(used, "exact" if exact else "overlap", window.days)


async def load_ads_reports(session: AsyncSession, shop_id: uuid.UUID, window: Window) -> AdsReports:
    rows = await PlatformPeriodMetricsRepo(session).overlapping(
        shop_id,
        datasets=["ads_campaign_period", "ads_keyword_period"],
        start=window.start,
        end=window.end,
        order_types=[PLACED],
    )
    camp_rows, camp_choice = _pick_report_rows(
        window, [p for p in rows if p.dataset == "ads_campaign_period"]
    )
    kw_rows, kw_choice = _pick_report_rows(
        window, [p for p in rows if p.dataset == "ads_keyword_period"]
    )
    return AdsReports(camp_rows, kw_rows, camp_choice, kw_choice)


async def load_resolved_ad_spend(
    session: AsyncSession, shop_id: uuid.UUID, window: Window
) -> AdSpendResult:
    """Ad spend by the Step 6 rule (``shopee_profit.ads_sources.resolve_ad_spend``: Connector days
    first, CSV windows for the rest, newer window wins an overlap).

    Same inputs as ``ingest.readers.load_ad_spend`` with one difference: a group campaign's own
    total row is dropped from a window that also has its per-product rows (the total is their
    sum, so keeping both counts the campaign twice).
    """
    daily = await PlatformDailyMetricsRepo(session).window(
        shop_id,
        datasets=["ads_campaign_daily"],
        start=window.start,
        end=window.end,
        streams=["ads"],
    )
    covered = {r.day for r in daily}
    days = [
        AdDay(
            campaign=r.platform_source or "",
            day=r.day,
            spend=_z((r.extra or {}).get("cost")),
            gmv=r.gmv,
            orders=r.orders,
            order_basis=r.order_type,
        )
        for r in daily
        if r.segment != "all"
    ]
    rows = [
        p
        for p in await PlatformPeriodMetricsRepo(session).overlapping(
            shop_id,
            datasets=["ads_campaign_period"],
            start=window.start,
            end=window.end,
            order_types=[PLACED],
        )
    ]
    with_products = {(p.segment, _period_key(p)) for p in rows if p.item_id}
    windows = [
        AdWindow(
            campaign=p.platform_source or "",
            start=p.period_start,
            end=p.period_end,
            spend=_z((p.extra or {}).get("ads_expense")),
            item_id=p.item_id or None,
            gmv=p.gmv,
            orders=p.orders,
            order_basis=p.order_type,
        )
        for p in rows
        if p.item_id or (p.segment, _period_key(p)) not in with_products
    ]
    return resolve_ad_spend(days, windows, window.start, window.end, covered_days=covered)


@dataclass
class VoucherRow:
    name: str
    starts_at: Any
    orders: Decimal
    gmv: Decimal
    cost: Decimal
    usage_rate: Decimal | None
    by_shopee: bool
    value_hint: Decimal | None
    period: tuple[date, date]


_VALUE_IN_NAME = re.compile(r"(\d+(?:[.,]\d+)?)\s*k\b", re.IGNORECASE)


def voucher_value_from_name(name: str) -> Decimal | None:
    """The seller names a voucher by its value ("Ory 5k" = 5.000đ); None when it does not."""
    hit = _VALUE_IN_NAME.search(name)
    if hit is None:
        return None
    return Decimal(hit.group(1).replace(",", ".")) * 1000


@dataclass
class VouchersLoad:
    rows: list[VoucherRow]
    choice: PeriodChoice


async def load_vouchers(session: AsyncSession, shop_id: uuid.UUID, window: Window) -> VouchersLoad:
    prom = await PlatformPromotionsRepo(session).overlapping(
        shop_id,
        promo_types=["voucher"],
        start=window.start,
        end=window.end,
        order_types=[CONFIRMED],
    )
    choice = choose_periods(window, {(p.period_start, p.period_end) for p in prom})
    chosen = set(choice.periods)
    out: list[VoucherRow] = []
    for p in prom:
        if (p.period_start, p.period_end) not in chosen:
            continue
        extra = p.extra or {}
        out.append(
            VoucherRow(
                name=p.program_name,
                starts_at=p.starts_at,
                orders=_z(p.orders),
                gmv=_z(p.gmv),
                cost=_z(extra.get("voucher_cost")),
                usage_rate=_d(extra.get("usage_rate")),
                by_shopee=bool(extra.get("created_by_shopee")),
                value_hint=voucher_value_from_name(p.program_name),
                period=(p.period_start, p.period_end),
            )
        )
    return VouchersLoad(out, choice)


@dataclass
class PromotionRow:
    promo_type: str
    name: str
    orders: Decimal
    gmv: Decimal
    period: tuple[date, date]


@dataclass
class PromotionsLoad:
    rows: list[PromotionRow]
    choice: PeriodChoice


async def load_promotions(
    session: AsyncSession, shop_id: uuid.UUID, window: Window
) -> PromotionsLoad:
    prom = await PlatformPromotionsRepo(session).overlapping(
        shop_id,
        promo_types=["discount", "bundle", "flash_sale", "add_on_deal"],
        start=window.start,
        end=window.end,
        order_types=[CONFIRMED],
    )
    choice = choose_periods(window, {(p.period_start, p.period_end) for p in prom})
    chosen = set(choice.periods)
    return PromotionsLoad(
        [
            PromotionRow(
                p.promo_type,
                p.program_name,
                _z(p.orders),
                _z(p.gmv),
                (p.period_start, p.period_end),
            )
            for p in prom
            if (p.period_start, p.period_end) in chosen
        ],
        choice,
    )


@dataclass
class AffiliatePartner:
    key: str
    handle: str
    orders: Decimal
    gmv: Decimal
    clicks: Decimal
    est_commission: Decimal
    period: tuple[date, date]


@dataclass
class AffiliateLoad:
    partners: list[AffiliatePartner]
    product_commission: dict[str, Decimal]
    choice: PeriodChoice


async def load_affiliate(
    session: AsyncSession, shop_id: uuid.UUID, window: Window
) -> AffiliateLoad:
    rows = await PlatformPeriodMetricsRepo(session).overlapping(
        shop_id,
        datasets=["affiliate_partner_period", "affiliate_product_period"],
        start=window.start,
        end=window.end,
        any_item=True,
    )
    partners = [p for p in rows if p.dataset == "affiliate_partner_period"]
    products = [p for p in rows if p.dataset == "affiliate_product_period"]
    choice = choose_periods(window, {_period_key(p) for p in partners})
    chosen = set(choice.periods)
    out = [
        AffiliatePartner(
            key=p.segment,
            handle=p.platform_source or "",
            orders=_z(p.orders),
            gmv=_z(p.gmv),
            clicks=_z(p.clicks),
            est_commission=_z((p.extra or {}).get("est_commission")),
            period=_period_key(p),
        )
        for p in partners
        if _period_key(p) in chosen
    ]
    pchoice = choose_periods(window, {_period_key(p) for p in products})
    pc: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for p in products:
        if _period_key(p) in set(pchoice.periods) and p.item_id:
            pc[p.item_id] += _z((p.extra or {}).get("est_commission"))
    return AffiliateLoad(out, dict(pc), choice)


async def default_as_of(session: AsyncSession, shop_id: uuid.UUID) -> date | None:
    """The newest day the shop has Shopee numbers for: shop-overview day rows, else order lines."""
    day = await PlatformDailyMetricsRepo(session).latest_day(shop_id, SHOP_OVERVIEW_DAILY)
    if day is not None:
        return day
    bounds = await ShopeeOrderLinesRepo(session).day_bounds(shop_id)
    return bounds[1] if bounds else None


# ---------------------------------------------------------------------------------------
# Product page extras: header snapshot, keyword key list, daily flow series
# ---------------------------------------------------------------------------------------


@dataclass
class ItemHeader:
    item_id: str
    title: str | None = None
    image_urls: list[str] = field(default_factory=list)
    list_price: Decimal | None = None
    current_price: Decimal | None = None
    promo_label: str | None = None
    promo_start: Any = None
    promo_end: Any = None
    stock: int | None = None
    sold_total: int | None = None
    rating: Decimal | None = None
    rating_count: int | None = None
    likes: int | None = None
    category_path: tuple[str, ...] = ()
    status: str | None = None
    created_on: date | None = None
    captured_at: Any = None
    snapshot_variations: list[dict[str, Any]] = field(default_factory=list)


async def load_item_header(
    session: AsyncSession, shop_id: uuid.UUID, item_id: str
) -> ItemHeader | None:
    rows = await PlatformItemSnapshotsRepo(session).latest_per_item(shop_id, [item_id])
    if not rows:
        return None
    head = next((r for r in rows if r.variation_id == ""), rows[0])
    return ItemHeader(
        item_id=item_id,
        title=head.title,
        image_urls=list(head.image_urls or []),
        list_price=head.list_price,
        current_price=head.current_price,
        promo_label=head.promo_label,
        promo_start=head.promo_start,
        promo_end=head.promo_end,
        stock=head.stock,
        sold_total=head.sold_total,
        rating=head.rating,
        rating_count=head.rating_count,
        likes=head.likes,
        category_path=tuple(head.category_path or ()),
        status=head.status,
        created_on=head.created_on,
        captured_at=head.captured_at,
        snapshot_variations=[
            {
                "variation_id": r.variation_id,
                "list_price": r.list_price,
                "current_price": r.current_price,
                "stock": r.stock,
            }
            for r in rows
            if r.variation_id != ""
        ],
    )


@dataclass
class KeywordSeed:
    keyword: str
    role: str
    pattern: str
    item_scope: str | None


async def load_keyword_seeds(
    session: AsyncSession, shop_id: uuid.UUID, item_id: str
) -> list[KeywordSeed]:
    out: list[KeywordSeed] = []
    for s in await ShopKeywordSeedsReadRepo(session).roled(shop_id):
        if s.item_scope == item_id or (s.item_scope is None and item_id in (s.item_ids or [])):
            out.append(KeywordSeed(s.keyword, s.role or "", s.pattern, s.item_scope))
    return out


async def load_keyword_market(session: AsyncSession, keywords: list[str]) -> dict[str, Any]:
    return {m.keyword: m for m in await MarketKeywordMetricsReadRepo(session).latest(keywords)}


async def load_freshness(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    """The newest day each stored dataset reaches, for the screens' "dữ liệu cũ" state. Day rows
    give their ``day``, period rows their ``period_end``, order lines their last order day and
    snapshots their last capture. Datasets the shop has no rows for are simply absent."""
    daily = await PlatformDailyMetricsRepo(session).latest_days(shop_id)
    periods = await PlatformPeriodMetricsRepo(session).latest_ends(shop_id)
    bounds = await ShopeeOrderLinesRepo(session).day_bounds(shop_id)
    snap = await PlatformItemSnapshotsRepo(session).latest_capture(shop_id)
    out: dict[str, Any] = {
        **{d: {"kind": "daily", "latest_day": day} for d, day in daily.items()},
        **{d: {"kind": "period", "latest_day": end} for d, end in periods.items()},
    }
    if bounds is not None:
        out["order_lines"] = {"kind": "orders", "latest_day": bounds[1]}
    if snap is not None:
        out["item_snapshots"] = {"kind": "snapshot", "latest_day": snap.date()}
    return out


@dataclass
class ProductDay:
    day: date
    gmv: Decimal
    orders: Decimal
    views: Decimal | None = None
    clicks: Decimal | None = None


async def load_product_daily(
    session: AsyncSession, shop_id: uuid.UUID, item_id: str, window: Window
) -> tuple[list[ProductDay], str]:
    """One product's GMV / orders / views / clicks per day in the window (confirmed orders,
    all flows). Source: the Connector's ``item_traffic_sources`` day rows; without them the
    order lines give GMV and orders only (views / clicks None). Returns (days, source)."""
    rows = await PlatformDailyMetricsRepo(session).window(
        shop_id,
        datasets=ITEM_SOURCE_DAILY,
        start=window.start,
        end=window.end,
        streams=[*STREAM_TO_SOURCE],
        order_types=[CONFIRMED],
        item_id=item_id,
    )
    by_day: dict[date, ProductDay] = {}
    for r in rows:
        if r.segment != "all":
            continue
        d = by_day.setdefault(r.day, ProductDay(r.day, ZERO, ZERO, ZERO, ZERO))
        d.gmv += _z(r.gmv)
        d.orders += _z(r.orders)
        d.views = (d.views or ZERO) + _z(r.impressions)
        d.clicks = (d.clicks or ZERO) + _z(r.clicks)
    if by_day:
        return [by_day[k] for k in sorted(by_day)], "item_traffic_sources"
    return [], "none"


@dataclass
class ListingSource:
    """What the listing audits read about one product: its newest snapshot (title, images,
    prices), the keyword seeds that carry a role for it and their market numbers."""

    item_id: str
    header: ItemHeader | None = None
    seeds: list[KeywordSeed] = field(default_factory=list)
    market: dict[str, Any] = field(default_factory=dict)


async def load_listing_sources(
    session: AsyncSession, shop_id: uuid.UUID, item_ids: list[str]
) -> dict[str, ListingSource]:
    """One read per table for many products (the recommendation generators audit them all)."""
    out = {i: ListingSource(i) for i in item_ids}
    if not out:
        return out
    for row in await PlatformItemSnapshotsRepo(session).latest_per_item(shop_id, list(out)):
        if row.variation_id != "":
            continue
        out[row.item_id].header = ItemHeader(
            item_id=row.item_id,
            title=row.title,
            image_urls=list(row.image_urls or []),
            list_price=row.list_price,
            current_price=row.current_price,
            promo_label=row.promo_label,
            stock=row.stock,
            category_path=tuple(row.category_path or ()),
            status=row.status,
            captured_at=row.captured_at,
        )
    for seed in await ShopKeywordSeedsReadRepo(session).roled(shop_id):
        for item_id in out:
            if seed.item_scope == item_id or (
                seed.item_scope is None and item_id in (seed.item_ids or [])
            ):
                out[item_id].seeds.append(
                    KeywordSeed(seed.keyword, seed.role or "", seed.pattern, seed.item_scope)
                )
    market = await load_keyword_market(
        session, sorted({k.keyword for src in out.values() for k in src.seeds})
    )
    for src in out.values():
        src.market = {k.keyword: market[k.keyword] for k in src.seeds if k.keyword in market}
    return out


async def load_flow_series(
    session: AsyncSession, shop_id: uuid.UUID, end: date, days: int = 400
) -> dict[str, dict[date, tuple[float, float, float, float]]]:
    """Daily (impressions, clicks, orders, gmv) per shop flow up to ``end``, confirmed orders:
    ``the_san_pham_khac`` is Thẻ sản phẩm minus its Trang shop child (contract 2)."""
    from datetime import timedelta

    start = end - timedelta(days=days - 1)
    rows = await PlatformDailyMetricsRepo(session).window(
        shop_id,
        datasets=[TRAFFIC_DAILY],
        start=start,
        end=end,
        streams=[*STREAM_TO_SOURCE],
        order_types=[CONFIRMED],
    )
    Day = tuple[float, float, float, float]
    card: dict[date, Day] = {}
    shop_page: dict[date, Day] = {}
    out: dict[str, dict[date, Day]] = {"live": {}, "video": {}, "lien_ket": {}}

    def tup(r: Any) -> Day:
        return (
            float(_z(r.impressions)),
            float(_z(r.clicks)),
            float(_z(r.orders)),
            float(_z(r.gmv)),
        )

    for r in rows:
        if r.segment == "all" and r.stream == "product_card":
            card[r.day] = tup(r)
        elif r.segment == TRANG_SHOP_SEGMENT and r.stream == "product_card":
            shop_page[r.day] = tup(r)
        elif r.segment == "all" and r.stream == "seller_live":
            out["live"][r.day] = tup(r)
        elif r.segment == "all" and r.stream == "seller_video":
            out["video"][r.day] = tup(r)
        elif r.segment == "all" and r.stream == "affiliate":
            out["lien_ket"][r.day] = tup(r)
    out["trang_shop"] = dict(shop_page)
    zero: Day = (0.0, 0.0, 0.0, 0.0)
    for d, v in card.items():
        sp = shop_page.get(d, zero)
        out.setdefault("the_san_pham_khac", {})[d] = (
            v[0] - sp[0],
            v[1] - sp[1],
            v[2] - sp[2],
            v[3] - sp[3],
        )
    return {k: v for k, v in out.items() if v}
