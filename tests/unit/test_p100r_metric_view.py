"""P100 redesign (board B): the metric view of Phân tích and its KOL section.

Pure arithmetic on a synthetic funnel (two windows), the card counts, the KOL section's previous
period, then the seller and Ops routes. Synthetic only.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from juli_backend.services.shopee_analytics import kol, metric_view
from juli_backend.services.shopee_analytics.funnel import FunnelRows, ScopeDay, SourceDay
from juli_backend.services.shopee_analytics.metric_view import Cell, impact_of, value_of
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_recommendations.refs import CardRef
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_analytics import CUR_END, seed_shopee_shop

D = Decimal
NOW_W = Window(date(2026, 10, 2), date(2026, 10, 2))
OLD_W = Window(date(2026, 10, 1), date(2026, 10, 1))


def _rows(window, *, card_views, card_orders, card_gmv, a_orders):
    day = window.start
    srcs = [
        SourceDay(
            day,
            None,
            "the_san_pham_khac",
            card_views,
            100,
            card_orders,
            D(card_gmv),
            D(0),
            ads_views=200,
            ads_clicks=20,
            ads_orders=10,
            ads_gmv=D(1_000_000),
            ads_spend=D(100_000),
        ),  # fmt: skip
        SourceDay(day, None, "lien_ket", None, 50, 5, D(500_000), D(0)),
        SourceDay(
            day,
            "A",
            "the_san_pham_khac",
            card_views,
            100,
            a_orders,
            D(card_gmv),
            D(0),
            ads_views=0,
            ads_clicks=0,
            ads_orders=0,
            ads_gmv=D(0),
            ads_spend=D(0),
        ),  # fmt: skip
    ]
    shop = (ScopeDay(day, None, card_orders + 5, D(card_gmv + 500_000), D(0)),)
    prods = (ScopeDay(day, "A", a_orders, D(card_gmv), D(0), views=card_views, clicks=100),)
    return FunnelRows(window, tuple(srcs), shop, prods)


def _ref(kpi, products=("A",), flow=None, family="listing"):
    return CardRef("c", family, "t", None, 1, tuple(products), None, kpi, flow, None)


def test_value_and_impact_follow_views_ctr_ctor_aov():
    before = Cell(D(1000), D(100), D(10), D(1_000_000))  # aov 100k, ctr .1, ctor .1
    now = Cell(D(1000), D(80), D(8), D(800_000))
    assert value_of(now, "ctr") == D("0.08") and value_of(now, "aov") == D(100_000)
    # CTR fell 0.02: x views 1000 x ctor_before .1 x aov_before 100k
    assert impact_of("ctr", now, before) == D("-0.02") * 1000 * D("0.1") * 100_000
    assert impact_of("gmv", now, before) == D(-200_000)
    assert impact_of("orders", now, before) == D(-2) * 100_000
    assert impact_of("aov", now, before) == D(0)
    assert impact_of("views", now, before) == D(0)
    assert impact_of("ctor", now, before) == D(0)  # 8/80 == 10/100
    assert impact_of("ctr", Cell(None, None, None, None), before) is None


def test_card_counts_use_the_metric_of_each_card():
    refs = [_ref("ctr"), _ref("bien", ("B",)), _ref("roas", ("A", "B"), family="ads"), _ref("sale")]
    by_product, _ = metric_view.card_counts(refs, "gmv")
    assert by_product == {"A": 1, "B": 1}
    by_product, by_channel = metric_view.card_counts(refs, "margin")
    assert by_product == {"B": 1} and by_channel == {}
    by_product, by_channel = metric_view.card_counts([_ref("ads_gmv", family="ads")], "gmv")
    assert by_channel == {"ads_product": 1}


def _assemble(metric, **kw):
    now = _rows(NOW_W, card_views=2000, card_orders=40, card_gmv=4_000_000, a_orders=20)
    before = _rows(OLD_W, card_views=2000, card_orders=50, card_gmv=5_000_000, a_orders=25)
    return metric_view.assemble(
        metric,
        now=now,
        before=before,
        shop_key="s",
        ad_types_now={"ads_shop": {"gmv": D(300), "orders": D(2), "spend": D(1)}},
        ad_types_before=None,
        item_ids=["A"],
        names={"A": "Sản phẩm A"},
        margin_now={"A": D("0.18")},
        margin_before={"A": D("0.20")},
        **kw,
    )


def test_gmv_view_by_channel_and_product():
    out = _assemble("gmv", refs=[_ref("gmv")])
    assert out["days"] == 1 and out["metric"] == "gmv"
    ch = {c["key"]: c for c in out["channels"]}
    assert list(ch) == [
        "the_san_pham",
        "trang_shop",
        "video",
        "live",
        "ads_product",
        "ads_shop",
        "lien_ket",
    ]
    # Thẻ sản phẩm is organic: the source minus the "trong đó Quảng cáo" overlay
    assert ch["the_san_pham"]["now"] == 3_000_000 and ch["the_san_pham"]["prev"] == 4_000_000
    assert ch["the_san_pham"]["change"] == -0.25 and ch["the_san_pham"]["impact"] == -1_000_000
    assert ch["ads_shop"]["now"] == 300 and ch["ads_shop"]["ad_base"] == "ads_report"
    assert ch["ads_shop"]["prev"] is None  # no ads report before
    assert ch["trang_shop"]["now"] == 0
    assert out["total"]["now"] == 4_500_000 and out["total"]["prev"] == 5_500_000
    p = out["products"][0]
    assert p["product_id"] == "A" and p["name"] == "Sản phẩm A" and p["cards"] == 1
    assert p["now"] == 4_000_000 and p["change"] == -0.2 and p["impact"] == -1_000_000


def test_rates_stay_rates_and_affiliate_has_no_views():
    ctr = _assemble("ctr")
    aff = {c["key"]: c for c in ctr["channels"]}["lien_ket"]
    assert aff["now"] is None
    ctor = {c["key"]: c for c in _assemble("ctor")["channels"]}["lien_ket"]
    assert ctor["now"] == 0.1
    p = ctr["products"][0]
    assert p["now"] == 0.05 and p["prev"] == 0.05 and p["change"] == 0.0


def test_margin_is_a_product_figure_with_a_profit_gap():
    out = _assemble("margin")
    assert all(c["now"] is None for c in out["channels"])
    p = out["products"][0]
    assert p["now"] == 0.18 and p["prev"] == 0.2
    assert p["impact"] == pytest.approx(-0.02 * 4_000_000)


def test_channel_filter_restricts_the_product_cells_and_product_scope_the_channels():
    out = _assemble("gmv", channel="lien_ket")
    assert out["products"][0]["now"] == 0  # product A sells nothing through lien_ket
    one = _assemble("gmv", product_id="A")
    keys = [c["key"] for c in one["channels"]]
    assert "ads_shop" not in keys and "ads_product" in keys


def test_unknown_metric_is_refused():
    with pytest.raises(ValueError, match="metric"):
        _assemble("roas")


# -- KOL section ------------------------------------------------------------------------


def _krow(key, channel, item, gmv, net, clicks=10):
    r = kol.KolRow(key, f"@{key}", channel, item, f"SP {item}")
    r.orders = 2
    r.gmv = D(gmv)
    r.net_profit = D(net)
    r.commission = D(10)
    r.kol_clicks = D(clicks)
    r.order_ids = {f"{key}1", f"{key}2"}
    return r


def test_kol_section_totals_split_and_previous_change():
    now = SimpleNamespace(
        rows=[
            _krow("k1", "Shopee Video", "A", 1000, 100),
            _krow("k2", "Shopee Live", "A", 300, -5),
            _krow("k3", "Facebook", "B", 200, 10),
        ]
    )
    before = SimpleNamespace(rows=[_krow("k1", "Shopee Video", "A", 800, 50)])
    out = metric_view.assemble_kol(
        now,
        before,
        flow_totals={"clicks": D(100), "orders": D(10), "gmv": D(1500)},
        kol_card_counts={("k1", "A"): 2},
        days=30,
    )
    assert out["totals"] == {
        "clicks": 100,
        "orders": 10,
        "gmv": 1500,
        "video_gmv": 1000,
        "live_gmv": 300,
        "other_gmv": 200,
    }
    first = out["rows"][0]
    assert first["kol_key"] == "k1" and first["cards"] == 2 and first["change"] == 0.25
    assert first["prev_profit"] == 50 and first["profit"] == 100 and first["commission"] == 10
    assert out["rows"][1]["change"] is None and out["rows"][2]["cards"] == 0


# -- routes -----------------------------------------------------------------------------


async def test_the_seller_routes_answer(session):
    seeded = await seed_shopee_shop(session, rules=True)
    await session.commit()
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    params = {"period": "7d", "as_of": CUR_END.isoformat()}
    base = "/v1/demo/shopee"
    async with client_for(app) as client:
        res = await client.get(f"{base}/metric-view", params={**params, "metric": "gmv"})
        bad = await client.get(f"{base}/metric-view", params={**params, "metric": "roas"})
        kols = await client.get(f"{base}/kol-section", params=params)
    app.dependency_overrides.clear()
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["days"] == 7 and len(body["channels"]) == 7 and body["products"]
    assert bad.status_code == 422
    assert kols.status_code == 200, kols.text
    assert {"totals", "rows", "days"} <= set(kols.json())


async def test_the_ops_routes_mirror_the_seller_routes(session, monkeypatch):
    from tests.unit.test_ops_shopee_dashboards import _ops_client

    seeded = await seed_shopee_shop(session, rules=True)
    await session.commit()
    params = {"period": "7d", "as_of": CUR_END.isoformat()}
    app = await _ops_client(session, monkeypatch, "viewer")
    base = f"/v1/ops/shops/{seeded.shop_id}/shopee/analytics"
    async with client_for(app) as client:
        res = await client.get(f"{base}/metric-view", params={**params, "metric": "ctr"})
        kols = await client.get(f"{base}/kol-section", params=params)
    app.dependency_overrides.clear()
    assert res.status_code == 200 and res.json()["metric"] == "ctr"
    assert kols.status_code == 200
