"""5a (owner #99): each forecast column is the MEAN of the scenarios ranked within +-5 % of n
around its quantile (P10: 5-15 %, P50: 45-55 %, P90: 85-95 %), not one scenario.

Fixture (invented figures): a cost-dominated option -- the offer's use share sets Δ profit while
an independent AOV lift sets Δ GMV (contribution rate 2 %), so ranking by Δ profit says almost
nothing about Δ GMV. One drawn scenario then shows a near-random Δ GMV; the mean of the middle
10 % does not."""

from __future__ import annotations

import statistics
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

import pytest

from juli_backend.services.shopee_builder.engine.contract import (
    DriverEffect,
    FunnelBase,
    OfferCost,
    OptionInput,
)
from juli_backend.services.shopee_builder.engine.engine import run
from tests.unit.test_funnel_engine import band, src

SOURCES = ("the_san_pham_khac", "trang_shop")


def cost_base(gmv_a: float = 20_000_000) -> FunnelBase:
    return FunnelBase(
        "shop-1",
        "shop",
        (),
        date(2026, 10, 1),
        date(2026, 10, 30),
        (
            src("the_san_pham_khac", 100000, 5000, 200, int(gmv_a), 4_000_000),
            src("trang_shop", 20000, 1000, 50, 5_000_000, 1_000_000),
        ),
        D("0.02"),
    )


def cost_option() -> OptionInput:
    return OptionInput(
        "combo",
        "Combo",
        (DriverEffect("aov", SOURCES, "prior", lift=band(0.02, 0.10, 0.18)),),
        14,
        offers=(OfferCost(D(20000), band(0.3, 0.5, 0.7), None, "giảm giá combo"),),
    )


def d_gmv(r) -> float:
    return float(r.likely.gmv - r.before.gmv)


def test_the_middle_gmv_is_stable_over_seeds():
    """30 seeds: the spread (sd) of the middle Δ GMV is at least 5x smaller than that of one drawn
    scenario (n=1 is one scenario: what the old single P50 draw amounted to here)."""
    one = [d_gmv(run(cost_base(), cost_option(), seed=s, n=1)) for s in range(30)]
    mean = [d_gmv(run(cost_base(), cost_option(), seed=s, n=2000)) for s in range(30)]
    assert statistics.pstdev(mean) * 5 <= statistics.pstdev(one)


def test_a_one_percent_input_change_moves_the_middle_a_little():
    """+1 % GMV on one source (same seed): the middle Δ GMV moves by at most 3 % (the input itself
    moves Δ GMV by about 0.8 %: the AOV lift multiplies that source's GMV)."""
    for seed in range(6):
        a = d_gmv(run(cost_base(), cost_option(), seed=seed, n=2000))
        b = d_gmv(run(cost_base(20_200_000), cost_option(), seed=seed, n=2000))
        assert abs(b - a) <= 0.03 * abs(a), seed


def test_columns_are_ordered_on_the_ranking_key():
    for seed in range(5):
        r = run(cost_base(), cost_option(), seed=seed, n=500)
        p0 = r.before.profit
        assert r.low.profit - p0 <= r.likely.profit - p0 <= r.high.profit - p0
    no_profit = replace(
        cost_base(),
        sources=tuple(replace(s, profit=None) for s in cost_base().sources),
    )
    r = run(no_profit, cost_option(), seed=1, n=500)
    assert r.low.gmv <= r.likely.gmv <= r.high.gmv


def test_the_middle_is_the_mean_of_the_middle_ten_percent():
    """n=21: P50 = ranks 9..11 (45-55 % of n-1=20), averaged. The averaged column reconciles:
    GMV = đơn x AOV, sources add up, build-up adds up to Δ profit, cost = its offer cost."""
    r = run(cost_base(), cost_option(), seed=3, n=21)
    j = r.json()
    for col in ("low", "likely", "high"):
        c = j["detail"][col]
        assert c["gmv"] == pytest.approx(c["orders"] * c["aov"], rel=1e-9)
        assert sum(s["gmv"] for s in c["by_source"].values()) == pytest.approx(c["gmv"], rel=1e-9)
        assert sum(s["orders"] for s in c["by_source"].values()) == pytest.approx(c["orders"])
        assert sum(s["profit"] for s in c["by_source"].values()) == pytest.approx(c["profit"])
    assert sum(p["amount"] for p in j["build_up"]) == j["delta"]["profit"]["value"]
    assert r.cost_total == r.likely.offer_cost
