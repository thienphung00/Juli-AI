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
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_metrics import ShopeePlanBaseSnapshot
from juli_backend.services.shopee_recommendations.env import RecoEnv

LABEL = "Số liệu gốc của kế hoạch"


def base_json(env: RecoEnv) -> dict[str, Any]:
    """The aggregates the plan math shows as "hôm nay" (D85.2: from ShopMetrics)."""
    m = env.metrics
    return {
        "as_of": env.as_of.isoformat(),
        "window": env.view.window.json(),
        "gmv_30d": float(env.shop_gmv_30d),
        "orders_30d": env.shop_orders_30d,
        "aov": None if m.aov is None else float(m.aov),
        "margin_pct": None if m.margin_pct is None else float(m.margin_pct),
        "chi_per_day": float(env.shop_chi_per_day()),
        "read_from": m.read_from,
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
        base=base_json(env),
        created_by=created_by,
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return row


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
