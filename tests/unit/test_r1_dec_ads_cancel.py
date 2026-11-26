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


def test_the_cancelled_share_is_its_own_row_only_when_non_zero():
    from juli_backend.services.shopee_analytics.metrics import (
        CANCELLED_LABEL,
        cancelled_row,
        cancelled_share,
    )

    pairs = [
        (_line("o1", "A", 100_000), None),
        (_line("o2", "B", 100_000, OrderStatus.CANCELLED), None),
        (_line("o2", "C", 50_000, OrderStatus.CANCELLED), None),
    ]
    gmv, orders = cancelled_share(pairs, D(1))
    assert (gmv, orders) == (D(150_000), 1)
    assert cancelled_share(pairs, D("0.5"))[0] == D(75_000)  # scaled like the products
    assert cancelled_row(D(0), 0) is None
    assert cancelled_row(gmv, orders) == {
        "label": "Đơn hủy sau xác nhận",
        "gmv": 150000,
        "orders": 1,
    }
    assert CANCELLED_LABEL == "Đơn hủy sau xác nhận"


def test_the_five_numbers_show_no_profit_without_ad_data():
    from juli_backend.services.shopee_analytics.shared import five_json
    from juli_backend.services.shopee_profit.five_numbers import five_numbers, snapshot_from

    pairs = [_pair("o1", 100_000, 4, 40_000)]
    snap = snapshot_from(pairs, D(0), days=D(1))
    five = five_numbers(snap, snap)
    shown = five_json(five)["margin"]
    assert shown["profit_before"] is not None
    gated = five_json(five, ads_known=False)["margin"]
    assert all(
        gated[k] is None for k in ("profit_before", "profit_after", "pct_before", "pct_after")
    )


def test_a_campaign_with_connector_days_keeps_its_break_even_without_a_same_window_report():
    """#99 1a blanks a product's report GMV off the report's own period; the ads cards still read
    the campaign's Connector days (C2): ROAS from the campaign's own direct GMV, the break-even
    from its products' contribution rates weighted by their share of its spend (decision #39)."""
    from juli_backend.services.shopee_analytics.compute import AdsFigures, CampaignAlloc
    from juli_backend.services.shopee_recommendations.evaluate import campaign_profile

    alloc = CampaignAlloc(
        "c1",
        "Nhóm",
        D(30_000),
        D(150_000),
        D(120_000),
        D(4),
        D(90),
        D(3000),
        True,
        {"A": D(20_000), "B": D(10_000)},
        "daily",
    )
    figures = {"A": AdsFigures(D(20_000), None, None), "B": AdsFigures(D(10_000), None, None)}
    products = {
        "A": SimpleNamespace(contribution=D(50_000), buyer_paid_covered=D(100_000)),  # 50 %
        "B": SimpleNamespace(contribution=D(20_000), buyer_paid_covered=D(100_000)),  # 20 %
    }
    ads = SimpleNamespace(
        campaigns=[alloc], product_figures=figures, product_spend={"A": D(20_000), "B": D(10_000)}
    )
    env = SimpleNamespace(view=SimpleNamespace(ads=ads), window_days=30, product=products.get)
    prof = campaign_profile(env, "c1")
    assert prof is not None and prof["roas_direct"] == D(4)
    rate = (D("0.5") * 2 + D("0.2")) / 3  # spend-weighted 40 %
    assert prof["rate"] == rate and prof["break_even_roas"] == 1 / rate
    assert prof["profit_before_ads_per_day"] == D(120_000) * rate / 30
