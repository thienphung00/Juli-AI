"""T1 (batch 1119) as amended by #42 / #44 (Track P): the card's margin is Biên đóng góp =
Lợi nhuận đóng góp ÷ doanh thu thực, before and after on the card's OWN days (doanh thu thực of a
column = its GMV x the scope's net/GMV ratio less the offers that lower it).

Synthetic shops only. Net revenue is ``buyer_paid`` (covered); the dashboard's function is
``shop_profit.scope_margin_pct``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from juli_backend.services.sample_shop import content_specs
from juli_backend.services.shopee_builder.engine.contract import (
    FunnelBase,
    MarginBasis,
    OptionResult,
    Scenario,
)
from juli_backend.services.shopee_builder.engine.wire import _margin
from juli_backend.services.shopee_builder.engine_families.integrate import (
    margin_basis,
    sum_results,
)
from juli_backend.services.shopee_builder.reasons import REASON_TEXT
from juli_backend.services.shopee_profit.fees import FeeComponent, FeeFormula, FeeKind, FeeSchedule
from juli_backend.services.shopee_profit.income import LineIncome
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    OrderStatus,
    SkuCost,
    profit_lines,
)
from juli_backend.services.shopee_profit.shop_profit import scope_margin_pct, shop_profit
from juli_backend.services.shopee_recommendations import config

DAY = date(2026, 10, 15)
SCHEDULE = FeeSchedule(
    (FeeFormula(date(2026, 1, 1), (FeeComponent("commission", FeeKind.PCT, rate=D("0.10")),)),)
)


def scen(gmv: int, profit: int | None) -> Scenario:
    return Scenario(None, None, D(10), D(gmv), None if profit is None else D(profit), D(0))


def result(
    before: Scenario, likely: Scenario | None, basis: MarginBasis | None, days: int = 30
) -> OptionResult:
    return OptionResult(
        kind="x",
        label="x",
        days=days,
        horizon="duration",
        drivers=(),
        estimable=likely is not None,
        basis="not_estimable",
        before=before,
        low=None,
        likely=likely,
        high=None,
        build_up=(),
        cost_total=D(0),
        break_even_orders=None,
        break_even_aov=None,
        margin_basis=basis,
    )


# net = 0.94 x GMV; covered profit 188.000 on net 940.000 -> 20,0 %
BASIS = MarginBasis(profit=D(188_000), net_revenue=D(940_000), gmv=D(1_000_000))


def test_t1_1_before_margin_is_profit_over_net_revenue_not_gmv():
    m = _margin(result(scen(1_000_000, 188_000), scen(1_000_000, 188_000), BASIS))
    assert m["before_pct"] == 20.0  # 188.000 / 940.000; over GMV it would be 18,8


def test_t1_2_after_margin_uses_after_gmv_times_the_before_net_gmv_ratio():
    # +20 % GMV, +50.000 profit: after = (188.000 + 50.000) / (1.200.000 x 0,94) = 21,1 %
    m = _margin(result(scen(1_000_000, 188_000), scen(1_200_000, 238_000), BASIS))
    assert m["after_pct"] == 21.1
    assert m["shift_pts"] == pytest.approx(21.1 - 20.0)


@pytest.mark.parametrize(
    "basis",
    [
        None,
        MarginBasis(D(1), D(0), D(100)),
        MarginBasis(D(1), D(-5), D(100)),
    ],
)
def test_t1_3_no_net_revenue_or_profit_means_no_margin_never_a_gmv_fallback(basis):
    m = _margin(result(scen(1_000_000, 100_000), scen(1_100_000, 150_000), basis))
    assert m == {"before_pct": None, "after_pct": None, "shift_pts": None}
    unknown = _margin(result(scen(1_000_000, None), scen(1_100_000, None), BASIS))
    assert unknown == {"before_pct": None, "after_pct": None, "shift_pts": None}


def test_not_estimable_card_keeps_only_the_before_margin():
    m = _margin(result(scen(1_000_000, 188_000), None, BASIS))
    assert m["before_pct"] == 20.0 and m["after_pct"] is None and m["shift_pts"] is None


def _shop():
    def ol(oid, sku, item, price):  # a shop voucher takes 6 % off: net = 0,94 x GMV
        return OrderLine(oid, sku, item, DAY, 1, D(price), D(price), D(price) * D("0.06"))

    lines = [ol("o1", "S1", "P1", 100_000), ol("o2", "S2", "P2", 200_000)]
    costs = {"S1": SkuCost("S1", D(30_000), D(0)), "S2": SkuCost("S2", D(60_000), D(0))}
    pairs = profit_lines(lines, costs, schedule=SCHEDULE)
    return shop_profit(pairs, campaigns=[], product_ad_spend={})


@pytest.mark.parametrize("items", [(), ("P1",), ("P1", "P2")])
def test_t1_4_card_margin_equals_the_scopes_bien_dong_gop(items):
    """#44: on the scope's own window the card's before margin is the scope's Biên đóng góp
    (Lợi nhuận đóng góp ÷ doanh thu thực of its covered lines); with no ad or affiliate cost it
    is the dashboard's margin too."""
    sp = _shop()
    assert sp.buyer_paid_covered != sp.gmv  # net is not GMV here
    basis = margin_basis(sp, items)
    assert basis is not None and basis.profit is not None
    one = scen(int(basis.gmv), int(basis.profit))
    m = _margin(result(one, one, basis))
    want = round(float(basis.profit / basis.net_revenue * 100), 1)
    assert m["before_pct"] == want and m["after_pct"] == want
    dash = scope_margin_pct(sp, items)  # no ads, no affiliate: ròng = đóng góp here
    assert dash is not None and m["before_pct"] == float(dash)


def test_basis_is_none_without_covered_revenue():
    sp = _shop()
    assert margin_basis(sp, ("unknown",)) is None


def test_several_targets_add_the_basis_up():
    a = result(scen(100, 1), scen(110, 2), BASIS)
    both = sum_results([a, a], "x")
    assert both.margin_basis == MarginBasis(D(376_000), D(1_880_000), D(2_000_000))
    assert sum_results([a, replace(a, margin_basis=None)], "x").margin_basis is None


def test_funnel_base_defaults_to_no_basis():
    fields = FunnelBase.__dataclass_fields__
    assert fields["margin_basis"].default is None
    assert SimpleNamespace  # keep import used


def test_sample_title_spec_uses_the_one_title_limit():
    spec, _ = content_specs.title_spec(0)
    assert spec["inputs"]["max_chars"] == config.MAX_TITLE_CHARS == 120


def _income(payout):
    z = D(0)
    return LineIncome((), z, z, z, z, z, z, z, z, D(payout))


def test_only_the_sale_is_in_net_revenue_and_in_the_covered_gmv():
    """Owner rule: refunded / returned / cancelled / undelivered goods are not doanh thu thuc.
    One order of each status plus one normal order: R and the covered GMV are the normal one's."""
    S = OrderStatus
    lines = [OrderLine("ok", "S1", "P1", DAY, 1, D(100_000), D(100_000), D(6_000))]
    # the refund statuses carry a settlement row (they cost its deduction), so they are in the
    # profit base; cancelled and in transit are outside it
    for i, st in enumerate(
        (S.REFUNDED_ACCEPTED, S.REFUNDED_NOT_RECEIVED, S.RETURNED, S.CANCELLED, S.IN_TRANSIT)
    ):
        lines.append(
            OrderLine(
                f"x{i}", "S1", "P1", DAY, 1, D(70_000), D(70_000), status=st, income=_income(-5_000)
            )
        )
    pairs = profit_lines(lines, {"S1": SkuCost("S1", D(30_000), D(1_000))}, schedule=SCHEDULE)
    sp = shop_profit(pairs, campaigns=[], product_ad_spend={})
    normal_net, normal_gmv = D(94_000), D(100_000)
    p = sp.products["P1"]
    assert sp.buyer_paid == p.buyer_paid == normal_net
    assert sp.buyer_paid_covered == p.buyer_paid_covered == normal_net
    assert sp.gmv_covered == p.gmv_covered == normal_gmv
    # headline GMV is unchanged: it still counts cancelled and in-transit orders (not refunds)
    assert sp.gmv == p.gmv == normal_gmv + 2 * D(70_000)
    b = margin_basis(sp, ())
    assert b is not None and (b.net_revenue, b.gmv) == (normal_net, normal_gmv)


# -- a result that is not estimable shows ONE label to the seller (owner 2026-11-19) -------------

LABEL = "Chưa ước tính được"
NOT_ESTIMABLE_NOTES = {
    "no_driver_data": "Chưa có dữ liệu để đòn bẩy Lượt xem chưa có dữ liệu",
    "no_estimate": "Ít dữ liệu để ước tính CTR",
    "needs_trial_run": "Cần chạy thử trước",
    "measure_after_run": "Sẽ đo sau khi chạy",
    "kol_first_sample": "Đo sau lần gửi mẫu đầu tiên",
    "no_keyword_data": "Chưa có từ khoá của sản phẩm",
    "no_keyword_gain": "Không thêm từ khoá nào",
    "combo_few_orders": "Chưa đủ đơn để đo số đơn lên mức combo",
    "combo_no_history": "Shop chưa chạy combo",
    "set_not_cheaper": "Chưa có set nào rẻ hơn",
    "no_pack_evidence": "Chưa có dữ liệu của quy cách này",
    "pack_already_sold": "Shop đang bán quy cách này",
    "followers_unknown": "Chưa biết người theo dõi",
    "ads_budget_unlimited": "Chiến dịch không giới hạn ngân sách",
    "ads_no_history": "Chưa có lịch sử ở mức này",
    "ads_no_product_rows": "Chưa có báo cáo quảng cáo theo sản phẩm",
    "ads_no_cpa": "Chưa đo được CPA",
    "ads_no_incremental": "Chưa đủ ngày có và không có quảng cáo",
    "ads_roas_system": "Shopee tự đặt mục tiêu ROAS",
    "attach_few_orders": "Chưa đủ 10 đơn để ước tính mua kèm",
}


@pytest.mark.parametrize(("code", "note"), sorted(NOT_ESTIMABLE_NOTES.items()))
def test_not_estimable_result_shows_only_the_one_label(code, note):
    r = replace(result(scen(1_000_000, 0), None, BASIS), notes=(note,))
    j = r.json()
    assert j["reason_code"] == code  # the detail stays for internal use
    assert j["delta"]["orders"]["note"] == LABEL
    assert j["reason_text"] == REASON_TEXT[code]  # the hover keeps the real reason (G5)
    assert j["notes"] == [LABEL]
    assert r.notes == (note,)  # the OptionResult (and its stored core) keep the detail


def test_not_estimable_result_without_a_note_shows_the_label_too():
    j = result(scen(1_000_000, 0), None, BASIS).json()
    assert j["delta"]["orders"]["note"] == LABEL
    assert j["reason_code"] == "no_estimate" and j["reason_text"] == REASON_TEXT["no_estimate"]


def test_every_no_estimate_reason_code_is_covered():
    from juli_backend.services.shopee_builder import reasons

    codes = [c for c in reasons.REASON_TEXT if not c.startswith("profit_")]
    assert sorted(codes) == sorted(NOT_ESTIMABLE_NOTES)


def test_estimable_result_keeps_its_notes_and_reason_text():
    r = replace(result(scen(1_000_000, 10), scen(1_100_000, 20), BASIS), notes=("n1",))
    j = r.json()
    assert j["notes"] == ["n1"] and j["reason_text"] is None


# -- the card's horizon: the dashboard basis is 30 days, the card's Δ and GMV are over `days` -----


def test_after_margin_of_a_2_day_card_is_on_the_cards_own_horizon():
    # 2 days: before GMV 100.000 (profit 18.800), after GMV 120.000 (profit 25.000)
    # R_before = 94.000, R_after = 112.800: 18.800 / 94.000 = 20 %, 25.000 / 112.800 = 22,2 %
    m = _margin(result(scen(100_000, 18_800), scen(120_000, 25_000), BASIS, days=2))
    assert m["before_pct"] == 20.0 and m["after_pct"] == 22.2


def test_after_margin_of_a_14_day_card_is_on_the_cards_own_horizon():
    # R_before = 470.000, R_after = 564.000: 120.000 / 564.000 = 21,3 %
    m = _margin(result(scen(500_000, 94_000), scen(600_000, 120_000), BASIS, days=14))
    assert m["after_pct"] == 21.3


def test_after_margin_of_a_30_day_card_is_unchanged():
    m = _margin(result(scen(1_000_000, 188_000), scen(1_200_000, 238_000), BASIS, days=30))
    assert m["after_pct"] == 21.1


@pytest.mark.parametrize("days", [2, 14, 30])
def test_no_change_means_no_margin_shift_on_any_horizon(days):
    one = scen(100_000 * days, 18_800 * days)
    m = _margin(result(one, one, BASIS, days=days))
    assert m["after_pct"] == m["before_pct"] == 20.0 and m["shift_pts"] == 0
