"""``GET /v1/ingest/order-ref-key``: the Connector's affiliate reader gets its shop's order_ref key.

The key must equal the one the Ops order upload hands out for the same shop (otherwise the
affiliate lines cannot mark the order export's), must never be another shop's, and the route
is closed without a token and when the master key is missing.
"""

from __future__ import annotations

import uuid

import pytest

from juli_backend.services import ingest as ingest_service
from juli_backend.services.ingest import order_ref
from tests.support.api import build_app, client_for
from tests.support.shopee_reco import seed_reco_shop
from tests.unit.test_planned_changes import NOW

ROUTE = "/v1/ingest/order-ref-key"
MASTER = "synthetic-master-key-for-tests-only"


@pytest.fixture
def master(monkeypatch):
    monkeypatch.setenv(order_ref.ENV_MASTER, MASTER)


async def _headers(session, shop) -> dict[str, str]:
    created = await ingest_service.create_pairing_code(
        session, shop=shop.shop, user_id=shop.user.id, now=NOW
    )
    issued = await ingest_service.redeem_pairing_code(
        session, code=created.code, platform="shopee", platform_shop_id=str(uuid.uuid4().int)[:9],
        client_label="Juli Connector test", now=NOW,
    )  # fmt: skip
    await session.commit()
    return {"Authorization": f"Bearer {issued.token}"}


async def test_the_token_gets_its_own_shops_key_and_it_matches_the_ops_upload_key(session, master):
    mine = await seed_reco_shop(session)
    other = await seed_reco_shop(session)
    await session.commit()
    mine_headers = await _headers(session, mine)
    other_headers = await _headers(session, other)
    app = build_app(session)
    async with client_for(app) as client:
        r = await client.get(ROUTE, headers=mine_headers)
        r_other = await client.get(ROUTE, headers=other_headers)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    expected = order_ref.shop_key(MASTER.encode(), mine.shop_id).hex()
    assert body["order_ref_key"] == expected
    assert body["algorithm"] == "HMAC-SHA256" and body["key_version"] == order_ref.KEY_VERSION
    assert r_other.json()["order_ref_key"] != expected
    assert (
        r_other.json()["order_ref_key"] == order_ref.shop_key(MASTER.encode(), other.shop_id).hex()
    )


async def test_no_token_no_key(session, master):
    app = build_app(session)
    async with client_for(app) as client:
        assert (await client.get(ROUTE)).status_code == 401
        bad = await client.get(ROUTE, headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


async def test_a_missing_master_key_is_a_503_not_a_random_key(session, monkeypatch):
    monkeypatch.setenv(order_ref.ENV_MASTER, "short")
    shop = await seed_reco_shop(session)
    await session.commit()
    headers = await _headers(session, shop)
    app = build_app(session)
    async with client_for(app) as client:
        r = await client.get(ROUTE, headers=headers)
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "order_ref_key_not_configured"
