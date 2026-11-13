"""Reads the numbers of the two exports through the app's own service functions.

Nothing is computed here that a service already computes: the channel table comes from
``channel_split`` (the Tổng quan numbers, shop and each product), the month figures from
``month_plan``, the cards and their Δ from ``plans.get_plan`` / ``service.list_cards``, the daily
rows from the stored funnel rows (``funnel.load_rows``: the shopee metrics tables) and the ads
report's ``spend_by_day``.

Kế hoạch baseline and goal for a period / day / product (rule, owner 2026-11-13): the plan
aggregate's own "today" level of the EARLIEST executed plan (the pre-plan level, a 30-day figure)
is the baseline, per day = level / 30 (``HORIZON_DAYS``); goal = baseline + the P50 Δ of the
running cards (the cards of executed plans) on their days inside the period (``month_plan.
uplift_in_month``: a card's own-days Δ spread evenly over its own days). A product's baseline is
its row of that aggregate (``aggregate.products[].today``) when the plan has one, else its
pre-plan 30-day level read from the data (funnel GMV, ``profit.products`` profit) on the
aggregate's own window; its uplift is that of the running cards of that product. Cards with no
product go to the "Cả shop" row, which also carries the shop baseline minus the products', so the
product targets add up to the shop target. No running card -> no goal (``None``).
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_plans import PLAN_DRAFT, PLAN_EXECUTED
from juli_backend.services.exports import ke_hoach_xlsx as kh
from juli_backend.services.exports import tong_quan_xlsx as tq
from juli_backend.services.shopee_analytics import channel_split, funnel, loaders, service
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.order_profit import OrderStatus
from juli_backend.services.shopee_recommendations import (
    change_sets,
    kinds,
    month_plan,
    plan_groups,
    plans,
)
from juli_backend.services.shopee_recommendations import service as reco_service
from juli_backend.services.shopee_recommendations.plan_aggregate import HORIZON_DAYS

PERIOD_DAYS = 30
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


# ----------------------------------------------------------------------------- running plans


class Running:
    """The running cards (executed plans) and the pre-plan baseline of the earliest one."""

    def __init__(self, cards: list[dict[str, Any]], today: dict[str, Any] | None,
                 products: dict[str, dict[str, Any]], as_of: date | None) -> None:  # fmt: skip
        self.cards = cards
        self.today = today
        self.products = products
        self.as_of = as_of

    @classmethod
    async def load(cls, session: AsyncSession, shop_id: uuid.UUID, now: datetime) -> Running:
        cards: list[dict[str, Any]] = []
        today: dict[str, Any] | None = None
        products: dict[str, dict[str, Any]] = {}
        as_of: date | None = None
        for plan in await month_plan._executed(session, shop_id):
            out = await plans.get_plan(session, shop_id, plan.id, now=now, audience="seller")
            cards += month_plan._cards_of(out)
            if today is None:
                agg = out.get("aggregate") or {}
                today = agg.get("today")
                products = {p["product_id"]: p.get("today") or {} for p in agg.get("products", [])}
                as_of = date.fromisoformat(agg["as_of"]) if agg.get("as_of") else None
        return cls(cards, today, products, as_of)

    def uplift(self, first: date, last: date, product: str | None | bool = False):
        """(Δ GMV, Δ lợi nhuận, cards counted) of the running cards on first..last; ``product``
        False = every card, None = the cards with no product, an id = that product's cards."""
        pick = [
            c for c in self.cards
            if product is False or (c.get("product_id") or None) == product
        ]  # fmt: skip
        return month_plan.uplift_in_month(pick, first, last)

    def level(self, key: str) -> float | None:
        v = None if self.today is None else self.today.get(key)
        return None if v is None else float(v)


def _targets(
    base_gmv: float | None, base_profit: float | None, up: tuple[float, float, int], days: int
) -> dict[str, float | None]:
    """baseline / goal for ``days`` days from a 30-day level and an uplift."""
    k = days / HORIZON_DAYS
    bg = None if base_gmv is None else base_gmv * k
    bp = None if base_profit is None else base_profit * k
    n = up[2]
    return {
        "baseline_gmv": bg, "baseline_profit": bp,
        "goal_gmv": None if n == 0 or bg is None else bg + up[0],
        "goal_profit": None if n == 0 or bp is None else bp + up[1],
    }  # fmt: skip


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


def _aff_cost_day(view: PeriodView, day: date) -> float | None:
    known = [
        ln.commission for ln, _ in view.pairs
        if ln.affiliate and ln.order_date == day and ln.commission is not None
    ]  # fmt: skip
    return float(sum(known)) if known else None


def _figures(split: dict[str, Any], offer: float) -> tq.Figures:
    """One scope's Figures from a ``channel_split`` answer."""
    by = {r["key"]: r for r in split["rows"]}
    k = split["kpis"]
    channels: dict[str, tq.Channel] = {}
    for key in tq.CHANNELS:
        r = by.get(key) or {}
        channels[key] = tq.Channel(
            _f(r.get("views")), _f(r.get("clicks")), _f(r.get("orders")), _f(r.get("gmv")),
            {"ads": _f(k["ads_cost"]), "affiliate": _f(k["affiliate_cost"])}.get(key),
        )  # fmt: skip
    return tq.Figures(
        channels=channels, gmv=_f(k["gmv"]), orders=_f(k["orders"]), profit=_f(k["profit"]),
        ads_cost=_f(k["ads_cost"]), aff_cost=_f(k["affiliate_cost"]), offer_cost=offer,
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


async def _product_base(
    session: AsyncSession, shop_id: uuid.UUID, running: Running, ids: list[str]
) -> dict[str, tuple[float | None, float | None]]:
    """Pre-plan 30-day (GMV, profit) of each product: the aggregate's row, else the data."""
    out: dict[str, tuple[float | None, float | None]] = {}
    missing = [i for i in ids if not running.products.get(i)]
    for i in ids:
        row = running.products.get(i)
        if row:
            out[i] = (_f(row.get("gmv_30d")), _f(row.get("profit_30d")))
    if missing and running.as_of is not None:
        w = Window(running.as_of - timedelta(days=PERIOD_DAYS - 1), running.as_of)
        view, rows = await _view(session, shop_id, w)
        for i in missing:
            base = funnel.base_from_rows(rows, str(shop_id), item_ids=(i,))
            pp = view.profit.products.get(i)
            out[i] = (_f(base.total("gmv")), None if pp is None else _f(pp.profit))
    return out


async def collect_tong_quan(
    session: AsyncSession, shop_id: uuid.UUID, *, shop_name: str, now: datetime,
    platform: str = "Shopee",
) -> tq.TongQuanData:  # fmt: skip
    anchor_window = await service.resolve(session, shop_id)
    assert anchor_window is not None
    end = anchor_window.end
    cur = Window(end - timedelta(days=PERIOD_DAYS - 1), end)
    prv = Window(cur.start - timedelta(days=PERIOD_DAYS), cur.start - timedelta(days=1))
    running = await Running.load(session, shop_id, now)
    base_gmv, base_profit = running.level("gmv_30d"), running.level("profit_30d")

    figures: dict[str, tq.Figures] = {}
    product_figures: dict[str, dict[str, tq.Figures]] = {"now": {}, "prev": {}}
    names: dict[str, str] = {}
    views: dict[str, tuple[PeriodView, funnel.FunnelRows]] = {}
    for tag, w in (("now", cur), ("prev", prv)):
        kw = {"period": "custom", "start": w.start, "end": w.end}
        views[tag] = await _view(session, shop_id, w)
        split = await channel_split.channel_split(session, shop_id, **kw)
        figures[tag] = _figures(split, _offer_cost(views[tag][0]))
        listing = await channel_split.channel_split_products(session, shop_id, **kw)
        for p in listing["products"]:
            names[p["product_id"]] = p["name"]
            ps = await channel_split.channel_split(
                session, shop_id, product_id=p["product_id"], **kw
            )
            product_figures[tag][p["product_id"]] = _figures(
                ps, _offer_cost(views[tag][0], p["product_id"])
            )
    with_cards = {c["product_id"] for c in running.cards if c.get("product_id")}
    ids = sorted({*product_figures["now"], *product_figures["prev"], *with_cards})
    for tag in ("now", "prev"):
        for i in ids:
            product_figures[tag].setdefault(i, tq.Figures())

    shop_up = running.uplift(cur.start, cur.end)
    n_running = shop_up[2]
    now_fig = replace(figures["now"], **_targets(base_gmv, base_profit, shop_up, PERIOD_DAYS))
    pbase = await _product_base(session, shop_id, running, ids)
    rows: list[tq.ProductRow] = []
    for i in sorted(ids, key=lambda x: -(product_figures["now"][x].gmv or 0)):
        up = (*running.uplift(cur.start, cur.end, i)[:2], n_running)
        bg, bp = pbase.get(i, (None, None))
        product_figures["now"][i] = replace(
            product_figures["now"][i], **_targets(bg, bp, up, PERIOD_DAYS)
        )
        rows.append(
            tq.ProductRow(i, names.get(i, i), product_figures["now"][i], product_figures["prev"][i])
        )
    shop_row = tq.ProductRow(
        tq.SHOP_ROW_LABEL, "",
        _residual(now_fig, [r.now for r in rows]),
        _residual(figures["prev"], [r.prev for r in rows]),
    )  # fmt: skip
    sb = sum(v[0] for v in pbase.values() if v[0] is not None)
    sp = sum(v[1] for v in pbase.values() if v[1] is not None)
    shop_row.now = replace(
        shop_row.now,
        **_targets(
            None if base_gmv is None else base_gmv - sb,
            None if base_profit is None else base_profit - sp,
            (*running.uplift(cur.start, cur.end, None)[:2], n_running), PERIOD_DAYS,
        ),
    )  # fmt: skip
    rows.append(shop_row)

    view, frows = views["now"]
    shop_days = {d.day: d for d in frows.shop_days}
    spend = view.data.ads_daily.spend_by_day
    days: list[tq.DayRow] = []
    for k in range(PERIOD_DAYS):
        d = cur.start + timedelta(days=k)
        one = replace(
            frows, window=Window(d, d),
            sources=tuple(s for s in frows.sources if s.day == d),
            shop_days=tuple(s for s in frows.shop_days if s.day == d),
            product_days=tuple(s for s in frows.product_days if s.day == d),
        )  # fmt: skip
        by = {
            r["key"]: r for r in channel_split.split_rows(funnel.base_from_rows(one, str(shop_id)))
        }
        sd = shop_days.get(d)
        t = _targets(base_gmv, base_profit, running.uplift(d, d), 1)
        days.append(
            tq.DayRow(
                d,
                {key: _f(by[key]["gmv"]) for key in tq.CHANNELS},
                {key: _f(by[key]["orders"]) for key in tq.CHANNELS},
                _f(spend.get(d)),
                _aff_cost_day(view, d),
                _offer_cost(view, day=d),
                None if sd is None else _f(sd.profit),
                **t,
            )  # fmt: skip
        )
    return tq.TongQuanData(
        shop_name, cur.start, cur.end, prv.start, prv.end, now_fig, figures["prev"], days, rows,
        platform,
    )  # fmt: skip


# ----------------------------------------------------------------------------- Kế hoạch


def _card_row(
    card: dict[str, Any], plan_code: str | None, status: str, ev: dict[str, Any] | None,
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
        gmv_low=q("p10", "dgmv"), gmv_mid=q("p50", "dgmv"), gmv_high=q("p90", "dgmv"),
        profit_low=q("p10", "dprofit"), profit_mid=q("p50", "dprofit"),
        profit_high=q("p90", "dprofit"),
        orders=q("p50", "dorders"),
    )  # fmt: skip


async def collect_ke_hoach(
    session: AsyncSession, shop_id: uuid.UUID, *, shop_name: str, now: datetime,
    platform: str = "Shopee",
) -> kh.KeHoachData:  # fmt: skip
    window = await service.resolve(session, shop_id)
    assert window is not None
    anchor = window.end
    first = anchor.replace(day=1)
    both = await month_plan.month_plans(session, shop_id, now=now, anchor=anchor)
    run = both[month_plan.SCOPE_RUNNING]
    listing = await channel_split.channel_split_products(session, shop_id, period="30d")
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
            plan_groups.split_entry_id(c["card_id"])[0]: c for c in month_plan._cards_of(payload)
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
        row.gmv_low, row.gmv_mid, row.gmv_high = (
            _f(pm["dgmv_month"][p]) for p in ("p10", "p50", "p90")
        )
        row.profit_low, row.profit_mid, row.profit_high = (
            _f(pm["dprofit_month"][p]) for p in ("p10", "p50", "p90")
        )
        out.append(row)
    return kh.KeHoachData(
        shop_name, first, anchor,
        float(run["baseline_gmv"] or 0), float(run["baseline_profit"] or 0),
        actual_gmv, actual_profit, out, platform,
    )  # fmt: skip


__all__ = ["Running", "collect_ke_hoach", "collect_tong_quan"]
