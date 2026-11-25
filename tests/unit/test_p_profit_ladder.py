"""Track P (decisions #42 / #44): the profit ladder on the profit service and Tổng quan.

Synthetic lines only. Lợi nhuận đóng góp = before ads AND affiliate; break-even ROAS and the
ladder read it; ROI = Lợi nhuận ròng ÷ Tổng chi phí."""

from __future__ import annotations

from decimal import Decimal as D

from juli_backend.services.shopee_profit.ladder import ladder_of
from juli_backend.services.shopee_profit.order_profit import line_profit
from juli_backend.services.shopee_profit.shop_profit import product_profits
from tests.unit.test_shopee_profit import COST, SCHEDULE, line


def _pairs():
    plain = line("a")
    aff = line("b", affiliate=True, commission=D(7000))
    return [
        (plain, line_profit(plain, COST, schedule=SCHEDULE)),
        (aff, line_profit(aff, COST, schedule=SCHEDULE)),
    ]


def test_organic_contribution_adds_the_commission_back() -> None:
    (_, a), (_, b) = _pairs()
    assert a.organic_contribution == a.contribution  # no commission on an organic line
    assert b.contribution is not None and b.organic_contribution == b.contribution + D(7000)


def test_break_even_roas_is_net_over_the_ladder_contribution() -> None:
    pp = product_profits(_pairs(), {"P1": D(10000)})["P1"]
    assert pp.affiliate_commission == D(7000)
    assert pp.organic_contribution == pp.contribution + D(7000)
    assert pp.profit == pp.contribution - D(10000)  # ròng unchanged
    assert pp.break_even_roas == pp.buyer_paid_covered / pp.organic_contribution


def test_the_ladder_ends_on_the_shown_profit_and_roi_is_over_total_cost() -> None:
    pairs = _pairs()
    pp = product_profits(pairs, {"P1": D(10000)})["P1"]
    lad = ladder_of(pairs, ads_spend=D(10000), other_marketing=D(0), profit=pp.profit)
    contribution = lad.get("contribution")
    assert contribution == pp.organic_contribution
    gross = lad.get("gross_profit")
    assert gross is not None and contribution is not None and gross > contribution
    # ròng = đóng góp − QC − AFF − khác
    assert lad.get("profit") == contribution - D(10000) - D(7000)
    total = lad.get("cost_total")
    assert total is not None and lad.get("roi") == pp.profit / total
    assert lad.get("cost_cogs") == D(200000)


# -- decision #50: doanh thu thực subtracts only the voucher the seller bore ---------------------


def _with_settlement(voucher_share: D, borne: D | None):
    from juli_backend.services.shopee_analytics.engine import ShopLine, attach_income
    from juli_backend.services.shopee_profit.income import IncomeOrder

    ln = line("v1", shop_voucher_share=voucher_share)
    # C9: the settlement's arithmetic confirms the stated amount (goods − payout = the voucher)
    settled = {"product_price": ln.order_value, "payout": ln.order_value - (borne or D(0))}
    if borne is None:
        settled = {}
    income = {"v1": IncomeOrder("v1", fee_service=D(0), seller_voucher_borne=borne, **settled)}
    out = attach_income([ShopLine(ln, ln.order_date, "S1")], income)
    return out[0].line


def test_a_platform_funded_shop_voucher_does_not_cut_doanh_thu_thuc():
    """A buyer-side "Mã giảm giá của Shop" of 34.680đ the seller did NOT bear (settlement
    seller_voucher_borne 0, a Voucher Xtra code): doanh thu thực = the goods total."""
    ln = _with_settlement(D(34680), D(0))
    assert ln.voucher_funded == D(34680) and ln.seller_voucher == 0
    assert ln.buyer_paid == ln.order_value
    pb = line_profit(ln, COST, schedule=SCHEDULE)
    assert pb.voucher == 0 and pb.offer_cost == pb.promo_discount + pb.bundle


def test_a_voucher_the_seller_bore_cuts_doanh_thu_thuc():
    ln = _with_settlement(D(34680), D(34680))
    assert ln.voucher_funded == 0 and ln.buyer_paid == ln.order_value - D(34680)
    assert line_profit(ln, COST, schedule=SCHEDULE).voucher == D(34680)


def test_without_a_settlement_the_buyer_side_voucher_is_kept():
    """No settlement yet (in transit; outside the profit base anyway): today's behaviour."""
    ln = line("v1", shop_voucher_share=D(34680))
    assert ln.voucher_funded == 0 and ln.buyer_paid == ln.order_value - D(34680)
    unstated = _with_settlement(D(34680), None)  # a settlement that does not state it
    assert unstated.voucher_funded == 0


def test_the_ladder_and_the_split_still_add_up_with_a_funded_voucher():
    from types import SimpleNamespace as NS

    from juli_backend.services.shopee_analytics.channel_split import (
        SPLIT_CHANNELS,
        SPLIT_COLUMNS,
        profit_split,
    )

    funded = _with_settlement(D(34680), D(0))
    pairs = [(funded, line_profit(funded, COST, schedule=SCHEDULE)), *_pairs()]
    pp = product_profits(pairs, {"P1": D(10000)})["P1"]
    lad = ladder_of(pairs, ads_spend=D(10000), other_marketing=D(0), profit=pp.profit)
    assert lad.get("contribution") == pp.organic_contribution
    assert lad.get("cost_offers") == sum(pb.offer_cost for _, pb in pairs)
    view = NS(
        pairs=pairs,
        ads=NS(product_figures={}),
        profit=NS(products={"P1": pp}, total_ad_spend=D(10000), other_marketing_costs=D(0)),
    )
    split = profit_split(view, "P1")
    for col in SPLIT_COLUMNS:
        assert sum(split["rows"][ch][col] for ch in SPLIT_CHANNELS) == split["total"][col]
    assert split["total"]["net_revenue"] == sum(pb.revenue for _, pb in pairs)
