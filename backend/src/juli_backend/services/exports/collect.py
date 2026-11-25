"""Reads the numbers of the two exports through the app's own service functions.

Nothing is computed here that a service already computes: the channel table comes from
``channel_split`` (the Tổng quan numbers, shop and each product), the month figures from
``month_plan``, the cards and their Δ from ``plans.get_plan`` / ``service.list_cards``, the daily
rows from the stored funnel rows (``funnel.load_rows``: the shopee metrics tables) and the ads
report's ``spend_by_day``.

Baseline and goal (Tổng quan, shop / product / day, and the Kế hoạch month): the app's own
``month_plan.range_plan`` / ``month_plans`` of the exported period and level, so a figure in the
file is the figure of the screen's Kế hoạch card / Kế hoạch totals. No running card -> no goal.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_tenant_scope
from juli_backend.models.shopee_plans import PLAN_DRAFT, PLAN_EXECUTED
from juli_backend.services.exports import ke_hoach_xlsx as kh
from juli_backend.services.exports import report_calc as calc
from juli_backend.services.exports import report_sheets as rs
from juli_backend.services.exports import sku as skumod
from juli_backend.services.exports import tong_quan_xlsx as tq
from juli_backend.services.exports.profit_bridge import profit_bridge
from juli_backend.services.shopee_analytics import (
    NoShopeeData,
    RowsNotMaterialized,
    channel_split,
    funnel,
    loaders,
    metric_view,
    queries,
    service,
)
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.shared import shop_profit_of
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.ladder import unknown_orders
from juli_backend.services.shopee_recommendations import (
    change_sets,
    execution_state,
    kinds,
    month_plan,
    plan_groups,
    plans,
)
from juli_backend.services.shopee_recommendations import service as reco_service
from juli_backend.services.stock_alert import data as stock_data
from juli_backend.services.stock_alert import forecast as stock_forecast
from juli_backend.services.stock_alert import stock_basis

_CHANNEL_FIELDS = ("views", "clicks", "orders", "gmv", "cost")
#: order lines whose SKU matched no listing ("sku:…" product ids)
UNMATCHED_PREFIX = "sku:"
UNMATCHED_LABEL = "Đơn không khớp sản phẩm"
METRIC_LABELS = {
    "views": "Lượt xem", "ctr": "CTR", "ctor": "CTOR", "aov": "AOV", "orders": "Đơn",
    "ads_gmv": "GMV quảng cáo", "roas": "ROAS",
}  # fmt: skip
GROUP_OF_FAMILY = {
    "voucher": "Ưu đãi", "promotion": "Ưu đãi", "sale": "Ưu đãi", "combo": "Ưu đãi",
    "mega_sale": "Ưu đãi", "listing": "Listing", "ads": "Truy cập", "affiliate": "Truy cập",
}  # fmt: skip
KEY_OF_ROW = {"organic": "organic", "ads": "ads", "affiliate": "affiliate"}


def _f(x: Any) -> float | None:
    return None if x is None else float(x)


# ----------------------------------------------------------------------------- period reads


async def _view(
    session: AsyncSession, shop_id: uuid.UUID, window: Window
) -> tuple[PeriodView, funnel.FunnelRows]:
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{window.end:%Y-%m}"))
    view = await service.load_view(session, shop_id, ctx, window, funnel=True)
    rows = view.data.funnel
    if rows is None:
        rows = await funnel.load_rows(session, shop_id, window)
    return view, rows


def _line_offer(pair: tuple[Any, Any]) -> float:
    """Ưu đãi of one line (``ProfitBreakdown.offer_cost``, the seller-borne basis): as Tổng quan
    (``channel_split._offers_cost``): khuyến mãi + voucher + combo, so the days add up to it."""
    _ln, bd = pair
    return float(bd.offer_cost)


def _offer_cost(view: PeriodView, product: str | None = None, day: date | None = None) -> float:
    """Chi phí ưu đãi = Chương Trình Của Shop + voucher + combo discount of the lines."""
    total = 0.0
    for pair in view.pairs:
        ln = pair[0]
        if (product is None or ln.product_id == product) and (day is None or ln.order_date == day):
            total += _line_offer(pair)
    return total


def _aff_cost_day(view: PeriodView, day: date, product: str | None = None) -> float | None:
    """One day's affiliate cost: the one definition, ``channel_split.affiliate_cost``."""
    cost = channel_split.affiliate_cost(
        [
            (ln, pb)
            for ln, pb in view.pairs
            if ln.order_date == day and (product is None or ln.product_id == product)
        ],
        basis=view.pairs,
    )
    return None if cost is None else float(cost)


def _figures(split: dict[str, Any]) -> tq.Figures:
    """One scope's Figures from a ``channel_split`` answer."""
    by = {r["key"]: r for r in split["rows"]}
    k = split["kpis"]
    ps = split.get("profit_split")  # P7: the channel profit split (None off Shopee)
    channels: dict[str, tq.Channel] = {}
    for key in tq.CHANNELS:
        r = by.get(key) or {}
        cost = {"ads": _f(k["cost_ads"]), "affiliate": _f(k["cost_affiliate"])}.get(key)
        profit = None
        if ps is not None:
            pr = ps["rows"][key]
            # one combined Chi phí marketing per channel: its QC / AFF + its Ưu đãi
            cost = float(pr["cost_ads"] + pr["cost_affiliate"] + pr["cost_offers"])
            profit = _f(pr["profit"])
        channels[key] = tq.Channel(
            _f(r.get("views")), _f(r.get("clicks")), _f(r.get("orders")), _f(r.get("gmv")),
            cost, profit,
        )  # fmt: skip
    rest = None if ps is None else ps.get("unattributed")
    rest_cost = None if rest is None else float(rest["cost_ads"] + rest.get("other_marketing", 0))
    return tq.Figures(
        channels=channels, gmv=_f(k["gmv"]), orders=_f(k["orders"]), profit=_f(k["profit"]),
        ads_cost=_f(k["cost_ads"]), aff_cost=_f(k["cost_affiliate"]),
        offer_cost=_f(k["cost_offers"]), cost_total=_f(k.get("cost_total")),
        rest_cost=rest_cost, rest_profit=None if rest is None else _f(rest["profit"]),
        gross_profit=_f(k.get("gross_profit")), contribution=_f(k.get("contribution")),
    )  # fmt: skip


def _residual(shop: tq.Figures, parts: list[tq.Figures]) -> tq.Figures:
    """Shop minus the products, field by field (``None`` where the shop has none)."""

    def sub(a: float | None, vals: list[float | None]) -> float | None:
        return None if a is None else a - sum(v for v in vals if v is not None)

    def sub_channel(a: float | None, vals: list[float | None]) -> float | None:
        # a channel's products can add up past the shop (the product rows and the shop row come
        # from different reports): the "Cả shop" cell is then unknown, never a negative figure
        got = sub(a, vals)
        return None if got is not None and got < 0 else got

    channels = {}
    for key in tq.CHANNELS:
        s = shop.channel(key)
        ps = [p.channel(key) for p in parts]
        channels[key] = tq.Channel(
            *(sub_channel(getattr(s, n), [getattr(p, n) for p in ps]) for n in _CHANNEL_FIELDS)
        )  # fmt: skip
    return tq.Figures(
        channels=channels,
        gmv=sub(shop.gmv, [p.gmv for p in parts]),
        orders=sub(shop.orders, [p.orders for p in parts]),
        profit=sub(shop.profit, [p.profit for p in parts]),
        ads_cost=sub(shop.ads_cost, [p.ads_cost for p in parts]),
        aff_cost=sub(shop.aff_cost, [p.aff_cost for p in parts]),
        offer_cost=sub(shop.offer_cost, [p.offer_cost for p in parts]),
        net_revenue_known=sub(shop.net_revenue_known, [p.net_revenue_known for p in parts]),
        cost_total=sub(shop.cost_total, [p.cost_total for p in parts]),
        gross_profit=sub(shop.gross_profit, [p.gross_profit for p in parts]),
        contribution=sub(shop.contribution, [p.contribution for p in parts]),
    )  # fmt: skip


def _net_revenue_known(view: PeriodView, product_id: str | None) -> float | None:
    """The margin base (registry ``net_revenue_known``) of the shop or of one product: the buyer
    paid of the orders whose costs are known, the base of the screen's margin."""
    if product_id is None:
        return _f(shop_profit_of(view).buyer_paid)
    unknown = unknown_orders(view.pairs)  # whole known orders, the rule of the shop figure
    lines = [
        pb for ln, pb in view.pairs
        if ln.product_id == product_id and pb.excluded_reason is None
        and pb.contribution is not None and ln.order_id not in unknown
    ]  # fmt: skip
    return (
        None
        if product_id not in view.profit.products
        else _f(sum((pb.revenue for pb in lines), Decimal(0)))
    )


def _gmv_of(listing: dict[str, Any], product_id: str) -> float:
    for p in listing["products"]:
        if p["product_id"] == product_id:
            return float(p.get("gmv") or 0)
    return 0.0


async def _plan(
    session: AsyncSession, shop_id: uuid.UUID, window: Window, view: PeriodView, now: datetime,
    daily: bool = False,
) -> dict[str, Any]:  # fmt: skip
    """The running-plan figures of the period (the Kế hoạch export's Mục tiêu): exactly the
    Kế hoạch card's."""
    return await month_plan.range_plan(
        session, shop_id, window.start, window.end, scope=month_plan.SCOPE_RUNNING, now=now,
        view=view, daily=daily,
    )  # fmt: skip


def _day_scope(rows: funnel.FunnelRows, day: date, product: str | None) -> funnel.FunnelRows:
    return replace(
        rows, window=Window(day, day),
        sources=tuple(s for s in rows.sources if s.day == day),
        shop_days=tuple(s for s in rows.shop_days if s.day == day),
        product_days=tuple(s for s in rows.product_days if s.day == day),
    )  # fmt: skip


def _ads_basis(rows: funnel.FunnelRows, shop_id: uuid.UUID, pid: str | None) -> str | None:
    """Where a scope's Quảng cáo GMV comes from: Seller Centre's ads overlay on Thẻ sản phẩm
    ("overlay") or the ads report ("report")."""
    base = funnel.base_from_rows(rows, str(shop_id), item_ids=(pid,) if pid else ())
    card = next((s for s in base.sources if s.source == channel_split.CARD), None)
    return "overlay" if card is not None and card.ads is not None else "report"


def partition(fig: tq.Figures) -> tq.Figures:
    """``fig`` with its channels' GMV made to add up to its GMV (``report_calc.partition_channels``:
    Organic = GMV - Quảng cáo - Tiếp thị liên kết)."""
    got = calc.partition_channels(
        fig.gmv, fig.channel("ads").gmv, fig.channel("affiliate").gmv, fig.channel("organic").gmv
    )
    channels = {
        key: replace(fig.channel(key), gmv=g) for key, g in zip(tq.CHANNELS, got, strict=True)
    }
    return replace(fig, channels=channels)


async def _month_rows(
    session: AsyncSession, shop_id: uuid.UUID, cur: Window, cur_view: PeriodView,
    others: dict[tuple[date, date], PeriodView],
) -> list[rs.MonthRow]:  # fmt: skip
    """ "Theo tháng": the calendar month before the period, then each month of it (clipped to the
    period). A month that the stored days do not cover is a row of "—"."""
    out: list[rs.MonthRow] = []
    for first, last in calc.months_of(cur.start, cur.end):
        label = f"{first:%m/%Y}" if (first.day, last) == (1, calc.month_end(first)) else (
            f"{first:%d/%m}–{last:%d/%m/%Y}"
        )  # fmt: skip
        win = Window(first, last)
        try:
            if (first, last) == (cur.start, cur.end):
                view = cur_view
            elif (first, last) in others:
                view = others[(first, last)]
            else:
                view = (await _view(session, shop_id, win))[0]
            fig = _figures(await channel_split.split_figures(session, shop_id, view, win, None))
        except RowsNotMaterialized:
            out.append(rs.MonthRow(label))
            continue
        out.append(rs.MonthRow(label, fig.gmv, fig.orders, fig.profit, tq.cost_of(fig)))
    return out


async def _goal(
    session: AsyncSession, shop_id: uuid.UUID, window: Window, view: PeriodView, now: datetime,
    product_id: str | None,
) -> tuple[float | None, float | None]:  # fmt: skip
    """Mục tiêu = the Kế hoạch's expected GMV / lợi nhuận of the period (the running plan's goal,
    ``month_plan.range_plan``); ``None`` when the period has no plan."""
    try:
        plan = await month_plan.range_plan(
            session, shop_id, window.start, window.end, scope=month_plan.SCOPE_RUNNING, now=now,
            actual_to=window.end, view=view, product_id=product_id,
        )  # fmt: skip
    except RowsNotMaterialized:
        return None, None
    return _f(plan.get("goal_gmv")), _f(plan.get("goal_profit"))


async def collect_tong_quan(
    session: AsyncSession, shop_id: uuid.UUID, *, shop_name: str, now: datetime,
    period: str = "30d", month: str | None = None, start: date | None = None,
    end: date | None = None, as_of: date | None = None, product_id: str | None = None,
    platform: str = "Shopee",
) -> tq.TongQuanData:  # fmt: skip
    """The Tổng quan numbers of the period (the screen's period parameters) and level (the shop,
    or ``product_id``). Every figure is the screen's: ``channel_split`` for the channels and KPIs,
    ``month_plan.range_plan`` for the baseline / goal of the shop, of each product and of each
    day."""
    window = await service.resolve(
        session, shop_id, period=period, month=month, start=start, end=end, as_of=as_of
    )
    if window is None:
        raise ValueError("no data")
    cur = window
    ps, pe, prev_kind = calc.previous_period(cur.start, cur.end)
    prv = Window(ps, pe)
    kw: dict[str, Any] = {"period": "custom", "start": cur.start, "end": cur.end}
    kw_prev: dict[str, Any] = {"period": "custom", "start": prv.start, "end": prv.end}
    view, frows = await _view(session, shop_id, cur)
    prev_rows: funnel.FunnelRows | None = None
    try:
        pview: PeriodView | None
        pview, prev_rows = await _view(session, shop_id, prv)
    except RowsNotMaterialized:  # no stored days before the period: nothing to compare with
        pview = None

    listing = await channel_split.channel_split_products(session, shop_id, **kw)
    names = {p["product_id"]: p["name"] for p in listing["products"]}
    if pview is not None:
        prev_listing = await channel_split.channel_split_products(session, shop_id, **kw_prev)
        names.update({p["product_id"]: p["name"] for p in prev_listing["products"]})
    # every active listing (the Sản phẩm list), not only those with channel data: a product
    # without orders in the period is a 0 row, not a missing one
    for i, name in getattr(view, "active_items", {}).items():
        names.setdefault(i, name)
    for i in names:
        if i.startswith(UNMATCHED_PREFIX):
            names[i] = UNMATCHED_LABEL

    async def figures(
        v: PeriodView | None, w: Window, pid: str | None, rows_: funnel.FunnelRows | None
    ) -> tq.Figures:
        if v is None or rows_ is None:
            return tq.Figures()
        fig = _figures(await channel_split.split_figures(session, shop_id, v, w, pid))
        base = _net_revenue_known(v, pid)
        return partition(
            replace(fig, ads_basis=_ads_basis(rows_, shop_id, pid), net_revenue_known=base)
        )

    shop_now = await figures(view, cur, None, frows)
    shop_prev = await figures(pview, prv, None, prev_rows)

    # One critical read feeds both the product cause/fix columns and Phân tích & đề xuất.
    critical_items = await _critical_items(session, shop_id, cur, product_id)
    product_notes = rs.product_issue_texts(critical_items)
    rows: list[tq.ProductRow] = []
    ids = [product_id] if product_id else sorted(names, key=lambda i: -_gmv_of(listing, i))
    for i in ids:
        now_fig = await figures(view, cur, i, frows)
        cause, fix = product_notes.get(i, (calc.DASH, calc.DASH))
        rows.append(
            tq.ProductRow(
                i,
                names.get(i, i),
                now_fig,
                await figures(pview, prv, i, prev_rows),
                cause=cause,
                fix=fix,
            )  # fmt: skip
        )
    if product_id:  # the Sản phẩm level: the file's period figures are the product's
        shop_now, shop_prev = rows[0].now, rows[0].prev
    else:
        rest = tq.ProductRow(
            tq.SHOP_ROW_LABEL, tq.SHOP_ROW_NAME, _residual(shop_now, [r.now for r in rows]),
            _residual(shop_prev, [r.prev for r in rows]),
        )  # fmt: skip
        rows.append(rest)

    shop_days = {d.day: d for d in frows.shop_days}
    prod_days = {d.day: d for d in frows.product_days if d.item_id == product_id}
    spend = view.data.ads_daily.spend_by_day
    days: list[tq.DayRow] = []
    for k in range(cur.days):
        d = cur.start + timedelta(days=k)
        one = _day_scope(frows, d, product_id)
        ids_ = (product_id,) if product_id else ()
        by = {
            r["key"]: r
            for r in channel_split.split_rows(
                funnel.base_from_rows(one, str(shop_id), item_ids=ids_)
            )
        }
        sd = prod_days.get(d) if product_id else shop_days.get(d)
        # no traffic-source rows that day: the channel split is unknown (not "all affiliate")
        traffic = any(by.get(key, {}).get("gmv") is not None for key in tq.CHANNELS)
        gmv_by = {key: _f(by[key]["gmv"]) if traffic else None for key in tq.CHANNELS}
        orders_by = {key: _f(by[key]["orders"]) if traffic else None for key in tq.CHANNELS}
        days.append(
            tq.DayRow(
                d,
                gmv_by,
                orders_by,
                _f(sd.ads_spend) if product_id and sd else None if product_id else _f(spend.get(d)),
                _aff_cost_day(view, d, product_id),
                _offer_cost(view, product_id, d),
                None if sd is None else _f(sd.profit),
                total_gmv=None if sd is None else _f(sd.gmv),
                total_orders=None if sd is None else _f(sd.orders),
            )  # fmt: skip
        )
    skus = await _sku_rows(session, shop_id, view, cur, list(ids), names, now)
    goal_gmv, goal_profit = await _goal(session, shop_id, cur, view, now, product_id)
    months = await _month_rows(
        session, shop_id, cur, view, {(prv.start, prv.end): pview} if pview else {}
    )
    koc, share = await _koc(session, shop_id, cur, product_id, shop_now, shop_prev)
    analysis = await _analysis(session, shop_id, critical_items, names, now, shop_name, platform)
    return tq.TongQuanData(
        shop_name, cur.start, cur.end, prv.start, prv.end, shop_now, shop_prev, days, rows,
        platform, product_name=names.get(product_id, product_id) if product_id else None,
        product_id=product_id, skus=skus, prev_kind=prev_kind, goal_gmv=goal_gmv,
        goal_profit=goal_profit, months=months, koc=koc, affiliate_share=share,
        analysis=analysis, bridge=None if product_id else profit_bridge(view),
    )  # fmt: skip


async def _stock_facts(
    session: AsyncSession, shop_id: uuid.UUID, now: datetime
) -> tuple[dict[tuple[str, str], stock_data.SkuState], date]:
    """The stock alert's own facts of every variation (``stock_alert.data.load_states``: Kho hàng
    first, then sellable; its sell rate and its days-left walk), keyed (item id, model id)."""
    moment = now.astimezone(UTC).replace(tzinfo=None) if now.tzinfo else now
    today = stock_basis.local_day(moment)
    states, _catalog = await stock_data.load_states(session, shop_id, today, moment)
    return {(st.facts.item_id, st.facts.model_id): st for st in states}, today


def _stock_of(
    states: Mapping[tuple[str, str], stock_data.SkuState], today: date, product_id: str,
    variation_id: str, only_sku: bool,
) -> tuple[float | None, float | None, float | None]:  # fmt: skip
    """(tồn kho, bán / ngày, còn ~ ngày) of one SKU as the stock alert has them; ``None`` = the
    alert has no usable read / no forecast for it."""
    st = states.get((product_id, variation_id)) or (
        states.get((product_id, "")) if only_sku else None
    )
    if st is None:
        return None, None, None
    rate = st.facts.base
    if st.stock is None:
        return None, rate, None
    left = stock_forecast.days_left(st.stock.stock, rate, today, st.facts.effects).days_left
    return float(st.stock.stock), rate, None if left is None else float(left)


async def _sku_rows(
    session: AsyncSession, shop_id: uuid.UUID, view: PeriodView, window: Window,
    product_ids: list[str], names: dict[str, str], now: datetime,
) -> list[tq.SkuRow]:  # fmt: skip
    """The "Theo SKU" rows (``exports/sku``): actuals of the period; tồn kho, bán / ngày and còn
    ~ ngày as the stock alert has them."""
    now_figs = await skumod.sku_figures(session, shop_id, view, window)
    ctx = await loaders.load_context(session, shop_id)
    catalog_variations = {
        pid: [(v.variation_id, v.name, v.seller_sku) for v in info.variations]
        for pid in product_ids
        if (info := ctx.catalog.items.get(pid)) is not None
    }
    rows = skumod.build_rows(
        product_ids=product_ids, names=names, now=now_figs, base={}, plans={},
        stock=skumod.Stock(), catalog_variations=catalog_variations, finished=True,
    )  # fmt: skip
    states, today = await _stock_facts(session, shop_id, now)
    per_product: dict[str, int] = {}
    for r in rows:
        per_product[r.key[0]] = per_product.get(r.key[0], 0) + 1
    out = []
    for r in rows:
        code, combo = split_sku(r.sku)
        stock, rate, left = _stock_of(states, today, r.key[0], r.key[2], per_product[r.key[0]] == 1)
        out.append(
            tq.SkuRow(
                code,
                r.variation,
                r.product_name,
                r.units,
                r.revenue,
                r.profit,
                stock,
                rate,
                left,
                combo,
            )  # fmt: skip
        )
    return out


async def _koc(
    session: AsyncSession, shop_id: uuid.UUID, window: Window, product_id: str | None,
    shop_now: tq.Figures, shop_prev: tq.Figures,
) -> tuple[list[rs.KocRow], rs.AffiliateShare]:  # fmt: skip
    """ "KOC": the Phân tích › KOL section's rows of the period summed per KOC (its own previous
    period: the same number of days before), and Tiếp thị liên kết's share of the shop's GMV."""
    share = rs.AffiliateShare(
        shop_now.channel("affiliate").gmv, shop_now.gmv, shop_prev.channel("affiliate").gmv,
        shop_prev.gmv,
    )  # fmt: skip
    try:
        section = await metric_view.kol_section(
            session, shop_id, audience="seller", period="custom", start=window.start,
            end=window.end,
        )  # fmt: skip
    except RowsNotMaterialized:
        return [], share
    if product_id is not None:
        section = {**section, "rows": [r for r in section["rows"] if r["item_id"] == product_id]}
    return rs.koc_rows(section), share


async def _critical_items(
    session: AsyncSession,
    shop_id: uuid.UUID,
    window: Window,
    product_id: str | None,
) -> list[Mapping[str, Any]]:
    """Phân tích's critical metrics for this window, once. Product cause/fix and the analysis
    sheet both read this list."""
    try:
        crit = await queries.critical(
            session, shop_id, period="custom", start=window.start, end=window.end
        )
    except (RowsNotMaterialized, NoShopeeData):
        return []
    return [it for it in crit["items"] if product_id is None or it.get("product_id") == product_id]


def _goal_rows_for_products(items: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, str]]:
    """Test seam: ``product_issue_texts`` on critical items (product id -> cause, fix)."""
    return rs.product_issue_texts(items)


async def _analysis(
    session: AsyncSession,
    shop_id: uuid.UUID,
    items: Sequence[Mapping[str, Any]],
    names: dict[str, str],
    now: datetime,
    shop_name: str,
    platform: str,
) -> list[rs.AnalysisRow]:
    """ "Phân tích & đề xuất": the critical metrics already loaded, with the cards Juli created
    for them (the Kế hoạch's cards, ``_cards_of``)."""
    if not items:
        return []
    cards = await _cards_of(
        session, shop_id, shop=shop_name, platform=platform, now=now, names=names
    )
    return rs.analysis_rows(items, cards)


def split_sku(label: str) -> tuple[str, float | None]:
    """A combo cost key "G500001×10" -> ("G500001", 10.0): Seller Centre's SKU and the units per
    variation; any other label as it is."""
    code, sep, mult = label.partition("×")
    if not sep:
        return label, None
    try:
        return code, float(mult)
    except ValueError:
        return label, None


# ----------------------------------------------------------------------------- Kế hoạch


def _card_row(
    card: Mapping[str, Any], plan_code: str | None, status: str, ev: Mapping[str, Any] | None,
    names: dict[str, str], *, shop: str, platform: str, proposed: date | None,
) -> kh.CardRow:  # fmt: skip
    kind = card.get("change_kind") or ""
    spec = kinds.KINDS.get(kind)
    own = ((ev or {}).get("result") or {}).get("own") or {}
    dates = own.get("dates") or {}
    delta = own.get("delta") or {}

    def q(p: str, m: str) -> float | None:
        return _f((delta.get(p) or {}).get(m))

    version = next(
        (
            v.get("label")
            for v in card.get("versions", [])
            if v.get("version") == card.get("chosen_version")
        ),
        None,
    )  # fmt: skip
    row = kh.CardRow(
        code=card["code"], plan_code=plan_code, status=status,
        group=GROUP_OF_FAMILY.get(card.get("family") or "", ""),
        kind=spec.label if spec else kind, version=version,
        product_id=card.get("product_id"), product_name=names.get(card.get("product_id") or ""),
        metrics=METRIC_LABELS.get(spec.target_metric) if spec else None,
        start=date.fromisoformat(dates["from"]) if dates.get("from") else None,
        end=date.fromisoformat(dates["to"]) if dates.get("to") else None,
        kind_key=kind, family=card.get("family") or "", shop=shop, platform=platform,
        proposed=proposed,
        cost=_f(own.get("cost_total")),
        gmv_mid=q("p50", "dgmv"), profit_mid=q("p50", "dprofit"), orders_mid=q("p50", "dorders"),
        source=kh.source_label(card.get("origin")),
        external_ref=card.get("external_ref"),
    )  # fmt: skip
    block = forecast_block(card, ev)
    row.figures = figures_of(block, None)
    row.prediction_type = kh.prediction_label(block.get("prediction_type"))
    row.tailored = ads_tailored(card, own)
    return row


def forecast_block(card: Mapping[str, Any], ev: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """The card's stored F7 forecast (``forecast.forecast_of``): on the card, else on its stored
    result. Empty when the card has none."""
    result = (ev or {}).get("result") or {}
    for found in (
        card.get("forecast"), (ev or {}).get("forecast"), result.get("forecast"),
        (card.get("evaluation") or {}).get("forecast"),
    ):  # fmt: skip
        if isinstance(found, Mapping):
            return found
    return {}


ADDITIVE = ("profit", "gmv", "orders")


def figures_of(
    forecast: Mapping[str, Any], actual: Mapping[str, Any] | None
) -> dict[str, tuple[float | None, float | None, float | None]]:
    """(Hiện tại, Dự kiến, Thực tế) per metric over the card's measured days. Hiện tại and Dự kiến
    are the stored forecast's (over the card's ``days``); when only ``k`` of ``N`` days are
    measured the additive ones (Lợi nhuận, GMV, Đơn) are prorated to ``k/N`` so the three amounts
    cover the same days. Thực tế is the running measurement's, ``None`` when not measured."""
    fm = forecast.get("metrics") or {}
    am = (actual or {}).get("metrics") or {}
    k, n = (actual or {}).get("days_measured"), (actual or {}).get("days")
    share = k / n if isinstance(k, int) and isinstance(n, int) and 0 < k < n else 1.0
    out: dict[str, tuple[float | None, float | None, float | None]] = {}
    for key in ("profit", "gmv", "orders", "aov"):
        f = fm.get(key) or {}
        mult = share if key in ADDITIVE else 1.0
        now, exp = _f(f.get("hien_tai")), _f(f.get("du_kien"))
        got = _f((am.get(key) or {}).get("thuc_te"))
        out[key] = (
            None if now is None else now * mult, None if exp is None else exp * mult, got,
        )  # fmt: skip
    return out


def _ratio(v: Any) -> float | None:
    x = _f(v)
    return None if x is None or x <= 0 else x


def ads_tailored(
    card: Mapping[str, Any], own: Mapping[str, Any]
) -> dict[str, tuple[float | None, float | None]]:
    """The Quảng cáo sheet's CPA / ROAS / hoà vốn: (Dự kiến, Thực tế) from the card's stored ads
    lines and its read-back. A reading the card does not have stays ``None`` ("—"), never 0."""
    ads = (card.get("evaluation") or {}).get("option", {}).get("ads") or {}
    ads = (own.get("option") or {}).get("ads") or ads
    if not ads and not card.get("ads_readback"):
        return {}
    read = (card.get("ads_readback") or {}).get("actual") or {}
    spend, orders = _f(read.get("spend")), _f(read.get("orders"))
    cpa = _f(read.get("cpa"))
    if cpa is None and spend is not None and orders:
        cpa = spend / orders
    be_roas = (own.get("certain") or {}).get("break_even_roas", ads.get("break_even_roas"))
    return {
        "CPA": (_f((ads.get("cpa") or {}).get("after")), cpa),
        "ROAS": (_f((ads.get("roas_shopee") or {}).get("after")), _f(read.get("roas"))),
        "CPA hoà vốn": (_f(ads.get("break_even_cpa")), None),
        "ROAS hoà vốn": (_f(be_roas), None),
    }


VERDICT_TEXT = {
    execution_state.VERDICT_RUNNING: "Đang đo",
    execution_state.VERDICT_INSIDE: "Trong khoảng",
    execution_state.VERDICT_BELOW: "Dưới khoảng",
    execution_state.VERDICT_ABOVE: "Vượt khoảng",
}


def _conclusion(row: Mapping[str, Any]) -> str | None:
    """Kết luận of one Đo lường row: ``execution_state``'s own verdict, in words."""
    verdict_key = row.get("verdict")
    return VERDICT_TEXT.get(verdict_key) if isinstance(verdict_key, str) else None


def _apply_measure(
    row: kh.CardRow, m: Mapping[str, Any] | None, ref_of: Mapping[str, str | None]
) -> None:
    """Layer one Đo lường row on a card row: Thực tế per metric, Đã đo, Đo chung với (the other
    cards' mã gốc when they have one, else their code) and Kết luận."""
    if m is None:
        return
    actual = m.get("actual") if isinstance(m.get("actual"), Mapping) else None
    if actual is not None:
        # the card's own forecast (kept unscaled on the row) re-laid over the measured days
        forecast = {
            "metrics": {k: {"hien_tai": v[0], "du_kien": v[1]} for k, v in row.figures.items()}
        }
        row.figures = figures_of(forecast, actual)
        row.days_measured, row.days_total = actual.get("days_measured"), actual.get("days")
        profit = (actual.get("metrics") or {}).get("profit") or {}
        row.actual_profit = _f(profit.get("delta"))
    row.measured_with = [ref_of.get(code) or code for code in m.get("measured_with") or []]
    row.conclusion = _conclusion(m)


def _day(v: Any) -> date | None:
    if v is None:
        return None
    return v.date() if isinstance(v, datetime) else date.fromisoformat(str(v)[:10])


async def _cards_of(
    session: AsyncSession, shop_id: uuid.UUID, *, shop: str, platform: str, now: datetime,
    names: dict[str, str],
) -> list[kh.CardRow]:  # fmt: skip
    """Every card of the shop with a plan (executed or draft) or a measurement, whatever its dates;
    the caller keeps the ones active in its range (``kh.active_in``)."""
    today = now.date()
    sets_by_card: dict[str, Any] = {}
    for cs in await change_sets.sets_for(session, shop_id):
        for cid in cs.card_ids or []:
            sets_by_card[str(cid)] = cs

    def measure_end(card_id: str) -> date | None:
        s = sets_by_card.get(card_id)
        if s is None:
            return None
        closed = s.status in (change_sets.SET_DONE, change_sets.SET_CUT)
        return (
            s.started_at.date() + timedelta(days=s.window_days)
            if closed
            else max(today, s.started_at.date() + timedelta(days=s.window_days))
        )  # an open measurement is still active today

    out: list[kh.CardRow] = []
    seen: set[str] = set()
    for pj in await plans.list_plans(session, shop_id):
        if pj["status"] not in (PLAN_EXECUTED, PLAN_DRAFT):
            continue
        payload = await plans.get_plan(
            session, shop_id, None if pj["status"] == PLAN_DRAFT else uuid.UUID(pj["id"]),
            now=now, audience="seller",
        )  # fmt: skip
        evs = {
            plan_groups.split_entry_id(c["card_id"])[0]: c for c in month_plan.plan_cards(payload)
        }
        sets = {str(cid): s for s in payload.get("change_sets", []) for cid in s["card_ids"]}
        for c in payload["cards"]:
            ev = evs.get(c["card_id"])
            if pj["status"] == PLAN_DRAFT:
                status = kh.DRAFT
            else:
                s = sets.get(c["card_id"])
                own = ((ev or {}).get("result") or {}).get("own", {}) or {}
                ended = bool(own.get("dates")) and date.fromisoformat(own["dates"]["to"]) < today
                status = (
                    kh.MEASURED if s and s["status"] in (change_sets.SET_DONE, change_sets.SET_CUT)
                    else kh.MEASURING if s and ended else kh.RUNNING
                )  # fmt: skip
            row = _card_row(c, payload["plan"]["code"], status, ev, names, shop=shop,
                            platform=platform, proposed=_day(c.get("added_at")))  # fmt: skip
            row.measure_end = measure_end(c["card_id"])
            out.append(row)
            seen.add(c["card_id"])
    # measuring / measured cards that no plan holds
    listed = (
        await reco_service.list_cards(session, shop_id, audience="seller", queue="all", now=now)
    )["cards"]
    for c in listed:
        s = sets_by_card.get(c["id"])
        if c["id"] in seen or c.get("plan_id") or s is None:
            continue
        closed = s.status in (change_sets.SET_DONE, change_sets.SET_CUT)
        pm = c["predicted_summary"]
        row = _card_row(
            c, None, kh.MEASURED if closed else kh.MEASURING, None, names, shop=shop,
            platform=platform, proposed=_day(c.get("created_at")),
        )  # fmt: skip
        row.start = s.executed_on
        row.end = s.started_at.date() + timedelta(days=s.window_days)
        row.measure_end = measure_end(c["id"])
        # one card, one number: the card's stored result (its own days), as the card shows it
        row.gmv_mid, row.profit_mid = _f(pm["dgmv"]["p50"]), _f(pm["dprofit"]["p50"])
        row.orders_mid = _f(pm["dorders"]["p50"])
        row.cost = _f(c.get("cost"))
        out.append(row)
    measured = {
        c["code"]: c
        for c in (await execution_state.measurement_states(session, shop_id, now=now))["cards"]
    }
    ref_of = {r.code: r.external_ref for r in out}
    for row in out:
        _apply_measure(row, measured.get(row.code), ref_of)
    return out


async def _kols_of(
    session: AsyncSession, shop_id: uuid.UUID, window: Window, *, shop: str, platform: str
) -> list[kh.KolRow]:  # fmt: skip
    """One row per KOL: the Phân tích KOL section's rows of the range, summed over product and
    channel."""
    try:
        section = await metric_view.kol_section(
            session, shop_id, audience="seller", period="custom", start=window.start,
            end=window.end,
        )  # fmt: skip
    except RowsNotMaterialized:
        return []
    by: dict[str, kh.KolRow] = {}
    for r in section["rows"]:
        k = by.setdefault(r["kol_key"], kh.KolRow(shop, platform, r["handle"] or r["kol_key"]))
        for attr, key in (("clicks", "clicks"), ("orders", "orders"), ("gmv", "gmv"),
                          ("commission", "commission"), ("profit", "profit"),
                          ("sample_cost", "sample_cost")):  # fmt: skip
            v = _f(r.get(key))
            if v is not None:
                setattr(k, attr, (getattr(k, attr) or 0.0) + v)
        k.cards += int(r.get("cards") or 0)
    return list(by.values())


async def collect_ke_hoach_shop(
    session: AsyncSession, shop_id: uuid.UUID, *, shop_name: str, now: datetime, start: date,
    end: date, platform: str = "Shopee",
) -> tuple[list[kh.CardRow], kh.GoalRow, list[kh.GoalDay], list[kh.KolRow]]:  # fmt: skip
    """One Shopee shop's Kế hoạch figures of ``start..end``: the cards active in the range (G22),
    the shop's goal row and its daily rows, its KOL rows."""
    if end < start:
        raise ValueError("end before start")
    window = await service.resolve(session, shop_id, period="custom", start=start, end=end)
    if window is None:
        raise ValueError("no data")
    view, rows = await _view(session, shop_id, window)
    names = {
        p["product_id"]: p["name"]
        for p in (
            await channel_split.channel_split_products(
                session, shop_id, period="custom", start=window.start, end=window.end
            )
        )["products"]
    }
    cards = [
        c
        for c in await _cards_of(
            session, shop_id, shop=shop_name, platform=platform, now=now, names=names
        )
        if kh.active_in(c, start, end)
    ]
    plan = await _plan(session, shop_id, window, view, now, daily=True)
    actual_gmv = {d.day: float(d.gmv) for d in rows.shop_days}
    actual_profit = {d.day: float(d.profit) for d in rows.shop_days if d.profit is not None}
    goal = kh.GoalRow(
        shop_name, platform, _f(plan.get("baseline_gmv")), _f(plan.get("goal_gmv")),
        sum(actual_gmv.values()) if actual_gmv else None,
        _f(plan.get("baseline_profit")), _f(plan.get("goal_profit")),
        # P9 (audit P4): the period's actual on the screen's basis (the Kế hoạch card's known-cost
        # profit, ``month_plan``), the same basis as its baseline and goal -- not a sum of days
        _f(plan.get("actual_profit")) if "actual_profit" in plan
        else (sum(actual_profit.values()) if actual_profit else None),
    )  # fmt: skip
    days = [
        kh.GoalDay(
            shop_name,
            d,
            _f(t.get("baseline_gmv")),
            _f(t.get("goal_gmv")),
            actual_gmv.get(d),
            _f(t.get("baseline_profit")),
            _f(t.get("goal_profit")),
            actual_profit.get(d),
        )  # fmt: skip
        for t in plan["daily"]
        for d in [date.fromisoformat(t["day"])]
    ]
    kols = await _kols_of(session, shop_id, window, shop=shop_name, platform=platform)
    return cards, goal, days, kols


async def collect_ke_hoach(
    session: AsyncSession, shop_id: uuid.UUID, *, shop_name: str, now: datetime,
    start: date | None = None, end: date | None = None, platform: str = "Shopee",
) -> kh.KeHoachData:  # fmt: skip
    """The Kế hoạch workbook's numbers of ``start..end`` (default: the newest data month to date).
    Days are Asia/Ho_Chi_Minh calendar days (the stored daily rows' own days)."""
    if start is None or end is None:
        window = await service.resolve(session, shop_id)
        if window is None:
            raise ValueError("no data")
        end = end or window.end
        start = start or end.replace(day=1)
    cards, goal, days, kols = await collect_ke_hoach_shop(
        session, shop_id, shop_name=shop_name, now=now, start=start, end=end, platform=platform
    )
    return kh.KeHoachData(start, end, [shop_name], cards, [goal], days, kols)


# ----------------------------------------------------------------------------- Tất cả shop (G23)


@dataclass(frozen=True)
class ShopRef:
    """One shop of the "Tất cả shop" gate: the shops the user can access (their own, and those of
    the businesses they are an active member of: migration 130, the membership-aware ``shops``
    policy that ``ShopsRepo.list_for_authorization`` reads)."""

    id: uuid.UUID
    name: str
    platform: str  # "shopee" | "tiktok"


def _platform_label(platform: str) -> str:
    return {"shopee": "Shopee", "tiktok": "TikTok"}.get(platform, platform)


async def collect_tong_quan_shops(
    session: AsyncSession, shops: Sequence[ShopRef], *, user_id: uuid.UUID, now: datetime,
    **window: Any,
) -> list[tq.TongQuanData]:  # fmt: skip
    """One Tổng quan data per shop, over one date range (``window``: the screen's period args).

    TODO(TikTok session): a TikTok shop has no collector here yet; it is a column of "—" until its
    Tổng quan figures are wired in (a shop with no figures also means no Tổng for the metric it
    lacks only because SUM skips empty cells: the Tổng column is the Shopee shops' sum then)."""
    out: list[tq.TongQuanData] = []
    for shop in shops:
        if shop.platform != "shopee":
            continue
        async with with_tenant_scope(session, shop.id, user_id):
            out.append(
                await collect_tong_quan(
                    session, shop.id, shop_name=shop.name, now=now, platform="Shopee", **window
                )
            )
    if not out:
        raise ValueError("no data")
    first = out[0]
    merged: list[tq.TongQuanData] = []
    done = {d.shop_name: d for d in out}
    for shop in shops:
        d = done.get(shop.name) if shop.platform == "shopee" else None
        merged.append(
            d
            or tq.TongQuanData(
                shop.name, first.start, first.end, first.prev_start, first.prev_end,
                tq.Figures(), tq.Figures(), platform=_platform_label(shop.platform),
            )
        )  # fmt: skip
    return merged


async def collect_ke_hoach_shops(
    session: AsyncSession, shops: Sequence[ShopRef], *, user_id: uuid.UUID, now: datetime,
    start: date, end: date,
) -> kh.KeHoachData:  # fmt: skip
    """The Kế hoạch workbook over every shop: one date range, a Shop and Platform on every card
    row, a goal row per shop (a shop without a plan collector has an empty goal, so the business
    total is empty: ``kh.business_total``)."""
    data = kh.KeHoachData(start, end, [s.name for s in shops], all_shops=True)
    for shop in shops:
        if shop.platform != "shopee":  # TODO(TikTok session): its card / goal collector
            data.goals.append(kh.GoalRow(shop.name, _platform_label(shop.platform)))
            continue
        async with with_tenant_scope(session, shop.id, user_id):
            cards, goal, days, kols = await collect_ke_hoach_shop(
                session, shop.id, shop_name=shop.name, now=now, start=start, end=end
            )
        data.cards += cards
        data.goals.append(goal)
        data.days += days
        data.kols += kols
    return data


__all__ = [
    "ShopRef",
    "collect_ke_hoach",
    "collect_ke_hoach_shops",
    "collect_tong_quan",
    "collect_tong_quan_shops",
]
