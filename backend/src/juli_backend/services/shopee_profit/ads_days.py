"""P100 A.5: ONE ad spend per day, for every screen.

Three sources describe a shop's ad spend; each day takes the first one that has it:

1. ``connector`` -- the Connector's ``ads_campaign_daily`` (finished days, one row per campaign);
2. ``daily_report`` -- the daily CSV report (``traffic_overview`` ads stream, one row per ad type);
3. ``period_spread`` -- the CSV period reports (``ads_campaign_period``): the period's spend
   spread evenly over its days, the newer report answering a day two reports share. This is
   the same pro-rata share :func:`ads_sources.resolve_ad_spend` uses (days in the range ÷ days in
   the window), taken one day at a time so a day is answered once.

A day with none of them has no figure (``None``, "chưa có dữ liệu"): it is never 0, and never in
a total. A day that two sources cover is counted once (the first source). The ``source`` of
each day travels with the figure, so a payload can say where each day came from.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from juli_backend.services.shopee_profit.ads_sources import AdWindow, campaign_key
from juli_backend.services.shopee_profit.money import ZERO

SOURCE_CONNECTOR = "connector"
SOURCE_DAILY_REPORT = "daily_report"
SOURCE_PERIOD_SPREAD = "period_spread"


@dataclass(frozen=True)
class TypeFigure:
    """One ad type's figures of a day (placed orders)."""

    spend: Decimal | None = None
    gmv: Decimal = ZERO
    orders: Decimal = ZERO


@dataclass(frozen=True)
class DayAds:
    """One day's ad figures and the source they came from."""

    spend: Decimal
    gmv: Decimal
    orders: Decimal
    source: str
    by_type: Mapping[str, TypeFigure] = field(default_factory=dict)


def resolve_ad_days(
    connector: Mapping[date, DayAds],
    daily_report: Mapping[date, DayAds],
    windows: Iterable[AdWindow],
    start: date,
    end: date,
) -> dict[date, DayAds]:
    """The figure of every day of ``start..end`` that has one (see the module docstring)."""
    out: dict[date, DayAds] = {}
    by_campaign: dict[str, dict[tuple[date, date], list[AdWindow]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for w in windows:
        by_campaign[campaign_key(w.campaign)][(w.start, w.end)].append(w)
    day = start
    while day <= end:
        if day in connector:
            out[day] = connector[day]
        elif day in daily_report:
            out[day] = daily_report[day]
        else:
            spread = _period_day(by_campaign, day)
            if spread is not None:
                out[day] = spread
        day += timedelta(days=1)
    return out


def _period_day(
    by_campaign: Mapping[str, Mapping[tuple[date, date], list[AdWindow]]], day: date
) -> DayAds | None:
    spend = gmv = orders = ZERO
    found = False
    for by_window in by_campaign.values():
        # the newest report answers the day, an older overlapping one never adds to it
        for (w_start, w_end), rows in sorted(by_window.items(), reverse=True):
            if not w_start <= day <= w_end:
                continue
            span = Decimal((w_end - w_start).days + 1)
            for row in rows:
                spend += row.spend / span
                gmv += (row.gmv or ZERO) / span
                orders += (row.orders or ZERO) / span
            found = True
            break
    if not found:
        return None
    return DayAds(spend, gmv, orders, SOURCE_PERIOD_SPREAD, {})


def source_counts(days: Mapping[date, DayAds]) -> dict[str, int]:
    """How many days each source answered (for the ``sources`` / coverage fields)."""
    out: dict[str, int] = defaultdict(int)
    for figure in days.values():
        out[figure.source] += 1
    return dict(out)
