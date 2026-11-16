"""TikTok's series source for the F10 reader (:mod:`.reader`).

Daily GMV per product from ``analytics_performance_intervals`` (``grain = 'product'``, day
rows). A day the shop has any product row for is a covered day: a product without a row on
it sold 0. A day with no row at all for the shop (not synced yet -- TikTok analytics run
:data:`TIKTOK_ANALYTICS_EXPECTED_LAG_DAYS` behind -- or a gap) is dropped, never read as 0.

- **Treated** -- the card's products summed per day.
- **Controls** -- every other product of the shop that no other run touched in the window
  (another run's non-sandbox write, or another verified promotion's start).
- **Dropped days** -- uncovered days, and the days another run changed a treated product.

Metric: GMV. Profit stays null until the TikTok profit adapter exists (F9), so the verdict
is on ΔGMV.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.lever_flows import RunLeverFlow
from juli_backend.models.models import (
    WRITE_MODE_SIMULATED,
    AnalyticsPerformanceInterval,
    Product,
)
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.run_changes import RunWriteValue
from juli_backend.services.card_measure.reader import Forecast, SeriesBundle

#: TikTok analytics normally run 2 days behind (F2 amendment, 2026-11-16).
#: NOTE: the F2 executor's branch may define the same tunable for the forecast core; when both
#: land, keep one and import it here.
TIKTOK_ANALYTICS_EXPECTED_LAG_DAYS = 2
PLATFORM = "tiktok"
METRIC = "gmv"
DAYS_PER_MONTH = 30
_GRAIN = "product"


class DayRow(Protocol):
    @property
    def start_date(self) -> date: ...
    @property
    def tiktok_product_id(self) -> str | None: ...
    @property
    def gmv(self) -> Any: ...


def _days(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def gmv_bundle(
    rows: Iterable[DayRow],
    treated_ids: Sequence[str],
    first: date,
    last: date,
    *,
    touched: Mapping[str, Iterable[date]] | None = None,
) -> SeriesBundle:
    """The reader's input from the shop's product-day rows over ``[first, last]``.

    ``touched``: product -> the days another run changed it. A touched treated product drops
    those days; a touched other product is not a control."""
    per_product: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
    covered: set[date] = set()
    newest: date | None = None
    for row in rows:
        day = row.start_date
        newest = day if newest is None or day > newest else newest
        if not first <= day <= last or not row.tiktok_product_id:
            continue
        covered.add(day)
        per_product[row.tiktok_product_id][day] += float(row.gmv or 0)
    window = _days(first, last)
    treated = set(treated_ids)
    touched = touched or {}
    excluded = {d for d in window if d not in covered}
    for pid in treated:
        excluded.update(d for d in touched.get(pid, ()) if first <= d <= last)

    def series(days_of: Mapping[date, float]) -> dict[date, float]:
        return {d: days_of.get(d, 0.0) for d in window if d in covered}

    treated_series = {
        d: sum(per_product.get(pid, {}).get(d, 0.0) for pid in treated)
        for d in window
        if d in covered
    }
    controls = {
        pid: series(days_of)
        for pid, days_of in per_product.items()
        if pid not in treated and not any(first <= d <= last for d in touched.get(pid, ()))
    }
    return SeriesBundle(treated_series, controls, frozenset(excluded), newest)


def card_forecast(payload_json: str | None) -> Forecast:
    """The card's GMV/day forecast: P50 = ``diagnosis.recoverable_gmv_per_day`` (Dự kiến);
    P10 / P90 = ``gmv_estimate.per_month_min`` / ``per_month_max`` ÷ 30 (internal, F4)."""
    try:
        payload = json.loads(payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, Mapping):
        return Forecast()
    diagnosis = payload.get("diagnosis")
    estimate = payload.get("gmv_estimate")

    def num(block: Any, key: str, scale: float = 1.0) -> float | None:
        if not isinstance(block, Mapping) or block.get(key) is None:
            return None
        try:
            return float(block[key]) / scale
        except (TypeError, ValueError):
            return None

    return Forecast(
        p50=num(diagnosis, "recoverable_gmv_per_day"),
        p10=num(estimate, "per_month_min", DAYS_PER_MONTH),
        p90=num(estimate, "per_month_max", DAYS_PER_MONTH),
    )


def _naive_utc_date(value: datetime) -> date:
    return (value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value).date()


async def touched_days(
    session: AsyncSession,
    shop_id: uuid.UUID,
    run_id: uuid.UUID | None,
    first: date,
    last: date,
) -> dict[str, set[date]]:
    """product -> the days in ``[first, last]`` another run wrote to it (not a sandbox write)
    or another verified promotion started on it."""
    out: dict[str, set[date]] = defaultdict(set)
    writes = select(RunWriteValue.tiktok_product_id, RunWriteValue.recorded_at).join(
        WorkflowRunRow, WorkflowRunRow.id == RunWriteValue.workflow_run_id
    )
    writes = writes.where(
        RunWriteValue.shop_id == shop_id,
        or_(
            WorkflowRunRow.write_mode.is_(None),
            WorkflowRunRow.write_mode != WRITE_MODE_SIMULATED,
        ),
    )
    if run_id is not None:
        writes = writes.where(RunWriteValue.workflow_run_id != run_id)
    for pid, at in (await session.execute(writes)).all():
        day = _naive_utc_date(at)
        if pid and first <= day <= last:
            out[pid].add(day)
    promos = (
        select(Product.tiktok_product_id, RunLeverFlow.measurement_start)
        .join(WorkflowRunRow, WorkflowRunRow.id == RunLeverFlow.workflow_run_id)
        .join(Product, Product.id == WorkflowRunRow.product_id)
        .where(RunLeverFlow.shop_id == shop_id, RunLeverFlow.measurement_start.is_not(None))
    )
    if run_id is not None:
        promos = promos.where(RunLeverFlow.workflow_run_id != run_id)
    for pid, day in (await session.execute(promos)).all():
        if pid and day is not None and first <= day <= last:
            out[pid].add(day)
    return dict(out)


@dataclass(frozen=True)
class TikTokGmvSource:
    """:class:`reader.SeriesSource` for TikTok product GMV."""

    platform: str = PLATFORM
    expected_lag_days: int = TIKTOK_ANALYTICS_EXPECTED_LAG_DAYS

    async def load(
        self,
        session: AsyncSession,
        shop_id: uuid.UUID,
        subject_ids: Sequence[str],
        first: date,
        last: date,
        *,
        run_id: uuid.UUID | None = None,
    ) -> SeriesBundle:
        rows = (
            (
                await session.execute(
                    select(AnalyticsPerformanceInterval).where(
                        AnalyticsPerformanceInterval.shop_id == shop_id,
                        AnalyticsPerformanceInterval.grain == _GRAIN,
                        AnalyticsPerformanceInterval.hour_index.is_(None),
                        AnalyticsPerformanceInterval.start_date >= first,
                        AnalyticsPerformanceInterval.start_date <= last,
                    )
                )
            )
            .scalars()
            .all()
        )
        touched = await touched_days(session, shop_id, run_id, first, last)
        bundle = gmv_bundle(rows, subject_ids, first, last, touched=touched)
        newest = await self._newest_day(session, shop_id)
        return SeriesBundle(bundle.treated, bundle.controls, bundle.excluded, newest)

    @staticmethod
    async def _newest_day(session: AsyncSession, shop_id: uuid.UUID) -> date | None:
        return (
            await session.execute(
                select(func.max(AnalyticsPerformanceInterval.start_date)).where(
                    AnalyticsPerformanceInterval.shop_id == shop_id,
                    AnalyticsPerformanceInterval.grain == _GRAIN,
                )
            )
        ).scalar_one_or_none()


__all__ = [
    "METRIC",
    "PLATFORM",
    "TIKTOK_ANALYTICS_EXPECTED_LAG_DAYS",
    "TikTokGmvSource",
    "card_forecast",
    "gmv_bundle",
    "touched_days",
]
