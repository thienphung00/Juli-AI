"""P16 D25.13 "Huỷ kết nối": Admin only, audited, idempotent; polling stops,
pending runs are cancelled, history is kept, and reconnecting resumes."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

from juli_backend.core.security import get_current_user
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.models.models import Shop, TikTokCredential, User, WorkflowRun
from juli_backend.models.ops import OpsAuditLog, OpsStaff
from juli_backend.services.ops import disconnect
from juli_backend.services.ops import mailer as ops_mailer
from juli_backend.services.tiktok.credential_binding import make_binding_verifier
from juli_backend.workers.services.polling.ingestion import enumerate_pollable_shops
from tests.support.api import build_app, client_for
from tests.support.builders import make_credential, make_tenant, make_user, make_workflow_run


class Notices:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_invite(self, mail):
        return False

    async def send_notice(self, *, to, subject, body):
        self.sent.append((to, subject))
        return True


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    notices = Notices()
    ops_mailer.set_mailer(notices)
    yield notices
    ops_mailer.set_mailer(None)


async def _staff(session, role):
    email = f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=True))
    await session.flush()
    return user


def _client(session, user):
    app = build_app(session)

    async def current() -> User:
        await session.refresh(user)  # a route's rollback expires it, like a new request
        return user

    app.dependency_overrides[get_current_user] = current
    return client_for(app)


async def _connected_shop(session):
    owner, shop = await make_tenant(session)
    owner.email = "seller@gmail.com"
    await make_credential(
        session,
        shop,
        capability="production_read",
        merchant_authorization_id=f"merchant-{uuid.uuid4().hex[:6]}",
        status="active",
    )
    run = await make_workflow_run(session, shop, status="waiting_approval")
    done = await make_workflow_run(session, shop, status="completed")
    await session.commit()
    return owner, shop, run, done


@pytest.mark.parametrize("role", ["viewer", "operator"])
async def test_only_admin_can_disconnect(session, role):
    _, shop, _, _ = await _connected_shop(session)
    user = await _staff(session, role)
    async with _client(session, user) as client:
        response = await client.post(
            f"/v1/ops/shops/{shop.id}/disconnect",
            json={"reason": "seller asked", "confirm_name": shop.shop_name},
        )
    assert response.status_code == 403


async def test_reason_and_shop_name_are_required(session):
    _, shop, _, _ = await _connected_shop(session)
    shop_id, name = shop.id, shop.shop_name
    user = await _staff(session, "admin")
    async with _client(session, user) as client:
        no_reason = await client.post(
            f"/v1/ops/shops/{shop_id}/disconnect",
            json={"reason": " ", "confirm_name": name},
        )
        wrong_name = await client.post(
            f"/v1/ops/shops/{shop_id}/disconnect", json={"reason": "x", "confirm_name": "nope"}
        )
    assert no_reason.status_code == 422 and wrong_name.status_code == 422


async def test_disconnect_stops_polling_cancels_runs_keeps_history_and_is_idempotent(session, env):
    _, shop, pending, done = await _connected_shop(session)
    shop_id, pending_id, done_id, name = shop.id, pending.id, done.id, shop.shop_name
    assert shop_id in {p.shop_id for p in await enumerate_pollable_shops(session)}
    user = await _staff(session, "admin")
    async with _client(session, user) as client:
        first = await client.post(
            f"/v1/ops/shops/{shop_id}/disconnect",
            json={"reason": "seller asked to stop the trial", "confirm_name": name},
        )
        second = await client.post(
            f"/v1/ops/shops/{shop_id}/disconnect", json={"reason": "again", "confirm_name": name}
        )
    assert first.status_code == 200, first.text
    data = first.json()["data"]
    assert data["already_disconnected"] is False
    assert data["credentials_revoked"] == 1 and data["runs_cancelled"] == 1
    assert data["tiktok_revoke"] == "not_available"
    assert second.json()["data"]["already_disconnected"] is True
    assert env.sent == [("seller@gmail.com", f"Juli đã huỷ kết nối shop {name}")]

    assert shop_id not in {p.shop_id for p in await enumerate_pollable_shops(session)}
    is_active = (
        await session.execute(select(Shop.is_active).where(Shop.id == shop_id))
    ).scalar_one()
    assert is_active is False
    cred = (
        (await session.execute(select(TikTokCredential).where(TikTokCredential.shop_id == shop_id)))
        .scalars()
        .one()
    )
    assert cred.status == "needs_reauth" and cred.access_token == disconnect.REVOKED_TOKEN
    flags = dict(
        (await session.execute(select(WorkflowRun.id, WorkflowRun.cancel_requested))).all()
    )
    assert flags[pending_id] is True and flags[done_id] is False
    runs = (
        await session.execute(
            select(func.count()).select_from(WorkflowRun).where(WorkflowRun.shop_id == shop_id)
        )
    ).scalar_one()
    assert runs == 2  # history kept
    audits = (
        (await session.execute(select(OpsAuditLog).where(OpsAuditLog.action == "shop_disconnect")))
        .scalars()
        .all()
    )
    assert len(audits) == 2
    assert audits[0].after["reason"] in {"seller asked to stop the trial", "again"}


async def test_reconnecting_resumes(session, user_id):
    tiktok_auth = TikTokAuth(
        app_key="k", app_secret="s", base_url="https://open-api.tiktokglobalshop.com"
    )
    service = TikTokOAuthService(
        tiktok_auth=tiktok_auth,
        session=session,
        redirect_uri="https://x/cb",
        app_secret="s",
        binding_verifier=make_binding_verifier(app_key="k", app_secret="s"),
    )
    session.add(User(id=user_id, phone="+84901234599", email="seller2@gmail.com"))
    await session.flush()
    tiktok_auth.exchange_code = MagicMock(
        return_value={
            "access_token": "ROW_a",
            "refresh_token": "ROW_r",
            "access_token_expire_in": 604800,
            "open_id": "seller_resume",
            "seller_name": "Resume Shop",
        }
    )
    url = await service.initiate_oauth(user_id)
    shop = await service.handle_callback("c1", parse_qs(urlparse(url).query)["state"][0])
    listing = disconnect.ShopListing(
        shop_id=shop.id,
        shop_name=shop.shop_name,
        tiktok_shop_id=shop.tiktok_shop_id,
        is_active=True,
        owner_user_id=user_id,
        owner_email="seller2@gmail.com",
        owner_consent_at=None,
    )
    from juli_backend.services.ops.audit import Actor

    await disconnect.disconnect_shop(
        session, Actor(None, "a@app-juli.com"), listing, reason="test", confirm_name=shop.shop_name
    )
    assert shop.is_active is False
    url = await service.initiate_oauth(user_id)
    again = await service.handle_callback("c2", parse_qs(urlparse(url).query)["state"][0])
    assert again.id == shop.id and again.is_active is True
    cred = (
        (await session.execute(select(TikTokCredential).where(TikTokCredential.shop_id == shop.id)))
        .scalars()
        .one()
    )
    assert cred.status == "active"
