"""A changed item against its own history (ADR-118 §3, D81.1-D81.2). Pure: no database.

Day 0 is the verified ``executed_at``. The baseline is the 28 days before it (day 0
itself left out), the post window the 7 days after it; sale days and the contract's extra
days are dropped from both. Verdict on the targeted metric, with the item's last 8 weekly
values before the change as the yardstick:

- ``dat`` -- the post-week value is above the MAX of those weekly values;
- ``khong_dat`` -- at or below their MEDIAN;
- ``chua_ket_luan`` -- in between; or the baseline has fewer than :data:`MIN_BASELINE_CLICKS`
  clicks, fewer than :data:`MIN_WEEKS` weekly values exist, or the exports do not yet cover
  all 7 post days.

The other two metrics (impressions, clicks, CTR) are stored with their values and always
``chua_ket_luan``: only the targeted one decides.

A day is *covered* up to ``covered_through`` (the newest day the shop's item exports reach)
and from the item's ``first_day``; a covered day with no row is a day without traffic (0).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Any

METRICS: tuple[str, ...] = ("impressions", "clicks", "ctr")
BASELINE_DAYS = 28
POST_DAYS = 7
WEEKS = 8
MIN_WEEKS = 4
MIN_BASELINE_CLICKS = 30
#: ``shop_proposal_results.band`` is Numeric(9, 6): the relative gap is clamped to fit.
BAND_LIMIT = 999.0

VERDICT_PASS = "dat"
VERDICT_FAIL = "khong_dat"
VERDICT_OPEN = "chua_ket_luan"

#: (impressions, clicks) of one day.
DayTotals = tuple[float, float]


@dataclass(frozen=True)
class MetricOutcome:
    metric: str
    verdict: str
    value: float | None
    comparison: float | None
    band: float | None
    detail: dict[str, Any]


@dataclass(frozen=True)
class Outcome:
    pre_from: date
    pre_to: date
    post_from: date
    post_to: date
    data_through: date
    metrics: tuple[MetricOutcome, ...]

    def of(self, metric: str) -> MetricOutcome:
        return next(m for m in self.metrics if m.metric == metric)


def _window(
    series: dict[date, DayTotals],
    start: date,
    end: date,
    *,
    first_day: date,
    covered_through: date,
    excluded: frozenset[date],
) -> tuple[float, float, int]:
    """(Σ impressions, Σ clicks, kept days) over the covered, non-excluded days."""
    imp = clk = 0.0
    kept = 0
    for i in range((end - start).days + 1):
        day = start + timedelta(i)
        if day in excluded or day < first_day or day > covered_through:
            continue
        d_imp, d_clk = series.get(day, (0.0, 0.0))
        imp, clk, kept = imp + d_imp, clk + d_clk, kept + 1
    return imp, clk, kept


def _value(metric: str, imp: float, clk: float, kept: int) -> float | None:
    """Daily average for impressions / clicks; Σclicks / Σimpressions for CTR."""
    if kept == 0:
        return None
    if metric == "ctr":
        return clk / imp if imp else None
    return (imp if metric == "impressions" else clk) / kept


def evaluate(
    series: dict[date, DayTotals],
    *,
    day0: date,
    target: str,
    first_day: date,
    covered_through: date,
    excluded: frozenset[date],
) -> Outcome:
    """Values for all three metrics; the verdict decides on ``target`` only."""
    pre_from, pre_to = day0 - timedelta(BASELINE_DAYS), day0 - timedelta(1)
    post_from, post_to = day0 + timedelta(1), day0 + timedelta(POST_DAYS)

    def window(start: date, end: date) -> tuple[float, float, int]:
        return _window(
            series,
            start,
            end,
            first_day=first_day,
            covered_through=covered_through,
            excluded=excluded,
        )

    pre = window(pre_from, pre_to)
    post = window(post_from, post_to)
    weeks = [
        window(day0 - timedelta(7 * w), day0 - timedelta(7 * w) + timedelta(6))
        for w in range(1, WEEKS + 1)
    ]
    out = []
    for metric in METRICS:
        value = _value(metric, post[0], post[1], post[2])
        comparison = _value(metric, pre[0], pre[1], pre[2])
        if metric != target:
            out.append(
                MetricOutcome(metric, VERDICT_OPEN, value, comparison, None, {"target": False})
            )
            continue
        weekly = [v for w in weeks if (v := _value(metric, w[0], w[1], w[2])) is not None]
        out.append(
            _decide(
                metric,
                value,
                comparison,
                weekly,
                baseline_clicks=pre[1],
                covered=covered_through >= post_to,
                kept=(pre[2], post[2]),
                excluded_days=len(excluded),
            )
        )
    return Outcome(
        pre_from=pre_from,
        pre_to=pre_to,
        post_from=post_from,
        post_to=post_to,
        data_through=min(covered_through, post_to),
        metrics=tuple(out),
    )


def _decide(
    metric: str,
    value: float | None,
    comparison: float | None,
    weekly: list[float],
    *,
    baseline_clicks: float,
    covered: bool,
    kept: tuple[int, int],
    excluded_days: int,
) -> MetricOutcome:
    detail: dict[str, Any] = {
        "target": True,
        "weeks": len(weekly),
        "baseline_days_kept": kept[0],
        "post_days_kept": kept[1],
        "excluded_days": excluded_days,
        "baseline_clicks": baseline_clicks,
    }
    top = max(weekly) if weekly else None
    mid = median(weekly) if weekly else None
    if weekly:
        detail |= {"weekly_max": top, "weekly_median": mid, "weekly_min": min(weekly)}
    reason = None
    if not covered:
        reason = "post_window_not_covered"
    elif baseline_clicks < MIN_BASELINE_CLICKS:
        reason = "baseline_clicks_below_minimum"
    elif len(weekly) < MIN_WEEKS:
        reason = "too_few_weekly_values"
    elif value is None:
        reason = "no_post_value"
    band = None
    if value is not None and top:
        band = max(-BAND_LIMIT, min(BAND_LIMIT, value / top - 1))
    verdict = VERDICT_OPEN
    if reason is None and value is not None and top is not None and mid is not None:
        if value > top:
            verdict = VERDICT_PASS
        elif value <= mid:
            verdict = VERDICT_FAIL
    if reason is not None:
        detail["reason"] = reason
    return MetricOutcome(metric, verdict, value, comparison, band, detail)
