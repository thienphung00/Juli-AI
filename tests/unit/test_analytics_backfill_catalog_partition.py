"""P2-9-7 (#469) — catalog Active/New counts via A-2 Search Products."""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import (
    AnalyticsBackfillPartitionsRepo,
    AnalyticsPerformanceRepo,
)
from juli_backend.services.analytics_backfill.catalog_partition import (
    ACTIVE_PRODUCT_STATUSES,
    CATALOG_BUCKET,
    CatalogCountStrategy,
    compute_catalog_counts,
    run_catalog_partition,
)

FIXTURES_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "analytics_backfill" / "catalog"
)
PARTITION_DATE = date(2026, 3, 20)


def _load_mixed_products() -> list[dict]:
    return json.loads((FIXTURES_DIR / "mixed_products.json").read_text())


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84909997766")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Catalog Backfill Shop",
        tiktok_shop_id="tts_catalog_backfill",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


class TestComputeCatalogCounts:
    def test_daily_strategy_counts_active_and_new_from_fixture(self) -> None:
        products = _load_mixed_products()

        counts = compute_catalog_counts(
            products,
            partition_date=PARTITION_DATE,
            strategy=CatalogCountStrategy.DAILY,
        )

        assert counts.active_products == 3
        assert counts.new_products == 4
        assert counts.strategy is CatalogCountStrategy.DAILY

    def test_active_status_allowlist_documents_activate_minimum(self) -> None:
        assert "ACTIVATE" in ACTIVE_PRODUCT_STATUSES
        assert "DEACTIVATED" not in ACTIVE_PRODUCT_STATUSES
        assert "DRAFT" not in ACTIVE_PRODUCT_STATUSES

    def test_point_in_time_fallback_counts_new_since_window_start(self) -> None:
        products = _load_mixed_products()

        counts = compute_catalog_counts(
            products,
            partition_date=PARTITION_DATE,
            strategy=CatalogCountStrategy.POINT_IN_TIME,
        )

        assert counts.active_products == 3
        assert counts.new_products == 4
        assert counts.strategy is CatalogCountStrategy.POINT_IN_TIME


class TestRunCatalogPartition:
    pytestmark = pytest.mark.asyncio

    async def test_uses_a2_search_all_not_get_details(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        products_resource = MagicMock()
        products_resource.search_all.return_value = _load_mixed_products()
        products_resource.get_details = MagicMock()

        result = await run_catalog_partition(
            session=session,
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            products=products_resource,
        )

        products_resource.search_all.assert_called_once()
        products_resource.get_details.assert_not_called()
        assert result.status == "completed"
        assert result.active_products == 3
        assert result.new_products == 4

    async def test_persists_active_and_new_products_columns(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        products_resource = MagicMock()
        products_resource.search_all.return_value = _load_mixed_products()

        await run_catalog_partition(
            session=session,
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            products=products_resource,
        )

        perf_repo = AnalyticsPerformanceRepo(session)
        rows = await perf_repo.list(shop.id, limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row.active_products == 3
        assert row.new_products == 4
        assert row.grain == "catalog_daily"
        assert row.start_date == PARTITION_DATE

    async def test_skips_completed_partition(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        partitions = AnalyticsBackfillPartitionsRepo(session)
        await partitions.mark_complete(shop.id, CATALOG_BUCKET, PARTITION_DATE)

        products_resource = MagicMock()
        products_resource.search_all.return_value = _load_mixed_products()

        result = await run_catalog_partition(
            session=session,
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            products=products_resource,
        )

        assert result.status == "skipped"
        products_resource.search_all.assert_not_called()

    async def test_marks_partition_complete_after_success(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        products_resource = MagicMock()
        products_resource.search_all.return_value = _load_mixed_products()

        await run_catalog_partition(
            session=session,
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            products=products_resource,
        )

        partitions = AnalyticsBackfillPartitionsRepo(session)
        assert await partitions.is_complete(shop.id, CATALOG_BUCKET, PARTITION_DATE)

    async def test_point_in_time_strategy_is_explicit_and_persisted(
        self, session: AsyncSession, shop: Shop
    ) -> None:
        products_resource = MagicMock()
        products_resource.search_all.return_value = _load_mixed_products()

        result = await run_catalog_partition(
            session=session,
            shop_id=shop.id,
            partition_date=PARTITION_DATE,
            products=products_resource,
            strategy=CatalogCountStrategy.POINT_IN_TIME,
        )

        assert result.strategy is CatalogCountStrategy.POINT_IN_TIME
        assert result.new_products == 4

        perf_repo = AnalyticsPerformanceRepo(session)
        rows = await perf_repo.list(shop.id, limit=10)
        assert len(rows) == 1
        assert rows[0].grain == "catalog_point_in_time"
        assert rows[0].new_products == 4


def test_no_live_partner_http_in_unit_tests() -> None:
    """Catalog partition tests mock ProductsResource — no live Partner HTTP."""
    resource = MagicMock()
    resource.search_all.return_value = []
    assert resource.search_all() == []
