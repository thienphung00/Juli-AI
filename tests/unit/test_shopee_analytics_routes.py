"""P90 step 7: the Demo (seller scope) and Ops (viewer) routes of the Shopee read APIs.

The numbers are tested in ``test_shopee_analytics.py``; here the access rules, the parameter
validation, the status codes and what a response may and may not contain. Synthetic shop.
"""

from __future__ import annotations

import json
import uuid

import pytest

from juli_backend.services.shopee_analytics import queries
from tests.support.api import authenticate, build_app, client_for
from tests.support.builders import make_shop, make_user
from tests.support.shopee_analytics import CUR_END, Seeded, seed_shopee_shop, snapshot
from tests.unit.test_ops_shopee_dashboards import _ops_client

DEMO = "/v1/demo/shopee"
PARAMS = {"period": "7d", "as_of": CUR_END.isoformat()}
SCREENS = ("overview", "matrix", "critical", "ranking")


@pytest.fixture
async def seeded(session) -> Seeded:
    seeded = await seed_shopee_shop(session, rules=True)
    session.add(snapshot(seeded.shop_id, "1001"))
    await session.commit()
    return seeded


@pytest.fixture
async def seller(session, seeded):
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    async with client_for(app) as client:
        yield client
    app.dependency_overrides.clear()


def _no_leak(seeded: Seeded, text: str) -> None:
    for ref in seeded.order_refs:
        assert ref not in text
    for banned in ('"order_ref"', '"buyer', "recipient", '"address', '"phone', "•••"):
        assert banned not in text


# =========================================================================== seller scope


@pytest.mark.parametrize("screen", SCREENS)
async def test_a_seller_reads_every_screen_for_their_own_shopee_shop(seller, seeded, screen):
    response = await seller.get(f"{DEMO}/{screen}", params=PARAMS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["platform"] == "shopee"
    _no_leak(seeded, response.text)


async def test_the_overview_states_its_basis_its_ads_label_and_its_assumed_cost_share(
    seller, seeded
):
    body = (await seller.get(f"{DEMO}/overview", params=PARAMS)).json()
    assert body["order_basis"] == {"key": "confirmed", "label": "Đơn đã xác nhận"}
    assert body["period"]["window"] == {"from": "2026-10-01", "to": "2026-10-07", "days": 7}
    assert body["period"]["kind"] == "7d"
    assert body["ads"]["basis"]["label"] == "đơn đã đặt"
    assert body["profit"]["assumed_cost_share_pct"] is not None
    assert body["profit"]["cost_coverage"]["assumed_pct"] is not None
    assert body["flows"]["adds_up"] is True and body["levers"]["adds_up"] is True


async def test_the_default_window_ends_on_the_newest_day_the_shop_has_data_for(seller):
    body = (await seller.get(f"{DEMO}/overview")).json()
    assert body["period"]["window"]["to"] == "2026-10-07" and body["period"]["window"]["days"] == 30


async def test_month_and_custom_periods_resolve(seller):
    month = await seller.get(f"{DEMO}/overview", params={"period": "month", "month": "2026-10"})
    assert month.status_code == 200 and month.json()["period"]["window"]["from"] == "2026-10-01"
    custom = await seller.get(
        f"{DEMO}/overview", params={"period": "custom", "from": "2026-10-02", "to": "2026-10-04"}
    )
    assert custom.status_code == 200 and custom.json()["period"]["window"]["days"] == 3
    assert custom.json()["period"]["previous"]["to"] == "2026-10-01"


@pytest.mark.parametrize(
    "params",
    [
        {"period": "fortnight"},
        {"period": "month"},
        {"period": "month", "month": "2026-1"},
        {"period": "custom", "from": "2026-10-04"},
        {"period": "custom", "from": "2026-10-05", "to": "2026-10-01"},
        {"period": "custom", "from": "2020-01-01", "to": "2026-10-01"},
    ],
)
async def test_a_bad_period_is_422(seller, params):
    response = await seller.get(f"{DEMO}/overview", params=params)
    assert response.status_code == 422


async def test_the_ranking_takes_kind_source_and_xep_theo_and_refuses_politely(seller):
    ok = await seller.get(
        f"{DEMO}/ranking",
        params={**PARAMS, "kind": "products", "source": "lien_ket", "xep_theo": "orders"},
    )
    assert ok.status_code == 200 and ok.json()["adds_up"] is True
    refused = await seller.get(
        f"{DEMO}/ranking", params={**PARAMS, "source": "live", "xep_theo": "profit_per_day"}
    )
    assert refused.status_code == 200 and refused.json()["supported"] is False
    assert refused.json()["reason"] == "not_split_by_flow"
    assert (
        await seller.get(f"{DEMO}/ranking", params={**PARAMS, "kind": "orders"})
    ).status_code == 422


async def test_the_product_page_and_its_404(seller):
    page = await seller.get(f"{DEMO}/products/1001", params=PARAMS)
    assert page.status_code == 200
    body = page.json()
    assert body["header"]["product_id"] == "1001" and set(body["kpi_by_period"]) == {
        "7d",
        "30d",
        "90d",
    }
    assert (await seller.get(f"{DEMO}/products/9999", params=PARAMS)).status_code == 404
    assert (
        await seller.get(f"{DEMO}/products/1001", params={"period": "month"})
    ).status_code == 422


async def test_a_shop_that_is_not_on_shopee_is_refused_with_409(session):
    user = await make_user(session)
    shop = await make_shop(session, user, platform="tiktok")
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    async with client_for(app) as client:
        responses = [await client.get(f"{DEMO}/{s}") for s in SCREENS]
    app.dependency_overrides.clear()
    assert [r.status_code for r in responses] == [409] * 4
    assert responses[0].json()["detail"]["code"] == "not_a_shopee_shop"


async def test_a_shopee_shop_without_numbers_is_409_not_a_page_of_zeros(session):
    user = await make_user(session)
    shop = await make_shop(session, user, platform="shopee")
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    async with client_for(app) as client:
        response = await client.get(f"{DEMO}/overview")
    app.dependency_overrides.clear()
    assert response.status_code == 409 and response.json()["detail"]["code"] == "no_shopee_data"


async def test_a_seller_cannot_read_another_sellers_shop(session, seeded):
    # the active shop is whatever the dependency resolves for THIS user; a shop that is not the
    # caller's is rejected before the route runs. Here the resolved shop has no data of its own.
    stranger = await make_user(session)
    theirs = await make_shop(session, stranger, platform="shopee")
    app = build_app(session)
    authenticate(app, user=stranger, shop=theirs)
    async with client_for(app) as client:
        anchored = await client.get(f"{DEMO}/overview", params=PARAMS)
        unanchored = await client.get(f"{DEMO}/overview")
    app.dependency_overrides.clear()
    assert unanchored.status_code == 409  # nothing to anchor a window on
    body = anchored.json()  # an explicit day gives an empty page, never the seeded shop's rows
    assert anchored.status_code == 200 and body["gmv"]["line_orders"] == 0
    assert body["data"]["shop_totals"]["basis"] == "none" and body["flows"]["available"] is False


# =========================================================================== Ops viewer


async def test_an_ops_viewer_reads_the_same_payload_as_the_seller(
    session, monkeypatch, seeded, seller
):
    seller_body = (await seller.get(f"{DEMO}/overview", params=PARAMS)).json()
    app = await _ops_client(session, monkeypatch, "viewer")
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/analytics"
    async with client_for(app) as client:
        responses = {s: await client.get(f"{base}/{s}", params=PARAMS) for s in SCREENS}
        product = await client.get(f"{base}/products/1001", params=PARAMS)
    app.dependency_overrides.clear()
    assert all(r.status_code == 200 for r in responses.values()), {
        k: r.text[:200] for k, r in responses.items()
    }
    assert product.status_code == 200
    ops_body = responses["overview"].json()
    assert (
        ops_body["flows"] == seller_body["flows"]
        and ops_body["five_numbers"] == seller_body["five_numbers"]
    )
    # the masking layer must not blank a number: no key of the payloads looks like a buyer field
    _no_leak(seeded, json.dumps([r.json() for r in responses.values()] + [product.json()]))
    assert ops_body["profit"]["net_revenue"] is not None


async def test_ops_refuses_a_tiktok_shop_an_unknown_shop_and_a_stranger(session, monkeypatch):
    shop = await make_shop(session, await make_user(session), platform="tiktok")
    await session.commit()
    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        tiktok = await client.get(f"/v1/ops/shops/{shop.id}/shopee/analytics/overview")
        unknown = await client.get(f"/v1/ops/shops/{uuid.uuid4()}/shopee/analytics/overview")
    app.dependency_overrides.clear()
    assert tiktok.status_code == 409 and unknown.status_code == 404

    from juli_backend.core.security import get_current_user

    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    stranger = await make_user(session, email="nobody@example.com")
    outsider = build_app(session)
    outsider.dependency_overrides[get_current_user] = lambda: stranger
    async with client_for(outsider) as client:
        denied = await client.get(f"/v1/ops/shops/{shop.id}/shopee/analytics/overview")
    outsider.dependency_overrides.clear()
    assert denied.status_code in (401, 403)


async def test_ops_maps_the_services_refusals(session, monkeypatch, seeded):
    app = await _ops_client(session, monkeypatch, "viewer")
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/analytics"
    async with client_for(app) as client:
        bad = await client.get(
            f"{base}/overview",
            params={"period": "custom", "from": "2026-10-09", "to": "2026-10-01"},
        )
        missing = await client.get(f"{base}/products/9999", params=PARAMS)
    app.dependency_overrides.clear()
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_period"
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "product_not_found"


def test_the_service_exposes_no_write_path():
    names = {n for n in dir(queries) if not n.startswith("_")}
    assert not {n for n in names if n.startswith(("set_", "save_", "write_", "delete_", "upsert"))}
