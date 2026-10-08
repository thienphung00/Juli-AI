"""Event timeline, the report's only daily view — ADR-108 decision 9.

Per channel, four lines — Lượt hiển thị sản phẩm, CTR, CTOR, AOV — as trailing
7-day rolling values: impressions are the 7-day mean, each rate the ratio of
the 7-day sums (never a mean of daily rates). A point exists from the 7th day
of the snapshot. Platform sale days (same-number day and month: 9.9, 10.10,
11.11, 12.12, …) are marked, not dropped (d.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from juli_backend.services.shop_diagnosis.channels import Channel, Counts, Series, daily_values

TIMELINE_CHANNELS: tuple[Channel, ...] = (
    Channel.TOTAL,
    Channel.PRODUCT_CARD,
    Channel.SHOP_TAB,
    Channel.SELLER_VIDEO,
    Channel.SELLER_LIVE,
    Channel.AFFILIATE,
)


@dataclass(frozen=True)
class RollingPoint:
    day: date
    impressions: float
    ctr: float | None
    ctor: float | None
    aov: float | None


@dataclass(frozen=True)
class ChannelTimeline:
    channel: Channel
    points: tuple[RollingPoint, ...]


def is_sale_day(day: date) -> bool:
    """A platform double-day sale: 9.9, 10.10, 11.11, 12.12 (and 1.1 … 8.8)."""
    return day.day == day.month


def sale_days(days: list[date]) -> list[date]:
    return [d for d in days if is_sale_day(d)]


def rolling(days: list[date], per_day: list[Counts], width: int) -> tuple[RollingPoint, ...]:
    """Trailing ``width``-day values; ``per_day`` is aligned with ``days``."""
    out: list[RollingPoint] = []
    for end in range(width - 1, len(days)):
        total = per_day[end - width + 1]
        for counts in per_day[end - width + 2 : end + 1]:
            total = total + counts
        out.append(
            RollingPoint(days[end], total.impressions / width, total.ctr, total.ctor, total.aov)
        )
    return tuple(out)


def build_timelines(
    series: Series,
    days: list[date],
    width: int,
    products: list[str] | None = None,
) -> tuple[ChannelTimeline, ...]:
    """One rolling timeline per channel of :data:`TIMELINE_CHANNELS`."""
    return tuple(
        ChannelTimeline(
            channel, rolling(days, daily_values(series, [channel], days, products), width)
        )
        for channel in TIMELINE_CHANNELS
    )
