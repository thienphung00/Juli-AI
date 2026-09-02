"""The GUC a scope sets does not outlive the scope (#1495, ADR-089).

`with_shop_scope` set `app.current_shop_id` with SET LOCAL and, on exit, reset
only a Python flag. SET LOCAL clears at transaction end — which in a per-item
loop is nowhere near the end of the item. Every W7-bis slice is such a loop,
over items belonging to DIFFERENT tenants, so a query issued between scopes ran
under whichever tenant happened to be last and still returned rows.

These tests assert the observable rather than the parameter: between two
scopes, a read of a tenant-scoped table returns ZERO rows. A test that only
checked `current_setting` would pass against an implementation that set the
GUC to a value RLS still accepted.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import with_shop_scope, with_tenant_scope
from tests.integration.two_tenant import juli_app_session, seed_tenant

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

_COUNT_RUNS = text("SELECT count(*) FROM public.workflow_runs")
_SHOP_GUC = text("SELECT current_setting('app.current_shop_id', true)")


@pytest.mark.asyncio
async def test_a_read_between_two_scopes_sees_nothing(owner_engine):
    """AC1 + AC2: the leak is gone, measured by rows rather than by parameter.

    Before the fix this returned tenant A's rows — not zero — which is why the
    defect was invisible: the query succeeded and the data looked plausible.
    """
    tenant_a = seed_tenant(owner_engine, label="leak_a")
    seed_tenant(owner_engine, label="leak_b")

    async with juli_app_session() as session:
        async with with_shop_scope(session, tenant_a.shop_id):
            inside = (await session.execute(_COUNT_RUNS)).scalar()

        # Same session, same transaction, immediately after the block.
        between = (await session.execute(_COUNT_RUNS)).scalar()
        guc = (await session.execute(_SHOP_GUC)).scalar()

    assert inside > 0, "the scope must be able to read its own tenant's rows"
    assert between == 0, (
        f"a read outside every scope returned {between} rows — the previous tenant's "
        "context outlived the block that set it"
    )
    assert guc in (None, ""), f"app.current_shop_id still names a shop after exit: {guc!r}"


@pytest.mark.asyncio
async def test_consecutive_scopes_do_not_bleed_into_each_other(owner_engine):
    """The per-item loop shape every W7-bis slice uses.

    Each iteration must see exactly its own tenant, and the count must not grow
    as the loop proceeds — growth would mean context accumulating rather than
    being replaced.
    """
    tenant_a = seed_tenant(owner_engine, label="loop_a")
    tenant_b = seed_tenant(owner_engine, label="loop_b")

    seen: dict[str, set[str]] = {}
    between_iterations: list[int] = []
    async with juli_app_session() as session:
        for label, tenant in (("a", tenant_a), ("b", tenant_b), ("a_again", tenant_a)):
            async with with_shop_scope(session, tenant.shop_id):
                rows = (
                    await session.execute(text("SELECT DISTINCT shop_id FROM public.workflow_runs"))
                ).all()
            seen[label] = {str(r[0]) for r in rows}
            # The gap between items is where the defect lived. Reading only
            # INSIDE each scope cannot see it: entry overwrites the GUC, so
            # consecutive scopes look correct even when nothing is released.
            between_iterations.append((await session.execute(_COUNT_RUNS)).scalar())

    assert seen["a"] == {str(tenant_a.shop_id)}
    assert seen["b"] == {str(tenant_b.shop_id)}, (
        f"iteration 2 saw {seen['b']} — it inherited iteration 1's tenant"
    )
    assert seen["a_again"] == {str(tenant_a.shop_id)}
    assert between_iterations == [0, 0, 0], (
        f"rows were readable between loop iterations: {between_iterations}. A helper "
        "hoisted out of the block — or a retry, or a log line that touches the DB — "
        "would run under the previous item's tenant."
    )


@pytest.mark.asyncio
async def test_nesting_restores_the_outer_scope(owner_engine):
    """AC3: exiting an inner scope restores the outer one, not 'no context'.

    This is why the fix saves and restores rather than clearing. A clear-on-exit
    implementation passes every other test in this module and fails here.
    """
    tenant_a = seed_tenant(owner_engine, label="nest_a")
    tenant_b = seed_tenant(owner_engine, label="nest_b")

    async with juli_app_session() as session:
        async with with_shop_scope(session, tenant_a.shop_id):
            async with with_shop_scope(session, tenant_b.shop_id):
                inner = (
                    await session.execute(text("SELECT DISTINCT shop_id FROM public.workflow_runs"))
                ).all()
            after_inner = (
                await session.execute(text("SELECT DISTINCT shop_id FROM public.workflow_runs"))
            ).all()

    assert {str(r[0]) for r in inner} == {str(tenant_b.shop_id)}
    assert {str(r[0]) for r in after_inner} == {str(tenant_a.shop_id)}, (
        "leaving the inner scope must restore the outer tenant, not clear context"
    )


@pytest.mark.asyncio
async def test_the_scope_is_left_even_when_the_body_raises(owner_engine):
    """AC5: the exit path runs on the exception path too.

    A leak that only happens when something went wrong is the worse version:
    the handler that runs next is exactly the code least likely to set its own
    context.
    """
    tenant_a = seed_tenant(owner_engine, label="raise_a")

    class Boom(RuntimeError):
        pass

    async with juli_app_session() as session:
        with pytest.raises(Boom):
            async with with_shop_scope(session, tenant_a.shop_id):
                await session.execute(_COUNT_RUNS)
                raise Boom("body failed")

        # The body's exception must reach the caller unchanged, and the GUC
        # must not survive it. The transaction is still usable here because
        # Boom is a Python error, not a database one.
        guc = (await session.execute(_SHOP_GUC)).scalar()

    assert guc in (None, ""), f"context survived a raising body: {guc!r}"


@pytest.mark.asyncio
async def test_with_tenant_scope_has_the_same_guarantee(owner_engine):
    """AC4: the sibling scope had the identical no-op `finally`.

    `system_scope` is deliberately excluded — it sets no GUC at all, only a
    Python flag, so it has nothing to leak.
    """
    tenant_a = seed_tenant(owner_engine, label="tenant_scope_a")

    async with juli_app_session() as session:
        async with with_tenant_scope(session, tenant_a.shop_id, tenant_a.user_id):
            inside = (await session.execute(_COUNT_RUNS)).scalar()
        between = (await session.execute(_COUNT_RUNS)).scalar()
        user_guc = (
            await session.execute(text("SELECT current_setting('app.current_user_id', true)"))
        ).scalar()

    assert inside > 0
    assert between == 0, f"with_tenant_scope leaked: {between} rows readable after exit"
    assert user_guc in (None, ""), f"user context survived exit: {user_guc!r}"


@pytest.mark.asyncio
async def test_shop_scope_withholds_the_user_guc_even_when_one_was_set(owner_engine):
    """`with_shop_scope` promises user-keyed policies deny inside it.

    That promise held only while nothing had set the user GUC earlier in the
    transaction. Nested inside `with_tenant_scope` it was inherited, and the
    docstring was quietly false.
    """
    tenant_a = seed_tenant(owner_engine, label="withhold_a")

    async with juli_app_session() as session:
        async with with_tenant_scope(session, tenant_a.shop_id, tenant_a.user_id):
            outer_user = (
                await session.execute(text("SELECT current_setting('app.current_user_id', true)"))
            ).scalar()
            async with with_shop_scope(session, tenant_a.shop_id):
                inner_user = (
                    await session.execute(
                        text("SELECT current_setting('app.current_user_id', true)")
                    )
                ).scalar()

    assert outer_user == str(tenant_a.user_id)
    assert inner_user in (None, ""), (
        f"with_shop_scope inherited a user id it promises to withhold: {inner_user!r}"
    )
