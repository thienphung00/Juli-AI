"""RED->GREEN regression for #2019: the credential resolve runs outside any
shop scope, so RLS hides the credential it needs.

Since 05:28 UTC 2026-09-16 the `fujiwa-poll-cycle` beat entry (#1949) fails
every fifteen minutes with

    NotFound('No credentials for merchant 7658073774813611784 with
             capability production_read')

raised from `workers/services/polling/orchestrate.py::run_fujiwa_poll_cycle`.
The credential is present, `active`, and unexpired. What is absent is the
tenant GUC: `tiktok_credentials_select_public` carries qual
`(shop_id = app_current_shop_id())`, the worker connects as `juli_app`
(`rolbypassrls = f`), and `resolve_production_read_credential` queries before
any scope is entered -- it must, because the scope on the line below it needs
`credential.shop_id`, and the credential is what supplies it.

WHY EVERY EXISTING TEST PASSES. The unit suites bind to a SQLite fixture where
row-level security does not exist, so a scope-less read returns the row and the
defect is invisible. These tests therefore run against real Postgres, under the
real policies, as the real non-bypassing runtime role -- the session factory
from `tests.support.postgres`, the same reasoning as
`test_fujiwa_poll_cycle_scope_across_commits.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from juli_backend.core.security.credential_resolver import (
    resolve_production_read_credential,
)
from juli_backend.database.exceptions import NotFound
from juli_backend.database.tenant_context import system_scope
from juli_backend.integrations.tiktok import PRODUCTION_AUTH_ID, TikTokCapability
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)


def _seed_fujiwa_credential(engine, *, label: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed one shop and the Fujiwa production-read credential it owns.

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
                "merchant_id": PRODUCTION_AUTH_ID,
                "capability": TikTokCapability.PRODUCTION_READ.value,
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
@pytest.mark.xfail(
    strict=True,
    reason=(
        "#2019 OPEN: the resolve still runs outside any shop scope. The fix is "
        "NOT `system_scope` -- proved inert by "
        "`test_system_scope_confers_no_database_access` below and forbidden as a "
        "database-layer claim by ADR-089 decision 1. ADR-089 decisions 3-4 require a "
        "`SECURITY DEFINER` enumeration returning identifiers only, which is a "
        "migration (data-platform), not an integrations change. Marked strict so "
        "this turns RED the moment the real fix lands and the mark must be removed."
    ),
)
@pytest.mark.asyncio
async def test_production_read_resolve_finds_the_credential_without_a_prior_scope():
    """The resolve must find the credential it is pointed at, as `juli_app`,
    with no tenant context established -- because none *can* be established
    before it: the shop id the scope needs is the one this call returns.

    RED on the pre-fix code, with exactly the production symptom:

        juli_backend.database.exceptions.NotFound: No credentials for merchant
        7658073774813611784 with capability production_read

    Not a fixture error, and not a missing row -- the seeding above is
    owner-side and unconditional. The row is there; the transaction cannot
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
@pytest.mark.xfail(
    strict=True,
    reason=(
        "#2019 OPEN: the resolve still runs outside any shop scope. The fix is "
        "NOT `system_scope` -- proved inert by "
        "`test_system_scope_confers_no_database_access` below and forbidden as a "
        "database-layer claim by ADR-089 decision 1. ADR-089 decisions 3-4 require a "
        "`SECURITY DEFINER` enumeration returning identifiers only, which is a "
        "migration (data-platform), not an integrations change. Marked strict so "
        "this turns RED the moment the real fix lands and the mark must be removed."
    ),
)
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
@pytest.mark.xfail(
    strict=True,
    reason=(
        "#2019 OPEN: the resolve still runs outside any shop scope. The fix is "
        "NOT `system_scope` -- proved inert by "
        "`test_system_scope_confers_no_database_access` below and forbidden as a "
        "database-layer claim by ADR-089 decision 1. ADR-089 decisions 3-4 require a "
        "`SECURITY DEFINER` enumeration returning identifiers only, which is a "
        "migration (data-platform), not an integrations change. Marked strict so "
        "this turns RED the moment the real fix lands and the mark must be removed."
    ),
)
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
    `NotFound` -- and after the fix that answer means what it says, rather than
    being the ambiguous report of an RLS-hidden row that #2019 was.
    """
    with owner_sync_engine() as engine, engine.begin() as conn:
        conn.execute(
            text("DELETE FROM public.tiktok_credentials WHERE merchant_authorization_id = :m"),
            {"m": PRODUCTION_AUTH_ID},
        )

    async with juli_app_async_sessionmaker() as factory, factory() as session:
        with pytest.raises(NotFound):
            await resolve_production_read_credential(session)
