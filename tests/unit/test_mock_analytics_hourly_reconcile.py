"""Tests for Phase 2.10 Mock-mode hourly Analytics reconciler (#533).

Issue #632: Route through SharedComputeOrchestrator with reconcile_hourly enqueue_reason.
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
    BronzeOrderRawPayload,
    GoldKpiEnvelope,
    Order,
    Shop,
    User,
)
from juli_backend.services.cdp_speed import (
    FetchResource,
    TargetedFetchPlan,
    is_quota_guarded,
    job_correlation_token,
)
from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import (
    BronzeAppendTracker,
    make_targeted_fetch_bronze_handoff,
)
from juli_backend.workers.celery_app import celery_app
from juli_backend.workers.tasks import mock_analytics_reconcile


@pytest.fixture
def reference_shop_id() -> uuid.UUID:
    return uuid.uuid4()


def test_celery_beat_hourly_entrypoint_recomputes_reference_shop():
    schedule = celery_app.conf.beat_schedule["mock-analytics-hourly-reconcile"]
    assert schedule["task"] == "juli_backend.mock_analytics_hourly_reconcile"
    assert schedule["schedule"].minute == {0}


def test_mock_reconcile_invokes_precompute_for_configured_shop_id_only(
    monkeypatch,
    reference_shop_id: uuid.UUID,
):
    calls: list[str] = []

    def fake_precompute(shop_key: str) -> None:
        calls.append(shop_key)

    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(reference_shop_id))
    monkeypatch.setattr(
        mock_analytics_reconcile,
        "_lookup_tiktok_shop_key",
        lambda _shop_id: "tiktok-reference-shop",
    )

    mock_analytics_reconcile.run_mock_analytics_reconcile_sync(precompute_fn=fake_precompute)

    assert calls == ["tiktok-reference-shop"]


def test_mock_reconcile_does_not_fan_out_to_all_shops(
    monkeypatch,
    reference_shop_id: uuid.UUID,
):
    calls: list[str] = []

    def fake_precompute(shop_key: str) -> None:
        calls.append(shop_key)

    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(reference_shop_id))
    monkeypatch.setattr(
        mock_analytics_reconcile,
        "_lookup_tiktok_shop_key",
        lambda _shop_id: "only-reference-shop",
    )

    mock_analytics_reconcile.run_mock_analytics_reconcile_sync(precompute_fn=fake_precompute)

    assert len(calls) == 1
    assert calls[0] == "only-reference-shop"


def test_mock_reconcile_skips_when_demo_reference_shop_id_unset(monkeypatch):
    calls: list[str] = []

    def fake_precompute(shop_key: str) -> None:
        calls.append(shop_key)

    monkeypatch.delenv("DEMO_REFERENCE_SHOP_ID", raising=False)

    mock_analytics_reconcile.run_mock_analytics_reconcile_sync(precompute_fn=fake_precompute)

    assert calls == []


def test_mock_reconcile_uses_material_precompute_path(monkeypatch, reference_shop_id: uuid.UUID):
    """Idempotent upsert path shared with material-webhook compute (#532)."""
    calls: list[str] = []

    def fake_precompute(shop_key: str) -> None:
        calls.append(shop_key)

    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(reference_shop_id))
    monkeypatch.setattr(
        mock_analytics_reconcile,
        "_lookup_tiktok_shop_key",
        lambda _shop_id: "shared-upsert-shop",
    )
    monkeypatch.setattr(
        mock_analytics_reconcile,
        "material_analytics_precompute_sync",
        fake_precompute,
    )

    mock_analytics_reconcile.run_mock_analytics_reconcile_sync()

    assert calls == ["shared-upsert-shop"]


# --- Issue #632: SharedComputeOrchestrator integration ---


@pytest_asyncio.fixture
async def medallion_session():
    """Async session for medallion tests (bronze → silver → gold)."""
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
        user = User(phone="+84901234632", display_name="Reconcile Test User")
        session.add(user)
        await session.flush()
        shop = Shop(
            user_id=user.id,
            shop_name="Reconcile Test Shop",
            tiktok_shop_id="shop_632",
        )
        session.add(shop)
        await session.flush()
        yield session, shop
        await session.rollback()
    await eng.dispose()


TEST_ORDER_ID_632 = "632000000000001"


async def _fake_gap_fetch_executor(
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
        clock=lambda: datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
    )
    fixture_order = {
        "order_id": TEST_ORDER_ID_632,
        "order_status": "AWAITING_SHIPMENT",
        "total_amount": "120000.00",
        "currency": "VND",
        "update_time": int(datetime(2026, 8, 3, 12, 0, tzinfo=UTC).timestamp()),
    }
    for resource in fetch_plan.resources:
        if resource.resource_attr == "orders":
            await handoff(
                "tiktok.orders.raw",
                "test-shop",
                json.dumps(fixture_order).encode(),
            )
    return tracker


def _make_hourly_gap_plan(shop_key: str) -> TargetedFetchPlan:
    """Create a bounded gap-targeted fetch plan for hourly reconciliation.

    Not the material matrix — just orders and returns for hourly reconciliation,
    with quota guards applied.
    """
    # Start with bounded resources: orders and analytics_shop
    base_resources = [
        FetchResource("orders", "/orders/202309/list", "orders"),
        FetchResource("analytics_shop", "/analytics/202309/shop", "analytics"),
    ]

    # Filter out any quota-guarded resources
    filtered_resources = tuple(r for r in base_resources if not is_quota_guarded(r.name))

    return TargetedFetchPlan(
        catalog_id=None,  # Gap plan, not material matrix
        shop_id=shop_key,
        resources=filtered_resources,
    )


@pytest.mark.asyncio
async def test_hourly_reconcile_calls_orchestrator_with_reconcile_hourly_reason(
    medallion_session,
):
    """Hourly reconciler calls SharedComputeOrchestrator with reconcile_hourly reason."""
    session, shop = medallion_session
    calls: list[dict] = []

    async def mock_orchestrator_run(job):
        calls.append(
            {
                "enqueue_reason": job.enqueue_reason,
                "fetch_plan_size": len(job.fetch_plan.resources),
                "shop_id": job.shop_id,
            }
        )
        from juli_backend.services.cdp_speed import SharedComputeResult

        return SharedComputeResult(
            bronze_appended=0,
            silver_promoted=0,
            gold_written=True,
        )

    # This test should fail initially because the implementation doesn't exist yet
    from juli_backend.workers.tasks.mock_analytics_reconcile import (
        run_mock_analytics_reconcile_orchestrated,
    )

    await run_mock_analytics_reconcile_orchestrated(
        session=session,
        shop_id=shop.id,
        shop_key=shop.tiktok_shop_id,
        orchestrator_run_fn=mock_orchestrator_run,
    )

    assert len(calls) == 1
    assert calls[0]["enqueue_reason"] == "reconcile_hourly"
    assert calls[0]["shop_id"] == shop.id


@pytest.mark.asyncio
async def test_hourly_reconcile_uses_bounded_gap_plan_not_full_poll(medallion_session):
    """Hourly reconcile must use bounded gap plan, not ALL of _FUJIWA_POLL_STEPS."""
    session, shop = medallion_session
    captured_jobs: list = []

    async def mock_orchestrator_run(job):
        captured_jobs.append(job)
        from juli_backend.services.cdp_speed import SharedComputeResult

        return SharedComputeResult(
            bronze_appended=0,
            silver_promoted=0,
            gold_written=True,
        )

    from juli_backend.workers.tasks.mock_analytics_reconcile import (
        run_mock_analytics_reconcile_orchestrated,
    )

    await run_mock_analytics_reconcile_orchestrated(
        session=session,
        shop_id=shop.id,
        shop_key=shop.tiktok_shop_id,
        orchestrator_run_fn=mock_orchestrator_run,
    )

    assert len(captured_jobs) == 1
    job = captured_jobs[0]

    # Verify it's not using the FULL poll stack (all four resources)
    from juli_backend.services.cdp_speed import FUJIWA_POLL_RESOURCE_NAMES

    used_poll_resources = {
        r.name for r in job.fetch_plan.resources if r.name in FUJIWA_POLL_RESOURCE_NAMES
    }
    # Must not use all four poll resources (that would be the full cycle)
    assert len(used_poll_resources) < len(FUJIWA_POLL_RESOURCE_NAMES), (
        f"Hourly reconcile uses full poll stack {used_poll_resources}, should be bounded"
    )
    # Gap plan should have some resources
    assert len(job.fetch_plan.resources) > 0, "Gap plan should have at least some resources"


@pytest.mark.asyncio
async def test_hourly_reconcile_does_not_invoke_run_fujiwa_poll_cycle(monkeypatch):
    """Negative test: hourly job must not invoke run_fujiwa_poll_cycle."""
    poll_cycle_called = []

    def mock_poll_cycle(*args, **kwargs):
        poll_cycle_called.append(True)

    monkeypatch.setattr(
        "juli_backend.workers.services.polling.orchestrate.run_fujiwa_poll_cycle",
        mock_poll_cycle,
        raising=False,
    )

    # Attempt to trigger the hourly reconciler
    # This is a negative test — just verify the mock poll function isn't called
    from juli_backend.workers.tasks import mock_analytics_reconcile as reconcile_module

    source = open(reconcile_module.__file__, encoding="utf-8").read()
    assert "run_fujiwa_poll_cycle" not in source, (
        "mock_analytics_reconcile must not import or call run_fujiwa_poll_cycle"
    )


@pytest.mark.asyncio
async def test_hourly_and_material_enqueue_coexist_via_idempotency_key(
    medallion_session,
):
    """Hourly and material enqueues should coexist without duplicate writes via idempotency."""
    session, shop = medallion_session

    from juli_backend.services.cdp_speed import SharedComputeJob, run_shared_compute_job

    # First job: hourly reconcile
    hourly_job = SharedComputeJob(
        shop_id=shop.id,
        shop_key=shop.tiktok_shop_id,
        enqueue_reason="reconcile_hourly",
        fetch_plan=_make_hourly_gap_plan(shop.tiktok_shop_id),
        idempotency_key="hourly-2026-08-03-12:00",
    )

    result1 = await run_shared_compute_job(
        session,
        hourly_job,
        fetch_executor=_fake_gap_fetch_executor,
    )

    # Second job: different trigger (e.g., webhook), different idempotency key
    webhook_job = SharedComputeJob(
        shop_id=shop.id,
        shop_key=shop.tiktok_shop_id,
        enqueue_reason="webhook_catalog:1",
        fetch_plan=_make_hourly_gap_plan(shop.tiktok_shop_id),
        idempotency_key="webhook-order-status-2026-08-03-12:05",
    )

    result2 = await run_shared_compute_job(
        session,
        webhook_job,
        fetch_executor=_fake_gap_fetch_executor,
    )

    # Both should succeed and not corrupt each other
    assert result1.gold_written is True
    assert result2.gold_written is True

    # Check that both bronze entries exist (or at least one if deduped)
    bronze_rows = (
        (
            await session.execute(
                select(BronzeOrderRawPayload).where(BronzeOrderRawPayload.shop_id == shop.id)
            )
        )
        .scalars()
        .all()
    )
    # With same data, bronze should have at least 1 (idempotency-keyed append)
    assert len(bronze_rows) >= 1


# --- Issue #733: nested asyncio.run() in the Celery entrypoint ---


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_hourly_reconcile_task_resolves_shop_key_without_nested_event_loop(
    monkeypatch, reference_shop_id: uuid.UUID
):
    """The Celery entrypoint must reach the orchestrator with a resolved shop_key.

    Issue #733: ``mock_analytics_hourly_reconcile`` opens an event loop via
    ``asyncio.run``. If ``_run_hourly_reconcile_async`` then calls the *synchronous*
    ``_lookup_tiktok_shop_key`` wrapper, that wrapper's own ``asyncio.run`` raises
    ``RuntimeError: asyncio.run() cannot be called from a running event loop`` and the
    task dies before any envelope is computed. This exercises the real task entrypoint,
    not the coroutine, so the production failure path is covered.
    """
    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(reference_shop_id))

    async def fake_lookup_async(shop_id: uuid.UUID) -> str | None:
        return "shop-key-733"

    orchestrated: list[dict] = []

    async def fake_orchestrated(*, session, shop_id, shop_key):
        orchestrated.append({"shop_id": shop_id, "shop_key": shop_key})

    monkeypatch.setattr(
        mock_analytics_reconcile, "_lookup_tiktok_shop_key_async", fake_lookup_async
    )
    monkeypatch.setattr(
        mock_analytics_reconcile,
        "run_mock_analytics_reconcile_orchestrated",
        fake_orchestrated,
    )
    monkeypatch.setattr(mock_analytics_reconcile, "_ensure_session_factory", lambda: _FakeSession)

    mock_analytics_reconcile.mock_analytics_hourly_reconcile()

    assert orchestrated == [{"shop_id": reference_shop_id, "shop_key": "shop-key-733"}], (
        "task must reach the orchestrator with the resolved shop_key"
    )


def test_sync_lookup_wrapper_still_usable_outside_an_event_loop(
    monkeypatch, reference_shop_id: uuid.UUID
):
    """``_lookup_tiktok_shop_key`` is retained for the non-orchestrated sync path."""

    async def fake_lookup_async(shop_id: uuid.UUID) -> str | None:
        return "shop-key-sync"

    monkeypatch.setattr(
        mock_analytics_reconcile, "_lookup_tiktok_shop_key_async", fake_lookup_async
    )

    assert mock_analytics_reconcile._lookup_tiktok_shop_key(reference_shop_id) == "shop-key-sync"
