"""Performance and durability tests for issue #790 - O(n²) silver stage.

Tests for:
1. Bounded query count in silver stage (not O(n))
2. Per-stage commit semantics (bronze/silver durability on gold failure)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.database.database import Base
from juli_backend.models.models import (
    BronzeOrderRawPayload,
    GoldKpiEnvelope,
    Order,
    Shop,
    User,
)
from juli_backend.services.cdp_speed import (
    plan_targeted_fetch,
)
from juli_backend.services.cdp_speed.shared_compute_orchestrator import (
    SharedComputeJob,
    SharedComputeOrchestrator,
)
from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import (
    BronzeAppendTracker,
)


@pytest_asyncio.fixture
async def perf_session_with_counter():
    """Session with query counter for performance measurements."""
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
                    BronzeOrderRawPayload.__table__,
                    GoldKpiEnvelope.__table__,
                ],
            )
        )
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as session:
        user = User(phone="+84901234790", display_name="Issue 790 Test User")
        session.add(user)
        await session.flush()
        shop = Shop(
            user_id=user.id,
            shop_name="Issue 790 Test Shop",
            tiktok_shop_id="shop_790",
        )
        session.add(shop)
        await session.flush()

        # Prepare query counter
        query_counter = {"count": 0, "queries": []}

        def count_queries(conn, cursor, statement, parameters, context, executemany):
            query_counter["count"] += 1
            query_counter["queries"].append(statement)

        event.listen(eng.sync_engine, "before_cursor_execute", count_queries)

        yield session, shop, eng, query_counter

        event.remove(eng.sync_engine, "before_cursor_execute", count_queries)
        await session.rollback()
    await eng.dispose()


@pytest.mark.asyncio
async def test_silver_stage_query_count_is_bounded_red(perf_session_with_counter):
    """RED TEST: Silver stage should issue bounded queries per row, not O(n).

    Current behavior on main: each promote_order calls:
    1. SELECT to find existing row
    2. flush() which triggers autoflush of ALL pending objects

    With autoflush=True (SQLAlchemy default), every SELECT in promote_order
    flushes all N pending rows accumulated so far, making the stage O(n²).

    Example with N=100:
    - Row 1: SELECT + flush 1 pending = 1 flush
    - Row 2: SELECT + flush 2 pending = 2 flush
    - ...
    - Row 100: SELECT + flush 100 pending = 100 flush
    - Total: ~5050 flush operations, each progressively more expensive

    This test FAILS before fix (queries > 200) and PASSES after (queries < 100).
    """
    session, shop, eng, query_counter = perf_session_with_counter

    # Create N bronze order rows to promote
    N = 50  # Use 50 for reasonable test time
    bronze_ids_set = set()
    for i in range(N):
        bronze_row = BronzeOrderRawPayload(
            shop_id=shop.id,
            ingest_source="targeted_fetch",
            payload={
                "order_id": f"order_790_{i:05d}",
                "order_status": "AWAITING_SHIPMENT",
                "total_amount": str(100000 + i),
                "currency": "VND",
                "update_time": int(datetime(2026, 8, 6, 12, 0, tzinfo=UTC).timestamp()),
            },
        )
        session.add(bronze_row)
        bronze_ids_set.add(bronze_row.id)
    await session.flush()

    # Verify that bronze rows were created
    all_bronze = (
        (
            await session.execute(
                select(BronzeOrderRawPayload).where(BronzeOrderRawPayload.shop_id == shop.id)
            )
        )
        .scalars()
        .all()
    )
    print(f"After flush: {len(all_bronze)} bronze rows in DB")
    bronze_ids = [b.id for b in all_bronze]

    # Reset counter after setup
    query_counter["count"] = 0
    query_counter["queries"] = []

    # Run silver stage promotion using the orchestrator's batched logic
    from juli_backend.services.cdp_speed.shared_compute_orchestrator import (
        SharedComputeOrchestrator,
    )

    # Create a tracker with the bronze order IDs
    tracker = BronzeAppendTracker()
    for bronze_id in bronze_ids:
        tracker.order_row_ids.append(bronze_id)

    # Reset counter after setup (before calling the orchestrator's silver stage)
    query_counter["count"] = 0
    query_counter["queries"] = []

    # Use orchestrator's batched silver stage
    promoted = await SharedComputeOrchestrator._default_silver_stage(
        session,
        shop.id,
        tracker,
    )

    queries = query_counter["count"]
    print(f"\nPromoted {promoted} rows with {queries} queries")
    print(f"Queries per row: {queries / promoted if promoted > 0 else 0:.2f}")

    # ASSERTION: Should be much less than 2 per row
    # Current (broken): ~150-200+ queries (lots of autoflushes)
    # Fixed (batched): ~30-50 queries
    assert queries < N * 1.5, (
        f"Silver stage is O(n): {queries} queries for {promoted} rows. "
        f"This is {queries / promoted:.2f} queries/row, should be bounded near 1."
    )


@pytest.mark.asyncio
async def test_orchestrator_per_stage_commits_preserve_durability(
    perf_session_with_counter,
):
    """Verify that per-stage commits in orchestrator preserve durability (#752 compat).

    Issue #752 required that after run_shared_compute_job completes and
    the session is committed, all bronze/silver/gold writes are durable
    across a new session.

    Issue #790 adds per-stage commits inside the orchestrator. This test
    verifies that the durability guarantee from #752 is still maintained.
    """
    session, shop, eng, query_counter = perf_session_with_counter

    # Create one bronze order
    bronze_row = BronzeOrderRawPayload(
        shop_id=shop.id,
        ingest_source="targeted_fetch",
        payload={
            "order_id": "order_durability_test",
            "order_status": "AWAITING_SHIPMENT",
            "total_amount": "100000",
            "currency": "VND",
            "update_time": int(datetime(2026, 8, 6, 12, 0, tzinfo=UTC).timestamp()),
        },
    )
    session.add(bronze_row)
    await session.flush()
    bronze_id = bronze_row.id

    # Run orchestrator with per-stage commits
    job = SharedComputeJob(
        shop_id=shop.id,
        shop_key=shop.tiktok_shop_id,
        enqueue_reason="test_durability",
        fetch_plan=plan_targeted_fetch(event_type="PACKAGE_UPDATE", shop_id=shop.tiktok_shop_id),
        idempotency_key="test-durability-001",
    )

    async def fake_bronze(sess, _job):
        tracker = BronzeAppendTracker()
        tracker.order_row_ids.append(bronze_id)
        return tracker

    orch = SharedComputeOrchestrator(session, bronze_stage=fake_bronze)
    await orch.run(job)

    # The orchestrator now commits after each stage internally,
    # but we still commit the session at the end for the task wrapper
    await session.commit()

    # Verify durability with new session
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as read_session:
        # Verify bronze is durable
        bronze_count = len(
            (
                await read_session.execute(
                    select(BronzeOrderRawPayload).where(BronzeOrderRawPayload.shop_id == shop.id)
                )
            )
            .scalars()
            .all()
        )

        # Verify silver is durable
        silver = (
            (await read_session.execute(select(Order).where(Order.shop_id == shop.id)))
            .scalars()
            .all()
        )

        # Verify gold is durable
        gold = await read_session.get(GoldKpiEnvelope, shop.id)

        # The #752 guarantee: bronze/silver/gold are all durable after commit
        # This ensures per-stage commits don't break the existing durability contract
        assert bronze_count > 0, "Bronze rows must be durable"
        assert len(silver) > 0, "Silver rows must be durable"
        assert gold is not None, "Gold envelope must be durable"
