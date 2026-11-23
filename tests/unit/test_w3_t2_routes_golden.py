"""W3 t2 (R-1, R-2, X-1): a TikTok shop that has layer-4 rows only answers every seller analytics
route, with the same number per metric on every endpoint.

The fixture is the synthetic shop of ``tests.support.shopee_analytics`` after the build: its raw
Shopee tables are emptied (the raw repositories read Shopee lines only, as they do for a TikTok
shop), the shop becomes a TikTok shop, and its shop rows are set to the four-source total of
decision #7 (the shop tab and the Shopee residual are not part of it). Every figure is invented.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import delete, update

from juli_backend.database import Shop
from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.shopee_metrics import ShopeeShopMetricsDaily, ShopeeSourceMetricsDaily
from juli_backend.models.shopee_profit import ShopeeOrderLine
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_analytics import seed_shopee_shop

DEMO = "/v1/demo/shopee"
PARAMS = {"period": "7d"}
ROUTES = (
    "overview",
    "matrix",
    "critical",
    "ranking",
    "products/1001",
    "kols",
    "kols/compare",
    "products/1001/kols",
    "channel-split",
    "channel-split/products",
    "metric-view",
    "kol-section",
)
IN_TOTAL = ("the_san_pham_khac", "video", "live", "lien_ket")


@pytest.fixture
async def tiktok(session):
    seeded = await seed_shopee_shop(session, rules=True)
    sid = seeded.shop_id
    await session.execute(delete(ShopeeOrderLine).where(ShopeeOrderLine.shop_id == sid))
    await session.execute(delete(PlatformDailyMetric).where(PlatformDailyMetric.shop_id == sid))
    await session.execute(
        delete(ShopeeSourceMetricsDaily).where(
            ShopeeSourceMetricsDaily.shop_id == sid,
            ShopeeSourceMetricsDaily.source == "chenh_lech_nguon",
        )
    )
    await session.execute(update(Shop).where(Shop.id == sid).values(platform="tiktok"))
    sources = (
        await session.execute(
            ShopeeSourceMetricsDaily.__table__.select().where(
                ShopeeSourceMetricsDaily.shop_id == sid,
                ShopeeSourceMetricsDaily.item_id.is_(None),
            )
        )
    ).all()
    per_day: dict[Any, tuple[int, int]] = {}
    for row in sources:
        if row.source in IN_TOTAL:
            gmv, orders = per_day.get(row.day, (0, 0))
            per_day[row.day] = (gmv + int(row.gmv), orders + int(row.orders))
    for day, (gmv, orders) in per_day.items():
        await session.execute(
            update(ShopeeShopMetricsDaily)
            .where(ShopeeShopMetricsDaily.shop_id == sid, ShopeeShopMetricsDaily.day == day)
            .values(gmv=gmv, orders=orders, aov=gmv / orders if orders else None)
        )
    await session.commit()
    await session.refresh(seeded.shop)
    return seeded


@pytest.fixture
async def client(session, tiktok):
    app = build_app(session)
    authenticate(app, user=tiktok.user, shop=tiktok.shop)
    async with client_for(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.parametrize("route", ROUTES)
async def test_every_analytics_route_answers_a_tiktok_shop_with_layer_4_rows(client, route):
    response = await client.get(f"{DEMO}/{route}", params=PARAMS)
    assert response.status_code == 200, (route, response.text[:300])
    body = response.json()
    if isinstance(body, dict) and "platform" in body:
        assert body["platform"] == "tiktok"


async def test_the_same_gmv_and_orders_on_every_endpoint(client):
    overview = (await client.get(f"{DEMO}/overview", params=PARAMS)).json()["shop_metrics"]
    split = (await client.get(f"{DEMO}/channel-split", params=PARAMS)).json()
    gmv_view = (await client.get(f"{DEMO}/metric-view", params={**PARAMS, "metric": "gmv"})).json()
    orders_view = (
        await client.get(f"{DEMO}/metric-view", params={**PARAMS, "metric": "orders"})
    ).json()
    rows = {r["key"]: r for r in split["rows"]}
    assert overview["gmv"] == split["kpis"]["gmv"] == gmv_view["total"]["now"]
    assert overview["orders"] == split["kpis"]["orders"] == orders_view["total"]["now"]
    # the four sources add up to the shop total; the shop tab is beside them (decision #7)
    assert rows["organic"]["gmv"] + rows["affiliate"]["gmv"] == overview["gmv"]
    assert rows["organic"]["orders"] + rows["affiliate"]["orders"] == overview["orders"]
    by_channel = {c["key"]: c["now"] for c in gmv_view["channels"]}
    assert by_channel["the_san_pham"] == rows["organic_card"]["gmv"]
    assert by_channel["video"] == rows["organic_video"]["gmv"]
    assert by_channel["lien_ket"] == rows["affiliate"]["gmv"]
    assert by_channel["trang_shop"] == rows["organic_shop"]["gmv"]


async def test_what_tiktok_lacks_is_none_with_a_reason_never_zero(client):
    split = (await client.get(f"{DEMO}/channel-split", params=PARAMS)).json()
    rows = {r["key"]: r for r in split["rows"]}
    assert rows["organic_shop"]["orders"] is None
    assert rows["organic_shop"]["unavailable"]["orders"] == "tab_reports_no_orders"
    assert rows["ads"]["gmv"] is None
    assert rows["ads"]["unavailable"]["gmv"] == "ads_scope_missing"
    orders_view = (
        await client.get(f"{DEMO}/metric-view", params={**PARAMS, "metric": "orders"})
    ).json()
    assert orders_view["unavailable"]["trang_shop"] == "tab_reports_no_orders"
    assert orders_view["unavailable"]["ads_product"] == "ads_scope_missing"
    ads = {c["key"]: c["now"] for c in orders_view["channels"]}
    assert ads["ads_product"] is None and ads["trang_shop"] is None


async def test_a_tiktok_shop_without_any_rows_is_409_no_tiktok_data(session):
    from tests.support.builders import make_shop, make_user

    user = await make_user(session)
    shop = await make_shop(session, user, platform="tiktok")
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    async with client_for(app) as c:
        response = await c.get(f"{DEMO}/channel-split")
    app.dependency_overrides.clear()
    assert response.status_code == 409 and response.json()["detail"]["code"] == "no_tiktok_data"
