"""T5 round 2 (owner 2026-11-18): every đơn / GMV / AOV site goes through ``counts_in_sales`` --
the five numbers' snapshot, the recommendation env and evaluators, the builder's order
statistics, the profit bridge. No refund status (``refunded_accepted``, ``refunded_not_received``,
``returned``) is a sale; its settlement cost stays in the profit. Synthetic amounts only.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from juli_backend.services.shopee_builder import copurchase
from juli_backend.services.shopee_builder.engine_families import adapters
from juli_backend.services.shopee_builder.variations import with_orders
from juli_backend.services.shopee_profit.five_numbers import snapshot_from
from juli_backend.services.shopee_profit.income import LineIncome
from juli_backend.services.shopee_profit.order_profit import (
    REFUND_STATUSES,
    OrderLine,
    OrderStatus,
    SkuCost,
    counts_in_sales,
    profit_lines,
)
from juli_backend.services.shopee_recommendations.env import RecoEnv, voucher_takeup
from juli_backend.services.shopee_recommendations.evaluate import _item_gmv

COST = SkuCost(sku="S1", cogs=Decimal(30_000), packaging=Decimal(2_000))
REFUNDS = sorted(REFUND_STATUSES)
SETTLED = LineIncome(
    fees=(),
    commission=Decimal(0),
    net_shipping=Decimal(0),
    return_shipping=Decimal(0),
    refund=Decimal(0),
    compensation=Decimal(0),
    tax_withheld=Decimal(0),
    seller_coin=Decimal(0),
    trade_in=Decimal(0),
    payout=Decimal(-7_000),
)


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


def test_no_refund_status_is_a_sale():
    assert all(not s.counts_in_sales for s in REFUND_STATUSES)
    assert all(s.counts_in_sales for s in OrderStatus if s not in REFUND_STATUSES)
    for status in REFUND_STATUSES:
        assert not counts_in_sales(_line("r", status))
        assert not counts_in_sales(SimpleNamespace(status=status.value))  # a stored string
    assert counts_in_sales(SimpleNamespace())  # a what-if line without a status


@pytest.mark.parametrize("status", REFUNDS)
def test_the_five_numbers_snapshot_leaves_a_refund_out_of_orders_and_gmv(status):
    refund = _line("r1", status, income=SETTLED)
    both = snapshot_from(profit_lines([DELIVERED, refund], {"S1": COST}), Decimal(0))
    sold = snapshot_from(profit_lines([DELIVERED], {"S1": COST}), Decimal(0))
    assert (both.orders, both.gmv, both.list_value) == (sold.orders, sold.gmv, sold.list_value)
    assert both.orders == 1 and both.gmv == Decimal(90_000)
    assert both.discount == sold.discount  # its promo is no spend either
    assert both.contribution < sold.contribution  # its settlement cost stays in the profit


@pytest.mark.parametrize("status", REFUNDS)
def test_the_reco_env_sales_pairs_and_orders_leave_a_refund_out(status):
    pairs = profit_lines([DELIVERED, _line("r1", status)], {"S1": COST})
    env = SimpleNamespace(view=SimpleNamespace(pairs=pairs), _sales_pairs=None)
    sales = RecoEnv.sales_pairs.fget(env)
    assert [ln.order_id for ln, _ in sales] == ["d1"]
    env.sales_pairs = sales
    assert RecoEnv.orders_of(env, "1001") == 1


@pytest.mark.parametrize("status", REFUNDS)
def test_reco_and_builder_order_statistics_skip_a_refund(status):
    lines = [DELIVERED, _line("r1", status), _line("d2", OrderStatus.IN_TRANSIT, product="2002")]
    assert _item_gmv(lines, "1001") == Decimal(90_000)
    assert adapters.order_values(lines) == {"d1": Decimal(90_000), "d2": Decimal(90_000)}
    assert sorted(map(sorted, copurchase.order_sets(lines))) == [["1001"], ["2002"]]
    rows = with_orders([{"sku_key": "S1"}], lines, "1001")
    assert rows[0]["orders_30d"] == 1


def test_voucher_takeup_counts_only_the_orders_that_are_sales():
    voucher = {"shop_voucher_share": Decimal(5_000)}
    lines = [_line(f"d{n}", OrderStatus.DELIVERED) for n in range(40)]
    refunds = [_line(f"r{n}", REFUNDS[n % 3], **voucher) for n in range(40)]
    lines.append(_line("v1", OrderStatus.DELIVERED, **voucher))
    rate = voucher_takeup(lines + refunds, Decimal(0), None)
    assert rate == Decimal(1) / Decimal(41)


async def test_the_profit_bridge_adds_up_to_the_headline_without_a_second_refund_cut(session):
    """The headline from the sale lines already leaves the refund orders out, so the bridge does
    not subtract them again: GMV - cancelled - in transit = the delivered orders' GMV. On
    Shopee's own total (which still holds them) the refund row is subtracted once. (The seed's
    lines do not cover Shopee's total, so the exact sum is checked on the sale-line headline.)"""
    from juli_backend.services.exports.profit_bridge import profit_bridge
    from juli_backend.services.shopee_analytics import loaders, service
    from juli_backend.services.shopee_analytics.compute import compute_view
    from juli_backend.services.shopee_analytics.loaders import ShopTotals
    from juli_backend.services.shopee_analytics.windows import Window
    from tests.support.shopee_analytics import CUR_END, CUR_START, seed_shopee_shop
    from tests.support.shopee_analytics import _line as stored_line

    seeded = await seed_shopee_shop(session)
    ctx = await loaders.load_context(session, seeded.shop_id)
    for n, status in enumerate(REFUNDS):
        session.add(stored_line(seeded.shop_id, 70 + n, CUR_START, "G1", status=status.value))
    await session.flush()
    view = await service.load_view(session, seeded.shop_id, ctx, Window(CUR_START, CUR_END))
    delivered = sum(
        (ln.order_value for ln, _ in view.pairs if ln.status is OrderStatus.DELIVERED),
        Decimal(0),
    )
    refund_gmv = sum(
        (ln.order_value for ln, _ in view.pairs if ln.status in REFUND_STATUSES), Decimal(0)
    )
    assert refund_gmv == Decimal(3 * 90_000)
    # the headline from the sale lines: the same window without Shopee's shop totals
    no_totals = ShopTotals(None, None, "none", 0, view.data.totals.window_days)
    data = replace(view.data, totals=no_totals, stored=None, rows_policy="raw")
    lines_view = compute_view(ctx, data)
    b = profit_bridge(lines_view)
    assert not lines_view.gmv_from_totals and not b.refunds_in_gmv
    assert (b.refund_orders, b.refund_gmv) == (3, float(refund_gmv))
    assert b.gmv == float(lines_view.line_gmv)  # the sale lines: no refund inside
    assert b.gmv - b.lost_gmv - b.pending_gmv == pytest.approx(float(delivered))
    # on Shopee's own total (which still holds them) the bridge subtracts the refund row once
    assert view.gmv_from_totals and profit_bridge(view).refunds_in_gmv


def test_the_cost_coverage_counts_sale_orders_and_gmv_only_and_keeps_the_refund_cost():
    """``known_cost_profit``: 10 delivered orders at 90.000 plus one refunded_accepted order with
    a settlement row (payout -20.000) on a sale-line headline: "trên 10 đơn có chi phí, 100 %
    GMV" (never over 100 %), and the profit still carries the refund's 20.000 cost."""
    from juli_backend.services.shopee_profit.shop_profit import known_cost_profit, shop_profit

    sold = [_line(f"d{n}", OrderStatus.DELIVERED) for n in range(10)]
    refund = _line(
        "r1", OrderStatus.REFUNDED_ACCEPTED, income=replace(SETTLED, payout=Decimal(-20_000))
    )
    costs = {"S1": COST}
    pairs = profit_lines([*sold, refund], costs)
    sales_only = profit_lines(sold, costs)
    headline = Decimal(10 * 90_000)  # the sale lines: the refund is not in it
    sp = shop_profit(pairs, campaigns=[], product_ad_spend={})
    fig = known_cost_profit(sp, pairs, headline)
    base = known_cost_profit(
        shop_profit(sales_only, campaigns=[], product_ad_spend={}), sales_only, headline
    )
    assert (fig.orders, fig.gmv, fig.gmv_share_pct) == (10, headline, Decimal("100.0"))
    assert fig.profit == base.profit - Decimal(20_000)
