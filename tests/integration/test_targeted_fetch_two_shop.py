"""Two shops, real Postgres, as `juli_app`: the targeted fetch is per shop (fast track P61-D).

Owner-approved scope add (2026-10-20): `services/cdp_speed/targeted_fetch_executor.py`
used to re-resolve the configured production merchant and sign with
`PRODUCTION_AUTH_ID`, so the targeted fetch served one shop and skipped every
other shop's job. It now resolves the JOB shop's own read credential
(`resolve_read_credential_for_shop`) and signs with that credential's merchant id.
Only the vendor client and the HTTP fetch are replaced here; credential
resolution runs for real under RLS.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.services.cdp_speed import TargetedFetchPlan, static_fetch_resource
from tests.integration.two_tenant import RUNTIME_ROLE

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


def _gap_plan(shop_key: str) -> TargetedFetchPlan:
    names = ("orders", "ctor")
    return TargetedFetchPlan(
        catalog_id=None,
        shop_id=shop_key,
        resources=tuple(static_fetch_resource(n) for n in names),
    )


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
    """Both tenants: a SELLER_CONNECT read credential with their own merchant id."""
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
    return tenant_a, tenant_b


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
                fetch_plan=_gap_plan(tenant.tiktok_shop_key),
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
