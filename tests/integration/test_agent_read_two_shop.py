"""Two-shop proof, on real Postgres as `juli_app`, that an agent read is built
from the run's OWN shop credential (fast track P61-A, D71.1).

Before P61-A `composition.build_read_resources` resolved the configured
production merchant's credential for every non-sandbox shop and signed with
that merchant's id, so an agent run for shop B read the reference shop's
catalogue. Here two seeded shops each hold their own read credential (one
`production_read`, one `seller_connect`, neither the configured reference
merchant). The read factory is replaced by a fake that records the
`ClientFactoryConfig` it receives; nothing reaches TikTok.

- a read built for shop B carries B's token, cipher and merchant id, never A's;
- the same for shop A, from the same database;
- a shop with no read credential fails closed with `NoReadCredentialForShop`;
- the analytics backfill top-up for B signs with B's merchant id.

The sessions run as `juli_app` (RLS enforced) with NO tenant scope set by the
test: `build_read_resources` must enter the shop's scope itself.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tests.integration.two_tenant import RUNTIME_ROLE

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


@asynccontextmanager
async def juli_app_session():
    """A `juli_app` session with no tenant scope (the code under test sets it)."""
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
                await session.rollback()
                await session.close()
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def shops(owner_engine, two_tenants):
    """Give each tenant its own read credential: A `production_read`, B `seller_connect`."""
    tenant_a, tenant_b = two_tenants
    expected = {}
    with owner_engine.begin() as conn:
        for tenant, label, capability in (
            (tenant_a, "a", "production_read"),
            (tenant_b, "b", "seller_connect"),
        ):
            merchant = f"agent-read-merchant-{label}-{tenant.shop_id.hex[:6]}"
            cipher = f"agent-read-cipher-{label}"
            conn.execute(
                text(
                    "UPDATE public.tiktok_credentials "
                    "SET capability = :capability, merchant_authorization_id = :merchant, "
                    "    shop_cipher = :cipher "
                    "WHERE id = :id"
                ),
                {
                    "capability": capability,
                    "merchant": merchant,
                    "cipher": cipher,
                    "id": str(tenant.fresh_credential_id),
                },
            )
            token = conn.execute(
                text("SELECT access_token FROM public.tiktok_credentials WHERE id = :id"),
                {"id": str(tenant.fresh_credential_id)},
            ).scalar_one()
            expected[tenant.shop_id] = (token, cipher, merchant)
    return tenant_a.shop_id, tenant_b.shop_id, expected


@pytest.fixture
def captured(monkeypatch) -> list[Any]:
    from juli_backend.services.agent import composition

    monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")
    configs: list[Any] = []

    class _Factory:
        def create_resources(self, config):
            configs.append(config)
            return object()

    monkeypatch.setattr(composition, "ProductionReadClientFactory", _Factory)
    return configs


def _triple(config) -> tuple[str, str | None, str]:
    return (config.access_token, config.shop_cipher, config.merchant_auth_id)


@pytest.mark.asyncio
async def test_agent_read_for_shop_b_uses_b_credential_never_a(shops, captured):
    from juli_backend.services.agent.composition import build_read_resources

    shop_a, shop_b, expected = shops

    async with juli_app_session() as session:
        await build_read_resources(session, shop_b)

    assert [_triple(c) for c in captured] == [expected[shop_b]]
    a_token, a_cipher, a_merchant = expected[shop_a]
    assert captured[0].access_token != a_token
    assert captured[0].shop_cipher != a_cipher
    assert captured[0].merchant_auth_id != a_merchant


@pytest.mark.asyncio
async def test_agent_read_for_shop_a_uses_a_credential(shops, captured):
    from juli_backend.services.agent.composition import build_read_resources

    shop_a, _shop_b, expected = shops

    async with juli_app_session() as session:
        await build_read_resources(session, shop_a)

    assert [_triple(c) for c in captured] == [expected[shop_a]]


@pytest.mark.asyncio
async def test_shop_without_read_credential_fails_closed(shops, captured):
    from juli_backend.core.security import NoReadCredentialForShop
    from juli_backend.services.agent.composition import build_read_resources

    unknown_shop = uuid.uuid4()

    async with juli_app_session() as session:
        with pytest.raises(NoReadCredentialForShop) as excinfo:
            await build_read_resources(session, unknown_shop)

    assert str(unknown_shop) in str(excinfo.value)
    assert captured == []


@pytest.mark.asyncio
async def test_backfill_topup_for_shop_b_signs_with_b_merchant(shops, monkeypatch):
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.services.analytics_backfill import orchestrator

    _shop_a, shop_b, expected = shops
    monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")
    configs: list[Any] = []

    class _Stop(Exception):
        pass

    class _Factory:
        def create_resources(self, config):
            configs.append(config)
            raise _Stop

    monkeypatch.setattr(orchestrator, "ProductionReadClientFactory", _Factory)

    async with juli_app_session() as session:
        async with with_shop_scope(session, shop_b):
            with pytest.raises(_Stop):
                await orchestrator.backfill_analytics_history_auto_topup(
                    session,
                    shop_id=shop_b,
                    start_date=date(2026, 3, 16),
                    end_date=date(2026, 3, 16),
                )

    assert [_triple(c) for c in configs] == [expected[shop_b]]
