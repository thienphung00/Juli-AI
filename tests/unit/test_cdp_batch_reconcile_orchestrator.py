"""Unit tests for BatchReconcileOrchestrator (#621 / CDP-A2-8)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    GoldKpiEnvelope,
    Shop,
    User,
)
from juli_backend.services.cdp_batch import (
    BatchFetchPlanner,
    BatchReconcileOrchestrator,
    InMemoryShopComputeMutex,
    ReconcileWindow,
    begin_partner_budget_run,
    begin_postgres_io_budget_run,
)


class MockPageFetcher:
    """Mock Partner page fetcher for testing."""

    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.page_index = 0

    def fetch_page(self, *, page_token: str | None) -> dict:
        if self.page_index >= len(self.pages):
            return {"payloads": [], "next_page_token": None}
        page = self.pages[self.page_index]
        self.page_index += 1
        return page


@pytest.fixture
async def shop_and_user(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Create test shop and user."""
    user_id = uuid.uuid4()
    user = User(id=user_id, phone="+84901234567")
    session.add(user)
    await session.flush()

    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Test Shop",
    )
    session.add(shop)
    await session.commit()
    return shop.id, user.id


@pytest.mark.asyncio
async def test_batch_reconcile_orchestrator_full_flow(
    session: AsyncSession,
    shop_and_user: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """Test end-to-end batch reconcile: fetch → bronze → silver → gold."""
    shop_id, _ = shop_and_user

    # Setup: create one page with one order
    order_data = {
        "order_id": "test_order_621",
        "order_status": "AWAITING_SHIPMENT",
        "total_amount": "100000.00",
        "currency": "VND",
        "update_time": int(datetime(2026, 7, 31, 12, 0, tzinfo=UTC).timestamp()),
    }

    pages = [
        {
            "payloads": [order_data],
            "next_page_token": None,
        }
    ]

    fetcher = MockPageFetcher(pages)
    partition_date = date(2026, 7, 31)
    window = ReconcileWindow(shop_id=str(shop_id), day=partition_date, minute_of_day=0)

    mutex = InMemoryShopComputeMutex()
    planner = BatchFetchPlanner()
    partner_budget = begin_partner_budget_run()
    postgres_budget = begin_postgres_io_budget_run()

    orchestrator = BatchReconcileOrchestrator(
        session,
        mutex=mutex,
        planner=planner,
        partner_budget=partner_budget,
        postgres_budget=postgres_budget,
    )

    # Execute
    result = await orchestrator.run(
        shop_id=shop_id,
        detected_gaps=frozenset({"orders"}),
        fetcher=fetcher,
        partition_date=partition_date,
        reconcile_window=window,
    )

    # Assert: result indicates success
    assert result.acquired, "Should acquire compute mutex"
    assert not result.deferred, "Should not defer"
    assert result.pages_fetched == 1
    assert result.bronze_rows_appended == 1
    assert result.silver_promoted >= 0
    assert result.gold_written, "Should write gold envelope"

    # Verify gold envelope was written
    stmt = select(GoldKpiEnvelope).where(GoldKpiEnvelope.shop_id == shop_id)
    gold = (await session.execute(stmt)).scalar_one_or_none()
    assert gold is not None, "Gold envelope should be written"
    assert "kpis" in gold.payload, "Gold payload should contain kpis"


@pytest.mark.asyncio
async def test_batch_reconcile_orchestrator_defers_on_partner_budget(
    session: AsyncSession,
    shop_and_user: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """Test batch reconcile defers when partner budget exhausted."""
    shop_id, _ = shop_and_user

    pages = [
        {
            "payloads": [
                {
                    "order_id": f"order_{i}",
                    "order_status": "AWAITING_SHIPMENT",
                    "total_amount": "100000.00",
                    "currency": "VND",
                    "update_time": int(datetime(2026, 7, 31, 12, 0, tzinfo=UTC).timestamp()),
                }
                for i in range(5)
            ],
            "next_page_token": "page_2",
        },
        {
            "payloads": [
                {
                    "order_id": f"order_{i + 5}",
                    "order_status": "AWAITING_SHIPMENT",
                    "total_amount": "100000.00",
                    "currency": "VND",
                    "update_time": int(datetime(2026, 7, 31, 12, 0, tzinfo=UTC).timestamp()),
                }
                for i in range(5)
            ],
            "next_page_token": None,
        },
    ]

    fetcher = MockPageFetcher(pages)
    partition_date = date(2026, 7, 31)
    window = ReconcileWindow(shop_id=str(shop_id), day=partition_date, minute_of_day=0)

    mutex = InMemoryShopComputeMutex()
    planner = BatchFetchPlanner()
    # Set hard limit to 1 attempt so second page fetch will fail
    partner_budget = begin_partner_budget_run(max_attempts=1, hard_limit=1)
    postgres_budget = begin_postgres_io_budget_run()

    orchestrator = BatchReconcileOrchestrator(
        session,
        mutex=mutex,
        planner=planner,
        partner_budget=partner_budget,
        postgres_budget=postgres_budget,
    )

    # Execute
    result = await orchestrator.run(
        shop_id=shop_id,
        detected_gaps=frozenset({"orders"}),
        fetcher=fetcher,
        partition_date=partition_date,
        reconcile_window=window,
    )

    # Assert: deferred on partner budget
    assert result.acquired, "Should acquire compute mutex before deferring"
    assert result.deferred, "Should defer on budget exhaustion"
    assert result.defer_reason == "partner_budget_exhausted"
    assert result.pages_fetched == 1, "Should have fetched first page"


@pytest.mark.asyncio
async def test_batch_reconcile_orchestrator_defers_on_speed_mutex(
    session: AsyncSession,
    shop_and_user: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """Test batch reconcile defers when speed compute holds mutex."""
    shop_id, _ = shop_and_user

    # Speed owns the mutex
    mutex = InMemoryShopComputeMutex()
    mutex.try_acquire(str(shop_id), "speed")

    planner = BatchFetchPlanner()
    partner_budget = begin_partner_budget_run()
    postgres_budget = begin_postgres_io_budget_run()

    orchestrator = BatchReconcileOrchestrator(
        session,
        mutex=mutex,
        planner=planner,
        partner_budget=partner_budget,
        postgres_budget=postgres_budget,
    )

    partition_date = date(2026, 7, 31)
    window = ReconcileWindow(shop_id=str(shop_id), day=partition_date, minute_of_day=0)

    # Execute
    result = await orchestrator.run(
        shop_id=shop_id,
        detected_gaps=frozenset({"orders"}),
        fetcher=MockPageFetcher([]),
        partition_date=partition_date,
        reconcile_window=window,
    )

    # Assert: deferred on speed mutex
    assert not result.acquired, "Should not acquire mutex when speed owns it"
    assert result.deferred, "Should defer"
    assert result.defer_reason == "speed_mutex_active"


@pytest.mark.asyncio
async def test_batch_reconcile_orchestrator_gap_not_detected(
    session: AsyncSession,
    shop_and_user: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """Test batch reconcile defers when no gap is detected."""
    shop_id, _ = shop_and_user

    mutex = InMemoryShopComputeMutex()
    planner = BatchFetchPlanner()
    partner_budget = begin_partner_budget_run()
    postgres_budget = begin_postgres_io_budget_run()

    orchestrator = BatchReconcileOrchestrator(
        session,
        mutex=mutex,
        planner=planner,
        partner_budget=partner_budget,
        postgres_budget=postgres_budget,
    )

    partition_date = date(2026, 7, 31)
    window = ReconcileWindow(shop_id=str(shop_id), day=partition_date, minute_of_day=0)

    # Execute with empty gaps
    result = await orchestrator.run(
        shop_id=shop_id,
        detected_gaps=frozenset(),  # No gaps
        fetcher=MockPageFetcher([]),
        partition_date=partition_date,
        reconcile_window=window,
    )

    # Assert: deferred on gap not detected
    assert result.deferred, "Should defer when no gap is detected"
    assert result.defer_reason == "gap_not_detected"
