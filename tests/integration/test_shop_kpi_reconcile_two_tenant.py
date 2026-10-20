"""Two shops, real Postgres, as `juli_app`: the hourly KPI envelope recompute is per shop.

Fast track P61-D (D71.4, ADR-112 §6.5). Rewrites the #1513 reference-shop test
(`test_mock_analytics_reconcile_two_tenant.py`): the task used to recompute
`DEMO_REFERENCE_SHOP_ID`'s envelope only, so every other shop's
`gold.kpi_envelopes` row was never refreshed. This proves, under row-level
security as the runtime role, with every stage commit really committing:

- the fan-out enumerates BOTH shops through migration 074's definer function
  with no tenant context, and enqueues one task each -- no shop id configured;
- each shop's task, through the REAL `SharedComputeOrchestrator` (bronze ->
  silver -> gold), writes that shop's envelope and nothing for the other shop;
- a seller shop (not the configured production merchant) gets the hourly gap
  plan too, and the targeted fetch signs with that shop's own credential;
- the shop-key read is shop-scoped: from A's scope, B's key does not resolve.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.workers.tasks.shop_kpi_reconcile import (
    GAP_PLAN_RESOURCES,
    read_shop_key,
    run_fanout,
    run_shop_kpi_reconcile,
)
from tests.integration.two_tenant import RUNTIME_ROLE, juli_app_session

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


@asynccontextmanager
async def committing_juli_app_session():
    """A `juli_app` session whose `commit()` really commits (no outer transaction).

    The orchestrator commits after every stage and re-enters the shop scope; a
    session nested in the fixture's `SET ROLE` transaction would make those
    commits no-ops and let a lost `SET LOCAL` go unnoticed.
    """
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.close()
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def shops(owner_engine, two_tenants):
    """Both tenants: a SELLER_CONNECT read credential and a finished fast phase."""
    tenant_a, tenant_b = two_tenants
    with owner_engine.begin() as conn:
        for tenant, label in ((tenant_a, "a"), (tenant_b, "b")):
            conn.execute(
                text(
                    "UPDATE public.tiktok_credentials "
                    "SET capability = 'seller_connect', merchant_authorization_id = :merchant, "
                    "    shop_cipher = :cipher "
                    "WHERE id = :id"
                ),
                {
                    "merchant": f"merchant-{label}-{tenant.shop_id.hex[:6]}",
                    "cipher": f"cipher-{label}",
                    "id": str(tenant.fresh_credential_id),
                },
            )
            conn.execute(
                text(
                    "INSERT INTO public.shop_ingestion_state (shop_id, status, fast_done_at) "
                    "VALUES (:shop, 'fast_done', now())"
                ),
                {"shop": str(tenant.shop_id)},
            )
    return tenant_a, tenant_b


def _envelope_computed_at(owner_engine, shop_id: uuid.UUID):
    with owner_engine.connect() as conn:
        return conn.execute(
            text("SELECT computed_at FROM gold.kpi_envelopes WHERE shop_id = :shop"),
            {"shop": str(shop_id)},
        ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_the_fanout_enqueues_both_shops_as_juli_app_without_context(shops):
    tenant_a, tenant_b = shops
    enqueued: list[str] = []

    async with committing_juli_app_session() as session:
        count = await run_fanout(session, enqueue=enqueued.append)

    assert str(tenant_a.shop_id) in enqueued
    assert str(tenant_b.shop_id) in enqueued
    assert count == len(enqueued)


@pytest.mark.asyncio
async def test_each_shops_task_writes_only_that_shops_envelope(shops, owner_engine, monkeypatch):
    tenant_a, tenant_b = shops
    monkeypatch.delenv("CDP_DECISIONS_SCORING_ENABLED", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    plans: dict[uuid.UUID, int] = {}

    async def recording_executor(_session, *, shop_id, shop_key, fetch_plan, idempotency_key):
        # The bronze stage runs with the hourly gap plan for BOTH seller shops:
        # since P61-D the targeted fetch is per shop, not production-merchant-only.
        from juli_backend.services.cdp_speed import BronzeAppendTracker

        plans[shop_id] = len(fetch_plan.resources)
        return BronzeAppendTracker()

    assert _envelope_computed_at(owner_engine, tenant_a.shop_id) is None
    assert _envelope_computed_at(owner_engine, tenant_b.shop_id) is None

    await run_shop_kpi_reconcile(
        tenant_a.shop_id,
        session_factory=committing_juli_app_session,
        fetch_executor=recording_executor,
    )

    a_first = _envelope_computed_at(owner_engine, tenant_a.shop_id)
    assert a_first is not None, "shop A's envelope was not written"
    assert _envelope_computed_at(owner_engine, tenant_b.shop_id) is None, (
        "shop A's run wrote shop B's envelope"
    )

    await run_shop_kpi_reconcile(
        tenant_b.shop_id,
        session_factory=committing_juli_app_session,
        fetch_executor=recording_executor,
    )

    assert _envelope_computed_at(owner_engine, tenant_b.shop_id) is not None, (
        "shop B (not the reference shop) got no envelope -- the pre-P61-D defect"
    )
    assert _envelope_computed_at(owner_engine, tenant_a.shop_id) == a_first, (
        "shop B's run touched shop A's envelope"
    )
    gap = len(GAP_PLAN_RESOURCES)
    assert plans == {tenant_a.shop_id: gap, tenant_b.shop_id: gap}


@pytest.mark.asyncio
async def test_the_shop_key_resolves_only_under_its_own_scope(shops):
    tenant_a, tenant_b = shops

    async with juli_app_session() as session:
        async with with_shop_scope(session, tenant_a.shop_id):
            own = await read_shop_key(session, tenant_a.shop_id)
            other = await read_shop_key(session, tenant_b.shop_id)
        unscoped = await read_shop_key(session, tenant_a.shop_id)

    assert own == tenant_a.tiktok_shop_key
    assert other is None, "resolved another tenant's shop key from inside A's scope"
    assert unscoped is None, "the shop key resolved with no tenant context at all"


@pytest.mark.asyncio
async def test_the_targeted_fetch_signs_each_shop_with_its_own_credential(shops, monkeypatch):
    """P61-D (owner-approved): the executor resolves the JOB shop's credential.

    Real `resolve_read_credential_for_shop` as `juli_app` under each shop's scope;
    only the vendor client and the HTTP fetch are replaced. Before, the executor
    re-resolved the configured production merchant and skipped every other shop.
    """
    from juli_backend.services.cdp_speed import targeted_fetch_executor as tfe
    from juli_backend.services.cdp_speed.targeted_fetch_executor import (
        PartnerFetchEnv,
        execute_targeted_fetch_to_bronze,
    )
    from juli_backend.workers.tasks.shop_kpi_reconcile import make_gap_fetch_plan

    tenant_a, tenant_b = shops
    signed: list[tuple[str, str]] = []
    fetched: list[str] = []

    class _Factory:
        def create_resources(self, config):
            signed.append((config.merchant_auth_id, config.access_token))
            return object()

    async def _no_vendor_call(plan_resource, *, shop_key, **_kwargs):
        fetched.append(shop_key)

    monkeypatch.setattr(tfe, "ProductionReadClientFactory", _Factory)
    monkeypatch.setattr(tfe, "_run_plan_resource", _no_vendor_call)
    env = PartnerFetchEnv(
        app_key="k",
        app_secret="s",
        redirect_uri="https://example.test/cb",
        redis_url="redis://localhost:6379/0",
    )

    for tenant in (tenant_a, tenant_b):
        async with committing_juli_app_session() as session:
            await execute_targeted_fetch_to_bronze(
                session,
                shop_id=tenant.shop_id,
                shop_key=tenant.tiktok_shop_key,
                fetch_plan=make_gap_fetch_plan(tenant.tiktok_shop_key),
                idempotency_key=f"p61d-{uuid.uuid4()}",
                env=env,
            )
            await session.commit()

    merchant_a = f"merchant-a-{tenant_a.shop_id.hex[:6]}"
    merchant_b = f"merchant-b-{tenant_b.shop_id.hex[:6]}"
    assert [m for m, _ in signed] == [merchant_a, merchant_b], signed
    assert signed[0][1] != signed[1][1], "both shops signed with one access token"
    assert set(fetched) == {tenant_a.tiktok_shop_key, tenant_b.tiktok_shop_key}


@pytest.mark.asyncio
async def test_a_job_cannot_borrow_another_shops_credential(shops):
    """Resolving for B from inside a session that just served A finds only B's row."""
    from juli_backend.services.cdp_speed import resolve_job_read_credential

    tenant_a, tenant_b = shops
    async with committing_juli_app_session() as session:
        a = await resolve_job_read_credential(session, tenant_a.shop_id)
        b = await resolve_job_read_credential(session, tenant_b.shop_id)

    assert a is not None and b is not None
    assert a.shop_id == tenant_a.shop_id and b.shop_id == tenant_b.shop_id
    assert a.merchant_authorization_id != b.merchant_authorization_id
