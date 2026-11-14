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

import calendar
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_plans import PLAN_DRAFT, PLAN_EXECUTED
from juli_backend.services.exports import ke_hoach_xlsx as kh
from juli_backend.services.exports import sku as skumod
from juli_backend.services.exports import tong_quan_xlsx as tq
from juli_backend.services.shopee_analytics import (
    RowsNotMaterialized,
    channel_split,
    funnel,
    loaders,
    service,
)
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.order_profit import OrderStatus
from juli_backend.services.shopee_recommendations import (
    change_sets,
    execution_state,
    kinds,
    month_plan,
    plan_groups,
    plans,
)
from juli_backend.services.shopee_recommendations import service as reco_service

_CHANNEL_FIELDS = ("views", "clicks", "orders", "gmv", "cost")
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
    ln, bd = pair
    if ln.status in (OrderStatus.CANCELLED, OrderStatus.IN_TRANSIT):
        return 0.0
    return float((bd.voucher or 0) + (bd.bundle or 0))


def _offer_cost(view: PeriodView, product: str | None = None, day: date | None = None) -> float:
    """Chi phí ưu đãi = the shop's voucher share + combo discount of the lines (seller-funded)."""
    total = 0.0
    for pair in view.pairs:
        ln = pair[0]
        if (product is None or ln.product_id == product) and (day is None or ln.order_date == day):
            total += _line_offer(pair)
    return total


def _aff_cost_day(view: PeriodView, day: date, product: str | None = None) -> float | None:
    known = [
        ln.commission for ln, _ in view.pairs
        if ln.affiliate and ln.order_date == day and ln.commission is not None
        and (product is None or ln.product_id == product)
    ]  # fmt: skip
    return float(sum(known)) if known else None


def _figures(split: dict[str, Any]) -> tq.Figures:
    """One scope's Figures from a ``channel_split`` answer."""
    by = {r["key"]: r for r in split["rows"]}
    k = split["kpis"]
    channels: dict[str, tq.Channel] = {}
    for key in tq.CHANNELS:
        r = by.get(key) or {}
        channels[key] = tq.Channel(
            _f(r.get("views")), _f(r.get("clicks")), _f(r.get("orders")), _f(r.get("gmv")),
            {"ads": _f(k["cost_ads"]), "affiliate": _f(k["cost_affiliate"])}.get(key),
        )  # fmt: skip
    return tq.Figures(
        channels=channels, gmv=_f(k["gmv"]), orders=_f(k["orders"]), profit=_f(k["profit"]),
        ads_cost=_f(k["cost_ads"]), aff_cost=_f(k["cost_affiliate"]),
        offer_cost=_f(k["cost_offers"]),
    )  # fmt: skip


def _residual(shop: tq.Figures, parts: list[tq.Figures]) -> tq.Figures:
    """Shop minus the products, field by field (``None`` where the shop has none)."""

    def sub(a: float | None, vals: list[float | None]) -> float | None:
        return None if a is None else a - sum(v for v in vals if v is not None)

    channels = {}
    for key in tq.CHANNELS:
        s = shop.channel(key)
        ps = [p.channel(key) for p in parts]
        channels[key] = tq.Channel(
            *(sub(getattr(s, n), [getattr(p, n) for p in ps]) for n in _CHANNEL_FIELDS)
        )  # fmt: skip
    return tq.Figures(
        channels=channels,
        gmv=sub(shop.gmv, [p.gmv for p in parts]),
        orders=sub(shop.orders, [p.orders for p in parts]),
        profit=sub(shop.profit, [p.profit for p in parts]),
        ads_cost=sub(shop.ads_cost, [p.ads_cost for p in parts]),
        aff_cost=sub(shop.aff_cost, [p.aff_cost for p in parts]),
        offer_cost=sub(shop.offer_cost, [p.offer_cost for p in parts]),
    )  # fmt: skip


def _gmv_of(listing: dict[str, Any], product_id: str) -> float:
    for p in listing["products"]:
        if p["product_id"] == product_id:
            return float(p.get("gmv") or 0)
    return 0.0


def _residual_plan(shop: tq.Figures, parts: list[tq.Figures]) -> dict[str, Any]:
    """The "Cả shop" row's baseline / goal: the shop's minus the products' (a product without a
    goal takes none), so each column adds up to the shop."""

    def sub(total: float | None, vals: list[float | None]) -> float | None:
        return None if total is None else total - sum(v for v in vals if v is not None)

    return {
        k: sub(getattr(shop, k), [getattr(p, k) for p in parts])
        for k in ("baseline_gmv", "goal_gmv", "baseline_profit", "goal_profit")
    }


def _plan_of(r: dict[str, Any]) -> dict[str, Any]:
    return {k: _f(r.get(k)) for k in ("baseline_gmv", "goal_gmv", "baseline_profit", "goal_profit")}


async def _plan(
    session: AsyncSession, shop_id: uuid.UUID, window: Window, view: PeriodView, now: datetime,
    product_id: str | None = None, daily: bool = False,
) -> dict[str, Any]:  # fmt: skip
    """The running-plan figures of the period and level: exactly the Kế hoạch card's."""
    return await month_plan.range_plan(
        session, shop_id, window.start, window.end, scope=month_plan.SCOPE_RUNNING, now=now,
        view=view, product_id=product_id, daily=daily,
    )  # fmt: skip


def _day_scope(rows: funnel.FunnelRows, day: date, product: str | None) -> funnel.FunnelRows:
    return replace(
        rows, window=Window(day, day),
        sources=tuple(s for s in rows.sources if s.day == day),
        shop_days=tuple(s for s in rows.shop_days if s.day == day),
        product_days=tuple(s for s in rows.product_days if s.day == day),
    )  # fmt: skip


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
    cur, prv = window, window.previous()
    kw: dict[str, Any] = {"period": "custom", "start": cur.start, "end": cur.end}
    kw_prev: dict[str, Any] = {"period": "custom", "start": prv.start, "end": prv.end}
    view, frows = await _view(session, shop_id, cur)
    try:
        pview: PeriodView | None = (await _view(session, shop_id, prv))[0]
    except RowsNotMaterialized:  # no stored days before the period: nothing to compare with
        pview = None

    listing = await channel_split.channel_split_products(session, shop_id, **kw)
    names = {p["product_id"]: p["name"] for p in listing["products"]}
    if pview is not None:
        prev_listing = await channel_split.channel_split_products(session, shop_id, **kw_prev)
        names.update({p["product_id"]: p["name"] for p in prev_listing["products"]})

    async def figures(v: PeriodView | None, w: Window, pid: str | None) -> tq.Figures:
        if v is None:
            return tq.Figures()
        return _figures(await channel_split.split_figures(session, shop_id, v, w, pid))

    shop_now = await figures(view, cur, None)
    shop_prev = await figures(pview, prv, None)
    shop_plan = await _plan(session, shop_id, cur, view, now, daily=product_id is None)
    shop_now = replace(shop_now, **_plan_of(shop_plan))

    rows: list[tq.ProductRow] = []
    ids = [product_id] if product_id else sorted(names, key=lambda i: -_gmv_of(listing, i))
    plans_of: dict[str, dict[str, Any]] = {}
    for i in ids:
        plans_of[i] = await _plan(session, shop_id, cur, view, now, product_id=i,
                                  daily=i == product_id)  # fmt: skip
        now_fig = replace(await figures(view, cur, i), **_plan_of(plans_of[i]))
        rows.append(tq.ProductRow(i, names.get(i, i), now_fig, await figures(pview, prv, i)))
    if product_id:  # the Sản phẩm level: the file's period figures are the product's
        shop_now, shop_prev = rows[0].now, rows[0].prev
    else:
        rest = tq.ProductRow(
            tq.SHOP_ROW_LABEL, "", _residual(shop_now, [r.now for r in rows]),
            _residual(shop_prev, [r.prev for r in rows]),
        )  # fmt: skip
        rest.now = replace(rest.now, **_residual_plan(shop_now, [r.now for r in rows]))
        rows.append(rest)

    day_plan = {d["day"]: d for d in (plans_of[product_id] if product_id else shop_plan)["daily"]}
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
        t = day_plan.get(d.isoformat(), {})
        days.append(
            tq.DayRow(
                d,
                {key: _f(by[key]["gmv"]) for key in tq.CHANNELS},
                {key: _f(by[key]["orders"]) for key in tq.CHANNELS},
                _f(sd.ads_spend) if product_id and sd else None if product_id else _f(spend.get(d)),
                _aff_cost_day(view, d, product_id),
                _offer_cost(view, product_id, d),
                None if sd is None else _f(sd.profit),
                **_plan_of(t),
            )  # fmt: skip
        )
    skus = await _sku_rows(
        session, shop_id, view, cur, plans_of, list(ids), names,
        period=period, month=month, now=now,
    )  # fmt: skip
    return tq.TongQuanData(
        shop_name, cur.start, cur.end, prv.start, prv.end, shop_now, shop_prev, days, rows,
        platform, product_name=names.get(product_id, product_id) if product_id else None,
        product_id=product_id, skus=skus,
    )  # fmt: skip


async def _sku_rows(
    session: AsyncSession, shop_id: uuid.UUID, view: PeriodView, window: Window,
    plans_of: dict[str, dict[str, Any]], product_ids: list[str], names: dict[str, str], *,
    period: str, month: str | None, now: datetime,
) -> list[tq.SkuRow]:  # fmt: skip
    """The "Theo SKU" rows (``exports/sku``): actuals of the period, stock at its end, goals split
    from each product's own Kế hoạch figures."""
    now_figs = await skumod.sku_figures(session, shop_id, view, window)
    base: dict[str, dict[skumod.SkuKey, skumod.Fig]] = {}
    cache: dict[tuple[str, str], dict[skumod.SkuKey, skumod.Fig]] = {}
    for pid in product_ids:
        bw = (plans_of.get(pid) or {}).get("baseline_window")
        if not bw or (plans_of[pid].get("goal_gmv") is None):
            continue
        key = (bw["from"], bw["to"])
        if key not in cache:
            w = Window(date.fromisoformat(bw["from"]), date.fromisoformat(bw["to"]))
            try:
                bview, _ = await _view(session, shop_id, w)
                cache[key] = await skumod.sku_figures(session, shop_id, bview, w)
            except RowsNotMaterialized:
                cache[key] = {}
        base[pid] = {k: f for k, f in cache[key].items() if k[0] == pid}
    ctx = await loaders.load_context(session, shop_id)
    catalog_variations = {
        pid: [(v.variation_id, v.name, v.seller_sku) for v in info.variations]
        for pid in product_ids
        if (info := ctx.catalog.items.get(pid)) is not None
    }
    stock = await skumod.stock_at(session, shop_id, product_ids, window.end)
    period_end = window.end
    if period == "month" and month:
        first = date(int(month[:4]), int(month[5:7]), 1)
        period_end = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    finished = period_end <= window.end
    plans_full = None
    if not finished:  # the goal of the whole period (the month's end is still ahead)
        plans_full = {
            pid: await month_plan.range_plan(
                session, shop_id, window.start, period_end, scope=month_plan.SCOPE_RUNNING,
                now=now, view=view, product_id=pid, actual_to=window.end,
            )
            for pid in product_ids
        }  # fmt: skip
    rows = skumod.build_rows(
        product_ids=product_ids, names=names, now=now_figs, base=base, plans=plans_of, stock=stock,
        catalog_variations=catalog_variations, finished=finished, plans_full=plans_full,
    )  # fmt: skip
    return [
        tq.SkuRow(
            r.sku,
            r.variation,
            r.product_name,
            r.units_goal,
            r.units,
            r.revenue_goal,
            r.revenue,
            r.profit_goal,
            r.profit,
            r.stock,
            r.need,
        )
        for r in rows
    ]


# ----------------------------------------------------------------------------- Kế hoạch


def _card_row(
    card: Mapping[str, Any], plan_code: str | None, status: str, ev: Mapping[str, Any] | None,
    names: dict[str, str],
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
    return kh.CardRow(
        code=card["code"], plan_code=plan_code, status=status,
        group=GROUP_OF_FAMILY.get(card.get("family") or "", ""),
        kind=spec.label if spec else kind, version=version,
        product_id=card.get("product_id"), product_name=names.get(card.get("product_id") or ""),
        metrics=METRIC_LABELS.get(spec.target_metric) if spec else None,
        start=date.fromisoformat(dates["from"]) if dates.get("from") else None,
        end=date.fromisoformat(dates["to"]) if dates.get("to") else None,
        cost=_f(own.get("cost_total")),
        gmv_mid=q("p50", "dgmv"), profit_mid=q("p50", "dprofit"),
    )  # fmt: skip


VERDICT_TEXT = {
    execution_state.VERDICT_RUNNING: "Đang đo",
    execution_state.VERDICT_INSIDE: "Trong khoảng",
    execution_state.VERDICT_BELOW: "Dưới khoảng",
    execution_state.VERDICT_ABOVE: "Vượt khoảng",
}


def _result_text(row: Mapping[str, Any]) -> str | None:
    """ "<Δ lợi nhuận thực tế> · <kết luận>" of one Đo lường row (``execution_state``'s own actual
    and verdict); ``None`` when it has neither."""
    actual, verdict_key = row.get("actual"), row.get("verdict")
    verdict = VERDICT_TEXT.get(verdict_key) if isinstance(verdict_key, str) else None
    money = None if actual is None else f"{round(float(actual)):+,}".replace(",", ".") + " đ"
    parts = [p for p in (money, verdict) if p]
    return " · ".join(parts) or None


async def collect_ke_hoach(
    session: AsyncSession, shop_id: uuid.UUID, *, shop_name: str, now: datetime,
    month: str | None = None, platform: str = "Shopee",
) -> kh.KeHoachData:  # fmt: skip
    """The Kế hoạch workbook's numbers of ``month`` (YYYY-MM; default the newest data month),
    month to date up to the newest data day inside it."""
    window = await service.resolve(session, shop_id)
    if window is None:
        raise ValueError("no data")
    if month is None:
        first = window.end.replace(day=1)
    else:
        first = date(int(month[:4]), int(month[5:7]), 1)
    if first > window.end:
        raise ValueError("month after the newest data day")
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    anchor = min(window.end, last)
    both = await month_plan.month_plans(session, shop_id, now=now, anchor=anchor)
    run = both[month_plan.SCOPE_RUNNING]
    listing = await channel_split.channel_split_products(
        session, shop_id, period="custom", start=first, end=anchor
    )
    names = {p["product_id"]: p["name"] for p in listing["products"]}
    # actual per day of the month so far: the stored daily rows
    view, rows = await _view(session, shop_id, Window(first, anchor))
    actual_gmv = {d.day: float(d.gmv) for d in rows.shop_days}
    actual_profit = {d.day: float(d.profit) for d in rows.shop_days if d.profit is not None}

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
                end = ((ev or {}).get("result") or {}).get("own", {}) or {}
                ended = bool(end.get("dates")) and date.fromisoformat(end["dates"]["to"]) < anchor
                status = (
                    kh.MEASURED if s and s["status"] in (change_sets.SET_DONE, change_sets.SET_CUT)
                    else kh.MEASURING if s and ended else kh.RUNNING
                )  # fmt: skip
            out.append(_card_row(c, payload["plan"]["code"], status, ev, names))
            seen.add(c["card_id"])
    # measuring / measured cards of the month that no plan holds
    listed = (
        await reco_service.list_cards(session, shop_id, audience="seller", queue="all", now=now)
    )["cards"]
    sets_by_card = {}
    for cs in await change_sets.sets_for(session, shop_id):
        for cid in cs.card_ids or []:
            sets_by_card[str(cid)] = cs
    for c in listed:
        s = sets_by_card.get(c["id"])
        if c["id"] in seen or c.get("plan_id") or s is None:
            continue
        end = s.started_at.date() + timedelta(days=s.window_days)
        if end < first or s.executed_on > anchor:
            continue
        closed = s.status in (change_sets.SET_DONE, change_sets.SET_CUT)
        pm = c["predicted_summary"]
        row = _card_row(c, None, kh.MEASURED if closed else kh.MEASURING, None, names)
        row.start, row.end = s.executed_on, end
        # one card, one number: the card's stored result (its own days), as the card shows it
        row.gmv_mid = _f(pm["dgmv"]["p50"])
        row.profit_mid = _f(pm["dprofit"]["p50"])
        row.cost = _f(c.get("cost"))
        out.append(row)
    measured = {
        c["code"]: _result_text(c)
        for c in (await execution_state.measurement_states(session, shop_id, now=now))["cards"]
    }
    for row in out:
        row.result = measured.get(row.code)
    return kh.KeHoachData(
        shop_name, first, anchor,
        float(run["baseline_gmv"] or 0), float(run["baseline_profit"] or 0),
        actual_gmv, actual_profit, out, platform,
    )  # fmt: skip


__all__ = ["collect_ke_hoach", "collect_tong_quan"]
