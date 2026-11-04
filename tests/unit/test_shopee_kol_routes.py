"""P91 D-9: the KOL routes - Phân tích › KOL and the product's Tiếp thị liên kết tab.

Seller: ``/v1/demo/shopee/kols`` (+ ``/products/{id}/kols``); Ops viewer: the same under
``/v1/ops/shops/{id}/shopee/analytics``. Access rules, parameter validation, and what a response
may not hold. The numbers are in ``test_shopee_kol.py``. Synthetic shop and creators.
"""

from __future__ import annotations

import json
import uuid

import pytest

from tests.support.api import authenticate, build_app, client_for
from tests.support.builders import make_shop, make_user
from tests.support.shopee_reco import AS_OF
from tests.unit.test_ops_shopee_dashboards import _ops_client
from tests.unit.test_shopee_kol import ALPHA, BETA, _seed

DEMO = "/v1/demo/shopee"
PARAMS = {"as_of": AS_OF.isoformat()}


@pytest.fixture
async def seeded(session):
    return await _seed(session)


@pytest.fixture
async def seller(session, seeded):
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    async with client_for(app) as client:
        yield client
    app.dependency_overrides.clear()


def _clean(seeded, text: str) -> None:
    for ref in seeded.order_refs:
        assert ref not in text
    for banned in ('"order_ref"', '"buyer', "recipient", '"address', '"phone'):
        assert banned not in text


async def test_a_seller_reads_the_kol_table_with_filters_and_sort(seller, seeded):
    response = await seller.get(f"{DEMO}/kols", params=PARAMS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert {r["handle"] for r in body["rows"]} == {ALPHA, BETA}
    assert body["labels"]["roi_shopee"] == "ROI Shopee (chỉ hoa hồng)"
    assert body["labels"]["low_data_threshold"] == 10
    assert body["order_basis"]["key"] == "confirmed"
    _clean(seeded, response.text)
    fb = (await seller.get(f"{DEMO}/kols", params={**PARAMS, "channel": "Facebook"})).json()
    assert [r["handle"] for r in fb["rows"]] == [BETA]
    prod = (await seller.get(f"{DEMO}/kols", params={**PARAMS, "item_id": "1002"})).json()
    assert {r["item_id"] for r in prod["rows"]} == {"1002"}
    top = (await seller.get(f"{DEMO}/kols", params={**PARAMS, "sort": "orders", "limit": 1})).json()
    assert len(top["rows"]) == 1 and top["rows"][0]["orders"] == 12
    assert top["totals"]["orders"] == 17  # totals cover every filtered row, not only the page


@pytest.mark.parametrize(
    "params", [{"sort": "bogus"}, {"limit": 0}, {"period": "fortnight"}, {"item_id": "a b"}]
)
async def test_bad_parameters_are_422(seller, params):
    response = await seller.get(f"{DEMO}/kols", params={**PARAMS, **params})
    assert response.status_code == 422


async def test_the_product_tab_lists_the_products_kols_and_404_is_not_used_for_empty(
    seller, seeded
):
    tab = await seller.get(f"{DEMO}/products/1002/kols", params=PARAMS)
    assert tab.status_code == 200
    body = tab.json()
    assert {r["handle"] for r in body["rows"]} == {ALPHA, BETA}
    assert body["product"]["commission_rate"] == pytest.approx(0.10)
    _clean(seeded, tab.text)
    empty = await seller.get(f"{DEMO}/products/1003/kols", params=PARAMS)
    assert empty.status_code == 200 and empty.json()["rows"] == []


async def test_a_shop_not_on_shopee_or_without_numbers_is_refused(session):
    user = await make_user(session)
    tiktok = await make_shop(session, user, platform="tiktok")
    app = build_app(session)
    authenticate(app, user=user, shop=tiktok)
    async with client_for(app) as client:
        refused = await client.get(f"{DEMO}/kols")
    app.dependency_overrides.clear()
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "not_a_shopee_shop"
    other = await make_user(session)
    empty = await make_shop(session, other, platform="shopee")
    app = build_app(session)
    authenticate(app, user=other, shop=empty)
    async with client_for(app) as client:
        none = await client.get(f"{DEMO}/kols")
    app.dependency_overrides.clear()
    assert none.status_code == 409 and none.json()["detail"]["code"] == "no_shopee_data"


async def test_a_seller_never_reads_another_sellers_kols(session, seeded):
    stranger = await make_user(session)
    theirs = await make_shop(session, stranger, platform="shopee")
    app = build_app(session)
    authenticate(app, user=stranger, shop=theirs)
    async with client_for(app) as client:
        response = await client.get(f"{DEMO}/kols", params=PARAMS)
    app.dependency_overrides.clear()
    assert response.status_code == 200 and response.json()["rows"] == []


async def test_an_ops_viewer_reads_the_same_rows_and_nobody_else_does(
    session, monkeypatch, seeded, seller
):
    seller_body = (await seller.get(f"{DEMO}/kols", params=PARAMS)).json()
    app = await _ops_client(session, monkeypatch, "viewer")
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/analytics"
    async with client_for(app) as client:
        table = await client.get(f"{base}/kols", params=PARAMS)
        tab = await client.get(f"{base}/products/1002/kols", params=PARAMS)
        bad = await client.get(f"{base}/kols", params={**PARAMS, "sort": "bogus"})
        unknown = await client.get(f"/v1/ops/shops/{uuid.uuid4()}/shopee/analytics/kols")
    app.dependency_overrides.clear()
    assert table.status_code == 200 and tab.status_code == 200
    assert table.json()["rows"] == seller_body["rows"]
    assert table.json()["totals"] == seller_body["totals"]
    assert bad.status_code == 422 and unknown.status_code == 404
    _clean(seeded, json.dumps([table.json(), tab.json()]))


async def test_ops_refuses_a_stranger_and_a_tiktok_shop(session, monkeypatch):
    shop = await make_shop(session, await make_user(session), platform="tiktok")
    await session.commit()
    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        tiktok = await client.get(f"/v1/ops/shops/{shop.id}/shopee/analytics/kols")
    app.dependency_overrides.clear()
    assert tiktok.status_code == 409

    from juli_backend.core.security import get_current_user

    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    stranger = await make_user(session, email="nobody@example.com")
    outsider = build_app(session)
    outsider.dependency_overrides[get_current_user] = lambda: stranger
    async with client_for(outsider) as client:
        denied = await client.get(f"/v1/ops/shops/{shop.id}/shopee/analytics/kols")
    outsider.dependency_overrides.clear()
    assert denied.status_code in (401, 403)
