"""The hourly reconcile's own completion line becomes an honest count (#1857, W8-F / P10-6).

Before this slice, `mock_analytics_reconcile_orchestrated_completed` reported only
`fetch_plan_size` -- the size of the REQUESTED plan -- even though
`SharedComputeOrchestrator.run` already returns a `SharedComputeResult` carrying
`bronze_appended` / `silver_promoted`. A reader of the task's own line could not
tell a genuinely-empty cycle from a full one. This suite pins:

* a nonzero cycle's `bronze_appended` / `silver_promoted` on the emitted line,
  proven through a collaborator bound to the real `run_shared_compute_job`
  signature returning a real `SharedComputeResult` (not a canned double);
* a genuinely-zero cycle's counts are PRESENT as the number `0`, not absent --
  proven at least once through the real `SharedComputeOrchestrator.run`
  pipeline (bronze -> silver -> gold) on real Postgres, so the wiring under
  test is the real orchestrator, not a fake standing in for it;
* `fetch_plan_size` survives alongside the new counts -- it answers a
  different question (requested vs. written);
* a mid-pipeline crash records the counts as explicitly UNKNOWN (`None`),
  never a fabricated `0`, and still re-raises.

Every assertion reads the EMITTED log record (`caplog`), never the module
source. `asyncio_mode = auto` (pytest.ini) -- test coroutines run without
`@pytest.mark.asyncio`.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.observability.logging import JsonFormatter
from juli_backend.database.database import Base
from juli_backend.models.models import (
    AnalyticsPerformanceInterval,
    BronzeOrderRawPayload,
    GoldKpiEnvelope,
    Order,
    Shop,
    User,
)
from juli_backend.services.cdp_speed import (
    SharedComputeJob,
    SharedComputeResult,
    job_correlation_token,
    run_shared_compute_job,
)
from juli_backend.services.cdp_speed.targeted_fetch_bronze_handoff import (
    BronzeAppendTracker,
    make_targeted_fetch_bronze_handoff,
)
from juli_backend.workers.tasks.mock_analytics_reconcile import (
    run_mock_analytics_reconcile_orchestrated,
)
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

_EVENT = "mock_analytics_reconcile_orchestrated_completed"
_ORCHESTRATOR_EVENT = "shared_compute_job_completed"


def _completion_record(caplog):
    return next(r for r in caplog.records if r.message == _EVENT)


def _fake_clock(*ticks: float):
    values = iter(ticks)

    def _clock() -> float:
        return next(values)

    return _clock


# --- SQLite medallion fixture, mirroring the house pattern already proven in
# --- test_mock_analytics_hourly_reconcile.py (self-contained here: that file
# --- must pass untouched per #1857's scope). -------------------------------


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
                    AnalyticsPerformanceInterval.__table__,
                    GoldKpiEnvelope.__table__,
                ],
            )
        )
    factory = async_sessionmaker(eng, expire_on_commit=False)
    async with factory() as session:
        user = User(phone="+84901234857", display_name="1857 Reconcile Test User")
        session.add(user)
        await session.flush()
        shop = Shop(user_id=user.id, shop_name="1857 Reconcile Shop", tiktok_shop_id="shop_1857")
        session.add(shop)
        await session.flush()
        yield session, shop
        await session.rollback()
    await eng.dispose()


_ORDER_ID_1857 = "1857000000000001"


async def _one_order_fetch_executor(
    session, *, shop_id, shop_key, fetch_plan, idempotency_key
) -> BronzeAppendTracker:
    """Bound to the real `TargetedFetchExecutor` signature. Hands one order row
    to bronze so `bronze_appended`/`silver_promoted` are genuinely nonzero."""
    del shop_key
    tracker = BronzeAppendTracker()
    if fetch_plan.is_empty:
        return tracker
    handoff = make_targeted_fetch_bronze_handoff(
        session,
        shop_id=shop_id,
        job_token=job_correlation_token(shop_id, idempotency_key),
        tracker=tracker,
        clock=lambda: datetime(2026, 9, 14, 12, 0, tzinfo=UTC),
    )
    fixture_order = {
        "order_id": _ORDER_ID_1857,
        "order_status": "AWAITING_SHIPMENT",
        "total_amount": "50000.00",
        "currency": "VND",
        "update_time": int(datetime(2026, 9, 14, 12, 0, tzinfo=UTC).timestamp()),
    }
    for resource in fetch_plan.resources:
        if resource.resource_attr == "orders":
            await handoff("tiktok.orders.raw", "test-shop", json.dumps(fixture_order).encode())
    return tracker


async def _empty_fetch_executor(
    session, *, shop_id, shop_key, fetch_plan, idempotency_key
) -> BronzeAppendTracker:
    """Bound to the real `TargetedFetchExecutor` signature; appends nothing --
    the genuinely-empty cycle this slice must NOT report as `0` for free."""
    del session, shop_id, shop_key, fetch_plan, idempotency_key
    return BronzeAppendTracker()


# --- nonzero cycle: real run_shared_compute_job, real SharedComputeResult --


async def test_nonzero_cycle_reports_bronze_and_silver_counts(medallion_session, caplog):
    session, shop = medallion_session

    async def via_real_orchestrator(job: SharedComputeJob) -> SharedComputeResult:
        return await run_shared_compute_job(session, job, fetch_executor=_one_order_fetch_executor)

    with caplog.at_level(logging.INFO):
        await run_mock_analytics_reconcile_orchestrated(
            session=session,
            shop_id=shop.id,
            shop_key=shop.tiktok_shop_id,
            orchestrator_run_fn=via_real_orchestrator,
            clock=_fake_clock(10.0, 10.02),
        )

    record = _completion_record(caplog)
    assert record.bronze_appended == 1
    assert record.silver_promoted == 1
    assert record.fetch_plan_size > 0
    assert record.duration_ms == int((10.02 - 10.0) * 1000)
    assert record.status == "succeeded"


# --- fetch_plan_size survives alongside the new counts ---------------------


async def test_fetch_plan_size_and_new_counts_coexist_on_the_same_line(medallion_session, caplog):
    session, shop = medallion_session

    async def via_real_orchestrator(job: SharedComputeJob) -> SharedComputeResult:
        return await run_shared_compute_job(session, job, fetch_executor=_one_order_fetch_executor)

    with caplog.at_level(logging.INFO):
        await run_mock_analytics_reconcile_orchestrated(
            session=session,
            shop_id=shop.id,
            shop_key=shop.tiktok_shop_id,
            orchestrator_run_fn=via_real_orchestrator,
        )

    record = _completion_record(caplog)
    # fetch_plan_size answers "what was requested"; bronze_appended answers
    # "what was written" -- both questions, both present, on the same line.
    from juli_backend.workers.tasks.mock_analytics_reconcile import (
        _make_hourly_gap_fetch_plan,
    )

    expected_plan_size = len(_make_hourly_gap_fetch_plan(shop.tiktok_shop_id).resources)
    assert record.fetch_plan_size == expected_plan_size
    assert record.bronze_appended == 1


# --- mid-pipeline crash: counts are explicitly unknown, never a fabricated 0 -


async def test_crash_during_orchestration_records_unknown_counts_and_reraises(
    medallion_session, caplog
):
    session, shop = medallion_session

    async def crashing_orchestrator(job: SharedComputeJob) -> SharedComputeResult:
        raise RuntimeError("silver stage exploded")

    with caplog.at_level(logging.INFO):
        with pytest.raises(RuntimeError, match="silver stage exploded"):
            await run_mock_analytics_reconcile_orchestrated(
                session=session,
                shop_id=shop.id,
                shop_key=shop.tiktok_shop_id,
                orchestrator_run_fn=crashing_orchestrator,
                clock=_fake_clock(20.0, 20.03),
            )

    completion_records = [r for r in caplog.records if r.message == _EVENT]
    assert len(completion_records) == 1
    record = completion_records[0]
    assert record.bronze_appended is None
    assert record.silver_promoted is None
    assert record.status == "failed"
    assert record.duration_ms == int((20.03 - 20.0) * 1000)


# --- one valid JSON object per line, including the None-valued fields ------


async def test_completion_record_with_unknown_counts_still_formats_as_valid_json(
    medallion_session, caplog
):
    session, shop = medallion_session

    async def crashing_orchestrator(job: SharedComputeJob) -> SharedComputeResult:
        raise RuntimeError("boom")

    with caplog.at_level(logging.INFO):
        with pytest.raises(RuntimeError):
            await run_mock_analytics_reconcile_orchestrated(
                session=session,
                shop_id=shop.id,
                shop_key=shop.tiktok_shop_id,
                orchestrator_run_fn=crashing_orchestrator,
            )

    record = next(r for r in caplog.records if r.message == _EVENT)
    formatted = JsonFormatter().format(record)
    assert "\n" not in formatted.strip("\n")
    payload = json.loads(formatted)
    assert payload["bronze_appended"] is None
    assert payload["silver_promoted"] is None


# --- genuinely-zero cycle, through the REAL orchestrator, on REAL Postgres -


def _seed_shop(engine) -> uuid.UUID:
    """Owner-side seed (set-up, not the thing under test), mirroring the
    pattern in test_action_card_refresh_task_scope.py / test_agent_run_shop_id_bootstrap.py."""
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id, shop_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1857{user_id.hex[:7]}", "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO public.shops "
                "(id, user_id, shop_name, tiktok_shop_id, is_active, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, :tiktok_id, true, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "user_id": str(user_id),
                "name": "1857 Postgres Reconcile Shop",
                "tiktok_id": f"tt-1857-{shop_id.hex[:10]}",
                "now": now,
            },
        )
    return shop_id


@requires_postgres
async def test_real_orchestrator_zero_cycle_on_postgres_reports_present_zeros(caplog):
    """At least one assertion goes through the REAL SharedComputeOrchestrator.run
    pipeline (bronze -> silver -> gold) against real Postgres -- proving the
    wiring, not a fake standing in for it. `SharedComputeOrchestrator.run`
    commits per stage and re-enters `with_shop_scope` around each one, which
    only real Postgres (not SQLite) behaviour can exercise (#1576).
    """
    with owner_sync_engine() as owner_engine:
        shop_id = _seed_shop(owner_engine)

    async with juli_app_async_sessionmaker() as sessionmaker:
        async with sessionmaker() as session:
            with caplog.at_level(logging.INFO):
                await run_mock_analytics_reconcile_orchestrated(
                    session=session,
                    shop_id=shop_id,
                    shop_key=f"tt-1857-{shop_id.hex[:10]}",
                    fetch_executor=_empty_fetch_executor,
                    clock=_fake_clock(50.0, 50.07),
                )
            await session.commit()

    record = _completion_record(caplog)
    assert record.bronze_appended == 0
    assert record.silver_promoted == 0
    assert record.fetch_plan_size > 0
    assert record.duration_ms == int((50.07 - 50.0) * 1000)
    assert record.status == "succeeded"

    # Cross-checked against the orchestrator's own line for the same cycle,
    # not read alone (mirrors the plan's post-deploy pairing rule).
    orchestrator_record = next(r for r in caplog.records if r.message == _ORCHESTRATOR_EVENT)
    assert orchestrator_record.bronze_appended == record.bronze_appended
    assert orchestrator_record.silver_promoted == record.silver_promoted
