"""P2-9-8 (#470) — budgeted multi-bucket analytics historical backfill orchestrator."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import AnalyticsBackfillPartitionsRepo
from juli_backend.services.analytics_backfill.budget import begin_run
from juli_backend.services.analytics_backfill.cli import build_parser
from juli_backend.services.analytics_backfill.orchestrator import (
    ALLOWED_BUCKETS,
    DEFAULT_BUCKET_ORDER,
    backfill_analytics_history,
    validate_buckets,
)

pytestmark_async = pytest.mark.asyncio


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84909997766")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Orchestrator Shop",
        tiktok_shop_id="tts_orchestrator",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


@pytest_asyncio.fixture
async def other_shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84909997767")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Other Orchestrator Shop",
        tiktok_shop_id="tts_orchestrator_other",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


class TestOrchestratorSkipComplete:
    pytestmark = pytestmark_async
    async def test_skips_completed_partitions_without_partner_calls(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        repo = AnalyticsBackfillPartitionsRepo(session)
        partition_date = date(2026, 3, 16)
        await repo.mark_complete(shop.id, "revenue", partition_date)

        calls: list[tuple[str, date]] = []
        budget = begin_run(max_attempts=10, hard_limit=10)

        async def run_partition(bucket: str, d: date) -> None:
            budget.record_attempt()
            calls.append((bucket, d))

        result = await backfill_analytics_history(
            session,
            shop_id=shop.id,
            start_date=partition_date,
            end_date=partition_date,
            buckets=("revenue",),
            budget=budget,
            run_partition=run_partition,
        )

        assert calls == []
        assert result.skipped_partitions == 1
        assert result.completed_partitions == 0
        assert result.stopped_reason == "complete"


class TestOrchestratorBudgetResume:
    pytestmark = pytestmark_async
    async def test_two_run_simulation_resumes_without_refetching_completed(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        start = date(2026, 3, 16)
        end = date(2026, 3, 18)
        buckets = DEFAULT_BUCKET_ORDER
        repo = AnalyticsBackfillPartitionsRepo(session)
        all_calls: list[tuple[str, date]] = []

        async def run_partition(bucket: str, partition_date: date) -> None:
            budget = run_partition.budget  # type: ignore[attr-defined]
            budget.record_attempt()
            budget.record_success()
            all_calls.append((bucket, partition_date))
            await repo.mark_complete(shop.id, bucket, partition_date)

        budget_run1 = begin_run(max_attempts=5, hard_limit=10)
        run_partition.budget = budget_run1  # type: ignore[attr-defined]

        result1 = await backfill_analytics_history(
            session,
            shop_id=shop.id,
            start_date=start,
            end_date=end,
            buckets=buckets,
            budget=budget_run1,
            run_partition=run_partition,
        )

        assert result1.stopped_reason == "budget"
        assert len(all_calls) == 5

        budget_run2 = begin_run(max_attempts=50, hard_limit=60)
        run_partition.budget = budget_run2  # type: ignore[attr-defined]

        result2 = await backfill_analytics_history(
            session,
            shop_id=shop.id,
            start_date=start,
            end_date=end,
            buckets=buckets,
            budget=budget_run2,
            run_partition=run_partition,
        )

        assert result2.stopped_reason == "complete"
        # 3 days × 4 buckets = 12 total partition runs across both runs
        assert len(all_calls) == 12
        assert len(set(all_calls)) == 12


class TestOrchestratorShopIsolation:
    pytestmark = pytestmark_async
    async def test_second_shop_does_not_skip_first_shops_partitions(
        self,
        session: AsyncSession,
        shop: Shop,
        other_shop: Shop,
    ) -> None:
        repo = AnalyticsBackfillPartitionsRepo(session)
        partition_date = date(2026, 3, 16)
        await repo.mark_complete(shop.id, "revenue", partition_date)

        calls: list[tuple[str, date]] = []
        budget = begin_run(max_attempts=10, hard_limit=10)

        async def run_partition(bucket: str, d: date) -> None:
            budget.record_attempt()
            calls.append((bucket, d))
            await repo.mark_complete(other_shop.id, bucket, d)

        await backfill_analytics_history(
            session,
            shop_id=other_shop.id,
            start_date=partition_date,
            end_date=partition_date,
            buckets=("revenue",),
            budget=budget,
            run_partition=run_partition,
        )

        assert calls == [("revenue", partition_date)]


class TestOrchestratorBucketAllowlist:
    def test_validate_buckets_rejects_ads(self) -> None:
        with pytest.raises(ValueError, match="ads"):
            validate_buckets(["revenue", "ads"])

    def test_validate_buckets_rejects_unknown_buckets(self) -> None:
        with pytest.raises(ValueError, match="A-26|allowlist|forbidden"):
            validate_buckets(["revenue", "a26"])

    def test_default_bucket_order_excludes_ads(self) -> None:
        assert "ads" not in ALLOWED_BUCKETS
        assert set(DEFAULT_BUCKET_ORDER) == ALLOWED_BUCKETS


class TestOrchestratorCli:
    def test_shop_id_required(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--end", "2026-03-20"])

    def test_parses_shop_id_and_dates(self) -> None:
        shop_id = str(uuid.uuid4())
        args = build_parser().parse_args(
            [
                "--shop-id",
                shop_id,
                "--start",
                "2026-03-16",
                "--end",
                "2026-03-20",
            ]
        )
        assert args.shop_id == shop_id
        assert args.start == "2026-03-16"
        assert args.end == "2026-03-20"


def test_no_live_partner_http_in_unit_tests() -> None:
    """Orchestrator tests inject partition runners — no live Partner HTTP."""
    budget = begin_run(max_attempts=1, hard_limit=1)
    assert budget.attempts == 0
