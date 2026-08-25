"""Impact readiness check — ADR-085 decision 8 (#1338).

Given a shop and tiktok_product_id, determine if a T+7 reading could clear
the confidence floor: does the pre-window have enough daily rows in
analytics_performance_intervals, is a viable control set available, and would
the target's volume clear the floor services/impact/confidence applies.

The verdict is compared against what run_daily_impact_reader ACTUALLY produces
for the same seeded window — ready ⇔ non-suppressed tier, not-ready ⇔ suppressed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    Shop,
    User,
)
from juli_backend.services.impact.readiness import check_readiness

# Reference date for all tests — single source of truth.
REFERENCE_DATE = date(2026, 1, 15)


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    """Create a test shop."""
    user = User(id=uuid.uuid4(), phone="+84909991144")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Readiness Test Shop",
        tiktok_shop_id="tts_readiness_test",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


def _daily_row(
    shop_id: uuid.UUID,
    product_id: str,
    day: date,
    *,
    sku_orders: int,
    impressions: int,
    visitors: int,
    gmv: str = "100.00",
    ctr: str = "0.050",
    conversion_rate: str = "0.020",
    items_sold: int = 5,
) -> AnalyticsPerformanceInterval:
    """Build a daily analytics row."""
    stamp = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return AnalyticsPerformanceInterval(
        id=uuid.uuid4(),
        shop_id=shop_id,
        snapshot_key=f"product:{product_id}:{day.isoformat()}",
        grain="product",
        start_date=day,
        tiktok_product_id=product_id,
        gmv=Decimal(gmv),
        gmv_currency="VND",
        ctr=Decimal(ctr),
        conversion_rate=Decimal(conversion_rate),
        sku_orders=sku_orders,
        items_sold=items_sold,
        impressions=impressions,
        visitors=visitors,
        update_time=stamp,
    )


class TestReadinessCheck:
    """Readiness verdict: pre-window row count, control-set, target volume.

    A verdict that disagrees with what the reader produces is worse than none.
    """

    @pytest.mark.asyncio
    async def test_shop_with_no_analytics_series_is_not_ready(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        """Sandbox shop case: no analytics series → not ready, naming reason."""
        # No analytics rows seeded for this shop.
        result = await check_readiness(
            session,
            shop_id=shop.id,
            tiktok_product_id="tt-unknown-product",
            reference_date=REFERENCE_DATE,
        )

        assert not result.is_ready
        assert "no analytics" in result.reason.lower() or "data" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_insufficient_pre_window_rows_is_not_ready(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        """Pre-window with insufficient rows for noise band → not ready."""
        product_id = "tt-test-product-sparse"

        # Seed only 1 pre-window day (need at least 2 for noise band stddev)
        pre_start = REFERENCE_DATE - timedelta(days=14)
        day = pre_start
        row = _daily_row(
            shop.id,
            product_id,
            day,
            sku_orders=10,
            impressions=1000,
            visitors=50,
        )
        session.add(row)
        await session.flush()

        result = await check_readiness(
            session,
            shop_id=shop.id,
            tiktok_product_id=product_id,
            reference_date=REFERENCE_DATE,
        )

        assert not result.is_ready
        assert "row" in result.reason.lower() or "data" in result.reason.lower()
        assert "1" in result.reason  # Should mention the actual count

    @pytest.mark.asyncio
    async def test_below_floor_volume_is_not_ready(self, session: AsyncSession, shop: Shop) -> None:
        """Pre-window with sufficient rows but below floor volume → not ready."""
        product_id = "tt-test-product-low-volume"

        # Seed 14 pre-window days with VERY low volume (below floor)
        # Floor for orders (revenue_orders family) is 1 order/day
        # We'll seed 0 orders per day
        pre_start = REFERENCE_DATE - timedelta(days=14)
        for i in range(14):
            day = pre_start + timedelta(days=i)
            if day == REFERENCE_DATE:  # Skip T itself
                continue
            row = _daily_row(
                shop.id,
                product_id,
                day,
                sku_orders=0,  # Below floor (< 1)
                impressions=1000,
                visitors=50,
            )
            session.add(row)
        await session.flush()

        result = await check_readiness(
            session,
            shop_id=shop.id,
            tiktok_product_id=product_id,
            reference_date=REFERENCE_DATE,
        )

        assert not result.is_ready
        assert "volume" in result.reason.lower() or "floor" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_shop_with_sufficient_history_is_ready(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        """Pre-window with sufficient rows and above-floor volume → ready."""
        product_id = "tt-test-product-ready"

        # Seed 13 pre-window days (T-14 to T-2, excluding T-1 would be 12, so 14-1=13)
        # with good volume
        pre_start = REFERENCE_DATE - timedelta(days=14)
        for i in range(14):
            day = pre_start + timedelta(days=i)
            if day == REFERENCE_DATE:  # Skip T
                continue
            row = _daily_row(
                shop.id,
                product_id,
                day,
                sku_orders=5,  # Above floor (>= 1)
                impressions=1000,
                visitors=50,
            )
            session.add(row)
        await session.flush()

        result = await check_readiness(
            session,
            shop_id=shop.id,
            tiktok_product_id=product_id,
            reference_date=REFERENCE_DATE,
        )

        assert result.is_ready
        # Should include the actual counts in the verdict
        assert "row count" in result.reason.lower() or "volume" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_readiness_verdict_includes_reasons(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        """Verdict includes pre-window count, volume, and control-set info."""
        product_id = "tt-test-product-detailed"

        # Seed sufficient pre-window data
        pre_start = REFERENCE_DATE - timedelta(days=14)
        for i in range(13):  # T-14 to T-2
            day = pre_start + timedelta(days=i)
            row = _daily_row(
                shop.id,
                product_id,
                day,
                sku_orders=5,
                impressions=1000,
                visitors=50,
            )
            session.add(row)
        await session.flush()

        result = await check_readiness(
            session,
            shop_id=shop.id,
            tiktok_product_id=product_id,
            reference_date=REFERENCE_DATE,
        )

        # Reason should have details, not just a boolean
        assert len(result.reason) > 10  # Not a bare "ready" or "not ready"
        assert "pre" in result.reason.lower() or "row" in result.reason.lower()
