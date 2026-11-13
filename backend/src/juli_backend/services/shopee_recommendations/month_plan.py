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
"""

from __future__ import annotations

import calendar
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import date, datetime
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


def _cards_of(out: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The cards' evaluation blocks of a plan payload: its own aggregate plus each group's."""
    cards = list((out.get("aggregate") or {}).get("cards") or [])
    for g in out.get("groups") or []:
        cards += list((g.get("aggregate") or {}).get("cards") or [])
    return cards


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


async def _mtd(
    session: AsyncSession, shop_id: uuid.UUID, anchor: date, view: PeriodView | None
) -> tuple[Any, Any]:
    if view is None:
        ctx = await loaders.load_context(session, shop_id)
        ctx = replace(ctx, rules=ctx.rules.for_month(f"{anchor:%Y-%m}"))
        view = await service.load_view(
            session, shop_id, ctx, Window(anchor.replace(day=1), anchor), funnel=True
        )
    return view.shop_gmv, shop_profit_of(view).profit


async def month_plans(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    anchor: date | None = None,
    mtd_view: PeriodView | None = None,
    draft_payload: Mapping[str, Any] | None = None,
    scopes: tuple[str, ...] = SCOPES,
) -> dict[str, dict[str, Any]]:
    """The month figures of Kế hoạch for each of ``scopes``, keyed by scope; the single place the
    numbers are computed (see the module docstring). ``anchor`` = the day the month is read on
    (default: the newest data day); ``mtd_view`` = a month-to-date view the caller already loaded
    (same window); ``draft_payload`` = the draft's ``plans.get_plan`` answer, when the caller
    has it."""
    for sc in scopes:
        if sc not in SCOPES:
            raise ValueError(f"unknown scope {sc!r}")
    if anchor is None:
        window = await service.resolve(session, shop_id)
        anchor = window.end if window is not None else plans.plan_today(now)
    first = anchor.replace(day=1)
    days_in_month = calendar.monthrange(anchor.year, anchor.month)[1]
    last = first.replace(day=days_in_month)

    running_cards: list[Mapping[str, Any]] = []
    baseline: Mapping[str, Any] | None = None
    for plan in await _executed(session, shop_id):
        out = await plans.get_plan(session, shop_id, plan.id, now=now, audience="seller")
        running_cards += _cards_of(out)
        if baseline is None:
            baseline = (out.get("aggregate") or {}).get("today")
    draft_cards: list[Mapping[str, Any]] = []
    draft_today: Mapping[str, Any] | None = None
    if SCOPE_RUNNING_DRAFT in scopes:
        dout = draft_payload
        if dout is None:
            dout = await plans.get_plan(session, shop_id, None, now=now, audience="seller")
        draft_cards = _cards_of(dout)
        draft_today = (dout.get("aggregate") or {}).get("today")
    mtd_gmv, mtd_profit = await _mtd(session, shop_id, anchor, mtd_view)

    def level(base: Mapping[str, Any] | None, key: str) -> float | None:
        v = None if base is None else base.get(key)
        return None if v is None else float(v) / HORIZON_DAYS * days_in_month

    answers: dict[str, dict[str, Any]] = {}
    for sc in scopes:
        cards = running_cards + (draft_cards if sc == SCOPE_RUNNING_DRAFT else [])
        up_gmv, up_profit, n_cards = uplift_in_month(cards, first, last)
        base = baseline if baseline is not None else draft_today
        b_gmv, b_profit = level(base, "gmv_30d"), level(base, "profit_30d")

        def goal(b: float | None, up: float, n: int = n_cards) -> float | None:
            return None if n == 0 or b is None else b + up

        answers[sc] = {
            "scope": sc,
            "month": f"{anchor:%Y-%m}",
            "day": anchor.day,
            "days_in_month": days_in_month,
            "cards": n_cards,
            "baseline_gmv": num(b_gmv),
            "baseline_profit": num(b_profit),
            "uplift_gmv": num(up_gmv),
            "uplift_profit": num(up_profit),
            "goal_gmv": num(goal(b_gmv, up_gmv)),
            "goal_profit": num(goal(b_profit, up_profit)),
            "mtd_gmv": num(mtd_gmv),
            "mtd_profit": num(mtd_profit),
        }
    return answers


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
        both = await month_plans(session, shop_id, now=now, draft_payload=out)
        out["month"] = {"running": both[SCOPE_RUNNING], "with_draft": both[SCOPE_RUNNING_DRAFT]}
    except RowsNotMaterialized:
        out["month"] = None
    return out


__all__ = [
    "SCOPES",
    "SCOPE_RUNNING",
    "SCOPE_RUNNING_DRAFT",
    "month_plan",
    "month_plans",
    "plan_with_month",
    "uplift_in_month",
]
