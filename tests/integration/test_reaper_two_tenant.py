"""Integration test: reaper works as juli_app on two tenants (#1489, ADR-089).

The reaper must enumerate active workflow runs via a SECURITY DEFINER function,
then loop under per-tenant context, setting the shop id for each run before
reaping it. This test proves:

1. The reaper reaps the stale run of BOTH tenants as `juli_app`
2. It does NOT reap the fresh run of either — the fixture seeds one stale
   and one fresh run per tenant precisely so a reaper that terminates
   everything fails
3. The per-item context is the run's shop, not one shop for the whole run
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text

from juli_backend.workers.tasks import reaper
from tests.integration.two_tenant import Tenant, juli_app_session, seed_tenant

# Both sibling two-tenant modules carry these. Without the skipif this module
# ERRORs rather than skipping in the supported local mode where
# `tests/conftest.py` clears DATABASE_URL, and without `migration_heavy` it
# runs in the PR-safe lane whose own comment says it excludes heavy suites —
# while doing a full `alembic upgrade head` and a CREATE DATABASE.
requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


def _never_live(_run_id: uuid.UUID) -> bool:
    """Liveness probe that always returns False — no live tasks."""
    return False


@pytest_asyncio.fixture
async def two_tenants(owner_engine) -> tuple[Tenant, Tenant]:
    """Seed two complete tenants with stale and fresh runs."""
    tenant1 = seed_tenant(owner_engine, label="tenant1")
    tenant2 = seed_tenant(owner_engine, label="tenant2")
    return tenant1, tenant2


async def test_reaper_reaps_stale_runs_from_both_tenants_as_juli_app(two_tenants, owner_engine):
    """AC: The reaper reaps stale runs from both tenants when running as juli_app.

    Proves:
    1. Enumeration finds runs from both tenants (not filtered by a GUC before enumeration)
    2. Each run is reaped under its own shop context (not one shared context for all)
    3. Only the stale run is reaped; the fresh run is not
    """
    tenant1, tenant2 = two_tenants
    now = datetime.now(UTC)

    # Open a session as juli_app (row visibility governed by RLS)
    async with juli_app_session() as session:
        # Call the core reaper logic (not the Celery task, just the logic)
        result = await reaper.reap_workflow_runs(
            session,
            now=now,
            has_live_task=_never_live,
        )
        # Commit the session to persist the reaper's changes
        await session.commit()

    # Assert: both stale runs were reaped (enumeration is working)
    # Membership, not a count. The module keeps one database across its tests
    # (`_SHARED_STATE_MODULES`), so rows from a sibling test accumulate and an
    # `== 2` here would pass or fail on test ordering rather than on behaviour.
    reaped_ids = set(result.stale_runs_reaped)
    assert tenant1.stale_run_id in reaped_ids, (
        f"Tenant 1's stale run {tenant1.stale_run_id} should be reaped. Reaped: {reaped_ids}"
    )
    assert tenant2.stale_run_id in reaped_ids, (
        f"Tenant 2's stale run {tenant2.stale_run_id} should be reaped. Reaped: {reaped_ids}"
    )

    # Assert: fresh runs were NOT reaped
    assert tenant1.fresh_run_id not in reaped_ids, (
        f"Tenant 1's fresh run should NOT be reaped. Reaped: {reaped_ids}"
    )
    assert tenant2.fresh_run_id not in reaped_ids, (
        f"Tenant 2's fresh run should NOT be reaped. Reaped: {reaped_ids}"
    )

    # The returned tuple is Python state. AC3 is explicit that "completed
    # without raising" is not evidence, and the same is true of "returned some
    # ids" — the failure this epic exists for is a task that reports work it
    # did not persist. So read the rows back.
    with owner_engine.connect() as conn:
        statuses = dict(
            conn.execute(text("SELECT id, status FROM public.workflow_runs ORDER BY id")).all()
        )

    for tenant in (tenant1, tenant2):
        assert statuses[tenant.stale_run_id] == "failed", (
            f"stale run {tenant.stale_run_id} was returned as reaped but its row "
            f"is {statuses[tenant.stale_run_id]!r} — the write did not persist"
        )
        assert statuses[tenant.fresh_run_id] == "running", (
            f"fresh run {tenant.fresh_run_id} must be untouched, is "
            f"{statuses[tenant.fresh_run_id]!r}"
        )

    # The status flip alone does not prove the reaper went through the sink.
    # ADR-074 decision 4: no side-channel UPDATE ever runs without the event row
    # landing in the same commit — it is what lets an SSE client watch a run die
    # rather than find it silently gone. A sink that set status/stop_reason
    # directly and never inserted the event would satisfy every assertion above.
    # Asserted here specifically because the unit suite proves it on SQLite as
    # the OWNER, so an RLS INSERT denial on workflow_run_events as juli_app
    # would surface nowhere else.
    with owner_engine.connect() as conn:
        events = {
            row[0]: row[1]
            for row in conn.execute(
                text(
                    "SELECT workflow_run_id, event_type FROM public.workflow_run_events "
                    " WHERE event_type = 'workflow.failed'"
                )
            ).all()
        }

    for tenant in (tenant1, tenant2):
        assert tenant.stale_run_id in events, (
            f"stale run {tenant.stale_run_id} reads 'failed' but has no "
            "workflow.failed event row — the status was written by a side channel"
        )
        assert tenant.fresh_run_id not in events, (
            f"fresh run {tenant.fresh_run_id} must have no terminal event"
        )


async def test_reaper_expires_waiting_approval_for_both_tenants(two_tenants, owner_engine):
    """AC3/AC4 for the second reap path.

    `waiting_approval` reaches the reaper through the same enumeration (widened
    by migration 052). Before that, this path ran a context-less
    `select(WorkflowRun)`.

    WHAT THAT SELECT ACTUALLY RETURNED, since the obvious answer is wrong.
    Not zero rows. `with_shop_scope` never unsets the GUC on exit (#1495), and
    SET LOCAL only clears at transaction end, so by the time loop 2 ran,
    `app.current_shop_id` was still whichever shop loop 1 touched last. The
    reverted select therefore read exactly ONE tenant's rows — measured, not
    reasoned about.

    That is why this test asserts on BOTH tenants. Narrow it to one and it
    stops being load-bearing: a context-less select would satisfy it.
    """
    tenant1, tenant2 = two_tenants
    now = datetime.now(UTC)

    async with juli_app_session() as session:
        result = await reaper.reap_workflow_runs(
            session,
            now=now,
            has_live_task=_never_live,
        )
        await session.commit()

    expired = set(result.expired_approvals_reaped)
    assert {tenant1.expired_approval_run_id, tenant2.expired_approval_run_id} <= expired, (
        f"expected both tenants' expired approvals, got {expired}"
    )
    assert tenant1.fresh_approval_run_id not in expired, "un-expired approval was reaped"
    assert tenant2.fresh_approval_run_id not in expired, "un-expired approval was reaped"

    with owner_engine.connect() as conn:
        statuses = dict(
            conn.execute(text("SELECT id, status FROM public.workflow_runs ORDER BY id")).all()
        )

    for tenant in (tenant1, tenant2):
        assert statuses[tenant.expired_approval_run_id] == "cancelled", (
            f"expired approval {tenant.expired_approval_run_id} is "
            f"{statuses[tenant.expired_approval_run_id]!r}, not cancelled"
        )
        # Inside the 4h window: the threshold is doing the work, not the status.
        assert statuses[tenant.fresh_approval_run_id] == "waiting_approval", (
            f"un-expired approval {tenant.fresh_approval_run_id} must be untouched, is "
            f"{statuses[tenant.fresh_approval_run_id]!r}"
        )


async def test_reaper_enumeration_returns_both_tenants_as_juli_app(two_tenants):
    """The enumeration itself is the one cross-tenant read (ADR-089 decision 3).

    Asserted directly, because if it silently returned one tenant's rows the
    tests above would still pass for that tenant and the isolation defect would
    read as a partial success.
    """
    tenant1, tenant2 = two_tenants

    async with juli_app_session() as session:
        rows = await reaper._enumerate_active_runs(
            session, ("queued", "running", "waiting_approval")
        )

    shop_ids = {shop_id for _, shop_id in rows}
    assert {tenant1.shop_id, tenant2.shop_id} <= shop_ids, (
        f"enumeration must span both tenants as juli_app; saw shops {shop_ids}"
    )
    run_ids = {run_id for run_id, _ in rows}
    for tenant in (tenant1, tenant2):
        assert tenant.expired_approval_run_id in run_ids, (
            "migration 052 widened the enumeration to waiting_approval; "
            f"{tenant.expired_approval_run_id} is missing"
        )


async def test_each_run_is_reaped_by_its_own_workflows_policy_as_juli_app(
    two_tenants, owner_engine
):
    """AC 4 of #1702, through the REAL Postgres path.

    `tests/unit/test_reaper_per_workflow_policy.py` proves the per-run
    resolution on SQLite, where `_enumerate_active_runs` takes its
    non-Postgres branch and neither RLS nor `with_shop_scope` does anything.
    This proves the same decision survives the path production actually
    takes: the `enumerate_active_workflow_runs()` SECURITY DEFINER function
    as `juli_app`, the per-run `with_shop_scope`, and the RLS policies on
    `workflow_runs`/`workflow_run_events`.

    Two runs on ONE tenant, identical age (400s of silence), differing only
    in `workflow_key`. 400s sits strictly between the test workflow's
    threshold (10s wall clock + the fixed 300s slack = 310s) and Optimize
    Product's (300 + 300 = 600s), so a reaper carrying one global threshold
    reaps both or neither.

    The two runs share one product on purpose: since #1701 re-keyed
    `uq_workflow_runs_active_shop_product` to
    `(shop_id, workflow_key, subject_type, subject_ref)`, two DIFFERENT
    workflows on the same subject are no longer a uniqueness collision, and
    this INSERT pair would have failed before that migration.
    """
    from juli_backend.services.agent import playbooks as playbooks_module
    from tests.support.workflow_registry import TEST_WORKFLOW_KEY, make_test_playbook

    tenant1, _tenant2 = two_tenants
    now = datetime.now(UTC)
    silence = timedelta(seconds=400)

    prod_run_id = uuid.uuid4()
    test_run_id = uuid.uuid4()
    subject_product_id = uuid.uuid4()

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.products (id, shop_id, tiktok_product_id, name, status, "
                " update_time, created_at, updated_at) "
                "VALUES (:id, :shop_id, :tiktok_id, 'per-workflow subject', 'active', "
                " :now, :now, :now)"
            ),
            {
                "id": str(subject_product_id),
                "shop_id": str(tenant1.shop_id),
                "tiktok_id": f"tt-{subject_product_id.hex[:10]}",
                "now": now,
            },
        )
        for run_id, workflow_key in (
            (prod_run_id, "optimize_product_2"),
            (test_run_id, TEST_WORKFLOW_KEY),
        ):
            conn.execute(
                text(
                    "INSERT INTO public.workflow_runs "
                    "(id, shop_id, product_id, workflow_key, subject_type, subject_ref, state, "
                    " status, prompt_version, prompt_sha256, running_seconds_elapsed, "
                    " cancel_requested, created_at, updated_at) "
                    "VALUES (:id, :shop_id, :product_id, :workflow_key, 'product', "
                    " CAST(:product_id AS text), '{}', 'running', 'v1', :sha, 0, false, "
                    " :created, :created)"
                ),
                {
                    "id": str(run_id),
                    "shop_id": str(tenant1.shop_id),
                    "product_id": str(subject_product_id),
                    "workflow_key": workflow_key,
                    "sha": "0" * 64,
                    "created": now - silence,
                },
            )

    test_playbook = make_test_playbook(wall_clock_timeout_s=10)
    with playbooks_module.playbook_registered_for_test(test_playbook):
        async with juli_app_session() as session:
            result = await reaper.reap_workflow_runs(
                session,
                now=now,
                has_live_task=_never_live,
            )
            await session.commit()

    reaped = set(result.stale_runs_reaped)
    assert test_run_id in reaped, (
        f"the run whose OWN workflow times out at 10s must be reaped at 400s of "
        f"silence; reaped {reaped}"
    )
    assert prod_run_id not in reaped, (
        "the optimize_product_2 run of IDENTICAL age must NOT be reaped -- its own "
        f"threshold is 600s; reaped {reaped}"
    )

    # Python state is not evidence: read the rows back as the owner.
    with owner_engine.connect() as conn:
        statuses = dict(
            conn.execute(
                text("SELECT id, status FROM public.workflow_runs WHERE id IN (:a, :b)").bindparams(
                    a=str(prod_run_id), b=str(test_run_id)
                )
            ).all()
        )
    assert statuses[test_run_id] == "failed"
    assert statuses[prod_run_id] == "running"
