"""Build the materialized metrics (P97 D85.2): the shop's day, its product rows and (P98 / ADR-122
d.3) the funnel per traffic source.

``rebuild_days`` recomputes whole days from the raw tables (order lines, daily totals, traffic,
ads) through the same ``compute_view`` the screens used to run per request, then upserts
``shopee_shop_metrics_daily`` and ``shopee_product_metrics_daily``. Idempotent: the same raw data
gives the same rows (rows are upserted on their natural key; a product that left a day is
zeroed, not deleted). The product rows of a day plus the ``__residual__`` row add up to the shop
row. ``after_ingest`` is the one hook the ingest gateway calls after a write; ``backfill_shop``
walks every day a shop has data (``scripts/backfill_shopee_metrics.py``).

Source rows (``shopee_source_metrics_daily``): six per scope and day (the shop, and each product
the daily item-traffic reader covered). Lượt xem / lượt nhấp are the traffic tables'; đơn and GMV
are the ShopMetrics row's, allocated over the sources with :func:`metrics.allocate` (each
source's own traffic-table count is its weight, the shortfall to the totals is the
``chenh_lech_nguon`` weight), so the sources add up to the shop / product row exactly. After a
rebuild the hook runs the daily check (:mod:`funnel_check`), which only logs.

P99: a day that stands on a longer Shopee period (product totals without order lines, or the
period traffic table) gets its share of that period (:mod:`period_spread`), never the period
total. ``rebuild_days`` loads the shop's daily series of each period once and passes the day's
spread to the pure ``day_rows``; the rows say so (product ``source`` = ``spread_period``, shop
``sources.product_splits`` / ``sources.product_traffic`` = ``spread_product_period``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.models import Shop
from juli_backend.models.shopee_metrics import (
    FUNNEL_SOURCES,
    RESIDUAL_ITEM,
    ShopeeProductMetricsDaily,
    ShopeeShopMetricsDaily,
    ShopeeSourceMetricsDaily,
)
from juli_backend.models.shopee_profit import ShopeeOrderLine
from juli_backend.repositories import PlatformDailyMetricsRepo
from juli_backend.services.shopee_analytics import (
    funnel_check,
    loaders,
    period_spread,
    rules_view,
    service,
    stored,
    tiktok_days,
)
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.metrics import (
    SPLIT_PRODUCT_PERIOD,
    SPLIT_SPREAD_PERIOD,
    allocate,
    shop_metrics,
)
from juli_backend.services.shopee_analytics.period_spread import ShopDay, SpreadDay
from juli_backend.services.shopee_analytics.shared import order_data_days, shop_profit_raw
from juli_backend.services.shopee_analytics.stored import ORDER_TYPE
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.flows import FLOW_ORDER, RESIDUAL_KEY, FlowTable
from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_profit.order_profit import OrderStatus, counts_in_sales

logger = logging.getLogger(__name__)

#: version of the rule the stored rows are built with (``shop row detail.rows_v``). 2 (F7.10): the
#: stored profit is the unscaled known-cost profit (P100 B.5); 3 (decision #39): a product's
#: ad cost is the ads report by product (:mod:`product_ads`), ad-only days get a row; 4 (decision
#: #50): doanh thu thực subtracts only the shop voucher the seller bore (settlement); 5 (owners
#: #99 / #103): a product leaves out its cancelled lines, whose share is the shop row's
#: ``detail.cancelled_gmv`` / ``cancelled_orders``. Bump it to
#: rebuild every shop's stored days automatically (:func:`rebuild_outdated`).
ROWS_VERSION = 5
ROWS_VERSION_KEY = "rows_v"

#: ingest datasets that cannot change a day's shop or product numbers
IGNORED_DATASETS = frozenset({"market_search", "shop_health", "ads_change_log", "item_snapshot"})
#: the hook rebuilds at most this many of the newest days inline; the backfill covers older ones
HOOK_MAX_DAYS = 45
DAILY_DATASETS = ("shop_overview", "traffic_overview", "shop_traffic")
#: the source the "trong đó Quảng cáo" share sits on (ADR-122 d.3)
ADS_SOURCE = "the_san_pham_khac"
#: product x source rows only from the per-day item traffic reader (a period file is not a day)
ITEM_TRAFFIC_DAILY = "item_traffic_sources"
#: P101 W3: the platforms whose days are materialized (TikTok's from its canonical order lines
#: and A-34 analytics, :mod:`tiktok_days`). Data, not a platform check.
MATERIALIZED_PLATFORMS = stored.MATERIALIZED_PLATFORMS
#: period reports that change a stored day: the ads report by product is every product's ad cost
#: (decision #39), so an upload rebuilds the days it covers
PRODUCT_AD_DATASETS = frozenset({"ads_campaign_period"})
#: per-run day budget of :func:`rebuild_outdated` (newest days first): a 400-day shop is rebuilt
#: over several daily runs instead of one run that times out
OUTDATED_DAYS_PER_RUN = 90
#: the nightly rebuild's reach (TikTok revises its analytics; the re-read fills old days)
NIGHTLY_DAYS = 90


def _insert(session: AsyncSession) -> Any:
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert


def _money(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(Decimal("0.01"))


@dataclass
class DayRows:
    shop: dict[str, Any]
    products: list[dict[str, Any]]
    #: ``shopee_source_metrics_daily`` rows (shop rows have ``item_id`` None)
    sources: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AdsDay:
    """The day's shop ads figures (``traffic_overview`` stream ``ads``, placed orders)."""

    views: int | None
    clicks: int | None
    orders: int | None
    gmv: Decimal | None
    spend: Decimal | None


@dataclass(frozen=True)
class SourceSplit:
    """One source of one scope: traffic-table views / clicks, allocated đơn / GMV / profit."""

    source: str
    views: int | None
    clicks: int | None
    orders: int
    gmv: Decimal
    profit: Decimal | None
    #: the source's own traffic-table đơn / GMV were changed to fit the totals
    scaled: bool


def split_sources(
    table: FlowTable | None,
    orders: int | None,
    gmv: Decimal | None,
    profit: Decimal | None,
) -> list[SourceSplit]:
    """Allocate a scope's totals over the six sources (ADR-122 d.3). Pure.

    Each flow's own traffic-table đơn (GMV) is its weight and the shortfall of the flows to the
    total is the residual's weight, so when Shopee assigns less than the total every flow keeps
    its own count and ``chenh_lech_nguon`` holds the rest; when it assigns more, the flows are
    scaled down and the residual is 0. The sources add up to ``orders`` / ``gmv`` / ``profit``
    exactly (whole đơn; GMV and profit to the đồng, any sub-đồng part on the residual). Profit is
    split like the allocated GMV; None stays None ("chưa tính"). Residual đơn whose GMV the flows
    already took weigh at the scope's AOV, so ``chenh_lech_nguon`` never holds 0đ đơn."""
    total_orders = Decimal(orders or 0)
    total_gmv = gmv if gmv is not None else ZERO
    own: dict[str, tuple[int | None, int | None, int, Decimal]] = {}
    for f in FLOW_ORDER:
        row = table.row(f.value) if table is not None else None
        own[f.value] = (
            (row.views, row.clicks, row.orders, row.gmv) if row else (None, None, 0, ZERO)
        )
    w_orders = {k: Decimal(max(v[2], 0)) for k, v in own.items()}
    w_gmv = {k: max(v[3], ZERO) for k, v in own.items()}
    w_orders[RESIDUAL_KEY] = max(total_orders - sum(w_orders.values(), ZERO), ZERO)
    w_gmv[RESIDUAL_KEY] = max(total_gmv - sum(w_gmv.values(), ZERO), ZERO)
    a_orders = allocate(total_orders, w_orders)
    if a_orders[RESIDUAL_KEY] > 0 and w_gmv[RESIDUAL_KEY] <= 0 and total_orders > 0:
        # đơn the sources leave out carry the scope's AOV, never 0đ (P99): the flows give way
        kept = (total_gmv * a_orders[RESIDUAL_KEY] / total_orders).quantize(Decimal(1))
        a_gmv = allocate(total_gmv - kept, {k: w_gmv[k] for k in own})
        a_gmv[RESIDUAL_KEY] = kept
    else:
        a_gmv = allocate(total_gmv, w_gmv)
    a_gmv[RESIDUAL_KEY] = total_gmv - sum((a_gmv[k] for k in own), ZERO)
    a_profit: dict[str, Decimal | None] = {k: None for k in FUNNEL_SOURCES}
    if profit is not None:
        weights = {k: a_gmv[k] for k in own if a_gmv[k] > 0}
        shares = allocate(profit, weights) if weights else {}
        a_profit = {k: shares.get(k, ZERO) for k in own}
        a_profit[RESIDUAL_KEY] = profit - sum(shares.values(), ZERO)
    out = [
        SourceSplit(
            k,
            v[0],
            v[1],
            int(a_orders[k]),
            a_gmv[k],
            a_profit[k],
            int(a_orders[k]) != v[2] or a_gmv[k] != v[3],
        )
        for k, v in own.items()
    ]
    out.append(
        SourceSplit(
            RESIDUAL_KEY,
            None,
            None,
            int(a_orders[RESIDUAL_KEY]),
            a_gmv[RESIDUAL_KEY],
            a_profit[RESIDUAL_KEY],
            False,
        )
    )
    return out


def source_rows(
    splits: list[SourceSplit],
    *,
    shop_id: uuid.UUID,
    day: date,
    item_id: str | None,
    ads: AdsDay | None,
) -> list[dict[str, Any]]:
    """The table rows of one scope's splits; the ads share goes on :data:`ADS_SOURCE` only."""
    rows: list[dict[str, Any]] = []
    for s in splits:
        a = ads if s.source == ADS_SOURCE else None
        rows.append(
            {
                "shop_id": shop_id,
                "day": day,
                "item_id": item_id,
                "source": s.source,
                "views": s.views,
                "clicks": s.clicks,
                "orders": s.orders,
                "gmv": _money(s.gmv),
                "profit": _money(s.profit),
                "ads_views": a.views if a else None,
                "ads_clicks": a.clicks if a else None,
                "ads_orders": a.orders if a else None,
                "ads_gmv": _money(a.gmv) if a else None,
                "ads_spend": _money(a.spend) if a else None,
                "scaled_to_totals": s.scaled,
            }
        )
    return rows


def _shop_table(view: PeriodView) -> FlowTable | None:
    if view.flows is None:
        return None
    if view.data.traffic.basis == "none" and view.data.product_flows.source != ITEM_TRAFFIC_DAILY:
        return None
    return view.flows.shop


def _funnel(rows: Any) -> tuple[int | None, int | None]:
    views = [r.views for r in rows if not r.is_residual and r.views is not None]
    clicks = [r.clicks for r in rows if not r.is_residual and r.clicks is not None]
    return (sum(views) if views else None, sum(clicks) if clicks else None)


def _ads_gmv(view: PeriodView) -> Decimal:
    """The ads GMV that goes with the day's ``ads_spend``: both from the one per-day figure
    (:func:`loaders.load_ad_days`), so the stored ROAS never divides one source's GMV by another's
    spend (P100 A.5)."""
    return view.data.ads_daily.gmv


def _no_order_day_profit(view: PeriodView, day: date) -> Decimal | None:
    """R11 for one stored day: a day Shopee's order data speaks for with spend and NO counted
    order line is charged whole to the shop profit (the window headline subtracts it), so the day
    stores ``-spend`` and the days sum to the headline. A day whose orders all lack costs stays
    None (missing is not zero)."""
    if any(
        pb.excluded_reason is None or getattr(ln, "status", None) is OrderStatus.IN_TRANSIT
        for ln, pb in view.pairs
    ):
        return None  # C1: in-transit orders are orders whose costs are not known yet
    spent = view.data.ads_daily.spend_by_day.get(day, ZERO)
    days = order_data_days(view)
    if spent > 0 and (days is None or day in days):
        return -spent.quantize(Decimal(1))
    return None


def day_rows(
    view: PeriodView,
    shop_id: uuid.UUID,
    day: date,
    traffic_tag: str,
    ads: AdsDay | None = None,
    spread: Mapping[str, SpreadDay] | None = None,
) -> DayRows:
    """The rows of one day from its (one-day) view. Pure. ``spread`` = each product's share of
    the longer Shopee period the day stands on (:func:`period_spread.day_spread`)."""
    spread = spread or {}
    m = shop_metrics(view, spread=spread)
    traffic_spread = {i: s for i, s in spread.items() if s.traffic_period is not None}
    p = view.profit
    ad_source = view.data.ads_daily.source_by_day.get(day)
    # P100 B.2: a day is complete when Shopee posted its daily totals (shop_overview); a day
    # without traffic_overview keeps views / clicks None, it no longer holds the window back
    complete = view.data.totals.basis == "daily"
    sources = {
        "gmv": "shop_totals" if view.data.totals.basis == "daily" else "order_lines",
        "orders": "shop_totals" if view.data.totals.basis == "daily" else "order_lines",
        "views": traffic_tag,
        "product_clicks": traffic_tag,
        # P100 A.5: the day's ad spend names its own source (connector / daily_report /
        # period_spread); a day with none is NULL below, never 0
        "ads_spend": ad_source or "none",
        "profit": "order_lines",
    }
    if any(s.basis == SPLIT_SPREAD_PERIOD for s in m.splits.values()):
        sources["product_splits"] = SPLIT_SPREAD_PERIOD
    shop_views, shop_clicks = m.views, m.clicks
    if traffic_spread:
        sources["product_traffic"] = SPLIT_SPREAD_PERIOD
        if view.data.traffic.basis == "none":  # the shop table is the products' period flows
            v = [t.views for t in traffic_spread.values() if t.views is not None]
            c = [t.clicks for t in traffic_spread.values() if t.clicks is not None]
            shop_views, shop_clicks = (sum(v) if v else None), (sum(c) if c else None)
    covered = p.buyer_paid_covered
    # P100 B.5 / F7.10: the stored profit is the known-cost figure of the day, never scaled to
    # the shop totals: the one ``shop_profit_of`` the dashboard headline shows
    day_profit = shop_profit_raw(view).profit  # R1: stored raw, the readers gate
    if day_profit is None:
        day_profit = _no_order_day_profit(view, day)
    net_gmv = sum(
        (ln.order_value - ln.shop_voucher_share for ln, _ in view.pairs if counts_in_sales(ln)),
        ZERO,
    )
    shop = {
        "shop_id": shop_id,
        "day": day,
        "order_type": ORDER_TYPE,
        "gmv": _money(m.gmv),
        "orders": m.orders,
        "aov": _money(m.aov),
        "units": m.units or None,
        "views": shop_views,
        "visitors": None,
        "product_clicks": shop_clicks,
        "ads_spend": _money(m.ad_spend) if ad_source else None,
        "ads_gmv": _money(_ads_gmv(view)) if ad_source else None,
        "profit": _money(day_profit),
        "margin_profit": _money(p.covered_margin_profit),
        "buyer_paid_known": _money(covered),
        "cogs_coverage": None
        if not p.buyer_paid
        else (covered / p.buyer_paid).quantize(Decimal("0.0001")),
        "line_gmv": _money(m.line_gmv),
        "line_orders": m.line_orders,
        "sources": sources,
        "detail": {
            "aov_sc_net_gmv": None if not m.line_orders else str(net_gmv),
            "profit_partial": bool(m.profit_is_partial),
            ROWS_VERSION_KEY: ROWS_VERSION,
            **(
                {"cancelled_gmv": str(m.cancelled_gmv), "cancelled_orders": m.cancelled_orders}
                if m.cancelled_gmv or m.cancelled_orders
                else {}
            ),
        },
        "complete": complete,
    }
    products: list[dict[str, Any]] = []
    shop_profit = None if m.profit_is_partial else day_profit
    funnel = source_rows(
        split_sources(_shop_table(view), m.orders, m.gmv, shop_profit),
        shop_id=shop_id,
        day=day,
        item_id=None,
        ads=ads,
    )
    product_profit: dict[str, Decimal | None] = {}
    spent = ZERO
    for item_id, s in sorted(m.splits.items()):
        flow = view.flows.products.get(item_id) if view.flows else None
        views, clicks = _funnel(flow.rows) if flow else (None, None)
        if item_id in traffic_spread:
            views, clicks = traffic_spread[item_id].views, traffic_spread[item_id].clicks
        pp = p.products.get(item_id)
        # P100-A (A.2): a product with an order whose cost is unknown has no day profit (NULL,
        # out of the funnel's profit coverage), never the known part or 0
        profit = pp.profit if pp is not None and not (pp.buyer_paid > 0 and pp.is_partial) else None
        product_profit[item_id] = profit
        spent += s.gmv
        products.append(
            {
                "shop_id": shop_id,
                "day": day,
                "order_type": ORDER_TYPE,
                "item_id": item_id,
                "variation_id": None,
                "gmv": _money(s.gmv),
                "orders": s.orders,
                "units": s.units,
                "views": views,
                "clicks": clicks,
                "ads_spend": _money(view.ads.product_spend.get(item_id)),
                "profit": _money(profit),
                "line_gmv": _money(s.line_gmv),
                "line_orders": s.line_orders,
                "source": _row_source(s.basis),
                "scaled_to_totals": s.basis
                in ("scaled_order_lines", SPLIT_PRODUCT_PERIOD, SPLIT_SPREAD_PERIOD),
            }
        )
    # decision #39: a product with an ad cost this day but no order is not dropped: its row has no
    # sale, the day's ad cost, and the profit it makes (minus that cost; no order = no cost gap)
    for item_id, ad_cost in sorted(view.ads.product_spend.items()):
        if item_id in m.splits or item_id == RESIDUAL_ITEM:
            continue
        products.append(
            {
                "shop_id": shop_id,
                "day": day,
                "order_type": ORDER_TYPE,
                "item_id": item_id,
                "variation_id": None,
                "gmv": ZERO,
                "orders": 0,
                "units": 0,
                "views": None,
                "clicks": None,
                "ads_spend": _money(ad_cost),
                "profit": _money(-ad_cost),
                "line_gmv": ZERO,
                "line_orders": 0,
                "source": "order_lines",
                "scaled_to_totals": False,
            }
        )
    residual = (m.gmv - spent) if m.gmv is not None else ZERO
    products.append(
        {
            "shop_id": shop_id,
            "day": day,
            "order_type": ORDER_TYPE,
            "item_id": RESIDUAL_ITEM,
            "variation_id": None,
            "gmv": _money(residual),
            "orders": 0,
            "units": 0,
            "views": None,
            "clicks": None,
            "ads_spend": None,
            "profit": None,
            "line_gmv": ZERO,
            "line_orders": 0,
            "source": "shop_totals",
            "scaled_to_totals": False,
        }
    )
    if view.flows is not None and view.data.product_flows.source == ITEM_TRAFFIC_DAILY:
        for item_id, table in sorted(view.flows.products.items()):
            sp = m.splits.get(item_id)
            funnel += source_rows(
                split_sources(
                    table,
                    sp.orders if sp else 0,
                    sp.gmv if sp else ZERO,
                    product_profit.get(item_id) if sp else None,
                ),
                shop_id=shop_id,
                day=day,
                item_id=item_id,
                ads=_product_ads(view, item_id),
            )
    return DayRows(shop, products, funnel)


def _row_source(basis: str) -> str:
    if basis == SPLIT_SPREAD_PERIOD:
        return period_spread.ROW_SOURCE
    return "file" if basis == SPLIT_PRODUCT_PERIOD else "order_lines"


def _product_ads(view: PeriodView, item_id: str) -> AdsDay | None:
    """A product's ads share: the spend allocated to it (as ``shopee_product_metrics_daily``)
    and the ads report's direct GMV; Shopee posts no per-product daily views / clicks / đơn."""
    spend = view.ads.product_spend.get(item_id)
    fig = view.ads.product_figures.get(item_id)
    if spend is None and fig is None:
        return None
    return AdsDay(None, None, None, fig.direct_gmv if fig else None, spend)


def _whole_of(rows: list[Any]) -> list[Any]:
    """The day's ads total of one order type: Shopee's own ``all`` row, else its types."""
    total = [r for r in rows if r.segment == "all"]
    return total or rows


def _sum_attr(rows: Iterable[Any], attr: str) -> Decimal | None:
    values = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
    return sum(values, ZERO) if values else None


def _ratio(confirmed: Decimal | None, placed: Decimal | None) -> Decimal | None:
    return None if confirmed is None or placed is None or placed <= 0 else confirmed / placed


def ads_overlay(rows: list[Any], card_rows: list[Any]) -> AdsDay | None:
    """The day's "trong đó Quảng cáo" overlay of Thẻ sản phẩm (pure).

    ``rows``: the day's ``traffic_overview`` ads-stream rows (both order types); ``card_rows``:
    its product-card ``all`` rows (both order types).

    P100 B.4b -- **one order basis, confirmed** (the sources' ShopMetrics basis): the confirmed
    ads row when Shopee posted one; else the placed row put on the confirmed basis by the card's
    own confirmed ÷ placed ratio (orders by orders, GMV by GMV); else the placed figure as read.
    Views / clicks are the overlay's own (traffic-overview base), never borrowed from another
    report: when they are missing the Quảng cáo row takes both from the ads report at read time
    (:func:`channel_split.split_rows`), so its CTR stays on one basis. A type row is never added
    to the day's own total row."""
    if not rows:
        return None
    confirmed = _whole_of([r for r in rows if r.order_type == loaders.CONFIRMED])
    placed = _whole_of([r for r in rows if r.order_type == loaders.PLACED])
    seen = confirmed or placed

    def whole(value: Decimal | None) -> int | None:
        return None if value is None else int(value)

    views, clicks = _sum_attr(seen, "impressions"), _sum_attr(seen, "clicks")
    if confirmed:
        orders, gmv = _sum_attr(confirmed, "orders"), _sum_attr(confirmed, "gmv")
    else:
        orders, gmv = _sum_attr(placed, "orders"), _sum_attr(placed, "gmv")
        card_c = [r for r in card_rows if r.order_type == loaders.CONFIRMED]
        card_p = [r for r in card_rows if r.order_type == loaders.PLACED]
        k_orders = _ratio(_sum_attr(card_c, "orders"), _sum_attr(card_p, "orders"))
        k_gmv = _ratio(_sum_attr(card_c, "gmv"), _sum_attr(card_p, "gmv"))
        if orders is not None and k_orders is not None:
            orders = (orders * k_orders).quantize(Decimal(1))
        if gmv is not None and k_gmv is not None:
            gmv = gmv * k_gmv
    spend_rows = placed or confirmed
    spend = sum((Decimal(str((r.extra or {}).get("ads_expense") or 0)) for r in spend_rows), ZERO)
    return AdsDay(whole(views), whole(clicks), whole(orders), gmv, spend)


async def _ads_day(session: AsyncSession, shop_id: uuid.UUID, day: date) -> AdsDay | None:
    repo = PlatformDailyMetricsRepo(session)
    rows = await repo.window(
        shop_id,
        datasets=[loaders.TRAFFIC_DAILY],
        start=day,
        end=day,
        streams=["ads", "product_card"],
        order_types=[loaders.PLACED, loaders.CONFIRMED],
    )
    ads = [r for r in rows if r.stream == "ads" and not r.item_id]
    card = [r for r in rows if r.stream == "product_card" and r.segment == "all" and not r.item_id]
    if not ads:
        return None
    return ads_overlay(ads, card)


async def _traffic_tag(session: AsyncSession, shop_id: uuid.UUID, day: date) -> str:
    rows = await PlatformDailyMetricsRepo(session).window(
        shop_id,
        datasets=[loaders.TRAFFIC_DAILY],
        start=day,
        end=day,
        streams=["product_card"],
        order_types=[loaders.CONFIRMED],
    )
    tags = {str(getattr(r, "source", "")) for r in rows}
    return "connector" if "connector" in tags else "file"


async def _upsert(
    session: AsyncSession,
    model: Any,
    values: list[dict[str, Any]],
    keys: tuple[str, ...],
    where: Any = None,
) -> None:
    if not values:
        return
    insert = _insert(session)
    now = datetime.now(UTC).replace(tzinfo=None)
    stmt = insert(model).values([{**v, "id": uuid.uuid4(), "built_at": now} for v in values])
    update = {
        c.name: stmt.excluded[c.name]
        for c in model.__table__.columns
        if c.name not in ("id", "shop_id", *keys)
    }
    await session.execute(
        stmt.on_conflict_do_update(index_elements=list(keys), index_where=where, set_=update)
    )


async def rebuild_days(session: AsyncSession, shop_id: uuid.UUID, days: Iterable[date]) -> int:
    """Recompute and upsert these days. Returns the number of days written."""
    wanted = sorted(set(days))
    if not wanted:
        return 0
    ctx0 = await loaders.load_context(session, shop_id)
    shop = await session.get(Shop, shop_id)
    settlement_only = shop is not None and shop.platform in tiktok_days.SETTLEMENT_ONLY_PLATFORMS
    if settlement_only:  # P101 W3 (M-5): a TikTok order's fees are its settlement's, never Shopee's
        ctx0 = replace(ctx0, formula_rows=[])
    series: dict[period_spread.Period, dict[date, ShopDay]] = {}  # one read per period
    # P101 W3: a shop's daily analytics (none for a Shopee shop: nothing below changes for it)
    analytics = await tiktok_days.load_days(session, shop_id, wanted)
    analytics_known = await tiktok_days.headline_days(session, shop_id)
    for day in wanted:
        ctx = replace(ctx0, rules=ctx0.rules.for_month(f"{day:%Y-%m}"))
        view = await service.load_view(session, shop_id, ctx, Window(day, day))
        shop_days: dict[date, ShopDay] = {}
        for period in period_spread.periods_to_load(view.data.product_flows, day):
            if period not in series:
                series[period] = await period_spread.load_shop_days(session, shop_id, period)
            shop_days.update(series[period])
        rows = day_rows(
            view,
            shop_id,
            day,
            await _traffic_tag(session, shop_id, day),
            await _ads_day(session, shop_id, day),
            period_spread.for_view(view, day, shop_days),
        )
        rows = _with_analytics(rows, analytics, analytics_known, shop_id, day)
        if settlement_only:
            rows = tiktok_days.settled_profit_only(rows, tiktok_days.unsettled_items(view))
            rows = tiktok_days.without_ads_profit(rows)  # owner W3-Q5 = a
        have = set(
            (
                await session.execute(
                    select(ShopeeProductMetricsDaily.item_id).where(
                        ShopeeProductMetricsDaily.shop_id == shop_id,
                        ShopeeProductMetricsDaily.day == day,
                        ShopeeProductMetricsDaily.order_type == ORDER_TYPE,
                    )
                )
            )
            .scalars()
            .all()
        )
        now_items = {r["item_id"] for r in rows.products}
        for gone in sorted(have - now_items):  # left the day: zeroed, not deleted
            rows.products.append(
                {
                    "shop_id": shop_id, "day": day, "order_type": ORDER_TYPE, "item_id": gone,
                    "variation_id": None, "gmv": ZERO, "orders": 0, "units": 0, "views": None,
                    "clicks": None, "ads_spend": None, "profit": None, "line_gmv": ZERO,
                    "line_orders": 0, "source": "order_lines", "scaled_to_totals": False,
                }
            )  # fmt: skip
        await _upsert(
            session, ShopeeShopMetricsDaily, [rows.shop], ("shop_id", "day", "order_type")
        )
        await _upsert(
            session,
            ShopeeProductMetricsDaily,
            rows.products,
            ("shop_id", "day", "order_type", "item_id"),
        )
        await _upsert_sources(session, shop_id, day, rows.sources)
    await session.flush()
    return len(wanted)


def _with_analytics(
    rows: DayRows,
    analytics: Mapping[date, tiktok_days.AnalyticsDay],
    known: list[date],
    shop_id: uuid.UUID,
    day: date,
) -> DayRows:
    """P101 W3: the day's analytics over its order-line rows when they cover it; else the day
    says up to which day they do. A shop with no analytics rows is returned unchanged."""
    found = analytics.get(day)
    if found is not None and tiktok_days.covers(found, rows.shop["line_orders"]):
        return tiktok_days.overlay(rows, found, shop_id=shop_id, day=day)
    if not known:
        return rows
    before = [d for d in known if d < day]
    return tiktok_days.mark_through(rows, before[-1] if before else None)


async def _upsert_sources(
    session: AsyncSession, shop_id: uuid.UUID, day: date, rows: list[dict[str, Any]]
) -> None:
    """Shop and product source rows; a product that left the day is zeroed, not deleted."""
    t = ShopeeSourceMetricsDaily
    found = await session.execute(
        select(t.item_id)
        .where(t.shop_id == shop_id, t.day == day, t.item_id.is_not(None))
        .distinct()
    )
    had = {i for i in found.scalars().all() if i is not None}
    items = [r for r in rows if r["item_id"] is not None]
    for gone in sorted(had - {r["item_id"] for r in items}):
        items += source_rows(
            split_sources(None, 0, ZERO, None), shop_id=shop_id, day=day, item_id=gone, ads=None
        )
    shop_rows = [r for r in rows if r["item_id"] is None]
    if len(shop_rows) < len(FUNNEL_SOURCES):
        # W3.1: a TikTok day without A-34 blocks writes only its residual row; the source rows an
        # earlier build stored (0 đơn, read as a count) go. Shopee always writes all six.
        await session.execute(
            delete(t).where(
                t.shop_id == shop_id,
                t.day == day,
                t.item_id.is_(None),
                t.source.not_in([r["source"] for r in shop_rows]),
            )
        )
    await _upsert(
        session,
        t,
        shop_rows,
        ("shop_id", "day", "source"),
        t.item_id.is_(None),
    )
    await _upsert(
        session, t, items, ("shop_id", "day", "item_id", "source"), t.item_id.is_not(None)
    )


async def outdated_days(session: AsyncSession, shop_id: uuid.UUID) -> list[date]:
    """The stored days built by an older rule (``detail.rows_v`` below :data:`ROWS_VERSION`)."""
    rows = await session.execute(
        select(ShopeeShopMetricsDaily.day, ShopeeShopMetricsDaily.detail).where(
            ShopeeShopMetricsDaily.shop_id == shop_id,
            ShopeeShopMetricsDaily.order_type == ORDER_TYPE,
        )
    )
    return sorted(
        d for d, detail in rows.all() if (detail or {}).get(ROWS_VERSION_KEY) != ROWS_VERSION
    )


async def rebuild_outdated(
    session: AsyncSession, shop_id: uuid.UUID, *, limit: int = OUTDATED_DAYS_PER_RUN
) -> int:
    """F7.10: rebuild the stored days an older rule built (automatic, no manual step; the daily
    learning / measurement job calls it first). Never raises: a failed rebuild is logged and
    retried next day. Returns the days rebuilt."""
    days = (await outdated_days(session, shop_id))[-limit:]
    if not days:
        return 0
    try:
        async with session.begin_nested():
            return await rebuild_days(session, shop_id, days)
    except (SQLAlchemyError, RuntimeError, ArithmeticError, LookupError, TypeError, ValueError):
        logger.warning(
            "shopee_metrics_outdated_rebuild_failed",
            extra={"shop_id": str(shop_id), "days": len(days)},
            exc_info=True,
        )
        return 0


async def rebuild_recent(
    session: AsyncSession, shop_id: uuid.UUID, *, today: date, days: int = NIGHTLY_DAYS
) -> int:
    """P101 W3 nightly: rebuild every data day of the last ``days`` days (TikTok revises its
    analytics for days already stored, and the A-34 re-read fills older days with the channel
    blocks). Automatic, no manual step. Never raises: a failed rebuild is logged and retried the
    next night. Returns the days rebuilt."""
    first = today - timedelta(days=days)
    wanted = [d for d in await data_days(session, shop_id) if first <= d <= today]
    if not wanted:
        return 0
    try:
        async with session.begin_nested():
            return await rebuild_days(session, shop_id, wanted)
    except (SQLAlchemyError, RuntimeError, ArithmeticError, LookupError, TypeError, ValueError):
        logger.warning(
            "shop_metrics_nightly_rebuild_failed",
            extra={"shop_id": str(shop_id), "days": len(wanted)},
            exc_info=True,
        )
        return 0


def days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


async def after_ingest(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    platform: str,
    dataset: str,
    start: date,
    end: date,
) -> None:
    """The hook the ingest gateway calls after a (non-duplicate) write: rebuild the affected
    days. Never raises into the ingest: a failed rebuild is logged and the backfill repairs it."""
    if (
        platform not in MATERIALIZED_PLATFORMS
        or dataset in IGNORED_DATASETS
        or (dataset.endswith("_period") and dataset not in PRODUCT_AD_DATASETS)
    ):
        return
    days = days_between(start, end)[-HOOK_MAX_DAYS:]
    try:
        async with session.begin_nested():
            await rebuild_days(session, shop_id, days)
    except (SQLAlchemyError, RuntimeError, ArithmeticError, LookupError, TypeError, ValueError):
        # the ingest must not fail because a derived table did
        logger.warning(
            "shopee_metrics_rebuild_failed",
            extra={"shop_id": str(shop_id), "dataset": dataset, "days": len(days)},
            exc_info=True,
        )
        return
    await funnel_check.check_days(session, shop_id, days)  # logs only, never raises


async def data_days(session: AsyncSession, shop_id: uuid.UUID) -> list[date]:
    """Every day the shop has order lines or daily Shopee rows for, plus (P100-A, A.3) every day
    that already has a stored row: a day built by an ingest hook over a range but holding no data
    of its own (rows stamped before the P99 spread) is rewritten too, never left stale."""
    out: set[date] = set()
    built = await session.execute(
        select(ShopeeProductMetricsDaily.day)
        .where(ShopeeProductMetricsDaily.shop_id == shop_id)
        .distinct()
    )
    out.update(built.scalars().all())
    lines = await session.execute(
        select(ShopeeOrderLine.day).where(ShopeeOrderLine.shop_id == shop_id).distinct()
    )
    out.update(lines.scalars().all())
    daily = await session.execute(
        select(PlatformDailyMetric.day)
        .where(
            PlatformDailyMetric.shop_id == shop_id,
            PlatformDailyMetric.platform.in_(MATERIALIZED_PLATFORMS),
            PlatformDailyMetric.dataset.in_(DAILY_DATASETS),
        )
        .distinct()
    )
    out.update(daily.scalars().all())
    out.update(await tiktok_days.analytics_days(session, shop_id))  # P101 W3 (TikTok only)
    return sorted(out)


#: the seller rules the stored rows are computed with (giá vốn, đóng gói, pack, VAT, exclusions):
#: a change to any of them makes every stored day stale. Targets and discount caps are not in rows.
PROFIT_RULE_KEYS: frozenset[str] = frozenset(
    {
        rules_view.SKU_COST,
        rules_view.PRODUCT_COST,
        rules_view.PACKAGING_COST,
        rules_view.PACK_COUNT,
        rules_view.PACK_COMPONENTS,
        rules_view.VAT_RATE,
        rules_view.VAT_RATE_DEFAULT,
        rules_view.PRICES_INCLUDE_VAT,
        rules_view.COST_INCLUDES_VAT,
        rules_view.EXCLUDED,
        rules_view.EXCLUDE_REASON,
    }
)


@dataclass(frozen=True)
class RuleRebuild:
    """What :func:`after_rules_change` did: ``days`` rebuilt, or ``cleared`` (the rebuild failed,
    the stale rows were removed so the screens say "đang tính lại", never the old profit)."""

    days: int = 0
    cleared: int = 0


async def _clear_days(session: AsyncSession, shop_id: uuid.UUID, days: list[date]) -> None:
    for model in (ShopeeShopMetricsDaily, ShopeeProductMetricsDaily, ShopeeSourceMetricsDaily):
        await session.execute(delete(model).where(model.shop_id == shop_id, model.day.in_(days)))
    await session.flush()


async def after_rules_change(
    session: AsyncSession, shop_id: uuid.UUID, rule_keys: Iterable[str]
) -> RuleRebuild:
    """P99c: a saved giá vốn / đóng gói / pack / VAT / exclusion rule makes the stored rows stale
    (they hold profit computed with the old rule). Rules carry no effective dates (the current
    value applies to every day), so every data day of the shop is rebuilt, synchronously in the
    caller's transaction: the new rule and the new rows commit together, no reader ever sees the
    old profit beside the new rule. A failed rebuild removes those days' rows instead (the screens
    answer ``rows_not_materialized`` "đang tính lại" until the backfill rebuilds them)."""
    if not PROFIT_RULE_KEYS.intersection(rule_keys):
        return RuleRebuild()
    days = await data_days(session, shop_id)
    if not days:
        return RuleRebuild()
    try:
        async with session.begin_nested():
            written = await rebuild_days(session, shop_id, days)
    except (SQLAlchemyError, RuntimeError, ArithmeticError, LookupError, TypeError, ValueError):
        logger.warning(
            "shopee_metrics_rule_rebuild_failed",
            extra={"shop_id": str(shop_id), "days": len(days)},
            exc_info=True,
        )
        await _clear_days(session, shop_id, days)
        return RuleRebuild(cleared=len(days))
    return RuleRebuild(days=written)


@dataclass
class BackfillReport:
    days_found: int
    days_written: int
    first: date | None
    last: date | None
    #: ``funnel_check`` findings over the rebuilt days (logged, never corrected)
    mismatches: int = 0


async def backfill_shop(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    start: date | None = None,
    end: date | None = None,
) -> BackfillReport:
    """Rebuild every day the shop has data for (optionally clipped to ``start``..``end``)."""
    days = [
        d
        for d in await data_days(session, shop_id)
        if (not start or d >= start) and (not end or d <= end)
    ]
    written = await rebuild_days(session, shop_id, days)
    found = await funnel_check.check_days(session, shop_id, days)
    return BackfillReport(
        len(days), written, days[0] if days else None, days[-1] if days else None, len(found)
    )


__all__ = [
    "MATERIALIZED_PLATFORMS",
    "PROFIT_RULE_KEYS",
    "AdsDay",
    "RuleRebuild",
    "SourceSplit",
    "after_ingest",
    "after_rules_change",
    "backfill_shop",
    "day_rows",
    "rebuild_days",
    "rebuild_recent",
    "source_rows",
    "split_sources",
]
