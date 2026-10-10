"""Two-tenant proof for run write values, rules and revert questions as `juli_app`
(fast track AC-8.3, migration 078).

The SQLite tests (`tests/unit/test_run_changes_revert.py`,
`tests/unit/test_shop_rules.py`) prove the services and routes filter on the
caller's shop. This proves the database agrees, under row-level security, as
the runtime role, with real commits:

- the worker's recorder, scoped to shop A, writes A's before/after rows; shop B
  sees none of them and cannot insert a row for A;
- a rule set by A is invisible to B, and B can neither insert nor delete one
  for A;
- under B's scope, A's run cannot be reverted (it does not exist for B); under
  A's scope the revert run is created and linked;
- a "Hoàn tác?" question for A cannot be written from B's scope.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from juli_backend.services import run_changes, shop_rules
from juli_backend.services.agent.runner.write_capture import FieldWrite
from tests.integration.two_tenant import RUNTIME_ROLE

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

PRODUCT_TIKTOK_ID = "tt-revert-proof"


def _set_scope_sql() -> str:
    return "SELECT set_config('app.current_shop_id', :v, false)"


@asynccontextmanager
async def committing_juli_app_session(shop_id: uuid.UUID):
    """A `juli_app` async session scoped to one shop whose commits really commit."""
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            await conn.execute(text(_set_scope_sql()).bindparams(v=str(shop_id)))
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
                await session.commit()
            finally:
                await session.close()
    finally:
        await engine.dispose()


@contextmanager
def juli_app_sync_session(shop_id: uuid.UUID):
    """The worker's shape: a sync session as `juli_app` under a sticky shop scope."""
    from juli_backend.core.config.runtime import sync_database_url

    engine = create_engine(sync_database_url(os.environ["DATABASE_URL"]))
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            conn.execute(text(_set_scope_sql()), {"v": str(shop_id)})
            conn.commit()
            session = Session(bind=conn)
            try:
                yield session
            finally:
                session.close()
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def finished_runs(owner_engine, two_tenants):
    """Per tenant: a product with a completed run that wrote its title."""
    now = datetime.now(UTC).replace(tzinfo=None)
    seeded = {}
    with owner_engine.begin() as conn:
        for tenant in two_tenants:
            product_id, run_id = uuid.uuid4(), uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO public.products (id, shop_id, tiktok_product_id, name, status, "
                    " revenue, units_sold, update_time, created_at, updated_at) "
                    "VALUES (:id, :shop, :tt, 'revert proof', 'ACTIVE', 0, 0, :now, :now, :now)"
                ),
                {
                    "id": str(product_id),
                    "shop": str(tenant.shop_id),
                    "tt": PRODUCT_TIKTOK_ID,
                    "now": now,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO public.workflow_runs (id, shop_id, product_id, state, status, "
                    " prompt_version, prompt_sha256, running_seconds_elapsed, cancel_requested, "
                    " subject_ref, created_at, updated_at) "
                    "VALUES (:id, :shop, :product, :state, 'completed', 'optimize_product.v3', "
                    " :sha, 0, false, :product, :now, :now)"
                ),
                {
                    "id": str(run_id),
                    "shop": str(tenant.shop_id),
                    "product": str(product_id),
                    "state": json.dumps({}),
                    "sha": "0" * 64,
                    "now": now,
                },
            )
            seeded[tenant.shop_id] = (product_id, run_id)
    return seeded


def _count(owner_engine, table: str, shop_id: uuid.UUID) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(
            text(f"SELECT COUNT(*) FROM public.{table} WHERE shop_id = :shop"),  # nosec B608
            {"shop": str(shop_id)},
        ).scalar_one()


def test_the_recorder_writes_only_under_its_own_shop(owner_engine, two_tenants, finished_runs):
    tenant_a, tenant_b = two_tenants
    _product_a, run_a = finished_runs[tenant_a.shop_id]

    with juli_app_sync_session(tenant_a.shop_id) as session:
        run_changes.SqlWriteValueRecorder(
            session, shop_id=tenant_a.shop_id, workflow_run_id=run_a
        ).record(
            tool_name="update_product_listing",
            tool_call_id="call-1",
            tiktok_product_id=PRODUCT_TIKTOK_ID,
            writes=[FieldWrite("title", "Tiêu đề cũ", "Tiêu đề Juli", "read_back")],
        )
    assert _count(owner_engine, "run_write_values", tenant_a.shop_id) == 1
    assert _count(owner_engine, "run_write_values", tenant_b.shop_id) == 0

    with juli_app_sync_session(tenant_b.shop_id) as session:
        visible = session.execute(text("SELECT shop_id FROM public.run_write_values")).all()
        assert {row[0] for row in visible} <= {tenant_b.shop_id}
        # B's scope recording a row for A's run: refused by RLS, logged, not raised.
        run_changes.SqlWriteValueRecorder(
            session, shop_id=tenant_a.shop_id, workflow_run_id=run_a
        ).record(
            tool_name="update_product_listing",
            tool_call_id="call-2",
            tiktok_product_id=PRODUCT_TIKTOK_ID,
            writes=[FieldWrite("description", "a", "b", "read_back")],
        )
    assert _count(owner_engine, "run_write_values", tenant_a.shop_id) == 1


@pytest.mark.asyncio
async def test_rules_are_invisible_and_unwritable_across_tenants(owner_engine, two_tenants):
    tenant_a, tenant_b = two_tenants
    async with committing_juli_app_session(tenant_a.shop_id) as session:
        await shop_rules.set_rule(
            session,
            tenant_a.shop_id,
            rule_key="max_open_cards",
            scope_ref=None,
            value=6,
            set_by="team",
            set_by_user_id=tenant_a.user_id,
        )
    assert _count(owner_engine, "shop_rules", tenant_a.shop_id) == 1

    async with committing_juli_app_session(tenant_b.shop_id) as session:
        assert await shop_rules.configured_max_open_cards(session, tenant_a.shop_id) is None
        assert not await shop_rules.delete_rule(
            session, tenant_a.shop_id, rule_key="max_open_cards", scope_ref=None
        )
        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO public.shop_rules (id, shop_id, rule_key, scope_ref, value, "
                    " set_by, set_at) "
                    "VALUES (:id, :shop, 'max_open_cards', '', '3', 'seller', now())"
                ),
                {"id": str(uuid.uuid4()), "shop": str(tenant_a.shop_id)},
            )
        await session.rollback()
    assert _count(owner_engine, "shop_rules", tenant_a.shop_id) == 1

    async with committing_juli_app_session(tenant_a.shop_id) as session:
        assert await shop_rules.configured_max_open_cards(session, tenant_a.shop_id) == 6


@pytest.mark.asyncio
async def test_a_run_is_revertible_only_from_its_own_shop(owner_engine, two_tenants, finished_runs):
    tenant_a, tenant_b = two_tenants
    _product_a, run_a = finished_runs[tenant_a.shop_id]

    async def _live(session, shop_id, tiktok_product_id):
        return {"title": "Tiêu đề Juli", "description": None, "main_images": []}

    async with committing_juli_app_session(tenant_b.shop_id) as session:
        with pytest.raises(run_changes.RevertRunNotFound):
            await run_changes.start_revert(
                session,
                shop_id=tenant_b.shop_id,
                run_id=run_a,
                started_by_user_id=tenant_b.user_id,
                read_live_product=_live,
            )
        await session.rollback()

    async with committing_juli_app_session(tenant_a.shop_id) as session:
        started = await run_changes.start_revert(
            session,
            shop_id=tenant_a.shop_id,
            run_id=run_a,
            started_by_user_id=tenant_a.user_id,
            read_live_product=_live,
        )
    with owner_engine.connect() as conn:
        row = conn.execute(
            text("SELECT shop_id, reverts_run_id, status FROM public.workflow_runs WHERE id = :id"),
            {"id": str(started.run_id)},
        ).one()
    assert (row[0], row[1], row[2]) == (tenant_a.shop_id, run_a, "queued")


@pytest.mark.asyncio
async def test_a_question_cannot_be_raised_for_another_shop(
    owner_engine, two_tenants, finished_runs
):
    tenant_a, tenant_b = two_tenants
    _product_a, run_a = finished_runs[tenant_a.shop_id]
    async with committing_juli_app_session(tenant_b.shop_id) as session:
        with pytest.raises(Exception, match="row-level security"):
            await run_changes.raise_revert_question(
                session,
                shop_id=tenant_a.shop_id,
                run_id=run_a,
                breaches=[run_changes.BandBreach("ctr", Decimal("0.2"), Decimal(3))],
            )
        await session.rollback()
    assert _count(owner_engine, "run_revert_questions", tenant_a.shop_id) == 0
