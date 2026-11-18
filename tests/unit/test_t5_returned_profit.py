"""T5 / owner D2 (2026-11-18): a ``returned`` order line -- goods back with the seller, buyer
refunded.

Revenue 0, no goods cost, no commission; the settlement fees and the packaging are the seller's
cost, so its contribution is -(fees + packaging). It is not counted in đơn / GMV / AOV, and it is
in the profit.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    OrderStatus,
    SkuCost,
    counts_in_sales,
    line_profit,
    profit_lines,
)
from juli_backend.services.shopee_profit.shop_profit import shop_profit

FEES = Decimal(8_000)
PACKAGING = Decimal(2_000)
COST = SkuCost(sku="S1", cogs=Decimal(30_000), packaging=PACKAGING)


def _line(order: str, status: OrderStatus, **over) -> OrderLine:
    values = {
        "order_id": order,
        "sku": "S1",
        "product_id": "1001",
        "order_date": date(2026, 11, 1),
        "qty": 1,
        "original_price": Decimal(100_000),
        "deal_price": Decimal(90_000),
        "actual_fees": FEES,
        "status": status,
        **over,
    }
    return OrderLine(**values)


def test_returned_is_in_the_profit_vocabulary_but_not_in_sales():
    returned = OrderStatus("returned")
    assert returned is OrderStatus.RETURNED
    assert returned.carries_profit is False
    assert returned.charges_fees is True
    assert returned.counts_in_sales is False
    assert all(s.counts_in_sales for s in OrderStatus if s is not OrderStatus.RETURNED)
    assert OrderStatus.DELIVERED.charges_fees and not OrderStatus.CANCELLED.charges_fees


def test_a_returned_line_costs_its_fees_and_packaging_and_earns_nothing():
    pb = line_profit(_line("r1", OrderStatus.RETURNED, affiliate=True), COST)
    assert pb.revenue == 0
    assert pb.cogs == 0
    assert pb.commission == 0
    assert (pb.fees_total, pb.packaging) == (FEES, PACKAGING)
    assert pb.contribution == -(FEES + PACKAGING)
    assert pb.excluded_reason is None and pb.missing == ()


def test_a_returned_line_needs_no_goods_cost_to_be_known():
    pb = line_profit(
        _line("r2", OrderStatus.RETURNED), SkuCost(sku="S1", cogs=None, packaging=PACKAGING)
    )
    assert pb.contribution == -(FEES + PACKAGING)


def test_a_delivered_line_is_unchanged():
    pb = line_profit(_line("d1", OrderStatus.DELIVERED), COST)
    assert pb.revenue == Decimal(90_000)
    assert pb.contribution == Decimal(90_000) - FEES - Decimal(30_000) - PACKAGING


def test_returned_is_outside_orders_and_gmv_and_inside_profit():
    delivered = _line("d1", OrderStatus.DELIVERED)
    returned = _line("r1", OrderStatus.RETURNED)
    assert counts_in_sales(delivered) and not counts_in_sales(returned)
    pairs = profit_lines([delivered, returned], {"S1": COST})
    only = profit_lines([delivered], {"S1": COST})
    shop = shop_profit(pairs, campaigns=[], product_ad_spend={})
    base = shop_profit(only, campaigns=[], product_ad_spend={})
    assert (shop.orders, shop.gmv) == (base.orders, base.gmv) == (1, Decimal(90_000))
    assert shop.buyer_paid == base.buyer_paid  # revenue 0 adds nothing to the margin base
    assert shop.contribution == base.contribution - (FEES + PACKAGING)
    product = shop.products["1001"]
    assert (product.orders, product.gmv) == (1, Decimal(90_000))
    assert product.contribution == base.products["1001"].contribution - (FEES + PACKAGING)


def test_a_returned_line_without_actual_fees_takes_the_formula_share():
    from juli_backend.services.shopee_profit.fees import FeeSchedule, shopee_vn_non_mall

    schedule = FeeSchedule((shopee_vn_non_mall(Decimal("0.05"), date(2026, 1, 1)),))
    returned = _line("r3", OrderStatus.RETURNED, actual_fees=None)
    pb = line_profit(returned, COST, schedule=schedule)
    assert pb.fee_source == "formula" and pb.fees_total is not None and pb.fees_total > 0
    assert pb.contribution == -(pb.fees_total + PACKAGING)


async def test_a_stored_returned_line_leaves_the_view_sales_and_costs_its_fees(session):
    """The engine path: a ``returned`` order line in the window adds nothing to the line đơn / GMV
    and takes its fees off the shop contribution."""
    from juli_backend.services.shopee_analytics import loaders, service
    from juli_backend.services.shopee_analytics.windows import Window
    from tests.support.shopee_analytics import CUR_END, CUR_START, seed_shopee_shop
    from tests.support.shopee_analytics import _line as stored_line

    seeded = await seed_shopee_shop(session)
    window = Window(CUR_START, CUR_END)
    ctx = await loaders.load_context(session, seeded.shop_id)
    before = await service.load_view(session, seeded.shop_id, ctx, window)
    session.add(stored_line(seeded.shop_id, 77, CUR_START, "G1", status="returned"))
    await session.flush()
    after = await service.load_view(session, seeded.shop_id, ctx, window)
    returned = [(ln, pb) for ln, pb in after.pairs if ln.status is OrderStatus.RETURNED]
    assert len(returned) == 1
    _, pb = returned[0]
    assert pb.fees_total == Decimal(13_500 + 5_400) and pb.revenue == 0 and pb.cogs == 0
    assert (after.line_orders, after.line_gmv) == (before.line_orders, before.line_gmv)
    assert (after.profit.orders, after.profit.gmv) == (before.profit.orders, before.profit.gmv)
    assert after.profit.contribution == before.profit.contribution - (pb.fees_total + pb.packaging)
