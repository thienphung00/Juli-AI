"""P90 contract alignment (fasttrack/contracts/p90-metrics.md): flows, fixed fees once per
order, product / shop profit, the five numbers and the voucher what-if usage model.

Everything is synthetic. The end-to-end shop is hand-computed in the comments.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D
from typing import Any

import pytest

from juli_backend.services.shopee_profit.fees import (
    FeeComponent,
    FeeFormula,
    FeeKind,
    FeeSchedule,
    shopee_vn_non_mall,
)
from juli_backend.services.shopee_profit.five_numbers import five_numbers, snapshot_from
from juli_backend.services.shopee_profit.flows import (
    RESIDUAL_KEY,
    Flow,
    FlowAdsRow,
    FlowError,
    FlowRow,
    FlowSource,
    build_flow_tables,
)
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    OrderStatus,
    PromoKind,
    SkuCost,
    profit_lines,
)
from juli_backend.services.shopee_profit.shop_profit import (
    AdCampaign,
    AdsFigures,
    pools_from_product_spend,
    reconcile_gmv,
    shop_profit,
)
from juli_backend.services.shopee_profit.sources import assert_additive, build_source_matrix
from juli_backend.services.shopee_profit.whatif import PredictedRange, VoucherRule, voucher_whatif

DAY = date(2026, 10, 15)
SCHEDULE = FeeSchedule(
    (
        FeeFormula(
            date(2026, 1, 1),
            (
                FeeComponent("commission", FeeKind.PCT, rate=D("0.15")),
                FeeComponent("fixed", FeeKind.FIXED, amount=D(1650)),
            ),
        ),
    )
)


def ol(oid: str, sku: str, product: str, qty: int, orig: int, deal: int, **kw: Any) -> OrderLine:
    return OrderLine(oid, sku, product, DAY, qty, D(orig), D(deal), **kw)


# ------------------------------------------------------------ fixed fee once


def test_fixed_fee_is_charged_once_per_order_split_by_value() -> None:
    lines = [ol("o", "S1", "P1", 1, 200000, 200000), ol("o", "S2", "P2", 1, 100000, 100000)]
    costs = {"S1": SkuCost("S1", D(1), D(0)), "S2": SkuCost("S2", D(1), D(0))}
    pairs = profit_lines(lines, costs, schedule=SCHEDULE)
    fixed = [dict(pb.fees or ())["fixed"] for _, pb in pairs]
    assert fixed == [D(1100), D(550)] and sum(fixed) == D(1650)  # once, 2:1 by value
    # a single-line order still pays it in full
    solo = profit_lines([lines[0]], costs, schedule=SCHEDULE)
    assert dict(solo[0][1].fees or ())["fixed"] == D(1650)
    # shares always add up to the charge, even when it does not divide evenly
    odd = [ol("p", "S1", "P1", 1, 1, 1000 + i) for i in range(3)]
    odd_fixed = [
        dict(pb.fees or ())["fixed"] for _, pb in profit_lines(odd, costs, schedule=SCHEDULE)
    ]
    assert sum(odd_fixed) == D(1650)


# ------------------------------------------------------------------- flows


def flow_rows() -> list[FlowRow]:
    S = FlowSource
    return [
        FlowRow("P1", S.THE_SAN_PHAM_TOTAL, orders=2, gmv=D(560000), views=1000, clicks=100),
        FlowRow("P1", S.TRANG_SHOP, orders=1, gmv=D(200000), views=300, clicks=40),
        FlowRow("P2", S.LIVE, orders=1, gmv=D(100000), views=500, clicks=50),
        FlowRow("P2", S.VIDEO, orders=1, gmv=D(100000), views=400, clicks=20),
        FlowRow("P3", S.THE_SAN_PHAM_TOTAL, orders=1, gmv=D(150000), views=300, clicks=30),
        FlowRow("P4", S.LIEN_KET, orders=1, gmv=D(250000), views=None, clicks=25),
        FlowRow("P5", S.THE_SAN_PHAM_TOTAL, orders=1, gmv=D(130000), views=200, clicks=10),
    ]


def test_flows_split_the_san_pham_khac_and_add_up_with_a_residual_row() -> None:
    t = build_flow_tables(
        flow_rows(),
        shop_gmv=D(1310000),
        shop_orders=8,
        product_totals={"P1": (D(560000), 2)},
        ads=[FlowAdsRow("P1", Flow.THE_SAN_PHAM_KHAC, D(50000), D(360000), 1)],
    )
    shop = t.shop
    assert [r.key for r in shop.rows] == [
        "the_san_pham_khac",
        "trang_shop",
        "live",
        "video",
        "lien_ket",
        RESIDUAL_KEY,
    ]
    tsp = shop.row("the_san_pham_khac")
    assert tsp is not None
    # P1: 1000-300 / 100-40 / 2-1 / 560.000-200.000 ; P3 and P5 whole
    assert (tsp.views, tsp.clicks, tsp.orders, tsp.gmv) == (1200, 100, 3, D(640000))
    trang = shop.row("trang_shop")
    assert trang is not None and trang.gmv == D(200000) and trang.views == 300
    # flows + residual == shop GMV and orders exactly; the residual is the gap, not a scaling
    assert shop.gmv_sum == D(1310000) and shop.orders_sum == 8
    res = shop.residual
    assert res is not None and res.is_residual and res.gmv == D(20000) and res.orders == 1
    assert res.views is None and res.ctr is None
    # ads are an overlay on the flow it lands in, never part of the sum
    assert tsp.ads is not None and tsp.ads.spend == D(50000) and tsp.ads.roas == D("7.2")
    assert shop.gmv_sum == sum((r.gmv for r in shop.rows), D(0))
    # product table adds up to the product's own total
    p1 = t.products["P1"]
    assert p1.gmv_sum == D(560000) and p1.residual is None


def test_flow_ratios_and_exact_identity() -> None:
    t = build_flow_tables(flow_rows(), shop_gmv=D(1310000), shop_orders=8)
    for row in t.shop.rows:
        if row.is_residual or row.views is None or row.clicks is None:
            continue
        assert row.gmv_by_identity() == row.gmv  # views x CTR x CTOR x AOV, exact
    tsp = t.shop.row("the_san_pham_khac")
    assert tsp is not None
    assert tsp.ctr == D(100) / D(1200) and tsp.ctor == D(3) / D(100)
    assert tsp.aov == D(640000) / D(3)
    lk = t.shop.row("lien_ket")
    assert lk is not None and lk.views is None and lk.ctr is None  # no view definition -> no CTR
    assert lk.ctor == D(1) / D(25)


def test_flow_child_larger_than_parent_is_rejected() -> None:
    S = FlowSource
    rows = [
        FlowRow("P", S.THE_SAN_PHAM_TOTAL, 1, D(100), 10, 5),
        FlowRow("P", S.TRANG_SHOP, 2, D(100), 10, 5),
    ]
    with pytest.raises(FlowError):
        build_flow_tables(rows, shop_gmv=D(100))


# ----------------------------------------------- end-to-end synthetic shop


def shop_lines() -> list[OrderLine]:
    P = PromoKind
    return [
        ol("o1", "S1", "P1", 1, 200000, 200000),
        ol("o1", "S2", "P2", 1, 100000, 100000),
        ol("o2", "S1", "P1", 2, 200000, 180000, promo_kind=P.PROMOTION, ad_attributed=True),
        ol("o3", "S3", "P3", 1, 150000, 150000, shop_voucher_share=D(10000)),
        ol("o4", "S4", "P4", 1, 250000, 250000, bundle_discount=D(5000), affiliate=True,
           commission=D(8000)),
        ol("o5", "S5", "P5", 1, 150000, 150000),  # SKU without giá vốn
        ol("o6", "S2", "P2", 1, 100000, 100000),
    ]  # fmt: skip


SHOP_COSTS = {
    "S1": SkuCost("S1", D(100000), D(3000)),
    "S2": SkuCost("S2", D(40000), D(2000)),
    "S3": SkuCost("S3", D(80000), D(2000)),
    "S4": SkuCost("S4", D(90000), D(3000)),
    "S5": SkuCost("S5", None, D(2000)),
}
CAMPAIGNS = [
    AdCampaign("C1", D(50000), revenue=D(400000)),
    AdCampaign("C2", D(30000), revenue=D(0)),  # no revenue, no product rows
]
PRODUCT_ADS = {"P1": D(50000)}


def test_end_to_end_shop_consistency() -> None:
    pairs = profit_lines(shop_lines(), SHOP_COSTS, schedule=SCHEDULE)

    # fixed fee once per order: 6 orders x 1.650
    fixed_total = sum(dict(pb.fees or ())["fixed"] for _, pb in pairs)
    assert fixed_total == D(6 * 1650)

    # contributions (hand-computed): o1a 65.900, o1b 42.450, o2 101.350, o3 35.350,
    # o4 105.600, o6 41.350 ; o5 unknown (no giá vốn)
    got = [pb.contribution for _, pb in pairs]
    assert got == [
        D(65900), D(42450), D(101350), D(35350), D(105600), None, D(41350)
    ]  # fmt: skip

    sp = shop_profit(
        pairs,
        campaigns=CAMPAIGNS,
        product_ad_spend=PRODUCT_ADS,
        other_marketing_costs=D(5000),
        export_gmv=D(1310000),
    )
    # contribution 392.000 ; ads 80.000 (all campaigns) ; other 5.000
    assert sp.contribution == D(392000) and sp.total_ad_spend == D(80000)
    # coverage 88,4 % -> shop profit in dong is NOT shown (contract 9); components stay
    assert sp.profit is None and sp.profit_on_covered == D(307000)
    assert sp.unattributed_ad_spend == D(30000) and sp.zero_revenue_campaign_spend == D(30000)
    assert sp.ad_spend_consistent is True
    # sum(product profit) - unattributed ads - other costs == shop profit components
    assert sum((p.profit for p in sp.products.values()), D(0)) == D(342000)
    assert (
        sum((p.profit for p in sp.products.values()), D(0))
        - sp.unattributed_ad_spend
        - sp.other_marketing_costs
        == sp.profit_on_covered
    )
    assert sp.products["P1"].profit == D(167250) - D(50000)
    assert sp.products["P1"].break_even_roas == D(560000) / D(167250)
    # margin base is buyer_paid, never GMV. Contract 9 partial formula, covered share
    # s = 1.145.000 / 1.295.000 = 229/259:
    #   covered ads = P1 50.000 (fully covered) + unattributed 30.000 x s (26.525,0965)
    #   numerator   = 392.000 - 76.525,0965 - 5.000 x s (4.420,8494) = 311.054,054 = 80.563.000/259
    #   margin      = 311.054,054 / 1.145.000 = 27,2 %   (not 26,8 %: ads are not all charged)
    assert sp.buyer_paid == D(1295000) and sp.gmv == D(1310000)
    assert sp.buyer_paid_covered == D(1145000)
    assert abs(sp.covered_ad_charge - (D(50000) + D(6870000) / D(259))) < D("0.0001")
    assert sp.covered_margin_profit is not None
    assert abs(sp.covered_margin_profit - D(80563000) / D(259)) < D("0.0001")
    assert sp.margin_pct == D("27.2")
    # coverage < 100 % is flagged, not extrapolated
    assert sp.cost_coverage_pct == D("88.4") and sp.margin_is_partial is True
    assert sp.products["P5"].is_partial and sp.products["P5"].margin_rate is None
    assert sp.missing == {"cogs": 1}
    # GMV reconciliation: lines vs export
    assert sp.reconciliation.warn is False and sp.reconciliation.gap == 0
    bad = reconcile_gmv(pairs, D(1250000))
    assert bad.warn is True and bad.gap == D(60000)
    edge = reconcile_gmv(pairs, D(1310000) / D("1.02"))
    assert edge.warn is True
    assert reconcile_gmv(pairs, D(1290000)).warn is False  # 1,55 %

    # levers add up (each line exactly one) and the ads overlay stays inside
    m = build_source_matrix(pairs)
    assert_additive(m)
    assert sum((c.gmv for c in m.lever.values()), D(0)) == D(1310000)
    assert m.lever[("P1", "khuyen_mai")].orders == 1
    assert m.lever[("P3", "voucher")].orders == 1 and m.lever[("P4", "combo")].orders == 1

    # flows add up to the shop GMV (aggregates, not order lines)
    flows = build_flow_tables(flow_rows(), shop_gmv=sp.gmv, shop_orders=8)
    assert flows.shop.gmv_sum == sp.gmv

    # five numbers: before = o1 + o6 with no spend ; after = whole shop with real ad spend
    by_id = {ln.order_id: (ln, pb) for ln, pb in pairs if ln.sku in ("S1", "S2")}
    before_pairs = [p for p in pairs if p[0].order_id in ("o1", "o6")]
    assert len(by_id) > 0
    fn = five_numbers(
        snapshot_from(before_pairs, D(0)),
        snapshot_from(
            pairs,
            sp.total_ad_spend,
            other_costs=sp.other_marketing_costs,
            ad_spend_covered=sp.covered_ad_charge,
        ),
        spend_cap=D(200000),
    )
    # 1: (promo 40.000 + voucher 10.000 + combo 5.000) / list 1.350.000
    assert fn.discount.vnd_after == D(55000) and fn.discount.pct_after == D("4.1")
    assert fn.discount.vnd_before == 0
    # 2: dGMV 1.310.000 - 400.000 = 910.000 ; dchi = ads 80.000 + 10.000 + 40.000 + 5.000 + 8.000
    assert fn.extra_revenue == D(910000) and fn.extra_spend == D(143000)
    assert fn.extra_revenue_per_extra_spend == D(910000) / D(143000)
    assert fn.extra_revenue_pct == D("227.5") and fn.chi_status == "per_vnd"
    assert fn.below_one is False
    # 3: margin = profit / buyer_paid (covered) ; before 149.700 / 400.000
    assert fn.margin.vnd_before == D(149700) and fn.margin.pct_before == D("37.4")
    # after: partial coverage -> no dong figure, margin 27,2 % on 88,4 % of revenue
    assert fn.margin.vnd_after is None and fn.margin.pct_after == D("27.2")
    assert fn.margin_is_partial is True and fn.cost_coverage_pct == D("88.4")
    # 4 and 5
    assert fn.orders == (2, 6, D("200.0"))
    assert fn.aov.vnd_before == D(200000) and fn.aov.vnd_after == D(1310000) / D(6)
    # spend per day vs cap
    assert fn.spend_cap is not None and fn.spend_cap.remaining == D(57000)
    assert fn.spend_cap.used_pct == D("71.5") and fn.spend_cap.over_cap is False


def test_line_ad_split_reconciles_to_the_ads_report() -> None:
    lines = shop_lines()
    pools = pools_from_product_spend(lines, PRODUCT_ADS)
    pairs = profit_lines(lines, SHOP_COSTS, schedule=SCHEDULE, ads_pools=pools)
    sp = shop_profit(pairs, campaigns=CAMPAIGNS, product_ad_spend=PRODUCT_ADS)
    p1 = sp.products["P1"]
    assert p1.line_ads_display == D(50000) and p1.line_ads_gap == 0
    # the display split does not change product profit (contribution - report spend)
    assert p1.profit == D(117250)


# -------------------------------------------------------------- voucher


def history(n: int = 40, deal: int = 250000) -> list[OrderLine]:
    return [
        OrderLine(f"h{i}", "S1", "P1", DAY + timedelta(days=i % 30), 1, D(deal), D(deal))
        for i in range(n)
    ]


def run(rule: VoucherRule, **kw: Any) -> Any:
    base: dict[str, Any] = {"schedule": SCHEDULE, "ad_spend": D(0)}
    base.update(kw)
    return voucher_whatif(
        history(),
        {"S1": SkuCost("S1", D(100000), D(3000))},
        scenario=rule,
        **base,
    ).certain


def test_voucher_usage_limit_sweep_is_monotonic_and_consistent() -> None:
    results = {
        lim: run(VoucherRule(D(200000), amount=D(10000), usage_limit=lim))
        for lim in (5, 20, 40, 100, None)
    }
    costs = [results[k].voucher_cost_scenario for k in (5, 20, 40, 100)]
    assert costs == [D(50000), D(200000), D(400000), D(400000)]  # 40 qualifying orders
    assert results[100].voucher_cost_scenario == results[None].voucher_cost_scenario
    assert results[20].usage_capped is True and results[100].usage_capped is False
    assert results[20].used_scenario == 20 and results[100].used_scenario == 40
    assert results[20].expected_qualifying_orders == 40 and results[20].usage_rate == 1
    assert results[20].usage_rate_source == "default_1"
    be = [results[k].break_even_extra_orders for k in (5, 20, 40, 100)]
    assert all(x is not None for x in be) and be == sorted(x for x in be if x is not None)
    for r in results.values():
        # five numbers agree with the cost: dchi == voucher cost, and profit drops by cost less
        # the 15 % fee that is not charged on the discounted amount
        f = r.five_numbers
        assert f.extra_spend == r.voucher_cost_scenario
        # contract 9: no volume in the certain layer -> number 2 is not shown
        assert f.extra_revenue == 0 and f.extra_revenue_per_extra_spend is None
        assert f.chi_status == "needs_volume" and f.below_one is False
        assert f.margin.vnd_before is not None and f.margin.vnd_after is not None
        assert f.margin.vnd_before - f.margin.vnd_after == r.extra_cost * D("0.85")
        assert f.orders[0] == f.orders[1] == 40
    spend = [results[k].five_numbers.extra_spend for k in (5, 20, 40, 100)]
    assert spend == sorted(spend)
    # discount % (item 1) rises with usage and equals used x 10.000 / list GMV
    assert results[20].five_numbers.discount.vnd_after == D(200000)
    assert results[20].five_numbers.discount.pct_after == D("2.0")  # 200.000 / 10.000.000


def test_voucher_value_sweep_10k_vs_15k_at_min_200k() -> None:
    a = run(VoucherRule(D(200000), amount=D(10000), usage_limit=20))
    b = run(VoucherRule(D(200000), amount=D(15000), usage_limit=20))
    c = run(VoucherRule(D(200000), amount=D(15000), usage_limit=100))
    assert (a.voucher_cost_scenario, b.voucher_cost_scenario, c.voucher_cost_scenario) == (
        D(200000),
        D(300000),
        D(600000),
    )
    assert a.organic.contribution_per_order is not None
    assert b.organic.contribution_per_order is not None
    # per-order contribution falls by 5.000 x (1 - 15 % fee)
    assert a.organic.contribution_per_order - b.organic.contribution_per_order == D(4250)
    assert a.break_even_extra_orders is not None and b.break_even_extra_orders is not None
    # no baseline: contribution/order 99.350 and 95.100 (after the 1.650 fixed fee)
    # -> ceil(200.000 / 99.350) and ceil(300.000 / 95.100)
    assert (a.break_even_extra_orders, b.break_even_extra_orders) == (3, 4)
    # against a 10k baseline with the same limit: extra cost and break-even follow the limit
    base = VoucherRule(D(200000), amount=D(10000), usage_limit=20)
    ex20 = run(VoucherRule(D(200000), amount=D(15000), usage_limit=20), baseline=base)
    ex100 = run(VoucherRule(D(200000), amount=D(15000), usage_limit=100), baseline=base)
    assert (ex20.extra_cost, ex100.extra_cost) == (D(100000), D(400000))
    assert ex20.break_even_extra_orders == 2  # ceil(100.000 / 95.100)
    assert ex100.break_even_extra_orders == 5  # ceil(400.000 / 95.100)
    assert ex20.break_even_extra_orders < ex100.break_even_extra_orders
    assert ex100.five_numbers.extra_spend == D(400000)


def test_voucher_usage_rate_days_scaling_and_spend_cap() -> None:
    half = run(VoucherRule(D(200000), amount=D(10000)), usage_rate=D("0.5"))
    assert half.usage_rate == D("0.5") and half.usage_rate_source == "input"
    assert half.used_scenario == 20 and half.voucher_cost_scenario == D(200000)
    # 60 days doubles Q (80) ; limit 50 binds, u = 1
    longer = run(VoucherRule(D(200000), amount=D(10000), usage_limit=50), voucher_days=60)
    assert longer.expected_qualifying_orders == 80 and longer.used_scenario == 50
    assert longer.voucher_cost_scenario == D(500000) and longer.usage_capped is True
    # spend per day against the daily cap
    capped = run(VoucherRule(D(200000), amount=D(10000), usage_limit=20), spend_cap_per_day=D(5000))
    assert capped.voucher_spend_per_day == D(200000) / D(30)
    assert capped.voucher_spend_check is not None and capped.voucher_spend_check.over_cap is True
    with pytest.raises(ValueError):
        run(VoucherRule(D(200000), amount=D(10000)), usage_rate=D(2))


def test_voucher_per_user_limit_is_reported_not_enforced() -> None:
    plain = run(VoucherRule(D(200000), amount=D(10000), usage_limit=20))
    limited = run(VoucherRule(D(200000), amount=D(10000), usage_limit=20, per_user_limit=1))
    assert plain.per_user_limit_status is None
    assert limited.per_user_limit_status == "not_enforceable" and limited.per_user_limit == 1
    assert limited.voucher_cost_scenario == plain.voucher_cost_scenario
    assert limited.qualifying_orders == plain.qualifying_orders
    assert limited.five_numbers == plain.five_numbers
    assert "buyer_key" not in OrderLine.__dataclass_fields__


def test_voucher_number_2_only_from_predicted_range() -> None:
    lines = history()
    costs = {"S1": SkuCost("S1", D(100000), D(3000))}
    rule = VoucherRule(D(200000), amount=D(10000), usage_limit=20)
    r = voucher_whatif(lines, costs, scenario=rule, schedule=SCHEDULE)
    assert r.predicted is None and r.certain.break_even_extra_orders is not None
    assert r.certain.five_numbers.extra_revenue_per_extra_spend is None
    p = voucher_whatif(
        lines,
        costs,
        scenario=rule,
        schedule=SCHEDULE,
        predicted_extra_orders=PredictedRange(D(2), D(10), "caller"),
    ).predicted
    assert p is not None
    # dGMV = n x 250.000 ; dchi = extra voucher cost 200.000 + n x 10.000
    assert p.extra_revenue_per_extra_spend_low == D(2 * 250000) / D(200000 + 2 * 10000)
    assert p.extra_revenue_per_extra_spend_high == D(10 * 250000) / D(200000 + 10 * 10000)


# ------------------------------------------------- contract 10: fees, status, ROAS


def test_non_mall_formula_bases_once_per_order() -> None:
    f = shopee_vn_non_mall(D("0.08"), date(2026, 5, 23))
    assert [c.code for c in f.components] == [
        "phi_co_dinh",
        "phi_xu_ly_giao_dich",
        "phi_ha_tang",
    ]
    sched = FeeSchedule((f,))
    lines = [
        ol("o", "S1", "P1", 1, 200000, 200000, buyer_shipping_fee=D(20000), bank_promo=D(5000)),
        ol("o", "S2", "P2", 1, 100000, 100000),  # NULL shipping / bank promo -> 0
    ]
    costs = {"S1": SkuCost("S1", D(1), D(0)), "S2": SkuCost("S2", D(1), D(0))}
    pairs = profit_lines(lines, costs, schedule=sched)
    fees = [dict(pb.fees or ()) for _, pb in pairs]
    # phi co dinh per item: 8 % x 200.000 / 100.000
    assert (fees[0]["phi_co_dinh"], fees[1]["phi_co_dinh"]) == (D(16000), D(8000))
    # transaction fee once per order: 6 % x (300.000 + 20.000 - 5.000) = 18.900, split 2:1
    assert (fees[0]["phi_xu_ly_giao_dich"], fees[1]["phi_xu_ly_giao_dich"]) == (D(12600), D(6300))
    # infrastructure 3.000 once per order
    assert (fees[0]["phi_ha_tang"], fees[1]["phi_ha_tang"]) == (D(2000), D(1000))
    assert sum(pb.fees_total or D(0) for _, pb in pairs) == D(24000 + 18900 + 3000)
    # one line = its own order: 16.000 + 6 % x (200.000 + 15.000) + 3.000
    solo = f.fee(lines[0])
    assert solo.total == D(16000 + 12900 + 3000)
    assert f.pct_rate_on_buyer_paid == D("0.14")


def test_fixed_fee_base_is_after_seller_promotions() -> None:
    f = shopee_vn_non_mall(D("0.10"), date(2026, 5, 23))
    line = ol("o", "S1", "P1", 1, 200000, 180000, shop_voucher_share=D(10000))
    assert line.item_after_seller_promo == D(170000)
    assert dict(f.fee(line).components)["phi_co_dinh"] == D(17000)


def test_order_status_fee_and_profit_rules() -> None:
    S = OrderStatus
    cost = {"S1": SkuCost("S1", D(100000), D(3000))}
    lines = [
        ol("d", "S1", "P1", 1, 200000, 200000),
        ol("c", "S1", "P1", 1, 200000, 200000, status=S.CANCELLED),
        ol("t", "S1", "P1", 1, 200000, 200000, status=S.IN_TRANSIT),
        ol("n", "S1", "P1", 1, 200000, 200000, status=S.REFUNDED_NOT_RECEIVED),
        ol("r", "S1", "P1", 1, 200000, 200000, status=S.REFUNDED_ACCEPTED, affiliate=True,
           commission=D(5000)),
    ]  # fmt: skip
    pairs = profit_lines(lines, cost, schedule=SCHEDULE)
    pb = {ln.order_id: b for ln, b in pairs}
    # delivered: 200.000 - (30.000 + 1.650) - 103.000
    assert pb["d"].contribution == D(65350)
    # cancelled / undelivered / not received: no fee, no profit, outside the base
    for k in ("c", "t", "n"):
        assert pb[k].fees_total is None and pb[k].contribution is None
        assert pb[k].excluded_reason == "no_fee_no_profit" and pb[k].profit is None
    # accepted "Hoan tien ngay": fee kept, revenue 0, goods + packaging lost, no commission
    assert pb["r"].fees_total == D(31650) and pb["r"].revenue == D(0)
    assert pb["r"].contribution == D(-31650 - 103000)

    sp = shop_profit(pairs, campaigns=[], product_ad_spend={})
    # confirmed views keep every order's GMV ...
    assert sp.orders == 5 and sp.gmv == D(1000000)
    assert sp.products["P1"].gmv == D(1000000) and sp.products["P1"].excluded_orders == 3
    # ... the profit base is delivered + accepted refund only: revenue 200.000 + 0
    assert sp.buyer_paid == D(200000) and sp.buyer_paid_covered == D(200000)
    assert sp.contribution == D(65350 - 134650) and sp.profit == D(-69300)
    assert sp.cost_coverage_pct == D("100.0")
    m = build_source_matrix(pairs)
    assert_additive(m)
    assert m.totals["P1"].orders == 5 and m.totals["P1"].orders_excluded == 3
    assert m.totals["P1"].orders_missing_profit == 0
    assert m.totals["P1"].gmv == D(1000000)
    # the five numbers: GMV and orders are confirmed, the margin base is not
    snap = snapshot_from(pairs, D(0))
    assert snap.gmv == D(1000000) and snap.orders == 5 and snap.buyer_paid == D(200000)


def test_roas_broad_and_direct_per_product_and_campaign() -> None:
    pairs = profit_lines(shop_lines(), SHOP_COSTS, schedule=SCHEDULE)
    ads = {"P1": AdsFigures(D(50000), gmv=D(400000), direct_gmv=D(150000))}
    sp = shop_profit(pairs, campaigns=CAMPAIGNS, product_ad_spend=PRODUCT_ADS, product_ads=ads)
    p1 = sp.products["P1"]
    assert p1.roas_broad == D(8) and p1.roas_direct == D(3)
    # break-even 560.000 / 167.250 = 3,35: the DIRECT roas (3,0) is below it, broad (8) is not
    assert p1.break_even_roas == D(560000) / D(167250)
    assert p1.ads_below_break_even is True
    assert sp.products["P2"].roas_direct is None and sp.products["P2"].ads_below_break_even is None
    c = AdCampaign("C", D(100), revenue=D(500), direct_revenue=D(200))
    assert (c.roas_broad, c.roas_direct) == (D(5), D(2))
    assert AdCampaign("Z", D(30), revenue=D(0)).roas_direct is None
