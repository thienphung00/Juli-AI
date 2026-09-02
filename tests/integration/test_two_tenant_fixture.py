"""The two-tenant fixture proves isolation, not emptiness (#1483 / ADR-089).

A fixture that hands back a session which can read nothing would pass every denial assertion in
this file's neighbourhood and be worthless for W7-bis, whose entire subject is a task that
completes having read nothing. So each denial here is paired with the positive control that
makes it meaningful: the same session, the same query, the other tenant's context.

This module also closes the two acceptance criteria #1478 deferred for want of a Postgres
fixture — that a shop-scoped session can reach its own shop's rows, and cannot reach `users` or
`shops` at all.

It is in `_ISOLATED_DATABASE_MODULES` because it seeds. `test_rls_policies.py` was isolated for
asserting unscoped global counts (#1425); rows seeded here would corrupt that class of assertion
from any module sharing the database.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import column, func, select, table, text

from tests.integration.two_tenant import (
    ACTIVE_RUNS_PER_TENANT,
    RUNTIME_ROLE,
    SEEDED_TABLES,
    juli_app_session,
)

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


@pytest.mark.asyncio
async def test_the_session_really_runs_as_the_runtime_role(two_tenants) -> None:
    """Guard the guard.

    If `SET ROLE` silently failed, or the session checked out a different
    connection from the pool, every isolation assertion below would run as the
    table owner — which is exempt from RLS — and pass while proving nothing.
    That is the most likely way this fixture goes quietly wrong, so it is
    checked first.
    """
    tenant_a, _tenant_b = two_tenants

    async with juli_app_session(tenant_a.shop_id) as session:
        current = (await session.execute(text("SELECT current_user"))).scalar()

    assert current == RUNTIME_ROLE, (
        f"the session is running as {current!r}, not {RUNTIME_ROLE!r}. Every isolation claim "
        "in this module would be evaluated against the table owner, which Postgres exempts "
        "from row policies, and would pass without meaning anything."
    )


@pytest.mark.asyncio
async def test_a_shop_scoped_session_reads_its_own_rows(two_tenants) -> None:
    """The positive control, asserted before any denial.

    Without it, "zero rows" is ambiguous between isolation working and the role
    being able to read nothing — and the second is exactly the W7-bis failure.
    """
    tenant_a, _tenant_b = two_tenants

    async with juli_app_session(tenant_a.shop_id) as session:
        runs = (
            await session.execute(
                text("SELECT count(*) FROM public.workflow_runs WHERE shop_id = :s"),
                {"s": str(tenant_a.shop_id)},
            )
        ).scalar()
        credentials = (
            await session.execute(
                text("SELECT count(*) FROM public.tiktok_credentials WHERE shop_id = :s"),
                {"s": str(tenant_a.shop_id)},
            )
        ).scalar()

    assert runs == ACTIVE_RUNS_PER_TENANT, (
        f"expected tenant A's {ACTIVE_RUNS_PER_TENANT} seeded runs, got {runs}"
    )
    assert credentials == 2, f"expected tenant A's two seeded credentials, got {credentials}"


@pytest.mark.asyncio
async def test_a_shop_scoped_session_reads_none_of_the_other_tenant(two_tenants) -> None:
    """The denial, on the same fixture the positive control just passed on."""
    tenant_a, tenant_b = two_tenants

    async with juli_app_session(tenant_a.shop_id) as session:
        leaked_runs = (
            await session.execute(
                text("SELECT count(*) FROM public.workflow_runs WHERE shop_id = :s"),
                {"s": str(tenant_b.shop_id)},
            )
        ).scalar()
        leaked_credentials = (
            await session.execute(
                text("SELECT count(*) FROM public.tiktok_credentials WHERE shop_id = :s"),
                {"s": str(tenant_b.shop_id)},
            )
        ).scalar()
        # The unfiltered read matters as much as the targeted one: a policy that
        # scopes an explicit WHERE but not a bare SELECT would pass above.
        all_visible_runs = (
            await session.execute(text("SELECT count(*) FROM public.workflow_runs"))
        ).scalar()

    assert leaked_runs == 0, f"tenant A saw {leaked_runs} of tenant B's runs"
    assert leaked_credentials == 0, f"tenant A saw {leaked_credentials} of tenant B's credentials"
    assert all_visible_runs == ACTIVE_RUNS_PER_TENANT, (
        f"an unfiltered SELECT returned {all_visible_runs} runs; tenant A seeded "
        f"{ACTIVE_RUNS_PER_TENANT}, so the "
        "policy is not scoping reads that do not name a shop"
    )


@pytest.mark.asyncio
async def test_switching_the_context_switches_what_is_visible(two_tenants) -> None:
    """Isolation follows the context, not the connection.

    A fixture that pinned visibility at connect time would pass both tests above
    and be useless for a per-item loop, which is the shape every remaining
    W7-bis slice uses.
    """
    tenant_a, tenant_b = two_tenants

    async with juli_app_session(tenant_a.shop_id) as session:
        seen_by_a = (
            await session.execute(text("SELECT count(*) FROM public.workflow_runs"))
        ).scalar()
    async with juli_app_session(tenant_b.shop_id) as session:
        seen_by_b = (
            await session.execute(text("SELECT count(*) FROM public.workflow_runs"))
        ).scalar()

    assert seen_by_a == ACTIVE_RUNS_PER_TENANT and seen_by_b == ACTIVE_RUNS_PER_TENANT, (
        f"each tenant should see its own {ACTIVE_RUNS_PER_TENANT} runs; "
        f"got A={seen_by_a} B={seen_by_b}"
    )


@pytest.mark.asyncio
async def test_a_shop_scoped_session_cannot_reach_users_or_shops(two_tenants) -> None:
    """#1478 AC4, deferred until this fixture existed.

    `with_shop_scope` withholds `app.current_user_id` so user-keyed policies
    deny. This is that denial observed in Postgres rather than inferred from
    which GUCs the seam emits.
    """
    tenant_a, _tenant_b = two_tenants

    async with juli_app_session(tenant_a.shop_id) as session:
        users = (await session.execute(text("SELECT count(*) FROM public.users"))).scalar()
        shops = (await session.execute(text("SELECT count(*) FROM public.shops"))).scalar()

    assert users == 0, (
        f"a shop-scoped session read {users} rows from public.users. It withholds "
        "app.current_user_id precisely so that table denies; a non-zero count means either "
        "the user GUC leaked in or the policy is not keyed to it (#1478)."
    )
    assert shops == 0, f"a shop-scoped session read {shops} rows from public.shops"


@pytest.mark.asyncio
async def test_no_context_reads_nothing_rather_than_raising(two_tenants) -> None:
    """The state a pooled connection is left in between transactions.

    Before #1467 this raised `invalid input syntax for type uuid` on the empty
    string. It must now be a clean denial, and this is the fixture-level
    regression test for that.
    """
    async with juli_app_session(shop_id=None) as session:
        runs = (await session.execute(text("SELECT count(*) FROM public.workflow_runs"))).scalar()

    assert runs == 0, f"with no tenant context the session read {runs} rows; expected a denial"


def test_the_seeder_covers_every_table_it_claims(owner_engine, two_tenants) -> None:
    """Coverage asserted against the database, not stated in a docstring.

    The helper this fixture extends — `_seed_tenant_data` in #1329's proof —
    documents itself as seeding "across all tenant-scoped tables" and seeds
    three. A list that is checked cannot drift from the rows that exist.
    """
    tenant_a, _tenant_b = two_tenants
    scoped_by = {"users": "id", "shops": "user_id"}

    missing = []
    with owner_engine.connect() as conn:
        for name in SEEDED_TABLES:
            key = scoped_by.get(name, "shop_id")
            value = tenant_a.user_id if name in scoped_by else tenant_a.shop_id
            # Core constructs rather than an f-string. The table name varies, so
            # raw SQL here would need a suppression to excuse the interpolation;
            # table()/column() quote the identifier and keep the value bound.
            target = table(name, column(key), schema="public")
            count = conn.execute(
                select(func.count()).select_from(target).where(column(key) == str(value))
            ).scalar()
            if not count:
                missing.append(name)

    assert not missing, (
        f"SEEDED_TABLES names these but no row exists for the seeded tenant: {missing}. "
        "The list is the fixture's contract with the slices that consume it."
    )
