"""Integration test: impact_reader enumerates measurable executions and processes per-tenant.

Issue #1488 / ADR-089: Proves that:
- impact_reader calls the SECURITY DEFINER enumeration function
- It loops over results, setting per-execution context
- Both tenants' executions are processed as juli_app
- Only qualifying rows are acted on
- Idempotency is preserved
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from juli_backend.workers.impact_reader.pipeline import run_daily_impact_reader
from tests.integration.two_tenant import (
    juli_app_session,
    seed_tenant,
)


@pytest.mark.asyncio
async def test_impact_reader_acts_on_both_tenants(owner_engine):
    """AC1: impact_reader processes executions from both tenants as juli_app.

    Proves:
    - Enumeration function returns rows for BOTH tenants
    - The task loop sets per-execution context (shop scope)
    - Both tenants' executions are acted upon
    """
    # Seed two complete tenants
    tenant_a = seed_tenant(owner_engine, label="tenant_a")
    tenant_b = seed_tenant(owner_engine, label="tenant_b")

    # Run the task under juli_app (no tenant context initially; enumeration is fleet-wide)
    async with juli_app_session() as session:
        reference_date = date.today()
        result = await run_daily_impact_reader(session, reference_date)
        await session.commit()

    # Assert: at least one execution was scanned (both tenants have one)
    assert result.executions_scanned >= 2, (
        f"Task should have scanned both tenants' executions; scanned {result.executions_scanned}"
    )

    # Verify via direct query that both tenants' executions were processed
    # by checking that impact_readings were written for both shops
    async with juli_app_session() as session:
        # Query impact_readings, which is joined through tool_executions
        stmt = text(
            """
            SELECT DISTINCT te.shop_id
            FROM public.impact_readings ir
            JOIN public.tool_executions te ON ir.tool_execution_id = te.id
            ORDER BY te.shop_id
            """
        )
        result_rows = await session.execute(stmt)
        processed_shops = [str(row[0]) for row in result_rows.all()]

    # Expect both tenants' shops to have readings
    assert str(tenant_a.shop_id) in processed_shops, (
        f"Tenant A's shop should have readings; got {processed_shops}"
    )
    assert str(tenant_b.shop_id) in processed_shops, (
        f"Tenant B's shop should have readings; got {processed_shops}"
    )


@pytest.mark.asyncio
async def test_impact_reader_per_item_context_is_correct(owner_engine):
    """AC2: The per-item context is set correctly for each execution.

    Proves that the task correctly sets app.current_shop_id to each execution's
    shop when processing it.
    """
    tenant = seed_tenant(owner_engine, label="single_tenant")

    # Run the task
    async with juli_app_session() as session:
        reference_date = date.today()
        await run_daily_impact_reader(session, reference_date)
        await session.commit()

    # Verify that a reading was written
    async with juli_app_session(shop_id=tenant.shop_id) as session:
        stmt = text(
            """
            SELECT COUNT(*)
            FROM public.impact_readings
            """
        )
        result_row = await session.execute(stmt)
        count = result_row.scalar()

    # At least one reading should have been written
    assert count > 0, "Task should have written readings"


@pytest.mark.asyncio
async def test_impact_reader_skips_non_qualifying_rows(owner_engine):
    """AC3: Task does NOT act on rows that don't qualify.

    Seeds one qualifying execution (status='succeeded') and one non-qualifying
    (status='queued'), proves only the qualifying one is acted on.
    """
    tenant_a = seed_tenant(owner_engine, label="qualifying_test")

    # The seeded execution is already 'succeeded' and 30 days old (qualifies)
    # Manually seed a non-qualifying execution (queued, not succeeded)
    non_qualifying_id = uuid.uuid4()
    now = datetime.now(UTC).replace(tzinfo=None)
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO public.tool_executions
                (id, shop_id, approval_id, tool_name, payload_json, status, created_at, updated_at)
                VALUES (:id, :shop_id, :approval, :tool, :payload, 'queued', :now, :now)
                """
            ),
            {
                "id": str(non_qualifying_id),
                "shop_id": str(tenant_a.shop_id),
                "approval": f"approval-{non_qualifying_id.hex[:8]}",
                "tool": "update_product_price",
                "payload": json.dumps({"product_id": f"tt-{tenant_a.product_id.hex[:10]}"}),
                "now": now,
            },
        )

    # Run the task
    async with juli_app_session() as session:
        reference_date = date.today()
        await run_daily_impact_reader(session, reference_date)
        await session.commit()

    # The enumeration function only returns 'succeeded', so non-qualifying shouldn't be scanned
    # by the enumeration, but if it is, it shouldn't have readings written
    async with juli_app_session(shop_id=tenant_a.shop_id) as session:
        # Count readings for the non-qualifying execution
        stmt_non_qualifying = text(
            """
            SELECT COUNT(*)
            FROM public.impact_readings ir
            WHERE ir.tool_execution_id = :execution_id
            """
        )
        result_non_qualifying = await session.execute(
            stmt_non_qualifying, {"execution_id": str(non_qualifying_id)}
        )
        non_qualifying_count = result_non_qualifying.scalar()

    # The non-qualified execution should have zero readings
    assert non_qualifying_count == 0, (
        f"Non-qualified execution should not have readings; got {non_qualifying_count}"
    )


@pytest.mark.asyncio
async def test_impact_reader_idempotency_preserved(owner_engine):
    """AC4: Idempotency is preserved — running twice on same state writes zero new rows.

    Proves that the per-execution idempotency checks still work correctly.
    """
    seed_tenant(owner_engine, label="idempotency_test")

    # Run the task once
    async with juli_app_session() as session:
        reference_date = date.today()
        await run_daily_impact_reader(session, reference_date)
        await session.commit()

    # Run it again on identical state
    async with juli_app_session() as session:
        reference_date = date.today()
        result_second = await run_daily_impact_reader(session, reference_date)
        await session.commit()

    second_written = result_second.readings_written

    # Second run should write zero new readings
    assert second_written == 0, (
        f"Second run should be idempotent; wrote {second_written} new readings"
    )
