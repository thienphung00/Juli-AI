import math
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models import Livestream


@dataclass
class RetentionPoint:
    minute: int
    viewers: int


async def get_stream_retention(
    session: AsyncSession, livestream_id: uuid.UUID
) -> list[RetentionPoint]:
    """Derive a minute-by-minute estimated viewer retention curve from
    post-stream summary data.

    TikTok's official API provides only post-stream aggregate viewer counts,
    not per-minute telemetry. This function models an exponential-decay
    retention curve using the total viewer count and session duration.
    """
    ls = await session.get(Livestream, livestream_id)
    if ls is None:
        return []

    if ls.start_time is None or ls.end_time is None:
        return []

    duration_seconds = (ls.end_time - ls.start_time).total_seconds()
    duration_minutes = max(1, int(duration_seconds // 60))

    peak_viewers = ls.viewer_count or 0
    if peak_viewers == 0:
        return [RetentionPoint(minute=m, viewers=0) for m in range(1, duration_minutes + 1)]

    # Exponential decay: viewers(t) = peak * e^(-λt)
    # λ chosen so that viewers at the end ≈ 30% of peak (typical livestream retention)
    decay_target = 0.30
    lam = -math.log(decay_target) / duration_minutes

    points: list[RetentionPoint] = []
    for m in range(1, duration_minutes + 1):
        estimated = int(peak_viewers * math.exp(-lam * (m - 1)))
        points.append(RetentionPoint(minute=m, viewers=max(0, estimated)))

    return points
