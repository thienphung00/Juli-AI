"""#880 follow-up — SharedComputeOrchestrator silver stage must promote ctor/live_hours.

Coordinator finding: ``ctor_row_ids`` / ``live_hours_row_ids`` were populated on
``BronzeAppendTracker`` but ``_default_silver_stage`` only ever dispatched on
``order_row_ids`` / ``return_row_ids`` by name — bronze rows landed and nothing
ever promoted them to ``analytics_performance_intervals``. This file proves the
wiring: bronze rows go in, ``analytics_performance_intervals`` rows come out,
and ``silver_promoted`` counts them.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.database.database import Base
from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    BronzeCtorPerformanceRawPayload,
    BronzeLiveHoursRawPayload,
    GoldKpiEnvelope,
    Order,
    Shop,
    User,
)
from juli_backend.services.cdp_speed.job_correlation import job_correlation_token
from juli_backend.services.cdp_speed.shared_compute_orchestrator import (
    SharedComputeJob,
    SharedComputeOrchestrator,
    run_shared_compute_job,
)
from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import (
    BronzeAppendTracker,
    make_targeted_fetch_bronze_handoff,
)
from juli_backend.services.cdp_speed.targeted_fetch_planner import FetchResource, TargetedFetchPlan

FIXED_CLOCK = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
SYNCED_AT = int(FIXED_CLOCK.timestamp())


def _ctor_row() -> dict:
    return {
        "grain": "product",
        "start_date": "2026-08-10",
        "end_date": "2026-08-11",
        "update_time": SYNCED_AT,
        "snapshot_key": "product|2026-08-10|2026-08-11||prod-orch-880||",
        "product_id": "prod-orch-880",
        "gmv": "500000.00",
        "gmv_currency": "VND",
        "click_order_rate": "0.0900",
    }


def _live_session_row() -> dict:
    return {
        "grain": "live",
        "start_date": "2026-08-10",
        "end_date": "2026-08-11",
        "update_time": SYNCED_AT,
        "snapshot_key": "live|2026-08-10|2026-08-11|||live-orch-880",
        "live_id": "live-orch-880",
        "gmv": "80000.00",
        "gmv_currency": "VND",
    }


def _live_shop_rollup_row() -> dict:
    return {
        "grain": "shop",
        "start_date": "2026-08-10",
        "end_date": "2026-08-11",
        "update_time": SYNCED_AT,
        "snapshot_key": "shop|2026-08-10|2026-08-11||||",
        "live_hours": "2.5000",
        "live_sessions": 1,
    }


async def _fake_analytics_fetch_executor(
    session,
    *,
    shop_id: uuid.UUID,
    shop_key: str,
    fetch_plan,
    idempotency_key: str,
) -> BronzeAppendTracker:
    """Test-only fetch boundary: hand off fixture ctor/live_hours rows to bronze."""
    del shop_key
    tracker = BronzeAppendTracker()
    if fetch_plan.is_empty:
        return tracker

    handoff = make_targeted_fetch_bronze_handoff(
        session,
        shop_id=shop_id,
        job_token=job_correlation_token(shop_id, idempotency_key),
        tracker=tracker,
        clock=lambda: FIXED_CLOCK,
    )
    for resource in fetch_plan.resources:
        if resource.resource_attr == "ctor":
            await handoff(
                "tiktok.analytics.product.raw",
                "test-shop",
                json.dumps(_ctor_row()).encode(),
            )
        elif resource.resource_attr == "live_hours":
            await handoff(
                "tiktok.analytics.live.raw",
                "test-shop",
                json.dumps(_live_session_row()).encode(),
            )
            await handoff(
                "tiktok.analytics.live.raw",
                "test-shop",
                json.dumps(_live_shop_rollup_row()).encode(),
            )
    return tracker


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
                    BronzeCtorPerformanceRawPayload.__table__,
                    BronzeLiveHoursRawPayload.__table__,
                    AnalyticsPerformanceInterval.__table__,
                    GoldKpiEnvelope.__table__,
                ],
            )
        )
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as session:
        user = User(phone="+84901234880", display_name="Silver Analytics Orchestrator User")
        session.add(user)
        await session.flush()
        shop = Shop(
            user_id=user.id,
            shop_name="Silver Analytics Orchestrator Shop",
            tiktok_shop_id="shop_880",
        )
        session.add(shop)
        await session.flush()
        yield session, shop
        await session.rollback()
    await eng.dispose()


def _ctor_live_hours_job(shop: Shop, *, idempotency_key: str = "job-880-a") -> SharedComputeJob:
    fetch_plan = TargetedFetchPlan(
        catalog_id=None,
        shop_id=shop.tiktok_shop_id,
        resources=(
            FetchResource("ctor", "/analytics/202309/products/performance", "ctor"),
            FetchResource("live_hours", "/analytics/202309/shop_lives/performance", "live_hours"),
        ),
    )
    return SharedComputeJob(
        shop_id=shop.id,
        shop_key=shop.tiktok_shop_id,
        enqueue_reason="scheduled_reconcile",
        fetch_plan=fetch_plan,
        idempotency_key=idempotency_key,
    )


@pytest.mark.asyncio
async def test_silver_stage_promotes_ctor_and_live_hours_bronze_rows(medallion_session):
    """RED against the pre-wiring branch head: bronze rows land, nothing promotes
    them, ``analytics_performance_intervals`` stays empty and ``silver_promoted``
    stays 0 even though 3 bronze rows were appended. GREEN once
    ``_default_silver_stage`` dispatches on ``ctor_row_ids`` / ``live_hours_row_ids``."""
    session, shop = medallion_session

    result = await run_shared_compute_job(
        session,
        _ctor_live_hours_job(shop),
        fetch_executor=_fake_analytics_fetch_executor,
    )

    assert result.bronze_appended == 3  # 1 ctor product row + 2 live_hours rows
    assert result.silver_promoted == 3

    rows = (
        (
            await session.execute(
                select(AnalyticsPerformanceInterval).where(
                    AnalyticsPerformanceInterval.shop_id == shop.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 3

    by_grain = {row.grain: row for row in rows if row.grain != "live"}
    assert by_grain["product"].tiktok_product_id == "prod-orch-880"
    assert by_grain["product"].click_order_rate is not None
    assert by_grain["shop"].live_hours is not None

    live_rows = [row for row in rows if row.grain == "live"]
    assert len(live_rows) == 1
    assert live_rows[0].tiktok_live_id == "live-orch-880"


@pytest.mark.asyncio
async def test_silver_stage_ctor_live_hours_promotion_is_idempotent_on_replay(medallion_session):
    session, shop = medallion_session
    job = _ctor_live_hours_job(shop, idempotency_key="job-880-replay")

    first = await run_shared_compute_job(
        session, job, fetch_executor=_fake_analytics_fetch_executor
    )
    second = await run_shared_compute_job(
        session, job, fetch_executor=_fake_analytics_fetch_executor
    )

    assert first.bronze_appended == 3
    assert second.bronze_appended == 0  # same idempotency key -> bronze dedup
    assert first.silver_promoted == 3

    rows = (
        (
            await session.execute(
                select(AnalyticsPerformanceInterval).where(
                    AnalyticsPerformanceInterval.shop_id == shop.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 3  # no duplicates on replay


@pytest.mark.asyncio
async def test_silver_stage_direct_call_dispatches_ctor_and_live_hours_by_tracker_field(
    medallion_session,
):
    """Isolate the silver stage from bronze/gold: directly seed bronze rows and a
    tracker, call ``_default_silver_stage``, and assert it dispatches on the new
    tracker fields (not just ``order_row_ids`` / ``return_row_ids`` by name)."""
    session, shop = medallion_session

    ctor_row = BronzeCtorPerformanceRawPayload(
        shop_id=shop.id,
        ingest_source="targeted_fetch",
        payload=_ctor_row(),
        tiktok_product_id="prod-orch-880",
        source_event_id="direct:ctor:prod-orch-880",
    )
    live_row = BronzeLiveHoursRawPayload(
        shop_id=shop.id,
        ingest_source="targeted_fetch",
        payload=_live_shop_rollup_row(),
        tiktok_live_id=None,
        source_event_id="direct:live_hours:shop",
    )
    session.add_all([ctor_row, live_row])
    await session.flush()

    tracker = BronzeAppendTracker(
        ctor_row_ids=[ctor_row.id],
        live_hours_row_ids=[live_row.id],
    )

    promoted = await SharedComputeOrchestrator._default_silver_stage(session, shop.id, tracker)

    assert promoted == 2

    rows = (
        (
            await session.execute(
                select(AnalyticsPerformanceInterval).where(
                    AnalyticsPerformanceInterval.shop_id == shop.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
