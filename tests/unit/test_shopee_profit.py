"""``services/shopee_profit``: fees, waterfall, floor, what-if, five numbers, sources.

The worked example (illustrative, per 200.000đ order: giá vốn 100.000, đóng gói 3.000, phí sàn
15% of what the buyer pays, ads 18,4% on ad orders, target margin 10%) is asserted exactly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from juli_backend.services.shopee_profit.fees import (
    FeeBase,
    FeeComponent,
    FeeFormula,
    FeeKind,
    FeeSchedule,
)
from juli_backend.services.shopee_profit.five_numbers import five_numbers, snapshot_from
from juli_backend.services.shopee_profit.floor import FloorInputs, compute_floor
from juli_backend.services.shopee_profit.order_profit import (
    AdsPool,
    OrderLine,
    PromoKind,
    SkuCost,
    line_profit,
    profit_lines,
)
from juli_backend.services.shopee_profit.sources import (
    AdditivityError,
    CellStats,
    SourceMatrix,
    assert_additive,
    build_source_matrix,
)
from juli_backend.services.shopee_profit.whatif import (
    PredictedRange,
    VoucherRule,
    ads_whatif,
    price_change_whatif,
    voucher_whatif,
)

DAY = date(2026, 10, 15)
SCHEDULE = FeeSchedule(
    (FeeFormula(date(2026, 1, 1), (FeeComponent("commission", FeeKind.PCT, rate=D("0.15")),)),)
)
COST = SkuCost("S1", cogs=D(100000), packaging=D(3000))
AD_POOL = AdsPool(sku_ad_cost=D(36800), sku_ad_revenue=D(200000))


def line(oid: str, *, ad: bool = False, **kw: object) -> OrderLine:
    base: dict[str, object] = {
        "order_id": oid,
        "sku": "S1",
        "product_id": "P1",
        "order_date": DAY,
        "qty": 1,
        "original_price": D(200000),
        "deal_price": D(200000),
        "ad_attributed": ad,
    }
    base.update(kw)
    return OrderLine(**base)  # type: ignore[arg-type]


# ------------------------------------------------------------------- floor


def worked_floor() -> FloorInputs:
    return FloorInputs(
        list_price=D(200000),
        cogs=D(100000),
        packaging=D(3000),
        platform_fee_rate=D("0.15"),
        ads_rate=D("0.184"),
        affiliate_rate=D(0),
        target_margin_rate=D("0.10"),
    )


def test_worked_example_floors_and_max_discount() -> None:
    r = compute_floor(worked_floor())
    assert r.absolute_floor == D(121176)
    assert r.operating_floor == D(181979)
    assert r.max_discount_pct == D("9.0")
    assert r.max_discount_amount == D(18000)  # 18.021 rounded DOWN to 1.000
    assert r.reasons == {}


def test_seller_cap_lowers_max_discount() -> None:
    r = compute_floor(
        FloorInputs(**{**worked_floor().__dict__, "seller_max_discount_rate": D("0.05")})
    )
    assert (r.max_discount_pct, r.max_discount_amount) == (D("5.0"), D(10000))


def test_floor_missing_inputs_give_none_and_reason() -> None:
    r = compute_floor(
        FloorInputs(list_price=D(200000), packaging=D(3000), platform_fee_rate=D("0.15"))
    )
    assert r.absolute_floor is None and r.operating_floor is None and r.max_discount_pct is None
    assert r.reasons["absolute_floor"] == "missing:cogs"
    assert r.reasons["max_discount"] == "missing:cogs"


def test_operating_floor_needs_rates_but_absolute_does_not() -> None:
    r = compute_floor(FloorInputs(cogs=D(100000), packaging=D(3000), platform_fee_rate=D("0.15")))
    assert r.absolute_floor == D(121176)
    assert r.operating_floor is None
    assert r.reasons["operating_floor"] == "missing:ads_rate,affiliate_rate,target_margin_rate"


def test_non_positive_denominators_rejected() -> None:
    a = compute_floor(FloorInputs(cogs=D(1), packaging=D(1), platform_fee_rate=D(1)))
    assert a.absolute_floor is None and a.reasons["absolute_floor"] == "denominator_non_positive"
    o = compute_floor(FloorInputs(**{**worked_floor().__dict__, "ads_rate": D("0.80")}))
    assert o.absolute_floor == D(121176)
    assert o.operating_floor is None and o.reasons["operating_floor"] == "denominator_non_positive"
    assert o.max_discount_amount is None


def test_list_below_floor_gives_zero_discount() -> None:
    r = compute_floor(FloorInputs(**{**worked_floor().__dict__, "list_price": D(170000)}))
    assert r.max_discount_amount == D(0) and r.max_discount_pct == D("0.0")
    assert r.reasons["max_discount"] == "list_below_floor"


# ------------------------------------------------------------------ voucher


def voucher_lines(ad_orders: int = 0) -> list[OrderLine]:
    return [line(f"o{i}") for i in range(30)] + [line(f"a{i}", ad=True) for i in range(ad_orders)]


def test_worked_example_voucher_margins_and_break_even() -> None:
    a = voucher_whatif(
        voucher_lines(1),
        {"S1": COST},
        scenario=VoucherRule(D(200000), amount=D(10000)),
        schedule=SCHEDULE,
        ads_pools={"S1": AD_POOL},
        target_margin_rate=D("0.10"),
    ).certain
    assert a.organic.profit_per_order == D(58500) and a.organic.margin_pct == D("30.8")
    assert a.ad_attributed.profit_per_order == D(21700) and a.ad_attributed.margin_pct == D("11.4")
    assert a.ad_margin_below_target is False

    b = voucher_whatif(
        voucher_lines(1),
        {"S1": COST},
        scenario=VoucherRule(D(200000), amount=D(15000)),
        baseline=VoucherRule(D(200000), amount=D(10000)),
        schedule=SCHEDULE,
        ads_pools={"S1": AD_POOL},
        target_margin_rate=D("0.10"),
    ).certain
    assert b.organic.profit_per_order == D(54250) and b.organic.margin_pct == D("29.3")
    assert b.ad_attributed.profit_per_order == D(17450) and b.ad_attributed.margin_pct == D("9.4")
    assert b.ad_margin_below_target is True  # 9,4% < 10% target
    assert b.qualifying_orders == 31
    # 30 organic orders x 5.000 extra (the ad order adds 5.000 too, so compare organic-only)
    only_organic = voucher_whatif(
        voucher_lines(0),
        {"S1": COST},
        scenario=VoucherRule(D(200000), amount=D(15000)),
        baseline=VoucherRule(D(200000), amount=D(10000)),
        schedule=SCHEDULE,
    ).certain
    assert only_organic.extra_cost == D(150000)
    assert only_organic.break_even_extra_orders == 3  # ceil(150.000 / 54.250) = ceil(2,76)
    assert only_organic.discount_pct_of_qualifying == D("7.5")
    assert only_organic.floor_breaches == ()


def test_voucher_predicted_is_caller_range_times_certain_profit() -> None:
    r = voucher_whatif(
        voucher_lines(0),
        {"S1": COST},
        scenario=VoucherRule(D(200000), amount=D(15000)),
        baseline=VoucherRule(D(200000), amount=D(10000)),
        schedule=SCHEDULE,
        predicted_extra_orders=PredictedRange(D(2), D(10), "caller"),
    )
    assert r.predicted is not None
    assert r.predicted.net_profit_low == 2 * D(54250) - D(150000)
    assert r.predicted.net_profit_high == 10 * D(54250) - D(150000)
    assert (
        voucher_whatif(
            voucher_lines(0),
            {"S1": COST},
            scenario=VoucherRule(D(200000), amount=D(15000)),
            schedule=SCHEDULE,
        ).predicted
        is None
    )


def test_voucher_min_spend_excludes_orders_and_flags_floor_breach() -> None:
    lines = [line("big"), line("small", deal_price=D(150000))]
    floors = {"S1": compute_floor(worked_floor())}
    r = voucher_whatif(
        lines,
        {"S1": COST},
        scenario=VoucherRule(D(150000), amount=D(25000)),
        schedule=SCHEDULE,
        floors=floors,
    ).certain
    assert r.qualifying_orders == 2
    kinds = {(b.kind, b.floor, b.min_unit_price) for b in r.floor_breaches}
    assert ("operating", D(181979), D(125000)) in kinds
    assert ("absolute", D(121176), D(125000)) not in kinds  # 125.000 >= 121.176
    none = voucher_whatif(
        lines, {"S1": COST}, scenario=VoucherRule(D(300000), amount=D(25000)), schedule=SCHEDULE
    ).certain
    assert (
        none.qualifying_orders == 0 and none.extra_cost == 0 and none.break_even_extra_orders == 0
    )


def test_pct_voucher_with_cap_and_multi_line_allocation_sums_exactly() -> None:
    lines = [
        line("m", deal_price=D(100000)),
        OrderLine("m", "S2", "P2", DAY, 1, D(50001), D(50001)),
    ]
    rule = VoucherRule(D(100000), pct=D("0.10"), max_discount=D(12000))
    r = voucher_whatif(
        lines, {"S1": COST, "S2": SkuCost("S2", D(1), D(1))}, scenario=rule, schedule=SCHEDULE
    ).certain
    assert r.voucher_cost_scenario == D(12000)


def test_voucher_missing_cost_is_counted_not_zeroed() -> None:
    r = voucher_whatif(
        [line("x")],
        {"S1": SkuCost("S1", None, D(3000))},
        scenario=VoucherRule(D(1), amount=D(5000)),
        schedule=SCHEDULE,
    ).certain
    assert r.orders_missing_cost == 1
    assert r.organic.profit_per_order is None
    assert r.break_even_extra_orders is None and r.break_even_reason == "profit_per_order_unknown"


def test_voucher_rule_needs_exactly_one_of_amount_pct() -> None:
    with pytest.raises(ValueError):
        VoucherRule(D(1))
    with pytest.raises(ValueError):
        VoucherRule(D(1), amount=D(1), pct=D("0.1"))


# ------------------------------------------------------------ price & ads


def test_price_change_break_even() -> None:
    lines = [line(f"o{i}") for i in range(10)]
    r = price_change_whatif(
        lines,
        {"S1": COST},
        sku="S1",
        new_deal_price=D(190000),
        schedule=SCHEDULE,
        floors={"S1": compute_floor(worked_floor())},
    ).certain
    assert r.profit_per_order_before == D(200000 - 30000 - 103000)
    assert r.profit_per_order_after == D(190000 - 28500 - 103000)
    assert r.profit_delta_same_volume == D(-8500 * 0 - 10 * (67000 - 58500))
    assert r.break_even_extra_orders == 2  # ceil(85.000 / 58.500)
    assert r.floor_breaches == ()
    low = price_change_whatif(
        lines,
        {"S1": COST},
        sku="S1",
        new_deal_price=D(170000),
        schedule=SCHEDULE,
        floors={"S1": compute_floor(worked_floor())},
    ).certain
    assert [b.kind for b in low.floor_breaches] == ["operating"]
    up = price_change_whatif(
        lines, {"S1": COST}, sku="S1", new_deal_price=D(210000), schedule=SCHEDULE
    ).certain
    assert up.break_even_extra_orders == 0
    dead = price_change_whatif(
        lines, {"S1": COST}, sku="S1", new_deal_price=D(100000), schedule=SCHEDULE
    ).certain
    assert dead.break_even_extra_orders is None and dead.break_even_reason


def test_ads_whatif_break_even_roas() -> None:
    lines = [line(f"a{i}", ad=True) for i in range(5)]
    pool = AdsPool(D(36800 * 5), D(200000 * 5))
    r = ads_whatif(
        lines,
        {"S1": COST},
        sku="S1",
        pool=pool,
        new_budget=D(150000),
        target_roas=D(4),
        schedule=SCHEDULE,
        predicted_ad_revenue=PredictedRange(D(1000000), D(1500000)),
    ).certain
    assert r.current_roas is not None and r.current_roas.quantize(D("0.01")) == D("5.43")
    assert r.profit_before_ads == 5 * (200000 - 30000 - 103000)
    assert r.break_even_roas == D(1000000) / D(335000)
    assert r.max_budget_for_target_roas == D(250000)
    assert r.profit_at_current_revenue == D(335000) - D(150000)


# --------------------------------------------------------------- waterfall


def test_waterfall_steps_and_missing_cases() -> None:
    ln = line(
        "w",
        deal_price=D(180000),
        shop_voucher_share=D(5000),
        bundle_discount=D(1000),
        promo_kind=PromoKind.PROMOTION,
    )
    pb = line_profit(ln, COST, schedule=SCHEDULE)
    assert (pb.list_value, pb.promo_discount, pb.voucher, pb.bundle) == (
        D(200000),
        D(20000),
        D(5000),
        D(1000),
    )
    assert pb.buyer_paid == D(174000) and pb.fees_total == D(26100) and pb.fee_source == "formula"
    assert pb.profit == D(174000 - 26100 - 103000)

    actual = line_profit(line("w", actual_fees=D(31000)), COST, schedule=None)
    assert actual.fee_source == "actual" and actual.profit == D(200000 - 31000 - 103000)

    assert line_profit(line("w"), None, schedule=SCHEDULE).missing == ("cogs", "packaging")
    assert line_profit(line("w"), COST).missing == ("fee_formula",)
    no_pool = line_profit(line("w", ad=True), COST, schedule=SCHEDULE)
    assert no_pool.profit is None and no_pool.missing == ("ads_allocation",)
    aff = line_profit(line("w", affiliate=True), COST, schedule=SCHEDULE)
    assert aff.missing == ("commission",)
    assert line_profit(
        line("w", affiliate=True), COST, schedule=SCHEDULE, affiliate_rate=D("0.05")
    ).profit == D(200000 - 30000 - 103000 - 10000)
    assert line_profit(
        line("w", affiliate=True, commission=D(7000)), COST, schedule=SCHEDULE
    ).profit == D(200000 - 30000 - 103000 - 7000)


def test_ads_allocation_is_share_of_sku_ad_revenue() -> None:
    pool = AdsPool(D(100000), D(500000))
    a = line_profit(line("a", ad=True), COST, schedule=SCHEDULE, ads_pool=pool)
    assert a.ads == D(40000)  # 100.000 x 200.000 / 500.000
    assert line_profit(
        line("a", ad=True), COST, schedule=SCHEDULE, ads_pool=AdsPool(D(1), D(0))
    ).missing == ("ads_allocation",)


# -------------------------------------------------------------------- fees


def test_fee_components_bases_and_caps() -> None:
    ln = line("f", deal_price=D(180000), shop_voucher_share=D(10000))
    f = FeeFormula(
        date(2026, 1, 1),
        (
            FeeComponent("commission", FeeKind.PCT, FeeBase.BUYER_PAID, rate=D("0.10")),
            FeeComponent("service", FeeKind.PCT, FeeBase.LIST_PRICE, rate=D("0.05"), cap=D(8000)),
            FeeComponent("payment", FeeKind.PCT, FeeBase.ORDER_VALUE, rate=D("0.0491")),
            FeeComponent("fixed", FeeKind.FIXED, amount=D(1650)),
        ),
    )
    r = f.fee(ln)
    assert dict(r.components) == {
        "commission": D(17000),
        "service": D(8000),
        "payment": D(8838),
        "fixed": D(1650),
    }
    assert r.total == D(35488)
    assert f.pct_rate_on_buyer_paid == D("0.10") and f.fixed_per_order == D(1650)


def test_fee_versioning_picks_formula_valid_on_order_date() -> None:
    old = FeeFormula(date(2026, 1, 1), (FeeComponent("c", FeeKind.PCT, rate=D("0.10")),))
    new = FeeFormula(date(2026, 10, 16), (FeeComponent("c", FeeKind.PCT, rate=D("0.12")),))
    sched = FeeSchedule((new, old))
    assert sched.formula_on(date(2025, 12, 31)) is None
    assert sched.formula_on(date(2026, 10, 15)) is old
    assert sched.formula_on(date(2026, 10, 16)) is new
    before = line_profit(line("v", order_date=date(2026, 10, 15)), COST, schedule=sched)
    after = line_profit(line("v", order_date=date(2026, 10, 16)), COST, schedule=sched)
    assert (before.fees_total, after.fees_total) == (D(20000), D(24000))
    assert line_profit(line("v", order_date=date(2025, 1, 1)), COST, schedule=sched).profit is None
    with pytest.raises(ValueError):
        FeeSchedule((old, old))


def test_fee_component_validation() -> None:
    with pytest.raises(ValueError):
        FeeComponent("x", FeeKind.PCT)
    with pytest.raises(ValueError):
        FeeComponent("x", FeeKind.PCT, rate=D(1))
    with pytest.raises(ValueError):
        FeeComponent("x", FeeKind.FIXED)


# ------------------------------------------------------------ five numbers


def test_five_numbers_before_after_and_cap() -> None:
    cost = {"S1": COST}
    b = profit_lines([line(f"b{i}") for i in range(10)], cost, schedule=SCHEDULE)
    a = profit_lines(
        [line(f"a{i}", deal_price=D(180000)) for i in range(12)], cost, schedule=SCHEDULE
    )
    fn = five_numbers(snapshot_from(b, D(0)), snapshot_from(a, D(400000)), spend_cap=D(500000))
    assert fn.discount.vnd_before == 0 and fn.discount.pct_after == D("10.0")
    assert fn.extra_revenue == D(12 * 180000 - 10 * 200000)
    # chi = ads 400.000 + promo (12 x 20.000 off list) = 640.000; before chi = 0 (contract 5.2)
    assert fn.extra_spend == D(640000)
    assert fn.extra_revenue_per_extra_spend == D(160000) / D(640000)
    assert fn.chi_status == "per_vnd" and fn.below_one is True
    assert fn.margin.pct_before == D("33.5")  # 67.000 / 200.000
    assert fn.orders == (10, 12, D("20.0"))
    assert fn.aov.vnd_before == D(200000) and fn.aov.vnd_after == D(180000)
    assert fn.aov_change_pct == D("-10.0")
    assert fn.spend_cap is not None  # chi per day 640.000 against a 500.000 cap
    assert (fn.spend_cap.remaining, fn.spend_cap.used_pct, fn.spend_cap.over_cap) == (
        D(-140000),
        D("128.0"),
        True,
    )


def test_five_numbers_giam_chi_when_chi_does_not_rise() -> None:
    cost = {"S1": COST}
    b = profit_lines(
        [line(f"b{i}", deal_price=D(180000)) for i in range(10)], cost, schedule=SCHEDULE
    )
    a = profit_lines([line(f"a{i}") for i in range(10)], cost, schedule=SCHEDULE)
    fn = five_numbers(snapshot_from(b, D(0)), snapshot_from(a, D(0)))
    assert fn.extra_spend == D(-200000) and fn.chi_status == "giam_chi"
    assert fn.extra_revenue_per_extra_spend is None and fn.below_one is False


def test_five_numbers_unknown_profit_is_none_not_zero() -> None:
    p = profit_lines([line("x")], {"S1": SkuCost("S1", None, None)}, schedule=SCHEDULE)
    fn = five_numbers(snapshot_from(p, D(0)), snapshot_from(p, D(0)))
    assert fn.margin.vnd_after is None and fn.margin.pct_after is None
    assert fn.extra_revenue_per_extra_spend is None and fn.spend_cap is None
    assert fn.chi_status == "undefined"


# ----------------------------------------------------------------- sources


def mixed_lines() -> list[OrderLine]:
    return [
        line("1"),
        line("2", ad=True, shop_voucher_share=D(10000)),
        line("3", promo_kind=PromoKind.FLASH_SALE, deal_price=D(150000)),
        line("4", bundle_discount=D(5000), affiliate=True, commission=D(8000)),
        line("5", ad=True),
        OrderLine("6", "S2", "P2", DAY, 2, D(50000), D(45000)),
        OrderLine("6", "S1", "P1", DAY, 1, D(200000), D(200000)),
        OrderLine("6", "S1", "P1", DAY, 1, D(200000), D(200000), shop_voucher_share=D(1)),
    ]


def mixed_pairs() -> list:
    costs = {"S1": COST, "S2": SkuCost("S2", None, D(1000))}  # S2 cost unknown
    return profit_lines(mixed_lines(), costs, schedule=SCHEDULE, ads_pools={"S1": AD_POOL})


def test_sources_lever_sums_to_totals() -> None:
    m = build_source_matrix(mixed_pairs())
    assert_additive(m)
    assert sum(c.orders for c in m.lever.values()) == sum(c.orders for c in m.totals.values()) == 7
    assert sum(c.gmv for c in m.lever.values()) == sum(c.gmv for c in m.totals.values())
    p1 = m.totals["P1"]
    assert p1.orders == 6  # order 6 merges its two P1 lines into one pair
    assert m.lever[("P1", "khuyen_mai")].orders == 1  # flash sale price
    assert m.lever[("P1", "combo")].orders == 1
    assert m.lever[("P1", "voucher")].orders == 2  # order 2 and order 6 (merged voucher)
    assert m.lever[("P1", "khong_uu_dai")].orders == 2
    # ads overlay: orders 2 and 5, inside their lever cells, never added on top
    assert m.ads["P1"].orders == 2
    # unknown cost -> excluded from profit, counted
    assert m.totals["P2"].orders_missing_profit == 1 and m.totals["P2"].profit == 0
    assert m.totals["P2"].gmv == D(90000) and m.totals["P2"].aov == D(90000)


def test_sources_cell_margin_and_aov() -> None:
    m = build_source_matrix(mixed_pairs())
    cell = m.lever[("P1", "khuyen_mai")]
    assert cell.orders == 1 and cell.gmv == D(150000) and cell.aov == D(150000)
    assert cell.profit == D(150000 - 22500 - 103000) and cell.margin_pct == D("16.3")
    assert cell.contribution == cell.profit  # no line ad split on this order


def test_additivity_check_raises_on_a_corrupt_matrix() -> None:
    m = build_source_matrix(mixed_pairs())
    bad = SourceMatrix({**m.lever, ("P1", "voucher"): CellStats(orders=99)}, m.ads, m.totals)
    with pytest.raises(AdditivityError):
        assert_additive(bad)


@pytest.mark.parametrize("n", [0, 1, 7, 40])
def test_additivity_property_over_generated_lines(n: int) -> None:
    kinds = list(PromoKind)
    gen: list[OrderLine] = []
    for i in range(n):
        gen.append(
            OrderLine(
                order_id=f"o{i % 13}",
                sku=f"S{i % 3}",
                product_id=f"P{i % 3}",
                order_date=DAY,
                qty=1 + i % 3,
                original_price=D(100000),
                deal_price=D(100000 - 1000 * (i % 5)),
                shop_voucher_share=D(1000 * (i % 2)),
                bundle_discount=D(500 * (i % 4 == 0)),
                promo_kind=kinds[i % len(kinds)],
                ad_attributed=i % 3 == 0,
            )
        )
    costs = {f"S{k}": SkuCost(f"S{k}", None if k == 2 else D(50000), D(2000)) for k in range(3)}
    pools = {f"S{k}": AdsPool(D(10000), D(1000000)) for k in range(3)}
    m = build_source_matrix(profit_lines(gen, costs, schedule=SCHEDULE, ads_pools=pools))
    grand = sum((c.gmv for c in m.totals.values()), D(0))
    assert sum((c.gmv for c in m.lever.values()), D(0)) == grand
    assert sum(c.orders for c in m.lever.values()) == sum(c.orders for c in m.totals.values())
    assert sum((c.profit for c in m.lever.values()), D(0)) == sum(
        (c.profit for c in m.totals.values()), D(0)
    )
    assert all(m.ads[p].orders <= m.totals[p].orders for p in m.ads)
