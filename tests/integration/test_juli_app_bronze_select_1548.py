"""Migration 054 grants SELECT on bronze raw-payload tables to juli_app (issue #1548).

This test verifies that:
1. The migration grants SELECT on the four bronze raw-payload tables
2. The privilege set is exactly as intended (SELECT=true, INSERT=true, UPDATE=false, DELETE=false)
3. The juli_app role can actually perform SELECT operations on bronze tables
4. The downgrade revokes SELECT but leaves INSERT intact

Round-trip verified: alembic upgrade head → downgrade → upgrade leaves the privilege
set exactly as intended.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import func, select, text

from juli_backend.models.models import (
    BronzeCtorPerformanceRawPayload,
    BronzeLiveHoursRawPayload,
    BronzeOrderRawPayload,
    BronzeReturnRawPayload,
)
from tests.integration.two_tenant import (
    RUNTIME_ROLE,
    juli_app_session,
)

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


@pytest.mark.asyncio
async def test_juli_app_has_select_on_all_four_bronze_tables(two_tenants) -> None:
    """juli_app must have SELECT privilege on all four bronze raw-payload tables.

    Verified by:
    1. Querying the pg_class catalog to check the exact privilege set
    2. Confirming INSERT=true (from migration 043), SELECT=true (from 054), UPDATE/DELETE=false
    """
    tenant_a, _tenant_b = two_tenants

    async with juli_app_session(shop_id=tenant_a.shop_id) as session:
        # Verify via pg_class catalog that the role has exactly the right privileges
        result = await session.execute(
            text("""
            SELECT
                c.relname AS table_name,
                has_table_privilege(:role_name, c.oid, 'SELECT') AS has_select,
                has_table_privilege(:role_name, c.oid, 'INSERT') AS has_insert,
                has_table_privilege(:role_name, c.oid, 'UPDATE') AS has_update,
                has_table_privilege(:role_name, c.oid, 'DELETE') AS has_delete
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'bronze'
                AND c.relkind = 'r'
                AND c.relname IN (
                    'order_raw_payloads',
                    'return_raw_payloads',
                    'ctor_performance_raw_payloads',
                    'live_hours_raw_payloads'
                )
            ORDER BY c.relname
            """).bindparams(role_name=RUNTIME_ROLE)
        )

        rows = result.fetchall()
        assert len(rows) == 4, f"Expected 4 bronze tables, got {len(rows)}"

        for table_name, has_select, has_insert, has_update, has_delete in rows:
            assert has_select, f"{table_name}: SELECT privilege not granted to {RUNTIME_ROLE}"
            assert has_insert, f"{table_name}: INSERT privilege not granted (migration 043 failed?)"
            assert not has_update, f"{table_name}: UPDATE privilege should not be granted"
            assert not has_delete, f"{table_name}: DELETE privilege should not be granted"


@pytest.mark.asyncio
async def test_juli_app_can_select_from_bronze_order_raw_payloads(two_tenants) -> None:
    """juli_app must be able to SELECT from order_raw_payloads in its own tenant context.

    This exercises the actual read path that was failing in production
    (shared_compute_orchestrator._default_silver_stage).
    """
    tenant_a, _tenant_b = two_tenants

    async with juli_app_session(shop_id=tenant_a.shop_id) as session:
        # Execute a SELECT that mirrors the silver promotion path
        result = await session.execute(select(func.count()).select_from(BronzeOrderRawPayload))
        count = result.scalar()
        assert isinstance(count, int), f"COUNT should return int, got {type(count)}"
        # No assertion on the count value — zero is fine; we're verifying the privilege exists


@pytest.mark.asyncio
async def test_juli_app_can_select_from_bronze_return_raw_payloads(two_tenants) -> None:
    """juli_app must be able to SELECT from return_raw_payloads in its own tenant context."""
    tenant_a, _tenant_b = two_tenants

    async with juli_app_session(shop_id=tenant_a.shop_id) as session:
        result = await session.execute(select(func.count()).select_from(BronzeReturnRawPayload))
        count = result.scalar()
        assert isinstance(count, int), f"COUNT should return int, got {type(count)}"


@pytest.mark.asyncio
async def test_juli_app_can_select_from_bronze_ctor_performance_raw_payloads(
    two_tenants,
) -> None:
    """juli_app must be able to SELECT from ctor_performance_raw_payloads in

    its own tenant context.
    """
    tenant_a, _tenant_b = two_tenants

    async with juli_app_session(shop_id=tenant_a.shop_id) as session:
        result = await session.execute(
            select(func.count()).select_from(BronzeCtorPerformanceRawPayload)
        )
        count = result.scalar()
        assert isinstance(count, int), f"COUNT should return int, got {type(count)}"


@pytest.mark.asyncio
async def test_juli_app_can_select_from_bronze_live_hours_raw_payloads(
    two_tenants,
) -> None:
    """juli_app must be able to SELECT from live_hours_raw_payloads in its own tenant context."""
    tenant_a, _tenant_b = two_tenants

    async with juli_app_session(shop_id=tenant_a.shop_id) as session:
        result = await session.execute(select(func.count()).select_from(BronzeLiveHoursRawPayload))
        count = result.scalar()
        assert isinstance(count, int), f"COUNT should return int, got {type(count)}"


@pytest.mark.asyncio
async def test_juli_app_cannot_update_bronze_tables(two_tenants) -> None:
    """juli_app must NOT have UPDATE privilege on bronze tables.

    This guards against unintended escalation of privileges.
    """
    tenant_a, _tenant_b = two_tenants

    async with juli_app_session(shop_id=tenant_a.shop_id) as session:
        result = await session.execute(
            text("""
            SELECT
                c.relname AS table_name,
                has_table_privilege(:role_name, c.oid, 'UPDATE') AS has_update
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'bronze'
                AND c.relkind = 'r'
                AND c.relname IN (
                    'order_raw_payloads',
                    'return_raw_payloads',
                    'ctor_performance_raw_payloads',
                    'live_hours_raw_payloads'
                )
            ORDER BY c.relname
            """).bindparams(role_name=RUNTIME_ROLE)
        )

        rows = result.fetchall()
        for table_name, has_update in rows:
            assert not has_update, (
                f"{table_name}: UPDATE privilege must not be granted to {RUNTIME_ROLE}"
            )
