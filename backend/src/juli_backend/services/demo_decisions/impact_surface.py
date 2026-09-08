"""Demo impact surface — wire real package to synthetic series (issue #1768, ADR-099).

This module computes impact readings for demo products using the REAL
services/impact/ machinery, but with synthetic series as input. Every number
is genuinely computed — no hardcoded impact_pct — and all readings are
persisted with series_source='synthetic'.

The one seam for migration to real users is synthetic_series_for() — swap
the series source there, nothing else changes.

Key constraint: **No hardcoded impact_pct anywhere**. If a reading cannot be
computed (readiness fails, control pool fails, data is degenerate), the
refusal the algorithm produces is rendered — not a placeholder, not an
em-dash.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database import Product
from juli_backend.models.models import AnalyticsPerformanceInterval, ImpactReading
from juli_backend.services.impact import (
    ControlCandidate,
    MutationKind,
    RawDailyRecord,
    check_readiness,
    compute_confidence,
    compute_mutation_readings,
    select_control_pool,
    volume_floor_for,
    volume_indicator_for,
)
from juli_backend.services.impact.control_pool import ControlPoolResult
from juli_backend.services.impact.metric_map import METRIC_MAP


async def synthetic_series_for(
    session: AsyncSession,
    product: Product,
    reference_date: date,
) -> dict[date, RawDailyRecord]:
    """Fetch daily series for a product from synthetic analytics.

    This is the ONE function that changes when migrating from synthetic to
    real users. Replace the implementation here to read from
    AnalyticsPerformanceInterval against real mutation history instead of
    the seeded cohort.

    Args:
        session: Database session
        product: The product to fetch series for
        reference_date: The reference date (T) for window calculations

    Returns:
        Mapping of date → RawDailyRecord, covering [-14, +14] day window around reference_date
    """
    from juli_backend.services.impact.windows import date_range

    window_dates = date_range(
        reference_date - __import__("datetime").timedelta(days=14),
        reference_date + __import__("datetime").timedelta(days=14),
    )

    # Query analytics for the product in the window
    result = await session.execute(
        select(AnalyticsPerformanceInterval).where(
            (AnalyticsPerformanceInterval.shop_id == product.shop_id)
            & (AnalyticsPerformanceInterval.tiktok_product_id == product.tiktok_product_id)
            & (AnalyticsPerformanceInterval.start_date >= window_dates[0])
            & (AnalyticsPerformanceInterval.start_date <= window_dates[-1])
        )
    )
    intervals = result.scalars().all()

    # Build daily series
    daily: dict[date, RawDailyRecord] = {}
    for interval in intervals:
        # Skip the reference date itself (T is excluded from both windows)
        if interval.start_date == reference_date:
            continue

        daily[interval.start_date] = RawDailyRecord(
            gmv=Decimal(interval.gmv) if interval.gmv is not None else None,
            sku_orders=Decimal(interval.sku_orders) if interval.sku_orders is not None else None,
            items_sold=Decimal(interval.items_sold) if interval.items_sold is not None else None,
            impressions=Decimal(interval.impressions) if interval.impressions is not None else None,
            ctr=Decimal(interval.click_through_rate)
            if interval.click_through_rate is not None
            else None,
            conversion_rate=Decimal(interval.click_order_rate)
            if interval.click_order_rate is not None
            else None,
            visitors=Decimal(interval.visitors) if interval.visitors is not None else None,
        )

    return daily


async def _fetch_sibling_series(
    session: AsyncSession,
    shop_id: uuid.UUID,
    excluded_product_id: str,
    reference_date: date,
    first_active_date: date,
) -> list[ControlCandidate]:
    """Fetch all sibling products as ControlCandidate for control pool.

    Args:
        session: Database session
        shop_id: Shop ID
        excluded_product_id: Product ID to exclude (the target)
        reference_date: Reference date T
        first_active_date: Date when sibling became active (e.g., T - 20 days)

    Returns:
        List of ControlCandidate with daily series
    """
    from juli_backend.services.impact.windows import date_range

    window_dates = date_range(
        reference_date - __import__("datetime").timedelta(days=14),
        reference_date + __import__("datetime").timedelta(days=14),
    )

    # Query all products except target
    result = await session.execute(
        select(Product).where(
            (Product.shop_id == shop_id) & (Product.tiktok_product_id != excluded_product_id)
        )
    )
    sibling_products = result.scalars().all()

    candidates = []
    for sibling in sibling_products:
        # Fetch analytics for sibling
        analytics_result = await session.execute(
            select(AnalyticsPerformanceInterval).where(
                (AnalyticsPerformanceInterval.shop_id == shop_id)
                & (AnalyticsPerformanceInterval.tiktok_product_id == sibling.tiktok_product_id)
                & (AnalyticsPerformanceInterval.start_date >= window_dates[0])
                & (AnalyticsPerformanceInterval.start_date <= window_dates[-1])
            )
        )
        intervals = analytics_result.scalars().all()

        # Build daily series
        daily: dict[date, RawDailyRecord] = {}
        for interval in intervals:
            if interval.start_date == reference_date:
                continue

            daily[interval.start_date] = RawDailyRecord(
                gmv=Decimal(interval.gmv) if interval.gmv is not None else None,
                sku_orders=Decimal(interval.sku_orders)
                if interval.sku_orders is not None
                else None,
                items_sold=Decimal(interval.items_sold)
                if interval.items_sold is not None
                else None,
                impressions=Decimal(interval.impressions)
                if interval.impressions is not None
                else None,
                ctr=Decimal(interval.click_through_rate)
                if interval.click_through_rate is not None
                else None,
                conversion_rate=Decimal(interval.click_order_rate)
                if interval.click_order_rate is not None
                else None,
                visitors=Decimal(interval.visitors) if interval.visitors is not None else None,
            )

        candidates.append(
            ControlCandidate(
                product_id=sibling.tiktok_product_id,
                daily=daily,
                touched=False,  # Demo products are never "touched" (no prior Juli run)
                first_active_date=first_active_date,
            )
        )

    return candidates


async def _persist_refusal(
    session: AsyncSession,
    *,
    tool_execution_id: uuid.UUID,
    mutation_kind: MutationKind,
    reason: str,
) -> list[ImpactReading]:
    """Persist one `suppressed` row per metric the mutation would have reported.

    One row per metric, not a single summary row, because the surface renders per
    metric: if only some metrics were persisted, the others would render as absent
    rather than as declined, and absent reads as "nothing happened".

    The numerics stay NULL. `confidence.py` has a tier for exactly this — the
    algorithm was asked a question it could not answer — and `copy.py` already
    renders it into a Vietnamese sentence, so nothing here authors seller-facing
    text.
    """
    metrics = METRIC_MAP[mutation_kind]
    now = datetime.now(UTC)
    rows = [
        ImpactReading(
            id=uuid.uuid4(),
            tool_execution_id=tool_execution_id,
            metric=spec.key,
            kind="preliminary",
            pre=None,
            post=None,
            expected=None,
            incremental=None,
            impact_pct=None,
            confidence="suppressed",
            control_set_json=json.dumps(
                {
                    "control_ids": [],
                    "used_fallback": False,
                    "fallback_reason": None,
                    "refused_at": "readiness",
                    "reason": reason,
                }
            ),
            computed_at=now,
            series_source="synthetic",
        )
        for spec in [metrics.primary, *metrics.secondary]
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def compute_and_persist_demo_readings(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    tool_execution_id: uuid.UUID,
    mutation_kind: MutationKind,
    reference_date: date,
    tiktok_product_id: str = "cohort-target",
) -> list[ImpactReading]:
    """Compute readings from synthetic series with the REAL package, and persist them.

    Every number persisted here is produced by `compute.py` and tiered by
    `confidence.py`. Nothing is authored. If the algorithm refuses — readiness
    says the mutation is unmeasurable, the control pool falls back, or the
    arithmetic is degenerate — the refusal is what gets stored, as a row whose
    numerics are NULL and whose tier says why. It is never replaced by a
    placeholder, because a placeholder is a measurement that measured nothing
    (ADR-099 decision 1, gate #1339).

    A READING HANGS OFF A TOOL EXECUTION, not off a product. `tool_execution_id`
    is NOT NULL on this table: the question the reading answers is "what did THIS
    write do", so there is no such thing as a reading without one. The caller
    supplies it; the demo's seeded execution is as real a row as production's.

    `tiktok_product_id` is a parameter, not a constant, because the seeded cohort
    deliberately contains products the algorithm must REFUSE — one below the volume
    floor, one arithmetically degenerate (ADR-099 decision 4). If the target were
    hardcoded, no caller could ever reach a refusal, and the demo could only ever
    show the happy path — the failure that decision exists to prevent.

    Returns the persisted readings so a caller can render them without re-reading.
    """
    target = (
        await session.execute(
            select(Product).where(
                Product.shop_id == shop_id,
                Product.tiktok_product_id == tiktok_product_id,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        return []

    # DECISION 5: readiness first, and honoured. A surface that promises a reading
    # it cannot produce lies about the feature one step earlier than fabricating
    # the number would.
    readiness = await check_readiness(
        session,
        shop_id=shop_id,
        tiktok_product_id=target.tiktok_product_id,
        reference_date=reference_date,
    )
    # Direct attribute, not a defensive getattr: `ReadinessResult.is_ready` is a
    # real field, and a getattr default of True would silently PROMISE a reading
    # if the shape ever changed — the exact failure decision 5 exists to prevent.
    if not readiness.is_ready:
        # A refusal is a reading. Returning [] here would leave the surface with
        # nothing to render, and a surface handed nothing invents its own copy —
        # which is how a placeholder gets in front of a seller. So the refusal is
        # persisted: NULL numerics, a tier that says the algorithm declined, and
        # the readiness reason kept in `control_set_json` so the "why" survives
        # (ADR-099 decisions 1 and 4).
        return await _persist_refusal(
            session,
            tool_execution_id=tool_execution_id,
            mutation_kind=mutation_kind,
            reason=readiness.reason,
        )

    target_daily = await synthetic_series_for(session, target, reference_date)
    # Siblings must be active >= MIN_ACTIVE_DAYS before T or the pool disqualifies
    # them; the seeder backdates them, so anchor first_active well before the window.
    candidates = await _fetch_sibling_series(
        session,
        shop_id,
        target.tiktok_product_id,
        reference_date,
        reference_date - timedelta(days=60),
    )

    metrics = METRIC_MAP[mutation_kind]
    specs = [metrics.primary, *metrics.secondary]

    control_by_metric: dict[str, ControlPoolResult] = {}
    for spec in specs:
        control_by_metric[spec.key] = select_control_pool(
            metric=spec,
            target_daily=target_daily,
            candidates=candidates,
            t=reference_date,
            kind="preliminary",
            volume_floor=volume_floor_for(spec),
            volume_of=volume_indicator_for(spec),
        )

    readings = compute_mutation_readings(
        mutation=mutation_kind,
        target_daily=target_daily,
        control_daily_by_metric={k: v.control_daily for k, v in control_by_metric.items()},
        t=reference_date,
        kind="preliminary",
        confounded=False,
    )

    persisted: list[ImpactReading] = []
    now = datetime.now(UTC)
    for spec, reading in zip(specs, [readings.primary, *readings.secondary], strict=True):
        pool = control_by_metric[spec.key]
        # The tier is NOT on MetricReading — `reading.py` deliberately leaves tier
        # assignment to `confidence.py` (#1043), so it is computed here rather
        # than read off an attribute that does not exist.
        tier = compute_confidence(
            metric=spec,
            target_daily=target_daily,
            control_pool_result=pool,
            reading=reading,
        )
        row = ImpactReading(
            id=uuid.uuid4(),
            tool_execution_id=tool_execution_id,
            metric=reading.metric,
            kind=reading.kind,
            pre=reading.pre,
            post=reading.post,
            expected=reading.expected,
            incremental=reading.incremental,
            impact_pct=reading.impact_pct,
            confidence=tier.tier,
            control_set_json=json.dumps(
                {
                    "control_ids": [s.product_id for s in pool.selected],
                    "used_fallback": pool.used_fallback,
                    "fallback_reason": pool.fallback_reason,
                    "mean_correlation": pool.mean_correlation,
                    "windows": {
                        "pre_start": pool.windows.pre_start.isoformat(),
                        "pre_end": pool.windows.pre_end.isoformat(),
                        "post_start": pool.windows.post_start.isoformat(),
                        "post_end": pool.windows.post_end.isoformat(),
                    },
                }
            ),
            computed_at=now,
            # NOT NULL with no default (#1766): a caller that forgets this fails
            # rather than silently recording a synthetic reading as measured.
            series_source="synthetic",
        )
        session.add(row)
        persisted.append(row)

    await session.flush()
    return persisted
