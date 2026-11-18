"""T5 / owner D2 and the refund-cost rule (owner 2026-11-18).

A refund status -- ``refunded_accepted`` (refund window open), ``refunded_not_received`` (return
parcel on its way back), ``returned`` (goods back, buyer refunded): revenue 0, no goods cost, no
commission. Its cost is what the settlement deducted, ``max(0, -payout)`` of the order's
settlement row, as soon as a row exists whatever the status says; no row = no cost yet. The fee
and shipping columns are never summed for it (the payout nets them). A ``returned`` line also
costs its packaging. None of the three is counted in đơn / GMV / AOV. Synthetic amounts only.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from juli_backend.services.shopee_profit.income import (
    FEE_FIXED,
    FEE_PAYMENT,
    FEE_SERVICE,
    LineIncome,
)
from juli_backend.services.shopee_profit.order_profit import (
    FEE_SOURCE_NO_SETTLEMENT,
    FEE_SOURCE_SETTLEMENT,
    REFUND_STATUSES,
    OrderLine,
    OrderStatus,
    SkuCost,
    counts_in_sales,
    line_profit,
    profit_lines,
    settlement_deduction,
)
from juli_backend.services.shopee_profit.shop_profit import shop_profit

FEES = Decimal(8_000)
PACKAGING = Decimal(2_000)
COST = SkuCost(sku="S1", cogs=Decimal(30_000), packaging=PACKAGING)
#: a settlement whose columns offset each other: fees, shipping charged, the return shipping
#: refunded, a failed-return charge -- and the payout that nets them all
DEDUCTED = Decimal("12345")


def _income(payout: Decimal | None) -> LineIncome:
    return LineIncome(
        fees=(
            (FEE_FIXED, Decimal(4_000)),
            (FEE_SERVICE, Decimal(1_500)),
            (FEE_PAYMENT, Decimal(900)),
        ),
        commission=Decimal(3_000),
        net_shipping=Decimal(-41_000),
        return_shipping=Decimal(41_000),
        refund=Decimal(90_000),
        compensation=Decimal(0),
        tax_withheld=Decimal(0),
        seller_coin=Decimal(0),
        trade_in=Decimal(0),
        payout=payout,
    )


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


def test_the_refund_statuses_settle_by_payout_and_none_is_a_sale():
    returned = OrderStatus("returned")
    assert returned is OrderStatus.RETURNED
    assert REFUND_STATUSES == {
        OrderStatus.REFUNDED_ACCEPTED,
        OrderStatus.REFUNDED_NOT_RECEIVED,
        OrderStatus.RETURNED,
    }
    assert all(s.settles_by_payout for s in REFUND_STATUSES)
    assert not any(s.carries_profit or s.charges_fees for s in REFUND_STATUSES)
    assert not any(s.counts_in_sales for s in REFUND_STATUSES)
    assert all(s.counts_in_sales for s in OrderStatus if s not in REFUND_STATUSES)
    assert OrderStatus.DELIVERED.charges_fees and not OrderStatus.CANCELLED.charges_fees


@pytest.mark.parametrize("status", sorted(REFUND_STATUSES))
def test_a_refund_costs_exactly_the_settlement_deduction_not_the_columns(status):
    """(a) fee and shipping columns non-zero and offsetting; the payout nets them."""
    line = _line("r1", status, income=_income(-DEDUCTED), affiliate=True)
    pb = line_profit(line, COST)
    packaging = PACKAGING if status is OrderStatus.RETURNED else Decimal(0)
    assert settlement_deduction(line) == DEDUCTED
    assert (pb.fees_total, pb.fee_source) == (DEDUCTED, FEE_SOURCE_SETTLEMENT)
    assert (pb.revenue, pb.cogs, pb.commission, pb.income_costs) == (0, 0, 0, None)
    assert pb.packaging == packaging
    assert pb.contribution == -(DEDUCTED + packaging)
    assert pb.excluded_reason is None and pb.missing == ()


@pytest.mark.parametrize("payout", [Decimal(0), Decimal(5_000)])
def test_a_refund_whose_payout_is_not_negative_costs_nothing(payout):
    """(b) payout >= 0 -> cost 0."""
    pb = line_profit(_line("r2", OrderStatus.REFUNDED_NOT_RECEIVED, income=_income(payout)), COST)
    assert (pb.fees_total, pb.contribution) == (0, 0)
    returned = line_profit(_line("r3", OrderStatus.RETURNED, income=_income(payout)), COST)
    assert returned.contribution == -PACKAGING


@pytest.mark.parametrize(
    "status", [OrderStatus.REFUNDED_ACCEPTED, OrderStatus.REFUNDED_NOT_RECEIVED]
)
def test_a_refund_without_a_settlement_has_no_cost_yet(status):
    """(c) no settlement row -> no cost (the reported fees are not used either)."""
    pb = line_profit(_line("r4", status), COST)
    assert pb.excluded_reason == "no_fee_no_profit"
    assert pb.contribution is None and pb.fees_total is None


def test_a_returned_line_without_a_settlement_costs_its_packaging_only():
    pb = line_profit(_line("r5", OrderStatus.RETURNED), COST)
    assert (pb.fees_total, pb.fee_source) == (0, FEE_SOURCE_NO_SETTLEMENT)
    assert pb.contribution == -PACKAGING
    unknown = line_profit(
        _line("r6", OrderStatus.RETURNED), SkuCost(sku="S1", cogs=None, packaging=None)
    )
    assert unknown.contribution is None and unknown.missing == ("packaging",)


def test_refunded_accepted_with_a_settlement_is_counted_in_the_profit():
    """(d) the refund window still open, but a settlement row exists: its cost counts."""
    line = _line("r7", OrderStatus.REFUNDED_ACCEPTED, income=_income(-DEDUCTED))
    shop = shop_profit(profit_lines([line], {"S1": COST}), campaigns=[], product_ad_spend={})
    assert shop.contribution == -DEDUCTED
    assert not counts_in_sales(line)  # no sale (owner 2026-11-18), yet its cost counts
    assert (shop.orders, shop.gmv) == (0, 0)


def test_a_delivered_line_is_unchanged():
    pb = line_profit(_line("d1", OrderStatus.DELIVERED), COST)
    assert pb.revenue == Decimal(90_000)
    assert pb.contribution == Decimal(90_000) - FEES - Decimal(30_000) - PACKAGING


def test_returned_is_outside_orders_and_gmv_and_inside_profit():
    delivered = _line("d1", OrderStatus.DELIVERED)
    returned = _line("r1", OrderStatus.RETURNED, income=_income(-DEDUCTED))
    assert counts_in_sales(delivered) and not counts_in_sales(returned)
    pairs = profit_lines([delivered, returned], {"S1": COST})
    only = profit_lines([delivered], {"S1": COST})
    shop = shop_profit(pairs, campaigns=[], product_ad_spend={})
    base = shop_profit(only, campaigns=[], product_ad_spend={})
    assert (shop.orders, shop.gmv) == (base.orders, base.gmv) == (1, Decimal(90_000))
    assert shop.buyer_paid == base.buyer_paid  # revenue 0 adds nothing to the margin base
    assert shop.contribution == base.contribution - (DEDUCTED + PACKAGING)
    product = shop.products["1001"]
    assert (product.orders, product.gmv) == (1, Decimal(90_000))
    assert product.contribution == base.products["1001"].contribution - (DEDUCTED + PACKAGING)


def test_a_returned_line_takes_no_share_of_the_per_order_formula_fees():
    from juli_backend.services.shopee_profit.fees import FeeSchedule, shopee_vn_non_mall

    schedule = FeeSchedule((shopee_vn_non_mall(Decimal("0.05"), date(2026, 1, 1)),))
    returned = _line("r8", OrderStatus.RETURNED, actual_fees=None)
    pb = line_profit(returned, COST, schedule=schedule)
    assert pb.fee_source == FEE_SOURCE_NO_SETTLEMENT and pb.fees_total == 0
    assert pb.contribution == -PACKAGING


async def test_a_stored_returned_line_leaves_the_view_sales_and_costs_its_settlement(session):
    """The engine path: a ``returned`` order line in the window adds nothing to the line đơn / GMV;
    without a settlement row it costs its packaging only, with one the deduction too."""
    import uuid

    from juli_backend.models.shopee_profit import ShopeeOrderIncome
    from juli_backend.services.shopee_analytics import loaders, service
    from juli_backend.services.shopee_analytics.windows import Window
    from tests.support.shopee_analytics import CUR_END, CUR_START, _ref, seed_shopee_shop
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
    assert pb.fees_total == 0 and pb.revenue == 0 and pb.cogs == 0  # reported fees not used
    assert (after.line_orders, after.line_gmv) == (before.line_orders, before.line_gmv)
    assert (after.profit.orders, after.profit.gmv) == (before.profit.orders, before.profit.gmv)
    assert after.profit.contribution == before.profit.contribution - pb.packaging
    session.add(
        ShopeeOrderIncome(
            id=uuid.uuid4(),
            shop_id=seeded.shop_id,
            platform="shopee",
            order_ref=_ref(77),
            payout=-DEDUCTED,
            fee_fixed=Decimal(4_000),
            net_shipping_cost=Decimal(41_000),
            return_ship_refund=Decimal(41_000),
            source="file",
            source_rank=2,
            source_version="t5",
        )
    )
    await session.flush()
    settled = await service.load_view(session, seeded.shop_id, ctx, window)
    ((_, spb),) = [(ln, b) for ln, b in settled.pairs if ln.status is OrderStatus.RETURNED]
    assert (spb.fees_total, spb.fee_source) == (DEDUCTED, FEE_SOURCE_SETTLEMENT)
    assert settled.profit.contribution == before.profit.contribution - (DEDUCTED + spb.packaging)
