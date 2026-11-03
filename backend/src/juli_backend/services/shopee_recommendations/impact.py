"""The Shopee impact reader: ADR-077's ratio-form difference-in-differences on daily series.

    pre      = mean(metric, T-14 ... T-1)       post = mean(metric, T+1 ... T+14|28)
    growth   = mean(controls, post) / mean(controls, pre)
    expected = pre x growth
    incremental = post - expected       impact = incremental / expected

T is the verified time of the change (day T excluded; days in ``excluded`` -- sale days, other
executed changes -- are dropped everywhere). Controls: the K = 5 most pre-correlated untouched
series (at least 3, mean correlation >= 0.2), equal-weighted; otherwise plain pre/post, capped
at the lowest confidence tier. ``se_rel`` is the relative standard error from the pre-period
noise of the treated-vs-expected gap. Pure; the caller supplies the series.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, pstdev

PRE_DAYS = 14
K_CONTROLS = 5
MIN_CONTROLS = 3
MIN_CORRELATION = 0.2
TIERS = ("cao", "trung_binh", "thap", "suppressed")

Series = Mapping[date, float]


@dataclass(frozen=True)
class Reading:
    confidence: str  # cao | trung_binh | thap | suppressed
    reason: str | None
    pre: float | None = None
    post: float | None = None
    expected: float | None = None
    incremental: float | None = None
    impact_pct: float | None = None  # relative effect (0.08 = +8 %)
    se_rel: float | None = None
    fallback: bool = False
    controls: tuple[str, ...] = ()
    correlations: tuple[float, ...] = ()
    pre_days_used: int = 0
    post_days_used: int = 0


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _vals(series: Series, days: Sequence[date], excluded: frozenset[date]) -> list[float]:
    return [series.get(d, 0.0) for d in days if d not in excluded]


def _corr(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) < 3 or len(a) != len(b):
        return 0.0
    ma, mb = mean(a), mean(b)
    da = [x - ma for x in a]
    db = [y - mb for y in b]
    na, nb = math.sqrt(sum(x * x for x in da)), math.sqrt(sum(y * y for y in db))
    return (
        0.0 if na == 0 or nb == 0 else sum(x * y for x, y in zip(da, db, strict=True)) / (na * nb)
    )


def read_effect(
    treated: Series,
    controls: Mapping[str, Series],
    t: date,
    *,
    post_days: int = 14,
    excluded: frozenset[date] = frozenset(),
    volume_floor_per_day: float = 0.0,
) -> Reading:
    """The control-adjusted relative effect of a change made on day ``t``."""
    pre_range = [d for d in _days(t - timedelta(days=PRE_DAYS), t - timedelta(days=1))]
    post_range = [d for d in _days(t + timedelta(days=1), t + timedelta(days=post_days))]
    pre_used = [d for d in pre_range if d not in excluded]
    post_used = [d for d in post_range if d not in excluded]
    if len(pre_used) < 7 or len(post_used) < max(post_days // 2, 3):
        return Reading(
            "suppressed", "too_few_days", pre_days_used=len(pre_used), post_days_used=len(post_used)
        )
    pre = mean(_vals(treated, pre_used, frozenset()))
    post = mean(_vals(treated, post_used, frozenset()))
    if pre <= 0 or pre < volume_floor_per_day:
        return Reading(
            "suppressed",
            "pre_below_floor",
            pre=pre,
            post=post,
            pre_days_used=len(pre_used),
            post_days_used=len(post_used),
        )
    treated_pre = _vals(treated, pre_used, frozenset())
    scored: list[tuple[float, str]] = []
    for cid, s in controls.items():
        cp = _vals(s, pre_used, frozenset())
        if mean(cp) <= 0:
            continue
        scored.append((_corr(treated_pre, cp), cid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    picked = scored[:K_CONTROLS]
    fallback = len(picked) < MIN_CONTROLS or (
        picked and mean(c for c, _ in picked) < MIN_CORRELATION
    )
    if fallback:
        growth = 1.0
        ids: tuple[str, ...] = ()
        corrs: tuple[float, ...] = ()
        ctrl_pre_series: list[float] = []
    else:
        ids = tuple(cid for _, cid in picked)
        corrs = tuple(round(c, 3) for c, _ in picked)
        ctrl_pre = [mean(_vals(controls[c], pre_used, frozenset())) for c in ids]
        ctrl_post = [mean(_vals(controls[c], post_used, frozenset())) for c in ids]
        growth = mean(ctrl_post) / mean(ctrl_pre)
        # equal-weighted control series, scaled to the treated level, for the noise band
        ctrl_pre_series = [
            mean(
                controls[c].get(d, 0.0) / mean(_vals(controls[c], pre_used, frozenset()))
                for c in ids
            )
            for d in pre_used
        ]
    expected = pre * growth
    if expected <= 0:
        return Reading(
            "suppressed",
            "expected_non_positive",
            pre=pre,
            post=post,
            pre_days_used=len(pre_used),
            post_days_used=len(post_used),
        )
    incremental = post - expected
    if ctrl_pre_series:
        gap = [x - pre * c for x, c in zip(treated_pre, ctrl_pre_series, strict=True)]
    else:
        gap = [x - pre for x in treated_pre]
    noise = pstdev(gap) if len(gap) > 1 else 0.0
    se_abs = noise / math.sqrt(len(post_used))
    se_rel = se_abs / expected
    impact = incremental / expected
    floor = max(volume_floor_per_day, 1e-9)
    if fallback:
        tier = "thap"
    elif pre >= 3 * floor and abs(incremental) > 2 * noise:
        tier = "cao"
    elif pre >= floor and abs(incremental) > noise:
        tier = "trung_binh"
    else:
        tier = "thap"
    return Reading(
        tier,
        "no_controls" if fallback else None,
        pre,
        post,
        expected,
        incremental,
        impact,
        se_rel,
        bool(fallback),
        ids,
        corrs,
        len(pre_used),
        len(post_used),
    )
