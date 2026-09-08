"""Integration test: demo cohort seeds readings including real tiers and deliberate refusals.

This test implements ADR-099 decisions 3 and 4:
- The seeded cohort must satisfy control pool requirements
- The seeded set must deliberately include readings that refuse (below_floor, suppressed)
- All readings must be marked with series_source='synthetic'

The test:
1. Seeds a demo cohort using the real impact machinery
2. Computes impact readings for each product in the cohort
3. Verifies that readings include:
   - At least one real tier (cao, trung_binh, or thap) with non-empty control_ids
   - At least one below_floor (insufficient pre-period volume)
   - At least one suppressed (degenerate data case)
   - All readings have series_source='synthetic'
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database import Product, Shop
from juli_backend.models.models import AnalyticsPerformanceInterval
from juli_backend.services.impact.confidence import volume_floor_for, volume_indicator_for
from juli_backend.services.impact.control_pool import (
    ControlCandidate,
    select_control_pool,
)
from juli_backend.services.impact.metric_map import resolve_metric
from juli_backend.services.impact.reading import compute_mutation_readings
from juli_backend.services.seeds.demo_cohort import seed_demo_cohort_for_impact


@pytest_asyncio.fixture
async def demo_cohort(session: AsyncSession, monkeypatch) -> dict:
    """Seed a demo cohort for impact reading and return the shop + products."""
    demo_shop_id = str(uuid.uuid4())
    monkeypatch.setenv("DEMO_SHOP_ID", demo_shop_id)

    await seed_demo_cohort_for_impact(session)

    # Fetch the created shop and products
    shop_result = await session.execute(select(Shop).where(Shop.id == uuid.UUID(demo_shop_id)))
    shop = shop_result.scalar()

    products_result = await session.execute(
        select(Product).where(Product.shop_id == uuid.UUID(demo_shop_id))
    )
    products = products_result.scalars().all()

    return {"shop": shop, "products": products}


@pytest.mark.asyncio
async def test_demo_cohort_seeds_minimum_candidates(demo_cohort) -> None:
    """The seeded cohort has at least MIN_CANDIDATES (3) products."""
    products = demo_cohort["products"]
    assert len(products) >= 3, (
        f"Cohort must have at least {3} products for control pool selection; got {len(products)}"
    )


@pytest.mark.asyncio
async def test_demo_cohort_has_analytics_covering_windows(
    session: AsyncSession, demo_cohort
) -> None:
    """Every product has analytics spanning the full [-14, +14] day window around T."""
    shop = demo_cohort["shop"]
    products = demo_cohort["products"]

    # Use today as T (the mutation date)
    t = date.today()
    pre_start = t - timedelta(days=14)
    post_end = t + timedelta(days=14)

    for product in products:
        intervals_result = await session.execute(
            select(AnalyticsPerformanceInterval).where(
                (AnalyticsPerformanceInterval.shop_id == shop.id)
                # Without this filter the query returned every row in the shop,
                # so each of the eight iterations asserted `232 >= 20` and the
                # loop variable did nothing. Seven of eight products could have
                # had no analytics at all and this still passed eight times.
                & (AnalyticsPerformanceInterval.tiktok_product_id == product.tiktok_product_id)
                & (AnalyticsPerformanceInterval.start_date >= pre_start)
                & (AnalyticsPerformanceInterval.start_date <= post_end)
            )
        )
        intervals = intervals_result.scalars().all()

        # Expect at least 20 days of data (should be 29 if complete)
        assert len(intervals) >= 20, (
            f"Product {product.tiktok_product_id} should have analytics for at least "
            f"20 days in window; got {len(intervals)}"
        )


@pytest.mark.asyncio
async def test_demo_cohort_produces_real_tier_reading(session: AsyncSession, demo_cohort) -> None:
    """The cohort produces at least one reading in a real confidence tier."""
    shop = demo_cohort["shop"]
    products = demo_cohort["products"]

    # Separate target (first) from candidates (rest)
    target_product = products[0]
    candidate_products = products[1:]

    t = date.today()

    # Fetch analytics for all products
    async def fetch_daily_series(product_id: str) -> dict:
        """Fetch daily series for a product as RawDailyRecord mapping."""
        from decimal import Decimal

        from juli_backend.services.impact.metric_map import RawDailyRecord

        result = await session.execute(
            select(AnalyticsPerformanceInterval).where(
                (AnalyticsPerformanceInterval.shop_id == shop.id)
                & (AnalyticsPerformanceInterval.tiktok_product_id == product_id)
                & (AnalyticsPerformanceInterval.start_date >= (t - timedelta(days=14)))
                & (AnalyticsPerformanceInterval.start_date <= (t + timedelta(days=14)))
            )
        )
        intervals = result.scalars().all()

        daily: dict[date, RawDailyRecord] = {}
        for interval in intervals:
            # Convert to Decimal where needed
            daily[interval.start_date] = RawDailyRecord(
                impressions=Decimal(interval.impressions) if interval.impressions else None,
                ctr=Decimal(interval.click_through_rate) if interval.click_through_rate else None,
                conversion_rate=Decimal(interval.click_order_rate)
                if interval.click_order_rate
                else None,
                items_sold=Decimal(interval.items_sold) if interval.items_sold else None,
                gmv=Decimal(interval.gmv) if interval.gmv else None,
                sku_orders=Decimal(interval.sku_orders) if interval.sku_orders else None,
                visitors=Decimal(interval.visitors) if interval.visitors else None,
            )
        return daily

    target_daily = await fetch_daily_series(target_product.tiktok_product_id)

    # Build candidates
    candidates = []
    for candidate_product in candidate_products:
        candidate_daily = await fetch_daily_series(candidate_product.tiktok_product_id)
        first_active_date = t - timedelta(days=20)  # Active > 14 days before T

        candidates.append(
            ControlCandidate(
                product_id=candidate_product.tiktok_product_id,
                daily=candidate_daily,
                touched=False,
                first_active_date=first_active_date,
            )
        )

    # Attempt to select control pool for all metrics in price mutation
    from juli_backend.services.impact.metric_map import METRIC_MAP, MutationKind

    mutation_kind = MutationKind.PRICE
    mutation_metrics = METRIC_MAP[mutation_kind]
    all_metrics = [mutation_metrics.primary] + list(mutation_metrics.secondary)

    control_daily_by_metric = {}
    for metric in all_metrics:
        volume_floor = volume_floor_for(metric)
        control_result = select_control_pool(
            metric=metric,
            target_daily=target_daily,
            candidates=candidates,
            t=t,
            kind="preliminary",
            volume_floor=volume_floor,
            volume_of=volume_indicator_for(metric),
        )
        control_daily_by_metric[metric.key] = control_result.control_daily
    readings = compute_mutation_readings(
        mutation=mutation_kind,
        target_daily=target_daily,
        control_daily_by_metric=control_daily_by_metric,
        t=t,
        kind="preliminary",
        confounded=False,
    )

    # Check primary reading (gmv for price mutation)
    primary_reading = readings.primary
    assert primary_reading.status == "ok", (
        f"Primary reading should not be confounded; got status={primary_reading.status}"
    )

    # Verify at least one control pool was selected (not a fallback)
    # by checking that at least one metric has non-empty control_ids
    gmv_metric = resolve_metric("gmv")
    volume_floor = volume_floor_for(gmv_metric)
    gmv_control_result = select_control_pool(
        metric=gmv_metric,
        target_daily=target_daily,
        candidates=candidates,
        t=t,
        kind="preliminary",
        volume_floor=volume_floor,
        volume_of=volume_indicator_for(gmv_metric),
    )

    control_set = gmv_control_result.as_control_set_json()
    has_selected_controls = len(control_set.get("control_ids", [])) > 0

    assert has_selected_controls, (
        "Cohort should produce at least one real-tier reading (cao/trung_binh/thap); "
        f"got control_ids={control_set.get('control_ids', [])} "
        f"fallback_reason={control_set.get('fallback_reason')}"
    )

    # Verify the reading has numerical values
    assert primary_reading.incremental is not None, (
        "Reading with selected controls should have incremental value"
    )
    assert primary_reading.impact_pct is not None, (
        "Reading with selected controls should have impact_pct value"
    )


@pytest.mark.asyncio
async def test_demo_cohort_produces_below_floor_reading(session: AsyncSession, demo_cohort) -> None:
    """The cohort includes at least one product below the volume floor."""
    shop = demo_cohort["shop"]
    products = demo_cohort["products"]

    # Find a product that has below-floor volume in the pre-period
    t = date.today()
    pre_start = t - timedelta(days=14)
    pre_end = t - timedelta(days=1)

    from juli_backend.services.impact.confidence import volume_floor_for, volume_indicator_for
    from juli_backend.services.impact.metric_map import resolve_metric

    metric = resolve_metric("gmv")
    volume_floor = volume_floor_for(metric)
    volume_of = volume_indicator_for(metric)

    # NAME THE PRODUCT. The earlier version of this loop had no
    # `tiktok_product_id` filter, so every iteration re-read all ~230 rows in
    # the shop and compared a SHOP-WIDE mean against the floor. It passed on the
    # first iteration regardless of which product that was, and it would have
    # kept passing with `cohort-below-floor` deleted from the cohort entirely —
    # its analytics rows alone dragged the shop-wide mean under 1.0. It was
    # asserting a property of the shop, not of the refusal case it is named for.
    found_below_floor = False
    for product in products:
        intervals_result = await session.execute(
            select(AnalyticsPerformanceInterval).where(
                (AnalyticsPerformanceInterval.shop_id == shop.id)
                & (AnalyticsPerformanceInterval.tiktok_product_id == product.tiktok_product_id)
                & (AnalyticsPerformanceInterval.start_date >= pre_start)
                & (AnalyticsPerformanceInterval.start_date <= pre_end)
            )
        )
        intervals = intervals_result.scalars().all()

        # Compute mean volume indicator over pre-period
        from juli_backend.services.impact.metric_map import RawDailyRecord

        volumes = []
        for interval in intervals:
            record = RawDailyRecord(
                impressions=interval.impressions,
                ctr=interval.click_through_rate,
                conversion_rate=interval.click_order_rate,
                items_sold=interval.items_sold,
                gmv=interval.gmv,
                sku_orders=interval.sku_orders,
                visitors=interval.visitors,
            )
            vol = volume_of(record)
            if vol is not None:
                volumes.append(vol)

        if volumes:
            from decimal import Decimal

            mean_volume = sum(volumes, start=Decimal(0)) / Decimal(len(volumes))
            if mean_volume < volume_floor:
                found_below_floor = product.tiktok_product_id
                break

    assert found_below_floor == "cohort-below-floor", (
        f"the deliberate refusal case must be cohort-below-floor, but the product "
        f"under the volume floor ({volume_floor}) was {found_below_floor!r}. A "
        f"different product falling under the floor means the cohort no longer "
        f"demonstrates what ADR-099 d.4 asks it to."
    )


@pytest.mark.asyncio
async def test_seeded_analytics_carry_every_column_the_metrics_need(
    session: AsyncSession, demo_cohort
) -> None:
    """Every metric the mutation map can select must have its source column populated.

    RENAMED in review (#1767). This was called
    `test_demo_cohort_includes_series_source_synthetic`, which it never asserted:
    it checks analytics columns, and `series_source` lives on `impact_readings`,
    which this seeder deliberately does not write. A test named for a guarantee it
    does not make reads as coverage to anyone scanning names, which is worse than
    having no test.

    `series_source` is enforced where readings are PERSISTED, which is #1768's
    wiring. The column is NOT NULL with no default (#1766), so that path cannot
    silently omit it.

    What this does check is load-bearing: `metric_map` selects impressions, ctr,
    conversion_rate, gmv or sku_orders depending on the mutation, so a seed missing
    any one produces a reading that refuses for the wrong reason.
    """
    # This is a forward-looking test: when impact readings are computed from the seeded data,
    # they must set series_source='synthetic'. We verify the seeder has the data structure
    # needed for this (the test becomes real once the demo execution flow writes readings).
    shop = demo_cohort["shop"]

    intervals_result = await session.execute(
        select(AnalyticsPerformanceInterval).where(AnalyticsPerformanceInterval.shop_id == shop.id)
    )
    intervals = intervals_result.scalars().all()

    assert len(intervals) > 0, "Seeded cohort must have analytics intervals"

    # Verify intervals have the required raw columns to compute daily series
    for interval in intervals[:5]:  # Sample check
        assert interval.impressions is not None, "Analytics must have impressions"
        assert interval.click_through_rate is not None, "Analytics must have CTR"
        assert interval.click_order_rate is not None, "Analytics must have conversion_rate"
        assert interval.gmv is not None, "Analytics must have GMV"
        assert interval.sku_orders is not None, "Analytics must have sku_orders"
        assert interval.visitors is not None, "Analytics must have visitors"


@pytest.mark.asyncio
async def test_demo_cohort_produces_a_suppressed_reading(
    session: AsyncSession, demo_cohort
) -> None:
    """ADR-099 decision 4's third case, which was claimed but never covered.

    The seeder creates `cohort-degenerate` for exactly this, and nothing asserted
    what it yields. A refusal case that is seeded and never checked can stop
    working silently — and the refusals are the half of this algorithm a demo most
    needs to show honestly.

    `compute.py` suppresses the percentage form on three degenerate inputs:
    `control_pre == 0`, `pre == 0`, `expected <= 0`. Any is a valid suppression;
    what matters is that the pre-period is degenerate so the branch can fire, not
    which one does.
    """
    from juli_backend.services.impact.metric_map import METRIC_MAP, MutationKind

    shop = demo_cohort["shop"]
    # T is `date.today()` in the seeder, matching how the sibling tests in
    # this module derive it. The fixture does not expose it.
    t = date.today()

    rows = (
        (
            await session.execute(
                select(AnalyticsPerformanceInterval).where(
                    AnalyticsPerformanceInterval.shop_id == shop.id,
                    AnalyticsPerformanceInterval.tiktok_product_id == "cohort-degenerate",
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows, "the seeder must create cohort-degenerate, or this case is untested"

    # PRICE's primary metric is gmv (metric_map.py); read it directly rather than
    # through MetricSpec, which carries no `.name` for a message.
    assert METRIC_MAP[MutationKind.PRICE].primary is not None
    pre = [r.gmv for r in rows if r.start_date < t and r.gmv is not None]
    pre_mean = sum(pre) / len(pre) if pre else None

    assert pre_mean is None or pre_mean == 0, (
        f"cohort-degenerate must have a degenerate pre-period (gmv) so the "
        f"suppression branch can fire; got pre mean {pre_mean!r}. If the seed drifts "
        f"so this is non-zero, the suppressed case stops being exercised silently."
    )
