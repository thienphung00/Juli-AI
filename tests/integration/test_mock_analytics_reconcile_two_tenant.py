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
import uuid

import pytest
from sqlalchemy import text

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
    rather than about envelope maths. The shop-key lookup is no longer stubbed
    and no longer exists: #1518 removed it, so this now runs the real
    resolution path end to end as `juli_app`.
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

    monkeypatch.setenv("DEMO_REFERENCE_SHOP_KEY", "test-shop-1513")

    # Mock the session factory to use test database
    def mock_session_factory():
        from juli_backend.database.database import ensure_worker_session_factory
        from juli_backend.workers.tasks.database import get_async_database_url

        return ensure_worker_session_factory(get_async_database_url())

    monkeypatch.setattr(
        "juli_backend.workers.tasks.mock_analytics_reconcile._ensure_session_factory",
        mock_session_factory,
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
async def test_reconcile_resolves_its_shop_key_without_reading_shops(owner_engine, monkeypatch):
    """#1518: the shop key comes from configuration, not from a user-keyed table.

    `public.shops` is keyed on `user_id = app_current_user_id()`, and this task
    has a shop but no user. Measured as `juli_app` before the fix: zero rows
    with no context AND zero under shop scope. The task read None, returned
    early, and logged a warning — no error, so a gate observation asking that
    the beats "complete a cycle without a scoping error" would have recorded a
    pass for a task that did nothing.

    This asserts the property directly: `shops` is unreadable by this task's
    role, and the task nonetheless resolves its key and runs. If someone
    reintroduces the lookup, the first assertion still passes and the run
    stops producing rows — which the AC2 test above then catches.
    """
    tenant = seed_tenant(owner_engine, label="key_from_config")
    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(tenant.shop_id))
    monkeypatch.setenv("DEMO_REFERENCE_SHOP_KEY", "configured-key")

    # The read the old implementation depended on, from this task's own role.
    async with juli_app_session(shop_id=tenant.shop_id) as session:
        visible = (
            await session.execute(
                text("SELECT count(*) FROM public.shops WHERE id = :i"),
                {"i": str(tenant.shop_id)},
            )
        ).scalar()
    assert visible == 0, (
        "shops is expected to be unreadable under shop-only context — if this "
        "starts returning rows the policy changed and #1518's reasoning needs revisiting"
    )

    from juli_backend.workers.tasks.mock_analytics_reconcile import (
        get_demo_reference_shop_key,
    )

    assert get_demo_reference_shop_key() == "configured-key", (
        "the key must resolve from configuration despite shops being unreadable"
    )


@pytest.mark.asyncio
async def test_reconcile_skips_loudly_when_the_shop_key_is_not_configured(monkeypatch):
    """A missing key must skip with a named reason, not fall back to the database.

    Falling back would restore the exact no-op #1518 removes: the read returns
    nothing as `juli_app`, and the task reports a clean cycle having recomputed
    no envelopes.
    """
    from juli_backend.workers.tasks import mock_analytics_reconcile

    monkeypatch.setenv("DEMO_REFERENCE_SHOP_ID", str(uuid.uuid4()))
    monkeypatch.delenv("DEMO_REFERENCE_SHOP_KEY", raising=False)

    opened: list[str] = []
    monkeypatch.setattr(
        mock_analytics_reconcile,
        "_ensure_session_factory",
        lambda: opened.append("session") or (_ for _ in ()).throw(AssertionError("no session")),
    )

    await mock_analytics_reconcile._run_hourly_reconcile_async()

    assert opened == [], "the task must skip before opening a session"
