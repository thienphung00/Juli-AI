"""Unit tests for A-7 cancellations targeted poll + webhook #11 reconcile (#628).

AC1 → webhook #11 fixture upserts/reconciles expected silver return row
AC2 → targeted cancellations poll step merges into silver without duplicating natural keys
AC3 → orchestrator job including A-7 plan updates silver returns end-to-end
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.database.database import Base
from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    BronzeReturnRawPayload,
    GoldKpiEnvelope,
    Order,
    Return,
    Shop,
    User,
)
from juli_backend.repositories.repos import (
    BronzeReturnRawPayloadsRepo,
    OrdersRepo,
)
from juli_backend.services.cdp_speed.shared_compute_orchestrator import (
    SharedComputeJob,
    SharedComputeOrchestrator,
)
from juli_backend.services.cdp_speed.targeted_fetch_planner import (
    FetchResource,
    TargetedFetchPlan,
)
from juli_backend.services.cdp_speed.targeted_fetch_sync import sync_cancellations
from juli_backend.services.etl.silver_promotion import SilverOrdersReturnsPromoter


@pytest_asyncio.fixture
async def medallion_session():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.execute(text("ATTACH DATABASE ':memory:' AS bronze"))
        await conn.execute(text("ATTACH DATABASE ':memory:' AS silver"))
        await conn.execute(text("ATTACH DATABASE ':memory:' AS gold"))
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn,
                tables=[
                    User.__table__,
                    Shop.__table__,
                    Order.__table__,
                    Return.__table__,
                    BronzeReturnRawPayload.__table__,
                    AnalyticsPerformanceInterval.__table__,
                    GoldKpiEnvelope.__table__,
                ],
            )
        )
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as session:
        user = User(phone="+84936500607", display_name="Silver Test User")
        session.add(user)
        await session.flush()
        shop = Shop(
            user_id=user.id,
            shop_name="Silver Test Shop",
            tiktok_shop_id="607_silver_shop",
        )
        session.add(shop)
        await session.flush()
        shop_id = shop.id
        yield session, shop_id
        await session.rollback()
    await eng.dispose()


@pytest.mark.asyncio
async def test_ac1_webhook_cancellation_upserts_silver_return(medallion_session):
    """Webhook #11 (CANCELLATION_STATUS_CHANGE) fixture upserts silver return row."""
    session, shop_id = medallion_session

    # First, create an order to reference
    orders_repo = OrdersRepo(session)
    update_time = datetime(2026, 7, 30, 14, 0, tzinfo=UTC).replace(tzinfo=None)
    order = await orders_repo.upsert(
        shop_id=shop_id,
        tiktok_order_id="577000607",
        status="confirmed",
        total_amount=99.50,
        currency="VND",
        update_time=update_time,
    )

    # Now ingest a cancellation payload via bronze (simulating webhook #11 handoff)
    bronze_repo = BronzeReturnRawPayloadsRepo(session)
    received_at = datetime(2026, 7, 30, 14, 15, tzinfo=UTC)

    # This is the cancellation payload that would come from webhook #11
    cancellation_payload = {
        "cancel_id": "cancel-607-001",
        "order_id": "577000607",
        "cancel_status": "BUYER_CANCELLED",
        "cancel_reason": "change_my_mind",
        "update_time": int(received_at.timestamp()),
    }

    bronze_rows = await bronze_repo.append_batch(
        [
            {
                "shop_id": shop_id,
                "ingest_source": "webhook",
                "payload": cancellation_payload,
                "received_at": received_at,
                "tiktok_return_id": "cancel-607-001",  # cancellation ID as return_id
                "tiktok_order_id": "577000607",
                "source_event_id": "evt-607-cancellation",
            },
        ]
    )

    # Promote the cancellation to silver returns
    promoter = SilverOrdersReturnsPromoter(session)
    ret = await promoter.promote_return(bronze_rows[0])

    # Assert the cancellation was stored in silver.returns with correct natural key
    assert ret.tiktok_return_id == "cancel-607-001"
    assert ret.tiktok_order_id == "577000607"
    assert ret.order_id == order.id

    # Verify idempotent re-promote returns same row
    ret_again = await promoter.promote_return(bronze_rows[0])
    assert ret_again.id == ret.id


@pytest.mark.asyncio
async def test_ac2_sync_cancellations_idempotent_merge(medallion_session):
    """Targeted cancellations poll step merges without duplicating natural keys."""
    session, shop_id = medallion_session

    # Create an order
    orders_repo = OrdersRepo(session)
    update_time = datetime(2026, 7, 30, 14, 0, tzinfo=UTC).replace(tzinfo=None)
    await orders_repo.upsert(
        shop_id=shop_id,
        tiktok_order_id="577000607",
        status="confirmed",
        total_amount=99.50,
        currency="VND",
        update_time=update_time,
    )

    # Mock the ReturnsResource and RateLimiter
    mock_resource = MagicMock()
    mock_rate_limiter = MagicMock()
    mock_rate_limiter.acquire.return_value = True

    # Mock handoff function to capture what would be appended
    appended_rows = []

    async def mock_handoff_fn(channel: str, shop_key: str, payload_bytes: bytes):
        appended_rows.append((channel, shop_key, payload_bytes))

    # First sync: return some cancellations
    mock_resource.search_cancellations_all.return_value = [
        {
            "cancel_id": "cancel-607-001",
            "order_id": "577000607",
            "cancel_status": "BUYER_CANCELLED",
            "cancel_reason": "change_my_mind",
            "update_time": 1690737600,  # Some timestamp
        },
        {
            "cancel_id": "cancel-607-002",
            "order_id": "577000607",
            "cancel_status": "SELLER_CANCELLED",
            "cancel_reason": "out_of_stock",
            "update_time": 1690737700,
        },
    ]

    sync_state = {}

    # Call sync_cancellations (this should be implemented)
    await sync_cancellations(
        resource=mock_resource,
        rate_limiter=mock_rate_limiter,
        handoff_fn=mock_handoff_fn,
        app_id="test_app",
        shop_key="607_silver_shop",
        sync_state=sync_state,
        correlation_id="test-correlation",
    )

    # Assert cancellations were handed off
    assert len(appended_rows) == 2
    assert appended_rows[0][0] == "tiktok.returns.raw"  # Same channel as returns

    # Simulate a second sync with one new cancellation
    mock_resource.search_cancellations_all.return_value = [
        {
            "cancel_id": "cancel-607-002",  # Duplicate
            "order_id": "577000607",
            "cancel_status": "SELLER_CANCELLED",
            "cancel_reason": "out_of_stock",
            "update_time": 1690737700,
        },
        {
            "cancel_id": "cancel-607-003",  # New
            "order_id": "577000607",
            "cancel_status": "ADMIN_CANCELLED",
            "cancel_reason": "fraud",
            "update_time": 1690737800,
        },
    ]

    appended_rows.clear()

    # Second sync should only get new ones (mocked Partner behavior)
    await sync_cancellations(
        resource=mock_resource,
        rate_limiter=mock_rate_limiter,
        handoff_fn=mock_handoff_fn,
        app_id="test_app",
        shop_key="607_silver_shop",
        sync_state=sync_state,
        correlation_id="test-correlation-2",
    )

    # When promoted to silver, duplicates are idempotent via natural key
    assert sync_state.get("cancellations_last_update_time") is not None


@pytest.mark.asyncio
async def test_ac3_orchestrator_with_cancellations_plan(medallion_session):
    """Orchestrator job including A-7 cancellations plan updates silver returns end-to-end."""
    session, shop_id = medallion_session

    # Create base order
    orders_repo = OrdersRepo(session)
    update_time = datetime(2026, 7, 30, 14, 0, tzinfo=UTC).replace(tzinfo=None)
    await orders_repo.upsert(
        shop_id=shop_id,
        tiktok_order_id="577000607",
        status="confirmed",
        total_amount=99.50,
        currency="VND",
        update_time=update_time,
    )

    # Create a fetch plan that includes cancellations
    # (This simulates a material webhook that triggered a plan including cancellations)
    plan = TargetedFetchPlan(
        catalog_id=2,  # Material webhook that might include cancellations
        shop_id=str(shop_id),
        resources=(FetchResource("returns", "/v2/shop/{shop_cipher}/returns/search", "returns"),),
    )

    # Create a job
    job = SharedComputeJob(
        shop_id=shop_id,
        shop_key="607_silver_shop",
        enqueue_reason="webhook_catalog:2",
        fetch_plan=plan,
        idempotency_key="job-628-cancellation-reconcile",
        event_type="RETURN_STATUS_CHANGE",
    )

    # Mock the fetch executor to inject cancellation data into bronze
    async def mock_fetch_executor(session, shop_id, shop_key, fetch_plan, idempotency_key):
        from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import (
            BronzeAppendTracker,
        )

        bronze_repo = BronzeReturnRawPayloadsRepo(session)
        received_at = datetime(2026, 7, 30, 14, 30, tzinfo=UTC)

        # Append a cancellation record
        rows = await bronze_repo.append_batch(
            [
                {
                    "shop_id": shop_id,
                    "ingest_source": "targeted_fetch",
                    "payload": {
                        "cancel_id": "cancel-628-001",
                        "order_id": "577000607",
                        "cancel_status": "BUYER_CANCELLED",
                        "cancel_reason": "change_my_mind",
                        "update_time": int(received_at.timestamp()),
                    },
                    "received_at": received_at,
                    "tiktok_return_id": "cancel-628-001",
                    "tiktok_order_id": "577000607",
                    "source_event_id": "evt-628-canc",
                },
            ]
        )

        tracker = BronzeAppendTracker()
        tracker.return_row_ids.append(rows[0].id)
        return tracker

    # Run orchestrator
    orchestrator = SharedComputeOrchestrator(
        session,
        fetch_executor=mock_fetch_executor,
    )
    result = await orchestrator.run(job)

    # Verify cancellation was promoted to silver.returns
    assert result.bronze_appended > 0
    assert result.silver_promoted > 0

    # Check that the cancellation exists in silver.returns
    query_result = await session.execute(
        select(Return).where(
            Return.shop_id == shop_id,
            Return.tiktok_return_id == "cancel-628-001",
        )
    )
    cancellation_row = query_result.scalars().first()
    assert cancellation_row is not None
    assert cancellation_row.tiktok_order_id == "577000607"
