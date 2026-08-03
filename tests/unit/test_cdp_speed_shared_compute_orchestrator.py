"""Issue #627 — Shared Compute Orchestrator contract tests (CDP-A1-3).

Fixtures live here only — production code must not fabricate Partner payloads.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.database.database import Base
from juli_backend.models.models import (
    BronzeOrderRawPayload,
    GoldKpiEnvelope,
    Order,
    Shop,
    User,
)
from juli_backend.repositories.repos import OrdersRepo
from juli_backend.services.cdp_speed import (
    job_correlation_token,
    plan_targeted_fetch,
    webhook_catalog_enqueue_reason,
)
from juli_backend.services.cdp_speed.shared_compute_orchestrator import (
    SharedComputeJob,
    SharedComputeOrchestrator,
    run_shared_compute_job,
)
from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import (
    BronzeAppendTracker,
    make_targeted_fetch_bronze_handoff,
)

TEST_ORDER_ID = "577000000000627"


async def _fake_orders_fetch_executor(
    session,
    *,
    shop_id: uuid.UUID,
    shop_key: str,
    fetch_plan,
    idempotency_key: str,
) -> BronzeAppendTracker:
    """Test-only fetch boundary: hand off fixture Partner order rows to bronze."""
    del shop_key
    tracker = BronzeAppendTracker()
    if fetch_plan.is_empty:
        return tracker

    handoff = make_targeted_fetch_bronze_handoff(
        session,
        shop_id=shop_id,
        job_token=job_correlation_token(shop_id, idempotency_key),
        tracker=tracker,
        clock=lambda: datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
    )
    fixture_order = {
        "order_id": TEST_ORDER_ID,
        "order_status": "AWAITING_SHIPMENT",
        "total_amount": "120000.00",
        "currency": "VND",
        "update_time": int(datetime(2026, 7, 31, 12, 0, tzinfo=UTC).timestamp()),
    }
    for resource in fetch_plan.resources:
        if resource.resource_attr == "orders":
            await handoff(
                "tiktok.orders.raw",
                "test-shop",
                json.dumps(fixture_order).encode(),
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
                    BronzeOrderRawPayload.__table__,
                    GoldKpiEnvelope.__table__,
                ],
            )
        )
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as session:
        user = User(phone="+84901234627", display_name="Orchestrator Test User")
        session.add(user)
        await session.flush()
        shop = Shop(
            user_id=user.id,
            shop_name="Orchestrator Test Shop",
            tiktok_shop_id="shop_627",
        )
        session.add(shop)
        await session.flush()
        yield session, shop
        await session.rollback()
    await eng.dispose()


def _order_status_job(shop: Shop, *, idempotency_key: str = "job-627-a") -> SharedComputeJob:
    fetch_plan = plan_targeted_fetch(
        event_type="ORDER_STATUS_CHANGE",
        shop_id=shop.tiktok_shop_id,
    )
    return SharedComputeJob(
        shop_id=shop.id,
        shop_key=shop.tiktok_shop_id,
        enqueue_reason=webhook_catalog_enqueue_reason(1),
        fetch_plan=fetch_plan,
        idempotency_key=idempotency_key,
        event_type="ORDER_STATUS_CHANGE",
    )


@pytest.mark.asyncio
async def test_runs_bronze_silver_gold_in_order(medallion_session, caplog):
    session, shop = medallion_session
    stage_log: list[str] = []

    async def track_bronze(sess, job):
        stage_log.append("bronze")
        inner = SharedComputeOrchestrator(sess, fetch_executor=_fake_orders_fetch_executor)
        return await inner._default_bronze_stage(sess, job)

    async def track_silver(*args, **kwargs):
        stage_log.append("silver")
        return await SharedComputeOrchestrator._default_silver_stage(*args, **kwargs)

    async def track_gold(*args, **kwargs):
        stage_log.append("gold")
        return await SharedComputeOrchestrator._default_gold_stage(*args, **kwargs)

    orchestrator = SharedComputeOrchestrator(
        session,
        fetch_executor=_fake_orders_fetch_executor,
        bronze_stage=track_bronze,
        silver_stage=track_silver,
        gold_stage=track_gold,
    )

    with caplog.at_level(logging.INFO):
        result = await orchestrator.run(_order_status_job(shop))

    assert stage_log == ["bronze", "silver", "gold"]
    assert result.bronze_appended >= 1
    assert result.silver_promoted >= 1
    assert result.gold_written is True


@pytest.mark.asyncio
async def test_fixture_fetch_boundary_bronze_to_silver_orders(medallion_session):
    """Fetch fake → bronze append → silver upsert for orders (no live Partner)."""
    session, shop = medallion_session
    result = await run_shared_compute_job(
        session,
        _order_status_job(shop),
        fetch_executor=_fake_orders_fetch_executor,
    )

    assert result.silver_promoted >= 1

    orders = await OrdersRepo(session).list(shop.id)
    assert len(orders) == 1
    assert orders[0].tiktok_order_id == TEST_ORDER_ID

    bronze_rows = (
        (
            await session.execute(
                select(BronzeOrderRawPayload).where(BronzeOrderRawPayload.shop_id == shop.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(bronze_rows) == 1
    assert bronze_rows[0].ingest_source == "targeted_fetch"
    assert bronze_rows[0].payload["order_id"] == TEST_ORDER_ID

    gold = await session.get(GoldKpiEnvelope, shop.id)
    assert gold is not None
    assert "kpis" in gold.payload


@pytest.mark.asyncio
async def test_same_idempotency_key_skips_duplicate_bronze(medallion_session):
    session, shop = medallion_session
    job = _order_status_job(shop, idempotency_key="job-627-same")

    first = await run_shared_compute_job(session, job, fetch_executor=_fake_orders_fetch_executor)
    second = await run_shared_compute_job(session, job, fetch_executor=_fake_orders_fetch_executor)

    assert first.bronze_appended == 1
    assert second.bronze_appended == 0
    assert first.silver_promoted == 1
    assert second.silver_promoted == 0

    orders = await OrdersRepo(session).list(shop.id)
    assert len(orders) == 1


@pytest.mark.asyncio
async def test_distinct_idempotency_keys_allow_new_trigger(medallion_session):
    session, shop = medallion_session

    await run_shared_compute_job(
        session,
        _order_status_job(shop, idempotency_key="job-627-first"),
        fetch_executor=_fake_orders_fetch_executor,
    )
    result = await run_shared_compute_job(
        session,
        _order_status_job(shop, idempotency_key="job-627-second"),
        fetch_executor=_fake_orders_fetch_executor,
    )

    assert result.bronze_appended == 1
    bronze_count = (
        (
            await session.execute(
                select(BronzeOrderRawPayload).where(BronzeOrderRawPayload.shop_id == shop.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(bronze_count) == 2
    assert len(await OrdersRepo(session).list(shop.id)) == 1


@pytest.mark.asyncio
async def test_structured_logs_include_enqueue_reason_and_fetch_plan_size(
    medallion_session, caplog
):
    session, shop = medallion_session
    job = _order_status_job(shop)

    with caplog.at_level(logging.INFO):
        await run_shared_compute_job(session, job, fetch_executor=_fake_orders_fetch_executor)

    start_records = [r for r in caplog.records if r.getMessage() == "shared_compute_job_started"]
    assert len(start_records) == 1
    start_record = start_records[0]
    assert getattr(start_record, "enqueue_reason", None) == webhook_catalog_enqueue_reason(1)
    assert getattr(start_record, "fetch_plan_size", None) == len(job.fetch_plan.resources)
    assert getattr(start_record, "correlation_id", None)
    assert not getattr(start_record, "shop_key", None)

    forbidden = ("access_token", "app_secret", "password", "+849", "shop_627")
    logged = " ".join(r.getMessage() + str(getattr(r, "__dict__", {})) for r in caplog.records)
    for token in forbidden:
        assert token not in logged


def test_orchestrator_forbids_full_poll_a2_batch_io_and_fleet_defer_wiring():
    import juli_backend.services.cdp_speed.shared_compute_orchestrator as orch
    import juli_backend.services.cdp_speed.targeted_fetch_executor as executor
    import juli_backend.services.cdp_speed.targeted_fetch_sync as sync_mod

    for module in (orch, executor, sync_mod):
        source = open(module.__file__, encoding="utf-8").read()
        for token in (
            "run_fujiwa_poll_cycle",
            "run_fujiwa_material_resource_fetch",
            "_FUJIWA_POLL_STEPS",
            "cdp_batch",
            "PostgresIOBudgetGovernor",
            "fleet_defer",
            "workers.services.polling",
            "workers.services",
        ):
            assert token not in source


def test_production_modules_contain_no_test_fixture_constants():
    import juli_backend.services.cdp_speed.shared_compute_orchestrator as orch
    import juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff as handoff
    import juli_backend.services.cdp_speed.targeted_fetch_executor as executor

    for module in (orch, executor, handoff):
        source = open(module.__file__, encoding="utf-8").read()
        assert TEST_ORDER_ID not in source
        assert "577000000000627" not in source
        assert "_fixture_order_payload" not in source


def test_accepts_targeted_fetch_plan_enqueue_reason_and_idempotency_key():
    fetch_plan = plan_targeted_fetch(event_type="ORDER_STATUS_CHANGE", shop_id="shop_627")
    shop_id = uuid.uuid4()
    job = SharedComputeJob(
        shop_id=shop_id,
        shop_key="shop_627",
        enqueue_reason="reconcile_hourly",
        fetch_plan=fetch_plan,
        idempotency_key="celery-task-abc",
        event_type="ORDER_STATUS_CHANGE",
    )
    assert job.enqueue_reason == "reconcile_hourly"
    assert job.idempotency_key == "celery-task-abc"
    assert len(job_correlation_token(shop_id, job.idempotency_key)) == 16
    assert not fetch_plan.is_empty


@pytest.mark.asyncio
async def test_empty_fetch_plan_still_completes_gold_stage(medallion_session):
    session, shop = medallion_session
    empty_plan = plan_targeted_fetch(event_type="PACKAGE_UPDATE", shop_id=shop.tiktok_shop_id)
    assert empty_plan.is_empty

    job = SharedComputeJob(
        shop_id=shop.id,
        shop_key=shop.tiktok_shop_id,
        enqueue_reason=webhook_catalog_enqueue_reason(1),
        fetch_plan=empty_plan,
        idempotency_key="job-empty",
    )
    result = await run_shared_compute_job(session, job, fetch_executor=_fake_orders_fetch_executor)

    assert result.bronze_appended == 0
    assert result.silver_promoted == 0
    assert result.gold_written is True
    assert await session.get(GoldKpiEnvelope, shop.id) is not None


@pytest.mark.asyncio
async def test_missing_env_skips_fetch_but_completes_gold_stage(medallion_session, monkeypatch):
    session, shop = medallion_session
    monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
    monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)
    monkeypatch.delenv("TIKTOK_REDIRECT_URI", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    result = await run_shared_compute_job(session, _order_status_job(shop))

    assert result.bronze_appended == 0
    assert result.silver_promoted == 0
    assert result.gold_written is True
    assert await session.get(GoldKpiEnvelope, shop.id) is not None
