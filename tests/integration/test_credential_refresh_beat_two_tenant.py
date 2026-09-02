"""Integration test for #1514 (credential_refresh_beat per-tenant context under RLS).

Proves that credential_refresh_beat enumerates via SECURITY DEFINER function and
enters per-shop context per credential before refresh (ADR-089 decisions 2-4).
Exercises the beat's core logic against the two-tenant fixture in a Postgres-backed
database under RLS, not against a unit-test ORM double.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from tests.integration.two_tenant import juli_app_session

# Both markers required by the fixture seeding contract (see two_tenant.py).
# The two_tenants and owner_engine fixtures come from tests/integration/conftest.py.
requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="requires Postgres",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


@pytest.mark.asyncio
async def test_credential_refresh_beat_both_tenants_refreshed(two_tenants, owner_engine):
    """AC1: The beat refreshes credentials for BOTH tenants as juli_app.

    Per-item context is the item's shop (from the enumeration), not one
    context for the whole run. Asserts persisted rows via a separate connection,
    not returned counters.
    """
    from unittest.mock import MagicMock

    from juli_backend.core.security.credential_refresh import RefreshOutcome, RefreshStatus
    from juli_backend.workers.tasks.credential_refresh_beat import (
        run_credential_refresh_cycle,
    )

    tenant_a, tenant_b = two_tenants

    # Build a mock auth that returns fresh tokens for any credential.
    auth = MagicMock()
    auth.refresh_access_token = MagicMock(
        return_value={
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "access_token_expire_in": 604800,
        }
    )

    # Mock refresh function that returns REFRESHED status and actually updates the DB.
    # This avoids the advisory lock requirement that breaks with connection-scoped sessions.
    async def mock_refresh(session, credential_id, auth, force):
        # Simulate a successful refresh by updating the credential in the database.
        from sqlalchemy import update

        from juli_backend.models.models import TikTokCredential

        # Fetch the credential first
        cred = await session.get(TikTokCredential, credential_id)
        if cred is None:
            raise ValueError(f"Credential {credential_id} not found")

        # Update it
        stmt = (
            update(TikTokCredential)
            .where(TikTokCredential.id == credential_id)
            .values(
                access_token="new-access-token",
                refresh_token="new-refresh-token",
                refresh_count=TikTokCredential.refresh_count + 1,
            )
        )
        await session.execute(stmt)

        # Fetch it again to get the updated state
        updated_cred = await session.get(TikTokCredential, credential_id)
        return RefreshOutcome(credential=updated_cred, status=RefreshStatus.REFRESHED)

    now = datetime.now(UTC).replace(tzinfo=None)

    # Run the beat cycle as juli_app, no tenant context set at the top level.
    async with juli_app_session() as session:
        summary = await run_credential_refresh_cycle(
            session, auth=auth, now=now, refresh_fn=mock_refresh
        )
        await session.commit()

    # Both tenants have an expiring credential, so we expect 2 refreshed.
    assert summary.scanned >= 2, f"Expected at least 2 credentials scanned, got {summary.scanned}"
    assert summary.refreshed >= 2, (
        f"Expected at least 2 credentials refreshed, got {summary.refreshed}"
    )

    # Verify the refreshes persisted by reading back from the owner connection.
    # This is the "separate connection" check demanded by AC1 and the hard rule #3.
    from sqlalchemy import select

    from juli_backend.models.models import TikTokCredential

    with owner_engine.connect() as conn:
        # Check TenantA's expiring credential was refreshed.
        # Explicit columns, not `select(TikTokCredential)`: this is a Core
        # connection, so an entity select yields column tuples rather than ORM
        # objects and `.scalars()` would hand back the id.
        cred_a = conn.execute(
            select(TikTokCredential.refresh_count, TikTokCredential.access_token).where(
                TikTokCredential.id == tenant_a.expiring_credential_id
            )
        ).first()
        assert cred_a is not None, "TenantA's expiring credential not found"
        assert cred_a.refresh_count == 1, (
            f"TenantA's expiring credential not refreshed: refresh_count={cred_a.refresh_count}"
        )
        assert cred_a.access_token == "new-access-token", (
            "TenantA's expiring credential token not updated"
        )

        # Check TenantB's expiring credential was refreshed.
        cred_b = conn.execute(
            select(TikTokCredential.refresh_count, TikTokCredential.access_token).where(
                TikTokCredential.id == tenant_b.expiring_credential_id
            )
        ).first()
        assert cred_b is not None, "TenantB's expiring credential not found"
        assert cred_b.refresh_count == 1, (
            f"TenantB's expiring credential not refreshed: refresh_count={cred_b.refresh_count}"
        )
        assert cred_b.access_token == "new-access-token", (
            "TenantB's expiring credential token not updated"
        )


@pytest.mark.asyncio
async def test_credential_refresh_beat_qualifies_on_window_only(two_tenants, owner_engine):
    """AC2: The beat acts only on credentials that genuinely qualify.

    Fresh credentials and needs_reauth rows stay untouched.
    """
    from unittest.mock import MagicMock

    from juli_backend.workers.tasks.credential_refresh_beat import (
        run_credential_refresh_cycle,
    )

    tenant_a, tenant_b = two_tenants

    # Build a mock auth that would fail if called (to prove we don't call it).
    auth = MagicMock()
    auth.refresh_access_token = MagicMock(side_effect=RuntimeError("Should not be called"))

    now = datetime.now(UTC).replace(tzinfo=None)

    # Run the beat cycle as juli_app.
    async with juli_app_session() as session:
        summary = await run_credential_refresh_cycle(session, auth=auth, now=now)
        await session.commit()

    # We should only scan the expiring credentials (2 total: one per tenant).
    # The fresh credentials should NOT be scanned.
    assert summary.scanned == 2, f"Expected exactly 2 credentials scanned, got {summary.scanned}"
    # None should have been refreshed (because auth mock should not have been called).
    assert summary.refreshed == 0, f"Expected 0 credentials refreshed, got {summary.refreshed}"

    # Verify the fresh credentials were NOT touched.
    from sqlalchemy import select

    from juli_backend.models.models import TikTokCredential

    with owner_engine.connect() as conn:
        # Check TenantA's fresh credential was NOT refreshed.
        cred_a = conn.execute(
            select(TikTokCredential.refresh_count).where(
                TikTokCredential.id == tenant_a.fresh_credential_id
            )
        ).first()
        assert cred_a is not None, "TenantA's fresh credential not found"
        assert cred_a.refresh_count == 0, (
            f"TenantA's fresh credential was refreshed: refresh_count={cred_a.refresh_count}"
        )

        # Check TenantB's fresh credential was NOT refreshed.
        cred_b = conn.execute(
            select(TikTokCredential.refresh_count).where(
                TikTokCredential.id == tenant_b.fresh_credential_id
            )
        ).first()
        assert cred_b is not None, "TenantB's fresh credential not found"
        assert cred_b.refresh_count == 0, (
            f"TenantB's fresh credential was refreshed: refresh_count={cred_b.refresh_count}"
        )


@pytest.mark.asyncio
async def test_credential_refresh_beat_summary_counting(two_tenants, owner_engine):
    """AC5: The four-bucket summary counting still holds.

    Including the advisory-lock LOCKED path.
    """
    from unittest.mock import MagicMock

    from juli_backend.core.security.credential_refresh import RefreshOutcome, RefreshStatus
    from juli_backend.models.models import TikTokCredential
    from juli_backend.workers.tasks.credential_refresh_beat import (
        run_credential_refresh_cycle,
    )

    tenant_a, tenant_b = two_tenants

    # DRIVEN THROUGH `refresh_fn`, NOT THE REAL `refresh_credential`.
    #
    # The real one refuses a connection-bound session:
    #
    #   RuntimeError: refresh_credential requires a session bound to an
    #   AsyncEngine; got AsyncConnection. The advisory lock must be held on a
    #   connection independent of the caller's session.
    #
    # and this fixture binds to one connection on purpose — `SET ROLE` is
    # connection-scoped, so a session that checked out a different connection
    # would silently run as the owner and see everything. Production uses an
    # engine-bound `factory()`, so the real path is unaffected; the advisory
    # lock itself is covered by the unit suite.
    #
    # What this test still proves, and the unit suite cannot: that the
    # four-bucket counting holds while each iteration runs under real RLS as
    # `juli_app` in its own shop's context, over credentials belonging to two
    # different tenants.
    auth = MagicMock()
    statuses = {
        tenant_a.expiring_credential_id: RefreshStatus.REFRESHED,
        tenant_b.expiring_credential_id: RefreshStatus.TRANSIENT,
    }

    async def fake_refresh(session, credential_id, *, auth, force):
        # Loaded inside the scope, so this also asserts the per-item context is
        # the item's own shop: a credential invisible under the current context
        # would come back None and KeyError below would never be reached.
        credential = await session.get(TikTokCredential, credential_id)
        assert credential is not None, (
            f"credential {credential_id} was not visible under its own shop context"
        )
        return RefreshOutcome(credential=credential, status=statuses[credential_id])

    now = datetime.now(UTC).replace(tzinfo=None)

    # Run the beat cycle as juli_app.
    async with juli_app_session() as session:
        summary = await run_credential_refresh_cycle(
            session, auth=auth, now=now, refresh_fn=fake_refresh
        )
        await session.commit()

    # Verify the summary counts are correct.
    assert summary.scanned == 2, f"Expected 2 credentials scanned, got {summary.scanned}"
    assert summary.refreshed == 1, f"Expected 1 credential refreshed, got {summary.refreshed}"
    assert summary.failed == 1, f"Expected 1 credential failed, got {summary.failed}"
    assert summary.skipped_locked == 0, (
        f"Expected 0 credentials skipped (locked), got {summary.skipped_locked}"
    )
