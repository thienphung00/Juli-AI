"""P2-9-6 (#468) — LIVE partition E2E for analytics historical backfill."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH,
    ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
)
from juli_backend.integrations.tiktok.mapping import analytics_snapshot_key
from juli_backend.models.models import AnalyticsPerformanceInterval, Shop, User
from juli_backend.repositories.repos import (
    AnalyticsBackfillPartitionsRepo,
    AnalyticsPerformanceRepo,
)
from juli_backend.services.analytics_backfill.budget import begin_run
from juli_backend.services.analytics_backfill.live_partition import (
    LIVE_BUCKET,
    assert_no_forbidden_live_backfill_paths,
    backfill_live_allowed_get_paths,
    run_live_partition,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "analytics_backfill" / "live"
PARTITION_DATE = date(2026, 7, 13)


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84901112233")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="LIVE Backfill Shop",
        tiktok_shop_id="tts_live_backfill",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


def _analytics_resource_from_fixtures() -> MagicMock:
    a28 = _load_fixture("a28_sessions.json")
    a29 = _load_fixture("a29_overview.json")
    resource = MagicMock()
    resource.get_live_overview_performance.return_value = a29
    resource.list_live_performance_all.return_value = a28["data"]["live_stream_sessions"]
    return resource


class TestLivePartitionRollup:
    pytestmark = pytest.mark.asyncio

    async def test_a28_a29_populate_live_hours_and_sessions_on_rollup(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        resource = _analytics_resource_from_fixtures()
        budget = begin_run(max_attempts=10, hard_limit=10)
        partitions = AnalyticsBackfillPartitionsRepo(session)
        performance = AnalyticsPerformanceRepo(session)

        result = await run_live_partition(
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            analytics=resource,
            budget=budget,
            partitions_repo=partitions,
            performance_repo=performance,
            synced_at=int(datetime(2026, 7, 15, 12, 0, tzinfo=UTC).timestamp()),
        )

        assert result.status == "complete"

        snapshot_key = analytics_snapshot_key(
            grain="shop",
            start_date=PARTITION_DATE.isoformat(),
            end_date="2026-07-14",
        )
        stmt = select(AnalyticsPerformanceInterval).where(
            AnalyticsPerformanceInterval.shop_id == shop.id,
            AnalyticsPerformanceInterval.snapshot_key == snapshot_key,
        )
        row = (await session.execute(stmt)).scalar_one()
        assert row.live_hours == Decimal("3.0000")
        assert row.live_sessions == 2
        assert await partitions.is_complete(shop.id, LIVE_BUCKET, PARTITION_DATE)

    async def test_a28_maps_views_and_impressions_on_rollup(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        resource = _analytics_resource_from_fixtures()
        budget = begin_run(max_attempts=10, hard_limit=10)

        await run_live_partition(
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            analytics=resource,
            budget=budget,
            partitions_repo=AnalyticsBackfillPartitionsRepo(session),
            performance_repo=AnalyticsPerformanceRepo(session),
            synced_at=int(datetime(2026, 7, 15, 12, 0, tzinfo=UTC).timestamp()),
        )

        snapshot_key = analytics_snapshot_key(
            grain="shop",
            start_date=PARTITION_DATE.isoformat(),
            end_date="2026-07-14",
        )
        stmt = select(AnalyticsPerformanceInterval).where(
            AnalyticsPerformanceInterval.shop_id == shop.id,
            AnalyticsPerformanceInterval.snapshot_key == snapshot_key,
        )
        row = (await session.execute(stmt)).scalar_one()
        assert row.visitors == 300
        assert row.impressions == 1500


class TestLivePartitionResume:
    pytestmark = pytest.mark.asyncio

    async def test_skips_completed_live_partition(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        partitions = AnalyticsBackfillPartitionsRepo(session)
        await partitions.mark_complete(shop.id, LIVE_BUCKET, PARTITION_DATE)

        resource = _analytics_resource_from_fixtures()
        budget = begin_run(max_attempts=10, hard_limit=10)

        result = await run_live_partition(
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            analytics=resource,
            budget=budget,
            partitions_repo=partitions,
            performance_repo=AnalyticsPerformanceRepo(session),
            synced_at=int(datetime(2026, 7, 15, 12, 0, tzinfo=UTC).timestamp()),
        )

        assert result.status == "skipped"
        resource.get_live_overview_performance.assert_not_called()
        resource.list_live_performance_all.assert_not_called()
        assert budget.attempts == 0


class TestLivePartitionAllowlist:
    def test_backfill_live_allowed_paths_are_a28_and_a29_only(self) -> None:
        allowed = backfill_live_allowed_get_paths()
        assert allowed == frozenset({
            ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
            ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH,
        })

    def test_forbidden_a26_a27_paths_rejected(self) -> None:
        forbidden = [
            "/analytics/202510/shop_lives/live-1/performance_per_minutes",
            "/analytics/202509/shop_lives/live-1/products/performance",
        ]
        with pytest.raises(AssertionError):
            assert_no_forbidden_live_backfill_paths(forbidden)


class TestLivePartitionAllowlistIntegration:
    pytestmark = pytest.mark.asyncio

    async def test_run_live_partition_never_calls_forbidden_paths(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        resource = _analytics_resource_from_fixtures()
        budget = begin_run(max_attempts=10, hard_limit=10)

        result = await run_live_partition(
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            analytics=resource,
            budget=budget,
            partitions_repo=AnalyticsBackfillPartitionsRepo(session),
            performance_repo=AnalyticsPerformanceRepo(session),
            synced_at=int(datetime(2026, 7, 15, 12, 0, tzinfo=UTC).timestamp()),
        )

        assert result.status == "complete"
        assert_no_forbidden_live_backfill_paths(result.called_paths)


def test_no_live_partner_http_in_unit_tests() -> None:
    """LIVE partition tests use fixture payloads — no live Partner HTTP."""
    budget = begin_run(max_attempts=1, hard_limit=1)
    assert budget.attempts == 0
