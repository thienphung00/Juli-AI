"""P90 step 2: the Ops order upload routes and the per-shop ``order_ref`` key.

Synthetic shops and lines only. Checks:

- the key: stable per shop, different between shops, never the master; the endpoint needs the
  operator role, is ``no-store``, is audited without the key, and answers 503 when no master
  key is configured; the masking layer leaves the key intact (it is hex, not a phone);
- the upload: PII-free lines land in ``shopee_order_lines`` through the gateway; a buyer field
  is refused with 422 and nothing is stored; a viewer and a TikTok shop are refused;
- the hash function is the same as the affiliate lane's.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from juli_backend.models.ops import OpsAuditLog
from juli_backend.models.shopee_profit import ShopeeOrderLine
from juli_backend.services.ingest import order_ref
from juli_backend.services.ops.masking import mask_pii
from scripts.shopee_exports import parse
from tests.support.consent import grant_service_consent
from tests.unit.test_ops_shopee_dashboards import _ops_client, _shop

MASTER = "synthetic-master-key-for-tests-only"


@pytest.fixture
def master(monkeypatch):
    monkeypatch.setenv(order_ref.ENV_MASTER, MASTER)


def _line(**over):
    base = {
        "order_ref": "a" * 32,
        "line_no": 0,
        "ordered_at": "2026-10-05T10:15:00",
        "status": "delivered",
        "sku": "SKU-A",
        "qty": 1,
        "original_price": 100000,
        "deal_price": 90000,
    }
    return {**base, **over}


# =========================================================================== the key


def test_the_shop_key_is_stable_per_shop_and_is_not_the_master():
    one, two = uuid.uuid4(), uuid.uuid4()
    master_key = MASTER.encode()
    assert order_ref.shop_key(master_key, one) == order_ref.shop_key(master_key, one)
    assert order_ref.shop_key(master_key, one) != order_ref.shop_key(master_key, two)
    assert order_ref.shop_key(master_key, one) != master_key
    assert order_ref.shop_key(b"another master key", one) != order_ref.shop_key(master_key, one)


def test_the_backend_hash_is_the_affiliate_lanes_hash():
    key = order_ref.shop_key(MASTER.encode(), uuid.uuid4())
    for order_id in ("2610AAAAAA0001", "  2610aaaaaa0001 ", "x"):
        assert order_ref.order_ref(order_id, key) == parse.order_ref(order_id, key)
    assert order_ref.order_ref("2610AAAAAA0001", b"key") == "45fc017608554811b91b3b4040801ee2"


def test_a_missing_or_short_master_is_unavailable(monkeypatch):
    monkeypatch.delenv(order_ref.ENV_MASTER, raising=False)
    with pytest.raises(order_ref.OrderRefKeyUnavailable):
        order_ref.master_key()
    monkeypatch.setenv(order_ref.ENV_MASTER, "short")
    with pytest.raises(order_ref.OrderRefKeyUnavailable):
        order_ref.master_key()


def test_the_masking_layer_leaves_a_hex_key_whole():
    key = "0123456789" * 6 + "0123"
    assert mask_pii({"order_ref_key": key})["order_ref_key"] == key


async def test_an_operator_gets_the_key_once_with_no_store_and_it_is_audited_without_it(
    session, monkeypatch, master
):
    shop_id = await _shop(session, "shopee")
    app = await _ops_client(session, monkeypatch, "operator")
    from tests.support.api import client_for

    async with client_for(app) as client:
        response = await client.get(f"/v1/ops/shops/{shop_id}/shopee/orders/ref-key")
    app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    expected = order_ref.shop_key(MASTER.encode(), shop_id).hex()
    assert body["order_ref_key"] == expected and body["order_ref_key"] != MASTER
    assert (body["algorithm"], body["key_version"]) == ("HMAC-SHA256", order_ref.KEY_VERSION)
    assert body["expires_at"].endswith("Z")
    rows = (await session.scalars(select(OpsAuditLog))).all()
    issued = [r for r in rows if r.action == "order_ref_key_issue"]
    assert len(issued) == 1 and issued[0].shop_id == shop_id
    assert expected not in json.dumps(issued[0].after) and MASTER not in json.dumps(issued[0].after)


async def test_the_key_endpoint_is_503_without_a_master_and_403_for_a_viewer(session, monkeypatch):
    from tests.support.api import client_for

    monkeypatch.delenv(order_ref.ENV_MASTER, raising=False)
    shop_id = await _shop(session, "shopee")
    operator_app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(operator_app) as client:
        unconfigured = await client.get(f"/v1/ops/shops/{shop_id}/shopee/orders/ref-key")
    operator_app.dependency_overrides.clear()
    assert unconfigured.status_code == 503
    assert unconfigured.json()["detail"]["code"] == "order_ref_key_not_configured"

    monkeypatch.setenv(order_ref.ENV_MASTER, MASTER)
    viewer_app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(viewer_app) as client:
        refused = await client.get(f"/v1/ops/shops/{shop_id}/shopee/orders/ref-key")
        upload = await client.post(
            f"/v1/ops/shops/{shop_id}/shopee/orders/upload", json={"lines": [_line()]}
        )
    viewer_app.dependency_overrides.clear()
    assert refused.status_code == 403 and upload.status_code == 403


# =========================================================================== the upload


async def test_pii_free_lines_land_in_the_order_line_table_and_the_upload_is_audited(
    session, monkeypatch
):
    from tests.support.api import client_for

    shop_id = await _shop(session, "shopee")
    await grant_service_consent(session, shop_id)
    await session.commit()
    app = await _ops_client(session, monkeypatch, "operator")
    lines = [_line(), _line(line_no=1, sku="SKU-B", status="cancelled")]
    async with client_for(app) as client:
        first = await client.post(
            f"/v1/ops/shops/{shop_id}/shopee/orders/upload", json={"lines": lines}
        )
        again = await client.post(
            f"/v1/ops/shops/{shop_id}/shopee/orders/upload", json={"lines": lines}
        )
    app.dependency_overrides.clear()
    assert first.status_code == 200, first.text
    assert first.json() == {"lines": 2, "duplicate": False}
    assert again.json() == {"lines": 2, "duplicate": True}
    stored = (await session.scalars(select(ShopeeOrderLine))).all()
    assert sorted((s.line_no, s.status, s.sku) for s in stored) == [
        (0, "delivered", "SKU-A"),
        (1, "cancelled", "SKU-B"),
    ]
    audit = [
        r for r in (await session.scalars(select(OpsAuditLog))).all() if r.action == "orders_upload"
    ]
    assert len(audit) == 2 and audit[0].after == {"lines": 2, "duplicate": False}


@pytest.mark.parametrize(
    "extra",
    [
        {"buyer_name": "CANARY-buyer"},
        {"phone": "CANARY-0909"},
        {"address": "CANARY-street"},
        {"tracking_id": "CANARY-SPX1"},
        {"note": "CANARY-note"},
    ],
)
async def test_a_buyer_field_is_refused_and_nothing_is_stored(session, monkeypatch, extra):
    from tests.support.api import client_for

    shop_id = await _shop(session, "shopee")
    await grant_service_consent(session, shop_id)
    await session.commit()
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        refused = await client.post(
            f"/v1/ops/shops/{shop_id}/shopee/orders/upload", json={"lines": [_line(**extra)]}
        )
    app.dependency_overrides.clear()
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "invalid_rows"
    assert "CANARY" not in refused.text
    assert (await session.scalars(select(ShopeeOrderLine))).all() == []


async def test_a_tiktok_shop_and_a_shop_without_consent_are_refused(session, monkeypatch):
    from tests.support.api import client_for

    tiktok = await _shop(session, "tiktok")
    shopee = await _shop(session, "shopee")
    app = await _ops_client(session, monkeypatch, "operator")
    async with client_for(app) as client:
        wrong = await client.post(
            f"/v1/ops/shops/{tiktok}/shopee/orders/upload", json={"lines": [_line()]}
        )
        no_consent = await client.post(
            f"/v1/ops/shops/{shopee}/shopee/orders/upload", json={"lines": [_line()]}
        )
        empty = await client.post(
            f"/v1/ops/shops/{shopee}/shopee/orders/upload", json={"lines": []}
        )
        bad_day = await client.post(
            f"/v1/ops/shops/{shopee}/shopee/orders/upload",
            json={"lines": [_line(ordered_at="not a date")]},
        )
    app.dependency_overrides.clear()
    assert wrong.status_code == 409
    assert (
        no_consent.status_code == 403 and no_consent.json()["detail"]["code"] == "consent_required"
    )
    assert empty.status_code == 422 and bad_day.status_code == 422
