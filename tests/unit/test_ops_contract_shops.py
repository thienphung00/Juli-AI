"""Juli Ops contract-client shops (owner decisions 2026-11-02, ADR-118).

- "Thêm shop hợp đồng" creates a Shopee shop whose owner has no e-mail and no phone
  (no sign-in resolves to it), stamped with staff access; audited.
- "Bật" (no body) grants the four Terms scopes once, method ``contract_paper``,
  ``granted_by`` the staff member; a second press grants nothing and writes no audit.
- Ops never enables consent for a shop with a seller login (409), a viewer can do
  neither (403), and the ingest gate opens only after "Bật".

Synthetic fixtures only.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from juli_backend.models.consent import DataUseConsent
from juli_backend.models.models import Shop, User
from juli_backend.models.ops import OpsAuditLog
from juli_backend.services.consent import TERMS_SCOPES, has_consent
from tests.support.builders import make_shop, make_user


async def _ops_client(session, monkeypatch, role):
    from juli_backend.api.routes.ops import get_ops_user
    from juli_backend.core.security import get_current_user
    from juli_backend.models.ops import OpsStaff
    from tests.support.api import build_app

    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    email = f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=True))
    await session.flush()
    app = build_app(session)

    async def current():
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    app.dependency_overrides[get_ops_user] = current
    return app


async def _actions(session, shop_id) -> list[str]:
    rows = await session.execute(select(OpsAuditLog.action).where(OpsAuditLog.shop_id == shop_id))
    return sorted(rows.scalars())


async def test_an_operator_adds_a_contract_shop_and_enables_consent_once(session, monkeypatch):
    from tests.support.api import client_for

    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        made = await client.post(
            "/v1/ops/contract-shops",
            json={"shop_name": "Synthetic contract shop", "shopee_shop_id": "123456"},
        )
        assert made.status_code == 201, made.text
        shop_id = made.json()["shop"]["id"]
        before = await client.get(f"/v1/ops/shops/{shop_id}/consent")
        first = await client.post(f"/v1/ops/shops/{shop_id}/consent")
        second = await client.post(f"/v1/ops/shops/{shop_id}/consent")
    app.dependency_overrides.clear()

    shop = await session.get(Shop, uuid.UUID(shop_id))
    assert shop is not None and shop.platform == "shopee" and shop.shopee_shop_id == "123456"
    owner = await session.get(User, shop.user_id)
    assert owner is not None
    assert owner.email is None and owner.phone is None and owner.terms_accepted_at is None
    assert owner.staff_access_consent_at is not None

    assert before.json() == {
        "scopes": dict.fromkeys(TERMS_SCOPES, False),
        "enabled": False,
        "contract_client": True,
    }
    assert first.status_code == 200, first.text
    assert first.json()["enabled"] is True
    assert first.json()["granted"] == list(TERMS_SCOPES)
    assert second.json()["granted"] == []

    grants = (
        (await session.execute(select(DataUseConsent).where(DataUseConsent.shop_id == shop.id)))
        .scalars()
        .all()
    )
    assert sorted(g.scope for g in grants) == sorted(TERMS_SCOPES)
    assert {g.method for g in grants} == {"contract_paper"}
    assert all(g.evidence_ref.startswith("ops_contract_consent_enable:") for g in grants)
    assert "pooled_training" not in {g.scope for g in grants}
    assert await has_consent(session, shop.id, "service")
    assert await _actions(session, shop.id) == ["consent_enable", "contract_shop_create"]


async def test_ops_never_enables_consent_for_a_seller_shop(session, monkeypatch):
    from tests.support.api import client_for

    seller = await make_user(session, email="seller@example.com")
    shop_id = (await make_shop(session, seller)).id
    await session.commit()
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        state = await client.get(f"/v1/ops/shops/{shop_id}/consent")
        refused = await client.post(f"/v1/ops/shops/{shop_id}/consent")
    app.dependency_overrides.clear()
    assert state.json()["contract_client"] is False
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "not_a_contract_shop"
    assert not await has_consent(session, shop_id, "service")


async def test_a_viewer_can_read_but_not_add_or_enable(session, monkeypatch):
    from tests.support.api import client_for

    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        added = await client.post("/v1/ops/contract-shops", json={"shop_name": "Nope"})
    app.dependency_overrides.clear()
    assert added.status_code == 403


async def test_a_bad_shop_id_or_a_taken_one_is_refused(session, monkeypatch):
    from tests.support.api import client_for

    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        bad = await client.post(
            "/v1/ops/contract-shops", json={"shop_name": "Shop", "shopee_shop_id": "abc"}
        )
        first = await client.post(
            "/v1/ops/contract-shops", json={"shop_name": "Shop A", "shopee_shop_id": "777"}
        )
        taken = await client.post(
            "/v1/ops/contract-shops", json={"shop_name": "Shop B", "shopee_shop_id": "777"}
        )
    app.dependency_overrides.clear()
    assert bad.status_code == 422
    assert first.status_code == 201
    assert taken.status_code == 409
