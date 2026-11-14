"""P100 canvas: the month figures of Kế hoạch -- ONE computation behind Tổng quan's month card and
the Kế hoạch screen's two totals ("Đang chạy" / "Nếu áp dụng nháp").

Rules (owner 2026-11-13):

- **Running** = the cards of ``executed`` plans (a ``confirmed`` plan does not count yet).
  **Draft** = the cards of the shop's draft plan. Kế hoạch is the whole shop, never
  product-filtered.
- The goals are accumulated from the strategies, not read from Cài đặt › Mục tiêu:
  ``goal = baseline + uplift`` where
  ``baseline`` = the plan aggregate's own "today" level (``aggregate.today.gmv_30d`` /
  ``profit_30d``, a 30-day level) as a per-day figure (÷ ``HORIZON_DAYS``) x the days of
  the month;
  ``uplift`` = the sum over the cards of their P50 Δ (GMV / lợi nhuận), each card's own-days Δ
  spread evenly over its own days and counted only for the days that fall inside the month.
- The baseline is the frozen "today" of the EARLIEST executed plan (the pre-plan level, so the
  running cards' own effect is not added onto a level that already contains it); with no executed
  plan it is the draft's live "today".
- No running card -> no running goal (``goal_*`` is ``None``, never 0). An unknown Δ (``None``)
  is not counted; a card with no estimate adds nothing.
- ``mtd_*`` is the month to date up to ``anchor`` (the newest data day by default).
- **Per product** (``product_id``): the cards counted are the running cards of THAT product
  (``card["product_id"]``); shop-wide cards (no product, or a card over several products) count at
  the Shop level only, so product uplifts + the shop-wide uplift = the shop uplift. The product
  baseline is the product's own 30-day level frozen in the earliest executed plan's aggregate
  (``aggregate.products[].today``: the plan's per-product rows); a product with no row there (or
  no executed plan) takes its level from the stored data of the 30 days before that plan (before
  today without one). ``None`` when neither exists, so there is no goal, never a 0.
- Any period: :func:`range_plans` is the one computation; the month is a thin wrapper over it
  (goal = baseline per day x days + the running cards' uplift on the days inside the range).
"""

from __future__ import annotations

import calendar
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_plans import PLAN_EXECUTED, ShopRecoPlan
from juli_backend.services.shopee_analytics import loaders, service
from juli_backend.services.shopee_analytics.compute import PeriodView
from juli_backend.services.shopee_analytics.fmt import num
from juli_backend.services.shopee_analytics.shared import shop_profit_of
from juli_backend.services.shopee_analytics.stored import RowsNotMaterialized
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_recommendations import plans
from juli_backend.services.shopee_recommendations.plan_aggregate import HORIZON_DAYS

SCOPE_RUNNING = "running"
SCOPE_RUNNING_DRAFT = "running+draft"
SCOPES = (SCOPE_RUNNING, SCOPE_RUNNING_DRAFT)


def plan_cards(out: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The cards' evaluation blocks of a plan payload: its own aggregate plus each group's."""
    cards = list((out.get("aggregate") or {}).get("cards") or [])
    for g in out.get("groups") or []:
        cards += list((g.get("aggregate") or {}).get("cards") or [])
    return cards


def cards_of_product(
    cards: Iterable[Mapping[str, Any]], product_id: str | None
) -> list[Mapping[str, Any]]:
    """The cards of one product; ``None`` = every card (the Shop level). A shop-wide card (no
    product) belongs to the Shop level only."""
    return [c for c in cards if product_id is None or c.get("product_id") == product_id]


def card_sku_scope(card: Mapping[str, Any]) -> frozenset[str] | None:
    """The SKUs a plan card is scoped to: the SKU rows of its chosen version (a per-SKU price /
    discount card keeps them), else its what-if rows. ``None`` = a product-level card (every SKU
    of the product)."""
    chosen = next(
        (v for v in card.get("versions") or [] if v.get("version") == card.get("chosen_version")),
        None,
    )
    for source in ((chosen or {}).get("inputs"), card.get("what_if")):
        rows = (source or {}).get("variations")
        skus = {str(r["sku"]) for r in rows or [] if isinstance(r, Mapping) and r.get("sku")}
        if skus:
            return frozenset(skus)
    return None


def _scopes_of(out: Mapping[str, Any]) -> dict[str, frozenset[str] | None]:
    """``card_sku_scope`` of each card of a plan payload, by card id."""
    return {str(c["card_id"]): card_sku_scope(c) for c in out.get("cards") or []}


def _scope_of_block(
    scopes: Mapping[str, frozenset[str] | None], block: Mapping[str, Any]
) -> frozenset[str] | None:
    cid = str(block.get("card_id"))
    return scopes.get(cid) or scopes.get(cid.split("#")[0])


def _days_in(span_from: date, span_to: date, first: date, last: date) -> int:
    lo, hi = max(span_from, first), min(span_to, last)
    return 0 if hi < lo else (hi - lo).days + 1


def uplift_in_month(
    cards: Iterable[Mapping[str, Any]], first: date, last: date
) -> tuple[float, float, int]:
    """(Δ GMV, Δ lợi nhuận, cards counted) of ``cards`` inside ``first``..``last``: the P50 Δ of
    each card's own dates, per own day, x its days inside the month."""
    gmv = profit = 0.0
    counted = 0
    for c in cards:
        own = (c.get("result") or {}).get("own")
        if not own or not own.get("dates") or not own.get("days"):
            continue
        d = own["dates"]
        n = _days_in(date.fromisoformat(d["from"]), date.fromisoformat(d["to"]), first, last)
        if n == 0:
            continue
        p50 = (own.get("delta") or {}).get("p50") or {}
        k = n / int(own["days"])
        counted += 1
        gmv += (p50.get("dgmv") or 0.0) * k
        profit += (p50.get("dprofit") or 0.0) * k
    return gmv, profit, counted


async def _executed(session: AsyncSession, shop_id: uuid.UUID) -> list[ShopRecoPlan]:
    return list(
        await session.scalars(
            select(ShopRecoPlan)
            .where(ShopRecoPlan.shop_id == shop_id, ShopRecoPlan.status == PLAN_EXECUTED)
            .order_by(ShopRecoPlan.confirmed_at, ShopRecoPlan.created_at)
        )
    )


async def _view_of(session: AsyncSession, shop_id: uuid.UUID, window: Window) -> PeriodView:
    ctx = await loaders.load_context(session, shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{window.end:%Y-%m}"))
    return await service.load_view(session, shop_id, ctx, window, funnel=True)


async def _product_figures(
    session: AsyncSession, shop_id: uuid.UUID, view: PeriodView, window: Window, product_id: str
) -> tuple[Any, Any]:
    """(GMV, lợi nhuận) of one product over the view's window -- the figures Tổng quan's Sản phẩm
    level shows (funnel base total, the product's profit)."""
    from juli_backend.services.shopee_analytics import funnel

    rows = view.data.funnel
    if rows is None:
        rows = await funnel.load_rows(session, shop_id, window)
    base = funnel.base_from_rows(rows, str(shop_id), item_ids=(product_id,))
    pp = view.profit.products.get(product_id)
    return base.total("gmv"), None if pp is None else pp.profit


async def _actual(
    session: AsyncSession,
    shop_id: uuid.UUID,
    first: date,
    to: date,
    view: PeriodView | None,
    product_id: str | None = None,
) -> tuple[Any, Any]:
    """(GMV, lợi nhuận) of ``first``..``to`` -- ``view`` when the caller already loaded it."""
    if to < first:  # the range starts after the newest data day: nothing happened yet
        return None, None
    window = Window(first, to)
    if view is None:
        view = await _view_of(session, shop_id, window)
    if product_id is not None:
        return await _product_figures(session, shop_id, view, window, product_id)
    return view.shop_gmv, shop_profit_of(view).profit


def _product_row(out: Mapping[str, Any] | None, product_id: str) -> Mapping[str, Any] | None:
    """The plan aggregate's per-product "today" row of ``product_id`` (own or a group's)."""
    if out is None:
        return None
    aggs = [out.get("aggregate") or {}] + [
        g.get("aggregate") or {} for g in out.get("groups") or []
    ]
    for agg in aggs:
        for p in agg.get("products") or []:
            if p.get("product_id") == product_id and p.get("today"):
                return p["today"]
    return None


async def _product_level(
    session: AsyncSession,
    shop_id: uuid.UUID,
    product_id: str,
    row: Mapping[str, Any] | None,
    before: date,
) -> Mapping[str, Any] | None:
    """The product's 30-day level ``{gmv_30d, profit_30d}``: the plan's per-product row, else the
    stored data of the ``HORIZON_DAYS`` days before ``before``."""
    if row is not None:
        return row
    last = before - timedelta(days=1)
    try:
        window = Window(last - timedelta(days=HORIZON_DAYS - 1), last)
        view = await _view_of(session, shop_id, window)
        gmv, profit = await _product_figures(session, shop_id, view, window, product_id)
    except RowsNotMaterialized:
        return None
    return {
        "gmv_30d": None if gmv is None else float(gmv),
        "profit_30d": None if profit is None else float(profit),
    }


async def running_range(
    session: AsyncSession,
    shop_id: uuid.UUID,
    product_id: str | None = None,
    *,
    now: datetime,
) -> tuple[date, date] | None:
    """ "Cả kế hoạch": the earliest start and the latest end of the RUNNING (executed-plan) cards'
    own dates -- every running card at the Shop level, that product's at the Sản phẩm level.
    ``None`` when no running card has dates."""
    cards: list[Mapping[str, Any]] = []
    for plan in await _executed(session, shop_id):
        out = await plans.get_plan(session, shop_id, plan.id, now=now, audience="seller")
        cards += plan_cards(out)
    spans: list[tuple[date, date]] = []
    for c in cards_of_product(cards, product_id):
        d = ((c.get("result") or {}).get("own") or {}).get("dates")
        if d:
            spans.append((date.fromisoformat(d["from"]), date.fromisoformat(d["to"])))
    if not spans:
        return None
    return min(a for a, _ in spans), max(b for _, b in spans)


async def range_plans(
    session: AsyncSession,
    shop_id: uuid.UUID,
    first: date,
    last: date,
    *,
    now: datetime,
    actual_to: date | None = None,
    view: PeriodView | None = None,
    draft_payload: Mapping[str, Any] | None = None,
    scopes: tuple[str, ...] = SCOPES,
    product_id: str | None = None,
    daily: bool = False,
) -> dict[str, dict[str, Any]]:
    """The plan figures of ``first``..``last`` (any period) for each of ``scopes``.

    ``daily`` adds ``"daily"``: one ``{day, baseline_*, goal_*}`` per day of the range (the
    baseline spread evenly, the uplift on the day it falls), so the days add up to the range.

    ``product_id`` None = the whole shop.

    ``goal = baseline + uplift``: the baseline is the per-day "today" level x the days of the
    range, the uplift the running cards' own-days Δ on the days that fall inside the range (so
    the goal is the sum over days of baseline-per-day + the uplift per day on that day).
    ``actual_to`` = the last day with data (default ``last``); ``view`` = a view of
    ``first``..``actual_to`` the caller already loaded. ``today_marker`` (fraction of the range
    elapsed) only when today is inside the range; ``ahead`` = actual >= the pro-rated goal."""
    for sc in scopes:
        if sc not in SCOPES:
            raise ValueError(f"unknown scope {sc!r}")
    if last < first:
        raise ValueError("last must not be before first")
    days = (last - first).days + 1
    actual_to = min(actual_to or last, last)
    today = plans.plan_today(now)
    in_range = first <= today <= last
    elapsed = (today - first).days + 1 if in_range else days
    marker = elapsed / days if in_range else None

    running_cards: list[Mapping[str, Any]] = []
    card_scope: dict[int, frozenset[str] | None] = {}  # id(card block) -> its SKU scope
    baseline: Mapping[str, Any] | None = None
    first_out: Mapping[str, Any] | None = None
    first_day: date | None = None
    for plan in await _executed(session, shop_id):
        out = await plans.get_plan(session, shop_id, plan.id, now=now, audience="seller")
        blocks = plan_cards(out)
        sku_scopes = _scopes_of(out)
        card_scope.update({id(b): _scope_of_block(sku_scopes, b) for b in blocks})
        running_cards += blocks
        if baseline is None:
            baseline = (out.get("aggregate") or {}).get("today")
            first_out = out
            stamp = plan.confirmed_at or plan.created_at
            first_day = plans.plan_today(stamp) if stamp is not None else None
    dout: Mapping[str, Any] | None = None
    draft_cards: list[Mapping[str, Any]] = []
    draft_today: Mapping[str, Any] | None = None
    if SCOPE_RUNNING_DRAFT in scopes:
        dout = draft_payload
        if dout is None:
            dout = await plans.get_plan(session, shop_id, None, now=now, audience="seller")
        draft_cards = plan_cards(dout)
        dscopes = _scopes_of(dout)
        card_scope.update({id(b): _scope_of_block(dscopes, b) for b in draft_cards})
        draft_today = (dout.get("aggregate") or {}).get("today")
    base_window: tuple[date, date] | None = None
    if product_id is not None:
        running_cards = cards_of_product(running_cards, product_id)
        draft_cards = cards_of_product(draft_cards, product_id)
        row = _product_row(first_out, product_id) or _product_row(dout, product_id)
        baseline = draft_today = await _product_level(
            session, shop_id, product_id, row, first_day or today
        )
        source = first_out or dout
        as_of = ((source or {}).get("aggregate") or {}).get("today", {}).get("as_of")
        if row is None:  # the product's level was read from the 30 days before the plan
            last_day = (first_day or today) - timedelta(days=1)
            base_window = (last_day - timedelta(days=HORIZON_DAYS - 1), last_day)
        elif as_of:
            end_day = date.fromisoformat(str(as_of)[:10])
            base_window = (end_day - timedelta(days=HORIZON_DAYS - 1), end_day)
        else:
            base_window = None
    actual_gmv, actual_profit = await _actual(session, shop_id, first, actual_to, view, product_id)

    def level(base: Mapping[str, Any] | None, key: str) -> float | None:
        v = None if base is None else base.get(key)
        return None if v is None else float(v) / HORIZON_DAYS * days

    def ahead(actual: Any, goal: float | None) -> bool | None:
        if goal is None or actual is None:
            return None
        return float(actual) >= goal * elapsed / days

    answers: dict[str, dict[str, Any]] = {}
    for sc in scopes:
        cards = running_cards + (draft_cards if sc == SCOPE_RUNNING_DRAFT else [])
        up_gmv, up_profit, n_cards = uplift_in_month(cards, first, last)
        base = baseline if baseline is not None else draft_today
        b_gmv, b_profit = level(base, "gmv_30d"), level(base, "profit_30d")

        def goal(b: float | None, up: float, n: int = n_cards) -> float | None:
            return None if n == 0 or b is None else b + up

        g_gmv, g_profit = goal(b_gmv, up_gmv), goal(b_profit, up_profit)
        per_day: list[dict[str, Any]] = []
        for k in range(days if daily else 0):
            d_gmv, d_profit, _n = uplift_in_month(
                cards, first + timedelta(days=k), first + timedelta(days=k)
            )
            per_day.append(
                {
                    "day": (first + timedelta(days=k)).isoformat(),
                    "baseline_gmv": None if b_gmv is None else num(b_gmv / days),
                    "baseline_profit": None if b_profit is None else num(b_profit / days),
                    "goal_gmv": None
                    if g_gmv is None or b_gmv is None
                    else num(b_gmv / days + d_gmv),
                    "goal_profit": (
                        None
                        if g_profit is None or b_profit is None
                        else num(b_profit / days + d_profit)
                    ),
                }
            )
        per_card: list[dict[str, Any]] = []
        if product_id is not None:
            for c in cards:
                u_gmv, u_profit, n_one = uplift_in_month([c], first, last)
                if n_one:
                    skus = card_scope.get(id(c))
                    per_card.append(
                        {
                            "card_id": c.get("card_id"),
                            "uplift_gmv": u_gmv,
                            "uplift_profit": u_profit,
                            "sku_ids": None if skus is None else sorted(skus),
                        }
                    )
        answers[sc] = {
            **({"daily": per_day} if daily else {}),
            **(
                {
                    "baseline_window": None
                    if base_window is None
                    else {"from": base_window[0].isoformat(), "to": base_window[1].isoformat()},
                    "card_uplifts": per_card,
                }
                if product_id is not None
                else {}
            ),
            "scope": sc,
            "product_id": product_id,
            "from": first.isoformat(),
            "to": last.isoformat(),
            "days": days,
            "day": elapsed,
            "today_marker": marker,
            "cards": n_cards,
            "baseline_gmv": num(b_gmv),
            "baseline_profit": num(b_profit),
            "uplift_gmv": num(up_gmv),
            "uplift_profit": num(up_profit),
            "goal_gmv": num(g_gmv),
            "goal_profit": num(g_profit),
            "actual_gmv": num(actual_gmv),
            "actual_profit": num(actual_profit),
            "ahead_gmv": ahead(actual_gmv, g_gmv),
            "ahead_profit": ahead(actual_profit, g_profit),
        }
    return answers


async def range_plan(
    session: AsyncSession,
    shop_id: uuid.UUID,
    first: date,
    last: date,
    *,
    scope: str,
    now: datetime,
    actual_to: date | None = None,
    view: PeriodView | None = None,
    product_id: str | None = None,
    daily: bool = False,
) -> dict[str, Any]:
    """The plan figures of ``first``..``last`` for one ``scope`` (see :func:`range_plans`);
    ``product_id`` None = the whole shop."""
    return (
        await range_plans(
            session,
            shop_id,
            first,
            last,
            now=now,
            actual_to=actual_to,
            view=view,
            scopes=(scope,),
            product_id=product_id,
            daily=daily,
        )
    )[scope]


def _idle(r: Mapping[str, Any], key: str, idle_goal: bool) -> Any:
    goal = r[f"goal_{key}"]
    return r[f"baseline_{key}"] if goal is None and idle_goal else goal


async def month_plans(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    anchor: date | None = None,
    mtd_view: PeriodView | None = None,
    draft_payload: Mapping[str, Any] | None = None,
    scopes: tuple[str, ...] = SCOPES,
    idle_goal: bool = False,
) -> dict[str, dict[str, Any]]:
    """The month figures of Kế hoạch for each of ``scopes``, keyed by scope: :func:`range_plans`
    over the calendar month of ``anchor`` (default: the newest data day), month to date up to
    ``anchor``. ``mtd_view`` = a month-to-date view the caller already loaded.

    ``idle_goal``: with no card counted the goal is ``None`` (Tổng quan and the exports show "—").
    Kế hoạch's bars ask for ``idle_goal=True``: the goal is then the baseline level, so the bar
    has something to draw before any plan runs (``cards`` still says nothing runs)."""
    if anchor is None:
        window = await service.resolve(session, shop_id)
        anchor = window.end if window is not None else plans.plan_today(now)
    days_in_month = calendar.monthrange(anchor.year, anchor.month)[1]
    first = anchor.replace(day=1)
    last = first.replace(day=days_in_month)
    rng = await range_plans(
        session,
        shop_id,
        first,
        last,
        now=now,
        actual_to=anchor,
        view=mtd_view,
        draft_payload=draft_payload,
        scopes=scopes,
    )
    return {
        sc: {
            "scope": sc,
            "month": f"{anchor:%Y-%m}",
            "day": anchor.day,
            "days_in_month": days_in_month,
            "cards": r["cards"],
            "baseline_gmv": r["baseline_gmv"],
            "baseline_profit": r["baseline_profit"],
            "uplift_gmv": r["uplift_gmv"],
            "uplift_profit": r["uplift_profit"],
            "goal_gmv": _idle(r, "gmv", idle_goal),
            "goal_profit": _idle(r, "profit", idle_goal),
            "mtd_gmv": r["actual_gmv"],
            "mtd_profit": r["actual_profit"],
        }
        for sc, r in rng.items()
    }


async def month_plan(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    scope: str,
    now: datetime,
    anchor: date | None = None,
    mtd_view: PeriodView | None = None,
) -> dict[str, Any]:
    """The month figures of Kế hoạch for one ``scope`` ("running" | "running+draft")."""
    return (
        await month_plans(
            session, shop_id, now=now, anchor=anchor, mtd_view=mtd_view, scopes=(scope,)
        )
    )[scope]


async def plan_with_month(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime, audience: str
) -> dict[str, Any]:
    """The shop's draft plan payload (``plans.get_plan``) plus ``month``: ``{"running": ...,
    "with_draft": ...}`` -- Kế hoạch's two totals from :func:`month_plans` (``None`` while the
    month's stored daily rows are missing)."""
    out = await plans.get_plan(session, shop_id, None, now=now, audience=audience)
    try:
        both = await month_plans(session, shop_id, now=now, draft_payload=out, idle_goal=True)
        if both[SCOPE_RUNNING]["cards"] == 0:
            # No running card has a day in the data's month (e.g. the executed plan runs in the
            # next one): show the month the running cards fall in, never an empty "Đang chạy".
            span = await running_range(session, shop_id, None, now=now)
            if span is not None:
                window = await service.resolve(session, shop_id)
                data_end = window.end if window is not None else plans.plan_today(now)
                month = span[0] if span[0] > data_end else span[1]
                both = await month_plans(
                    session, shop_id, now=now, draft_payload=out, anchor=month, idle_goal=True
                )
        out["month"] = {"running": both[SCOPE_RUNNING], "with_draft": both[SCOPE_RUNNING_DRAFT]}
    except RowsNotMaterialized:
        out["month"] = None
    return out


__all__ = [
    "SCOPES",
    "SCOPE_RUNNING",
    "SCOPE_RUNNING_DRAFT",
    "month_plan",
    "plan_cards",
    "cards_of_product",
    "month_plans",
    "plan_with_month",
    "range_plan",
    "range_plans",
    "running_range",
    "uplift_in_month",
]
