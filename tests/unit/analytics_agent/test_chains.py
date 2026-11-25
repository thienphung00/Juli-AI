"""E3: chains on SYNTHETIC fixtures."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from juli_backend.services.analytics_agent import chains
from juli_backend.services.analytics_agent.labels import shopee_labels
from tests.unit.analytics_agent.fakes import (
    AS_OF,
    FakeData,
    funnel_data,
    noisy_orders,
    shop_rows,
    source_rows,
)

PRESET = "last_7d_vs_prev_7d"


async def test_orders_explained_by_one_source_collapse() -> None:
    shop, srcs = funnel_data()
    r = await chains.run_chain(FakeData(shop, srcs), "orders_change", "orders", PRESET, AS_OF)
    assert r.stop_reason == "explained"
    assert (r.explained_share or 0) >= 0.7
    nodes = {f.level + ":" + f.node for f in r.findings}
    assert "formula:ctr" in nodes and "source:video" in nodes
    assert any(f.level == "time" for f in r.findings)  # start day found


async def test_headline_change_under_3pct_stops_without_drilling() -> None:
    shop, srcs = funnel_data(ctr_video_before=0.10, ctr_video_after=0.0995)
    d = FakeData(shop, srcs)
    r = await chains.run_chain(d, "orders_change", "orders", PRESET, AS_OF)
    assert r.stop_reason == "within_noise"
    assert "source_daily" not in d.calls


async def test_coverage_below_half_is_data_missing() -> None:
    shop = shop_rows(
        AS_OF - timedelta(days=40),
        AS_OF,
        orders=lambda d: None if d > AS_OF - timedelta(days=5) else 5.0,
    )
    r = await chains.run_chain(FakeData(shop), "orders_change", "orders", PRESET, AS_OF)
    assert r.stop_reason == "data_missing"


async def test_yesterday_not_complete_is_data_stale() -> None:
    shop = shop_rows(AS_OF - timedelta(days=40), AS_OF - timedelta(days=2), orders=5.0)
    r = await chains.run_chain(
        FakeData(shop), "orders_change", "orders", "yesterday_vs_same_weekday", AS_OF
    )
    assert r.stop_reason == "data_stale"


async def test_unknown_o_source_is_grouped_as_khac_never_raw() -> None:
    shop, srcs = funnel_data(other_source="o:777")
    r = await chains.run_chain(FakeData(shop, srcs), "orders_change", "orders", PRESET, AS_OF)
    j = r.json(shopee_labels())
    names = [f["node_vi"] for f in j["findings"]]
    assert "Khác" in names
    assert not any("o:" in n for n in names)


async def test_null_source_is_missing_not_zero() -> None:
    shop, srcs = funnel_data()
    last = AS_OF
    for r in srcs:  # trang shop: data before, NULL in the current window
        pass
    srcs += source_rows(
        AS_OF - timedelta(days=60),
        AS_OF - timedelta(days=7),
        "trang_shop",
        views=100,
        clicks=10,
        orders=1.0,
    )
    srcs += source_rows(AS_OF - timedelta(days=6), last, "trang_shop")
    r = await chains.run_chain(FakeData(shop, srcs), "orders_change", "orders", PRESET, AS_OF)
    miss = [f for f in r.findings if f.node == "trang_shop"]
    assert miss and "no_data_in_current_window" in miss[0].flags


async def test_within_noise_is_decided_at_the_bottom() -> None:
    inside = await chains.run_chain(
        FakeData(noisy_orders((10.0, 9.0))), "orders_change", "orders", PRESET, AS_OF
    )
    assert inside.stop_reason == "within_noise"  # < 70 % explained, inside band, no Poisson
    assert inside.noise and inside.noise["in_band"] is True and inside.noise["significant"] is False
    outside = await chains.run_chain(
        FakeData(noisy_orders((10.0, 4.0))), "orders_change", "orders", PRESET, AS_OF
    )
    assert outside.stop_reason != "within_noise"
    assert outside.noise and outside.noise["in_band"] is False


async def test_bottom_up_fallback_explains_by_daily_outliers() -> None:
    base = noisy_orders((10.0, 10.0))
    for r in base:
        if r["day"] == AS_OF - timedelta(days=2):
            r["orders"] = 0.0
    r = await chains.run_chain(FakeData(base), "orders_change", "orders", PRESET, AS_OF)
    assert any(e["kind"] == "daily_outlier" for e in r.events)


async def test_yesterday_drills_against_latest_same_weekday_not_double_day() -> None:
    as_of = date(2026, 11, 18)  # Wed; 11/11 is a double day
    shop = shop_rows(
        as_of - timedelta(days=60),
        as_of,
        orders=lambda d: 3.0 if d == as_of else 10.0,
        views=1000,
        clicks=100,
    )
    r = await chains.run_chain(
        FakeData(
            shop,
            source_rows(
                as_of - timedelta(days=60), as_of, "video", views=1000, clicks=50, orders=5
            ),
        ),
        "orders_change",
        "orders",
        "yesterday_vs_same_weekday",
        as_of,
    )
    assert any("04/11" in s for s in r.steps)
    assert not any("drill-down compares with 11/11" in s for s in r.steps)


async def test_product_scope_reads_the_product() -> None:
    shop, srcs = funnel_data()
    d = FakeData(shop, srcs, names={"p1": "Sản phẩm A"})
    r = await chains.run_chain(d, "orders_change", "orders", PRESET, AS_OF, item_id="p1")
    assert r.item_id == "p1" and r.item_name == "Sản phẩm A" and "shop_daily:p1" in d.calls
    assert r.json(shopee_labels())["product"]["name"] == "Sản phẩm A"


def _ov(profit1: float, profit0: float, nr1: float, nr0: float):
    def f(a: date, b: date) -> dict:
        now = b >= AS_OF
        return {
            "shop_profit": {
                "profit": profit1 if now else profit0,
                "margin_pct": 100 * (profit1 / nr1 if now else profit0 / nr0),
                "net_revenue": nr1 if now else nr0,
                "gmv_share_pct": 95,
                "bridge": {
                    "product_profit": profit1 if now else profit0,
                    "ads_no_order_days": 0,
                    "other_marketing": 0,
                },
            },
            "shop_metrics": {},
        }

    return f


async def test_profit_chain_explained_by_bridge_and_margin_data_missing_on_low_coverage() -> None:
    shop = shop_rows(AS_OF - timedelta(days=40), AS_OF, orders=5.0)
    r = await chains.run_chain(
        FakeData(shop, overview=_ov(60.0, 100.0, 1000.0, 1000.0)),
        "profit_change",
        "profit",
        PRESET,
        AS_OF,
    )
    assert r.stop_reason == "explained"

    def low(a: date, b: date) -> dict:
        d = _ov(60.0, 100.0, 1000.0, 1000.0)(a, b)
        d["shop_profit"]["gmv_share_pct"] = 30
        return d

    m = await chains.run_chain(
        FakeData(shop, overview=low), "profit_change", "margin", PRESET, AS_OF
    )
    assert m.stop_reason == "data_missing"


def _costs(ads1: float, ads0: float, aff: float = 100.0, offers: float = 50.0):
    def f(a: date, b: date, item: str | None) -> dict:
        now = b >= AS_OF
        return {
            "net_revenue": 10_000.0 if item is None else None,
            "cost_ads": ads1 if now else ads0,
            "cost_affiliate": aff,
            "cost_offers": offers,
        }

    return f


async def test_cost_change_splits_by_line_product_and_start_day() -> None:
    first = AS_OF - timedelta(days=40)
    shop = shop_rows(
        first,
        AS_OF,
        orders=5.0,
        ads_spend=lambda d: 400.0 if d > AS_OF - timedelta(days=4) else 100.0,
    )
    prods = [
        {"day": d, "item_id": "p1", "gmv": 1000.0, "orders": 2.0, "units": 2.0}
        for d in shop_rows(first, AS_OF)
    ]
    prods = [
        {"day": r["day"], "item_id": "p1", "gmv": 1000.0, "orders": 2.0, "units": 2.0}
        for r in shop_rows(first, AS_OF)
    ]
    d = FakeData(shop, products=prods, names={"p1": "Sản phẩm A"}, costs=_costs(900.0, 300.0))
    r = await chains.run_chain(d, "cost_change", None, PRESET, AS_OF)
    assert r.metric == "cost_ratio" and r.stop_reason == "explained"
    head = r.findings[0]
    assert head.now == pytest.approx(1000 / 10000) and head.before == pytest.approx(400 / 10000)
    levels = {(f.level, f.node) for f in r.findings}
    assert ("line", "cost_ads") in levels and (
        "line",
        "cost_offers",
    ) in levels  # offers = its own line
    assert ("product", "Sản phẩm A") in levels
    assert any(f.level == "time" for f in r.findings)
    offers = next(f for f in r.findings if f.node == "cost_offers")
    assert "own_line" in offers.flags and offers.contribution_pct is None


async def test_cost_change_missing_cost_is_data_missing_and_small_change_within_noise() -> None:
    shop = shop_rows(AS_OF - timedelta(days=40), AS_OF, orders=5.0)

    def none_cost(a: date, b: date, item: str | None) -> dict:
        return {
            "net_revenue": 10_000.0,
            "cost_ads": None,
            "cost_affiliate": None,
            "cost_offers": 5.0,
        }

    assert (
        await chains.run_chain(FakeData(shop, costs=none_cost), "cost_change", None, PRESET, AS_OF)
    ).stop_reason == "data_missing"
    same = await chains.run_chain(
        FakeData(shop, costs=_costs(300.0, 300.0)), "cost_change", None, PRESET, AS_OF
    )
    assert same.stop_reason == "within_noise"


MV = {
    "total": {"impact": -100.0},
    "channels": [
        {"key": "video", "name": "Video", "impact": -60.0, "now": 5.0, "prev": 65.0},
        {"key": "live", "name": "LIVE", "impact": -2.0, "now": 1.0, "prev": 3.0},
    ],
    "products": [
        {"key": "p1", "name": "Sản phẩm A", "impact": -90.0, "now": 10.0, "prev": 100.0},
        {"key": "p2", "name": "Sản phẩm B", "impact": -5.0, "now": 1.0, "prev": 6.0},
    ],
}


async def test_metric_view_is_evidence_when_its_window_equals_ours() -> None:
    d = FakeData(noisy_orders((10.0, 4.0)), mv=MV)  # nothing else explains this drop
    r = await chains.run_chain(d, "orders_change", "orders", PRESET, AS_OF)
    assert "metric_view" in d.calls
    by = {(f.level, f.node): f for f in r.findings}
    assert by[("endpoint.product", "Sản phẩm A")].contribution_pct == pytest.approx(90.0)
    assert by[("endpoint.channel", "Video")].contribution_pct == pytest.approx(60.0)
    assert ("endpoint.product", "Sản phẩm B") not in by  # 5 % share: below the follow threshold
    assert by[("endpoint.product", "Sản phẩm A")].evidence_ref == "metric_view:orders:product:p1"
    assert r.stop_reason == "explained" and (r.explained_share or 0) >= 0.7


async def test_metric_view_is_skipped_when_the_comparison_window_differs() -> None:
    d = FakeData(noisy_orders((10.0, 4.0)), mv=MV)
    r = await chains.run_chain(d, "orders_change", "orders", "mtd_vs_same_days_last_month", AS_OF)
    assert "metric_view" not in d.calls
    assert any("comparison window differs" in s for s in r.steps)


async def test_metric_view_channel_without_data_is_flagged_not_counted() -> None:
    shop, srcs = funnel_data()
    srcs = [r for r in srcs if r["source"] != "video"] + source_rows(
        AS_OF - timedelta(days=60),
        AS_OF - timedelta(days=7),
        "video",
        views=400,
        clicks=40,
        orders=4.0,
    )
    shop2 = FakeData(shop, srcs, mv=MV)
    r = await chains.run_chain(shop2, "orders_change", "orders", PRESET, AS_OF)
    flagged = [f for f in r.findings if f.level == "endpoint.channel" and f.node == "video"]
    assert (
        flagged
        and "no_data_in_current_window" in flagged[0].flags
        and flagged[0].contribution_pct is None
    )


async def test_partial_coverage_uses_per_day_averages() -> None:
    first = AS_OF - timedelta(days=40)
    cur_first = AS_OF - timedelta(days=6)
    missing = {AS_OF - timedelta(days=1), AS_OF - timedelta(days=2)}  # 5 of 7 current days = 71 %

    def orders(d: date) -> float | None:
        if d in missing:
            return None
        return 10.0 if d >= cur_first else 20.0

    r = await chains.run_chain(
        FakeData(shop_rows(first, AS_OF, orders=orders)), "orders_change", "orders", PRESET, AS_OF
    )
    head = r.findings[0]
    assert "partial_coverage" in r.windows.flags
    assert head.now == pytest.approx(10.0) and head.before == pytest.approx(
        20.0
    )  # per-day, not 50 vs 140
    assert not any(f.startswith("poisson_z") for f in head.flags)  # counts are not comparable


async def test_coverage_80pct_or_more_uses_totals() -> None:
    first = AS_OF - timedelta(days=40)
    r = await chains.run_chain(
        FakeData(shop_rows(first, AS_OF, orders=lambda d: 10.0 if d > SPLIT_DAY else 20.0)),
        "orders_change",
        "orders",
        PRESET,
        AS_OF,
    )
    assert "partial_coverage" not in r.windows.flags
    assert r.findings[0].now == pytest.approx(70.0) and r.findings[0].before == pytest.approx(140.0)


SPLIT_DAY = AS_OF - timedelta(days=7)


async def _trang_shop_case(days_with_views: int) -> chains.ChainResult:
    shop, srcs = funnel_data()
    cur_first = AS_OF - timedelta(days=6)
    srcs += source_rows(
        AS_OF - timedelta(days=60),
        cur_first - timedelta(days=1),
        "trang_shop",
        views=100,
        clicks=10,
        orders=1.0,
    )
    for i in range(7):
        d = cur_first + timedelta(days=i)
        has = i < days_with_views
        srcs += source_rows(
            d,
            d,
            "trang_shop",
            views=100 if has else None,
            clicks=10 if has else None,
            orders=1.0 if has else None,
        )
    return await chains.run_chain(FakeData(shop, srcs), "orders_change", "orders", PRESET, AS_OF)


async def test_a_source_with_no_views_in_the_current_window_is_missing() -> None:
    low = await _trang_shop_case(0)  # no views in the current window: missing
    assert any(
        f.node == "trang_shop" and "no_data_in_current_window" in f.flags for f in low.findings
    )
    high = await _trang_shop_case(4)  # views reported in the current window: present
    assert not any(
        "no_data_in_current_window" in f.flags for f in high.findings if f.node == "trang_shop"
    )


def test_ratio_metrics_are_the_metric_registrys_not_a_second_formula() -> None:
    from decimal import Decimal

    from juli_backend.services.metrics.compute import raw_value

    rows = shop_rows(AS_OF - timedelta(days=9), AS_OF, gmv=700.0, orders=7.0, views=1000, clicks=70)
    a, b = AS_OF - timedelta(days=6), AS_OF
    for metric, comps in (
        ("ctr", {"clicks": 490, "views": 7000}),
        ("ctor", {"orders": 49, "clicks": 490}),
        ("aov", {"gmv": 4900, "orders": 49}),
    ):
        want = raw_value(metric, {k: Decimal(v) for k, v in comps.items()})
        assert chains.metric_value(rows, metric, a, b) == pytest.approx(float(want))
    nulls = shop_rows(AS_OF - timedelta(days=9), AS_OF, orders=7.0, views=None, clicks=70)
    assert chains.metric_value(nulls, "ctr", a, b) is None  # NULL is not 0
    zero = shop_rows(AS_OF - timedelta(days=9), AS_OF, orders=0.0, gmv=0.0)
    assert chains.metric_value(zero, "aov", a, b) is None  # zero denominator: no value


async def test_cost_change_reads_each_scope_once_as_a_window_pair() -> None:
    """The N+1: the shop and each of the top products used to be read once per window."""
    first = AS_OF - timedelta(days=40)
    shop = shop_rows(first, AS_OF, orders=5.0, ads_spend=100.0)
    prods = [
        {"day": r["day"], "item_id": f"p{i}", "gmv": 1000.0 * (i + 1), "orders": 1.0, "units": 1.0}
        for r in shop
        for i in range(7)
    ]
    d = FakeData(shop, products=prods, costs=_costs(900.0, 300.0))
    await chains.run_chain(d, "cost_change", None, PRESET, AS_OF)
    pairs = [c for c in d.calls if c.startswith("cost_pair:")]
    assert pairs[0] == "cost_pair:None" and len(pairs) == 1 + 5  # the shop + the top 5 products
