"""CDP-A2-5 (#620) — partition-resumable batch reconcile via ops checkpoints.

PR-safe: fixture page fetchers and in-memory SQLite only — no live Partner HTTP.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.models.models import (
    AnalyticsBackfillPartition,
    BronzeOrderRawPayload,
    Shop,
    User,
)
from juli_backend.services.cdp_batch.partition_checkpoints import (
    BATCH_RECONCILE_INGEST_SOURCE,
    BatchPartitionCheckpointsRepo,
    PartitionPageCheckpoint,
    append_reconcile_bronze_page,
    reconcile_page_source_event_id,
    reconcile_partition_with_checkpoints,
    recover_checkpoint_from_bronze,
)
from juli_backend.services.cdp_batch.partner_budget import begin_partner_budget_run

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "analytics_backfill" / "product"
PARTITION_DATE = date(2026, 7, 13)
BUCKET = "catalog"
RECEIVED_AT = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


class FakeReconcilePageFetcher:
    """Stub paginated reconcile fetcher — no live Partner HTTP."""

    def __init__(
        self,
        pages: dict[str | None, dict[str, Any]],
        *,
        fail_on_token: str | None = None,
    ) -> None:
        self._pages = pages
        self._fail_on_token = fail_on_token
        self.calls: list[str | None] = []

    def fetch_page(self, *, page_token: str | None) -> dict[str, Any]:
        self.calls.append(page_token)
        if self._fail_on_token is not None and page_token == self._fail_on_token:
            raise RuntimeError(f"simulated failure on page_token={page_token!r}")
        try:
            return self._pages[page_token]
        except KeyError as exc:
            raise RuntimeError(f"unexpected page_token {page_token!r}") from exc


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84962000620")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Batch Checkpoint Shop",
        tiktok_shop_id="tts_batch_checkpoint",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


def _page_result(
    *,
    order_id: str,
    next_page_token: str | None = None,
) -> dict[str, Any]:
    return {
        "payloads": [{"order_id": order_id, "status": "AWAITING_SHIPMENT"}],
        "next_page_token": next_page_token,
    }


class TestBatchPartitionCheckpointsRepo:
    pytestmark = pytest.mark.asyncio

    async def test_reads_and_writes_ops_partitions_only(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        repo = BatchPartitionCheckpointsRepo(session)
        checkpoint = PartitionPageCheckpoint(page_token="page-2", pages_completed=1)

        await repo.save_checkpoint(shop.id, BUCKET, PARTITION_DATE, checkpoint)
        loaded = await repo.get_checkpoint(shop.id, BUCKET, PARTITION_DATE)

        assert loaded == checkpoint
        row = await session.get(
            AnalyticsBackfillPartition,
            (
                await session.execute(
                    select(AnalyticsBackfillPartition.id).where(
                        AnalyticsBackfillPartition.shop_id == shop.id,
                        AnalyticsBackfillPartition.bucket == BUCKET,
                        AnalyticsBackfillPartition.partition_date == PARTITION_DATE,
                    )
                )
            ).scalar_one(),
        )
        assert row is not None
        assert row.__table__.schema == "ops"
        assert row.__table__.fullname == "ops.analytics_backfill_partitions"
        assert row.status == "pending"

    async def test_mark_complete_clears_checkpoint(self, session: AsyncSession, shop: Shop) -> None:
        repo = BatchPartitionCheckpointsRepo(session)
        await repo.save_checkpoint(
            shop.id,
            BUCKET,
            PARTITION_DATE,
            PartitionPageCheckpoint(page_token="page-2", pages_completed=1),
        )

        await repo.mark_complete(shop.id, BUCKET, PARTITION_DATE)

        assert await repo.is_complete(shop.id, BUCKET, PARTITION_DATE) is True
        assert await repo.get_checkpoint(shop.id, BUCKET, PARTITION_DATE) is None


class TestReconcilePartitionWithCheckpoints:
    pytestmark = pytest.mark.asyncio

    async def test_mid_partition_failure_then_resume_without_duplicating_pages(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        fetcher = FakeReconcilePageFetcher(
            {
                None: _page_result(order_id="577000001", next_page_token="page-2"),
                "page-2": _page_result(order_id="577000002"),
            },
            fail_on_token="page-2",
        )

        result1 = await reconcile_partition_with_checkpoints(
            session,
            shop_id=shop.id,
            bucket=BUCKET,
            partition_date=PARTITION_DATE,
            fetcher=fetcher,
            budget=begin_partner_budget_run(max_attempts=10, hard_limit=10),
            received_at=RECEIVED_AT,
        )

        assert result1.complete is False
        assert result1.pages_fetched == 1
        assert result1.bronze_rows_appended == 1
        assert fetcher.calls == [None, "page-2"]
        checkpoints = BatchPartitionCheckpointsRepo(session)
        assert await checkpoints.is_complete(shop.id, BUCKET, PARTITION_DATE) is False
        saved = await checkpoints.get_checkpoint(shop.id, BUCKET, PARTITION_DATE)
        assert saved == PartitionPageCheckpoint(page_token="page-2", pages_completed=1)

        fetcher_resume = FakeReconcilePageFetcher(
            {
                "page-2": _page_result(order_id="577000002"),
            }
        )

        result2 = await reconcile_partition_with_checkpoints(
            session,
            shop_id=shop.id,
            bucket=BUCKET,
            partition_date=PARTITION_DATE,
            fetcher=fetcher_resume,
            budget=begin_partner_budget_run(max_attempts=10, hard_limit=10),
            received_at=RECEIVED_AT,
        )

        assert result2.complete is True
        assert result2.skipped is False
        assert result2.pages_fetched == 1
        assert result2.bronze_rows_appended == 1
        assert fetcher_resume.calls == ["page-2"]
        assert await checkpoints.is_complete(shop.id, BUCKET, PARTITION_DATE) is True

        count_stmt = (
            select(func.count())
            .select_from(BronzeOrderRawPayload)
            .where(
                BronzeOrderRawPayload.shop_id == shop.id,
                BronzeOrderRawPayload.ingest_source == BATCH_RECONCILE_INGEST_SOURCE,
            )
        )
        assert (await session.execute(count_stmt)).scalar_one() == 2

        source_ids = (
            (
                await session.execute(
                    select(BronzeOrderRawPayload.source_event_id).where(
                        BronzeOrderRawPayload.shop_id == shop.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(source_ids) == len(set(source_ids))

    async def test_crash_after_bronze_before_checkpoint_resume_no_duplicate(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        """Bronze committed without ops checkpoint must recover via page idempotency."""
        await append_reconcile_bronze_page(
            session,
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            fetched_page_token=None,
            next_page_token="page-2",
            payloads=[{"order_id": "577000001", "status": "AWAITING_SHIPMENT"}],
            received_at=RECEIVED_AT,
        )
        await session.commit()

        checkpoints = BatchPartitionCheckpointsRepo(session)
        assert await checkpoints.get_checkpoint(shop.id, BUCKET, PARTITION_DATE) == (
            PartitionPageCheckpoint(page_token="page-2", pages_completed=1)
        )

        fetcher = FakeReconcilePageFetcher(
            {
                "page-2": _page_result(order_id="577000002"),
            }
        )

        result = await reconcile_partition_with_checkpoints(
            session,
            shop_id=shop.id,
            bucket=BUCKET,
            partition_date=PARTITION_DATE,
            fetcher=fetcher,
            budget=begin_partner_budget_run(max_attempts=10, hard_limit=10),
            received_at=RECEIVED_AT,
        )

        assert result.complete is True
        assert fetcher.calls == ["page-2"]
        assert (
            await session.execute(
                select(func.count())
                .select_from(BronzeOrderRawPayload)
                .where(
                    BronzeOrderRawPayload.shop_id == shop.id,
                    BronzeOrderRawPayload.ingest_source == BATCH_RECONCILE_INGEST_SOURCE,
                )
            )
        ).scalar_one() == 2

    async def test_shared_session_rollback_discards_bronze_and_checkpoint(
        self, engine, session: AsyncSession, shop: Shop
    ) -> None:
        """Append + checkpoint share one session; rollback drops both (transaction contract)."""
        await session.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as txn_session:
            fetcher = FakeReconcilePageFetcher(
                {
                    None: _page_result(order_id="577000001"),
                }
            )
            result = await reconcile_partition_with_checkpoints(
                txn_session,
                shop_id=shop.id,
                bucket=BUCKET,
                partition_date=PARTITION_DATE,
                fetcher=fetcher,
                budget=begin_partner_budget_run(max_attempts=10, hard_limit=10),
                received_at=RECEIVED_AT,
            )
            assert result.complete is True
            await txn_session.rollback()

        async with factory() as verify_session:
            bronze_count = (
                await verify_session.execute(
                    select(func.count())
                    .select_from(BronzeOrderRawPayload)
                    .where(BronzeOrderRawPayload.shop_id == shop.id)
                )
            ).scalar_one()
            assert bronze_count == 0
            checkpoints = BatchPartitionCheckpointsRepo(verify_session)
            assert await checkpoints.get_checkpoint(shop.id, BUCKET, PARTITION_DATE) is None

    async def test_completed_partition_skips_fetch_and_bronze_append(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        checkpoints = BatchPartitionCheckpointsRepo(session)
        await checkpoints.mark_complete(shop.id, BUCKET, PARTITION_DATE)

        fetcher = FakeReconcilePageFetcher({None: _page_result(order_id="577000099")})

        result = await reconcile_partition_with_checkpoints(
            session,
            shop_id=shop.id,
            bucket=BUCKET,
            partition_date=PARTITION_DATE,
            fetcher=fetcher,
            budget=begin_partner_budget_run(max_attempts=10, hard_limit=10),
            received_at=RECEIVED_AT,
        )

        assert result.skipped is True
        assert result.complete is True
        assert fetcher.calls == []

    async def test_partner_budget_exhaustion_persists_cursor_for_resume(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        fetcher = FakeReconcilePageFetcher(
            {
                None: _page_result(order_id="577000001", next_page_token="page-2"),
                "page-2": _page_result(order_id="577000002"),
            }
        )

        budget = begin_partner_budget_run(max_attempts=1, hard_limit=2)
        result = await reconcile_partition_with_checkpoints(
            session,
            shop_id=shop.id,
            bucket=BUCKET,
            partition_date=PARTITION_DATE,
            fetcher=fetcher,
            budget=budget,
            received_at=RECEIVED_AT,
        )

        assert result.complete is False
        assert result.deferred is True
        assert result.pages_fetched == 1
        checkpoints = BatchPartitionCheckpointsRepo(session)
        saved = await checkpoints.get_checkpoint(shop.id, BUCKET, PARTITION_DATE)
        assert saved == PartitionPageCheckpoint(page_token="page-2", pages_completed=1)

    async def test_append_reconcile_bronze_page_is_idempotent_by_source_event_id(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        payloads = [{"order_id": "577000001"}]
        first = await append_reconcile_bronze_page(
            session,
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            fetched_page_token=None,
            next_page_token="page-2",
            payloads=payloads,
            received_at=RECEIVED_AT,
        )
        second = await append_reconcile_bronze_page(
            session,
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            fetched_page_token=None,
            next_page_token="page-2",
            payloads=payloads,
            received_at=RECEIVED_AT,
        )

        assert first == 1
        assert second == 0
        event_id = reconcile_page_source_event_id(PARTITION_DATE, None)
        count = (
            await session.execute(
                select(func.count())
                .select_from(BronzeOrderRawPayload)
                .where(BronzeOrderRawPayload.source_event_id == event_id)
            )
        ).scalar_one()
        assert count == 1

    async def test_recover_checkpoint_from_bronze_reads_next_page_token(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        await append_reconcile_bronze_page(
            session,
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            fetched_page_token=None,
            next_page_token="page-2",
            payloads=[{"order_id": "577000001"}],
            received_at=RECEIVED_AT,
        )

        recovered = await recover_checkpoint_from_bronze(
            session,
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
        )

        assert recovered == PartitionPageCheckpoint(page_token="page-2", pages_completed=1)


def test_no_live_partner_http_in_unit_tests() -> None:
    """Partition checkpoint tests use fixture fetchers only — no live Partner HTTP."""
    fetcher = FakeReconcilePageFetcher({None: _page_result(order_id="577000001")})
    assert fetcher.calls == []
