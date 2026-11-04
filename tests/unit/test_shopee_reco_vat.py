"""P91 D-14: the shop's VAT flags apply to the card what-ifs, so a card's Δ profit is the shop's.

Pure: hand-built raw lines, no database. The what-ifs (versions, compare, plan totals) look costs up
by key; the VAT treatment travels on ``SkuCost`` so ``profit_lines`` takes the same VAT out of
revenue and cost as the shop profit does.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from juli_backend.services.shopee_analytics.rules_view import RuleRow
from juli_backend.services.shopee_profit.order_profit import profit_lines
from juli_backend.services.shopee_profit.whatif import price_change_whatif
from tests.unit.test_shopee_income_engine import CATALOG, _profit, _raw

D = Decimal
BASE = [RuleRow("sku_cost", "G1", 30_000), RuleRow("packaging_cost", "G1", 2_000)]
VAT = [
    RuleRow("prices_include_vat", "", True),
    RuleRow("cost_includes_vat", "", True),
    RuleRow("vat_rate", "G1", 8),
]


def _shop_profit(raws, rows):
    return sum((pb.profit for _, pb in _profit(raws, rows)[2]), D(0))


def test_the_vat_treatment_travels_on_the_cost_of_a_key():
    lines, costs, _ = _profit([_raw(1)], [*BASE, *VAT])
    vat = costs.by_key["G1"].vat
    assert vat is not None and vat.prices_include_vat is True and vat.rate == D("0.08")
    assert costs.by_key["G1"].vat == lines[0].vat


def test_a_what_if_profit_with_the_flags_is_the_shop_profit_of_the_repriced_orders():
    raws = [_raw(1), _raw(2, deal_price=D(86_000))]
    lines, costs, pairs = _profit(raws, [*BASE, *VAT])
    plain_lines, plain_costs, _ = _profit(raws, BASE)
    from juli_backend.services.shopee_analytics.engine import build_fee_context

    schedule = build_fee_context([sl.product_id for sl in lines], CATALOG).schedule(
        lines[0].product_id
    )
    new_price = D(80_000)
    after = [replace(sl.line, deal_price=min(sl.line.deal_price, new_price)) for sl in lines]
    with_vat = sum(
        (pb.profit for _, pb in profit_lines(after, costs.by_key, schedule=schedule)), D(0)
    )
    without_vat = sum(
        (pb.profit for _, pb in profit_lines(after, plain_costs.by_key, schedule=schedule)), D(0)
    )
    shop_after = _shop_profit(
        [_raw(1, deal_price=new_price), _raw(2, deal_price=min(D(86_000), new_price))],
        [*BASE, *VAT],
    )
    assert with_vat == shop_after and with_vat != without_vat

    result = price_change_whatif(
        [sl.line for sl in lines],
        costs.by_key,
        sku="G1",
        new_deal_price=new_price,
        schedule=schedule,
        ceiling=True,
    )
    shop_before = sum((pb.profit for _, pb in pairs), D(0))
    assert result.certain.profit_delta_same_volume == shop_after - shop_before


def test_without_the_flags_the_what_if_stays_before_vat():
    lines, costs, _ = _profit([_raw(1)], BASE)
    assert costs.by_key["G1"].vat is not None  # the flags are unset, the profit says before VAT
    (pair,) = profit_lines([lines[0].line], costs.by_key)
    assert pair[1].vat_basis == "before_vat" and pair[1].vat_output == 0
