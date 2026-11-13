"""P98 / ADR-122 d.11.1: the funnel engine proves the funnel identity in every column."""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal as D

import pytest

from juli_backend.services.shopee_builder.engine.contract import (
    SOURCES,
    WIRE_KEYS,
    AddedTraffic,
    Band,
    DriverEffect,
    FunnelBase,
    OfferCost,
    OptionInput,
    SourceFunnel,
)
from juli_backend.services.shopee_builder.engine.engine import compare, run


def band(a: float, b: float, c: float) -> Band:
    return Band(D(str(a)), D(str(b)), D(str(c)))


def src(key, views, clicks, orders, gmv, profit):
    return SourceFunnel(
        key,
        None if views is None else D(views),
        None if clicks is None else D(clicks),
        D(orders),
        D(gmv),
        None if profit is None else D(profit),
    )


def simple_base(profit=True, cr="0.3"):
    return FunnelBase(
        "shop-1",
        "shop",
        (),
        date(2026, 10, 1),
        date(2026, 10, 30),
        (
            src("the_san_pham_khac", 100000, 5000, 200, 20_000_000, 4_000_000 if profit else None),
            src("trang_shop", 20000, 1000, 50, 5_000_000, 1_000_000 if profit else None),
        ),
        D(cr) if profit else None,
    )


def voucher_option(days=14):
    return OptionInput(
        "voucher",
        "Voucher đơn tối thiểu",
        (
            DriverEffect(
                "aov", ("the_san_pham_khac", "trang_shop"), "prior", lift=band(0.0, 0.03, 0.06)
            ),
            DriverEffect(
                "ctor", ("the_san_pham_khac", "trang_shop"), "prior", lift=band(0.0, 0.02, 0.05)
            ),
        ),
        days,
        offers=(OfferCost(D(5000), band(0.1, 0.2, 0.3), None, "voucher"),),
    )


# -- readable examples ---------------------------------------------------------------------------


def test_voucher_like_example():
    r = run(simple_base(), voucher_option(), n=800)
    assert r.estimable and r.basis == "prior"
    assert r.likely and r.low and r.high
    j = r.json()
    assert j["basis_weak"] is True
    assert j["after"]["label"] == "Sau 14 ngày"
    assert j["delta"]["orders"]["value"] > 0
    assert (
        j["delta"]["profit"]["low"] <= j["delta"]["profit"]["value"] <= j["delta"]["profit"]["high"]
    )
    assert any("voucher" in p["text"] for p in j["build_up"])
    assert len(j["build_up"]) <= 3
    # before = base scaled to 14 days
    assert r.before.orders == pytest.approx(D(250) * 14 / 30, rel=D("1e-9"))


def test_ads_like_example():
    opt = OptionInput(
        "ads_new",
        "Quảng cáo mới",
        (
            DriverEffect(
                "views",
                ("the_san_pham_khac",),
                "measured",
                added=AddedTraffic(
                    band(8000, 10000, 12000),
                    D("0.04"),
                    D("0.05"),
                    D(100000),
                    band(0.3, 0.5, 0.7),
                    D(20000),
                ),
            ),
        ),
        None,
        fixed_cost=D(500_000),
    )
    r = run(simple_base(), opt, n=800)
    j = r.json()
    assert j["horizon"] == "first_30_days" and j["after"]["label"] == "30 ngày đầu"
    # 10000 views x 4 % x 5 % x 50 % = 10 extra orders x 20.000đ - 500.000đ
    assert j["delta"]["orders"]["value"] == pytest.approx(10, rel=0.15)
    assert j["delta"]["profit"]["value"] == pytest.approx(10 * 20000 - 500_000, abs=60_000)
    assert j["cost"]["total"] == 500_000
    assert j["cost"]["break_even_orders"] == 25


def test_aov_only_has_zero_delta_orders_and_note():
    opt = OptionInput(
        "bundle",
        "Bộ",
        (DriverEffect("aov", ("trang_shop",), "shop", lift=band(0.01, 0.02, 0.03)),),
        30,
    )
    r = run(simple_base(), opt, n=300)
    j = r.json()
    assert j["delta"]["orders"]["value"] == 0
    assert j["delta"]["orders"]["note"] == "Đòn bẩy này tăng giá trị mỗi đơn, không tăng số đơn."
    assert j["delta"]["gmv"]["value"] > 0


def test_not_estimable_keeps_cost_and_break_even():
    opt = OptionInput(
        "ads_new",
        "Ads",
        (
            DriverEffect(
                "views",
                ("the_san_pham_khac",),
                "not_estimable",
                note="chưa ước tính được — cần chạy thử",
            ),
        ),
        7,
        fixed_cost=D(700_000),
    )
    r = run(simple_base(), opt, n=100)
    j = r.json()
    assert not r.estimable and r.low is None and r.likely is None and r.high is None
    assert j["delta"]["profit"] is None and j["per_30d"]["profit"] is None
    assert j["cost"]["total"] == 700_000
    assert j["cost"]["break_even_orders"] == 700_000 / (5_000_000 / 250)  # 35
    assert j["delta"]["orders"]["note"] == "chưa ước tính được — cần chạy thử"


def test_missing_traffic_makes_view_driver_not_estimable():
    base = FunnelBase(
        "s",
        "shop",
        (),
        date(2026, 10, 1),
        date(2026, 10, 30),
        (src("the_san_pham_khac", None, None, 10, 1_000_000, 100_000),),
        D("0.2"),
    )
    opt = OptionInput(
        "t", "t", (DriverEffect("ctr", ("the_san_pham_khac",), "shop", lift=band(0, 0.1, 0.2)),), 30
    )
    r = run(base, opt, n=50)
    assert not r.estimable and r.notes


def test_profit_unknown_when_cost_missing_keeps_gmv_and_orders():
    r = run(simple_base(profit=False), voucher_option(), n=200)
    j = r.json()
    assert j["delta"]["profit"] is None and j["build_up"] == []
    assert j["delta"]["gmv"]["value"] is not None and j["delta"]["orders"]["value"] is not None


def test_use_cap_limits_offer_cost():
    opt = OptionInput(
        "voucher",
        "v",
        (DriverEffect("ctor", ("trang_shop",), "prior", lift=band(0, 0.1, 0.2)),),
        30,
        offers=(OfferCost(D(1000), band(0.9, 0.9, 0.9), D(10), "voucher"),),
    )
    r = run(simple_base(), opt, n=100)
    assert r.cost_total == 10_000


def test_compare_sorts_by_per_30d_profit_none_last():
    good = run(simple_base(), voucher_option(30), n=200)
    bad = run(simple_base(profit=False), voucher_option(30), n=200)
    best = run(
        simple_base(),
        OptionInput(
            "x",
            "x",
            (DriverEffect("ctor", ("the_san_pham_khac",), "shop", lift=band(0.2, 0.3, 0.4)),),
            30,
        ),
        n=200,
    )
    assert compare([bad, good, best]) == [best, good, bad]


# -- property tests (seeded loop; hypothesis is not a dependency) --------------------------------

METRICS = ("views", "ctr", "ctor", "aov")


def random_case(rng: random.Random):
    keys = rng.sample(SOURCES, rng.randint(1, 4))
    sources = []
    for key in keys:
        orders = rng.randint(0, 500)
        clicks = None if rng.random() < 0.15 else orders + rng.randint(1, 3000)
        views = None if (clicks is None or rng.random() < 0.1) else clicks + rng.randint(1, 50000)
        gmv = orders * rng.randint(20_000, 400_000)
        profit = None if rng.random() < 0.1 else int(gmv * rng.uniform(0.05, 0.4))
        sources.append(src(key, views, clicks, orders, gmv, profit))
    base = FunnelBase(
        "s",
        "shop",
        (),
        date(2026, 10, 1),
        date(2026, 10, 1 + rng.randint(6, 29)),
        tuple(sources),
        None if rng.random() < 0.1 else D(str(round(rng.uniform(0.05, 0.5), 3))),
    )
    drivers = []
    for _ in range(rng.randint(1, 2)):
        m = rng.choice(METRICS)
        chosen = tuple(rng.sample(keys, rng.randint(1, len(keys))))
        basis = rng.choice(("measured", "shop", "prior", "prior", "not_estimable"))
        if rng.random() < 0.25:
            drivers.append(
                DriverEffect(
                    "views",
                    chosen,
                    basis,
                    added=AddedTraffic(
                        band(1000, 5000, 9000),
                        D("0.05"),
                        D("0.04"),
                        D(rng.randint(50_000, 200_000)),
                        band(0.2, 0.5, 0.8),
                        None if rng.random() < 0.2 else D(15000),
                    ),
                )
            )
        else:
            lo = rng.uniform(-0.05, 0.1)
            drivers.append(
                DriverEffect(
                    m,
                    chosen,
                    basis,
                    lift=band(lo, lo + rng.uniform(0, 0.1), lo + rng.uniform(0.1, 0.3)),
                )
            )
    offers = ()
    if rng.random() < 0.5:
        offers = (
            OfferCost(
                D(rng.randint(1000, 9000)),
                band(0.05, 0.2, 0.4),
                D(rng.randint(5, 200)) if rng.random() < 0.5 else None,
                "voucher",
            ),
        )
    opt = OptionInput(
        "k",
        "l",
        tuple(drivers),
        rng.choice((None, 7, 14, 30, 45)),
        fixed_cost=D(rng.choice((0, 100_000, 800_000))),
        offers=offers,
        profit_per_order_after=D(rng.randint(5000, 60000)) if rng.random() < 0.2 else None,
    )
    return base, opt


def test_properties_over_random_cases():
    rng = random.Random(20261109)
    n_est = 0
    for case in range(200):
        base, opt = random_case(rng)
        r = run(base, opt, seed=case, n=150)
        j = r.json()
        assert set(j) == set(WIRE_KEYS), case
        assert set(j["delta"]) == set(WIRE_KEYS["delta"])
        assert run(base, opt, seed=case, n=150).json() == j  # same seed, same json
        if not r.estimable:
            assert r.low is None and r.likely is None and r.high is None
            assert j["delta"]["profit"] is None and j["build_up"] == []
            continue
        n_est += 1
        cols = [r.before, r.low, r.likely, r.high]
        for s in cols:
            assert s is not None
            for key, row in s.by_source.items():
                o, g = row["orders"], row["gmv"]
                assert o is not None and g is not None
                if row["views"] is not None and row["ctr"] is not None and row["ctor"] is not None:
                    assert float(row["views"] * row["ctr"] * row["ctor"]) == pytest.approx(
                        float(o), rel=1e-6, abs=1e-9
                    )
                if row["aov"] is not None:
                    assert float(o * row["aov"]) == pytest.approx(float(g), rel=1e-9, abs=1e-6)
            assert sum(x["orders"] for x in s.by_source.values()) == s.orders
            assert sum(x["gmv"] for x in s.by_source.values()) == s.gmv
            if s.profit is not None:
                assert sum(x["profit"] for x in s.by_source.values()) == s.profit
            if s.views is not None:  # the residual counts as 0 traffic (contract FunnelBase.total)
                assert (
                    sum(x["views"] or 0 for k, x in s.by_source.items() if k != "chenh_lech_nguon")
                    == s.views
                )
        assert r.low and r.likely and r.high
        if r.likely.profit is not None:
            lo, mid, hi = (c.profit for c in (r.low, r.likely, r.high))
            assert lo <= mid <= hi
            d = j["delta"]["profit"]
            assert d["low"] <= d["value"] <= d["high"]
            assert abs(sum(p["amount"] for p in j["build_up"]) - d["value"]) <= 1
            assert len(j["build_up"]) <= 3
        else:
            assert j["build_up"] == []
        if all(m == "aov" for m in r.drivers):
            assert r.likely.orders == r.before.orders
            assert j["delta"]["orders"]["value"] == 0
    assert n_est > 60  # the generator must exercise the estimable path


# -- the residual source (ADR-122 d.2 / d.3) ------------------------------------------------------


def residual_base():
    return FunnelBase(
        "shop-1",
        "shop",
        (),
        date(2026, 10, 1),
        date(2026, 10, 30),
        (
            src("the_san_pham_khac", 100000, 5000, 200, 20_000_000, 4_000_000),
            src("trang_shop", 20000, 1000, 50, 5_000_000, 1_000_000),
            src("chenh_lech_nguon", None, None, 10, 1_000_000, 200_000),
        ),
        D("0.3"),
    )


def test_residual_counts_as_zero_traffic_in_totals():
    base = residual_base()
    assert base.total("views") == D(120000)
    assert base.total("clicks") == D(6000)
    assert base.total("orders") == D(260)  # the residual's orders stay in the total


def test_residual_keeps_the_shop_funnel_and_adds_no_note():
    result = run(residual_base(), voucher_option())
    assert result.before.views is not None and result.before.clicks is not None
    assert result.likely is not None and result.likely.views is not None
    # shop CTOR = all orders (residual included) ÷ clicks, so views × CTR × CTOR = orders
    col = result.likely
    assert col.clicks is not None and col.views is not None
    ctr = col.clicks / col.views
    ctor = col.orders / col.clicks
    assert abs(col.views * ctr * ctor - col.orders) <= D("1e-6") * col.orders
    assert not any("Chênh lệch" in n for n in result.notes)


def test_a_price_change_counts_its_profit_effect_once():
    """profit_per_order_after carries the price effect; the AOV driver then moves GMV only."""
    base = simple_base()
    ppo_before = D(5_000_000) / D(250)  # 20.000đ per order
    option = OptionInput(
        "price",
        "Đổi giá",
        (
            DriverEffect(
                "aov", ("the_san_pham_khac", "trang_shop"), "measured", lift=band(0.1, 0.1, 0.1)
            ),
        ),
        30,
        profit_per_order_after=ppo_before + D(3_000),
    )
    r = run(base, option)
    assert r.likely is not None and r.likely.profit is not None
    # orders unchanged (AOV-only), so Δ profit = orders × 3.000đ exactly, with no extra AOV term
    assert abs((r.likely.profit - r.before.profit) - r.before.orders * D(3_000)) <= D(1)
    assert r.likely.gmv > r.before.gmv  # the AOV driver still moves GMV
