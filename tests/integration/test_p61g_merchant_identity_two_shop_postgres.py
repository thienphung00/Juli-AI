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


def _seed_bare_shop() -> uuid.UUID:
    """A shop with no credential at all (P64: the sandbox row never reads for it)."""
    user_id, shop_id = uuid.uuid4(), uuid.uuid4()
    with owner_sync_engine() as engine, engine.begin() as conn:
        conn.execute(
            text("INSERT INTO public.users (id, phone) VALUES (:id, :phone)"),
            {"id": str(user_id), "phone": f"+1555{user_id.hex[:7]}"},
        )
        conn.execute(
            text("INSERT INTO public.shops (id, user_id, shop_name) VALUES (:id, :u, 'bare')"),
            {"id": str(shop_id), "u": str(user_id)},
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

        # P64 (D73.2a): the sandbox shop reads through its OWN sandbox row, and only it.
        async with with_shop_scope(session, sandbox):
            own = await resolve_read_credential_for_shop(session, sandbox)
            assert (own.shop_id, own.capability) == (sandbox, "sandbox_write")
        bare = _seed_bare_shop()
        async with with_shop_scope(session, bare):
            with pytest.raises(NoReadCredentialForShop):
                await resolve_read_credential_for_shop(session, bare)

        # The sandbox shop is pollable (through its own row), beside the production shops.
        pollable = {p.shop_id for p in await enumerate_pollable_shops(session)}
        assert {shop_a, shop_b, sandbox} <= pollable


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


def _seed_for_shop(engine, shop_id, *, capability: TikTokCapability, merchant: str, cipher: str):
    now = datetime.now(UTC).replace(tzinfo=None)
    with engine.begin() as conn:
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


async def test_sandbox_shop_with_its_own_seller_connect_row_sharing_a_cipher_is_usable():
    """Production fact 2026-10-21 (D71.6a, migration 100): the sandbox shop holds sandbox_write
    (merchant A) and seller_connect (merchant B) with ONE cipher -- same shop, not a collision."""
    t = _tag()
    with owner_sync_engine() as engine:
        _clear_sandbox(engine)
        sbx = _seed(
            engine, capability=TikTokCapability.SANDBOX_WRITE, merchant=f"sa-{t}", cipher=f"S{t}"
        )
        _seed_for_shop(
            engine,
            sbx,
            capability=TikTokCapability.SELLER_CONNECT,
            merchant=f"sb-{t}",
            cipher=f"S{t}",
        )
        prod = _seed(
            engine, capability=TikTokCapability.SELLER_CONNECT, merchant=f"p-{t}", cipher=f"P{t}"
        )

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        credential = await resolve_sandbox_write_credential(session)
        assert credential.shop_id == sbx
        assert credential.merchant_authorization_id == f"sa-{t}"
        # The sandbox merchant stays unreachable from a production path; the production shop
        # and the sandbox shop's own seller_connect row (merchant B) behave as before P61-G.
        assert (await sandbox_write_merchant_ids(session)) == {f"sa-{t}"}
        async with with_shop_scope(session, prod):
            assert (await resolve_read_credential_for_shop(session, prod)).shop_id == prod


async def test_sandbox_row_sharing_merchant_or_cipher_with_another_shop_is_refused_beside_own():
    """The 2026-08-18 case stays caught even when the sandbox shop also has its own seller row."""
    t = _tag()
    for shared in ("cipher", "merchant"):
        with owner_sync_engine() as engine:
            _clear_sandbox(engine)
            sbx = _seed(
                engine,
                capability=TikTokCapability.SANDBOX_WRITE,
                merchant=f"sa-{t}",
                cipher=f"S{t}",
            )
            _seed_for_shop(
                engine,
                sbx,
                capability=TikTokCapability.SELLER_CONNECT,
                merchant=f"sb-{t}",
                cipher=f"S{t}",
            )
            _seed(
                engine,
                capability=TikTokCapability.SELLER_CONNECT,
                merchant=f"sa-{t}" if shared == "merchant" else f"p-{t}",
                cipher=f"S{t}" if shared == "cipher" else f"P{t}",
            )
        async with juli_app_async_sessionmaker() as factory, factory() as session:
            with pytest.raises(SandboxCredentialRefused):
                await resolve_sandbox_write_credential(session)


def test_migration_100_function_body_is_cross_shop_and_keeps_099_hardening():
    with owner_sync_engine() as engine, engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT pg_get_functiondef(p.oid), p.prosecdef, p.proconfig::text "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'public' AND p.proname = 'enumerate_sandbox_write_credentials'"
            )
        ).one()
    assert "o.shop_id <> c.shop_id" in row[0]
    assert row[1] is True
    assert "search_path=pg_catalog, public" in row[2]
