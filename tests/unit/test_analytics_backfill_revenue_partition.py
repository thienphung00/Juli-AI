"""P2-9-4 (#466) — revenue-core partition backfill for one calendar day."""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.integrations.tiktok.exceptions import RateLimitError
from juli_backend.integrations.tiktok.mapping import analytics_snapshot_key
from juli_backend.integrations.tiktok.resources.analytics import AnalyticsResource
from juli_backend.models.models import AnalyticsPerformanceInterval, Shop, User
from juli_backend.repositories.repos import (
    AnalyticsBackfillPartitionsRepo,
    AnalyticsPerformanceRepo,
)
from juli_backend.services.analytics_backfill.budget import begin_run
from juli_backend.services.analytics_backfill.revenue_partition import (
    backfill_revenue_partition,
    derive_aov,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "analytics_backfill" / "revenue"
PARTITION_DATE = date(2026, 7, 13)
SYNCED_AT = 1_784_192_270


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84909998878")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Revenue Partition Shop",
        tiktok_shop_id="tts_revenue_partition",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


def _analytics_mock(
    *,
    shop_performance: dict | None = None,
    per_hour: dict | None = None,
    shop_error: Exception | None = None,
    per_hour_error: Exception | None = None,
) -> MagicMock:
    resource = MagicMock(spec=AnalyticsResource)
    if shop_error is not None:
        resource.get_shop_performance.side_effect = shop_error
    else:
        resource.get_shop_performance.return_value = shop_performance or _load_fixture(
            "a36_shop_performance.json"
        )
    if per_hour_error is not None:
        resource.get_shop_performance_per_hour.side_effect = per_hour_error
    else:
        resource.get_shop_performance_per_hour.return_value = per_hour or _load_fixture(
            "a37_shop_performance_per_hour.json"
        )
    return resource


@pytest.mark.asyncio
class TestBackfillRevenuePartition:
    async def test_fixture_backfill_upserts_shop_grain_row(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        resource = _analytics_mock()
        partitions_repo = AnalyticsBackfillPartitionsRepo(session)
        performance_repo = AnalyticsPerformanceRepo(session)
        budget = begin_run(max_attempts=10, hard_limit=10)

        status = await backfill_revenue_partition(
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            analytics_resource=resource,
            partitions_repo=partitions_repo,
            performance_repo=performance_repo,
            budget=budget,
            synced_at=SYNCED_AT,
        )

        assert status == "complete"
        resource.get_shop_performance.assert_called_once_with(
            start_date_ge="2026-07-13",
            end_date_lt="2026-07-14",
        )
        resource.get_shop_performance_per_hour.assert_called_once_with(date="2026-07-13")

        expected_key = analytics_snapshot_key(
            grain="shop",
            start_date="2026-07-13",
            end_date="2026-07-14",
        )
        stmt = select(AnalyticsPerformanceInterval).where(
            AnalyticsPerformanceInterval.shop_id == shop.id,
            AnalyticsPerformanceInterval.snapshot_key == expected_key,
        )
        rows = list((await session.execute(stmt)).scalars().all())

        assert len(rows) == 1
        row = rows[0]
        assert row.grain == "shop"
        assert row.start_date == PARTITION_DATE
        assert row.gmv == Decimal("6408074.00")
        assert row.gmv_currency == "VND"
        assert row.orders_count == 26
        assert row.customers == 23
        assert await partitions_repo.is_complete(shop.id, "revenue", PARTITION_DATE)

    async def test_skips_partner_calls_when_partition_complete(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        resource = _analytics_mock()
        partitions_repo = AnalyticsBackfillPartitionsRepo(session)
        performance_repo = AnalyticsPerformanceRepo(session)
        budget = begin_run(max_attempts=10, hard_limit=10)

        await partitions_repo.mark_complete(shop.id, "revenue", PARTITION_DATE)

        status = await backfill_revenue_partition(
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            analytics_resource=resource,
            partitions_repo=partitions_repo,
            performance_repo=performance_repo,
            budget=budget,
            synced_at=SYNCED_AT,
        )

        assert status == "skipped"
        resource.get_shop_performance.assert_not_called()
        resource.get_shop_performance_per_hour.assert_not_called()
        assert budget.attempts == 0

    async def test_partner_rate_limit_leaves_partition_incomplete(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        resource = _analytics_mock(
            shop_error=RateLimitError(100005, "Too many requests", request_id="req-1")
        )
        partitions_repo = AnalyticsBackfillPartitionsRepo(session)
        performance_repo = AnalyticsPerformanceRepo(session)
        budget = begin_run(max_attempts=10, hard_limit=10)

        status = await backfill_revenue_partition(
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            analytics_resource=resource,
            partitions_repo=partitions_repo,
            performance_repo=performance_repo,
            budget=budget,
            synced_at=SYNCED_AT,
        )

        assert status == "failed"
        assert await partitions_repo.is_complete(shop.id, "revenue", PARTITION_DATE) is False
        incomplete = await partitions_repo.list_incomplete(
            shop.id, "revenue", PARTITION_DATE, PARTITION_DATE
        )
        assert len(incomplete) == 1
        assert incomplete[0].status == "failed"
        assert budget.failures == 1

    async def test_upsert_is_idempotent_on_snapshot_key(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        resource = _analytics_mock()
        partitions_repo = AnalyticsBackfillPartitionsRepo(session)
        performance_repo = AnalyticsPerformanceRepo(session)
        budget = begin_run(max_attempts=20, hard_limit=20)

        await backfill_revenue_partition(
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            analytics_resource=resource,
            partitions_repo=partitions_repo,
            performance_repo=performance_repo,
            budget=budget,
            synced_at=SYNCED_AT,
        )

        await partitions_repo.mark_failed(
            shop.id, "revenue", PARTITION_DATE, "forced retry", retryable=True
        )

        await backfill_revenue_partition(
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            analytics_resource=resource,
            partitions_repo=partitions_repo,
            performance_repo=performance_repo,
            budget=budget,
            synced_at=SYNCED_AT + 1,
        )

        count_stmt = select(func.count()).select_from(AnalyticsPerformanceInterval).where(
            AnalyticsPerformanceInterval.shop_id == shop.id,
            AnalyticsPerformanceInterval.grain == "shop",
            AnalyticsPerformanceInterval.start_date == PARTITION_DATE,
        )
        assert (await session.execute(count_stmt)).scalar_one() == 1

    async def test_section_b_write_apis_never_invoked(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        resource = _analytics_mock()
        partitions_repo = AnalyticsBackfillPartitionsRepo(session)
        performance_repo = AnalyticsPerformanceRepo(session)
        budget = begin_run(max_attempts=10, hard_limit=10)

        await backfill_revenue_partition(
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            analytics_resource=resource,
            partitions_repo=partitions_repo,
            performance_repo=performance_repo,
            budget=budget,
            synced_at=SYNCED_AT,
        )

        read_methods = {
            "get_shop_performance",
            "get_shop_performance_per_hour",
        }
        called = {call[0] for call in resource.method_calls}
        assert called <= read_methods
        assert called == read_methods


def test_derives_aov_from_gmv_and_orders() -> None:
    aov = derive_aov("6408074.00", 26)
    assert aov is not None
    assert aov == Decimal("246464")
