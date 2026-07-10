import math
import uuid
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Livestream

_MIN_HISTORY_FOR_STDDEV = 30
_ANOMALY_SIGMA_THRESHOLD = 2.0


@dataclass
class Anomaly:
    metric: str
    current_value: float
    mean: float
    deviation_sigma: float
    livestream_id: uuid.UUID


def _compute_stats(values: list[float]) -> tuple[float, float]:
    """Return (mean, stddev). Uses population stddev."""
    if not values:
        return 0.0, 0.0
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return mean, math.sqrt(variance)


def _moving_average_stats(values: list[float], window: int = 7) -> tuple[float, float]:
    """Fallback for <30 data points: use short moving-average window."""
    if not values:
        return 0.0, 0.0
    recent = values[-window:] if len(values) >= window else values
    return _compute_stats(recent)


async def detect_anomalies(
    session: AsyncSession, shop_id: uuid.UUID
) -> list[Anomaly]:
    stmt = (
        select(Livestream)
        .where(Livestream.shop_id == shop_id)
        .order_by(Livestream.start_time.asc())
    )
    result = await session.execute(stmt)
    streams = list(result.scalars().all())

    if len(streams) < 2:
        return []

    metrics_extractors: dict[str, Callable[[Livestream], float]] = {
        "revenue": lambda s: float(s.revenue or 0),
        "order_count": lambda s: float(s.order_count or 0),
        "viewer_count": lambda s: float(s.viewer_count or 0),
    }

    historical = streams[:-1]
    latest_batch = streams[-1:]

    use_stddev = len(historical) >= _MIN_HISTORY_FOR_STDDEV

    anomalies: list[Anomaly] = []
    for metric_name, extractor in metrics_extractors.items():
        hist_values = [extractor(s) for s in historical]

        if use_stddev:
            mean, stddev = _compute_stats(hist_values)
        else:
            mean, stddev = _moving_average_stats(hist_values)

        for stream in latest_batch:
            current = extractor(stream)

            if stddev == 0:
                if current != mean:
                    anomalies.append(Anomaly(
                        metric=metric_name,
                        current_value=current,
                        mean=mean,
                        deviation_sigma=float("inf"),
                        livestream_id=stream.id,
                    ))
                continue

            sigma = abs(current - mean) / stddev
            if sigma >= _ANOMALY_SIGMA_THRESHOLD:
                anomalies.append(Anomaly(
                    metric=metric_name,
                    current_value=current,
                    mean=mean,
                    deviation_sigma=sigma,
                    livestream_id=stream.id,
                ))

    return anomalies
