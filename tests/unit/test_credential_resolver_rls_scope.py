"""Regression for #2019: the credential resolve ran outside any shop scope, so
RLS hid the credential it needed.

From 05:28 UTC 2026-09-16 the `fujiwa-poll-cycle` beat entry (#1949) failed
every fifteen minutes with

    NotFound('No credentials for merchant 7658073774813611784 with
             capability production_read')

raised from `workers/services/polling/orchestrate.py::run_fujiwa_poll_cycle`.
`orders` and `inventory_items` held at zero for the whole window. The
credential was present, `active`, and unexpired. What was absent was the tenant
GUC: `tiktok_credentials_select_public` carries qual
`(shop_id = app_current_shop_id())`, the worker connects as `juli_app`
(`rolbypassrls = f`), and `resolve_production_read_credential` (deleted in P61-G) queried before
any scope was entered -- it had to, because the scope on the line below it
needs `credential.shop_id`, and the credential is what supplies it.

THE FIX these tests now hold green. Migration 061 adds
`enumerate_credential_owner_shop`, a `SECURITY DEFINER` function returning the
owning shop id and nothing else (ADR-089 decisions 3-4, the shape migration 051
already established for `credential_refresh_beat`). The resolve enumerates,
enters `with_shop_scope(shop_id)`, and does the real read -- tokens, decrypt,
lazy refresh -- inside it.

Three of these tests were committed `xfail(strict=True)` while the fix was
still an integrations-to-data-platform handoff, precisely so the suite would
turn RED the moment it landed rather than going quietly green. It did; the
marks came off in the same commit as the migration.

WHY EVERY OTHER TEST PASSED THROUGHOUT. The unit suites bind to a SQLite
fixture where row-level security does not exist, so a scope-less read returns
the row and the defect is invisible. These tests therefore run against real
Postgres, under the real policies, as the real non-bypassing runtime role --
the session factory from `tests.support.postgres`, the same reasoning as
`test_fujiwa_poll_cycle_scope_across_commits.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from juli_backend.core.security.credential_resolver import (
    NoReadCredentialForShop,
    SandboxCredentialRefused,
    resolve_read_credential_for_shop,
    resolve_sandbox_write_credential,
    sandbox_write_merchant_ids,
)
from juli_backend.database.exceptions import NotFound
from juli_backend.database.tenant_context import system_scope, with_shop_scope
from juli_backend.integrations.tiktok import TikTokCapability
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)


def _unique_merchant(prefix: str) -> str:
    """A merchant id no other row has -- identities come from the rows (P61-G, D71.6)."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _clear_sandbox_credentials(engine) -> None:
    """Remove every sandbox_write row so the capability lookup sees only this test's."""
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM public.tiktok_credentials WHERE capability = 'sandbox_write'")
        )


def _seed_credential(
    engine,
    *,
    label: str,
    merchant_id: str | None = None,
    cipher: str | None = None,
    capability: TikTokCapability = TikTokCapability.PRODUCTION_READ,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed one shop and the credential it owns (merchant id and cipher unique by default).

    Takes the pair as arguments so the sandbox-write resolver is proved against the same
    fixture as the per-shop read resolver rather than a near-copy that could drift.

    Seeded owner-side on purpose: set-up is not the thing under test, and
    seeding under RLS would make a fixture failure look like an isolation
    failure.

    Returns ``(shop_id, credential_id)``.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    merchant_id = merchant_id or _unique_merchant("merchant")
    cipher = cipher or f"ROW_{uuid.uuid4().hex[:16]}"
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()
    credential_id = uuid.uuid4()

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
                "VALUES (:id, :user_id, :name, :tiktok_shop_id, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "user_id": str(user_id),
                "name": f"{label} shop",
                "tiktok_shop_id": f"tt-{shop_id.hex[:10]}",
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.tiktok_credentials "
                "(id, shop_id, merchant_authorization_id, capability, shop_cipher, "
                " access_token, refresh_token, token_expires_at, status, refresh_count, "
                " created_at, updated_at) "
                "VALUES (:id, :shop_id, :merchant_id, :capability, :cipher, "
                " :access, :refresh, :expires, 'active', 0, :now, :now)"
            ),
            {
                "id": str(credential_id),
                "shop_id": str(shop_id),
                "merchant_id": merchant_id,
                "capability": capability.value,
                "cipher": cipher,
                "access": "fujiwa-access",
                "refresh": "fujiwa-refresh",
                # Far from expiry, so `_lazy_refresh`'s own freshness guard
                # returns without a vendor call and this test needs no HTTP
                # double: the resolve, not the refresh, is under test.
                "expires": now + timedelta(days=30),
                "now": now,
            },
        )

    return shop_id, credential_id


@requires_postgres
@pytest.mark.asyncio
async def test_system_scope_confers_no_database_access():
    """ADR-089 decision 1, asserted rather than assumed.

    `system_scope` is "a Python flag and a log line -- no `set_config`, no
    `SET ROLE`, no SQL" (migration 051's own docstring). It suppresses the
    `TenantContextRequiredError` fail-closed assertion and nothing else, so it
    cannot make an RLS-hidden row visible.

    This is pinned because #2019 was filed proposing `system_scope` as the fix
    for exactly that. If a future change ever makes this test fail, the flag
    has grown a database-layer claim that ADR-089 decision 1 forbids, and the
    boot-time isolation guarantee is weaker than it reads.
    """
    sysscope_merchant = _unique_merchant("sysscope")
    with owner_sync_engine() as engine:
        _seed_credential(engine, label="resolve-sysscope", merchant_id=sysscope_merchant)

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        async with system_scope(session, caller="test_2019"):
            result = await session.execute(
                text(
                    "SELECT count(*) FROM public.tiktok_credentials "
                    "WHERE merchant_authorization_id = :m"
                ),
                {"m": sysscope_merchant},
            )
            assert result.scalar() == 0, (
                "system_scope made an RLS-hidden row visible; it sets no GUC "
                "and must never confer database access (ADR-089 decision 1)"
            )

            # And the GUC is still unset inside the scope -- the direct reason.
            guc = await session.execute(text("SELECT app_current_shop_id()"))
            assert guc.scalar() is None


@requires_postgres
@pytest.mark.asyncio
async def test_sandbox_write_resolve_finds_the_credential_by_capability_without_a_prior_scope():
    """The sandbox resolve finds its credential by CAPABILITY, as `juli_app`, with no tenant
    context established -- because none can be: the shop id the scope needs is the one the
    enumeration returns. No merchant id is configured or passed (P61-G, D71.6).

    Surrounding production rows (another tenant's, other merchants) must not be returned.
    """
    with owner_sync_engine() as engine:
        _clear_sandbox_credentials(engine)
        _seed_credential(engine, label="decoy-prod", capability=TikTokCapability.PRODUCTION_READ)
        _seed_credential(engine, label="decoy-seller", capability=TikTokCapability.SELLER_CONNECT)
        shop_id, credential_id = _seed_credential(
            engine, label="sandbox-scope", capability=TikTokCapability.SANDBOX_WRITE
        )

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        credential = await resolve_sandbox_write_credential(session)

        assert credential.id == credential_id
        assert credential.shop_id == shop_id
        assert credential.access_token
        assert credential.capability == TikTokCapability.SANDBOX_WRITE

        leaked = await session.execute(text("SELECT app_current_shop_id()"))
        assert leaked.scalar() is None, "the sandbox resolve left a tenant context behind it"


@requires_postgres
@pytest.mark.asyncio
async def test_sandbox_write_resolve_raises_not_found_when_no_sandbox_credential_exists():
    """The exemption widens visibility, not the failure: no `sandbox_write` row is `NotFound`,
    and a production credential is never offered in its place."""
    with owner_sync_engine() as engine:
        _clear_sandbox_credentials(engine)
        _seed_credential(engine, label="only-prod", capability=TikTokCapability.PRODUCTION_READ)

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        with pytest.raises(NotFound):
            await resolve_sandbox_write_credential(session)


@requires_postgres
@pytest.mark.asyncio
async def test_sandbox_write_resolve_refuses_the_2026_08_18_row_from_credentials_alone():
    """The 2026-08-18 defect, caught on PostgreSQL with no pinned id: a `sandbox_write` row
    whose token resolves to the production shop (same shop cipher as the production row, here
    also the same merchant) is refused at resolve time, so a sandbox write can never be signed
    for a production merchant. Neither side is configured; both facts are in the rows."""
    cipher = f"ROW_{uuid.uuid4().hex[:16]}"
    merchant = _unique_merchant("shared")
    with owner_sync_engine() as engine:
        _clear_sandbox_credentials(engine)
        _seed_credential(
            engine,
            label="prod-real",
            merchant_id=merchant,
            cipher=cipher,
            capability=TikTokCapability.PRODUCTION_READ,
        )
        _seed_credential(
            engine,
            label="sandbox-mislabelled",
            merchant_id=merchant,
            cipher=cipher,
            capability=TikTokCapability.SANDBOX_WRITE,
        )

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        with pytest.raises(SandboxCredentialRefused):
            await resolve_sandbox_write_credential(session)
        # ...and the merchant the sandbox row carries is excluded from production reads.
        assert merchant in await sandbox_write_merchant_ids(session)


@requires_postgres
@pytest.mark.asyncio
async def test_a_shared_cipher_alone_also_refuses_the_sandbox_credential():
    """Distinctness by shop cipher even when the merchant ids differ (a token for the
    production shop filed under a different merchant label)."""
    cipher = f"ROW_{uuid.uuid4().hex[:16]}"
    with owner_sync_engine() as engine:
        _clear_sandbox_credentials(engine)
        _seed_credential(
            engine, label="prod-c", cipher=cipher, capability=TikTokCapability.SELLER_CONNECT
        )
        _seed_credential(
            engine, label="sandbox-c", cipher=cipher, capability=TikTokCapability.SANDBOX_WRITE
        )

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        with pytest.raises(SandboxCredentialRefused):
            await resolve_sandbox_write_credential(session)


@requires_postgres
@pytest.mark.asyncio
async def test_a_production_shop_holding_the_sandbox_merchant_cannot_read():
    """A read credential carrying a merchant id that a `sandbox_write` row carries is refused
    by the per-shop read resolver -- the identity-level belt the old constant gave, now from
    the DB."""
    sandbox_merchant = _unique_merchant("sbx")
    with owner_sync_engine() as engine:
        _clear_sandbox_credentials(engine)
        _seed_credential(
            engine,
            label="sbx",
            merchant_id=sandbox_merchant,
            capability=TikTokCapability.SANDBOX_WRITE,
        )
        shop_id, _ = _seed_credential(
            engine,
            label="mislabelled-read",
            merchant_id=sandbox_merchant,
            capability=TikTokCapability.SELLER_CONNECT,
        )

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        async with with_shop_scope(session, shop_id):
            with pytest.raises(NoReadCredentialForShop):
                await resolve_read_credential_for_shop(session, shop_id)


@requires_postgres
@pytest.mark.asyncio
async def test_resolve_read_credential_for_shop_is_not_self_scoped():
    """The third resolver must NOT get the same treatment, and this is why.

    `resolve_read_credential_for_shop` already RECEIVES the shop id. Wrapping
    it in a scope built from its own argument would mean the argument confers
    the authority to read itself -- ask for another shop's id and get that
    shop's credential back, tokens and all. That is privilege escalation, not
    a fix, and it is a worse outcome than #2019: #2019 returns nothing.

    Today the caller's scope decides, and RLS denies a shop the caller is not
    scoped to. #1995's consumer enters the scope itself. This test pins that
    property so a later reading of "apply the #2019 fix consistently to all
    three resolvers" fails here instead of shipping.
    """
    with owner_sync_engine() as engine:
        caller_shop, _caller_credential = _seed_credential(
            engine,
            label="selfscope-caller",
            merchant_id="8888888888888888888",
            capability=TikTokCapability.SELLER_CONNECT,
        )
        other_shop, _other_credential = _seed_credential(
            engine,
            label="selfscope-other",
            merchant_id="7777777777777777777",
            capability=TikTokCapability.SELLER_CONNECT,
        )

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        async with with_shop_scope(session, caller_shop):
            # Its own shop, under its own scope: allowed, and the control that
            # makes the refusal below mean something.
            own = await resolve_read_credential_for_shop(session, caller_shop)
            assert own.shop_id == caller_shop

            # Another shop's id, under the same scope: refused by RLS. If this
            # ever returns a credential, the resolver has become self-scoping
            # and hands out another tenant's tokens for the asking.
            with pytest.raises(NoReadCredentialForShop):
                await resolve_read_credential_for_shop(session, other_shop)
