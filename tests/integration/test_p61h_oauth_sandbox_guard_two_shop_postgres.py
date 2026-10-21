"""Two shops, real Postgres, as `juli_app`: OAuth refuses a cross-shop sandbox collision (P61-H).

Owner 2026-10-21 (D71.6a): the sandbox shop may hold a `seller_connect` row of its own; what must
never be written is another shop's credential carrying the sandbox row's merchant id or cipher,
or a `sandbox_write` row reaching another shop's. The guard asks migration 100's cross-tenant
function (the resolver's own predicate), so RLS hiding the other shop's rows does not blind it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url
from juli_backend.core.security import (
    SandboxCollisionRefused,
    resolve_sandbox_write_credential,
)
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.integrations.tiktok import TikTokAuth, TikTokCapability
from juli_backend.repositories import TikTokCredentialRepo
from tests.support.postgres import (
    database_url,
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


@asynccontextmanager
async def _callback_session() -> AsyncIterator[AsyncSession]:
    """The OAuth callback's session: it creates the shop and its credential in one request, which
    no single tenant GUC permits under RLS, so it runs with the table owner's privileges."""
    engine = create_async_engine(async_database_url(database_url()))
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


def _tag() -> str:
    return uuid.uuid4().hex[:10]


def _user(engine) -> uuid.UUID:
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1555{user_id.hex[:7]}", "now": now},
        )
    return user_id


def _shop(engine, user_id: uuid.UUID, *, open_id: str | None = None) -> uuid.UUID:
    now = datetime.now(UTC).replace(tzinfo=None)
    shop_id = uuid.uuid4()
    with engine.begin() as conn:
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
                "t": open_id or f"tt-{shop_id.hex[:10]}",
                "now": now,
            },
        )
    return shop_id


def _credential(engine, shop_id, *, capability: TikTokCapability, merchant: str, cipher: str):
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


def _clear_sandbox(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM public.tiktok_credentials WHERE capability = 'sandbox_write'")
        )


def _counts(engine, open_id: str) -> tuple[int, int]:
    with engine.connect() as conn:
        shops = conn.execute(
            text("SELECT count(*) FROM public.shops WHERE tiktok_shop_id = :t"), {"t": open_id}
        ).scalar_one()
        creds = conn.execute(
            text(
                "SELECT count(*) FROM public.tiktok_credentials "
                "WHERE merchant_authorization_id = :t"
            ),
            {"t": open_id},
        ).scalar_one()
    return shops, creds


def _service(session, cipher: str) -> TikTokOAuthService:
    async def verifier(_session, *, capability, access_token):
        return cipher

    return TikTokOAuthService(
        tiktok_auth=TikTokAuth(app_key="k", app_secret="s", base_url="https://example.test"),
        session=session,
        redirect_uri="https://example.test/cb",
        app_secret="s",
        binding_verifier=verifier,
    )


def _token(open_id: str) -> dict:
    return {
        "open_id": open_id,
        "access_token": "a",
        "refresh_token": "r",
        "seller_name": "Shop",
        "access_token_expire_in": 604800,
    }


def _seed_sandbox_shop(engine, t: str):
    """The sandbox shop: `sandbox_write` (merchant A) + its own `seller_connect` row."""
    _clear_sandbox(engine)
    user = _user(engine)
    shop = _shop(engine, user, open_id=f"sbx-open-{t}")
    _credential(
        engine, shop, capability=TikTokCapability.SANDBOX_WRITE, merchant=f"sa-{t}", cipher=f"S{t}"
    )
    return user, shop


async def test_same_shop_seller_connect_on_the_sandbox_shop_is_allowed():
    t = _tag()
    with owner_sync_engine() as engine:
        user, sandbox = _seed_sandbox_shop(engine, t)

    async with _callback_session() as session:
        shop = await _service(session, f"S{t}").provision_shop_and_credentials(
            _token(f"sbx-open-{t}"), user_id=user, capability=TikTokCapability.SELLER_CONNECT
        )
        await session.commit()
        assert shop.id == sandbox

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        assert (await resolve_sandbox_write_credential(session)).shop_id == sandbox


@pytest.mark.parametrize("carried", ["cipher", "merchant"])
async def test_another_shops_oauth_carrying_the_sandbox_identity_is_refused_with_no_write(carried):
    t = _tag()
    open_id = f"other-{t}"
    with owner_sync_engine() as engine:
        _seed_sandbox_shop(engine, t)
        seller = _user(engine)
    # A merchant collision means the OAuth open_id (the merchant id) IS the sandbox merchant.
    token_open_id = f"sa-{t}" if carried == "merchant" else open_id
    cipher = f"S{t}" if carried == "cipher" else f"OWN{t}"

    async with _callback_session() as session:
        with pytest.raises(SandboxCollisionRefused):
            await _service(session, cipher).provision_shop_and_credentials(
                _token(token_open_id), user_id=seller
            )
        await session.rollback()

    with owner_sync_engine() as engine:
        assert _counts(engine, token_open_id)[0] == 0
        with engine.connect() as conn:
            created = conn.execute(
                text("SELECT count(*) FROM public.shops WHERE user_id = :u"), {"u": str(seller)}
            ).scalar_one()
        assert created == 0  # no orphan shop

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        assert (
            await resolve_sandbox_write_credential(session)
        ).merchant_authorization_id == f"sa-{t}"


async def test_an_unrelated_second_shop_connects_while_the_sandbox_shop_exists():
    t = _tag()
    with owner_sync_engine() as engine:
        _seed_sandbox_shop(engine, t)
        seller = _user(engine)

    async with _callback_session() as session:
        await _service(session, f"OWN{t}").provision_shop_and_credentials(
            _token(f"seller-{t}"), user_id=seller
        )
        await session.commit()

    with owner_sync_engine() as engine:
        assert _counts(engine, f"seller-{t}") == (1, 1)


async def test_a_sandbox_write_pointing_at_another_shops_cipher_is_refused():
    t = _tag()
    with owner_sync_engine() as engine:
        _clear_sandbox(engine)
        prod_user = _user(engine)
        prod = _shop(engine, prod_user)
        _credential(
            engine,
            prod,
            capability=TikTokCapability.SELLER_CONNECT,
            merchant=f"p-{t}",
            cipher=f"P{t}",
        )
        operator = _user(engine)

    async with _callback_session() as session:
        with pytest.raises(SandboxCollisionRefused):
            await _service(session, f"P{t}").provision_shop_and_credentials(
                _token(f"sbx-{t}"), user_id=operator, capability=TikTokCapability.SANDBOX_WRITE
            )
        await session.rollback()

    with owner_sync_engine() as engine:
        assert _counts(engine, f"sbx-{t}") == (0, 0)
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM public.tiktok_credentials "
                        "WHERE capability = 'sandbox_write'"
                    )
                ).scalar_one()
                == 0
            )


async def test_rls_does_not_blind_the_guard_a_scoped_reconnect_onto_the_sandbox_cipher_is_refused():
    """As `juli_app` under the seller shop's own scope the sandbox shop's rows are invisible;
    the guard still sees the collision because it asks the cross-tenant function."""
    t = _tag()
    with owner_sync_engine() as engine:
        _seed_sandbox_shop(engine, t)
        seller = _user(engine)
        shop = _shop(engine, seller, open_id=f"seller-{t}")
        _credential(
            engine,
            shop,
            capability=TikTokCapability.SELLER_CONNECT,
            merchant=f"seller-{t}",
            cipher=f"OWN{t}",
        )

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        async with with_shop_scope(session, shop):
            with pytest.raises(SandboxCollisionRefused):
                await _service(session, f"S{t}").provision_shop_and_credentials(
                    _token(f"seller-{t}"), user_id=seller
                )
        await session.rollback()

    with owner_sync_engine() as engine, engine.connect() as conn:
        cipher = conn.execute(
            text("SELECT shop_cipher FROM public.tiktok_credentials WHERE shop_id = :s"),
            {"s": str(shop)},
        ).scalar_one()
    assert cipher == f"OWN{t}"


async def test_a_reconnect_and_a_token_refresh_of_an_ordinary_shop_are_not_blocked():
    t = _tag()
    with owner_sync_engine() as engine:
        _seed_sandbox_shop(engine, t)
        seller = _user(engine)
        shop = _shop(engine, seller, open_id=f"seller-{t}")
        _credential(
            engine,
            shop,
            capability=TikTokCapability.SELLER_CONNECT,
            merchant=f"seller-{t}",
            cipher=f"OWN{t}",
        )

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        async with with_shop_scope(session, shop):
            await _service(session, f"OWN{t}").provision_shop_and_credentials(
                _token(f"seller-{t}"), user_id=seller
            )
            repo = TikTokCredentialRepo(session)
            row = await repo.get_by_shop_and_capability(shop, TikTokCapability.SELLER_CONNECT)
            refreshed = await repo.mark_refreshed(
                row.id, "a2", "r2", datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7)
            )
            assert refreshed.shop_cipher == f"OWN{t}"
            await session.commit()
