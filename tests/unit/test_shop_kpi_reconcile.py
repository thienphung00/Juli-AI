"""Hourly KPI envelope recompute per shop (fast track P61-D, D71.4) -- no-DB unit tests.

Replaces the reference-shop-only `mock_analytics_reconcile` tests. The two-shop
proof on real Postgres as `juli_app` is
`tests/integration/test_shop_kpi_reconcile_two_tenant.py`.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from juli_backend.services.cdp_speed import SharedComputeResult
from juli_backend.workers.tasks import shop_kpi_reconcile as module

_LOGGER = "juli_backend.workers.tasks.shop_kpi_reconcile"


@dataclass(frozen=True)
class _Shop:
    shop_id: uuid.UUID
    fast_done: bool


def _records(caplog, message: str):
    return [r for r in caplog.records if r.name == _LOGGER and r.getMessage() == message]


# -- fan-out ------------------------------------------------------------------


async def test_fanout_enqueues_one_task_per_shop_past_its_fast_phase(caplog):
    caplog.set_level(logging.INFO, logger=_LOGGER)
    a, b, cold = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    shops = [_Shop(a, True), _Shop(b, True), _Shop(cold, False)]
    enqueued: list[str] = []

    async def enumerate_fn(_session):
        return shops

    count = await module.run_fanout(object(), enqueue=enqueued.append, enumerate_fn=enumerate_fn)

    assert count == 2
    assert enqueued == [str(a), str(b)]
    (summary,) = _records(caplog, "shop_kpi_reconcile_fanout")
    assert (summary.shops, summary.enqueued) == (3, 2)


async def test_one_shops_enqueue_failure_does_not_starve_the_rest(caplog):
    caplog.set_level(logging.INFO, logger=_LOGGER)
    a, b = uuid.uuid4(), uuid.uuid4()
    enqueued: list[str] = []

    def enqueue(shop_id: str) -> None:
        if shop_id == str(a):
            raise RuntimeError("broker hiccup")
        enqueued.append(shop_id)

    async def enumerate_fn(_session):
        return [_Shop(a, True), _Shop(b, True)]

    count = await module.run_fanout(object(), enqueue=enqueue, enumerate_fn=enumerate_fn)

    assert count == 1
    assert enqueued == [str(b)]
    (failed,) = _records(caplog, "shop_kpi_reconcile_enqueue_failed")
    assert failed.shop_id == str(a)


async def test_fanout_enumerates_like_the_shop_poll_fanout_by_default():
    """Same enumeration as `shop_poll_fanout` (migration 074's definer function)."""
    source = inspect.getsource(module.run_fanout)
    assert "enumerate_pollable_shops" in source


# -- the plan -----------------------------------------------------------------


def test_the_gap_plan_keeps_ctor_and_live_hours():
    plan = module.make_gap_fetch_plan("shop-key")

    assert plan.shop_id == "shop-key"
    assert plan.catalog_id is None
    assert {r.name for r in plan.resources} == set(module.GAP_PLAN_RESOURCES)


async def test_a_shop_the_fetch_executor_can_serve_gets_the_gap_plan():
    async def resolve(_session, _shop_id):
        return object()

    plan = await module.choose_fetch_plan(
        object(), uuid.uuid4(), "key", resolve_fetch_credential=resolve
    )

    assert {r.name for r in plan.resources} == set(module.GAP_PLAN_RESOURCES)


async def test_any_other_shop_gets_an_empty_plan_not_a_skip(caplog):
    caplog.set_level(logging.INFO, logger=_LOGGER)
    shop_id = uuid.uuid4()

    async def resolve(_session, _shop_id):
        return None

    plan = await module.choose_fetch_plan(
        object(), shop_id, "key", resolve_fetch_credential=resolve
    )

    assert plan.is_empty
    assert plan.shop_id == "key"
    (skipped,) = _records(caplog, "shop_kpi_reconcile_fetch_skipped")
    assert skipped.shop_id == str(shop_id)


def test_idempotency_key_is_per_shop_per_hour():
    from datetime import UTC, datetime

    a, b = uuid.uuid4(), uuid.uuid4()
    at = datetime(2026, 10, 20, 9, 5, tzinfo=UTC)
    later = datetime(2026, 10, 20, 9, 55, tzinfo=UTC)

    assert module.hourly_idempotency_key(a, at) == module.hourly_idempotency_key(a, later)
    assert module.hourly_idempotency_key(a, at) != module.hourly_idempotency_key(b, at)
    assert module.hourly_idempotency_key(a, at).endswith("2026-10-20-09:00")


# -- the job and its completion line (#1857) ------------------------------------


async def test_the_completion_line_carries_requested_and_written_counts(caplog):
    caplog.set_level(logging.INFO, logger=_LOGGER)
    shop_id = uuid.uuid4()
    jobs = []

    async def orchestrator(job):
        jobs.append(job)
        return SharedComputeResult(bronze_appended=3, silver_promoted=2, gold_written=True)

    ticks = iter([10.0, 10.25])
    await module.run_shop_kpi_reconcile_job(
        session=object(),
        shop_id=shop_id,
        shop_key="key",
        fetch_plan=module.make_gap_fetch_plan("key"),
        orchestrator_run_fn=orchestrator,
        clock=lambda: next(ticks),
    )

    (job,) = jobs
    assert (job.shop_id, job.shop_key, job.enqueue_reason) == (shop_id, "key", "reconcile_hourly")
    (line,) = _records(caplog, "shop_kpi_reconcile_completed")
    assert line.status == "succeeded"
    assert line.fetch_plan_size == len(module.GAP_PLAN_RESOURCES)
    assert (line.bronze_appended, line.silver_promoted) == (3, 2)
    assert line.duration_ms == 250


async def test_a_crash_logs_unknown_counts_and_reraises(caplog):
    caplog.set_level(logging.INFO, logger=_LOGGER)

    async def orchestrator(_job):
        raise RuntimeError("silver stage died")

    with pytest.raises(RuntimeError, match="silver stage died"):
        await module.run_shop_kpi_reconcile_job(
            session=object(),
            shop_id=uuid.uuid4(),
            shop_key="key",
            fetch_plan=module.empty_fetch_plan("key"),
            orchestrator_run_fn=orchestrator,
        )

    (line,) = _records(caplog, "shop_kpi_reconcile_completed")
    assert line.status == "failed"
    assert line.bronze_appended is None and line.silver_promoted is None
    assert line.fetch_plan_size == 0


# -- the per-shop body ------------------------------------------------------------


class _FakeSession:
    def __init__(self, shop_key: str | None) -> None:
        self.shop_key = shop_key
        self.commits = 0

    async def get(self, _model, _shop_id):
        if self.shop_key is None:
            return None

        class _Row:
            tiktok_shop_id = self.shop_key

        return _Row()

    async def commit(self) -> None:
        self.commits += 1


def _factory(session: _FakeSession):
    @asynccontextmanager
    async def factory():
        yield session

    return factory


async def test_the_shop_task_runs_under_that_shops_scope(monkeypatch):
    from juli_backend.database import tenant_context

    entered: list[uuid.UUID] = []

    @asynccontextmanager
    async def fake_scope(_session, shop_id):
        entered.append(shop_id)
        yield

    monkeypatch.setattr(tenant_context, "with_shop_scope", fake_scope)
    shop_id = uuid.uuid4()
    session = _FakeSession("tt-key")
    jobs = []

    async def orchestrator(job):
        jobs.append(job)
        return None

    async def no_credential(_session, _shop_id):
        return None

    await module.run_shop_kpi_reconcile(
        shop_id,
        session_factory=_factory(session),
        resolve_fetch_credential=no_credential,
        orchestrator_run_fn=orchestrator,
    )

    assert entered == [shop_id]
    (job,) = jobs
    assert job.shop_id == shop_id and job.shop_key == "tt-key"
    assert job.fetch_plan.is_empty
    assert session.commits == 1


async def test_an_unknown_shop_does_nothing(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger=_LOGGER)
    from juli_backend.database import tenant_context

    @asynccontextmanager
    async def fake_scope(_session, _shop_id):
        yield

    monkeypatch.setattr(tenant_context, "with_shop_scope", fake_scope)

    async def orchestrator(_job):  # pragma: no cover - must not run
        raise AssertionError("no job for a shop with no TikTok key")

    result = await module.run_shop_kpi_reconcile(
        uuid.uuid4(), session_factory=_factory(_FakeSession(None)), orchestrator_run_fn=orchestrator
    )

    assert result is None
    assert _records(caplog, "shop_kpi_reconcile_unknown_shop")


# -- nothing is configured per shop -------------------------------------------------


def test_no_reference_shop_is_read_anywhere_in_ingestion():
    """No worker reads the variable (a string literal is how it would be read)."""
    import re
    from pathlib import Path

    root = Path(module.__file__).resolve().parents[2]
    literal = re.compile(r"[\"']DEMO_REFERENCE_SHOP_ID[\"']")
    hits = [
        str(path.relative_to(root))
        for path in (root / "workers").rglob("*.py")
        if literal.search(path.read_text(encoding="utf-8"))
    ]
    assert hits == [], f"a worker still reads DEMO_REFERENCE_SHOP_ID: {hits}"


def test_the_beat_points_at_the_fanout_hourly():
    from celery.schedules import crontab

    from juli_backend.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert schedule["shop-kpi-reconcile-fanout"] == {
        "task": module.FANOUT_TASK,
        "schedule": crontab(minute=0),
    }
    assert "mock-analytics-hourly-reconcile" not in schedule
    assert "analytics-backfill-topup" not in schedule
