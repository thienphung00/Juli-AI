"""Juli Ops shop connection (contract shops removed).

- ``POST /v1/ops/contract-shops`` answers 410. Ops no longer creates a login-less shop.
- "Bật" still grants consent only for a shop with no seller login (409 otherwise).
- "Tạo mã kết nối" and the token list work for every shop once service consent is on.

Synthetic fixtures only.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from juli_backend.models.ops import OpsAuditLog
from juli_backend.services.consent import has_consent
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


async def test_adding_a_contract_shop_is_gone(session, monkeypatch):
    from tests.support.api import client_for

    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        made = await client.post(
            "/v1/ops/contract-shops",
            json={"shop_name": "Synthetic contract shop", "shopee_shop_id": "123456"},
        )
    app.dependency_overrides.clear()
    assert made.status_code == 410
    assert made.json()["detail"]["code"] == "contract_shop_removed"


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


async def test_a_viewer_cannot_add_a_contract_shop(session, monkeypatch):
    from tests.support.api import client_for

    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        added = await client.post("/v1/ops/contract-shops", json={"shop_name": "Nope"})
    app.dependency_overrides.clear()
    assert added.status_code == 403


async def test_a_pairing_code_comes_after_consent_and_its_token_can_be_revoked(
    session, monkeypatch
):
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.repositories import utc_now_naive
    from juli_backend.services import ingest as ingest_service
    from juli_backend.services.consent import grant_consent
    from tests.support.api import client_for

    seller = await make_user(session, email="connector@example.com")
    shop = await make_shop(session, seller, platform="shopee", tiktok_shop_id=None)
    shop_id = str(shop.id)
    async with with_shop_scope(session, shop.id):
        await grant_consent(
            session,
            shop.id,
            scope="service",
            method="in_app_click",
            terms_version="test",
            evidence_ref="test",
            granted_by="seller",
            granted_at=utc_now_naive(),
        )
    await session.commit()
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        issued = await client.post(f"/v1/ops/shops/{shop_id}/pairing-codes")
        assert issued.status_code == 201, issued.text
        code = issued.json()["code"]
        token = await ingest_service.redeem_pairing_code(
            session,
            code=code,
            platform=shop.platform,
            platform_shop_id=None,
            client_label="loader",
            now=utc_now_naive(),
        )
        await session.commit()
        listed = await client.get(f"/v1/ops/shops/{shop_id}/ingest-tokens")
        revoked = await client.delete(f"/v1/ops/shops/{shop_id}/ingest-tokens/{token.token_id}")
        after = await client.get(f"/v1/ops/shops/{shop_id}/ingest-tokens")
    app.dependency_overrides.clear()

    assert issued.json()["ttl_seconds"] == 600 and len(code.replace("-", "")) == 10
    assert [t["active"] for t in listed.json()["data"]] == [True]
    assert "token" not in listed.json()["data"][0]
    assert revoked.status_code == 204
    assert [t["active"] for t in after.json()["data"]] == [False]
    actions = await _actions(session, uuid.UUID(shop_id))
    assert "pairing_code_create" in actions and "ingest_token_revoke" in actions
    # The audit row never carries the code itself.
    rows = await session.execute(
        select(OpsAuditLog.after).where(OpsAuditLog.action == "pairing_code_create")
    )
    assert all(code not in str(row) for row in rows.scalars())


async def test_a_seller_shop_lists_connections_before_it_has_any(session, monkeypatch):
    from tests.support.api import client_for

    seller = await make_user(session, email="seller2@example.com")
    shop_id = (await make_shop(session, seller, platform="shopee", tiktok_shop_id=None)).id
    await session.commit()
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        code = await client.post(f"/v1/ops/shops/{shop_id}/pairing-codes")
        tokens = await client.get(f"/v1/ops/shops/{shop_id}/ingest-tokens")
    app.dependency_overrides.clear()
    assert code.status_code == 409
    assert code.json()["detail"]["code"] == "consent_required"
    assert tokens.status_code == 200
    assert tokens.json()["data"] == []
