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

from tests.integration.two_tenant import (
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

    The lookup is stubbed because it CANNOT run as `juli_app`: `public.shops`
    is user-keyed and `with_shop_scope` withholds the user GUC, so the real
    `_lookup_tiktok_shop_key_async` returns None and the task returns early.
    That is #1518 — a pre-existing gap this slice neither introduces nor fixes,
    since the lookup happens before any scope and in its own session. Until it
    is resolved, an end-to-end run of this task as `juli_app` is not possible,
    and a test claiming otherwise would be claiming more than it checks.
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

    # Mock the tiktok shop key lookup
    async def mock_lookup_shop_key(shop_id_arg):
        return "test-shop-1513"

    monkeypatch.setattr(
        "juli_backend.workers.tasks.mock_analytics_reconcile._lookup_tiktok_shop_key_async",
        mock_lookup_shop_key,
    )

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
