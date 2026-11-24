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
