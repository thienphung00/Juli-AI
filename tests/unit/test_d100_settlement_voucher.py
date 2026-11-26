"""Decision #100 (7a): a settlement-proven seller voucher is used even when the order lines show
less (or more). Synthetic orders only."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal as D

from juli_backend.services.shopee_analytics.engine import ShopLine, attach_income
from juli_backend.services.shopee_profit.order_profit import line_profit
from juli_backend.services.shopee_profit.shop_profit import _net_value
from tests.unit.test_c9_orders import BASE
from tests.unit.test_shopee_profit import COST, SCHEDULE, line


def _attach(lines, **changes):
    shop_lines = [ShopLine(ln, ln.order_date, "") for ln in lines]
    return [s.line for s in attach_income(shop_lines, {"v1": replace(BASE, **changes)})]


def test_lines_show_zero_the_settlement_proves_twenty_thousand():
    before = line("v1")
    (after,) = _attach([before], payout=D(140_000), seller_voucher_borne=D(20_000))
    assert after.seller_voucher == D(20_000)
    assert _net_value(before) - _net_value(after) == D(20_000)
    assert before.buyer_paid - after.buyer_paid == D(20_000)
    pb_before = line_profit(before, COST, schedule=SCHEDULE)
    pb_after = line_profit(after, COST, schedule=SCHEDULE)
    assert pb_after.voucher == D(20_000)
    assert pb_before.contribution is not None and pb_after.contribution is not None
    assert pb_before.contribution > pb_after.contribution


def test_the_proven_voucher_is_split_by_line_value():
    big = line("v1", original_price=D(150_000), deal_price=D(150_000))
    small = line("v1", original_price=D(50_000), deal_price=D(50_000))
    got = _attach([big, small], payout=D(140_000), seller_voucher_borne=D(20_000))
    assert [ln.seller_voucher for ln in got] == [D(15_000), D(5_000)]


def test_lines_show_five_thousand_funded_part_is_ignored():
    ln = line("v1", shop_voucher_share=D(5_000))
    (got,) = _attach([ln], payout=D(155_000), seller_voucher_borne=D(5_000))
    assert got.seller_voucher == D(5_000)
    forced = replace(got, voucher_funded=D(857))
    assert forced.seller_voucher == D(5_000)


def test_the_settlement_closing_at_zero_overrides_the_lines():
    ln = line("v1", shop_voucher_share=D(10_000))
    (got,) = _attach([ln])
    assert got.seller_voucher == D(0)
    assert got.buyer_paid == got.order_value


def test_without_a_settlement_the_line_rule_stays():
    ln = line("v1", shop_voucher_share=D(10_000))
    assert ln.seller_voucher == D(10_000)
    assert replace(ln, voucher_funded=D(3_000)).seller_voucher == D(7_000)
    (got,) = attach_income([ShopLine(ln, ln.order_date, "")], {})
    assert got.line.seller_voucher == D(10_000)
