"""A7 (owner #66): the affiliate source check. Logs and reports, never corrects.

The registry's TTLK source is the order-line affiliate flag (the conversion report marks the
lines; ``components.affiliate_gmv``). Two other Shopee reports count affiliate orders too, on
their own attribution, and are never added to it:

- the traffic report's Tiếp thị liên kết (``traffic_overview`` stream ``affiliate``, confirmed,
  shop level), per day: its ``all`` row, else its parts (``aff_live`` + ``aff_video``), never
  both (``components.one_segment_basis``);
- the affiliate partner report (``affiliate_partner_period``), per period, Σ over the KOLs.

The flag must see at least what each report sees: per day, line đơn ≥ the traffic report's TTLK
đơn; per partner period, line đơn over its days ≥ the report's đơn. :func:`reconcile` lists every
day / period where it does not (the owner verifies the source on these before confirming it).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.platform_data import PlatformPeriodMetric
from juli_backend.repositories import PlatformDailyMetricsRepo
from juli_backend.services.metrics.components import one_segment_basis
from juli_backend.services.shopee_analytics import loaders, service
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.order_profit import counts_in_sales

TRAFFIC_STREAM = "affiliate"
PARTNER_DATASET = "affiliate_partner_period"


@dataclass(frozen=True)
class DayShortfall:
    day: date
    lines: int
    report: int


@dataclass(frozen=True)
class PeriodShortfall:
    start: date
    end: date
    lines: int
    report: int


@dataclass(frozen=True)
class Reconcile:
    traffic_days: list[DayShortfall] = field(default_factory=list)
    partner_periods: list[PeriodShortfall] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.traffic_days and not self.partner_periods


def compare(
    *,
    lines: Mapping[date, int],
    traffic: Mapping[date, int],
    partner: Sequence[tuple[date, date, int]],
) -> Reconcile:
    """Pure: the days / periods where a report counts more affiliate đơn than the lines."""
    days = [
        DayShortfall(d, lines.get(d, 0), n)
        for d, n in sorted(traffic.items())
        if n > lines.get(d, 0)
    ]
    periods: list[PeriodShortfall] = []
    for start, end, n in sorted(partner):
        span = (end - start).days + 1
        seen = sum(lines.get(start + timedelta(days=i), 0) for i in range(span))
        if n > seen:
            periods.append(PeriodShortfall(start, end, seen, n))
    return Reconcile(days, periods)


async def reconcile(session: AsyncSession, shop_id: uuid.UUID, start: date, end: date) -> Reconcile:
    """Read the three sources over ``start``..``end`` and :func:`compare` them."""
    ctx = await loaders.load_context(session, shop_id)
    view = await service.load_view(session, shop_id, ctx, Window(start, end))
    orders: dict[date, set[str]] = defaultdict(set)
    for ln, _ in view.pairs:
        if ln.affiliate and counts_in_sales(ln):
            orders[ln.order_date].add(ln.order_id)
    lines = {d: len(o) for d, o in orders.items()}
    rows = await PlatformDailyMetricsRepo(session).window(
        shop_id,
        datasets=[loaders.TRAFFIC_DAILY],
        start=start,
        end=end,
        streams=[TRAFFIC_STREAM],
        order_types=[loaders.CONFIRMED],
    )
    by_day: dict[date, list[Any]] = defaultdict(list)
    for r in rows:
        if not r.item_id:
            by_day[r.day].append(r)
    traffic: dict[date, int] = {
        d: sum(int(r.orders or 0) for r in one_segment_basis(day_rows, lambda r: r.segment))
        for d, day_rows in by_day.items()
    }
    found = await session.execute(
        select(PlatformPeriodMetric).where(
            PlatformPeriodMetric.shop_id == shop_id,
            PlatformPeriodMetric.dataset == PARTNER_DATASET,
            PlatformPeriodMetric.period_start >= start,
            PlatformPeriodMetric.period_end <= end,
        )
    )
    partner: dict[tuple[date, date], int] = defaultdict(int)
    for p in found.scalars():
        partner[(p.period_start, p.period_end)] += int(p.orders or 0)
    return compare(
        lines=lines, traffic=traffic, partner=[(a, b, n) for (a, b), n in partner.items()]
    )


__all__ = ["DayShortfall", "PeriodShortfall", "Reconcile", "compare", "reconcile"]
