"""R1 owner decisions (#99, 26/11): product ads GMV / ROAS only from the period's own report;
missing ad cost is None, never 0; product GMV and đơn leave out cancelled lines. Synthetic data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from juli_backend.services.shopee_analytics.compute import allocate_ads
from juli_backend.services.shopee_analytics.loaders import (
    AdsDaily,
    AdsReports,
    AdsRow,
    PeriodChoice,
)
from juli_backend.services.shopee_analytics.metrics import _splits
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_profit.order_profit import OrderStatus
from juli_backend.services.shopee_profit.shop_profit import shop_profit
from tests.unit.test_c1_in_transit_ads import _pair

D = Decimal
W = Window(date(2026, 10, 1), date(2026, 10, 10))
NONE = PeriodChoice((), "none", 0)


def _row(item, spend, gmv, period):
    return AdsRow("G", "g", item, D(spend), D(gmv), D(gmv) / 2, D(3), D(10), D(100), True, period)


def _alloc(period, basis="overlap"):
    rows = [_row("1", 100, 500, period)]
    reports = AdsReports(rows, [], PeriodChoice((period,), basis, 10), NONE)
    return allocate_ads(W, AdsDaily(D(0), D(0), D(0), {}, 0, 10), reports)


def test_product_ads_gmv_and_roas_are_none_from_a_report_of_another_period():
    fig = _alloc((date(2026, 9, 21), date(2026, 10, 20))).product_figures["1"]
    assert fig.spend > 0
    assert fig.gmv is None and fig.direct_gmv is None
    assert fig.roas_broad is None and fig.roas_direct is None


def test_product_ads_gmv_is_kept_from_the_report_of_the_same_period():
    fig = _alloc((W.start, W.end), "exact").product_figures["1"]
    assert fig.gmv == D(500) and fig.roas_broad == D(5)


def test_no_ad_data_for_the_window_is_none_but_a_read_zero_is_zero():
    none = allocate_ads(W, AdsDaily(D(0), D(0), D(0), {}, 0, 10), AdsReports([], [], NONE, NONE))
    assert none.basis == "none" and none.known_spend is None
    zero = allocate_ads(W, AdsDaily(D(0), D(0), D(0), {}, 10, 10), AdsReports([], [], NONE, NONE))
    assert zero.known_spend == D(0)


def test_product_gmv_and_orders_leave_out_cancelled_lines():
    pairs = [
        _pair("o1", 100_000, 4, 40_000),
        _pair("o2", 300_000, 5, 90_000, status=OrderStatus.CANCELLED),
    ]
    pp = shop_profit(pairs, campaigns=[], product_ad_spend={}).products["A"]
    assert (pp.gmv, pp.orders) == (D(100_000), 1)
    view = SimpleNamespace(pairs=pairs, line_orders=2)
    split = _splits(view, None, None)[0]["A"]
    assert split.gmv == D(100_000) and split.orders == 1
