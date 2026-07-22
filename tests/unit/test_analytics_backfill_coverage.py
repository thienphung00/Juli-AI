"""P2-9-9 (#471) — analytics backfill coverage reporter + exit thresholds."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import AnalyticsPerformanceInterval, Shop, User
from juli_backend.repositories.repos import AnalyticsBackfillPartitionsRepo
from juli_backend.services.analytics_backfill.coverage import (
    PRODUCT_COVERAGE_THRESHOLD,
    REVENUE_LIVE_COVERAGE_THRESHOLD,
    BucketCoverageResult,
    generate_coverage_report,
    meets_coverage_threshold,
)
from juli_backend.services.analytics_backfill.orchestrator import BACKFILL_WINDOW_START


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84909996655")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Coverage Shop",
        tiktok_shop_id="tts_coverage",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


def _shop_row(
    shop_id: uuid.UUID,
    partition_date: date,
    *,
    gmv: Decimal | None = None,
    orders_count: int | None = None,
    live_hours: Decimal | None = None,
    live_sessions: int | None = None,
) -> AnalyticsPerformanceInterval:
    return AnalyticsPerformanceInterval(
        id=uuid.uuid4(),
        shop_id=shop_id,
        snapshot_key=f"shop|{partition_date}|{partition_date}||||",
        grain="shop",
        start_date=partition_date,
        end_date=partition_date,
        gmv=gmv,
        orders_count=orders_count,
        live_hours=live_hours,
        live_sessions=live_sessions,
        update_time=datetime.now(tz=UTC),
    )


def _product_row(shop_id: uuid.UUID, partition_date: date, product_id: str) -> AnalyticsPerformanceInterval:
    return AnalyticsPerformanceInterval(
        id=uuid.uuid4(),
        shop_id=shop_id,
        snapshot_key=f"product|{partition_date}|{partition_date}|{product_id}|||",
        grain="product",
        start_date=partition_date,
        end_date=partition_date,
        tiktok_product_id=product_id,
        gmv=Decimal("10.00"),
        update_time=datetime.now(tz=UTC),
    )


class TestCoverageThresholdRounding:
    def test_exact_fraction_at_95_percent_passes(self) -> None:
        assert meets_coverage_threshold(950, 1000, REVENUE_LIVE_COVERAGE_THRESHOLD) is True

    def test_949_of_1000_fails_revenue_live_gate(self) -> None:
        assert meets_coverage_threshold(949, 1000, REVENUE_LIVE_COVERAGE_THRESHOLD) is False

    def test_product_gate_passes_at_90_percent(self) -> None:
        assert meets_coverage_threshold(9, 10, PRODUCT_COVERAGE_THRESHOLD) is True
        assert meets_coverage_threshold(8, 10, PRODUCT_COVERAGE_THRESHOLD) is False


class TestGenerateCoverageReport:
    pytestmark = pytest.mark.asyncio

    async def test_exit_ready_when_revenue_live_and_product_gates_pass(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        start = date(2026, 3, 16)
        end = date(2026, 3, 25)
        rows: list[AnalyticsPerformanceInterval] = []
        for offset in range(10):
            d = start + timedelta(days=offset)
            rows.append(
                _shop_row(
                    shop.id,
                    d,
                    gmv=Decimal("100.00"),
                    live_hours=Decimal("1.0"),
                    live_sessions=1,
                )
            )
            rows.append(_product_row(shop.id, d, f"prod-{offset}"))
        session.add_all(rows)
        await session.flush()

        report = await generate_coverage_report(
            session,
            shop_id=shop.id,
            start_date=start,
            end_date=end,
        )

        assert report.days_total == 10
        assert report.revenue_live_gate is True
        assert report.product_gate is True
        assert report.exit_ready is True

        revenue_live = next(b for b in report.buckets if b.bucket == "revenue_live")
        product = next(b for b in report.buckets if b.bucket == "product")
        assert revenue_live.coverage_pct == pytest.approx(100.0)
        assert product.coverage_pct == pytest.approx(100.0)

    async def test_revenue_live_gate_true_at_950_of_1000_days(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        start = BACKFILL_WINDOW_START
        end = start + timedelta(days=999)
        rows = [
            _shop_row(
                shop.id,
                start + timedelta(days=offset),
                gmv=Decimal("1.00"),
                live_hours=Decimal("1.0"),
                live_sessions=1,
            )
            for offset in range(950)
        ]
        session.add_all(rows)
        await session.flush()

        report = await generate_coverage_report(
            session,
            shop_id=shop.id,
            start_date=start,
            end_date=end,
        )

        revenue_live = next(b for b in report.buckets if b.bucket == "revenue_live")
        assert revenue_live.days_present == 950
        assert revenue_live.days_total == 1000
        assert revenue_live.coverage_pct == pytest.approx(95.0)
        assert report.revenue_live_gate is True

    async def test_revenue_live_gate_false_at_949_of_1000_days(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        start = BACKFILL_WINDOW_START
        end = start + timedelta(days=999)
        rows = [
            _shop_row(
                shop.id,
                start + timedelta(days=offset),
                gmv=Decimal("1.00"),
                live_hours=Decimal("1.0"),
                live_sessions=1,
            )
            for offset in range(949)
        ]
        session.add_all(rows)
        await session.flush()

        report = await generate_coverage_report(
            session,
            shop_id=shop.id,
            start_date=start,
            end_date=end,
        )

        revenue_live = next(b for b in report.buckets if b.bucket == "revenue_live")
        assert revenue_live.days_present == 949
        assert revenue_live.coverage_pct == pytest.approx(94.9, rel=1e-3)
        assert report.revenue_live_gate is False
        assert report.exit_ready is False

    async def test_product_gate_passes_independently_when_revenue_live_fails(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        start = date(2026, 4, 1)
        end = date(2026, 4, 10)
        rows: list[AnalyticsPerformanceInterval] = []
        for offset in range(10):
            d = start + timedelta(days=offset)
            if offset < 9:
                rows.append(
                    _shop_row(
                        shop.id,
                        d,
                        gmv=Decimal("5.00"),
                        live_hours=Decimal("1.0"),
                        live_sessions=1,
                    )
                )
            rows.append(_product_row(shop.id, d, f"prod-{offset}"))
        session.add_all(rows)
        await session.flush()

        report = await generate_coverage_report(
            session,
            shop_id=shop.id,
            start_date=start,
            end_date=end,
        )

        assert report.product_gate is True
        assert report.revenue_live_gate is False
        assert report.exit_ready is False

    async def test_missing_dates_include_incomplete_partitions(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        start = date(2026, 5, 1)
        end = date(2026, 5, 3)
        repo = AnalyticsBackfillPartitionsRepo(session)
        gap_date = date(2026, 5, 2)
        await repo.mark_failed(shop.id, "revenue", gap_date, "timeout", retryable=True)
        await repo.mark_failed(shop.id, "product", gap_date, "timeout", retryable=True)

        session.add_all([
            _shop_row(
                shop.id,
                date(2026, 5, 1),
                gmv=Decimal("1.00"),
                live_hours=Decimal("1.0"),
                live_sessions=1,
            ),
            _shop_row(
                shop.id,
                date(2026, 5, 3),
                gmv=Decimal("1.00"),
                live_hours=Decimal("1.0"),
                live_sessions=1,
            ),
            _product_row(shop.id, date(2026, 5, 1), "p1"),
            _product_row(shop.id, date(2026, 5, 3), "p3"),
        ])
        await session.flush()

        report = await generate_coverage_report(
            session,
            shop_id=shop.id,
            start_date=start,
            end_date=end,
        )

        revenue = next(b for b in report.buckets if b.bucket == "revenue")
        product = next(b for b in report.buckets if b.bucket == "product")
        assert gap_date.isoformat() in revenue.missing_dates
        assert gap_date.isoformat() in product.missing_dates

        incomplete_revenue = await repo.list_incomplete(
            shop.id, "revenue", start, end
        )
        incomplete_product = await repo.list_incomplete(
            shop.id, "product", start, end
        )
        assert {row.partition_date.isoformat() for row in incomplete_revenue} <= set(
            revenue.missing_dates
        )
        assert {row.partition_date.isoformat() for row in incomplete_product} <= set(
            product.missing_dates
        )


def test_bucket_coverage_result_is_frozen() -> None:
    row = BucketCoverageResult(
        bucket="revenue",
        days_present=1,
        days_total=2,
        coverage_pct=50.0,
        missing_dates=("2026-03-17",),
        gate_pass=False,
    )
    with pytest.raises(AttributeError):
        row.days_present = 2  # type: ignore[misc]
