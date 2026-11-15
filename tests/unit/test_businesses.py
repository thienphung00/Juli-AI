"""P101 W1 identity: businesses, membership access, self-serve invites (SQLite).

Access to a shop = active member of its business, or an active ``shop_members`` row. A connected
shop joins the caller's selected / only business, or gets a business named after it. The business
owner invites by e-mail and removes members (soft delete); a removed member loses every shop of the
business at once. Ops' removal of a person from a shop also takes their business membership.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from juli_backend.api.routes.ops import get_ops_user
from juli_backend.core.security import get_current_user
from juli_backend.core.security.oauth_state import mint_oauth_state, verify_oauth_state
from juli_backend.models.businesses import Business, BusinessMember
from juli_backend.models.models import Shop, User
from juli_backend.models.ops import OpsAuditLog, OpsStaff
from juli_backend.repositories.identity import ShopsRepo
from juli_backend.services import businesses, shop_team
from juli_backend.services.ops import mailer as ops_mailer
from tests.support.api import build_app, client_for
from tests.support.builders import make_tenant, make_user


@pytest.fixture(autouse=True)
def bypass_access(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")


class FakeMailer:
    def __init__(self) -> None:
        self.notices: list[dict[str, str]] = []

    async def send_invite(self, mail):
        return True

    async def send_notice(self, *, to: str, subject: str, body: str) -> bool:
        self.notices.append({"to": to, "subject": subject, "body": body})
        return True


@pytest.fixture(autouse=True)
def fake_mailer():
    mailer = FakeMailer()
    ops_mailer.set_mailer(mailer)
    yield mailer
    ops_mailer.set_mailer(None)


def _client(session, user: User):
    app = build_app(session)

    async def current() -> User:
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    app.dependency_overrides[get_ops_user] = current
    return client_for(app)


async def _connect_shopee(session, user: User, name: str, business_id: str | None = None) -> dict:
    body: dict = {"shop_name": name}
    if business_id is not None:
        body["business_id"] = business_id
    async with _client(session, user) as client:
        response = await client.post("/v1/shops/shopee", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def _businesses(session, user: User) -> list[dict]:
    async with _client(session, user) as client:
        response = await client.get("/v1/businesses")
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def _invite_and_accept(session, owner: User, business_id: str, email: str, mailer) -> User:
    async with _client(session, owner) as client:
        created = await client.post(f"/v1/businesses/{business_id}/invites", json={"email": email})
    assert created.status_code == 201, created.text
    token = mailer.notices[-1]["body"].split("#")[1].split()[0]
    person = await make_user(session, email=email.lower())
    async with _client(session, person) as client:
        preview = await client.post("/v1/shop-invites/preview", json={"token": token})
        assert preview.status_code == 200, preview.text
        assert preview.json()["data"]["business_id"] == business_id
        accepted = await client.post("/v1/shop-invites/accept", json={"token": token})
    assert accepted.status_code == 200, accepted.text
    return person


async def test_first_shop_gets_a_business_named_after_it_and_the_second_joins_it(session):
    seller = await make_user(session, email="seller@gmail.com")
    first = await _connect_shopee(session, seller, "Ory Store")
    listed = await _businesses(session, seller)
    assert len(listed) == 1
    business = listed[0]
    assert business["name"] == "Ory Store" and business["role"] == "owner"
    assert business["shops"] == [
        {"id": first["id"], "name": "Ory Store", "platform": "shopee", "kind": "real"}
    ]
    second = await _connect_shopee(session, seller, "Ory Outlet")
    listed = await _businesses(session, seller)
    assert len(listed) == 1
    assert [s["id"] for s in listed[0]["shops"]] == [first["id"], second["id"]]
    assert [m["email"] for m in listed[0]["members"]] == ["seller@gmail.com"]


async def test_a_shop_joins_the_selected_business_and_a_foreign_one_is_refused(session):
    seller = await make_user(session, email="two@gmail.com")
    await _connect_shopee(session, seller, "A")
    a_id = (await _businesses(session, seller))[0]["id"]
    # a second business of their own (several businesses, no choice -> a new one)
    session.add(Business(id=uuid.uuid4(), name="B"))
    await session.flush()
    b = (await session.execute(select(Business).where(Business.name == "B"))).scalar_one()
    session.add(
        BusinessMember(
            id=uuid.uuid4(), business_id=b.id, user_id=seller.id, role="owner", added_via="owner"
        )
    )
    await session.flush()
    joined = await _connect_shopee(session, seller, "B shop", business_id=str(b.id))
    assert (await session.get(Shop, uuid.UUID(joined["id"]))).business_id == b.id
    unchosen = await _connect_shopee(session, seller, "C shop")
    shop_c = await session.get(Shop, uuid.UUID(unchosen["id"]))
    assert shop_c.business_id not in (b.id, uuid.UUID(a_id))

    stranger = await make_user(session, email="stranger@gmail.com")
    async with _client(session, stranger) as client:
        refused = await client.post(
            "/v1/shops/shopee", json={"shop_name": "X", "business_id": a_id}
        )
    assert refused.status_code == 404


async def test_invited_member_opens_every_shop_and_loses_them_when_removed(session, fake_mailer):
    owner = await make_user(session, email="owner@gmail.com")
    one = await _connect_shopee(session, owner, "Shop One")
    two = await _connect_shopee(session, owner, "Shop Two")
    business_id = (await _businesses(session, owner))[0]["id"]
    member = await _invite_and_accept(session, owner, business_id, "Staff@Gmail.com", fake_mailer)
    member_id = member.id
    assert {s.id for s in await ShopsRepo(session).list(member_id)} == {
        uuid.UUID(one["id"]),
        uuid.UUID(two["id"]),
    }
    async with _client(session, member) as client:
        ok = await client.get("/v1/shops/me", headers={"X-Shop-Id": two["id"]})
        assert ok.status_code == 200
        # a member is not the owner: no invite, no removal
        assert (
            await client.post(f"/v1/businesses/{business_id}/invites", json={"email": "z@x.vn"})
        ).status_code == 403
        assert (
            await client.delete(f"/v1/businesses/{business_id}/members/{owner.id}")
        ).status_code == 403
    listed = await _businesses(session, member)
    assert listed[0]["role"] == "member" and "members" not in listed[0]

    async with _client(session, owner) as client:
        self_removal = await client.delete(f"/v1/businesses/{business_id}/members/{owner.id}")
        assert self_removal.status_code == 409
        removed = await client.delete(f"/v1/businesses/{business_id}/members/{member_id}")
        assert removed.status_code == 200
        again = await client.delete(f"/v1/businesses/{business_id}/members/{member_id}")
        assert again.status_code == 404
    assert await ShopsRepo(session).list(member_id) == []
    async with _client(session, member) as client:
        denied = await client.get("/v1/shops/me", headers={"X-Shop-Id": one["id"]})
    assert denied.status_code == 403
    row = (
        await session.execute(select(BusinessMember).where(BusinessMember.user_id == member_id))
    ).scalar_one()
    assert row.removed_at is not None and row.added_via == "invite"  # soft delete
    actions = sorted(r.action for r in (await session.execute(select(OpsAuditLog))).scalars())
    assert actions.count(businesses.ACTION_BUSINESS_INVITE_CREATE) == 1
    assert actions.count(businesses.ACTION_BUSINESS_INVITE_ACCEPT) == 1
    assert actions.count(businesses.ACTION_BUSINESS_MEMBER_REMOVE) == 1


async def test_invite_rules_wrong_account_and_already_member(session, fake_mailer):
    owner = await make_user(session, email="o2@gmail.com")
    await _connect_shopee(session, owner, "Shop")
    business_id = (await _businesses(session, owner))[0]["id"]
    async with _client(session, owner) as client:
        assert (
            await client.post(
                f"/v1/businesses/{business_id}/invites", json={"email": "O2@gmail.com"}
            )
        ).status_code == 409
        assert (
            await client.post(f"/v1/businesses/{business_id}/invites", json={"email": "nope"})
        ).status_code == 422
        assert (
            await client.post(
                f"/v1/businesses/{business_id}/invites", json={"email": "p@gmail.com"}
            )
        ).status_code == 201
    token = fake_mailer.notices[-1]["body"].split("#")[1].split()[0]
    intruder = await make_user(session, email="other@gmail.com")
    async with _client(session, intruder) as client:
        wrong = await client.post("/v1/shop-invites/accept", json={"token": token})
        assert wrong.status_code == 403
        assert (
            await client.post(
                f"/v1/businesses/{business_id}/invites", json={"email": "q@gmail.com"}
            )
        ).status_code == 404
    assert await _businesses(session, intruder) == []


async def test_ops_removal_from_a_shop_also_ends_the_business_membership(session, fake_mailer):
    owner = await make_user(session, email="o3@gmail.com")
    shop = await _connect_shopee(session, owner, "Shop")
    business_id = (await _businesses(session, owner))[0]["id"]
    member = await _invite_and_accept(session, owner, business_id, "m3@gmail.com", fake_mailer)
    member_id = member.id
    staff_email = f"operator-{uuid.uuid4().hex[:6]}@app-juli.com"
    staff = await make_user(session, email=staff_email)
    session.add(OpsStaff(id=uuid.uuid4(), email=staff_email, role="operator", active=True))
    await session.flush()
    async with _client(session, staff) as client:
        listed = (await client.get(f"/v1/ops/shops/{shop['id']}/members")).json()["data"]
        assert str(member_id) in {m["user_id"] for m in listed}
        removed = await client.delete(f"/v1/ops/shops/{shop['id']}/members/{member_id}")
        assert removed.status_code == 200, removed.text
    assert not await shop_team.is_member(session, uuid.UUID(shop["id"]), member_id)
    assert await businesses.member_of(session, uuid.UUID(business_id), member_id) is None


async def test_a_legacy_shop_without_a_business_keeps_its_owner_and_lists_alone(session):
    owner, shop = await make_tenant(session)
    assert shop.business_id is None
    assert await shop_team.is_member(session, shop.id, owner.id)
    listed = await _businesses(session, owner)
    assert listed == [
        {
            "id": None,
            "name": shop.shop_name,
            "role": "owner",
            "shops": [
                {"id": str(shop.id), "name": shop.shop_name, "platform": "tiktok", "kind": "real"}
            ],
            "created_at": None,
        }
    ]


async def test_shops_user_id_is_no_access_rule_once_its_person_has_a_row(session):
    owner, shop = await make_tenant(session)
    business = Business(id=uuid.uuid4(), name="X")
    session.add(business)
    await session.flush()
    shop.business_id = business.id
    await session.flush()
    # no row of their own at all: P93's "owner without a row" (pre-backfill, or mid-insert)
    assert await shop_team.is_member(session, shop.id, owner.id)
    session.add(
        BusinessMember(
            id=uuid.uuid4(),
            business_id=business.id,
            user_id=owner.id,
            role="owner",
            added_via="owner",
            removed_at=datetime(2026, 11, 15),
        )
    )
    await session.flush()
    # a removed business row: shops.user_id alone admits nothing, removal is final
    assert not await shop_team.is_member(session, shop.id, owner.id)


def test_oauth_state_carries_the_business_signed():
    user_id, business_id = uuid.uuid4(), uuid.uuid4()
    state = mint_oauth_state(
        user_id, secret="s3cret", flow="seller_connect", business_id=business_id
    )
    verified = verify_oauth_state(state, secret="s3cret", expected_flow="seller_connect")
    assert verified.user_id == user_id and verified.business_id == business_id
    plain = mint_oauth_state(user_id, secret="s3cret", flow="seller_connect")
    assert (
        verify_oauth_state(plain, secret="s3cret", expected_flow="seller_connect").business_id
        is None
    )
