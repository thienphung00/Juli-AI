"""P101 W1 businesses on real Postgres (migration 130_businesses + its deferred backfill).

- the BEFORE INSERT trigger gives a shop inserted with no business its own, owned by ``user_id``;
- ``juli_app`` reads only its own member rows, never writes the tables, never reads the invites;
- the ``shops`` policies admit a business member to every shop of the business, a removed member
  to none, a stranger to none; ``shops.user_id`` alone admits nothing once a business exists;
- the deferred backfill maps each pre-130 shop to its own business (owner + active members,
  removed people left out, the sandbox shop ``kind = 'sandbox'``), is idempotent, and sets
  ``business_id`` NOT NULL; downgrade of 130 restores 121's policies (alembic, run separately).
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import with_user_scope
from juli_backend.models.models import User
from juli_backend.repositories.identity import ShopsRepo
from juli_backend.services import businesses
from tests.integration.test_ops_console_db import app_session
from tests.integration.two_tenant import seed_tenant

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
        reason="DATABASE_URL is not set to a Postgres instance",
    ),
    pytest.mark.migration_heavy,
]

BACKFILL = (
    Path(__file__).resolve().parents[2]
    / "backend/src/juli_backend/database/migrations/deferred/130_businesses_backfill.py"
)


def _tenant(engine, label: str):
    return seed_tenant(engine, label=f"{label}-{uuid.uuid4().hex[:6]}")


def _business_of(engine, shop_id) -> uuid.UUID | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT business_id FROM public.shops WHERE id = :s"), {"s": shop_id}
        ).scalar_one()


def _members(engine, business_id):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT user_id, role, added_via, removed_at FROM public.business_members "
                "WHERE business_id = :b ORDER BY added_at, id"
            ),
            {"b": business_id},
        ).all()


async def _visible(user_id) -> set[uuid.UUID]:
    async with app_session() as session:
        return {s.id for s in await ShopsRepo(session).list_for_authorization(user_id)}


async def _raw(user_id) -> set[uuid.UUID]:
    async with app_session() as session:
        async with with_user_scope(session, user_id):
            return {r[0] for r in (await session.execute(text("SELECT id FROM public.shops")))}


def test_trigger_gives_a_new_shop_its_own_business_owned_by_its_user(owner_engine):
    tenant = _tenant(owner_engine, "trig")
    business_id = _business_of(owner_engine, tenant.shop_id)
    assert business_id is not None
    rows = _members(owner_engine, business_id)
    assert [(r.user_id, r.role, r.added_via, r.removed_at) for r in rows] == [
        (tenant.user_id, "owner", "owner", None)
    ]
    with owner_engine.connect() as conn:
        name, kind = conn.execute(
            text(
                "SELECT b.name, s.kind FROM public.shops s JOIN public.businesses b "
                "ON b.id = s.business_id WHERE s.id = :s"
            ),
            {"s": tenant.shop_id},
        ).one()
    assert kind == "real" and name


def test_juli_app_reads_own_rows_only_and_cannot_write(owner_engine):
    a, b = _tenant(owner_engine, "a"), _tenant(owner_engine, "b")

    async def run():
        async with app_session() as session:
            async with with_user_scope(session, a.user_id):
                mine = (
                    await session.execute(text("SELECT user_id FROM public.business_members"))
                ).all()
                names = (await session.execute(text("SELECT id FROM public.businesses"))).all()
            assert {r[0] for r in mine} == {a.user_id}
            assert {r[0] for r in names} == {_business_of(owner_engine, a.shop_id)}
        for statement in (
            "INSERT INTO public.businesses (id, name) VALUES (gen_random_uuid(), 'x')",
            f"UPDATE public.business_members SET removed_at = now() WHERE user_id = '{b.user_id}'",
            "DELETE FROM public.business_members",
            "SELECT 1 FROM public.business_invites",
        ):
            async with app_session() as session:
                with pytest.raises(Exception, match="permission denied"):
                    await session.execute(text(statement))

    asyncio.run(run())


async def test_a_member_opens_every_shop_and_a_removed_one_none(owner_engine):
    owner = _tenant(owner_engine, "owner")
    business_id = _business_of(owner_engine, owner.shop_id)
    second_shop = uuid.uuid4()
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.shops (id, user_id, shop_name, business_id) "
                "VALUES (:s, :u, 'second', :b)"
            ),
            {"s": second_shop, "u": owner.user_id, "b": business_id},
        )
    member = _tenant(owner_engine, "member")
    stranger = _tenant(owner_engine, "stranger")
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.business_members (id, business_id, user_id, role, added_via) "
                "VALUES (gen_random_uuid(), :b, :u, 'member', 'invite')"
            ),
            {"b": business_id, "u": member.user_id},
        )
    both = {owner.shop_id, second_shop}
    assert await _visible(member.user_id) == both | {member.shop_id}
    assert await _raw(member.user_id) == both | {member.shop_id}
    assert await _raw(stranger.user_id) == {stranger.shop_id}

    async with app_session() as session:
        owner_user = User(id=owner.user_id, email=None)
        await businesses.remove_member(
            session, business_id, owner_user, member.user_id, now=datetime(2026, 11, 15)
        )
        await session.commit()
    assert await _visible(member.user_id) == {member.shop_id}
    assert await _raw(member.user_id) == {member.shop_id}


async def test_shops_user_id_alone_admits_nothing_once_a_business_exists(owner_engine):
    tenant = _tenant(owner_engine, "contact")
    business_id = _business_of(owner_engine, tenant.shop_id)
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE public.business_members SET removed_at = now() WHERE business_id = :b"),
            {"b": business_id},
        )
        conn.execute(
            text("DELETE FROM public.shop_members WHERE shop_id = :s"), {"s": tenant.shop_id}
        )
    assert tenant.shop_id not in await _raw(tenant.user_id)


def test_deferred_backfill_maps_pre_130_shops_and_is_idempotent(owner_engine):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    plain = _tenant(owner_engine, "plain")
    staffed = _tenant(owner_engine, "staffed")
    staff = _tenant(owner_engine, "staff")
    gone = _tenant(owner_engine, "gone")
    removed_owner = _tenant(owner_engine, "removed-owner")
    sandbox = _tenant(owner_engine, "sandbox")
    pre = [plain, staffed, gone, removed_owner, sandbox]
    with owner_engine.begin() as conn:  # simulate shops made before migration 130 ran
        for tenant in pre:
            business_id = conn.execute(
                text("SELECT business_id FROM public.shops WHERE id = :s"), {"s": tenant.shop_id}
            ).scalar_one()
            conn.execute(
                text("UPDATE public.shops SET business_id = NULL WHERE id = :s"),
                {"s": tenant.shop_id},
            )
            conn.execute(
                text("DELETE FROM public.business_members WHERE business_id = :b"),
                {"b": business_id},
            )
            conn.execute(text("DELETE FROM public.businesses WHERE id = :b"), {"b": business_id})
        conn.execute(
            text(
                "INSERT INTO public.shop_members (id, shop_id, user_id, email, added_via) "
                "VALUES (gen_random_uuid(), :s, :u, 'staff@x.vn', 'invite')"
            ),
            {"s": staffed.shop_id, "u": staff.user_id},
        )
        conn.execute(
            text(
                "INSERT INTO public.shop_members (id, shop_id, user_id, added_via, removed_at) "
                "VALUES (gen_random_uuid(), :s, :u, 'invite', now())"
            ),
            {"s": staffed.shop_id, "u": gone.user_id},
        )
        conn.execute(
            text("DELETE FROM public.shop_members WHERE shop_id = :s"),
            {"s": removed_owner.shop_id},
        )
        conn.execute(
            text(
                "INSERT INTO public.shop_members (id, shop_id, user_id, added_via, removed_at) "
                "VALUES (gen_random_uuid(), :s, :u, 'owner', now())"
            ),
            {"s": removed_owner.shop_id, "u": removed_owner.user_id},
        )
        conn.execute(
            text(
                "UPDATE public.tiktok_credentials SET capability = 'sandbox_write' "
                "WHERE shop_id = :s"
            ),
            {"s": sandbox.shop_id},
        )
    assert asyncio.run(_visible(plain.user_id)) >= {plain.shop_id}  # P93 rule until backfill

    spec = importlib.util.spec_from_file_location("backfill_130", BACKFILL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def run_backfill():
        with owner_engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                module.upgrade()

    try:
        run_backfill()
        run_backfill()
        for tenant in pre:
            assert _business_of(owner_engine, tenant.shop_id) == tenant.shop_id
        assert [(r.user_id, r.role) for r in _members(owner_engine, plain.shop_id)] == [
            (plain.user_id, "owner")
        ]
        staffed_rows = {(r.user_id, r.role) for r in _members(owner_engine, staffed.shop_id)}
        assert staffed_rows == {(staffed.user_id, "owner"), (staff.user_id, "member")}
        assert _members(owner_engine, removed_owner.shop_id) == []
        assert asyncio.run(_visible(removed_owner.user_id)) == set()  # removal stays final
        with owner_engine.connect() as conn:
            kinds = dict(
                conn.execute(
                    text("SELECT id, kind FROM public.shops WHERE id IN (:a, :b)"),
                    {"a": sandbox.shop_id, "b": plain.shop_id},
                ).all()
            )
            nullable = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'shops' AND column_name = 'business_id'"
                )
            ).scalar_one()
        assert kinds[plain.shop_id] == "real"
        assert kinds[sandbox.shop_id] == "sandbox"  # seed_tenant gives each shop a credential
        assert nullable == "NO"
    finally:
        with owner_engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                module.downgrade()
