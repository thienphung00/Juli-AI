"""T5 round 2 (owner 2026-11-18): every đơn / GMV / AOV site goes through ``counts_in_sales`` --
the five numbers' snapshot, the recommendation env and evaluators, the builder's order
statistics. A returned order is no sale; its cost stays in the profit.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from juli_backend.services.shopee_builder import copurchase
from juli_backend.services.shopee_builder.engine_families import adapters
from juli_backend.services.shopee_builder.variations import with_orders
from juli_backend.services.shopee_profit.five_numbers import snapshot_from
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    OrderStatus,
    SkuCost,
    profit_lines,
)
from juli_backend.services.shopee_recommendations.env import RecoEnv, voucher_takeup
from juli_backend.services.shopee_recommendations.evaluate import _item_gmv

COST = SkuCost(sku="S1", cogs=Decimal(30_000), packaging=Decimal(2_000))


def _line(order: str, status: OrderStatus, product: str = "1001", **over) -> OrderLine:
    values = {
        "order_id": order,
        "sku": "S1",
        "product_id": product,
        "order_date": date(2026, 11, 1),
        "qty": 1,
        "original_price": Decimal(100_000),
        "deal_price": Decimal(90_000),
        "actual_fees": Decimal(8_000),
        "status": status,
        **over,
    }
    return OrderLine(**values)


DELIVERED = _line("d1", OrderStatus.DELIVERED)
RETURNED = _line("r1", OrderStatus.RETURNED)


def test_the_five_numbers_snapshot_leaves_a_returned_order_out_of_orders_and_gmv():
    both = snapshot_from(profit_lines([DELIVERED, RETURNED], {"S1": COST}), Decimal(0))
    sold = snapshot_from(profit_lines([DELIVERED], {"S1": COST}), Decimal(0))
    assert (both.orders, both.gmv, both.list_value) == (sold.orders, sold.gmv, sold.list_value)
    assert both.orders == 1 and both.gmv == Decimal(90_000)
    assert both.discount == sold.discount  # its promo is no spend either
    assert both.contribution < sold.contribution  # its cost stays in the profit


def test_the_reco_env_sales_pairs_and_orders_leave_a_returned_order_out():
    pairs = profit_lines([DELIVERED, RETURNED], {"S1": COST})
    env = SimpleNamespace(view=SimpleNamespace(pairs=pairs), _sales_pairs=None)
    sales = RecoEnv.sales_pairs.fget(env)
    assert [ln.order_id for ln, _ in sales] == ["d1"]
    env.sales_pairs = sales
    assert RecoEnv.orders_of(env, "1001") == 1


def test_reco_and_builder_order_statistics_skip_a_returned_order():
    lines = [DELIVERED, RETURNED, _line("d2", OrderStatus.IN_TRANSIT, product="2002")]
    assert _item_gmv(lines, "1001") == Decimal(90_000)
    assert adapters.order_values(lines) == {"d1": Decimal(90_000), "d2": Decimal(90_000)}
    assert sorted(map(sorted, copurchase.order_sets(lines))) == [["1001"], ["2002"]]
    rows = with_orders([{"sku_key": "S1"}], lines, "1001")
    assert rows[0]["orders_30d"] == 1


def test_voucher_takeup_counts_only_the_orders_that_are_sales():
    voucher = {"shop_voucher_share": Decimal(5_000)}
    lines = [_line(f"d{n}", OrderStatus.DELIVERED) for n in range(40)]
    returned = [_line(f"r{n}", OrderStatus.RETURNED, **voucher) for n in range(40)]
    lines.append(_line("v1", OrderStatus.DELIVERED, **voucher))
    rate = voucher_takeup(lines + returned, Decimal(0), None)
    assert rate == Decimal(1) / Decimal(41)
