"""C1 (owner 2026-11-25): an order still on its way is an order. Its cost is not known yet, so its
day's ads are not charged to the orders whose costs are known, and the day is never a "day
without orders". Before, in-transit lines were outside the ads share: a day whose orders were all
in transit charged its whole spend against nothing (profit = -ads). Synthetic data only."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    OrderStatus,
    ProfitBreakdown,
)
from juli_backend.services.shopee_profit.shop_profit import (
    AdCampaign,
    known_cost_profit,
    shop_profit,
)

ZERO = Decimal(0)


def _pair(order, value, day, contribution=None, status=OrderStatus.DELIVERED):
    v = Decimal(value)
    ln = OrderLine(
        order_id=order,
        sku="S-A",
        product_id="A",
        order_date=date(2026, 11, day),
        qty=1,
        original_price=v,
        deal_price=v,
        status=status,
    )
    known = contribution is not None
    c = Decimal(contribution) if known else None
    pb = ProfitBreakdown(
        list_value=v,
        promo_discount=ZERO,
        voucher=ZERO,
        bundle=ZERO,
        buyer_paid=v,
        fees=(),
        fees_total=ZERO,
        fee_source="formula",
        cogs=v - c if known else None,
        packaging=ZERO,
        ads=ZERO,
        commission=ZERO,
        contribution=c,
        profit=c,
        margin_rate=None,
        missing=() if known else ("cogs",),
    )
    if not status.carries_profit:
        pb = replace(pb, status=status, excluded_reason="no_fee_no_profit", missing=())
    return ln, pb


def _fig(pairs, gmv, daily, **kw):
    spend = sum(daily.values(), ZERO)
    sp = shop_profit(pairs, campaigns=[AdCampaign("c", spend)], product_ad_spend={})
    return known_cost_profit(sp, pairs, Decimal(gmv), daily, **kw)


def test_a_day_with_only_in_transit_orders_charges_no_ads():
    pairs = [
        _pair("o1", 100_000, 4, 40_000),
        _pair("o2", 900_000, 5, status=OrderStatus.IN_TRANSIT),
    ]
    daily = {date(2026, 11, 4): Decimal(10_000), date(2026, 11, 5): Decimal(60_000)}
    fig = _fig(pairs, 1_000_000, daily)
    assert fig.ads_no_order_days == ZERO
    assert fig.ads_charged == Decimal(10_000)
    assert fig.profit == Decimal(30_000)
    assert fig.margin_pct == Decimal("30.0")
    assert fig.ads_total == Decimal(70_000)


def test_a_mixed_day_charges_the_known_orders_share_of_every_open_order():
    pairs = [
        _pair("o1", 100_000, 4, 40_000),
        _pair("o2", 300_000, 4, status=OrderStatus.IN_TRANSIT),
    ]
    fig = _fig(pairs, 400_000, {date(2026, 11, 4): Decimal(20_000)})
    assert fig.ads_charged == Decimal(5_000)  # 20k x 100k / 400k, not the whole 20k
    assert fig.profit == Decimal(35_000)


def test_the_window_share_counts_in_transit_orders_too():
    pairs = [
        _pair("o1", 100_000, 4, 40_000),
        _pair("o2", 100_000, 5, status=OrderStatus.IN_TRANSIT),
    ]
    sp = shop_profit(pairs, campaigns=[AdCampaign("c", Decimal(10_000))], product_ad_spend={})
    fig = known_cost_profit(sp, pairs, Decimal(200_000))
    assert fig.ads_basis == "window"
    assert fig.ads_charged == Decimal(5_000)


def test_a_day_with_no_orders_or_only_cancelled_ones_still_charges_its_ads():
    pairs = [
        _pair("o1", 100_000, 4, 40_000),
        _pair("o2", 50_000, 5, status=OrderStatus.CANCELLED),
    ]
    daily = {date(2026, 11, d): Decimal(10_000) for d in (4, 5, 6)}
    fig = _fig(pairs, 100_000, daily)
    assert fig.ads_no_order_days == Decimal(20_000)  # day 5 (cancelled only) and day 6
    assert fig.profit == Decimal(10_000)


def test_the_stored_day_of_in_transit_orders_has_no_profit_not_minus_ads():
    day = date(2026, 11, 5)

    def view(pairs):
        return SimpleNamespace(
            pairs=pairs,
            data=SimpleNamespace(
                ads_daily=SimpleNamespace(spend_by_day={day: Decimal(60_000)}),
                totals=SimpleNamespace(basis="daily"),
            ),
        )

    moving = [_pair("o2", 900_000, 5, status=OrderStatus.IN_TRANSIT)]
    assert materialize._no_order_day_profit(view(moving), day) is None
    assert materialize._no_order_day_profit(view([]), day) == Decimal(-60_000)
    gone = [_pair("o3", 900_000, 5, status=OrderStatus.CANCELLED)]
    assert materialize._no_order_day_profit(view(gone), day) == Decimal(-60_000)
