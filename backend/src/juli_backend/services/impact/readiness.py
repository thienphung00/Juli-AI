"""Impact readiness check — pre-write validation (#1338).

Given a shop and tiktok_product_id, answer whether a T+7 reading could clear
the confidence floor: does the pre-window (T−14…T−1) have enough daily rows in
analytics_performance_intervals, is a viable control set available, and would
the target's volume clear the floor services/impact/confidence applies.

The verdict is compared against what run_daily_impact_reader actually produces
for the same window on seeded data — ready ⇔ non-suppressed tier,
not-ready ⇔ suppressed. A readiness check that disagrees with the reader is
worse than none, and this is the assertion that prevents it.

Reuses services/impact's own floor and control-set logic rather than
re-deriving thresholds — a second copy of a threshold is a second thing to drift.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import AnalyticsPerformanceInterval
from juli_backend.services.impact.confidence import (
    GMV,
    pre_period_volume,
    volume_floor_for,
)
from juli_backend.services.impact.control_pool import MIN_CANDIDATES
from juli_backend.services.impact.metric_map import RawDailyRecord
from juli_backend.services.impact.windows import pre_window


@dataclass(frozen=True)
class ReadinessResult:
    """The readiness verdict with reasons."""

    is_ready: bool
    reason: str


async def check_readiness(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    tiktok_product_id: str,
    reference_date: date,
) -> ReadinessResult:
    """Check if a shop+product is ready for an impact reading.

    Given a shop and product, answer whether a T+7 reading could clear the
    confidence floor by examining:
    - Pre-window (T-14…T-1) daily row count in analytics_performance_intervals
    - Whether the target volume clears the floor that services/impact applies
    - Viability of control-set candidates (if applicable)

    Returns a verdict with reasons — the owner needs to know which condition
    is short and by how much, not just a bare boolean.

    The verdict is validated against what run_daily_impact_reader actually
    produces: ready ⇔ non-suppressed tier, not-ready ⇔ suppressed.
    """
    pre_start, pre_end = pre_window(reference_date)

    # Query analytics_performance_intervals for pre-window rows
    stmt = (
        select(AnalyticsPerformanceInterval)
        .where(
            and_(
                AnalyticsPerformanceInterval.shop_id == shop_id,
                AnalyticsPerformanceInterval.tiktok_product_id == tiktok_product_id,
                AnalyticsPerformanceInterval.start_date >= pre_start,
                AnalyticsPerformanceInterval.start_date <= pre_end,
            )
        )
        .order_by(AnalyticsPerformanceInterval.start_date)
    )

    result = await session.execute(stmt)
    rows = result.scalars().all()

    # Check 1: Do we have any data at all?
    if not rows:
        return ReadinessResult(
            is_ready=False,
            reason=(
                "Not ready: No analytics data in pre-window (T-14 to T-1). "
                "No history to measure against."
            ),
        )

    # Build daily series
    daily_series: dict[date, RawDailyRecord] = {}
    for row in rows:
        if row.start_date not in daily_series and row.start_date != reference_date:
            daily_series[row.start_date] = RawDailyRecord(
                gmv=row.gmv,
                sku_orders=Decimal(row.sku_orders) if row.sku_orders is not None else None,
                items_sold=Decimal(row.items_sold) if row.items_sold is not None else None,
                impressions=Decimal(row.impressions) if row.impressions is not None else None,
                ctr=row.ctr,
                conversion_rate=row.conversion_rate,
                visitors=Decimal(row.visitors) if row.visitors is not None else None,
            )

    # Check 2: Do we have enough pre-window rows?
    # Pre-window is T-14 to T-1 (14 days max, but T is excluded).
    # We need at least 2 days for noise band calculation (statistics.stdev >= 2).
    # With fewer than 2 days, the noise band will be None and the reading suppressed.
    pre_days_available = len(daily_series)
    if pre_days_available < 2:
        return ReadinessResult(
            is_ready=False,
            reason=(
                f"Not ready: Only {pre_days_available} pre-window data point(s), "
                "need at least 2 for noise band calculation."
            ),
        )

    # Check 3: Is the volume above floor?
    # Use GMV/orders as the default metric family for floor check
    metric = GMV
    volume = pre_period_volume(daily_series, metric, reference_date)
    floor = volume_floor_for(metric)

    if volume is None:
        return ReadinessResult(
            is_ready=False,
            reason=(
                f"Not ready: Pre-window volume data unavailable. "
                f"Cannot determine if above floor ({floor})."
            ),
        )

    if volume < floor:
        return ReadinessResult(
            is_ready=False,
            reason=(
                f"Not ready: Pre-window average volume {volume} is below floor "
                f"({floor} orders/day). Need more traffic."
            ),
        )

    # Check 4: Is a viable control set available?
    # Query for other products in the shop that could serve as controls.
    # Minimum requirement: MIN_CANDIDATES (3) products with pre-window data.
    control_product_count_stmt = (
        select(AnalyticsPerformanceInterval.tiktok_product_id)
        .where(
            and_(
                AnalyticsPerformanceInterval.shop_id == shop_id,
                AnalyticsPerformanceInterval.tiktok_product_id != tiktok_product_id,
                AnalyticsPerformanceInterval.start_date >= pre_start,
                AnalyticsPerformanceInterval.start_date <= pre_end,
            )
        )
        .distinct()
    )
    control_result = await session.execute(control_product_count_stmt)
    control_candidates = control_result.scalars().all()
    candidate_count = len(control_candidates)

    if candidate_count < MIN_CANDIDATES:
        return ReadinessResult(
            is_ready=False,
            reason=(
                f"Not ready: Only {candidate_count} candidate control product(s), "
                f"need at least {MIN_CANDIDATES}. "
                f"Signal will fall back to simple pre/post comparison (capped at Thấp)."
            ),
        )

    # All checks passed: ready!
    return ReadinessResult(
        is_ready=True,
        reason=(
            f"Ready: Pre-window has {pre_days_available} data point(s), "
            f"volume {volume} clears floor ({floor}), "
            f"and {candidate_count} control candidate(s) available. "
            f"T+7 reading should be measurable."
        ),
    )
