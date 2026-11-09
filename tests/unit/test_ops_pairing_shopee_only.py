"""P97 T1: a Connector pairing code is Shopee-only, and the shop is read in its own scope.

Synthetic fixtures only.
"""

from __future__ import annotations

from juli_backend.services.consent import grant_consent
from tests.support.builders import make_shop, make_user
from tests.unit.test_ops_contract_shops import _ops_client


async def _shop_with_consent(session, *, platform: str):
    seller = await make_user(session, email=f"seller-{platform}-p97@example.com")
    shop = await make_shop(
        session, seller, platform=platform, tiktok_shop_id=None if platform == "shopee" else "t-1"
    )
    await grant_consent(
        session,
        shop.id,
        scope="service",
        method="in_app_click",
        terms_version="test",
        evidence_ref="test",
        granted_by=str(seller.id),
    )
    await session.commit()
    return shop.id


async def test_a_tiktok_shop_is_refused_a_connector_code(session, monkeypatch):
    from tests.support.api import client_for

    shop_id = await _shop_with_consent(session, platform="tiktok")
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        issued = await client.post(f"/v1/ops/shops/{shop_id}/pairing-codes")
    app.dependency_overrides.clear()
    assert issued.status_code == 409
    assert issued.json()["detail"]["code"] == "not_a_shopee_shop"


async def test_a_seller_owned_shopee_shop_with_consent_gets_a_code(session, monkeypatch):
    from tests.support.api import client_for

    shop_id = await _shop_with_consent(session, platform="shopee")
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        issued = await client.post(f"/v1/ops/shops/{shop_id}/pairing-codes")
    app.dependency_overrides.clear()
    assert issued.status_code == 201, issued.text
