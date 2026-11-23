"""Comparison windows (J5): date arithmetic lives here, never in a model."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from juli_backend.services.shopee_kpi.flow_glm import calendar_row

WEEKDAYS = ["thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật"]


@dataclass
class Windows:
    preset: str
    cur: tuple[date, date]
    prev: tuple[date, date] | None
    context: tuple[date, date] | None = None
    same_weekday: list[date] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def label(self) -> str:
        def f(w: tuple[date, date]) -> str:
            return f"{w[0]:%d/%m}–{w[1]:%d/%m}" if w[0] != w[1] else f"{w[0]:%d/%m}"

        if self.same_weekday:
            wd = WEEKDAYS[self.cur[0].weekday()]
            return f"{f(self.cur)} so với trung bình {len(self.same_weekday)} {wd} trước"
        return f"{f(self.cur)} so với {f(self.prev)}" if self.prev else f(self.cur)


def _prev_month(d: date) -> tuple[date, date]:
    end = d.replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def _clamp_day(y: int, m: int, day: int) -> date:
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return date(y, m, min(day, (nxt - timedelta(days=1)).day))


def is_sale_day(d: date) -> bool:
    """Sale days: double days (11/11, 12/12 ...), the 15th and the 25th: the one calendar of
    `shopee_kpi.flow_glm.calendar_row`."""
    cal = calendar_row(d)
    return bool(cal["double_day"] or cal["day15"] or cal["day25"])


def campaign_days(a: date, b: date) -> list[date]:
    """Sale days in [a, b] (double days, 15th, 25th)."""
    out, d = [], a
    while d <= b:
        if is_sale_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


# One phrase -> one window (J2): the model never decides what "last week" means.
_PHRASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"tuần\s+(trước|vừa rồi|qua)|last\s+(full\s+)?week|previous\s+week", re.I),
        "last_full_week_vs_week_before",
    ),
    (re.compile(r"tuần\s+này|this\s+week", re.I), "this_week_vs_same_days_last_week"),
    (
        re.compile(r"7\s*ngày\s*(qua|gần nhất|vừa rồi)|(last|past)\s+7\s+days", re.I),
        "last_7d_vs_prev_7d",
    ),
)


def window_from_phrase(phrase: str | None) -> str | None:
    """The preset a time phrase names, or None when it names none."""
    for rx, preset in _PHRASES:
        if phrase and rx.search(phrase):
            return preset
    return None


def build_windows(
    preset: str,
    anchor: date,
    *,
    explicit: tuple[date, date] | None = None,
    named_month: str | None = None,
) -> Windows:
    a_ = anchor
    if explicit:
        a, b = explicit
        n = (b - a).days + 1
        w = Windows("custom", (a, b), (a - timedelta(days=n), a - timedelta(days=1)))
    elif preset == "yesterday_vs_same_weekday":
        w = Windows(
            preset, (a_, a_), None, same_weekday=[a_ - timedelta(days=7 * k) for k in range(1, 5)]
        )
    elif preset == "last_7d_vs_prev_7d":
        w = Windows(
            preset, (a_ - timedelta(days=6), a_), (a_ - timedelta(days=13), a_ - timedelta(days=7))
        )
    elif preset == "this_week_vs_same_days_last_week":
        mon = a_ - timedelta(days=a_.weekday())  # a_ = the newest complete day
        last_mon = mon - timedelta(days=7)
        w = Windows(preset, (mon, a_), (last_mon, last_mon + (a_ - mon)))
    elif preset == "last_full_week_vs_week_before":
        end = a_ - timedelta(days=(a_.weekday() + 1) % 7) if a_.weekday() != 6 else a_
        w = Windows(
            preset,
            (end - timedelta(days=6), end),
            (end - timedelta(days=13), end - timedelta(days=7)),
        )
    elif preset == "last_30d_vs_prev_30d":
        w = Windows(
            preset,
            (a_ - timedelta(days=29), a_),
            (a_ - timedelta(days=59), a_ - timedelta(days=30)),
        )
    elif preset == "mtd_vs_same_days_last_month":
        pa, pb = _prev_month(a_)
        w = Windows(
            preset,
            (a_.replace(day=1), a_),
            (pa, _clamp_day(pa.year, pa.month, a_.day)),
            context=(pa, pb),
        )
    elif preset == "last_month_vs_month_before":
        lm = _prev_month(a_)
        w = Windows(preset, lm, _prev_month(lm[0]))
    elif preset == "named_month_vs_previous" and named_month:
        y, m = map(int, named_month.split("-"))
        first = date(y, m, 1)
        w = Windows(preset, (first, min(_clamp_day(y, m, 31), a_)), _prev_month(first))
    else:
        w = build_windows("last_30d_vs_prev_30d", a_)
        w.flags.append("window_defaulted")
    lo = w.prev[0] if w.prev else (w.same_weekday[-1] if w.same_weekday else w.cur[0])
    days = campaign_days(lo, w.cur[1])
    if days:
        w.flags.append("contains_campaign_day:" + ",".join(f"{d:%d/%m}" for d in days))
    return w
