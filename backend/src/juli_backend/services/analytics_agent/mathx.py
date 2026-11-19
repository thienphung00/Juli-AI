"""Pure formulas of the chains (J4g): additive shares, LMDI, rate/mix, change point, noise."""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from datetime import date


def lmdi(y0: float, y1: float, factors: dict[str, tuple[float, float]]) -> dict[str, float]:
    """Effect of each factor (x0, x1) on y1 - y0; they add up to the change exactly."""
    if y0 <= 0 or y1 <= 0 or any(a <= 0 or b <= 0 for a, b in factors.values()):
        return {}
    big_l = (y1 - y0) / (math.log(y1) - math.log(y0)) if y1 != y0 else y0
    return {k: big_l * math.log(b / a) for k, (a, b) in factors.items()}


def rate_mix(
    seg0: dict[str, tuple[float, float]], seg1: dict[str, tuple[float, float]]
) -> dict[str, dict[str, float]]:
    """Segments -> (numerator, denominator) per window; delta R = sum w-bar*dr + sum r-bar*dw."""
    d0 = sum(d for _, d in seg0.values()) or 0
    d1 = sum(d for _, d in seg1.values()) or 0
    out: dict[str, dict[str, float]] = {}
    if not d0 or not d1:
        return out
    for k in set(seg0) | set(seg1):
        n0, e0 = seg0.get(k, (0.0, 0.0))
        n1, e1 = seg1.get(k, (0.0, 0.0))
        w0, w1 = e0 / d0, e1 / d1
        r0 = n0 / e0 if e0 else 0.0
        r1 = n1 / e1 if e1 else 0.0
        out[k] = {
            "rate": (w0 + w1) / 2 * (r1 - r0),
            "mix": (r0 + r1) / 2 * (w1 - w0),
            "r0": r0,
            "r1": r1,
            "w0": w0,
            "w1": w1,
        }
    return out


def change_point(series: list[tuple[date, float]]) -> date | None:
    best, arg = 0.0, None
    vals = [v for _, v in series]
    for i in range(2, len(vals) - 1):
        a, b = vals[:i], vals[i:]
        gap = abs(statistics.fmean(b) - statistics.fmean(a))
        if gap > best:
            best, arg = gap, series[i][0]
    return arg


def robust_z(x: float, hist: Iterable[float]) -> float | None:
    h = list(hist)
    if len(h) < 4:
        return None
    med = statistics.median(h)
    mad = statistics.median(abs(v - med) for v in h)
    if mad == 0:
        return None if x == med else math.copysign(99.0, x - med)
    return (x - med) / (1.4826 * mad)


def poisson_z(now: float, expected: float) -> float | None:
    return (now - expected) / math.sqrt(expected) if expected > 0 else None


def poisson_significant(now: float, expected: float) -> bool | None:
    z = poisson_z(now, expected)
    return None if z is None else abs(z) >= 1.96
