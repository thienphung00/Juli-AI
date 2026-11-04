"""P91 D-12: the engine side of the income export, the seller's VAT and the pack multiplier /
bill of materials. Pure: hand-built lines, no database.

- ``pack_count_from_name``: the default the template shows and the profit reads;
- a SKU's giá vốn is one item: combo variations sharing a SKU are costed, keyed and floored apart;
  a bill of materials costs the sum of its components; packaging is per order line, never x N;
- the floor is pack-aware (``FloorInputs.pack_count`` / ``component_cost``);
- income actuals win over the order export's fees and over the formula, and an order's amounts are
  split across its lines by value in whole cents;
- the costs only the income export states (net shipping, return shipping, coins, withheld tax,
  a refund of a delivered line, compensation) enter the contribution;
- the Income coverage figure; the VAT flags (unset = before VAT, labelled).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from juli_backend.services.shopee_analytics.catalog import RawItem, build_catalog
from juli_backend.services.shopee_analytics.engine import (
    RawLine,
    build_fee_context,
    cost_coverage,
    income_coverage,
    profit_pairs,
    resolve_costs,
    to_shop_lines,
)
from juli_backend.services.shopee_analytics.rules_view import (
    ProfitRules,
    RuleRow,
    read_rules,
    with_sku_aliases,
)
from juli_backend.services.shopee_profit.floor import FloorInputs, compute_floor
from juli_backend.services.shopee_profit.income import (
    IncomeOrder,
    split_amount,
    split_income,
)
from juli_backend.services.shopee_profit.pack import (
    Component,
    components_cost,
    pack_cogs,
    pack_count_from_name,
    parse_components,
)
from juli_backend.services.shopee_profit.vat import vat_label

D = Decimal


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


CATALOG = build_catalog([RawItem("11", "", "Găng", None, "G1", None)])


def _profit(raws, rules_rows=(), income=None, catalog=CATALOG):
    rules = read_rules(rules_rows)
    lines = to_shop_lines(raws, catalog, rules, income)
    costs = resolve_costs(lines, rules)
    fees = build_fee_context([sl.product_id for sl in lines], catalog)
    return lines, costs, profit_pairs(lines, costs, fees)


# ================================================================== the pack count of a name


@pytest.mark.parametrize(
    ("name", "count"),
    [
        ("Combo 3 hộp", 3),
        ("combo 10 hộp size L", 10),
        ("Combo 2 30cm x5m", 2),
        ("Set 3 cái", 3),
        ("COMBO3", 3),
        ("Hộp 500g", None),
        ("Bộ 2 màu", None),  # only "combo" and "set" are packs
        ("Combo tiết kiệm", None),
        ("Size 30cm", None),
        ("Combo 0 hộp", None),
        ("Combo 500 hộp", None),  # not a pack count
        ("Combo 3x5", 3),
        ("", None),
        (None, None),
    ],
)
def test_the_pack_count_is_read_from_the_variation_name(name, count):
    assert pack_count_from_name(name) == count


def test_the_pack_cost_is_one_item_times_the_count_or_the_sum_of_the_components():
    assert pack_cogs(D(30_000), 3) == D(90_000) and pack_cogs(None, 3) is None
    parts = (Component("A", 2), Component("B", 1))
    assert components_cost(parts, {"A": D(10_000), "B": D(5_000)}) == D(25_000)
    assert components_cost(parts, {"A": D(10_000)}) is None  # a part with no cost: unknown
    assert parse_components(
        [{"sku": " A ", "qty": 2}, {"sku": "", "qty": 1}, "x", {"sku": "B"}]
    ) == (Component("A", 2),)
    assert parse_components("not a list") == ()


# ============================================================== the floor is pack-aware


def _floor(**over) -> FloorInputs:
    base = dict(
        list_price=D(300_000),
        cogs=D(30_000),
        packaging=D(3_000),
        fixed_fee_per_order=D(3_000),
        platform_fee_rate=D("0.2"),
        ads_rate=D(0),
        affiliate_rate=D(0),
        target_margin_rate=D(0),
    )
    return FloorInputs(**{**base, **over})


def test_a_pack_floor_costs_the_items_not_the_packaging_or_the_fee():
    single = compute_floor(_floor())
    three = compute_floor(_floor(pack_count=3))
    assert single.absolute_floor == D(45_000)  # (30000 + 3000 + 3000) / 0.8
    assert three.absolute_floor == D(120_000)  # (90000 + 3000 + 3000) / 0.8
    assert three.operating_floor == D(120_000)
    # a floor of one item is not the floor of three: the old per-unit number would sell at a loss
    assert three.absolute_floor > single.absolute_floor * 2


def test_a_bill_of_materials_cost_wins_over_cogs_times_pack():
    bom = compute_floor(_floor(pack_count=3, component_cost=D(50_000)))
    assert bom.absolute_floor == D(70_000)  # (50000 + 3000 + 3000) / 0.8
    assert _floor(cogs=None, component_cost=D(1)).unit_cogs == D(1)


def test_a_floor_without_a_cost_is_still_unknown_with_a_pack():
    result = compute_floor(_floor(cogs=None, pack_count=3))
    assert result.absolute_floor is None and "cogs" in result.reasons["absolute_floor"]


def test_the_default_pack_count_changes_nothing():
    assert compute_floor(_floor(pack_count=1)) == compute_floor(_floor())


# ======================================================== pack and bill of materials in the cost

COMBO_CATALOG = build_catalog(
    [
        RawItem("500", "", "Giấy ăn", None, "G500001", None),
        RawItem("500", "5003", None, "Combo 3 hộp", "G500001", None),
        RawItem("500", "5005", None, "Combo 5 hộp", "G500001", None),
        RawItem("500", "5010", None, "Combo 10 hộp", "G500001", None),
        RawItem("500", "5099", None, "Hộp lẻ", "G500001", None),
    ]
)


def _combo(n, variation_id, name, price):
    return _raw(
        n,
        item_id="500",
        sku="G500001",
        variation_sku="G500001",
        variation_id=variation_id,
        variation_name=name,
        original_price=D(price),
        deal_price=D(price),
    )


def test_combo_variations_that_share_a_sku_are_costed_by_their_pack():
    raws = [
        _combo(1, "5003", "Combo 3 hộp", 90_000),
        _combo(2, "5005", "Combo 5 hộp", 140_000),
        _combo(3, "5010", "Combo 10 hộp", 260_000),
        _combo(4, "5099", "Hộp lẻ", 30_000),
    ]
    lines, costs, pairs = _profit(
        raws,
        [RuleRow("sku_cost", "G500001", 20_000), RuleRow("packaging_cost", "G500001", 2_000)],
        catalog=COMBO_CATALOG,
    )
    assert {sl.cost_key for sl in lines} == {"G500001×3", "G500001×5", "G500001×10", "G500001"}
    cogs = {key: c.cogs for key, c in costs.by_key.items()}
    assert cogs == {
        "G500001×3": D(60_000),
        "G500001×5": D(100_000),
        "G500001×10": D(200_000),
        "G500001": D(20_000),
    }
    assert all(c.packaging == D(2_000) for c in costs.by_key.values())  # per line, never x N
    assert costs.pack_count["G500001×10"] == 10 and costs.pack_source["G500001×10"] == "name"
    assert all(costs.cogs_source[k] == "real" for k in cogs)
    # the line's cogs follows qty: two combos of 3 cost six items
    twice = _combo(5, "5003", "Combo 3 hộp", 90_000)
    twice = RawLine(**{**twice.__dict__, "qty": 2})
    _, _, pairs2 = _profit([twice], [RuleRow("sku_cost", "G500001", 20_000)], catalog=COMBO_CATALOG)
    assert pairs2[0][1].cogs == D(120_000)


def test_the_name_default_is_a_labelled_share_of_the_coverage():
    raws = [_combo(1, "5003", "Combo 3 hộp", 90_000), _combo(2, "5099", "Hộp lẻ", 30_000)]
    _, costs, pairs = _profit(raws, [RuleRow("sku_cost", "G500001", 20_000)], catalog=COMBO_CATALOG)
    cov = cost_coverage(pairs, costs)
    assert cov.pack_from_name == D(90_000) and cov.json()["pack_from_name_pct"] == 75.0


def test_a_pack_the_seller_set_beats_the_name_even_when_it_is_one():
    rows = [
        RuleRow("sku_cost", "G500001", 20_000),
        RuleRow("pack_count", "500:5003", 1),  # "Combo 3 hộp" is one box here
        RuleRow("pack_count", "500:5005", 4),  # and the name's 5 is wrong
    ]
    raws = [_combo(1, "5003", "Combo 3 hộp", 90_000), _combo(2, "5005", "Combo 5 hộp", 80_000)]
    lines, costs, _ = _profit(raws, rows, catalog=COMBO_CATALOG)
    assert {sl.cost_key: sl.pack_source for sl in lines} == {
        "G500001": "set",
        "G500001×4": "set",
    }
    assert costs.by_key["G500001×4"].cogs == D(80_000)


def test_a_cost_set_on_the_variation_beats_the_sku_and_the_product():
    rows = [
        RuleRow("sku_cost", "500:5003", 25_000),
        RuleRow("sku_cost", "G500001", 20_000),
        RuleRow("product_cost", "500", 10_000),
    ]
    _, costs, _ = _profit([_combo(1, "5003", "Combo 3 hộp", 90_000)], rows, catalog=COMBO_CATALOG)
    assert costs.by_key["G500001×3"].cogs == D(75_000)


def test_a_line_stored_before_the_catalogue_knew_its_variation_is_found_by_sku_and_name():
    raw = _raw(
        1,
        item_id="sku:G500001",
        sku="G500001",
        variation_sku="G500001",
        variation_name="combo 5 HỘP",
        variation_id="",
        original_price=D(140_000),
        deal_price=D(140_000),
    )
    lines, costs, _ = _profit(
        [raw], [RuleRow("sku_cost", "G500001", 20_000)], catalog=COMBO_CATALOG
    )
    assert lines[0].product_id == "500" and lines[0].scope == "500:5005"
    assert costs.by_key["G500001×5"].cogs == D(100_000)


def test_a_listing_with_a_bill_of_materials_costs_the_sum_of_its_components():
    catalog = build_catalog(
        [
            RawItem("700", "", "Combo quà", None, None, None),
            RawItem("21", "", "Găng", None, "G1", None),
            RawItem("22", "", "Nước", None, "N1", None),
        ]
    )
    rows = [
        RuleRow("sku_cost", "G1", 10_000),
        RuleRow("sku_cost", "N1", 25_000),
        RuleRow("packaging_cost", "700", 3_000),
        RuleRow("pack_components", "700", [{"sku": "G1", "qty": 2}, {"sku": "N1", "qty": 1}]),
    ]
    raw = _raw(1, item_id="700", sku=None, original_price=D(120_000), deal_price=D(100_000))
    lines, costs, _ = _profit([raw], rows, catalog=catalog)
    assert lines[0].cost_key == "bom:700" and "bom:700" in costs.bom
    assert costs.by_key["bom:700"].cogs == D(45_000) and costs.cogs_source["bom:700"] == "real"
    assert costs.by_key["bom:700"].packaging == D(3_000)


def test_a_bill_of_materials_with_an_unpriced_component_falls_back_to_the_assumed_cost():
    catalog = build_catalog([RawItem("700", "", "Combo quà", None, None, None)])
    rows = [
        RuleRow("sku_cost", "G1", 10_000),
        RuleRow("pack_components", "700", [{"sku": "G1", "qty": 2}, {"sku": "N1", "qty": 1}]),
    ]
    raw = _raw(1, item_id="700", sku=None, original_price=D(120_000), deal_price=D(100_000))
    _, costs, pairs = _profit([raw], rows, catalog=catalog)
    assert costs.cogs_source["bom:700"] == "assumed" and costs.by_key["bom:700"].cogs == D(40_000)
    assert cost_coverage(pairs, costs).assumed == D(100_000)


def test_the_rules_view_reads_packs_boms_vat_and_the_flags():
    rules = read_rules(
        [
            RuleRow("pack_count", "500:5003", 3),
            RuleRow("pack_count", "500:5005", 2.5),  # not a whole number: ignored
            RuleRow("pack_count", "500:5010", 0),
            RuleRow("pack_components", "700", [{"sku": "G1", "qty": 2}]),
            RuleRow("vat_rate", "G1", 8),
            RuleRow("prices_include_vat", "", True),
            RuleRow("cost_includes_vat", "", False),
        ]
    )
    assert rules.pack_count == {"500:5003": 3}
    assert rules.pack_components["700"] == (Component("G1", 2),)
    assert rules.vat_rate == {"G1": D("0.08")}
    assert (rules.prices_include_vat, rules.cost_includes_vat) == (True, False)
    unset = read_rules([RuleRow("prices_include_vat", "", "yes"), RuleRow("vat_rate", "", 8)])
    assert unset.prices_include_vat is None and unset.vat_rate == {}
    aliased = with_sku_aliases(read_rules([RuleRow("vat_rate", "11", 5)]), {"11": "G1"})
    assert aliased.vat_rate == {"11": D("0.05"), "G1": D("0.05")}


# ===================================================================== splitting an order


def test_an_amount_is_split_by_value_in_whole_cents_and_adds_up():
    assert split_amount(D("100.00"), [D(1), D(1), D(1)]) == [D("33.34"), D("33.33"), D("33.33")]
    assert split_amount(D(13_700), [D(90_000), D(30_000)]) == [D("10275.00"), D("3425.00")]
    assert split_amount(D(10), [D(0), D(0)]) == [D("5.00"), D("5.00")]  # no value: equal shares
    assert split_amount(D(-10), [D(3), D(1)]) == [D("-7.50"), D("-2.50")]  # a reversal
    assert sum(split_amount(D("12345.67"), [D(7), D(11), D(13)])) == D("12345.67")
    assert split_amount(D(0), [D(5)]) == [D("0.00")]
    with pytest.raises(ValueError, match="no lines"):
        split_amount(D(1), [])


def test_every_part_of_the_income_row_is_split_over_the_lines():
    income = IncomeOrder(
        order_ref="r",
        fee_fixed=D(13_700),
        fee_service=D(8_000),
        fee_payment=D(5_400),
        affiliate_commission=D(2_001),
        net_shipping_cost=D(3_000),
        return_ship_refund=D(1_000),
        return_ship_failed=D(500),
        refund_amount=D(7),
        lost_compensation=D(9),
        vat_withheld=D(30),
        pit_withheld=D(10),
        seller_coin_borne=D(100),
        trade_in_bonus_seller=D(40),
        payout=D(50_000),
    )
    shares = split_income(income, [D(90_000), D(30_000)])
    assert [s.fees_total for s in shares] == [D("20325.00"), D("6775.00")]
    assert sum((s.commission for s in shares), D(0)) == D(2_001)
    assert sum((s.return_shipping for s in shares), D(0)) == D(1_500)
    assert sum((s.tax_withheld for s in shares), D(0)) == D(40)
    assert sum((s.payout for s in shares if s.payout is not None), D(0)) == D(50_000)
    assert sum((s.fees_total for s in shares), D(0)) == income.fees_total == D(27_100)


# =============================================================== income actuals in the profit

INCOME = IncomeOrder(
    order_ref=f"{1:032x}",
    fee_fixed=D(13_700),
    fee_service=D(8_000),
    fee_payment=D(5_400),
    affiliate_commission=D(2_000),
    net_shipping_cost=D(3_000),
)
RULES = [RuleRow("sku_cost", "G1", 30_000), RuleRow("packaging_cost", "G1", 2_000)]


def test_the_income_actuals_win_over_the_order_exports_fees_and_the_formula():
    with_income = _profit([_raw(1, fee_fixed=D(1))], RULES, {INCOME.order_ref: INCOME})[2][0][1]
    export_only = _profit([_raw(1, fee_fixed=D(1))], RULES)[2][0][1]
    formula_only = _profit([_raw(1)], RULES)[2][0][1]
    assert with_income.fee_source == "income" and with_income.fees_total == D(27_100)
    assert (export_only.fee_source, export_only.fees_total) == ("actual", D(1))
    assert formula_only.fee_source == "formula"
    # 90000 - 27100 fees - 30000 cogs - 2000 packaging - 2000 commission - 3000 net shipping
    assert with_income.contribution == D(25_900)
    assert dict(with_income.income_costs)["van_chuyen_rong"] == D(3_000)


def test_an_income_commission_counts_even_when_the_order_export_marked_no_affiliate():
    _, _, pairs = _profit([_raw(1, affiliate=False)], RULES, {INCOME.order_ref: INCOME})
    assert pairs[0][1].commission == D(2_000)
    # and an order export commission is not added on top
    _, _, both = _profit(
        [_raw(1, affiliate=True, commission=D(9_999))], RULES, {INCOME.order_ref: INCOME}
    )
    assert both[0][1].commission == D(2_000)


def test_a_two_line_order_is_charged_its_income_split_by_value():
    two = [
        _raw(1),
        _raw(
            1, line_no=1, item_id="sku:T1", sku="T1", deal_price=D(30_000), original_price=D(33_000)
        ),
    ]
    catalog = build_catalog(
        [RawItem("11", "", "Găng", None, "G1", None), RawItem("22", "", "Túi", None, "T1", None)]
    )
    _, _, pairs = _profit(two, RULES, {INCOME.order_ref: INCOME}, catalog=catalog)
    assert [pb.fees_total for _, pb in pairs] == [D("20325.00"), D("6775.00")]
    assert sum((pb.fees_total for _, pb in pairs), D(0)) == INCOME.fees_total
    assert sum((pb.commission for _, pb in pairs), D(0)) == INCOME.affiliate_commission


def test_return_shipping_coins_withheld_tax_and_compensation_move_the_contribution():
    income = IncomeOrder(
        order_ref=f"{1:032x}",
        fee_fixed=D(10_000),
        return_ship_refund=D(4_000),
        return_ship_failed=D(1_000),
        seller_coin_borne=D(2_000),
        vat_withheld=D(900),
        pit_withheld=D(100),
        lost_compensation=D(6_000),
    )
    _, _, pairs = _profit([_raw(1)], RULES, {income.order_ref: income})
    pb = pairs[0][1]
    costs = dict(pb.income_costs)
    assert costs["van_chuyen_tra_hang"] == D(5_000) and costs["xu_nguoi_ban_chiu"] == D(2_000)
    assert costs["thue_gtgt_tncn_khau_tru"] == D(1_000) and costs["den_bu_mat_hang"] == D(-6_000)
    # 90000 - 10000 - 30000 - 2000 - 0 commission - (5000 + 2000 + 1000 - 6000)
    assert pb.contribution == D(46_000)


def test_a_refund_of_a_delivered_line_is_a_cost_but_an_accepted_refund_is_not_deducted_twice():
    income = IncomeOrder(order_ref=f"{1:032x}", fee_fixed=D(10_000), refund_amount=D(20_000))
    delivered = _profit([_raw(1)], RULES, {income.order_ref: income})[2][0][1]
    assert dict(delivered.income_costs)["hoan_tien"] == D(20_000)
    assert delivered.contribution == D(90_000 - 10_000 - 30_000 - 2_000 - 20_000)
    refunded = _profit([_raw(1, status="refunded_accepted")], RULES, {income.order_ref: income})[2][
        0
    ][1]
    assert "hoan_tien" not in dict(refunded.income_costs)
    assert refunded.revenue == D(0) and refunded.contribution == D(-10_000 - 30_000 - 2_000)


def test_orders_without_income_keep_the_formula_and_the_coverage_says_so():
    other = IncomeOrder(order_ref=f"{3:032x}", fee_fixed=D(1))
    _, _, pairs = _profit(
        [_raw(1), _raw(2), _raw(3), _raw(4, status="cancelled")],
        RULES,
        {INCOME.order_ref: INCOME, other.order_ref: other},
    )
    assert [pb.fee_source for _, pb in pairs] == ["income", "formula", "income", "not_charged"]
    cov = income_coverage(pairs)
    assert (cov.orders, cov.with_income) == (3, 2)  # the cancelled order is outside the base
    assert cov.orders_pct == D("66.7") and cov.revenue_pct == D("66.7")
    assert cov.json()["with_income"] == 2


def test_income_coverage_of_an_empty_base_is_unknown_not_zero():
    cov = income_coverage([])
    assert (cov.orders, cov.orders_pct, cov.revenue_pct) == (0, None, None)


# ========================================================================= the seller's VAT


def _vat_profit(flags, rate_rows=(), cost=30_000):
    rows = [
        RuleRow("sku_cost", "G1", cost),
        RuleRow("packaging_cost", "G1", 2_000),
        *flags,
        *rate_rows,
    ]
    return _profit([_raw(1)], rows)[2][0][1]


def test_vat_unset_is_profit_before_vat_and_says_so():
    pb = _vat_profit([])
    assert pb.vat_basis == "before_vat" and pb.vat_output == 0 and pb.revenue == D(90_000)
    label = vat_label(None, None)
    assert label["basis"] == "before_vat" and "trước VAT" in str(label["label"])


def test_prices_that_include_vat_are_taken_out_of_revenue_and_the_margin_base():
    pb = _vat_profit([RuleRow("prices_include_vat", "", True)], [RuleRow("vat_rate", "G1", 8)])
    # 90000 / 1.08 = 83333.33: the VAT inside is 6667
    assert pb.vat_output == D(6_667) and pb.revenue == D(83_333)
    assert pb.vat_basis == "after_vat"
    # the formula fee is on buyer_paid; contribution = 83333 - fees - 30000 - 2000
    plain = _vat_profit([])
    assert pb.contribution == plain.contribution - D(6_667)
    assert pb.margin_rate == pb.profit / D(83_333)


def test_a_cost_that_includes_credited_vat_is_taken_ex_vat():
    pb = _vat_profit(
        [RuleRow("prices_include_vat", "", True), RuleRow("cost_includes_vat", "", True)],
        [RuleRow("vat_rate", "G1", 10)],
        cost=33_000,
    )
    assert pb.vat_input_credit == D(3_000)  # 33000 / 1.1 = 30000
    plain = _vat_profit(
        [RuleRow("prices_include_vat", "", True)], [RuleRow("vat_rate", "G1", 10)], cost=30_000
    )
    assert pb.contribution == plain.contribution


def test_prices_before_vat_need_no_adjustment_and_a_zero_rate_changes_nothing():
    before = _vat_profit([RuleRow("prices_include_vat", "", False)])
    assert before.vat_output == 0 and before.vat_basis == "after_vat"
    zero = _vat_profit([RuleRow("prices_include_vat", "", True)], [RuleRow("vat_rate", "G1", 0)])
    assert zero.vat_output == 0 and zero.contribution == _vat_profit([]).contribution


def test_a_flag_that_needs_a_rate_the_sku_lacks_makes_the_profit_unknown_not_zero_vat():
    pb = _vat_profit([RuleRow("prices_include_vat", "", True)])
    assert pb.contribution is None and "vat_rate" in pb.missing
    cost_only = _vat_profit([RuleRow("cost_includes_vat", "", True)])
    assert cost_only.contribution is None and "vat_rate" in cost_only.missing


def test_withheld_vat_and_pit_are_a_cost_even_for_a_vat_inclusive_company():
    income = IncomeOrder(order_ref=f"{1:032x}", fee_fixed=D(10_000), vat_withheld=D(500))
    rows = [*RULES, RuleRow("prices_include_vat", "", True), RuleRow("vat_rate", "G1", 8)]
    pb = _profit([_raw(1)], rows, {income.order_ref: income})[2][0][1]
    assert dict(pb.income_costs)["thue_gtgt_tncn_khau_tru"] == D(500)
    assert pb.vat_output == D(6_667)


def test_rules_summary_counts_the_new_rules():
    from juli_backend.services.shopee_analytics.rules_view import rules_summary

    summary = rules_summary(
        read_rules([RuleRow("pack_count", "1:2", 3), RuleRow("prices_include_vat", "", True)])
    )
    assert summary["pack_count_count"] == 1 and summary["prices_include_vat"] is True
    assert ProfitRules().prices_include_vat is None
