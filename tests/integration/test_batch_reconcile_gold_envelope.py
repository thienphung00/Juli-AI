"""Integration test for batch reconcile gold envelope contract (#621 / CDP-A2-8)."""

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
from juli_backend.services.gold_kpi_envelope_contract import (
    DEMO_MAIN_KPI_METRIC_IDS,
    ENVELOPE_VERSION,
)


class MockPageFetcher:
    """Mock Partner page fetcher that returns fixture order data."""

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
async def integration_shop_and_user(
    session: AsyncSession,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create test shop and user for integration test."""
    user_id = uuid.uuid4()
    user = User(id=user_id, phone="+84901234567")
    session.add(user)
    await session.flush()

    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Integration Test Shop",
    )
    session.add(shop)
    await session.commit()
    return shop.id, user.id


@pytest.mark.asyncio
async def test_batch_reconcile_writes_matching_gold_envelope(
    session: AsyncSession,
    integration_shop_and_user: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """Test that batch reconcile writes gold envelope with matching kpis shape."""
    shop_id, _ = integration_shop_and_user

    # Create mock order data for reconciliation
    order_data = {
        "order_id": "integration_order_621",
        "order_status": "AWAITING_SHIPMENT",
        "total_amount": "150000.00",
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

    # Execute batch reconcile
    result = await orchestrator.run(
        shop_id=shop_id,
        detected_gaps=frozenset({"orders"}),
        fetcher=fetcher,
        partition_date=partition_date,
        reconcile_window=window,
    )

    # Verify result
    assert result.acquired, "Should acquire mutex"
    assert not result.deferred, "Should not defer"
    assert result.gold_written, "Should write gold envelope"

    # Commit to persist the gold envelope
    await session.commit()

    # Verify gold envelope exists and has correct structure
    stmt = select(GoldKpiEnvelope).where(GoldKpiEnvelope.shop_id == shop_id)
    gold = (await session.execute(stmt)).scalar_one_or_none()

    assert gold is not None, "Gold envelope should exist"
    payload = gold.payload
    assert isinstance(payload, dict), "Payload should be a dict"

    # Verify contract fields
    assert payload.get("envelope_version") == ENVELOPE_VERSION
    assert payload.get("kind") == "analytics"
    assert str(payload.get("shop_id")) == str(shop_id)
    assert "computed_at" in payload, "Should have computed_at"
    assert "currency" in payload, "Should have currency"

    # Verify kpis structure matches Speed path contract
    kpis = payload.get("kpis")
    assert kpis is not None, "Should have kpis object"
    assert isinstance(kpis, dict), "KPIs should be a dict"

    # Verify all expected KPI metric_ids are present
    for metric_id in DEMO_MAIN_KPI_METRIC_IDS:
        assert metric_id in kpis, f"KPI {metric_id} should be present"
        kpi_data = kpis[metric_id]
        assert isinstance(kpi_data, dict), f"KPI {metric_id} should be a dict"
        # At minimum, should have availability and label fields
        assert "availability" in kpi_data or "value" in kpi_data, (
            f"KPI {metric_id} should have availability or value"
        )

    # Verify meta structure
    assert "meta" in payload, "Should have meta object"
    meta = payload.get("meta")
    assert isinstance(meta, dict), "Meta should be a dict"
    assert "source_partitions" in meta, "Meta should have source_partitions"
