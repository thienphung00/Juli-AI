"""P29: the round-trip shortcuts keep tenant isolation exactly where it was.

Three new shapes, each asserted by ROWS (what RLS lets through) rather than by
parameter, the same standard as ``test_shop_scope_guc_lifecycle.py``:

- ``sequential_shop_scopes``: one scope moving shop to shop sees exactly the
  shop just entered, and the prior pair is back after the block;
- ``find_shop_entering_seller_scope``: the listing read and the seller's scope
  in one statement -- the scope is THAT shop's owner's, and an unknown shop
  sets nothing (the role is still ``juli_ops`` until ``leave_ops_role``);
- ``transaction_ends_after``: skipping a restore is only ever followed by the
  transaction's end, which discards the scope (a fresh transaction sees none).
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import sequential_shop_scopes, with_shop_scope
from juli_backend.services.ops import overview
from juli_backend.services.ops.access import ops_role
from tests.integration.two_tenant import juli_app_session, seed_tenant
from tests.support.postgres import juli_app_async_sessionmaker

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

_RUN_SHOPS = text("SELECT DISTINCT shop_id FROM public.workflow_runs")
_GUCS = text(
    "SELECT current_setting('app.current_shop_id', true), "
    "current_setting('app.current_user_id', true), current_user"
)


async def _visible_shops(session) -> set[uuid.UUID]:
    return {row[0] for row in (await session.execute(_RUN_SHOPS)).all()}


async def test_sequential_scopes_see_one_shop_at_a_time_and_restore(owner_engine):
    a = seed_tenant(owner_engine, label="p29_seq_a")
    b = seed_tenant(owner_engine, label="p29_seq_b")
    async with juli_app_session() as session:
        before = (await session.execute(_GUCS)).one()
        async with sequential_shop_scopes(session) as scopes:
            await scopes.enter(a.shop_id)
            seen_a = await _visible_shops(session)
            await scopes.enter(b.shop_id)
            seen_b = await _visible_shops(session)
            guc_b = (await session.execute(_GUCS)).one()
        after_rows = await _visible_shops(session)
        after = (await session.execute(_GUCS)).one()
    assert seen_a == {a.shop_id}
    assert seen_b == {b.shop_id}
    assert guc_b[0] == str(b.shop_id) and guc_b[1] == "", guc_b  # user GUC withheld
    assert after_rows == set()
    assert (after[0] or "", after[1] or "") == (before[0] or "", before[1] or "")


async def test_ending_the_transaction_discards_an_unrestored_scope(owner_engine):
    a = seed_tenant(owner_engine, label="p29_end_a")
    seed_tenant(owner_engine, label="p29_end_b")
    # The role rides in the startup packet here, so the ROLLBACK below cannot
    # undo it (``juli_app_session``'s SET ROLE would be) -- see postgres.py.
    async with juli_app_async_sessionmaker() as factory, factory() as session:
        async with with_shop_scope(session, a.shop_id, transaction_ends_after=True):
            inside = await _visible_shops(session)
        await session.rollback()  # what the request's session close does
        after = await _visible_shops(session)
        gucs = (await session.execute(_GUCS)).one()
    assert inside == {a.shop_id}
    assert after == set(), "a skipped restore must never outlive its transaction"
    assert (gucs[0] or "") == ""


async def test_find_shop_entering_seller_scope_is_that_shops_owner(owner_engine):
    a = seed_tenant(owner_engine, label="p29_view_a")
    b = seed_tenant(owner_engine, label="p29_view_b")
    async with juli_app_session() as session:
        async with ops_role(session) as block:
            previous = block.hand_over()
            assert previous is not None
            listing = await overview.find_shop_entering_seller_scope(
                session, b.shop_id, restore_role=previous
            )
        gucs = (await session.execute(_GUCS)).one()
        visible = await _visible_shops(session)
        await session.rollback()
    assert listing is not None and listing.shop_id == b.shop_id
    assert listing.owner_user_id == b.user_id
    assert gucs[0] == str(b.shop_id) and gucs[1] == str(b.user_id)
    assert gucs[2] == previous  # back to the runtime role in the same statement
    assert visible == {b.shop_id}
    assert a.shop_id not in visible


async def test_unknown_shop_sets_nothing_and_leave_restores_the_role(owner_engine):
    seed_tenant(owner_engine, label="p29_404")
    async with juli_app_session() as session:
        async with ops_role(session) as block:
            previous = block.hand_over()
            listing = await overview.find_shop_entering_seller_scope(
                session, uuid.uuid4(), restore_role=previous
            )
            still = (await session.execute(_GUCS)).one()
            await overview.leave_ops_role(session, previous)
        after = (await session.execute(_GUCS)).one()
        visible = await _visible_shops(session)
        await session.rollback()
    assert listing is None
    assert (still[0] or "") == "" and still[2] == "juli_ops"
    assert after[2] == previous
    assert visible == set()


async def test_find_shop_and_settings_is_one_shop(owner_engine):
    a = seed_tenant(owner_engine, label="p29_fs_a")
    seed_tenant(owner_engine, label="p29_fs_b")
    async with juli_app_session() as session:
        listing, row = await overview.find_shop_and_settings(session, a.shop_id)
        missing, none_row = await overview.find_shop_and_settings(session, uuid.uuid4())
        await session.rollback()
    assert listing is not None and listing.shop_id == a.shop_id
    assert listing.owner_user_id == a.user_id
    assert row is None or row.shop_id == a.shop_id
    assert missing is None and none_row is None
