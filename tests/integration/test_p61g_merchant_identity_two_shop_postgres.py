"""Two production shops + the sandbox shop, real Postgres, as `juli_app`, NO merchant env (P61-G).

Owner decision 2026-10-21 (D71.6): merchant ids are neither hardcoded nor configured. Each shop's
merchant id is the one on its own credential row; the sandbox credential is the row whose
capability is `sandbox_write`. Nothing is set in the environment here, and everything works.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from juli_backend.core.security import (
    NoReadCredentialForShop,
    SandboxCredentialRefused,
    resolve_read_credential_for_shop,
    resolve_sandbox_write_credential,
    sandbox_write_merchant_ids,
)
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    TikTokCapability,
)
from juli_backend.services.execution.sandbox_guard import load_sandbox_write_resources
from juli_backend.workers.services.polling.ingestion import enumerate_pollable_shops
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


@pytest.fixture(autouse=True)
def _no_merchant_env(monkeypatch):
    monkeypatch.delenv("TIKTOK_PRODUCTION_MERCHANT_ID", raising=False)
    monkeypatch.delenv("TIKTOK_SANDBOX_MERCHANT_ID", raising=False)


def _seed(engine, *, capability: TikTokCapability, merchant: str, cipher: str) -> uuid.UUID:
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id, shop_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1555{user_id.hex[:7]}", "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO public.shops "
                "(id, user_id, shop_name, tiktok_shop_id, created_at, updated_at) "
                "VALUES (:id, :u, :n, :t, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "u": str(user_id),
                "n": f"shop-{shop_id.hex[:6]}",
                "t": f"tt-{shop_id.hex[:10]}",
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.tiktok_credentials "
                "(id, shop_id, merchant_authorization_id, capability, shop_cipher, access_token, "
                " refresh_token, token_expires_at, status, refresh_count, created_at, updated_at) "
                "VALUES (:id, :s, :m, :c, :ci, 'a', 'r', :exp, 'active', 0, :now, :now)"
            ),
            {
                "id": str(uuid.uuid4()),
                "s": str(shop_id),
                "m": merchant,
                "c": capability.value,
                "ci": cipher,
                "exp": now + timedelta(days=30),
                "now": now,
            },
        )
    return shop_id


def _tag() -> str:
    return uuid.uuid4().hex[:10]


def _clear_sandbox(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM public.tiktok_credentials WHERE capability = 'sandbox_write'")
        )


async def test_three_shops_each_use_their_own_merchant_with_no_env():
    t = _tag()
    with owner_sync_engine() as engine:
        _clear_sandbox(engine)
        sandbox = _seed(
            engine, capability=TikTokCapability.SANDBOX_WRITE, merchant=f"sbx-{t}", cipher=f"CS{t}"
        )
        shop_a = _seed(
            engine, capability=TikTokCapability.SELLER_CONNECT, merchant=f"a-{t}", cipher=f"CA{t}"
        )
        shop_b = _seed(
            engine, capability=TikTokCapability.PRODUCTION_READ, merchant=f"b-{t}", cipher=f"CB{t}"
        )

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        # The sandbox credential, found by capability across tenants.
        sandbox_credential = await resolve_sandbox_write_credential(session)
        assert sandbox_credential.shop_id == sandbox
        assert sandbox_credential.merchant_authorization_id == f"sbx-{t}"
        merchants = await sandbox_write_merchant_ids(session)
        assert merchants == frozenset({f"sbx-{t}"})

        # Sandbox resources are built from the credential alone.
        resources = await load_sandbox_write_resources(session, app_key="k", app_secret="s")
        assert resources is not None

        # Each production shop resolves ITS OWN credential and signs as ITS OWN merchant.
        for shop_id, merchant in ((shop_a, f"a-{t}"), (shop_b, f"b-{t}")):
            async with with_shop_scope(session, shop_id):
                credential = await resolve_read_credential_for_shop(session, shop_id)
                assert credential.shop_id == shop_id
                assert credential.merchant_authorization_id == merchant
                client = ProductionReadClientFactory().create(
                    ClientFactoryConfig(
                        app_key="k",
                        app_secret="s",
                        access_token=credential.access_token,
                        merchant_auth_id=merchant,
                        shop_cipher=credential.shop_cipher,
                        credential_capability=credential.capability,
                        sandbox_merchant_auth_ids=merchants,
                    )
                )
                assert client is not None

        # The sandbox shop is unreachable from any read path.
        async with with_shop_scope(session, sandbox):
            with pytest.raises(NoReadCredentialForShop):
                await resolve_read_credential_for_shop(session, sandbox)

        # And it is not a pollable shop; the two production shops are.
        pollable = {p.shop_id for p in await enumerate_pollable_shops(session)}
        assert {shop_a, shop_b} <= pollable
        assert sandbox not in pollable


async def test_a_sandbox_row_whose_token_resolves_to_a_production_shop_is_refused():
    """2026-08-18 on PostgreSQL: same shop cipher as a production row, so every sandbox path
    refuses it -- from credentials alone, with nothing configured."""
    t = _tag()
    with owner_sync_engine() as engine:
        _clear_sandbox(engine)
        _seed(
            engine, capability=TikTokCapability.PRODUCTION_READ, merchant=f"p-{t}", cipher=f"X{t}"
        )
        _seed(engine, capability=TikTokCapability.SANDBOX_WRITE, merchant=f"s-{t}", cipher=f"X{t}")

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        with pytest.raises(SandboxCredentialRefused):
            await resolve_sandbox_write_credential(session)
        with pytest.raises(SandboxCredentialRefused):
            await load_sandbox_write_resources(session, app_key="k", app_secret="s")
