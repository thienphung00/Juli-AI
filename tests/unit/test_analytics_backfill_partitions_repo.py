"""P2-9-2 (#464) — durable partition progress for resumable analytics backfill."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import AnalyticsBackfillPartitionsRepo

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84909998877")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Backfill Test Shop",
        tiktok_shop_id="tts_backfill_test",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


class TestAnalyticsBackfillPartitionsRepo:
    async def test_completed_partition_not_in_list_incomplete(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        repo = AnalyticsBackfillPartitionsRepo(session)
        partition_date = date(2026, 1, 15)

        await repo.mark_complete(shop.id, "revenue", partition_date)

        incomplete = await repo.list_incomplete(
            shop.id, "revenue", partition_date, partition_date
        )

        assert incomplete == []
        assert await repo.is_complete(shop.id, "revenue", partition_date) is True

    async def test_failed_partition_remains_incomplete_for_retry(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        repo = AnalyticsBackfillPartitionsRepo(session)
        partition_date = date(2026, 1, 16)

        await repo.mark_failed(
            shop.id,
            "product",
            partition_date,
            "Partner timeout after 30s",
            retryable=True,
        )

        incomplete = await repo.list_incomplete(
            shop.id, "product", partition_date, partition_date
        )

        assert len(incomplete) == 1
        row = incomplete[0]
        assert row.status == "failed"
        assert row.retryable is True
        assert row.attempt_count == 1
        assert await repo.is_complete(shop.id, "product", partition_date) is False

    async def test_duplicate_mark_complete_is_idempotent(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        repo = AnalyticsBackfillPartitionsRepo(session)
        partition_date = date(2026, 1, 17)

        await repo.mark_complete(shop.id, "live", partition_date)
        await repo.mark_complete(shop.id, "live", partition_date)

        assert await repo.is_complete(shop.id, "live", partition_date) is True
        incomplete = await repo.list_incomplete(
            shop.id, "live", partition_date, partition_date
        )
        assert incomplete == []

    async def test_mark_failed_redacts_tokens_in_last_error(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        repo = AnalyticsBackfillPartitionsRepo(session)
        partition_date = date(2026, 1, 18)
        secret = "super_secret_access_token_abc123xyz"

        await repo.mark_failed(
            shop.id,
            "catalog",
            partition_date,
            f"401 unauthorized bearer {secret}",
        )

        incomplete = await repo.list_incomplete(
            shop.id, "catalog", partition_date, partition_date
        )

        assert len(incomplete) == 1
        assert secret not in (incomplete[0].last_error or "")
        assert "[REDACTED]" in (incomplete[0].last_error or "")
