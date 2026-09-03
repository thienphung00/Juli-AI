"""Integration test: mock_analytics_reconcile runs under shop scope as juli_app.

Issue #1513 / ADR-089 decision 5: Proves that:
- mock_analytics_reconcile calls with_shop_scope (not system_scope)

AC3 (cannot reach another tenant) is asserted inside the AC2 test, by the
`count_b == 0` check on a shop the task was never scoped to. It previously had
a test of its own that imported `with_shop_scope` and asserted on the primitive
without ever calling the task — that proved the seam, which
tests/integration/test_shop_scope_guc_lifecycle.py (#1495) now owns, and proved
nothing about this task.
- It writes analytics rows for the demo shop only
- It cannot reach another tenant's rows
- The shop_id is None early return short-circuits before session is opened
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.workers.tasks.mock_analytics_reconcile import (
    _lookup_tiktok_shop_key_async,
)
from tests.integration.two_tenant import (
    juli_app_session,
    seed_tenant,
)

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


@pytest.mark.asyncio
async def test_mock_analytics_reconcile_writes_for_demo_shop_only(owner_engine, monkeypatch):
    """AC2: the task's writes land under the demo shop's context, and only there.

    WHAT THIS PROVES, AND WHAT IT STUBS. The orchestrator and the shop-key
    lookup are both replaced. What remains real is the part under test: that
    `_run_hourly_reconcile_async` opens a session, enters `with_shop_scope` for
    the shop it resolved, and that a write issued inside that scope commits for
    that shop and for no other. The stub writes one gold envelope row; the
    assertion reads it back through a SEPARATE owner connection, so it is
    persistence rather than a success flag.

    The orchestrator is stubbed so the assertion is about the scope wiring
    rather than envelope maths. The shop-key lookup is NOT stubbed any more:
    #1518 moved it inside the scope and migration 053 lets a shop-scoped
    session read its own shop, so the real resolution path runs here as
    `juli_app`. Before that it returned None and the task ended early.
    """
    from juli_backend.workers.tasks.mock_analytics_reconcile import (
        _run_hourly_reconcile_async,
    )

    # Seed two tenants, use tenant_a.shop_id as the demo shop
    tenant_a = seed_tenant(owner_engine, label="demo")
    tenant_b = seed_tenant(owner_engine, label="other")

    # Mock the demo shop id to tenant_a
    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(tenant_a.shop_id))

    # Mock the orchestrator to write a row so we can verify the scope works
    async def mock_orchestrator_writes_row(*, session, shop_id, shop_key, **kwargs):
        """Mock orchestrator: writes a gold KPI row to prove context works."""
        from datetime import UTC, datetime

        from juli_backend.models.models import GoldKpiEnvelope

        row = GoldKpiEnvelope(
            shop_id=shop_id,
            computed_at=datetime.now(UTC),
            envelope_version=1,
            payload={"test": "mock_1513"},
        )
        session.add(row)
        await session.flush()

    monkeypatch.setattr(
        "juli_backend.workers.tasks.mock_analytics_reconcile.run_mock_analytics_reconcile_orchestrated",
        mock_orchestrator_writes_row,
    )

    # AS `juli_app`, NOT AS THE OWNER.
    #
    # This used to hand the task a factory built from DATABASE_URL, which in
    # tests is the table owner — and Postgres exempts a table's owner from RLS.
    # The task then ran with every policy inert, so this test passed with
    # migration 053 removed and proved nothing about the role the runtime will
    # actually connect as. `juli_app_session` is itself an async context
    # manager taking no required argument, so it substitutes for `factory()`
    # directly.
    monkeypatch.setattr(
        "juli_backend.workers.tasks.mock_analytics_reconcile._ensure_session_factory",
        lambda: juli_app_session,
    )

    # Run the task
    await _run_hourly_reconcile_async()

    # Assert: verify via owner connection that the row was written for tenant_a
    # (not tenant_b, and verified on a separate connection to prove durability)
    with owner_engine.connect() as conn:
        # Check that GoldKpiEnvelope was written for tenant_a.shop_id
        result = conn.execute(
            text(
                "SELECT COUNT(*) FROM gold.kpi_envelopes "
                "WHERE shop_id = :shop_id AND payload->>'test' = 'mock_1513'"
            ),
            {"shop_id": str(tenant_a.shop_id)},
        )
        count = result.scalar()
        assert count > 0, f"Expected rows written for demo shop {tenant_a.shop_id}, found {count}"

        # Verify no rows were written for tenant_b
        result_b = conn.execute(
            text(
                "SELECT COUNT(*) FROM gold.kpi_envelopes "
                "WHERE shop_id = :shop_id AND payload->>'test' = 'mock_1513'"
            ),
            {"shop_id": str(tenant_b.shop_id)},
        )
        count_b = result_b.scalar()
        assert count_b == 0, f"Expected NO rows for other shop {tenant_b.shop_id}, found {count_b}"


@pytest.mark.asyncio
async def test_mock_analytics_reconcile_skips_when_demo_shop_is_none(monkeypatch):
    """AC4: mock_analytics_reconcile short-circuits when demo shop id is None.

    Proves that no session is opened when shop_id is None.
    """
    from juli_backend.workers.tasks.mock_analytics_reconcile import (
        _run_hourly_reconcile_async,
    )

    # Unset the demo shop id
    monkeypatch.delenv("DEMO_REFERENCE_SHOP_ID", raising=False)

    # Mock the session factory to track if it was called
    session_factory_called = []

    def mock_session_factory():
        session_factory_called.append(True)
        raise AssertionError("Session factory should not be called when shop_id is None")

    monkeypatch.setattr(
        "juli_backend.workers.tasks.mock_analytics_reconcile._ensure_session_factory",
        mock_session_factory,
    )

    # Run the task — should return early without calling session factory
    await _run_hourly_reconcile_async()

    # Assert: session factory was never called
    assert len(session_factory_called) == 0, (
        "Session factory should not be called when shop_id is None"
    )


@pytest.mark.asyncio
async def test_the_shop_key_resolves_as_juli_app_under_shop_scope(owner_engine):
    """#1518 directly: the read that used to return None now returns the key.

    Before migration 053 this was zero rows — `shops` answered only to a
    user-keyed policy and this task has a shop but no user — so the task logged
    `mock_analytics_reconcile_unknown_shop` and returned. No exception, which is
    why observation 1's "completes a cycle without a scoping error" would have
    recorded a pass for a task that did nothing.
    """
    tenant_a = seed_tenant(owner_engine, label="key_a")
    tenant_b = seed_tenant(owner_engine, label="key_b")

    async with juli_app_session() as session:
        async with with_shop_scope(session, tenant_a.shop_id):
            resolved = await _lookup_tiktok_shop_key_async(tenant_a.shop_id, session)
            # The same call for the OTHER tenant, from inside A's scope, must
            # not resolve — otherwise the lookup is reading across tenants and
            # the policy is not doing the work.
            cross = await _lookup_tiktok_shop_key_async(tenant_b.shop_id, session)

    assert resolved == tenant_a.tiktok_shop_key, (
        f"expected {tenant_a.tiktok_shop_key!r} as juli_app under shop scope, got {resolved!r}"
    )
    assert cross is None, (
        f"resolved another tenant's shop key ({cross!r}) from inside tenant A's scope"
    )


@pytest.mark.asyncio
async def test_the_shop_key_does_not_resolve_without_a_shop_scope(owner_engine):
    """The policy is keyed to the context, not granted to the role.

    If 053 had been written as a blanket grant, the test above would still pass
    and tenancy would be gone. This is the assertion that separates them.
    """
    tenant = seed_tenant(owner_engine, label="key_noctx")

    async with juli_app_session() as session:
        resolved = await _lookup_tiktok_shop_key_async(tenant.shop_id, session)

    assert resolved is None, (
        f"the shop key resolved with no tenant context at all ({resolved!r}); "
        "the policy must fail closed rather than grant the role blanket read"
    )
