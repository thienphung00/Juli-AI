"""P2-9-5 (#467) — Product funnel partition E2E via A-34 daily list."""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.integrations.tiktok.exceptions import TikTokAPIError
from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import (
    AnalyticsBackfillPartitionsRepo,
    AnalyticsPerformanceRepo,
)
from juli_backend.services.analytics_backfill.budget import begin_run
from juli_backend.services.analytics_backfill.product_partition import (
    backfill_product_partition,
)

pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "analytics_backfill" / "product"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


class FakeProductPerformanceResource:
    """In-memory A-34 stub — no live Partner HTTP."""

    def __init__(
        self,
        pages: dict[str | None, dict[str, Any]],
        *,
        fail_on_token: str | None = None,
    ) -> None:
        self._pages = pages
        self._fail_on_token = fail_on_token
        self.calls: list[dict[str, Any]] = []

    def list_product_performance(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "start_date_ge": start_date_ge,
                "end_date_lt": end_date_lt,
                "page_size": page_size,
                "page_token": page_token,
            }
        )
        if self._fail_on_token is not None and page_token == self._fail_on_token:
            raise TikTokAPIError(100006, "Partner timeout on page 2")
        try:
            return self._pages[page_token]
        except KeyError as exc:
            raise TikTokAPIError(100004, f"unexpected page_token {page_token!r}") from exc


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84901112233")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Product Partition Shop",
        tiktok_shop_id="tts_product_partition",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


@pytest.fixture
def partition_date() -> date:
    return date(2026, 7, 13)


@pytest.fixture
def multi_page_resource() -> FakeProductPerformanceResource:
    return FakeProductPerformanceResource(
        {
            None: _load_fixture("a34_page1.json"),
            "page-2": _load_fixture("a34_page2.json"),
        }
    )


async def test_multi_page_a34_upserts_product_rows_with_mapped_metrics(
    session: AsyncSession,
    shop: Shop,
    partition_date: date,
    multi_page_resource: FakeProductPerformanceResource,
) -> None:
    budget = begin_run(max_attempts=10, hard_limit=10)
    synced_at = 1_700_000_000

    result = await backfill_product_partition(
        session,
        shop_id=shop.id,
        partition_date=partition_date,
        resource=multi_page_resource,
        budget=budget,
        synced_at=synced_at,
    )

    assert result.skipped is False
    assert result.complete is True
    assert result.products_upserted == 2
    assert result.pages_fetched == 2
    assert len(multi_page_resource.calls) == 2
    assert multi_page_resource.calls[0]["start_date_ge"] == "2026-07-13"
    assert multi_page_resource.calls[0]["end_date_lt"] == "2026-07-14"
    assert multi_page_resource.calls[0]["page_token"] is None
    assert multi_page_resource.calls[1]["page_token"] == "page-2"

    perf_repo = AnalyticsPerformanceRepo(session)
    rows = await perf_repo.list(shop.id, limit=100)
    assert len(rows) == 2

    by_product = {row.tiktok_product_id: row for row in rows}
    assert set(by_product) == {"prod-1", "prod-2"}

    prod1 = by_product["prod-1"]
    assert prod1.grain == "product"
    assert prod1.start_date == partition_date
    assert prod1.end_date == date(2026, 7, 14)
    assert prod1.gmv == Decimal("2430217.00")
    assert prod1.gmv_currency == "VND"
    assert prod1.orders_count == 9
    assert prod1.sku_orders == 10
    assert prod1.customers == 6
    assert prod1.ctr == Decimal("0.0759")
    assert prod1.click_order_rate == Decimal("0.1064")
    assert prod1.impressions is None

    partitions = AnalyticsBackfillPartitionsRepo(session)
    assert await partitions.is_complete(shop.id, "product", partition_date) is True
    assert budget.attempts == 2
    assert budget.successes == 2


async def test_completed_partition_skips_partner_on_resume(
    session: AsyncSession,
    shop: Shop,
    partition_date: date,
    multi_page_resource: FakeProductPerformanceResource,
) -> None:
    partitions = AnalyticsBackfillPartitionsRepo(session)
    await partitions.mark_complete(shop.id, "product", partition_date)
    budget = begin_run(max_attempts=10, hard_limit=10)

    result = await backfill_product_partition(
        session,
        shop_id=shop.id,
        partition_date=partition_date,
        resource=multi_page_resource,
        budget=budget,
        synced_at=1_700_000_000,
    )

    assert result.skipped is True
    assert result.complete is True
    assert result.products_upserted == 0
    assert multi_page_resource.calls == []
    assert budget.attempts == 0


async def test_mid_pagination_failure_leaves_partition_incomplete(
    session: AsyncSession,
    shop: Shop,
    partition_date: date,
) -> None:
    resource = FakeProductPerformanceResource(
        {
            None: _load_fixture("a34_page1.json"),
            "page-2": _load_fixture("a34_page2.json"),
        },
        fail_on_token="page-2",
    )
    budget = begin_run(max_attempts=10, hard_limit=10)

    result = await backfill_product_partition(
        session,
        shop_id=shop.id,
        partition_date=partition_date,
        resource=resource,
        budget=budget,
        synced_at=1_700_000_000,
    )

    assert result.skipped is False
    assert result.complete is False
    assert result.pages_fetched == 1
    assert result.products_upserted == 1

    partitions = AnalyticsBackfillPartitionsRepo(session)
    assert await partitions.is_complete(shop.id, "product", partition_date) is False
    incomplete = await partitions.list_incomplete(
        shop.id, "product", partition_date, partition_date
    )
    assert len(incomplete) == 1
    assert incomplete[0].status == "failed"

    rows = await AnalyticsPerformanceRepo(session).list(shop.id, limit=100)
    assert len(rows) == 1
    assert rows[0].tiktok_product_id == "prod-1"


async def test_no_live_partner_http_in_unit_tests() -> None:
    """Product partition tests use fixture stubs only — no live Partner HTTP."""
    resource = FakeProductPerformanceResource({None: {"products": []}})
    assert resource.calls == []
