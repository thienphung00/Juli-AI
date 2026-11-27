"""Owner #85 / #94: the period a screen opens on when the seller chose none.

The default is the newest window of :data:`DEFAULT_DAYS` days whose known-cost share of GMV passes
the profit gate (70-100 %, ``shop_profit.share_passes``), so the screen opens on a period that
shows its profit. From the window ending on the anchor (the newest complete data day) the end
steps back one day at a time, at most :data:`MAX_STEP_BACK_DAYS` days; none passing keeps the
newest window (its profit then shows "—"). A period the seller chose is never moved.

One period per screen: the caller loads the whole view (GMV, đơn, ads, profit) on the window
returned here; nothing mixes windows. The search reads only the stored day rows
(``shop_metrics_daily``: ``gmv`` and ``detail.known_cost_gmv``) -- one query, no order lines.
A day row without ``known_cost_gmv`` (built before ROWS_VERSION 5) makes every window holding it
unknown, so before the rebuild nothing moves.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_metrics import ShopeeShopMetricsDaily
from juli_backend.services.shopee_analytics.stored import ORDER_TYPE
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.shop_profit import share_passes

#: the period kind a request sends (or gets when it sends none) for "the screen's default"
AUTO = "auto"
DEFAULT_DAYS = 30
#: how far the default window's end may step back from the anchor (days)
MAX_STEP_BACK_DAYS = 30
#: the stored-row detail key (``materialize.KNOWN_COST_GMV_KEY``)
KNOWN_COST_GMV_KEY = "known_cost_gmv"

#: a stored day: (GMV, known-cost GMV); GMV ``None`` = no order data that day (not in any sum),
#: known ``None`` = the row predates the key
DayShare = tuple[Decimal | None, Decimal | None]


@dataclass(frozen=True)
class DefaultPick:
    window: Window
    newest: Window
    passed: bool

    @property
    def moved_days(self) -> int:
        return (self.newest.end - self.window.end).days

    def json(self) -> dict[str, Any]:
        """What the screen shows: the dates of the period it opened on (``from`` / ``to``)."""
        return {
            **self.window.json(),
            "moved_days": self.moved_days,
            "max_back_days": MAX_STEP_BACK_DAYS,
            "profit_shown": self.passed,
        }


def pick_window(
    anchor: date,
    days: Mapping[date, DayShare],
    *,
    length: int = DEFAULT_DAYS,
    max_back: int = MAX_STEP_BACK_DAYS,
) -> DefaultPick:
    """Pure: the newest ``length``-day window ending at most ``max_back`` days before ``anchor``
    whose stored known-cost share passes the gate; else the newest window."""
    newest = Window(anchor - timedelta(days=length - 1), anchor)
    for back in range(max_back + 1):
        end = anchor - timedelta(days=back)
        win = Window(end - timedelta(days=length - 1), end)
        gmv = known = Decimal(0)
        complete = True
        for i in range(length):
            g, k = days.get(win.start + timedelta(days=i), (None, None))
            if g is None:
                continue  # no order data that day: in neither sum (``stored.load_stored``)
            if k is None:
                complete = False
                break
            gmv += g
            known += k
        if complete and share_passes(known, gmv):
            return DefaultPick(win, newest, True)
    return DefaultPick(newest, newest, False)


async def load_day_shares(
    session: AsyncSession, shop_id: uuid.UUID, start: date, end: date
) -> dict[date, DayShare]:
    """The stored days of ``start..end``: (GMV, known-cost GMV). One query."""
    rows = await session.execute(
        select(
            ShopeeShopMetricsDaily.day,
            ShopeeShopMetricsDaily.gmv,
            ShopeeShopMetricsDaily.orders,
            ShopeeShopMetricsDaily.detail,
        ).where(
            ShopeeShopMetricsDaily.shop_id == shop_id,
            ShopeeShopMetricsDaily.order_type == ORDER_TYPE,
            ShopeeShopMetricsDaily.day >= start,
            ShopeeShopMetricsDaily.day <= end,
        )
    )
    out: dict[date, DayShare] = {}
    for day, gmv, orders, detail in rows.all():
        if orders is None:
            continue  # P100-A: a day without order data is in no window sum
        raw = (detail or {}).get(KNOWN_COST_GMV_KEY)
        out[day] = (gmv or Decimal(0), None if raw is None else Decimal(str(raw)))
    return out


async def default_window(
    session: AsyncSession,
    shop_id: uuid.UUID,
    anchor: date,
    *,
    length: int = DEFAULT_DAYS,
) -> DefaultPick:
    """THE default period of every profit screen (Tổng quan, Phân tích, Sản phẩm, the export)."""
    first = anchor - timedelta(days=length - 1 + MAX_STEP_BACK_DAYS)
    days = await load_day_shares(session, shop_id, first, anchor)
    return pick_window(anchor, days, length=length)
