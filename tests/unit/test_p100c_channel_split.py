"""P100 S1 Tổng quan: the channel split (Organic / Quảng cáo / Tiếp thị liên kết).

Pure arithmetic on a synthetic funnel shaped like the ORY check (Organic = sources - the ads
overlay - affiliate; Trang shop pulled out of Thẻ sản phẩm), then the two routes. Synthetic only.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from juli_backend.services.shopee_analytics.channel_split import (
    kpis_of,
    split_rows,
    weakest_metric,
)
from juli_backend.services.shopee_analytics.funnel import FunnelRows, SourceDay, base_from_rows
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_builder.engine.contract import SOURCES
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_analytics import CUR_END, seed_shopee_shop

D = Decimal
DAY = date(2026, 10, 1)
W = Window(DAY, DAY)
DEMO = "/v1/demo/shopee/channel-split"


def _rows(**kw):
    """One day: card 10.88 tr, shop page 0.67, video 0.14, affiliate 1.20 (ads overlay on card)."""
    spec = {
        "the_san_pham_khac": (5000, 400, 70.0, 10_880_000),
        "trang_shop": (900, 105, 4.0, 670_000),
        "video": (300, 20, 1.0, 140_000),
        "lien_ket": (None, 100, 10.0, 1_200_000),
    }
    out = []
    for s in SOURCES:
        v, c, o, g = spec.get(s, (None, None, 0, 0))
        ads = (
            {
                "ads_views": 2000,
                "ads_clicks": 120,
                "ads_orders": 61,
                "ads_gmv": D(8_080_000),
                "ads_spend": D(2_570_000),
            }
            if s == "the_san_pham_khac" and not kw.get("no_ads")
            else {}
        )
        out.append(SourceDay(DAY, None, s, v, c, int(o), D(g), D(0), **ads))
    return FunnelRows(W, tuple(out))


_TYPES = {
    "ads_roas_custom": {"gmv": D(9_000_000), "orders": D(70), "spend": D(2_000_000)},
    "ads_shop": {"gmv": D(350_000), "orders": D(2), "spend": D(120_000)},
}


def _by_key(rows):
    return {r["key"]: r for r in rows}


def test_organic_is_sources_minus_ads_minus_affiliate_and_children_add_up():
    base = base_from_rows(_rows(), "s")
    r = _by_key(split_rows(base, ad_types=None))
    assert r["organic"]["gmv"] == 3_610_000 and r["organic"]["orders"] == 14
    kids = ("organic_card", "organic_shop", "organic_video", "organic_live")
    assert sum(r[k]["gmv"] for k in kids) == r["organic"]["gmv"]
    assert r["organic_shop"]["gmv"] == 670_000  # the shop_page segment
    assert r["organic_card"]["gmv"] == 10_880_000 - 8_080_000  # 2,80 tr: Video is its own child
    assert r["organic_video"]["gmv"] == 140_000 and r["organic_live"]["gmv"] == 0
    assert r["ads"]["gmv"] == 8_080_000 and r["ads"]["ad_base"] == "traffic_overview"
    assert r["organic"]["gmv"] + r["ads"]["gmv"] + r["affiliate"]["gmv"] == 12_890_000


def test_shares_of_the_three_channels_add_up_to_the_whole_on_the_traffic_base():
    r = _by_key(split_rows(base_from_rows(_rows(), "s"), ad_types=_TYPES))
    top = r["organic"]["share"] + r["ads"]["share"] + r["affiliate"]["share"]
    assert round(top, 4) == 1.0
    assert round(r["organic"]["share"], 3) == round(3_610_000 / 12_890_000, 3)
    assert r["organic_video"]["share"] == round(140_000 / 12_890_000, 6)
    assert r["ads_product"]["share"] is None and r["ads_shop"]["share"] is None  # other base


def test_roi_is_profit_over_the_total_cost_and_unknown_without_a_cost():
    k = kpis_of(D(12_890_000), D(85), D(2_700_000), D(500_000), D(0), D(0))
    assert k["cost_total"] == 500_000 and k["roi"] == 5.4
    k = kpis_of(D(1), D(1), D(100), D(200), D(100), D(300))
    assert k["cost_total"] == 600 and k["roi"] == round(100 / 600, 4)
    assert kpis_of(D(1), D(1), D(100), D(0), D(0), D(0))["roi"] is None
    unknown = kpis_of(D(1), D(1), D(100), None, None, None)
    assert unknown["cost_total"] is None and unknown["roi"] is None
    assert kpis_of(D(1), D(1), None, D(5), None, None)["roi"] is None


def test_affiliate_has_no_views_but_clicks_ctor_and_aov():
    r = _by_key(split_rows(base_from_rows(_rows(), "s")))["affiliate"]
    assert r["views"] is None and r["ctr"] is None
    assert r["clicks"] == 100 and r["ctor"] == 0.1 and r["aov"] == 120_000


def test_ads_report_children_use_their_own_base_and_are_never_summed_into_the_parent():
    types = {
        "ads_roas_custom": {"gmv": D(9_000_000), "orders": D(70), "spend": D(2_000_000)},
        "ads_auto_bid": {"gmv": D(1_030_000), "orders": D(4), "spend": D(450_000)},
        "ads_shop": {"gmv": D(350_000), "orders": D(2), "spend": D(120_000)},
    }
    r = _by_key(split_rows(base_from_rows(_rows(), "s"), ad_types=types))
    assert r["ads_product"]["gmv"] == 10_030_000 and r["ads_product"]["orders"] == 74
    assert r["ads_shop"]["gmv"] == 350_000 and r["ads_shop"]["ad_base"] == "ads_report"
    assert r["ads"]["gmv"] == 8_080_000  # the parent keeps the traffic-overview figure
    assert r["ads_product"]["views"] is None and r["ads_product"]["ctr"] is None


def test_without_an_ad_overlay_organic_is_unknown_never_the_whole_source():
    r = _by_key(split_rows(base_from_rows(_rows(no_ads=True), "s")))
    assert r["organic"]["gmv"] is None and r["ads"]["gmv"] is None


def test_product_level_has_no_shop_plus_row():
    rows = tuple(
        SourceDay(
            DAY,
            "A",
            "the_san_pham_khac",
            500,
            40,
            5,
            D(900_000),
            D(0),
            ads_gmv=D(300_000),
            ads_spend=D(50_000),
        )
        for _ in range(1)
    )
    base = base_from_rows(FunnelRows(W, rows), "s", item_ids=["A"])
    keys = [r["key"] for r in split_rows(base)]
    assert "ads_shop" not in keys and "ads_product" not in keys
    ads = _by_key(split_rows(base))["ads"]
    assert ads["ad_base"] == "ads_report" and ads["gmv"] == 300_000


def test_product_without_sources_takes_ads_and_affiliate_from_the_report_and_order_lines():
    from types import SimpleNamespace

    from juli_backend.services.shopee_analytics.channel_split import (
        _product_ads,
        _product_affiliate,
    )
    from juli_backend.services.shopee_profit.shop_profit import AdsFigures

    # the product's funnel rows carry no source breakdown: every GMV sits in the residual
    rows = (SourceDay(DAY, "A", "chenh_lech_nguon", None, None, 10, D(1_000_000), D(0)),)
    base = base_from_rows(FunnelRows(W, rows), "s", item_ids=["A"])

    def line(oid, aff):
        return SimpleNamespace(order_id=oid, product_id="A", affiliate=aff, order_value=D(100_000))

    view = SimpleNamespace(
        ads=SimpleNamespace(product_figures={"A": AdsFigures(D(50_000), D(300_000), D(0))}),
        pairs=[(line("o1", True), None), (line("o1", True), None), (line("o2", False), None)],
    )
    ads = _product_ads(view, "A", True)
    aff = _product_affiliate(view, "A")
    assert ads == {"gmv": 300_000} and aff == {"gmv": 200_000, "orders": 1}
    r = _by_key(split_rows(base, ads_known=True, ads_fallback=ads, affiliate_fallback=aff))
    assert r["ads"]["gmv"] == 300_000 and r["affiliate"]["gmv"] == 200_000
    assert r["organic"]["gmv"] == 500_000
    assert _product_ads(view, "A", False) is None  # no ad data at all stays unknown


def test_weakest_metric_is_the_one_furthest_below_the_shop_median():
    vals = {
        "a": {"views": 100.0, "ctr": 0.05, "ctor": 0.10, "aov": 100.0},
        "b": {"views": 100.0, "ctr": 0.05, "ctor": 0.10, "aov": 100.0},
        "c": {"views": 100.0, "ctr": 0.05, "ctor": 0.10, "aov": 100.0},
        "weak": {"views": 90.0, "ctr": 0.05, "ctor": 0.02, "aov": 100.0},
    }
    assert weakest_metric(vals, "weak") == "ctor"
    assert weakest_metric(vals, "a") is None


def test_weakest_metric_needs_enough_products_for_a_median():
    assert weakest_metric({"a": {"views": 1.0}, "b": {"views": 2.0}}, "a") is None


async def test_the_seller_route_answers_both_levels_and_the_picker(session):
    seeded = await seed_shopee_shop(session, rules=True)
    await session.commit()
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    params = {"period": "7d", "as_of": CUR_END.isoformat()}
    async with client_for(app) as client:
        shop = await client.get(DEMO, params=params)
        picker = await client.get(f"{DEMO}/products", params=params)
        pid = picker.json()["products"][0]["product_id"]
        prod = await client.get(DEMO, params={**params, "product_id": pid})
    app.dependency_overrides.clear()
    assert shop.status_code == 200, shop.text
    body = shop.json()
    assert body["level"] == "shop" and body["product_id"] is None
    assert [r["key"] for r in body["rows"]][:2] == ["organic", "organic_card"]
    assert set(body["kpis"]) == {
        "gmv", "orders", "profit", "cost_total", "cost_ads", "cost_affiliate", "cost_offers", "roi",
    }  # fmt: skip
    assert body["days"] == 7 and "kpis_prev" in body
    assert all("prev" in r and "share" in r for r in body["rows"])
    assert picker.status_code == 200 and picker.json()["products"]
    assert prod.status_code == 200, prod.text
    assert prod.json()["level"] == "product"
    assert "ads_shop" not in [r["key"] for r in prod.json()["rows"]]


async def test_the_ops_route_mirrors_the_seller_route(session, monkeypatch):
    from tests.unit.test_ops_shopee_dashboards import _ops_client

    seeded = await seed_shopee_shop(session, rules=True)
    await session.commit()
    params = {"period": "7d", "as_of": CUR_END.isoformat()}
    app = await _ops_client(session, monkeypatch, "viewer")
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/analytics/channel-split"
    async with client_for(app) as client:
        shop = await client.get(base, params=params)
        picker = await client.get(f"{base}/products", params=params)
    app.dependency_overrides.clear()
    assert shop.status_code == 200 and picker.status_code == 200
    assert shop.json()["level"] == "shop"


async def test_picker_margin_is_the_builders_one_scope_margin(session):
    """Step 1's product card shows the margin the builder result calls "hôm nay"."""
    from juli_backend.services.shopee_analytics import channel_split as cs
    from juli_backend.services.shopee_profit.shop_profit import scope_margin_pct

    seeded = await seed_shopee_shop(session, rules=True)
    await session.commit()
    out = await cs.channel_split_products(session, seeded.shop.id, period="7d", as_of=CUR_END)
    _ctx, view, _w = await cs._load(
        session, seeded.shop.id, period="7d", month=None, start=None, end=None, as_of=CUR_END
    )
    assert out["products"]
    for p in out["products"]:
        one = scope_margin_pct(view.profit, (p["product_id"],))
        assert p["margin"] == (None if one is None else float(one))
