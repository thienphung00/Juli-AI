"""The frozen base of a draft plan (P97 D85.4).

A draft plan is evaluated on the base it was created on: ``as_of`` is pinned when the first card
joins (``plans.add_card``) and moves only when the person presses "Cập nhật số"
(``plans.refresh_base``). The base's headline numbers (today's GMV / đơn / AOV / biên and the shop's
chi per day) are stored as versioned rows of ``shopee_plan_base_snapshots``; the highest version is
active. New ingest days after ``as_of`` therefore never move the plan's totals.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_metrics import ShopeePlanBaseSnapshot
from juli_backend.services.shopee_analytics import funnel
from juli_backend.services.shopee_analytics.fmt import num, ratio
from juli_backend.services.shopee_analytics.funnel import FunnelRows
from juli_backend.services.shopee_analytics.shared import shop_profit_of
from juli_backend.services.shopee_recommendations.env import RecoEnv

LABEL = "Số liệu gốc của kế hoạch"


def funnel_json(env: RecoEnv, rows: FunnelRows | None) -> dict[str, Any]:
    """Lượt xem / lượt nhấp / CTR / CTOR of the plan's base (P98 / ADR-122 d.2): the stored funnel
    of the base window, CTOR = ShopMetrics đơn ÷ lượt nhấp; the traffic tables (with a note) only
    while the shop has no source rows yet."""
    m = env.metrics
    if rows is not None and rows.available:
        n = funnel.numbers(funnel.base_from_rows(rows, ""), m.orders)
    else:
        views = None if m.views is None else Decimal(m.views)
        clicks = None if m.clicks is None else Decimal(m.clicks)
        orders = None if m.orders is None else Decimal(m.orders)
        n = funnel.FunnelNumbers(views, clicks, orders, funnel.BASIS_FLOWS, funnel.FALLBACK_NOTE)
    return {
        "views": num(n.views),
        "clicks": num(n.clicks),
        "ctr": ratio(n.ctr),
        "ctor": ratio(n.ctor),
        "ctor_note": funnel.CTOR_NOTE,
        "funnel_basis": n.basis,
        "funnel_note": n.note,
    }


def base_json(env: RecoEnv, rows: FunnelRows | None = None) -> dict[str, Any]:
    """The aggregates the plan math shows as "hôm nay" (D85.2: from ShopMetrics; the funnel from
    the stored source rows, P98)."""
    m = env.metrics
    fig = shop_profit_of(env.view).json()  # P100 B.5: the one shop profit
    return {
        "as_of": env.as_of.isoformat(),
        "window": env.view.window.json(),
        "gmv_30d": float(env.shop_gmv_30d),
        "orders_30d": env.shop_orders_30d,
        "aov": None if m.aov is None else float(m.aov),
        "margin_pct": fig["margin_pct"],
        "profit_30d": fig["profit"],
        "shop_profit": fig,
        "chi_per_day": float(env.shop_chi_per_day()),
        "read_from": m.read_from,
        **funnel_json(env, rows),
    }


async def latest(
    session: AsyncSession, shop_id: uuid.UUID, plan_id: uuid.UUID
) -> ShopeePlanBaseSnapshot | None:
    return await session.scalar(
        select(ShopeePlanBaseSnapshot)
        .where(ShopeePlanBaseSnapshot.shop_id == shop_id, ShopeePlanBaseSnapshot.plan_id == plan_id)
        .order_by(ShopeePlanBaseSnapshot.version.desc())
        .limit(1)
    )


async def write(
    session: AsyncSession,
    shop_id: uuid.UUID,
    plan_id: uuid.UUID,
    env: RecoEnv,
    created_by: dict[str, Any],
    now: datetime,
) -> ShopeePlanBaseSnapshot:
    """The next snapshot version of the plan, on ``env`` (the first one when none exists)."""
    previous = await latest(session, shop_id, plan_id)
    row = ShopeePlanBaseSnapshot(
        id=uuid.uuid4(),
        shop_id=shop_id,
        plan_id=plan_id,
        version=(previous.version + 1) if previous else 1,
        as_of=env.as_of,
        window_start=env.view.window.start,
        window_end=env.view.window.end,
        base=base_json(env, await funnel.load_rows(session, shop_id, env.view.window)),
        created_by=created_by,
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return row


def live_block(env: RecoEnv, today: date) -> dict[str, Any]:
    """P99b (owner 2026-11-10): the plan payload's ``base`` for a draft -- the plan is recomputed
    live on the newest data, so it names that day and never asks for "Cập nhật số"."""
    return {
        "label": LABEL,
        "live": True,
        "version": None,
        "as_of": env.as_of.isoformat(),
        "window": env.view.window.json(),
        "refreshed_at": None,
        "newest_day": env.as_of.isoformat(),
        "newer_available": False,
        "horizon_from": today.isoformat(),
        "note": f"Kế hoạch tính trên số liệu mới nhất (đến hết ngày {env.as_of:%d/%m/%Y}), "
        f"dự kiến cho 30 ngày tới từ hôm nay ({today:%d/%m/%Y}).",
    }


def block(snapshot: ShopeePlanBaseSnapshot | None, newest: date | None) -> dict[str, Any] | None:
    """The plan payload's ``base``: which day the numbers are on and whether newer ones exist."""
    if snapshot is None:
        return None
    newer = newest is not None and newest > snapshot.as_of
    return {
        "label": LABEL,
        "version": snapshot.version,
        "as_of": snapshot.as_of.isoformat(),
        "window": {
            "from": snapshot.window_start.isoformat(),
            "to": snapshot.window_end.isoformat(),
        },
        "refreshed_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "newest_day": None if newest is None else newest.isoformat(),
        "newer_available": newer,
        "note": f"Kế hoạch tính trên số liệu đến hết ngày {snapshot.as_of:%d/%m/%Y}."
        + (
            f" Đã có số mới đến {newest:%d/%m/%Y}: bấm “Cập nhật số” để tính lại."
            if newer and newest
            else ""
        ),
    }
