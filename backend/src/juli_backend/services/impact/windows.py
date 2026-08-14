"""Date-window arithmetic for the ratio-form DiD compute — ADR-077 decision 2
(#1041).

Pure ``date`` arithmetic only: no wall-clock reads (``date.today()`` /
``datetime.now()`` never appear in this module), no I/O. Every window is
derived from one caller-supplied ``t`` (the write's execution date, from
``ToolExecution`` — see the package docstring in ``__init__.py``), so the same
``t`` always produces the same windows, in any process, at any time.

**Day T is excluded everywhere** (ADR-077 decision 2): the pre window ends at
``T-1`` and the post window starts at ``T+1`` by construction, so ``t`` never
falls inside ``[pre_start, pre_end]`` or ``[post_start, post_end]``. This
module additionally exposes ``exclude`` on :func:`mean_over_window` as a
second, independent guard — the mean explicitly drops ``exclude`` even if a
caller-supplied window boundary were ever wrong — because the exclusion rule
is a correctness-critical, easy-to-regress invariant, not something to trust
to window construction alone.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

#: "preliminary" reads at T+7 (so the seller isn't staring at "pending" for
#: two weeks); "final" reads at T+14. Same names as ``impact_readings.kind``.
WindowKind = Literal["preliminary", "final"]

PRE_WINDOW_DAYS = 14
POST_WINDOW_DAYS: dict[WindowKind, int] = {"preliminary": 7, "final": 14}


def pre_window(t: date) -> tuple[date, date]:
    """``(T-14, T-1)`` inclusive — same window regardless of preliminary vs
    final, since only the post window's length changes."""
    return t - timedelta(days=PRE_WINDOW_DAYS), t - timedelta(days=1)


def post_window(t: date, kind: WindowKind) -> tuple[date, date]:
    """``(T+1, T+7)`` for ``"preliminary"``, ``(T+1, T+14)`` for ``"final"``."""
    days = POST_WINDOW_DAYS[kind]
    return t + timedelta(days=1), t + timedelta(days=days)


def date_range(start: date, end: date) -> tuple[date, ...]:
    """Inclusive ``[start, end]`` as a tuple of dates. Empty if ``end < start``."""
    if end < start:
        return ()
    span = (end - start).days
    return tuple(start + timedelta(days=i) for i in range(span + 1))


@dataclass(frozen=True, slots=True)
class Windows:
    """The four window boundaries for one ``(t, kind)`` pair, precomputed
    once so callers (and tests) don't recompute ``pre_window``/``post_window``
    separately and risk the two drifting apart."""

    pre_start: date
    pre_end: date
    post_start: date
    post_end: date


def compute_windows(t: date, kind: WindowKind) -> Windows:
    pre_start, pre_end = pre_window(t)
    post_start, post_end = post_window(t, kind)
    return Windows(pre_start=pre_start, pre_end=pre_end, post_start=post_start, post_end=post_end)


def mean_over_window(
    daily: Mapping[date, Decimal | None],
    start: date,
    end: date,
    exclude: date | None = None,
) -> Decimal | None:
    """Arithmetic mean of ``daily``'s values over the inclusive ``[start, end]``
    range.

    - ``exclude`` (typically ``t``) is always dropped, even if it falls
      inside ``[start, end]`` — belt-and-suspenders against day T leaking
      into a mean (ADR-077 decision 2).
    - Missing dates and ``None`` values are skipped, not treated as zero —
      an unrecorded day carries no information, it is not a zero day.
    - Returns ``None`` (not zero, not a ``ZeroDivisionError``) when no data
      point survives — "insufficient data" is a designed state the caller
      (``compute.py``) turns into a suppression reason, never an exception.
    - This function draws no distinction between a rate metric's series
      (e.g. CTR, fractional values) and a count metric's series (e.g.
      impressions, integer-valued) — both average the same way, by plain
      arithmetic mean. The rate/count distinction only matters to *threshold*
      comparisons (e.g. a downstream volume floor), which this module never
      performs; see ``metric_map.MetricSpec.is_rate`` for that seam.
    """
    values: list[Decimal] = []
    for day in date_range(start, end):
        if exclude is not None and day == exclude:
            continue
        value = daily.get(day)
        if value is None:
            continue
        values.append(value)
    if not values:
        return None
    return sum(values, start=Decimal(0)) / Decimal(len(values))
