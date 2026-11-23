"""F4: phí dịch vụ (Voucher / Freeship Xtra) joins the fee formula for an enrolled shop; its rate
is learned from the shop's own income rows. Synthetic amounts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from juli_backend.services.shopee_analytics import fee_table
from juli_backend.services.shopee_analytics.catalog import Catalog
from juli_backend.services.shopee_analytics.engine import (
    build_fee_context,
    profit_pairs,
    resolve_costs,
    to_shop_lines,
)
from juli_backend.services.shopee_analytics.rules_view import read_rules
from juli_backend.services.shopee_profit.fees import FeeBase, FeeKind
from juli_backend.services.shopee_profit.income import IncomeOrder
from tests.unit.test_shopee_income_engine import CATALOG, RULES, _raw

D = Decimal
ON = date(2026, 11, 10)


def _rows(n: int, with_fee: int, price="100000", fee="5500"):
    """Rows with the Xtra part stated (price, Phí Dịch Vụ, infra, Xtra)."""
    return [
        (
            D(price),
            D(fee) + 3000 if i < with_fee else D(3000),
            D(3000),
            D(fee) if i < with_fee else D(0),
        )
        for i in range(n)
    ]


def test_the_rate_is_learned_from_the_shops_income_rows():
    assert fee_table.learn_service_rate(_rows(10, 10)) == D("0.0550")


def test_a_shop_with_no_xtra_fee_in_its_rows_is_not_enrolled():
    assert fee_table.learn_service_rate(_rows(10, 0)) is None


def test_without_the_file_breakdown_the_rate_is_phi_dich_vu_minus_the_infrastructure_fee():
    rows = [(D(100_000), D(8_500), None, None)] * 6  # 8.500 - 3.000 = 5.500
    assert fee_table.learn_service_rate(rows) == D("0.0550")
    not_enrolled = [(D(100_000), D(3_000), None, None)] * 6  # only the infrastructure fee
    assert fee_table.learn_service_rate(not_enrolled) is None


def test_too_few_rows_learn_nothing():
    assert fee_table.learn_service_rate(_rows(2, 2)) is None
    assert fee_table.learn_service_rate([]) is None


def test_rows_without_a_price_or_fee_are_not_counted():
    rows = [(None, D(100), None, D(100)), (D(100), None, None, None), *_rows(5, 5)]
    assert fee_table.learn_service_rate(rows) == D("0.0550")


def _fee_of(service_rate):
    ctx = build_fee_context(["p1"], Catalog(), None, service_rate)
    formula = ctx.schedule("p1").formula_on(ON)
    assert formula is not None
    return formula


def test_an_enrolled_shop_formula_has_the_service_component_on_the_discounted_item_value():
    formula = _fee_of(D("0.055"))
    codes = [c.code for c in formula.components]
    assert "phi_dich_vu" in codes and "phi_ha_tang" in codes
    comp = next(c for c in formula.components if c.code == "phi_dich_vu")
    assert (comp.kind, comp.base, comp.rate) == (
        FeeKind.PCT,
        FeeBase.ITEM_AFTER_SELLER_PROMO,
        D("0.055"),
    )


def test_a_shop_not_enrolled_has_no_service_component():
    formula = _fee_of(None)
    assert "phi_dich_vu" not in [c.code for c in formula.components]


def test_the_service_component_is_not_added_twice():
    once = fee_table.with_service_fee(fee_table.seed_schedule(D("0.1")), D("0.055"))
    twice = fee_table.with_service_fee(once, D("0.055"))
    assert once == twice


# ------------------------------------------------------------------ through the line profit


def _pairs(service_rate, income=None):
    rules = read_rules(RULES)
    lines = to_shop_lines([_raw(1)], CATALOG, rules, income)
    fees = build_fee_context([sl.product_id for sl in lines], CATALOG, None, service_rate)
    return profit_pairs(lines, resolve_costs(lines, rules), fees)


def test_an_order_without_an_income_row_pays_the_service_fee_when_enrolled():
    plain = dict(_pairs(None)[0][1].fees)
    enrolled = dict(_pairs(D("0.055"))[0][1].fees)
    assert "phi_dich_vu" not in plain
    # deal price 90.000 (after the seller discount): 5,5 % = 4.950
    assert enrolled["phi_dich_vu"] == D(4_950)
    assert {k: v for k, v in enrolled.items() if k != "phi_dich_vu"} == plain


def test_an_order_with_an_income_row_keeps_the_files_real_fees():
    income = IncomeOrder(order_ref=f"{1:032x}", fee_fixed=D(1_000), fee_service=D(2_000))
    pb = _pairs(D("0.055"), {income.order_ref: income})[0][1]
    assert pb.fee_source == "income" and pb.fees_total == D(3_000)
