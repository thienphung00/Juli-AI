"""A shop scope that survives the commits inside its own block (#1883).

`with_shop_scope` sets `app.current_shop_id` with `SET LOCAL`, which Postgres
discards at COMMIT. That is fine when the caller can name the commits and put
the GUC back afterwards (`reapply_shop_scope`, #1874/#1880). On the agent-run
worker path it is not: `JsonbConversationStore.persist` commits on every turn
and `ToolExecutionLedger` commits around every write, inside a loop that lives
in another module. `with_sticky_shop_scope` re-applies the same `SET LOCAL`
pair at the start of every transaction the session opens, for as long as the
block lasts.

EVERY TEST HERE RUNS ON REAL POSTGRES AS `juli_app`, WITH A REAL COMMIT.

Both halves of that sentence are load-bearing. As the table owner, RLS does not
apply at all and every assertion below would pass with or without the fix. And
`tests.integration.two_tenant.juli_app_session` binds its `AsyncSession` to an
already-open connection, so `session.commit()` releases a SAVEPOINT rather than
ending the transaction — `SET LOCAL` survives it, and the whole defect class
becomes invisible. `tests.support.postgres.juli_app_async_sessionmaker` gives
each session its own connection lifecycle from an engine, which is the
production shape and where `commit()` is a real COMMIT; see that module for why
the role is set in the startup packet rather than by a `SET ROLE` on `connect`,
which only holds for the first checkout.

The contrast against plain `with_shop_scope` in the first test is the RED
evidence, kept permanently: it fails on the second read, and it will keep
failing, so nobody can mistake a passing sticky test for a test of nothing.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import event, text

from juli_backend.database.tenant_context import (
    TenantContextRequiredError,
    with_shop_scope,
    with_sticky_shop_scope,
    with_sticky_shop_scope_sync,
)
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    juli_app_sync_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

# The one policy-gated read every test below uses. Migration 053's
# `shops_shop_scope_select (id = app_current_shop_id())` makes this return the
# caller's own shop under a shop scope and nothing at all without one — so the
# count is 1 exactly when tenancy is established, and 0 exactly when a commit
# has thrown it away.
_GATED_READ = text("SELECT count(*) FROM public.shops WHERE id = :shop_id")
_CURRENT_SHOP = text("SELECT app_current_shop_id()")


@pytest.fixture
def owner_engine():
    """A sync engine as the table owner, for seeding only.

    `tests/conftest.py`'s `_shared_database_at_head` has already put the shared
    database at head, so this only needs to connect.
    """
    with owner_sync_engine() as engine:
        yield engine


@pytest.fixture
def app_sync_sessionmaker():
    """The sync `sessionmaker` the ledger-flavoured tests run on, as `juli_app`."""
    with juli_app_sync_sessionmaker() as maker:
        yield maker


def _seed_shop(engine, *, label: str) -> uuid.UUID:
    """One user + one shop. Nothing else: `shops` is the policy-gated row every
    assertion below reads, and a smaller fixture is a clearer one."""
    now = datetime.now(UTC)
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()

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
                "VALUES (:id, :user_id, :name, :tiktok_id, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "user_id": str(user_id),
                "name": f"{label} shop",
                "tiktok_id": f"tt-{shop_id.hex[:10]}",
                "now": now,
            },
        )
    return shop_id


async def _visible_shop_rows(session, shop_id: uuid.UUID) -> int:
    result = await session.execute(_GATED_READ, {"shop_id": str(shop_id)})
    return int(result.scalar_one())


def _visible_shop_rows_sync(session, shop_id: uuid.UUID) -> int:
    return int(session.execute(_GATED_READ, {"shop_id": str(shop_id)}).scalar_one())


@asynccontextmanager
async def _read_after_each_commit(scope, session, shop_id: uuid.UUID, seen: list[int]):
    """Read the gated row, then commit and read again, three times over.

    Shared by the sticky case and the plain-`with_shop_scope` contrast so the
    two differ in exactly one thing: which scope is open around them.
    """
    async with scope:
        seen.append(await _visible_shop_rows(session, shop_id))
        await session.commit()
        seen.append(await _visible_shop_rows(session, shop_id))
        await session.commit()
        seen.append(await _visible_shop_rows(session, shop_id))
        await session.commit()
        seen.append(await _visible_shop_rows(session, shop_id))
        yield


# ---------------------------------------------------------------------------
# AC1 — the GUC survives every commit in the block.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.asyncio
async def test_the_guc_survives_every_commit_in_the_block(owner_engine):
    """Three commits inside the block, a policy-gated read after each, all four
    reads resolve — and the same sequence under plain `with_shop_scope`
    resolves only the first.

    The second half is the RED evidence for this whole issue, kept as a
    permanent contrast rather than a note in a commit message.
    """
    shop_id = _seed_shop(owner_engine, label="sticky-commits")

    sticky_reads: list[int] = []
    plain_reads: list[int] = []

    async with juli_app_async_sessionmaker() as factory:
        async with factory() as session:
            async with _read_after_each_commit(
                with_sticky_shop_scope(session, shop_id), session, shop_id, sticky_reads
            ):
                pass

        async with factory() as session:
            async with _read_after_each_commit(
                with_shop_scope(session, shop_id), session, shop_id, plain_reads
            ):
                pass

    assert sticky_reads == [1, 1, 1, 1], (
        f"the sticky scope must hold across every commit in its block; reads were "
        f"{sticky_reads} (1 = the shop's own row is visible, 0 = RLS sees no tenant)"
    )
    assert plain_reads == [1, 0, 0, 0], (
        f"plain with_shop_scope is SET LOCAL and must lose the GUC at the first commit; "
        f"reads were {plain_reads} — if this ever becomes [1, 1, 1, 1] the sticky test "
        f"above has stopped proving anything"
    )


# ---------------------------------------------------------------------------
# AC2 — exit removes the listener and restores the prior GUC.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.asyncio
async def test_exit_removes_the_listener_and_restores_the_prior_guc(owner_engine):
    """Both exits: the normal one and the one taken by an exception.

    The listener is what makes the scope sticky, so a listener left attached is
    a shop id that keeps re-asserting itself after the block that chose it has
    ended — the exact leak `SET LOCAL` exists to prevent.
    """
    shop_id = _seed_shop(owner_engine, label="sticky-exit")

    async with juli_app_async_sessionmaker() as factory:
        async with factory() as session:
            sync_session = session.sync_session
            before = (await session.execute(_CURRENT_SHOP)).scalar()
            assert before is None, f"the fixture must start with no shop context, read {before!r}"
            assert len(sync_session.dispatch.after_begin) == 0, (
                "nothing may be listening on after_begin before the scope opens"
            )

            async with with_sticky_shop_scope(session, shop_id):
                inside = list(sync_session.dispatch.after_begin)
            assert len(inside) == 1, (
                f"exactly one after_begin listener must be bound inside the scope, "
                f"found {len(inside)}"
            )
            assert event.contains(sync_session, "after_begin", inside[0]) is False, (
                "the listener must be removed on the normal exit path"
            )
            assert (await session.execute(_CURRENT_SHOP)).scalar() == before, (
                "the prior GUC must be restored on the normal exit path"
            )

        async with factory() as session:
            sync_session = session.sync_session
            before = (await session.execute(_CURRENT_SHOP)).scalar()
            boom = RuntimeError("the body raised")
            captured: list[Any] = []
            try:
                async with with_sticky_shop_scope(session, shop_id):
                    captured.extend(sync_session.dispatch.after_begin)
                    raise boom
            except RuntimeError as exc:
                assert exc is boom, "the scope must not replace the caller's exception"

            assert len(captured) == 1, (
                f"exactly one after_begin listener must be bound inside the scope, "
                f"found {len(captured)}"
            )
            assert event.contains(sync_session, "after_begin", captured[0]) is False, (
                "the listener must be removed on the exception path too"
            )
            await session.rollback()
            assert (await session.execute(_CURRENT_SHOP)).scalar() == before, (
                "after the exception path the session must carry no shop context"
            )


@requires_postgres
@pytest.mark.asyncio
async def test_a_sticky_scope_with_no_shop_is_refused_before_any_sql():
    """`system_scope` exists for work with no tenant; a shop scope without a
    shop is neither, and must not reach the database at all."""
    async with juli_app_async_sessionmaker() as factory:
        async with factory() as session:
            raised: list[TenantContextRequiredError] = []
            try:
                async with with_sticky_shop_scope(session, None):
                    pass
            except TenantContextRequiredError as exc:
                raised.append(exc)

            assert len(raised) == 1, "a sticky scope with no shop id must be refused"
            assert len(session.sync_session.dispatch.after_begin) == 0, (
                "the refusal must happen before a listener is ever bound"
            )


# ---------------------------------------------------------------------------
# AC3 — the scope never leaks through the connection pool.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.asyncio
async def test_the_scope_never_leaks_through_the_connection_pool(owner_engine):
    """`SET LOCAL` only, never a session-level or connection-level `SET`.

    A fresh session on the same engine — very likely the same pooled physical
    connection — must read no shop id at all. If the sticky scope had reached
    for `SET` instead of `set_config(..., true)`, one tenant's id would ride a
    recycled connection into the next checkout, which is a cross-tenant read
    waiting to happen.
    """
    shop_id = _seed_shop(owner_engine, label="sticky-pool")

    async with juli_app_async_sessionmaker() as factory:
        async with factory() as session:
            async with with_sticky_shop_scope(session, shop_id):
                await session.commit()
                assert await _visible_shop_rows(session, shop_id) == 1, (
                    "precondition: the scope is genuinely established"
                )

        async with factory() as fresh_session:
            leaked = (await fresh_session.execute(_CURRENT_SHOP)).scalar()
            assert leaked is None, (
                f"a pooled connection carried app.current_shop_id={leaked!r} into the next "
                f"checkout; the scope must be transaction-local"
            )
            assert await _visible_shop_rows(fresh_session, shop_id) == 0, (
                "an unscoped session must see no shop row at all"
            )


# ---------------------------------------------------------------------------
# The sync twin — the ledger path is sync and commits four times per write.
# ---------------------------------------------------------------------------


@requires_postgres
def test_the_sync_guc_survives_every_commit_in_the_block(owner_engine, app_sync_sessionmaker):
    """AC1 for `with_sticky_shop_scope_sync`, on a real `sqlalchemy.orm.Session`.

    `ToolExecutionLedger` commits in `_claim`, `_mark_succeeded`,
    `_mark_succeeded_retroactive` and `_mark_failed` while writing the
    RLS-gated `tool_executions` — so without this flavour the async fix would
    leave every ledger row unscoped and the run would still fail, one layer
    down.
    """
    shop_id = _seed_shop(owner_engine, label="sticky-sync-commits")

    sticky_reads: list[int] = []
    with app_sync_sessionmaker() as session:
        with with_sticky_shop_scope_sync(session, shop_id):
            sticky_reads.append(_visible_shop_rows_sync(session, shop_id))
            session.commit()
            sticky_reads.append(_visible_shop_rows_sync(session, shop_id))
            session.commit()
            sticky_reads.append(_visible_shop_rows_sync(session, shop_id))
            session.commit()
            sticky_reads.append(_visible_shop_rows_sync(session, shop_id))

    assert sticky_reads == [1, 1, 1, 1], (
        f"the sync sticky scope must hold across every commit in its block; reads were "
        f"{sticky_reads}"
    )


@requires_postgres
def test_the_sync_scope_never_leaks_through_the_connection_pool(
    owner_engine, app_sync_sessionmaker
):
    """AC3 for the sync flavour: the ledger's throwaway Session must not hand a
    shop id to whatever checks the connection out next."""
    shop_id = _seed_shop(owner_engine, label="sticky-sync-pool")

    with app_sync_sessionmaker() as session:
        with with_sticky_shop_scope_sync(session, shop_id):
            session.commit()
            assert _visible_shop_rows_sync(session, shop_id) == 1, (
                "precondition: the sync scope is genuinely established"
            )

    with app_sync_sessionmaker() as fresh_session:
        leaked = fresh_session.execute(_CURRENT_SHOP).scalar()
        assert leaked is None, (
            f"a pooled connection carried app.current_shop_id={leaked!r} into the next checkout"
        )
