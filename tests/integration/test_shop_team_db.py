"""P93 shop team on real Postgres (migration 121_shop_members).

Membership is enforced by the database, not only by the route. The ``shops`` SELECT / UPDATE
policies admit an ACTIVE member, or the owner who has no ``shop_members`` row of their own yet,
so a removed member's session reads zero shop rows at once and a stranger never reads one.

- the AFTER INSERT trigger gives a seller owner a member row (no placeholder, no team account);
- ``juli_app`` reads only its own member rows and cannot write the table; ``juli_ops`` writes it;
- invite -> accept ADDS a member; the first person of a team-owned shop also takes it;
- removal (Ops) is immediate for ``list_for_authorization`` and for raw ``shops`` reads;
- two members and a stranger: no cross-tenant read of the other shop's rows;
- the deferred backfill is idempotent and leaves placeholders, team accounts and removed
  owners alone.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import with_user_scope
from juli_backend.models.models import User
from juli_backend.repositories.identity import ShopsRepo
from juli_backend.services import shop_team
from juli_backend.services.ops import audit, invites, overview
from juli_backend.services.ops import mailer as ops_mailer
from tests.integration.test_ops_console_db import app_session
from tests.integration.two_tenant import seed_tenant

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
        reason="DATABASE_URL is not set to a Postgres instance",
    ),
    pytest.mark.migration_heavy,
]

STAFF = audit.Actor(staff_id=None, email="tester@app-juli.com")
BACKFILL = (
    Path(__file__).resolve().parents[2]
    / "backend/src/juli_backend/database/migrations/deferred/102_shop_members_backfill.py"
)


def _tenant(engine, label: str, *, email: str | None):
    """A seeded tenant whose owner has ``email``; the trigger row follows it."""
    tenant = seed_tenant(engine, label=f"{label}-{uuid.uuid4().hex[:6]}")
    if email is not None:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE public.users SET email = :e WHERE id = :u"),
                {"e": email, "u": tenant.user_id},
            )
            if shop_team.is_team_email(email):
                conn.execute(
                    text("DELETE FROM public.shop_members WHERE shop_id = :s"),
                    {"s": tenant.shop_id},
                )
            else:
                conn.execute(
                    text("UPDATE public.shop_members SET email = lower(:e) WHERE shop_id = :s"),
                    {"e": email, "s": tenant.shop_id},
                )
    return tenant


def _members(engine, shop_id):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT user_id, email, added_via, removed_at FROM public.shop_members "
                "WHERE shop_id = :s ORDER BY added_at, id"
            ),
            {"s": shop_id},
        ).all()


def _unique(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:8]}@gmail.com"


class _Quiet:
    async def send_invite(self, mail):
        return False


async def _invite_accept(owner_engine, shop_id, person_id, email: str) -> dict:
    ops_mailer.set_mailer(_Quiet())
    try:
        async with app_session() as session:
            listing = await overview.find_shop(session, shop_id)
            created = await invites.create_invite(
                session, STAFF, listing, email=email, keep_ops_access=True
            )
            await session.commit()
        token = created.accept_url.split("#")[1]
        async with app_session() as session:
            user = User(id=person_id, email=email)
            result = await invites.accept_invite(session, token, user, keep_ops_access=False)
            await session.commit()
        return result
    finally:
        ops_mailer.set_mailer(None)


async def _visible_shops(user_id) -> list[uuid.UUID]:
    """What ``get_active_shop`` sees: the user's shops through the runtime role's RLS."""
    async with app_session() as session:
        shops = await ShopsRepo(session).list_for_authorization(user_id)
        return [s.id for s in shops]


async def _raw_shop_ids(user_id) -> list[uuid.UUID]:
    """A bare ``SELECT`` on ``shops`` under only the user GUC: the policy alone decides."""
    async with app_session() as session:
        async with with_user_scope(session, user_id):
            rows = await session.execute(text("SELECT id FROM public.shops"))
            return [r[0] for r in rows.all()]


def _new_shop(engine, *, email: str | None, phone: str | None) -> tuple[uuid.UUID, uuid.UUID]:
    user_id, shop_id = uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO public.users (id, email, phone) VALUES (:u, :e, :p)"),
            {"u": user_id, "e": email, "p": phone},
        )
        conn.execute(
            text("INSERT INTO public.shops (id, user_id, shop_name) VALUES (:s, :u, 'p93 shop')"),
            {"s": shop_id, "u": user_id},
        )
    return user_id, shop_id


def test_trigger_gives_a_seller_owner_a_row_and_skips_placeholders_and_team_accounts(owner_engine):
    seller_id, seller_shop = _new_shop(owner_engine, email="Seller.P93@Gmail.com", phone=None)
    rows = _members(owner_engine, seller_shop)
    assert [(r.user_id, r.added_via, r.removed_at, r.email) for r in rows] == [
        (seller_id, "owner", None, "seller.p93@gmail.com")
    ]
    # a Juli team account, and a login-less contract-shop owner (no e-mail, phone or Terms): no row
    _, team_shop = _new_shop(owner_engine, email="Ops.P93@app-juli.com", phone=None)
    _, placeholder_shop = _new_shop(owner_engine, email=None, phone=None)
    assert _members(owner_engine, team_shop) == []
    assert _members(owner_engine, placeholder_shop) == []
    # a phone-only legacy seller is still a person
    legacy_id, legacy_shop = _new_shop(
        owner_engine, email=None, phone=f"+1555{uuid.uuid4().hex[:7]}"
    )
    assert [r.user_id for r in _members(owner_engine, legacy_shop)] == [legacy_id]


def test_juli_app_reads_only_its_own_member_rows_and_cannot_write_the_table(owner_engine):
    import asyncio

    a = _tenant(owner_engine, "a", email=_unique("a"))
    b = _tenant(owner_engine, "b", email=_unique("b"))

    async def run():
        async with app_session() as session:
            async with with_user_scope(session, a.user_id):
                mine = (
                    await session.execute(text("SELECT user_id FROM public.shop_members"))
                ).all()
            assert {r[0] for r in mine} == {a.user_id}
            async with with_user_scope(session, uuid.uuid4()):
                none = (
                    await session.execute(text("SELECT user_id FROM public.shop_members"))
                ).all()
            assert none == []
        for statement in (
            f"INSERT INTO public.shop_members (id, shop_id, user_id, added_via) VALUES "
            f"(gen_random_uuid(), '{a.shop_id}', '{b.user_id}', 'invite')",
            f"UPDATE public.shop_members SET removed_at = now() WHERE shop_id = '{a.shop_id}'",
            "DELETE FROM public.shop_members",
        ):
            async with app_session() as session:
                with pytest.raises(Exception, match="permission denied"):
                    await session.execute(text(statement))

    asyncio.run(run())


async def test_invite_accept_adds_members_and_both_see_the_shop(owner_engine):
    team_email = f"ops{uuid.uuid4().hex[:5]}@app-juli.com"
    shop = _tenant(owner_engine, "team-shop", email=team_email)
    first, second = _tenant(owner_engine, "p1", email=None), _tenant(owner_engine, "p2", email=None)
    e1, e2 = _unique("first"), _unique("second")
    r1 = await _invite_accept(owner_engine, shop.shop_id, first.user_id, e1)
    r2 = await _invite_accept(owner_engine, shop.shop_id, second.user_id, e2)
    assert r1["took_shop"] is True and r2["took_shop"] is False
    with owner_engine.connect() as conn:
        owner = conn.execute(
            text("SELECT user_id FROM public.shops WHERE id = :s"), {"s": shop.shop_id}
        ).scalar_one()
    assert owner == first.user_id  # only the first accept moved the shop
    members = _members(owner_engine, shop.shop_id)
    assert sorted(m.email for m in members) == sorted([e1.lower(), e2.lower()])
    assert all(m.removed_at is None for m in members)
    assert shop.shop_id in await _visible_shops(first.user_id)
    assert shop.shop_id in await _visible_shops(second.user_id)
    assert shop.shop_id in await _raw_shop_ids(second.user_id)
    # the team account that connected it no longer reaches the seller side
    assert shop.shop_id not in await _visible_shops(shop.user_id)


async def test_removal_is_immediate_in_the_database_and_isolation_holds(owner_engine):
    shop_a = _tenant(owner_engine, "shop-a", email=_unique("owner-a"))
    shop_b = _tenant(owner_engine, "shop-b", email=_unique("owner-b"))
    joiner = _tenant(owner_engine, "joiner", email=None)
    stranger = _tenant(owner_engine, "stranger", email=_unique("stranger"))
    email = _unique("joiner")
    await _invite_accept(owner_engine, shop_a.shop_id, joiner.user_id, email)

    assert set(await _visible_shops(joiner.user_id)) == {joiner.shop_id, shop_a.shop_id}  # never B
    assert shop_b.shop_id not in await _raw_shop_ids(joiner.user_id)
    # a stranger (own shop only) never reads A's or B's row
    assert await _raw_shop_ids(stranger.user_id) == [stranger.shop_id]
    # the shop owner keeps both policies' view of their own shop
    assert await _visible_shops(shop_a.user_id) == [shop_a.shop_id]

    async with app_session() as session:
        listing = await overview.find_shop(session, shop_a.shop_id)
        removed = await shop_team.remove_member(
            session,
            STAFF,
            listing,
            joiner.user_id,
            now=__import__("datetime").datetime(2026, 11, 5),
        )
        await session.commit()
    assert removed.user_id == joiner.user_id
    assert await _visible_shops(joiner.user_id) == [joiner.shop_id]  # only their own shop is left
    assert await _raw_shop_ids(joiner.user_id) == [joiner.shop_id]
    # the other member and the data are untouched
    assert await _visible_shops(shop_a.user_id) == [shop_a.shop_id]
    with owner_engine.connect() as conn:
        runs = conn.execute(
            text("SELECT count(*) FROM public.workflow_runs WHERE shop_id = :s"),
            {"s": shop_a.shop_id},
        ).scalar_one()
        log = conn.execute(
            text(
                "SELECT count(*) FROM public.ops_audit_log "
                "WHERE shop_id = :s AND action = 'member_remove'"
            ),
            {"s": shop_a.shop_id},
        ).scalar_one()
    assert runs > 0 and log == 1
    rows = _members(owner_engine, shop_a.shop_id)
    assert [r.removed_at is not None for r in rows if r.user_id == joiner.user_id] == [True]


async def test_removing_the_owner_row_holds_against_the_owner_fallback(owner_engine):
    shop = _tenant(owner_engine, "solo", email=_unique("solo"))
    assert await _visible_shops(shop.user_id) == [shop.shop_id]
    async with app_session() as session:
        listing = await overview.find_shop(session, shop.shop_id)
        await shop_team.remove_member(
            session, STAFF, listing, shop.user_id, now=__import__("datetime").datetime(2026, 11, 5)
        )
        await session.commit()
    # the removed owner is still shops.user_id, but has a removed row: no access, shop kept
    assert await _visible_shops(shop.user_id) == []
    assert await _raw_shop_ids(shop.user_id) == []
    with owner_engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT user_id FROM public.shops WHERE id = :s"), {"s": shop.shop_id}
            ).scalar_one()
            == shop.user_id
        )


async def test_ops_shopee_screens_still_open_after_the_owner_is_removed(owner_engine):
    """2026-11-05: ``Gỡ`` on the owner of a Shopee shop made every Ops Shopee screen answer
    409 ``not_a_shopee_shop``: the platform was read under the removed owner's scope."""
    from fastapi import HTTPException

    from juli_backend.api.routes.ops_shopee_dashboards import _shopee_shop

    shop = _tenant(owner_engine, "shopee", email=_unique("shopee"))
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE public.shops SET platform = 'shopee' WHERE id = :s"),
            {"s": shop.shop_id},
        )
    async with app_session() as session:
        listing = await overview.find_shop(session, shop.shop_id)
        await shop_team.remove_member(
            session, STAFF, listing, shop.user_id, now=__import__("datetime").datetime(2026, 11, 5)
        )
        await session.commit()
    assert await _raw_shop_ids(shop.user_id) == []
    async with app_session() as session:
        await _shopee_shop(session, shop.shop_id)  # no 409
    # a TikTok shop is still refused
    other = _tenant(owner_engine, "tiktok", email=_unique("tiktok"))
    async with app_session() as session:
        with pytest.raises(HTTPException) as refused:
            await _shopee_shop(session, other.shop_id)
    assert refused.value.status_code == 409


def test_owner_without_a_row_keeps_access_until_the_backfill_and_the_backfill_is_idempotent(
    owner_engine,
):
    import asyncio

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    pre = _tenant(owner_engine, "pre", email=_unique("pre"))
    team = _tenant(owner_engine, "team2", email=f"ops{uuid.uuid4().hex[:5]}@app-juli.com")
    removed_owner = _tenant(owner_engine, "gone", email=_unique("gone"))
    with owner_engine.begin() as conn:  # simulate shops made before migration 121 ran
        conn.execute(
            text("DELETE FROM public.shop_members WHERE shop_id IN (:a, :b)"),
            {"a": pre.shop_id, "b": removed_owner.shop_id},
        )
        conn.execute(
            text(
                "INSERT INTO public.shop_members (id, shop_id, user_id, added_via, removed_at) "
                "VALUES (gen_random_uuid(), :s, :u, 'owner', now())"
            ),
            {"s": removed_owner.shop_id, "u": removed_owner.user_id},
        )
    assert _members(owner_engine, pre.shop_id) == []
    assert asyncio.run(_visible_shops(pre.user_id)) == [pre.shop_id]  # owner without a row

    spec = importlib.util.spec_from_file_location("backfill_102", BACKFILL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def run_backfill():
        with owner_engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                module.upgrade()

    run_backfill()
    run_backfill()
    assert [(r.added_via, r.removed_at) for r in _members(owner_engine, pre.shop_id)] == [
        ("backfill", None)
    ]
    assert _members(owner_engine, team.shop_id) == []
    assert [r.removed_at is not None for r in _members(owner_engine, removed_owner.shop_id)] == [
        True
    ]
    assert asyncio.run(_visible_shops(removed_owner.user_id)) == []
    assert asyncio.run(_visible_shops(pre.user_id)) == [pre.shop_id]
