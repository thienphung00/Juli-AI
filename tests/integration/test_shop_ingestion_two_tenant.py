"""Two-tenant proof for per-shop ingestion as `juli_app` (fast track AC-1.12, AC-1.4, AC-1.5).

The SQLite tests in `tests/unit/test_shop_ingestion.py` prove each run ENTERS
its own shop's scope. This proves the database agrees: under row-level security,
as the runtime role, with every ETL commit really committing (so `SET LOCAL` is
really discarded and only the sticky scope's `after_begin` listener puts the
shop back -- the #1967 failure mode).

- the fast phase for shop A lands analytics, sync state and bootstrap state for
  A and nothing for B;
- `shop_ingestion_state` is invisible across tenants and refuses a cross-tenant
  write;
- `enumerate_pollable_shops` (migration 074's definer function) is callable by
  `juli_app` with no tenant context and reports each shop's fast-phase verdict;
- a run for A cannot resolve B's credential.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from juli_backend.services.etl.consumer import EtlConsumer
from juli_backend.services.ingestion import make_etl_handoff
from juli_backend.workers.services.polling import FujiwaPollConfig
from juli_backend.workers.services.polling.ingestion import (
    enumerate_pollable_shops,
    run_bootstrap_fast_phase,
    run_shop_cycle,
)
from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.shop_ingestion_fakes import (
    FakeAnalyticsResource,
    FakeRateLimiter,
    make_resources,
)

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

NOW = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)
LATEST = date(2026, 7, 15)
CONFIG = FujiwaPollConfig(app_key="app-key", app_secret="app-secret")


@asynccontextmanager
async def committing_juli_app_session(shop_id: uuid.UUID | None = None):
    """`juli_app_session`, except a `session.commit()` REALLY commits.

    The shared fixture leaves the connection inside the transaction its own
    `SET ROLE` autobegan, so every session commit is a no-op on the outer
    transaction and a `SET LOCAL` would survive it -- which would make a
    sticky-scope test pass with the listener removed. Here the role switch is
    committed first (SET ROLE is session-level, so it survives), and the
    session owns every transaction after it.
    """
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            if shop_id is not None:
                await conn.execute(
                    text("SELECT set_config('app.current_shop_id', :v, false)").bindparams(
                        v=str(shop_id)
                    )
                )
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
                await session.commit()
            finally:
                await session.close()
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def tenants(owner_engine, two_tenants):
    """Give each seeded tenant a SELLER_CONNECT read credential."""
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


async def _no_sleep(_seconds: float) -> None:
    return None


async def _one_card(session, shop_id):
    return [object()]


def _count(owner_engine, sql: str, shop_id: uuid.UUID) -> int:
    with owner_engine.connect() as conn:
        return conn.execute(text(sql), {"shop": str(shop_id)}).scalar_one()


@pytest.mark.asyncio
async def test_enumeration_runs_as_juli_app_without_tenant_context(tenants):
    tenant_a, tenant_b = tenants
    async with committing_juli_app_session() as session:
        shops = await enumerate_pollable_shops(session)
    by_id = {shop.shop_id: shop.fast_done for shop in shops}
    assert by_id.get(tenant_a.shop_id) is False
    assert by_id.get(tenant_b.shop_id) is False


@pytest.mark.asyncio
async def test_fast_phase_for_one_shop_writes_only_that_shop(owner_engine, tenants):
    tenant_a, tenant_b = tenants
    analytics = FakeAnalyticsResource(prefix="A")

    async with committing_juli_app_session() as session:

        async def dlq(channel, shop_key, payload):
            raise AssertionError(f"ETL routed a row to the DLQ: {channel}")

        result = await run_bootstrap_fast_phase(
            session=session,
            config=CONFIG,
            shop_id=tenant_a.shop_id,
            rate_limiter=FakeRateLimiter(),
            handoff_fn=make_etl_handoff(EtlConsumer(session=session, dlq_handoff=dlq)),
            create_resources=lambda _cfg: make_resources(analytics),
            sleep=_no_sleep,
            now=NOW,
            score_fn=_one_card,
        )
    assert result.analytics is not None and result.analytics.outcome.persisted > 0

    product_days = (
        "SELECT COUNT(DISTINCT start_date) FROM public.analytics_performance_intervals "
        "WHERE shop_id = :shop AND grain = 'product'"
    )
    assert _count(owner_engine, product_days, tenant_a.shop_id) == 30
    assert _count(owner_engine, product_days, tenant_b.shop_id) == 0

    state = (
        "SELECT COUNT(*) FROM public.shop_ingestion_state "
        "WHERE shop_id = :shop AND fast_done_at IS NOT NULL AND first_card_at IS NOT NULL"
    )
    assert _count(owner_engine, state, tenant_a.shop_id) == 1
    assert _count(owner_engine, state, tenant_b.shop_id) == 0

    outcomes = "SELECT COUNT(*) FROM public.tiktok_sync_state WHERE shop_id = :shop"
    assert _count(owner_engine, outcomes, tenant_a.shop_id) > 0
    assert _count(owner_engine, outcomes, tenant_b.shop_id) == 0

    # The fan-out now sees A as bootstrapped and B as not.
    async with committing_juli_app_session() as session:
        by_id = {s.shop_id: s.fast_done for s in await enumerate_pollable_shops(session)}
    assert by_id[tenant_a.shop_id] is True
    assert by_id[tenant_b.shop_id] is False


@pytest.mark.asyncio
async def test_bootstrap_state_is_invisible_and_unwritable_across_tenants(owner_engine, tenants):
    tenant_a, tenant_b = tenants
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.shop_ingestion_state (shop_id, status) "
                "VALUES (:shop, 'fast_running') ON CONFLICT (shop_id) DO NOTHING"
            ),
            {"shop": str(tenant_a.shop_id)},
        )

    async with committing_juli_app_session(shop_id=tenant_b.shop_id) as session:
        visible = (
            await session.execute(text("SELECT shop_id FROM public.shop_ingestion_state"))
        ).all()
        assert {row[0] for row in visible} <= {tenant_b.shop_id}

        with pytest.raises(Exception, match="row-level security"):
            await session.execute(
                text(
                    "INSERT INTO public.shop_ingestion_state (shop_id, status) "
                    "VALUES (:shop, 'not_started')"
                ),
                {"shop": str(tenant_a.shop_id)},
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_a_run_for_one_shop_cannot_resolve_another_shops_credential(tenants):
    from juli_backend.core.security.credential_resolver import (
        NoReadCredentialForShop,
        resolve_read_credential_for_shop,
    )

    tenant_a, tenant_b = tenants

    async def other_shops(session, _shop_id):
        return await resolve_read_credential_for_shop(session, tenant_b.shop_id)

    analytics = FakeAnalyticsResource(prefix="X")
    async with committing_juli_app_session() as session:
        with pytest.raises(NoReadCredentialForShop):
            await run_shop_cycle(
                session=session,
                config=CONFIG,
                shop_id=tenant_a.shop_id,
                rate_limiter=FakeRateLimiter(),
                handoff_fn=make_etl_handoff(
                    EtlConsumer(session=session, dlq_handoff=lambda *a: None)
                ),
                resolve_credential=other_shops,
                create_resources=lambda _cfg: make_resources(analytics),
                sleep=_no_sleep,
                now=NOW,
            )
    assert analytics.calls == {}
