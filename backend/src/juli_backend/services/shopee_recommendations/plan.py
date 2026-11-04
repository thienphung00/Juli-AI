"""The pre-registered measurement plan (ADR-107 decision 7), computed when a card is proposed.

From the scope's last-30-day volume and its own variability the minimum detectable relative
effect (MDE) at alpha = 5 %, power = 80 % is computed for 14 and then 28 days of post data
against a 28-day baseline: MDE <= 30 % at 14 days -> 14-day plan; else <= 30 % at 28 days ->
28-day plan; else "khó kết luận" (the card may still be proposed; its own result will be hard
to conclude). The numbers (30 %, 5 %, 80 %) are config. Pure.

P91 D-8: ``mde_for`` already takes any number of post days; ``window_options`` /
``recommended_window`` answer "what can N days detect" for the presets 7 / 14 / 28 and a custom
3-90, and which preset to pre-select for a scope.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from statistics import mean, pstdev
from typing import TYPE_CHECKING, Any

from juli_backend.services.shopee_profit.money import ZERO
from juli_backend.services.shopee_recommendations import config

if TYPE_CHECKING:
    from juli_backend.services.shopee_recommendations.env import RecoEnv

RATE_METRICS = ("ctr", "ctor")
Z = config.Z_ALPHA_2 + config.Z_POWER


@dataclass(frozen=True)
class MetricStats:
    """Per-day volume and variability of the scope's target metric (history window)."""

    rate: float | None = None  # ctr / ctor level
    trials_per_day: float = 0.0  # views (ctr) or clicks (ctor)
    count_per_day: float = 0.0  # orders (or views) per day
    orders_per_day: float = 0.0
    cv: float | None = None  # coefficient of variation of order value
    phi: float = 1.0  # daily-count overdispersion (>= 1)


def mde_for(
    metric: str, stats: MetricStats, post_days: int, pre_days: int = config.PLAN_PRE_DAYS
) -> float | None:
    """Relative MDE of a pre/post comparison; None when the metric has no usable volume."""
    if metric == "none":
        return None
    if metric in RATE_METRICS:
        p = stats.rate
        if not p or p <= 0 or p >= 1 or stats.trials_per_day <= 0:
            return None
        n_post, n_pre = stats.trials_per_day * post_days, stats.trials_per_day * pre_days
        return Z * math.sqrt((1 - p) / (p * n_post) + (1 - p) / (p * n_pre))
    if metric == "aov":
        if stats.cv is None or stats.orders_per_day <= 0:
            return None
        n_post, n_pre = stats.orders_per_day * post_days, stats.orders_per_day * pre_days
        return Z * stats.cv * math.sqrt(1 / n_post + 1 / n_pre)
    if stats.count_per_day <= 0:
        return None
    lam_post, lam_pre = stats.count_per_day * post_days, stats.count_per_day * pre_days
    return Z * math.sqrt(stats.phi * (1 / lam_post + 1 / lam_pre))


def _sample(metric: str, stats: MetricStats, days: int) -> float:
    if metric in RATE_METRICS:
        return stats.trials_per_day * days
    if metric == "aov":
        return stats.orders_per_day * days
    return stats.count_per_day * days


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def measurement_plan(metric: str, stats: MetricStats) -> dict[str, Any]:
    mde_max = config.MDE_MAX
    mdes = {d: mde_for(metric, stats, d) for d in config.PLAN_DAYS}
    planned: int | None = None
    for d in config.PLAN_DAYS:
        m = mdes[d]
        if m is not None and m <= mde_max:
            planned = d
            break
    required = None
    if planned is None:
        for d in range(1, 365):
            m = mde_for(metric, stats, d)
            if m is not None and m <= mde_max:
                required = _sample(metric, stats, d)
                break
    else:
        required = _sample(metric, stats, planned)
    use = planned or config.PLAN_DAYS[-1]
    return {
        "metric": metric,
        "planned_days": planned,
        "label": f"Kết quả sau {planned} ngày" if planned else "khó kết luận",
        "mde_14": _r(mdes[14]),
        "mde_28": _r(mdes[28]),
        "mde_at_plan": _r(mdes[use]),
        "mde_max": mde_max,
        "alpha": config.MDE_ALPHA,
        "power": config.MDE_POWER,
        "expected_sample": round(_sample(metric, stats, use), 1),
        "required_sample": None if required is None else round(required, 1),
        "baseline_days": config.PLAN_PRE_DAYS,
        "pooled_only": planned is None,
        "clock_starts": "verified",
    }


# -- the measurement window the user chooses (P91 D-8) -----------------------------------------


def window_option(metric: str, stats: MetricStats, days: int) -> dict[str, Any]:
    """What a window of ``days`` can detect for this scope: the MDE at alpha 5 %, power 80 % against
    the 28-day baseline, for ANY ``days`` (``mde_for`` takes any N). ``hard`` = it cannot be
    judged or the MDE is above the limit: shown as "khó kết luận" but never refused."""
    mde = mde_for(metric, stats, days)
    hard = mde is None or mde > config.MDE_MAX
    pct = None if mde is None else round(mde * 100, 1)
    if mde is None:
        label = f"{days} ngày: chưa đủ dữ liệu để kết luận"
    elif hard:
        label = f"{days} ngày: chỉ thấy thay đổi ≥ {pct:g} % (khó kết luận)".replace(".", ",")
    else:
        label = f"{days} ngày: chỉ thấy thay đổi ≥ {pct:g} %".replace(".", ",")
    return {
        "days": days,
        "mde": _r(mde),
        "mde_pct": pct,
        "ok": not hard,
        "hard": hard,
        "label": label,
    }


def recommended_window(metric: str, stats: MetricStats) -> int | None:
    """The shortest preset whose MDE is within ``MDE_MAX`` (30 %); None when none of the presets
    reaches it (the longest preset is then pre-selected and the note says "khó kết luận")."""
    for d in config.WINDOW_PRESETS:
        m = mde_for(metric, stats, d)
        if m is not None and m <= config.MDE_MAX:
            return d
    return None


def window_options(metric: str, stats: MetricStats) -> dict[str, Any]:
    """The chooser: each preset with what it can detect, the recommended one, the bounds."""
    rec = recommended_window(metric, stats)
    presets = [window_option(metric, stats, d) for d in config.WINDOW_PRESETS]
    for row in presets:
        row["recommended"] = row["days"] == rec
    return {
        "metric": metric,
        "min_days": config.WINDOW_MIN_DAYS,
        "max_days": config.WINDOW_MAX_DAYS,
        "presets": presets,
        "recommended_days": rec,
        "default_days": rec or config.WINDOW_PRESETS[-1],
        "mde_max": config.MDE_MAX,
        "alpha": config.MDE_ALPHA,
        "power": config.MDE_POWER,
        "baseline_days": config.PLAN_PRE_DAYS,
    }


def check_window(days: Any) -> int:
    """A window the user typed: an integer between 3 and 90, else ``ValueError``."""
    if isinstance(days, bool) or not isinstance(days, int):
        raise ValueError("the window is a whole number of days")
    if not config.WINDOW_MIN_DAYS <= days <= config.WINDOW_MAX_DAYS:
        raise ValueError(f"the window is {config.WINDOW_MIN_DAYS} to {config.WINDOW_MAX_DAYS} days")
    return days


def stats_for(env: RecoEnv, items: tuple[str, ...] | list[str] | None, metric: str) -> MetricStats:
    """Volume / variability of the scope from the window's order lines and flow tables."""
    days = env.window_days
    wanted = set(items) if items else None
    per_order: dict[str, Decimal] = defaultdict(lambda: ZERO)
    per_day_orders: dict[Any, set[str]] = defaultdict(set)
    for ln, _ in env.view.pairs:
        if wanted is not None and ln.product_id not in wanted:
            continue
        per_order[ln.order_id] += ln.order_value
        per_day_orders[ln.order_date].add(ln.order_id)
    values = [float(v) for v in per_order.values()]
    daily = [len(per_day_orders.get(d, ())) for d in _days(env)]
    mu = mean(daily) if daily else 0.0
    phi = max(1.0, (pstdev(daily) ** 2) / mu) if mu > 0 and len(daily) > 1 else 1.0
    cv = None
    if len(values) >= 2 and mean(values) > 0:
        cv = pstdev(values) / mean(values)
    views = clicks = 0.0
    orders = float(len(per_order))
    flows = env.view.flows
    if flows is not None:
        tables = (
            [flows.products[i] for i in (items or []) if i in flows.products]
            if wanted is not None
            else [flows.shop]
        )
        for t in tables:
            for r in t.rows:
                if r.is_residual:
                    continue
                views += r.views or 0
                clicks += r.clicks or 0
    rate = None
    trials = 0.0
    if metric == "ctr" and views > 0:
        rate, trials = clicks / views, views / days
    elif metric == "ctor" and clicks > 0:
        rate, trials = orders / clicks, clicks / days
    count = (views / days) if metric == "views" else orders / days
    return MetricStats(rate, trials, count, orders / days, cv, phi)


def _days(env: RecoEnv) -> list[Any]:
    from datetime import timedelta

    w = env.view.window
    return [w.start + timedelta(days=i) for i in range(w.days)]
