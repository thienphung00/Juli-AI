"""Demo cohort seeding for impact readings — issue #1767, ADR-099 decisions 3 and 4.

This module extends the demo tenant seed (#1312) to seed a cohort that the control pool
will accept AND includes deliberate refusal cases (below_floor, suppressed).

The seeded cohort includes:
1. A target product (the one being mutated)
2. 5+ candidate products with high correlation to the target
3. Analytics data from T-14 through T+14 (where T is the mutation date: today)

Requirements satisfied:
- Minimum 3 candidates (control pool MIN_CANDIDATES) → 5+ to allow selection
- Each sibling active >= 14 days before T (control pool MIN_ACTIVE_DAYS)
- Target and siblings have complete pre-period data for correlation
- Mean correlation >= 0.2 across top-K siblings (one reading clears this)
- Pre-period volume >= family floor on at least one sibling (one reading clears)
- Deliberate cases below floor (one reading fails) and suppressed (edge case)

Seeding strategy:
- Derive data shapes from Fujiwa's real 8,200 analytics_performance_intervals rows
- Use realistic volume distributions and co-movement patterns
- Build sibling series that correlate with target (T is for Pearson, not randomness)
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database import Product, Shop, User
from juli_backend.models.models import AnalyticsPerformanceInterval


def _get_demo_shop_id() -> str:
    """Retrieve DEMO_SHOP_ID from environment; fail loudly if unset."""
    shop_id = os.getenv("DEMO_SHOP_ID", "").strip()
    if not shop_id:
        raise KeyError(
            "DEMO_SHOP_ID environment variable is required but not set. "
            "Set it to a UUID string before calling seed_demo_cohort_for_impact."
        )
    return shop_id


async def seed_demo_cohort_for_impact(session: AsyncSession) -> None:
    """Seed a demo cohort that the impact control pool will accept + refusal cases.

    Creates a target product and 5+ sibling products with analytics data designed
    to satisfy (and deliberately fail) the control pool requirements.

    The cohort seed is idempotent: running twice produces one shop with one
    consistent product set.

    Args:
        session: AsyncSession for database operations.

    Raises:
        KeyError: if DEMO_SHOP_ID environment variable is not set.
    """
    demo_shop_id_str = _get_demo_shop_id()
    demo_shop_id = uuid.UUID(demo_shop_id_str)

    # Derive demo user ID deterministically from shop ID
    demo_user_uuid_int = uuid.UUID("12345678-1234-5678-1234-567812345678").int
    demo_user_id = uuid.UUID(int=(int(demo_shop_id) ^ demo_user_uuid_int))

    # Naive UTC, deliberately. Every timestamp column this seeder writes —
    # users, shops, products, analytics_performance_intervals — is
    # `timestamp without time zone`, and asyncpg refuses a tz-aware value for
    # one with "can't subtract offset-naive and offset-aware datetimes". SQLite
    # accepts it, which is why the tests beside this file did not notice: the
    # seeder raised on its first INSERT against the Postgres it actually has to
    # run on. See tests/integration/test_demo_cohort_seeds_on_postgres.py.
    now = datetime.now(UTC).replace(tzinfo=None)

    # === Create demo user (idempotent) ===
    stmt = select(User).where(User.id == demo_user_id)
    existing_user = await session.scalar(stmt)

    if not existing_user:
        demo_user = User(
            id=demo_user_id,
            phone="+84-demo-cohort",
            display_name="Demo Cohort Tenant",
            created_at=now,
            updated_at=now,
        )
        session.add(demo_user)
        await session.flush()

    # === Create demo shop (idempotent) ===
    shop_stmt = select(Shop).where(Shop.id == demo_shop_id)
    existing_shop = await session.scalar(shop_stmt)

    if not existing_shop:
        demo_shop = Shop(
            id=demo_shop_id,
            user_id=demo_user_id,
            shop_name="Demo Cohort Shop",
            tiktok_shop_id=None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(demo_shop)
        await session.flush()

    # === Seed demo products for control pool (idempotent by tiktok_product_id) ===
    # The cohort consists of:
    # 1. A target product (e.g., "cohort-target") that we'll measure
    # 2. Five candidate products that correlate with the target
    # 3. One deliberately below-floor candidate
    # 4. One with degenerate data (for suppression)

    cohort_products = [
        {
            "tiktok_product_id": "cohort-target",
            "title": "Target Product",
            "name": "Target Product",
            "category": "Electronics",
            "price": 99.99,
            "inventory": 100,
            "status": "active",
            "role": "target",  # This one gets the mutation
        },
        {
            "tiktok_product_id": "cohort-candidate-1",
            "title": "High-Correlation Sibling 1",
            "name": "Sibling 1",
            "category": "Electronics",
            "price": 89.99,
            "inventory": 100,
            "status": "active",
            "role": "high_corr",  # High correlation with target
        },
        {
            "tiktok_product_id": "cohort-candidate-2",
            "title": "High-Correlation Sibling 2",
            "name": "Sibling 2",
            "category": "Electronics",
            "price": 79.99,
            "inventory": 100,
            "status": "active",
            "role": "high_corr",
        },
        {
            "tiktok_product_id": "cohort-candidate-3",
            "title": "High-Correlation Sibling 3",
            "name": "Sibling 3",
            "category": "Electronics",
            "price": 69.99,
            "inventory": 100,
            "status": "active",
            "role": "high_corr",
        },
        {
            "tiktok_product_id": "cohort-candidate-4",
            "title": "High-Correlation Sibling 4",
            "name": "Sibling 4",
            "category": "Electronics",
            "price": 59.99,
            "inventory": 100,
            "status": "active",
            "role": "high_corr",
        },
        {
            "tiktok_product_id": "cohort-candidate-5",
            "title": "High-Correlation Sibling 5",
            "name": "Sibling 5",
            "category": "Electronics",
            "price": 49.99,
            "inventory": 100,
            "status": "active",
            "role": "high_corr",
        },
        {
            "tiktok_product_id": "cohort-below-floor",
            "title": "Below Floor Volume",
            "name": "Below Floor",
            "category": "Electronics",
            "price": 39.99,
            "inventory": 100,
            "status": "active",
            "role": "below_floor",  # Will have insufficient volume
        },
        {
            "tiktok_product_id": "cohort-degenerate",
            "title": "Degenerate Data",
            "name": "Degenerate",
            "category": "Electronics",
            "price": 29.99,
            "inventory": 100,
            "status": "active",
            "role": "degenerate",  # Will have edge-case data
        },
    ]

    for prod_data in cohort_products:
        product_stmt = select(Product).where(
            (Product.shop_id == demo_shop_id)
            & (Product.tiktok_product_id == prod_data["tiktok_product_id"])
        )
        existing_product = await session.scalar(product_stmt)

        if not existing_product:
            product = Product(
                id=uuid.uuid4(),
                shop_id=demo_shop_id,
                tiktok_product_id=prod_data["tiktok_product_id"],
                title=prod_data["title"],
                name=prod_data["name"],
                category=prod_data["category"],
                price=prod_data["price"],
                price_currency="USD",
                inventory=prod_data["inventory"],
                audit_status="approved",
                status=prod_data["status"],
                revenue=Decimal(0),
                units_sold=0,
                update_time=now,
                created_at=now,
                updated_at=now,
            )
            session.add(product)

    await session.flush()

    # === Seed analytics data covering T-14 through T+14 ===
    # T = today (the mutation execution date)
    # Pre-window: T-14 to T-1
    # Post-window (preliminary): T+1 to T+7
    # Post-window (final): T+1 to T+14
    #
    # We need to build series that:
    # 1. Have high correlation (>0.2 for at least 5 siblings)
    # 2. Have sufficient volume (>= floor, which is 1 order/day for revenue family)
    # 3. Deliberately fail some:
    #    - One product below the floor (pre-period volume < floor)
    #    - One degenerate case (e.g., pre=0 or expected<=0 for suppression)

    t = datetime.now(UTC).date()
    start_date = t - timedelta(days=14)
    end_date = t + timedelta(days=14)

    # === Build analytics data ===
    # Strategy: Use realistic patterns derived from Fujiwa data
    # - Target: increasing trend (the effect of the mutation)
    # - High-corr siblings: co-moving with target (high Pearson correlation)
    # - Below-floor: consistently low volume
    # - Degenerate: very flat or zero pre-period

    # Base patterns (from Fujiwa distribution observations)
    base_gmv = Decimal("100")  # Daily GMV baseline
    base_impressions = Decimal("500")  # Baseline impressions/day
    base_visitors = Decimal("50")  # Baseline visitors/day
    base_orders = Decimal("2")  # 2 orders/day baseline (well above floor of 1)
    base_ctr = Decimal("0.05")  # 5% CTR
    base_conversion = Decimal("0.04")  # 4% conversion

    all_intervals = []

    # Generate a shared trend component for correlation
    # This ensures all products move together (high correlation)
    daily_trend = {}
    # Use a deterministic "pseudo-random" pattern based on day offset
    # This creates realistic daily variation while being reproducible
    for day_offset in range((end_date - start_date).days + 1):
        current_date = start_date + timedelta(days=day_offset)
        days_from_t = (current_date - t).days
        # Shared daily variation: all products respond to the same market movement
        # Use day_offset to create deterministic but varying trend
        day_sine_wave = Decimal(1) + (Decimal(day_offset % 7) - Decimal(3)) * Decimal("0.03")
        # Pre-period: flat baseline with daily noise
        # Post-period: increase (effect of the mutation)
        if days_from_t < 0:
            daily_trend[current_date] = day_sine_wave  # Pre-period with daily variation
        else:
            growth_factor = Decimal(1) + (Decimal(days_from_t + 1) * Decimal("0.08"))
            daily_trend[current_date] = day_sine_wave * growth_factor  # Growing post-period

    for day_offset in range((end_date - start_date).days + 1):
        current_date = start_date + timedelta(days=day_offset)
        days_from_t = (current_date - t).days

        # === Target product: showing growth post-mutation ===
        trend = daily_trend[current_date]

        target_gmv = base_gmv * trend
        target_impressions = base_impressions * trend
        target_visitors = base_visitors * trend
        target_orders = base_orders * trend
        target_ctr = base_ctr
        target_conversion = base_conversion

        interval = AnalyticsPerformanceInterval(
            id=uuid.uuid4(),
            shop_id=demo_shop_id,
            snapshot_key=f"cohort-target-{current_date}",
            grain="daily",
            start_date=current_date,
            end_date=current_date,
            tiktok_product_id="cohort-target",  # Add product ID
            gmv=float(target_gmv),
            gmv_currency="USD",
            click_through_rate=float(target_ctr),
            click_order_rate=float(target_conversion),
            visitors=int(target_visitors),
            impressions=int(target_impressions),
            sku_orders=int(target_orders),
            items_sold=int(target_orders * 2),  # 2 items per order
            conversion_rate=float(target_conversion),
            active_products=1,
            update_time=now,
            created_at=now,
            updated_at=now,
        )
        all_intervals.append((interval, "cohort-target"))

        # === High-correlation siblings: co-move with target ===
        for sibling_idx in range(1, 6):
            sibling_id = f"cohort-candidate-{sibling_idx}"

            # Each sibling has a fixed scale factor but follows the same trend
            # This ensures high correlation: they all move together
            sibling_scale = Decimal("0.8") + (Decimal(sibling_idx) * Decimal("0.03"))
            sibling_gmv = base_gmv * sibling_scale * trend
            sibling_impressions = base_impressions * sibling_scale * trend
            sibling_visitors = base_visitors * sibling_scale * trend
            sibling_orders = base_orders * sibling_scale * trend

            interval = AnalyticsPerformanceInterval(
                id=uuid.uuid4(),
                shop_id=demo_shop_id,
                snapshot_key=f"{sibling_id}-{current_date}",
                grain="daily",
                start_date=current_date,
                end_date=current_date,
                tiktok_product_id=sibling_id,  # Add product ID
                gmv=float(sibling_gmv),
                gmv_currency="USD",
                click_through_rate=float(target_ctr),
                click_order_rate=float(target_conversion),
                visitors=int(sibling_visitors),
                impressions=int(sibling_impressions),
                sku_orders=int(sibling_orders),
                items_sold=int(sibling_orders * 2),
                conversion_rate=float(target_conversion),
                active_products=1,
                update_time=now,
                created_at=now,
                updated_at=now,
            )
            all_intervals.append((interval, sibling_id))

        # === Below-floor product: consistently below volume floor ===
        # Floor is 1 order/day for revenue family, so use 0 orders
        interval = AnalyticsPerformanceInterval(
            id=uuid.uuid4(),
            shop_id=demo_shop_id,
            snapshot_key=f"cohort-below-floor-{current_date}",
            grain="daily",
            start_date=current_date,
            end_date=current_date,
            tiktok_product_id="cohort-below-floor",  # Add product ID
            gmv=0.0,  # No sales
            gmv_currency="USD",
            click_through_rate=float(base_ctr),
            click_order_rate=0.0,
            visitors=0,  # No visitors
            impressions=50,  # Some impressions but no conversions
            sku_orders=0,  # Zero orders — below the floor
            items_sold=0,
            conversion_rate=0.0,
            active_products=1,
            update_time=now,
            created_at=now,
            updated_at=now,
        )
        all_intervals.append((interval, "cohort-below-floor"))

        # === Degenerate product: zero pre-period for suppression ===
        # Pre-period (days_from_t < 0): zero volume
        # Post-period: some activity (so it's not confounded, but suppressed pre)
        if days_from_t < 0:
            # Pre-period: flat zero
            deg_gmv = Decimal(0)
            deg_impressions = Decimal(0)
            deg_visitors = Decimal(0)
            deg_orders = Decimal(0)
        else:
            # Post-period: some activity
            deg_gmv = base_gmv * Decimal("0.5")
            deg_impressions = base_impressions * Decimal("0.5")
            deg_visitors = base_visitors * Decimal("0.5")
            deg_orders = base_orders * Decimal("0.5")

        interval = AnalyticsPerformanceInterval(
            id=uuid.uuid4(),
            shop_id=demo_shop_id,
            snapshot_key=f"cohort-degenerate-{current_date}",
            grain="daily",
            start_date=current_date,
            end_date=current_date,
            tiktok_product_id="cohort-degenerate",  # Add product ID
            gmv=float(deg_gmv),
            gmv_currency="USD",
            click_through_rate=float(base_ctr),
            click_order_rate=float(base_conversion) if deg_orders > 0 else 0.0,
            visitors=int(deg_visitors),
            impressions=int(deg_impressions),
            sku_orders=int(deg_orders),
            items_sold=int(deg_orders * 2),
            conversion_rate=float(base_conversion) if deg_visitors > 0 else 0.0,
            active_products=1,
            update_time=now,
            created_at=now,
            updated_at=now,
        )
        all_intervals.append((interval, "cohort-degenerate"))

    # === Add all intervals to session (idempotent check per day) ===
    for interval, product_key in all_intervals:
        # Check if this interval already exists
        existing_stmt = select(AnalyticsPerformanceInterval).where(
            (AnalyticsPerformanceInterval.shop_id == demo_shop_id)
            & (AnalyticsPerformanceInterval.snapshot_key == interval.snapshot_key)
        )
        existing = await session.scalar(existing_stmt)
        if not existing:
            session.add(interval)

    await session.commit()
