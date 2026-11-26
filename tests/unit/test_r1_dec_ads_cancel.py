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
from juli_backend.services.shopee_profit.order_profit import OrderLine, OrderStatus
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


def _line(order, item, value, status=OrderStatus.DELIVERED):
    return OrderLine(
        order_id=order,
        sku="S-" + item,
        product_id=item,
        order_date=date(2026, 11, 4),
        qty=1,
        original_price=D(value),
        deal_price=D(value),
        status=status,
    )


def test_a_cancelled_line_keeps_its_place_in_the_scale_and_its_share_is_not_given_away():
    # shop day total 200k holds the cancelled order: A delivered 100k, B cancelled 100k
    pairs = [
        (_line("o1", "A", 100_000), None),
        (_line("o2", "B", 100_000, OrderStatus.CANCELLED), None),
    ]
    view = SimpleNamespace(pairs=pairs, line_orders=2)
    out = _splits(view, D(200_000), 2)[0]
    assert out["A"].gmv == D(100_000) and out["A"].orders == 1
    assert out["B"].gmv == 0 and out["B"].orders == 0 and out["B"].units == 0


def test_a_day_of_only_cancelled_lines_has_no_period_fallback():
    pairs = [(_line("o2", "B", 100_000, OrderStatus.CANCELLED), None)]
    view = SimpleNamespace(pairs=pairs, line_orders=1)
    out, scale, _ = _splits(view, D(100_000), 1)
    assert scale == 1 and out["B"].gmv == 0 and out["B"].basis == "scaled_order_lines"


def test_an_unknown_ad_cost_gives_no_final_margin_but_a_known_zero_does():
    from juli_backend.services.shopee_analytics.margins import final_margin, measured_rates

    pairs = [_pair("o1", 100_000, 4, 40_000)]
    unknown, _ = measured_rates(pairs, None, ads_unknown=True)
    known, _ = measured_rates(pairs, D(0))
    assert unknown is not None and known is not None
    assert final_margin(40.0, unknown) is None
    assert final_margin(40.0, known) == 40.0


def test_a_product_with_an_unknown_ads_gmv_is_not_ranked_as_zero():
    from juli_backend.services.shopee_analytics.rankings import _product_m
    from juli_backend.services.shopee_profit.shop_profit import AdsFigures

    view = SimpleNamespace(
        ads=SimpleNamespace(product_figures={"1": AdsFigures(D(10), None, None)}),
        profit=SimpleNamespace(products={}),
        pairs=[],
    )
    assert _product_m(view, "1", "ads", None) is None


def _known_profit(ads_known: bool):
    from juli_backend.services.shopee_profit.shop_profit import known_cost_profit

    pairs = [_pair("o1", 100_000, 4, 40_000)]
    sp = shop_profit(pairs, campaigns=[], product_ad_spend={}, ads_known=ads_known)
    return pairs, sp, known_cost_profit(sp, pairs, D(100_000), {}, None, ads_known=ads_known)


def test_no_ad_data_at_all_withholds_the_shop_profit_in_the_one_gate():
    from juli_backend.services.shopee_profit.shop_profit import gate_profit

    _, _, kp = _known_profit(False)
    assert kp.profit is not None  # the raw figure exists ...
    gated = gate_profit(kp)
    assert gated.profit is None and gated.margin_pct is None and gated.withheld
    assert gated.withheld_reason == "chưa có dữ liệu quảng cáo"


def test_a_window_whose_data_says_zero_spent_keeps_its_profit():
    from juli_backend.services.shopee_profit.shop_profit import gate_profit

    _, _, kp = _known_profit(True)
    assert gate_profit(kp).profit == kp.profit and kp.profit is not None


def test_the_product_profit_is_none_without_ad_data():
    from juli_backend.services.shopee_profit.shop_profit import (
        product_margin_pct_shown,
        product_profit_shown,
    )

    _, sp, _ = _known_profit(False)
    pp = sp.products["A"]
    assert product_profit_shown(pp) is None and product_margin_pct_shown(pp) is None
    _, sp_ok, _ = _known_profit(True)
    assert product_profit_shown(sp_ok.products["A"]) is not None
