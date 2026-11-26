"""Decision #39: one ad cost per product ("chi phí quảng cáo của sản phẩm"). The rule, the window
figure and the stored day rows add up. Synthetic numbers only."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from juli_backend.services.metrics.registry import METRICS
from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_analytics.compute import allocate_ads
from juli_backend.services.shopee_analytics.loaders import (
    AdsDaily,
    AdsReports,
    PeriodChoice,
)
from juli_backend.services.shopee_analytics.product_ads import (
    ProductAdRule,
    ProductAdsInput,
    ReportRow,
    product_ad_cost,
)
from juli_backend.services.shopee_analytics.windows import Window

D = Decimal
START = date(2026, 10, 1)
END = date(2026, 10, 10)
WINDOW = Window(START, END)


def _days(n: int = 10) -> list[date]:
    return [START + timedelta(days=i) for i in range(n)]


def _group_world() -> ProductAdsInput:
    """A group campaign "g" (products 1 and 2, 70 / 30) and a campaign "s" with one product (3).
    The report for "g" is one 10-day window; "s" has per-day rows plus an overlapping 3-day one."""
    daily = {("g", d): D(100) for d in _days()} | {("s", d): D(40) for d in _days()}
    rows = [
        ReportRow("g", "1", START, END, D(700)),
        ReportRow("g", "2", START, END, D(300)),
        ReportRow("s", "3", START, START + timedelta(days=2), D(999)),  # overlapping, longer
    ] + [ReportRow("s", "3", d, d, D(5)) for d in _days(3)]
    return ProductAdsInput(daily, frozenset(_days()), rows)


def test_day_values_add_up_to_the_window_figure_for_a_group_campaign():
    rule = ProductAdRule(_group_world())
    window = rule.window_spend(START, END)
    for item in ("1", "2", "3"):
        by_day = [rule.product_day(item, d) for d in _days()]
        assert None not in by_day
        assert sum(by_day, D(0)) == window[item]
    # 10 days x 100 spent, split 70 / 30; the one-product campaign is 100 %
    assert window["1"] == D(700) and window["2"] == D(300) and window["3"] == D(400)


def test_the_shortest_covering_report_window_wins_and_windows_are_never_summed():
    inp = _group_world()
    rule = ProductAdRule(inp)
    # day 1: the one-day row (5) covers it and beats the 3-day row (999): share is 100 % either way
    assert rule.product_day("3", START) == D(40)
    # a second product on the one-day rows changes only the days those rows cover
    inp.report_rows += [ReportRow("s", "4", START, START, D(15))]
    again = ProductAdRule(inp)
    assert again.product_day("3", START) == D(40) * D(5) / D(20)
    assert again.product_day("4", START) == D(40) * D(15) / D(20)
    assert again.product_day("4", START + timedelta(days=1)) is None  # a product, no basis that day


def test_no_basis_is_none_never_zero():
    rule = ProductAdRule(_group_world())
    assert rule.product_day("nobody", START) is None
    assert product_ad_cost(ProductAdsInput(), "1", START, END) is None
    # a report that spent nothing gives no share
    empty = ProductAdsInput(
        {("g", START): D(50)}, frozenset({START}), [ReportRow("g", "1", START, START, D(0))]
    )
    assert ProductAdRule(empty).product_day("1", START) is None


def test_the_nearest_report_serves_a_day_outside_every_window():
    inp = ProductAdsInput(
        {("g", START): D(100)},
        frozenset({START}),
        [ReportRow("g", "1", START - timedelta(days=5), START - timedelta(days=3), D(10))],
    )
    assert ProductAdRule(inp).product_day("1", START) == D(100)  # sole product of the campaign


def test_a_day_the_connector_did_not_read_takes_the_covering_report_spread_over_its_days():
    inp = ProductAdsInput(
        {},
        frozenset(),  # no Connector day at all
        [ReportRow("g", "1", START, START + timedelta(days=3), D(400))],
    )
    rule = ProductAdRule(inp)
    assert rule.product_day("1", START + timedelta(days=1)) == D(100)
    assert rule.product_day("1", START + timedelta(days=5)) is None  # no covering window


def test_the_window_figure_of_the_screens_is_the_sum_of_the_days():
    inp = _group_world()
    reports = AdsReports([], [], PeriodChoice((), "none", 0), PeriodChoice((), "none", 0))
    alloc = allocate_ads(WINDOW, AdsDaily(D(1400), D(0), D(0), {}, 10, 10), reports, None, inp)
    rule = ProductAdRule(inp)
    for item in ("1", "2", "3"):
        by_day = sum((rule.product_day(item, d) or D(0) for d in _days()), D(0))
        assert alloc.product_spend[item] == by_day
    assert set(alloc.product_figures) == {"1", "2", "3"}


def test_the_registry_names_the_product_variant_with_its_own_source():
    m = METRICS["cost_ads_product"]
    assert m.label_vi == "Chi phí quảng cáo của sản phẩm"
    assert m.sources["shopee"].dataset == "ads_report_by_product"
    assert "cost_ads" in METRICS and METRICS["cost_ads"].sources["shopee"].dataset == "ads_report"


@pytest.mark.parametrize("dataset", ["ads_campaign_period"])
def test_an_ads_by_product_report_upload_is_a_rebuilding_dataset(dataset):
    assert dataset in materialize.PRODUCT_AD_DATASETS
    assert materialize.ROWS_VERSION >= 3
