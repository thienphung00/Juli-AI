"""P93 shop team: many seller members on one shop, Ops-managed (SQLite).

Access is membership: an active ``shop_members`` row, or the owner who has no row of their own
yet. Invites ADD members; the first person of a shop with no seller member also takes it (P9-B
handover). Only Ops removes; a removed person loses the shop at once. Every seller action is
attributed to the acting member.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from juli_backend.api.routes.ops import get_ops_user
from juli_backend.core.security import get_current_user
from juli_backend.models.models import Shop, ShopMember, User
from juli_backend.models.ops import OpsAuditLog, OpsStaff
from juli_backend.models.run_changes import ShopRule
from juli_backend.repositories.identity import ShopsRepo
from juli_backend.services import shop_team
from juli_backend.services.ops import mailer as ops_mailer
from tests.support.api import authenticated_client, build_app, client_for
from tests.support.builders import make_tenant, make_user


@pytest.fixture(autouse=True)
def bypass_access(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[ops_mailer.InviteMail] = []

    async def send_invite(self, mail):
        self.sent.append(mail)
        return True


@pytest.fixture(autouse=True)
def fake_mailer():
    mailer = FakeMailer()
    ops_mailer.set_mailer(mailer)
    yield mailer
    ops_mailer.set_mailer(None)


async def _staff(session, role: str):
    email = f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=True))
    await session.flush()
    return user


def _ops_client(session, user: User):
    app = build_app(session)

    async def current() -> User:
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    app.dependency_overrides[get_ops_user] = current
    return client_for(app)


def _seller_client(session, user: User):
    """The real ``get_active_shop`` (membership) -- only the sign-in is stubbed."""
    app = build_app(session)

    async def current() -> User:
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    return client_for(app)


async def _invite_and_accept(session, staff_user, shop_id, email: str, fake_mailer) -> User:
    async with _ops_client(session, staff_user) as client:
        created = await client.post(
            f"/v1/ops/shops/{shop_id}/invites", json={"email": email, "keep_ops_access": True}
        )
    assert created.status_code == 201, created.text
    token = fake_mailer.sent[-1].accept_url.split("#")[1]
    person = await make_user(session, email=email)
    async with _seller_client(session, person) as client:
        accepted = await client.post("/v1/shop-invites/accept", json={"token": token})
    assert accepted.status_code == 200, accepted.text
    return person


async def _audit_actions(session) -> list[str]:
    return sorted(r.action for r in (await session.execute(select(OpsAuditLog))).scalars())


async def test_two_invites_two_members_both_see_the_shop(session, fake_mailer):
    _, shop = await make_tenant(session)
    shop_id = shop.id
    staff_user = await _staff(session, "operator")
    first = await _invite_and_accept(session, staff_user, shop_id, "a@gmail.com", fake_mailer)
    second = await _invite_and_accept(session, staff_user, shop_id, "B@Gmail.com", fake_mailer)
    first_id, second_id = first.id, second.id

    # the first accept took the shop (handover); the second only joined
    assert (
        await session.execute(select(Shop.user_id).where(Shop.id == shop_id))
    ).scalar_one() == first_id
    for person_id in (first_id, second_id):
        assert [s.id for s in await ShopsRepo(session).list(person_id)] == [shop_id]
        assert await shop_team.is_member(session, shop_id, person_id)
    rows = (
        (await session.execute(select(ShopMember).where(ShopMember.shop_id == shop_id)))
        .scalars()
        .all()
    )
    assert sorted(r.email or "" for r in rows) == ["a@gmail.com", "b@gmail.com"]
    assert all(r.removed_at is None and r.added_via == "invite" for r in rows)
    actions = await _audit_actions(session)
    assert actions.count("member_add") == 2 and actions.count("invite_accept") == 2


async def test_first_accept_hands_a_team_owned_shop_over_and_releases_the_team_account(
    session, fake_mailer
):
    team_owner, shop = await make_tenant(session)
    team_owner.email = "ops@app-juli.com"
    session.add(
        ShopMember(
            id=uuid.uuid4(),
            shop_id=shop.id,
            user_id=team_owner.id,
            email="ops@app-juli.com",
            added_via="owner",
        )
    )
    await session.flush()
    shop_id, team_id = shop.id, team_owner.id
    staff_user = await _staff(session, "operator")
    seller = await _invite_and_accept(session, staff_user, shop_id, "s@gmail.com", fake_mailer)
    assert (
        await session.execute(select(Shop.user_id).where(Shop.id == shop_id))
    ).scalar_one() == seller.id
    assert await shop_team.is_member(session, shop_id, seller.id)
    assert not await shop_team.is_member(session, shop_id, team_id)


async def test_a_pending_invite_to_someone_else_survives_a_new_invite(session, fake_mailer):
    _, shop = await make_tenant(session)
    shop_id = shop.id
    staff_user = await _staff(session, "operator")
    async with _ops_client(session, staff_user) as client:
        await client.post(f"/v1/ops/shops/{shop_id}/invites", json={"email": "x@gmail.com"})
        await client.post(f"/v1/ops/shops/{shop_id}/invites", json={"email": "y@gmail.com"})
        await client.post(f"/v1/ops/shops/{shop_id}/invites", json={"email": "x@gmail.com"})
        listed = (await client.get(f"/v1/ops/shops/{shop_id}/invites")).json()["data"]
    # Ops responses shorten seller e-mails (masking.py): "x@gmail.com" -> "x@gmail.com"[:6] + "…@…"
    live = sorted(i["email"] for i in listed if not i["revoked_at"] and not i["accepted_at"])
    assert live == ["x@gmai…@…", "y@gmai…@…"]  # only the older x@ link was replaced


async def test_ops_removes_a_member_who_loses_access_at_once_and_the_other_keeps_it(
    session, fake_mailer
):
    owner, shop = await make_tenant(session)
    shop_id, owner_id = shop.id, owner.id
    staff_user = await _staff(session, "operator")
    other = await _invite_and_accept(session, staff_user, shop_id, "o@gmail.com", fake_mailer)
    other_id = other.id

    async with _seller_client(session, other) as client:
        assert (
            await client.get("/v1/shops/me", headers={"X-Shop-Id": str(shop_id)})
        ).status_code == 200
    async with _ops_client(session, staff_user) as client:
        listed = (await client.get(f"/v1/ops/shops/{shop_id}/members")).json()["data"]
        # the pre-backfill owner is listed beside the invited person, same role
        assert {m["email"] for m in listed} >= {"o@gmai…@…"}
        assert str(other_id) in {m["user_id"] for m in listed}
        removed = await client.delete(f"/v1/ops/shops/{shop_id}/members/{other_id}")
        assert removed.status_code == 200
        assert removed.json()["data"]["removed"] is True
        again = await client.delete(f"/v1/ops/shops/{shop_id}/members/{other_id}")
        assert again.status_code == 404
    async with _seller_client(session, other) as client:
        denied = await client.get("/v1/shops/me", headers={"X-Shop-Id": str(shop_id)})
    assert denied.status_code == 403
    assert await ShopsRepo(session).list(other_id) == []
    assert not await shop_team.is_member(session, shop_id, other_id)
    assert await shop_team.is_member(
        session, shop_id, owner_id
    )  # the shop and its other people stay
    assert "member_remove" in await _audit_actions(session)
    row = (
        (await session.execute(select(ShopMember).where(ShopMember.user_id == other_id)))
        .scalars()
        .one()
    )
    assert (
        row.removed_at is not None and row.removed_by_staff is not None
    )  # soft delete, history kept


async def test_removing_the_last_member_and_the_pre_backfill_owner_is_allowed(session):
    owner, shop = await make_tenant(session)
    owner.email = "owner@gmail.com"
    await session.flush()
    shop_id, owner_id = shop.id, owner.id
    staff_user = await _staff(session, "operator")
    assert await shop_team.is_member(session, shop_id, owner_id)  # owner without a row
    async with _ops_client(session, staff_user) as client:
        gone = await client.delete(f"/v1/ops/shops/{shop_id}/members/{owner_id}")
    assert gone.status_code == 200
    assert not await shop_team.is_member(session, shop_id, owner_id)
    assert await ShopsRepo(session).list(owner_id) == []
    assert await session.get(Shop, shop_id) is not None


async def test_a_removed_person_can_be_invited_again(session, fake_mailer):
    _, shop = await make_tenant(session)
    shop_id = shop.id
    staff_user = await _staff(session, "operator")
    person = await _invite_and_accept(session, staff_user, shop_id, "r@gmail.com", fake_mailer)
    person_id = person.id
    async with _ops_client(session, staff_user) as client:
        await client.delete(f"/v1/ops/shops/{shop_id}/members/{person_id}")
        reinvite = await client.post(
            f"/v1/ops/shops/{shop_id}/invites", json={"email": "r@gmail.com"}
        )
    assert reinvite.status_code == 201
    token = fake_mailer.sent[-1].accept_url.split("#")[1]
    async with _seller_client(session, person) as client:
        assert (
            await client.post("/v1/shop-invites/accept", json={"token": token})
        ).status_code == 200
    assert await shop_team.is_member(session, shop_id, person_id)


async def test_only_operators_manage_members_and_sellers_have_no_endpoint(session):
    owner, shop = await make_tenant(session)
    shop_id, owner_id = shop.id, owner.id
    viewer = await _staff(session, "viewer")
    async with _ops_client(session, viewer) as client:
        assert (await client.get(f"/v1/ops/shops/{shop_id}/members")).status_code == 200
        assert (
            await client.delete(f"/v1/ops/shops/{shop_id}/members/{owner_id}")
        ).status_code == 403
        assert (
            await client.post(f"/v1/ops/shops/{shop_id}/invites", json={"email": "z@gmail.com"})
        ).status_code == 403
    async with _ops_client(session, owner) as client:  # a seller is not staff
        assert (
            await client.delete(f"/v1/ops/shops/{shop_id}/members/{owner_id}")
        ).status_code == 403
    from juli_backend.api.app import create_app

    seller_paths = [
        (r.path, sorted(r.methods or []))
        for r in create_app().routes
        if hasattr(r, "path") and "member" in r.path and not r.path.startswith("/v1/ops/")
    ]
    assert seller_paths == []  # no seller route adds, lists or removes members
    assert await shop_team.is_member(session, shop_id, owner_id)


async def test_inviting_a_current_member_is_refused(session, fake_mailer):
    _, shop = await make_tenant(session)
    shop_id = shop.id
    staff_user = await _staff(session, "operator")
    await _invite_and_accept(session, staff_user, shop_id, "m@gmail.com", fake_mailer)
    async with _ops_client(session, staff_user) as client:
        refused = await client.post(
            f"/v1/ops/shops/{shop_id}/invites", json={"email": "M@gmail.com"}
        )
    assert refused.status_code == 409


async def test_two_shops_of_one_person_are_both_listed_and_a_stranger_gets_nothing(
    session, fake_mailer
):
    _, shop_a = await make_tenant(session)
    _, shop_b = await make_tenant(session)
    a_id, b_id = shop_a.id, shop_b.id
    staff_user = await _staff(session, "operator")
    person = await _invite_and_accept(session, staff_user, a_id, "two@gmail.com", fake_mailer)
    async with _ops_client(session, staff_user) as client:
        await client.post(f"/v1/ops/shops/{b_id}/invites", json={"email": "two@gmail.com"})
    token = fake_mailer.sent[-1].accept_url.split("#")[1]
    async with _seller_client(session, person) as client:
        await client.post("/v1/shop-invites/accept", json={"token": token})
        mine = (await client.get("/v1/shops")).json()
    assert sorted(s["id"] for s in mine) == sorted([str(a_id), str(b_id)])
    stranger = await make_user(session, email="nobody@gmail.com")
    assert await ShopsRepo(session).list(stranger.id) == []
    async with _seller_client(session, stranger) as client:
        assert (
            await client.get("/v1/shops/me", headers={"X-Shop-Id": str(a_id)})
        ).status_code == 403


async def test_a_seller_action_is_attributed_to_the_acting_member(session, fake_mailer):
    owner, shop = await make_tenant(session)
    shop_id = shop.id
    staff_user = await _staff(session, "operator")
    member = await _invite_and_accept(session, staff_user, shop_id, "act@gmail.com", fake_mailer)
    member_id, owner_id = member.id, owner.id
    seller_shop = await session.get(Shop, shop_id)
    async with authenticated_client(session, user=member, shop=seller_shop) as client:
        put = await client.put(
            "/v1/demo/rules/content_tone", json={"value": "Thân thiện", "set_by": "seller"}
        )
    assert put.status_code == 200, put.text
    rule = (
        (await session.execute(select(ShopRule).where(ShopRule.shop_id == shop_id)))
        .scalars()
        .first()
    )
    assert rule is not None
    assert rule.set_by_user_id == member_id and rule.set_by_user_id != owner_id


async def test_write_approval_admits_any_member_and_refuses_a_removed_one(session, fake_mailer):
    from juli_backend.services.agent.write_approval import is_shop_member

    _, shop = await make_tenant(session)
    shop_id = shop.id
    staff_user = await _staff(session, "operator")
    person = await _invite_and_accept(session, staff_user, shop_id, "w@gmail.com", fake_mailer)
    person_id = person.id
    assert await is_shop_member(session, shop_id, person_id)
    async with _ops_client(session, staff_user) as client:
        await client.delete(f"/v1/ops/shops/{shop_id}/members/{person_id}")
    assert not await is_shop_member(session, shop_id, person_id)
