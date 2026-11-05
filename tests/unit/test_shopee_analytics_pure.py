"""P90 step 7: the pure parts of ``services/shopee_analytics`` -- windows, period choice, the fee
table, the SKU -> item resolution, the cost rules, the ads allocation, and the ranking's
adds-up property on hand-built rows. No database."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from juli_backend.services.shopee_analytics import fee_table
from juli_backend.services.shopee_analytics.catalog import RawItem, build_catalog
from juli_backend.services.shopee_analytics.compute import allocate_ads
from juli_backend.services.shopee_analytics.engine import (
    RawLine,
    build_fee_context,
    cost_coverage,
    profit_pairs,
    resolve_costs,
    to_shop_lines,
)
from juli_backend.services.shopee_analytics.loaders import (
    AdsDaily,
    AdsReports,
    AdsRow,
    voucher_value_from_name,
)
from juli_backend.services.shopee_analytics.rankings import M, rank
from juli_backend.services.shopee_analytics.rules_view import RuleRow, read_rules
from juli_backend.services.shopee_analytics.windows import (
    InvalidWindow,
    PeriodChoice,
    Window,
    choose_periods,
    resolve_window,
)

D = Decimal


# =========================================================================== windows


def test_last_n_days_end_on_as_of_and_the_previous_period_is_as_long():
    w = resolve_window("30d", as_of=date(2026, 10, 28))
    assert (w.start, w.end, w.days) == (date(2026, 9, 29), date(2026, 10, 28), 30)
    prev = w.previous()
    assert (prev.start, prev.end, prev.days) == (date(2026, 8, 30), date(2026, 9, 28), 30)
    assert resolve_window("7d", as_of=date(2026, 10, 28)).days == 7
    assert resolve_window("90d", as_of=date(2026, 10, 28)).days == 90


def test_a_calendar_month_is_whole_unless_it_is_the_current_one():
    assert resolve_window("month", as_of=date(2026, 10, 28), month="2026-09") == Window(
        date(2026, 9, 1), date(2026, 9, 30)
    )
    assert resolve_window("month", as_of=date(2026, 10, 28), month="2026-10").end == date(
        2026, 10, 28
    )
    assert resolve_window("month", as_of=date(2026, 10, 28), month="2026-02").days == 28


def test_a_custom_window_needs_both_bounds_and_is_validated():
    assert (
        resolve_window(
            "custom", as_of=date(2026, 1, 1), start=date(2026, 3, 1), end=date(2026, 3, 9)
        ).days
        == 9
    )
    for bad in (
        dict(kind="custom", start=date(2026, 3, 1)),
        dict(kind="custom", start=date(2026, 3, 9), end=date(2026, 3, 1)),
        dict(kind="custom", start=date(2024, 1, 1), end=date(2026, 3, 1)),
        dict(kind="month"),
        dict(kind="month", month="2026-13"),
        dict(kind="fortnight"),
    ):
        with pytest.raises(InvalidWindow):
            resolve_window(as_of=date(2026, 10, 1), **bad)


def test_period_choice_prefers_the_exact_period_then_contained_ones_then_a_close_overlap():
    w = Window(date(2026, 10, 1), date(2026, 10, 28))
    exact = choose_periods(
        w, {(date(2026, 10, 1), date(2026, 10, 28)), (date(2026, 9, 1), date(2026, 9, 30))}
    )
    assert exact.basis == "exact" and exact.covered_days == 28
    weeks = {
        (date(2026, 10, 1), date(2026, 10, 7)),
        (date(2026, 10, 8), date(2026, 10, 14)),
        (date(2026, 10, 5), date(2026, 10, 11)),
    }
    contained = choose_periods(w, weeks)
    assert contained.basis == "contained" and contained.periods == (
        (date(2026, 10, 1), date(2026, 10, 7)),
        (date(2026, 10, 8), date(2026, 10, 14)),
    )  # overlapping periods are never both used
    approx = choose_periods(w, {(date(2026, 9, 29), date(2026, 10, 28))})
    assert approx.basis == "approx" and approx.covered_days == 28
    assert choose_periods(w, {(date(2026, 9, 1), date(2026, 9, 30))}) == PeriodChoice((), "none", 0)


# =========================================================================== fee table


def test_the_seed_rates_are_the_contracts_and_a_category_beats_a_name_hint():
    glove = ("Nhà cửa & Đời sống", "Dụng cụ nhà bếp", "Tạp dề & găng tay nấu nướng")
    assert fee_table.choose_fixed_fee_rate(glove, "anything") == fee_table.RateChoice(
        D("0.15"), fee_table.SOURCE_SEED_CATEGORY, glove
    )
    bag = fee_table.choose_fixed_fee_rate(None, "Túi Rác Tự Hủy Sinh Học STAHAUS")
    assert (bag.rate, bag.source) == (D("0.10"), fee_table.SOURCE_SEED_NAME_HINT)
    foil = fee_table.choose_fixed_fee_rate(None, "Màng nhôm bọc thực phẩm")
    assert foil.rate == D("0.16")
    unknown = fee_table.choose_fixed_fee_rate(None, "Dĩa trồng cây 7.5cm")
    assert (unknown.rate, unknown.source) == (D("0.105"), fee_table.SOURCE_DEFAULT)


def test_a_deeper_category_path_falls_back_to_its_longest_known_prefix():
    deeper = ("Nhà cửa & Đời sống", "Dụng cụ nhà bếp", "Tạp dề & găng tay nấu nướng", "Găng cao su")
    assert fee_table.choose_fixed_fee_rate(deeper, None).rate == D("0.15")


def test_the_seed_formula_is_fixed_per_item_plus_six_percent_plus_three_thousand():
    formula = fee_table.seed_schedule(D("0.15")).formula_on(date(2026, 10, 1))
    assert formula is not None
    assert formula.pct_rate_on_buyer_paid == D("0.21") and formula.fixed_per_order == D(3000)
    assert fee_table.seed_schedule(D("0.15")).formula_on(date(2026, 5, 1)) is None  # never a guess


def test_a_database_formula_for_the_category_replaces_the_seed():
    rows = [
        fee_table.FormulaRow(
            ("Nhà cửa & Đời sống",),
            date(2026, 1, 1),
            ({"code": "phi_san", "kind": "pct", "base": "buyer_paid", "rate": 0.2},),
        ),
        fee_table.FormulaRow(
            (),
            date(2026, 1, 1),
            ({"code": "phi_san", "kind": "pct", "base": "buyer_paid", "rate": 0.3},),
        ),
    ]
    home = fee_table.schedule_from_rows(rows, ("Nhà cửa & Đời sống", "Dụng cụ nhà bếp"))
    assert home is not None and home.formula_on(date(2026, 2, 1)).pct_rate_on_buyer_paid == D("0.2")
    other = fee_table.schedule_from_rows(rows, ("Thời trang",))
    assert other is not None and other.formula_on(date(2026, 2, 1)).pct_rate_on_buyer_paid == D(
        "0.3"
    )
    assert fee_table.schedule_from_rows([], ("x",)) is None


# =========================================================================== catalogue


def test_an_order_line_known_only_by_sku_resolves_to_the_item_that_owns_the_sku():
    catalog = build_catalog(
        [
            RawItem("11", "", "Găng tay", None, "G1", "ok"),
            RawItem("11", "111", None, "Combo 3", "G1-A", "ok"),
            RawItem("22", "", "Nước rửa chén", None, "N1", "ok"),
        ]
    )
    assert catalog.resolve("sku:G1-A", "G1", "G1-A") == "11"
    assert catalog.resolve("sku:N1", "N1", None) == "22"
    assert catalog.resolve("sku:ZZ", "ZZ", None) == "sku:ZZ"  # unknown: kept, counted as such
    assert catalog.resolve("33", None, None) == "33"  # a real id is never rewritten
    assert catalog.name("sku:ZZ") == "ZZ" and catalog.name("11") == "Găng tay"


# =========================================================================== cost and fee rules


def _raw(n: int, **over) -> RawLine:
    base = dict(
        order_ref=f"{n:032x}",
        line_no=0,
        ordered_at=datetime(2026, 10, 3, 10),
        paid_at=datetime(2026, 10, 3, 10),
        status="delivered",
        item_id="sku:G1",
        sku="G1",
        variation_sku=None,
        qty=1,
        original_price=D(99_000),
        deal_price=D(90_000),
        shop_voucher_share=D(0),
        bundle_discount=D(0),
        promo_kind="discount",
        voucher_code=None,
        affiliate=False,
        commission=None,
        fee_fixed=None,
        fee_service=None,
        fee_payment=None,
        fee_other=None,
        buyer_shipping_fee=None,
        bank_promo=None,
        ad_attributed=None,
    )
    return RawLine(**{**base, **over})


def test_unpaid_lines_are_not_orders_and_a_paid_cancelled_line_is_kept():
    catalog = build_catalog([RawItem("11", "", "Găng", None, "G1", None)])
    lines = to_shop_lines(
        [_raw(1), _raw(2, paid_at=None, status="cancelled"), _raw(3, status="cancelled")], catalog
    )
    assert len(lines) == 2 and {sl.product_id for sl in lines} == {"11"}


def test_giá_vốn_falls_back_to_a_third_of_list_and_an_imported_cost_wins():
    catalog = build_catalog([RawItem("11", "", "Găng", None, "G1", None)])
    lines = to_shop_lines([_raw(1)], catalog)
    fallback = resolve_costs(lines, read_rules([]))
    assert fallback.by_key["G1"].cogs == D(33_000) and fallback.cogs_source["G1"] == "assumed"
    assert fallback.by_key["G1"].packaging == 0 and fallback.packaging_source["G1"] == "assumed"
    rules = read_rules(
        [
            RuleRow("sku_cost", "G1", 40_000),
            RuleRow("product_cost", "11", 10_000),
            RuleRow("packaging_cost", "G1", 2_000),
        ]
    )
    imported = resolve_costs(lines, rules)
    assert imported.by_key["G1"].cogs == D(40_000) and imported.cogs_source["G1"] == "real"
    assert imported.by_key["G1"].packaging == D(2_000) and imported.packaging_source["G1"] == "real"
    only_product = resolve_costs(lines, read_rules([RuleRow("product_cost", "11", 10_000)]))
    assert only_product.by_key["G1"].cogs == D(10_000)  # SKU rule absent: the product's applies


def test_coverage_splits_the_profit_base_by_where_the_cost_came_from():
    catalog = build_catalog(
        [RawItem("11", "", "Găng", None, "G1", None), RawItem("22", "", "Nước", None, "N1", None)]
    )
    lines = to_shop_lines([_raw(1), _raw(2, item_id="sku:N1", sku="N1")], catalog)
    costs = resolve_costs(lines, read_rules([RuleRow("sku_cost", "G1", 30_000)]))
    fees = build_fee_context([sl.product_id for sl in lines], catalog)
    pairs = profit_pairs(lines, costs, fees)
    cov = cost_coverage(pairs, costs)
    assert cov.base == D(180_000) and cov.real == D(90_000) and cov.assumed == D(90_000)
    assert cov.pct(cov.real) == D("50.0") and cov.json()["assumed_pct"] == 50.0
    assert cov.json()["packaging_assumed_pct"] == 100.0


def test_per_order_fees_are_charged_once_even_when_the_items_have_different_rates():
    catalog = build_catalog(
        [
            RawItem("11", "", "Găng tay", None, "G1", None),
            RawItem("22", "", "Túi rác", None, "T1", None),
        ]
    )
    one = _raw(1)
    two = _raw(1, line_no=1, item_id="sku:T1", sku="T1")
    lines = to_shop_lines([one, two], catalog)
    costs = resolve_costs(lines, read_rules([]))
    fees = build_fee_context([sl.product_id for sl in lines], catalog)
    pairs = profit_pairs(lines, costs, fees)
    components = [dict(pb.fees) for _, pb in pairs]
    assert sum(c["phi_ha_tang"] for c in components) == D(
        3000
    )  # once for the order, split by value
    assert components[0]["phi_co_dinh"] == D(13_500) and components[1]["phi_co_dinh"] == D(9_000)


def test_the_target_rules_are_read_by_alias_and_absent_means_none():
    rules = read_rules(
        [
            RuleRow("monthly_gmv_target", "", 30_000_000),
            RuleRow("min_margin_pct", "", 12),
            RuleRow("daily_marketing_cap", "", {"value": 500_000}),
        ]
    )
    assert rules.target("gmv_month") == D(30_000_000) and rules.target("margin_pct") == D(12)
    assert (
        rules.target("daily_marketing_cap") == D(500_000) and rules.target("orders_month") is None
    )


def test_a_voucher_is_valued_from_its_name_only_when_the_name_says_so():
    assert voucher_value_from_name("Ory 5k") == D(5000)
    assert voucher_value_from_name("Ory - 1k") == D(1000)
    assert voucher_value_from_name("Giảm 2,5k") == D(2500)
    assert voucher_value_from_name("Voucher Thông Minh của Dịch Vụ Hiển Thị") is None


# =========================================================================== ads allocation


def _ads_row(key, item, spend, gmv, period, *, name="Nhóm"):
    return AdsRow(
        name, key, item, D(spend), D(gmv), D(gmv) * D("0.8"), D(3), D(10), D(100), True, period
    )


def test_a_report_the_size_of_the_window_is_used_whole_and_scaled_to_the_daily_total():
    w = Window(date(2026, 10, 1), date(2026, 10, 7))
    rows = [
        _ads_row("g", "", 100, 500, (w.start, w.end)),
        _ads_row("g", "1", 60, 300, (w.start, w.end)),
        _ads_row("g", "2", 40, 200, (w.start, w.end)),
    ]
    daily = AdsDaily(D(200), D(900), D(5), {}, 7, 7)
    alloc = allocate_ads(
        w,
        daily,
        AdsReports(
            rows, [], PeriodChoice(((w.start, w.end),), "exact", 7), PeriodChoice((), "none", 0)
        ),
    )
    assert alloc.total_spend == D(200) and alloc.basis == "daily_scaled" and alloc.scale == D(2)
    assert sum(alloc.product_spend.values()) == alloc.campaigns[0].spend == D(200)
    assert alloc.product_figures["1"].roas_broad == D(5)  # ROAS survives the scaling


def test_a_longer_report_is_prorated_by_overlapping_days_and_labelled_an_estimate():
    w = Window(date(2026, 10, 1), date(2026, 10, 10))
    report = (date(2026, 9, 21), date(2026, 10, 20))  # 30 days, 10 of them in the window
    rows = [_ads_row("g", "1", 300, 900, report)]
    daily = AdsDaily(D(0), D(0), D(0), {}, 3, 10)  # incomplete daily rows: no scale to lean on
    alloc = allocate_ads(
        w,
        daily,
        AdsReports(rows, [], PeriodChoice((report,), "overlap", 10), PeriodChoice((), "none", 0)),
    )
    assert (
        alloc.basis == "report_prorated"
        and round(alloc.total_spend) == D(100)
        and not alloc.exact_window
    )
    assert "ước tính" in alloc.label


def test_with_no_report_only_the_daily_total_is_known_and_it_says_so():
    w = Window(date(2026, 10, 1), date(2026, 10, 7))
    alloc = allocate_ads(
        w,
        AdsDaily(D(70), D(300), D(2), {}, 7, 7),
        AdsReports([], [], PeriodChoice((), "none", 0), PeriodChoice((), "none", 0)),
    )
    assert alloc.basis == "daily_only" and alloc.total_spend == D(70) and alloc.product_spend == {}
    none = allocate_ads(
        w,
        AdsDaily(D(0), D(0), D(0), {}, 0, 7),
        AdsReports([], [], PeriodChoice((), "none", 0), PeriodChoice((), "none", 0)),
    )
    assert none.basis == "none" and none.campaigns == []


# =========================================================================== ranking arithmetic


def _rows(values: dict[str, tuple[int, int]]):
    return {k: (k.upper(), M(D(g), D(o)), {}) for k, (g, o) in values.items()}


def test_rows_plus_closing_rows_equal_the_cell_whatever_the_cell_says():
    now = _rows({"a": (700, 40), "b": (300, 35), "c": (50, 12), "tiny": (30, 2)})
    before = _rows({"a": (400, 40), "b": (500, 35), "c": (50, 12), "tiny": (5, 1)})
    cell_now, cell_before = (
        M(D(1200), D(90)),
        M(D(1000), D(88)),
    )  # the cell carries 120 the rows do not
    out = rank(
        kind="products",
        rows_now=now,
        rows_before=before,
        cell_now=cell_now,
        cell_before=cell_before,
        xep="gmv_per_day",
        days_now=1,
        days_before=1,
        source="all",
        sub=None,
    )
    assert out["adds_up"] is True
    listed = sum(D(str(r["delta"])) for r in out["down"] + out["up"])
    closing = sum(D(str(out["closing"][k]["delta"])) for k in ("few", "others", "mix"))
    assert listed + closing == D(str(out["cell"]["delta"])) == D(200)
    assert [r["id"] for r in out["up"]] == ["a"] and [r["id"] for r in out["down"]] == ["b"]
    assert out["closing"]["few"]["count"] == 1  # "tiny": under the order floor on both sides
    assert D(str(out["closing"]["mix"]["delta"])) == D(200 - (300 - 200 + 0 + 25))
    for view in out["views"].values():
        assert D(str(view["sum"])) == D(200)


def test_a_row_new_in_the_window_has_no_previous_value_and_is_marked():
    out = rank(
        kind="products",
        rows_now=_rows({"a": (500, 40)}),
        rows_before={},
        cell_now=M(D(500), D(40)),
        cell_before=M(D(0), D(0)),
        xep="gmv_per_day",
        days_now=1,
        days_before=1,
        source="all",
        sub=None,
    )
    assert out["up"] == [] or out["up"][0]["before_missing"] is True
    assert out["adds_up"] is True


def test_per_day_scaling_divides_by_each_windows_own_length():
    out = rank(
        kind="products",
        rows_now=_rows({"a": (700, 40)}),
        rows_before=_rows({"a": (700, 40)}),
        cell_now=M(D(700), D(40)),
        cell_before=M(D(700), D(40)),
        xep="gmv_per_day",
        days_now=7,
        days_before=14,
        source="all",
        sub=None,
    )
    assert out["cell"]["now"] == 100 and out["cell"]["before"] == 50 and out["cell"]["delta"] == 50
    assert out["adds_up"] is True


def test_monthly_targets_from_the_seller_import_override_shop_wide_ones_for_their_month():
    rules = read_rules(
        [
            RuleRow("monthly_gmv_target", "", 20_000_000),
            RuleRow("monthly_gmv_target", "2026-11", 25_000_000),
            RuleRow("daily_marketing_cap", "2026-11", 160_000),
        ]
    )
    assert rules.target("gmv_month") == 20_000_000
    november = rules.for_month("2026-11")
    assert november.target("gmv_month") == 25_000_000
    assert november.target("daily_marketing_cap") == 160_000
    assert rules.for_month("2026-12").target("gmv_month") == 20_000_000
    assert rules.for_month("2026-12").target("daily_marketing_cap") is None


def test_imported_per_sku_rules_are_found_under_the_order_lines_seller_sku():
    from juli_backend.services.shopee_analytics.rules_view import with_sku_aliases

    rules = read_rules(
        [
            RuleRow("sku_cost", "26107129526:251347806793", 30_000),
            RuleRow("sku_cost", "24008937848", 65_000),
            RuleRow("sku_cost", "G500001", 40_000),  # an explicit seller-SKU key wins
            RuleRow("packaging_cost", "26107129526:251347806793", 2_000),
        ]
    )
    aliased = with_sku_aliases(
        rules,
        {
            "26107129526:251347806793": "G500001",
            "24008937848": "TD01",
        },
    )
    assert aliased.sku_cost["G500001"] == 40_000
    assert aliased.sku_cost["TD01"] == 65_000
    assert aliased.packaging_by_key["G500001"] == 2_000
    assert aliased.sku_cost["26107129526:251347806793"] == 30_000


def test_a_listing_without_variations_takes_its_only_model_so_a_variation_scoped_cost_applies():
    # The catalogue knows the listing's single model but not its seller SKU; the order line only
    # carries the SKU text. The cost imported for "item:model" must still reach the line.
    catalog = build_catalog(
        [
            RawItem("33", "", "Viên giặt", None, None, None),
            RawItem("33", "333", None, None, None, None),
        ]
    )
    lines = to_shop_lines([_raw(1, item_id="33", sku="V1")], catalog)
    assert lines[0].scope == "33:333"
    costs = resolve_costs(lines, read_rules([RuleRow("sku_cost", "33:333", 50_000)]))
    key = lines[0].cost_key
    assert costs.by_key[key].cogs == D(50_000) and costs.cogs_source[key] == "real"
