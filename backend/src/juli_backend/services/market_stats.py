"""Tiny order statistics for the public market lane (P92 B-10). Pure."""

from __future__ import annotations

from collections.abc import Sequence


def percentile(values: Sequence[float], q: float) -> float | None:
    """The ``q`` (0..1) quantile with linear interpolation between ranks; ``None`` when empty."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = min(max(q, 0.0), 1.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return float(ordered[low] + (ordered[high] - ordered[low]) * (rank - low))


def median(values: Sequence[float]) -> float | None:
    return percentile(values, 0.5)


__all__ = ["median", "percentile"]
