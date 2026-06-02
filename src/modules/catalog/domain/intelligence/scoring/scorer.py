import math
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.utils.data.models import Livestream


@dataclass
class LivestreamScore:
    grade: int
    breakdown: dict[str, float] = field(default_factory=dict)


_WEIGHTS = {
    "revenue_per_viewer": 0.35,
    "conversion_rate": 0.25,
    "revenue_vs_avg": 0.20,
    "duration_efficiency": 0.20,
}


async def _shop_averages(
    session: AsyncSession, shop_id: uuid.UUID
) -> dict[str, float]:
    """Compute historical per-stream averages for the shop."""
    stmt = select(Livestream).where(
        Livestream.shop_id == shop_id,
        Livestream.viewer_count.isnot(None),
        Livestream.viewer_count > 0,
    )
    result = await session.execute(stmt)
    streams = list(result.scalars().all())

    if not streams:
        return {"avg_rpv": 0.0, "avg_conv": 0.0, "avg_revenue": 0.0, "avg_rph": 0.0}

    total_rpv = 0.0
    total_conv = 0.0
    total_revenue = 0.0
    total_rph = 0.0

    for s in streams:
        viewers = s.viewer_count or 1
        revenue = float(s.revenue or 0)
        orders = s.order_count or 0

        rpv = revenue / viewers
        conv = orders / viewers

        duration_hours = 1.0
        if s.start_time and s.end_time:
            dt = (s.end_time - s.start_time).total_seconds() / 3600
            if dt > 0:
                duration_hours = dt

        rph = revenue / duration_hours

        total_rpv += rpv
        total_conv += conv
        total_revenue += revenue
        total_rph += rph

    n = len(streams)
    return {
        "avg_rpv": total_rpv / n,
        "avg_conv": total_conv / n,
        "avg_revenue": total_revenue / n,
        "avg_rph": total_rph / n,
    }


def _sigmoid_scale(raw: float, midpoint: float) -> float:
    """Map a raw value to 0–100 via a logistic curve centered at *midpoint*."""
    if midpoint <= 0:
        return 50.0 if raw > 0 else 0.0
    x = (raw - midpoint) / (midpoint or 1)
    return 100.0 / (1.0 + math.exp(-3.0 * x))


async def score_livestream(
    session: AsyncSession, livestream_id: uuid.UUID
) -> LivestreamScore:
    ls = await session.get(Livestream, livestream_id)
    if ls is None:
        return LivestreamScore(grade=0, breakdown={})

    viewers = ls.viewer_count or 0
    if viewers == 0:
        return LivestreamScore(grade=0, breakdown={
            "revenue_per_viewer": 0.0,
            "conversion_rate": 0.0,
            "revenue_vs_avg": 0.0,
            "duration_efficiency": 0.0,
        })

    revenue = float(ls.revenue or 0)
    orders = ls.order_count or 0

    duration_hours = 1.0
    if ls.start_time and ls.end_time:
        dt = (ls.end_time - ls.start_time).total_seconds() / 3600
        if dt > 0:
            duration_hours = dt

    rpv = revenue / viewers
    conv = orders / viewers
    rph = revenue / duration_hours

    avgs = await _shop_averages(session, ls.shop_id)

    sub_scores = {
        "revenue_per_viewer": _sigmoid_scale(rpv, avgs["avg_rpv"]),
        "conversion_rate": _sigmoid_scale(conv, avgs["avg_conv"]),
        "revenue_vs_avg": _sigmoid_scale(revenue, avgs["avg_revenue"]),
        "duration_efficiency": _sigmoid_scale(rph, avgs["avg_rph"]),
    }

    weighted = sum(
        sub_scores[k] * _WEIGHTS[k] for k in _WEIGHTS
    )
    grade = max(0, min(100, int(round(weighted))))

    return LivestreamScore(grade=grade, breakdown=sub_scores)
