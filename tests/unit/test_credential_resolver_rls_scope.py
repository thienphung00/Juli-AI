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
(`rolbypassrls = f`), and `resolve_production_read_credential` queried before
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
    resolve_production_read_credential,
    resolve_read_credential_for_shop,
    resolve_sandbox_write_credential,
)
from juli_backend.database.exceptions import NotFound
from juli_backend.database.tenant_context import system_scope, with_shop_scope
from juli_backend.integrations.tiktok import (
    PRODUCTION_AUTH_ID,
    SANDBOX_AUTH_ID,
    TikTokCapability,
)
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)


def _seed_fujiwa_credential(
    engine,
    *,
    label: str,
    merchant_id: str = PRODUCTION_AUTH_ID,
    capability: TikTokCapability = TikTokCapability.PRODUCTION_READ,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed one shop and the configured-merchant credential it owns.

    Defaults to the Fujiwa production-read pair -- the one in the outage --
    and takes the pair as arguments so the sandbox-write twin, which carries
    the identical defect, is proved against the same fixture rather than a
    second near-copy of it that could drift.

    Seeded owner-side on purpose: set-up is not the thing under test, and
    seeding under RLS would make a fixture failure look like an isolation
    failure.

    Returns ``(shop_id, credential_id)``.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
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
                "cipher": "ROW_test_cipher",
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
async def test_production_read_resolve_finds_the_credential_without_a_prior_scope():
    """The resolve must find the credential it is pointed at, as `juli_app`,
    with no tenant context established -- because none *can* be established
    before it: the shop id the scope needs is the one this call returns.

    RED on the pre-fix code, with exactly the production symptom:

        juli_backend.database.exceptions.NotFound: No credentials for merchant
        7658073774813611784 with capability production_read

    Not a fixture error, and not a missing row -- the seeding above is
    owner-side and unconditional. The row was there; the transaction could not
    see it.
    """
    with owner_sync_engine() as engine:
        shop_id, credential_id = _seed_fujiwa_credential(engine, label="resolve-scope")

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        credential = await resolve_production_read_credential(session)

        assert credential.id == credential_id
        assert credential.shop_id == shop_id
        # The credential must arrive with real token material. A resolve that
        # returned an identifier-only stub would satisfy the lines above and
        # still leave the poll cycle unable to call TikTok.
        assert credential.access_token
        assert credential.capability == TikTokCapability.PRODUCTION_READ


@requires_postgres
@pytest.mark.asyncio
async def test_the_resolve_leaves_no_tenant_context_behind_it():
    """Whatever the resolve does to see across tenants, it must not leak a
    tenant context out to its caller.

    `run_fujiwa_poll_cycle` enters `with_sticky_shop_scope(credential.shop_id)`
    immediately afterwards and the rest of the cycle depends on that scope
    being the one thing in force. A resolve that left a GUC set behind it would
    make the enclosing scope a no-op that happens to agree -- and would agree
    with the wrong shop the moment a second credential exists.
    """
    with owner_sync_engine() as engine:
        _seed_fujiwa_credential(engine, label="resolve-noleak")

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        await resolve_production_read_credential(session)

        leaked = await session.execute(text("SELECT app_current_shop_id()"))
        assert leaked.scalar() is None


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
    with owner_sync_engine() as engine:
        _seed_fujiwa_credential(engine, label="resolve-sysscope")

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        async with system_scope(session, caller="test_2019"):
            result = await session.execute(
                text(
                    "SELECT count(*) FROM public.tiktok_credentials "
                    "WHERE merchant_authorization_id = :m"
                ),
                {"m": PRODUCTION_AUTH_ID},
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
async def test_resolve_does_not_cross_into_another_shops_credential():
    """The cross-tenant read the resolve needs must stay the narrowest one that
    answers the question -- the configured Fujiwa merchant, not "any row".

    Two shops each hold a credential; only one carries `PRODUCTION_AUTH_ID`.
    The resolve must return that one. Seeding the decoy first means a resolve
    that degraded to "first row wins" returns the wrong shop and fails here
    rather than passing by ordering luck.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    with owner_sync_engine() as engine:
        decoy_user = uuid.uuid4()
        decoy_shop = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO public.users (id, phone, created_at, updated_at) "
                    "VALUES (:id, :phone, :now, :now)"
                ),
                {"id": str(decoy_user), "phone": f"+1555{decoy_user.hex[:7]}", "now": now},
            )
            conn.execute(
                text(
                    "INSERT INTO public.shops "
                    "(id, user_id, shop_name, tiktok_shop_id, created_at, updated_at) "
                    "VALUES (:id, :user_id, 'decoy', :tt, :now, :now)"
                ),
                {
                    "id": str(decoy_shop),
                    "user_id": str(decoy_user),
                    "tt": f"tt-{decoy_shop.hex[:10]}",
                    "now": now,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO public.tiktok_credentials "
                    "(id, shop_id, merchant_authorization_id, capability, shop_cipher, "
                    " access_token, refresh_token, token_expires_at, status, "
                    " refresh_count, created_at, updated_at) "
                    "VALUES (:id, :shop_id, :merchant_id, :capability, 'ROW_decoy', "
                    " 'decoy-access', 'decoy-refresh', :expires, 'active', 0, :now, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "shop_id": str(decoy_shop),
                    "merchant_id": "9999999999999999999",
                    "capability": TikTokCapability.PRODUCTION_READ.value,
                    "expires": now + timedelta(days=30),
                    "now": now,
                },
            )

        fujiwa_shop, fujiwa_credential = _seed_fujiwa_credential(engine, label="resolve-decoy")

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        credential = await resolve_production_read_credential(session)

    assert credential.id == fujiwa_credential
    assert credential.shop_id == fujiwa_shop
    assert credential.merchant_authorization_id == PRODUCTION_AUTH_ID


@requires_postgres
@pytest.mark.asyncio
async def test_resolve_still_raises_not_found_when_the_credential_is_absent():
    """The exemption must widen visibility, not soften the failure.

    With no Fujiwa credential seeded at all, the resolve must still raise
    `NotFound` -- and now that answer means what it says, rather than being the
    ambiguous report of an RLS-hidden row that #2019 was.
    """
    with owner_sync_engine() as engine, engine.begin() as conn:
        conn.execute(
            text("DELETE FROM public.tiktok_credentials WHERE merchant_authorization_id = :m"),
            {"m": PRODUCTION_AUTH_ID},
        )

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        with pytest.raises(NotFound):
            await resolve_production_read_credential(session)


@requires_postgres
@pytest.mark.asyncio
async def test_sandbox_write_resolve_finds_the_credential_without_a_prior_scope():
    """`resolve_sandbox_write_credential` carries the identical defect.

    Same shape, line for line: a configured merchant id, no caller-supplied
    shop, and a policy keyed on the shop the caller does not yet know. It never
    showed up in an incident only because nothing calls it on a fifteen-minute
    cadence -- `services/execution/sandbox_guard.py` and
    `workers/services/polling/sync.py` reach it on demand.

    Fixed in the same commit and proved here rather than left for the next
    outage to find, because "the production twin is fixed" is not evidence
    about this one.
    """
    with owner_sync_engine() as engine, engine.begin() as conn:
        conn.execute(
            text("DELETE FROM public.tiktok_credentials WHERE merchant_authorization_id = :m"),
            {"m": SANDBOX_AUTH_ID},
        )
    with owner_sync_engine() as engine:
        shop_id, credential_id = _seed_fujiwa_credential(
            engine,
            label="sandbox-scope",
            merchant_id=SANDBOX_AUTH_ID,
            capability=TikTokCapability.SANDBOX_WRITE,
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
        caller_shop, _caller_credential = _seed_fujiwa_credential(
            engine,
            label="selfscope-caller",
            merchant_id="8888888888888888888",
            capability=TikTokCapability.SELLER_CONNECT,
        )
        other_shop, _other_credential = _seed_fujiwa_credential(
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
