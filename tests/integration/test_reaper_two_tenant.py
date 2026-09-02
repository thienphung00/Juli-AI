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

import uuid
from datetime import UTC, datetime

import pytest_asyncio
from sqlalchemy import text

from juli_backend.workers.tasks import reaper
from tests.integration.two_tenant import Tenant, juli_app_session, seed_tenant

# Staleness threshold from the reaper module, used to verify runs are reaped correctly
STALE_THRESHOLD_S = reaper.STALE_RUN_SLACK_S + 600  # default policy wall_clock_timeout_s


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


async def test_reaper_expires_waiting_approval_for_both_tenants(two_tenants, owner_engine):
    """AC3/AC4 for the second reap path.

    `waiting_approval` reaches the reaper through the same enumeration (widened
    by migration 052). Before that, this path ran a context-less
    `select(WorkflowRun)`, which as `juli_app` under RLS reads zero rows — the
    reap would report success having expired nothing. This test fails on that
    behaviour rather than passing quietly.
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
