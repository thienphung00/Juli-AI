"""P100-B / brief B.5: one shop profit on Tổng quan, Sản phẩm and Kế hoạch.

Shop profit = the profit of the orders whose costs are known, shown with its coverage line
("trên N đơn có chi phí, X % GMV"); the "ước tính theo tỉ lệ" number is gone. The synthetic shop
is rebuilt into the materialized tables and read through every screen's payload: the profit, the
coverage and the margin must be the same number everywhere. Synthetic data only.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from juli_backend.services.shopee_analytics import loaders, materialize, queries, service
from juli_backend.services.shopee_analytics.windows import resolve_window
from juli_backend.services.shopee_profit.order_profit import OrderLine, ProfitBreakdown
from juli_backend.services.shopee_profit.shop_profit import (
    AdCampaign,
    known_cost_profit,
    shop_profit,
)
from tests.support.shopee_analytics import CUR_END, seed_shopee_shop


@pytest.fixture
async def built(session):
    seeded = await seed_shopee_shop(session, rules=True)
    await materialize.backfill_shop(session, seeded.shop_id)
    return seeded


async def _screens(session, shop_id, monkeypatch):
    from juli_backend.services.shopee_recommendations import config, plan_aggregate, plan_base
    from juli_backend.services.shopee_recommendations.loader import load_env

    monkeypatch.setattr(config, "HISTORY_DAYS", 7)  # Kế hoạch reads the window the others show
    kw = {"period": "7d", "as_of": CUR_END}
    ov = await queries.overview(session, shop_id, **kw)
    mx = await queries.matrix(session, shop_id, **kw)
    window = resolve_window("7d", as_of=CUR_END)
    head = await queries.window_metrics(session, shop_id, start=window.start, end=window.end)
    assert head is not None
    env = await load_env(session, shop_id, as_of=CUR_END)
    assert env is not None
    agg, _ = plan_aggregate.aggregate(env, [], now=datetime(2026, 10, 8, 3, tzinfo=UTC))
    base = plan_base.base_json(env)
    frozen = plan_aggregate._today(env, base)  # a draft frozen on this base reads the same
    return ov, mx, head[0], agg["today"], frozen, env


async def test_tong_quan_san_pham_and_ke_hoach_show_one_shop_profit(session, built, monkeypatch):
    ov, mx, head, today, frozen, env = await _screens(session, built.shop_id, monkeypatch)
    sp = ov["shop_profit"]
    assert sp["profit"] is not None and sp["orders"] > 0
    # Tổng quan: the profit block headline, the tile and the payload's one figure
    assert ov["profit"]["profit_vnd"] == sp["profit"]
    assert ov["kpi_strip"]["profit"]["value"] == sp["profit"]
    assert ov["profit"]["margin_pct"] == sp["margin_pct"]
    # Sản phẩm: the product list (matrix) and the Sản phẩm + luồng headline
    assert mx["shop_profit"] == sp
    assert head["profit"] == sp["profit"] and head["margin_pct"] == sp["margin_pct"]
    assert head["shop_profit"] == sp
    # Kế hoạch: live "hôm nay" and a base frozen on the same day
    assert today["profit_30d"] == pytest.approx(sp["profit"], abs=0.01)
    assert today["margin_pct"] == pytest.approx(sp["margin_pct"], abs=0.05)
    assert today["shop_profit"] == sp
    assert frozen["profit_30d"] == pytest.approx(sp["profit"], abs=0.01)
    assert frozen["margin_pct"] == pytest.approx(sp["margin_pct"], abs=0.05)
    # the coverage line, the same words on every screen
    assert sp["label"] == (
        f"trên {sp['orders']} đơn có chi phí, {str(sp['gmv_share_pct']).replace('.', ',')} % GMV"
    )
    # it is the profit of the known-cost orders of the window (no scaling to the shop GMV)
    from juli_backend.services.shopee_analytics.shared import shop_profit_of

    assert sp == shop_profit_of(env.view).json()
    assert ov["kpi_strip"]["margin_pct"]["value"] == pytest.approx(sp["margin_pct"], abs=0.05)


async def test_the_ratio_estimate_is_gone_from_tong_quan(session, built, monkeypatch):
    ov, *_ = await _screens(session, built.shop_id, monkeypatch)
    text = json.dumps(ov, ensure_ascii=False)
    assert "ước tính theo tỉ lệ" not in text
    assert "profit_estimated" not in ov["profit"]
    assert "profit_estimate_label" not in ov["profit"]


async def test_one_profit_function_over_a_partial_window(session, built):
    """The view wrapper is the pure function over the window's profit, lines and shop GMV."""
    from juli_backend.services.shopee_analytics.shared import shop_profit_of

    ctx = await loaders.load_context(session, built.shop_id)
    window = await service.resolve(session, built.shop_id, period="7d", as_of=CUR_END)
    assert window is not None
    view = await service.load_view(session, built.shop_id, ctx, window)
    fig = shop_profit_of(view)
    daily = view.data.ads_daily.spend_by_day
    assert daily, "the seed has daily ads rows"
    assert fig == known_cost_profit(view.profit, view.pairs, view.metrics.gmv, daily)
    assert fig.ads_basis == "daily"


# ---- the pure function ------------------------------------------------------------------


def _line(order: str, product: str, value: int, day: int = 1) -> OrderLine:
    return OrderLine(
        order_id=order,
        sku=f"S-{product}",
        product_id=product,
        order_date=date(2026, 11, day),
        qty=1,
        original_price=Decimal(value),
        deal_price=Decimal(value),
    )


def _pb(revenue: int, contribution: int | None) -> ProfitBreakdown:
    paid = Decimal(revenue)
    known = contribution is not None
    return ProfitBreakdown(
        list_value=paid,
        promo_discount=Decimal(0),
        voucher=Decimal(0),
        bundle=Decimal(0),
        buyer_paid=paid,
        fees=(),
        fees_total=Decimal(0),
        fee_source="formula",
        cogs=paid - Decimal(contribution) if known else None,
        packaging=Decimal(0),
        ads=Decimal(0),
        commission=Decimal(0),
        contribution=Decimal(contribution) if known else None,
        profit=Decimal(contribution) if known else None,
        margin_rate=None,
        missing=() if known else ("cogs",),
    )


def test_unknown_cost_orders_are_left_out_and_counted_against_coverage():
    pairs = [
        (_line("o1", "A", 100_000), _pb(100_000, 40_000)),
        (_line("o2", "A", 100_000), _pb(100_000, 30_000)),
        # P100-A: an order whose cost is unknown carries a NULL profit -- never a 0
        (_line("o3", "B", 200_000), _pb(200_000, None)),
    ]
    sp = shop_profit(pairs, campaigns=[AdCampaign("c", Decimal(0))], product_ad_spend={})
    fig = known_cost_profit(sp, pairs, Decimal(500_000))
    assert fig.profit == Decimal(70_000)
    assert fig.orders == 2 and fig.gmv == Decimal(200_000)
    assert fig.gmv_share_pct == Decimal("40.0")
    assert fig.margin_pct == Decimal("35.0")  # 70k / 200k buyer paid, the same base as the profit
    assert fig.label == "trên 2 đơn có chi phí, 40,0 % GMV"
    assert fig.json()["label"] == fig.label


def test_an_order_with_one_unknown_line_is_not_a_known_cost_order():
    pairs = [
        (_line("o1", "A", 100_000), _pb(100_000, 40_000)),
        (_line("o1", "B", 50_000), _pb(50_000, None)),
        (_line("o2", "A", 100_000), _pb(100_000, 40_000)),
    ]
    sp = shop_profit(pairs, campaigns=[], product_ad_spend={})
    fig = known_cost_profit(sp, pairs, Decimal(250_000))
    assert fig.orders == 1 and fig.gmv == Decimal(100_000)
    # ORDER-based: o1's known line A (40k) is out of the profit and the margin base too
    assert fig.profit == Decimal(40_000)
    assert fig.buyer_paid == Decimal(100_000) and fig.margin_pct == Decimal("40.0")


def test_no_known_cost_gives_no_number_not_zero():
    pairs = [(_line("o1", "A", 100_000), _pb(100_000, None))]
    sp = shop_profit(pairs, campaigns=[], product_ad_spend={})
    fig = known_cost_profit(sp, pairs, Decimal(100_000))
    assert fig.profit is None and fig.margin_pct is None
    assert fig.orders == 0
    assert fig.label == "chưa có đơn nào có đủ chi phí"


def test_ads_on_unknown_cost_days_are_not_order_profit():
    """Prod 04/11-09/11: orders without giá vốn and a stored profit of −ads. Those orders count
    against the coverage; the ads are charged to the known-cost orders only in proportion to
    their share of buyer paid -- never the whole spend subtracted as if it were order profit."""
    pairs = [
        (_line("o1", "A", 100_000), _pb(100_000, 40_000)),
        (_line("o2", "B", 100_000), _pb(100_000, None)),
    ]
    sp = shop_profit(pairs, campaigns=[AdCampaign("c", Decimal(10_000))], product_ad_spend={})
    fig = known_cost_profit(sp, pairs, Decimal(200_000))
    assert fig.profit == Decimal(35_000)  # 40k − 10k × 50 % covered share
    assert fig.orders == 1 and fig.label == "trên 1 đơn có chi phí, 50,0 % GMV"


def test_a_partly_unknown_order_is_out_of_profit_base_and_ads_share():
    """o1 = A (known) + B (unknown cost) -> the whole order is out; product A's report spend is
    charged by the known orders' share of A's buyer paid; the window share drives the rest."""
    pairs = [
        (_line("o1", "A", 100_000), _pb(100_000, 40_000)),
        (_line("o1", "B", 100_000), _pb(100_000, None)),
        (_line("o2", "A", 100_000), _pb(100_000, 30_000)),
        (_line("o3", "A", 200_000), _pb(200_000, 80_000)),
    ]
    sp = shop_profit(
        pairs,
        campaigns=[AdCampaign("c", Decimal(20_000))],
        product_ad_spend={"A": Decimal(8_000)},
    )
    fig = known_cost_profit(sp, pairs, Decimal(500_000))
    assert fig.orders == 2 and fig.buyer_paid == Decimal(300_000)
    # A: 8k x 300/400; unattributed 12k x 300/500 (window share, no daily spend)
    assert fig.ads_basis == "window"
    assert fig.ads_charged == Decimal(6_000) + Decimal(7_200)
    assert fig.profit == Decimal(110_000) - Decimal(13_200)
    assert fig.margin_pct == Decimal("32.3")
    assert fig.label == "trên 2 đơn có chi phí, 60,0 % GMV"


def test_daily_spend_is_charged_by_each_days_known_orders():
    """Day 4: only orders without giá vốn -> its spend is not charged (never order profit);
    day 5: all known -> charged whole; day 6: spend, no order line -> the window share."""
    pairs = [
        (_line("o1", "A", 100_000, day=4), _pb(100_000, None)),
        (_line("o2", "A", 100_000, day=5), _pb(100_000, 40_000)),
    ]
    sp = shop_profit(pairs, campaigns=[AdCampaign("c", Decimal(30_000))], product_ad_spend={})
    daily = {
        date(2026, 11, 4): Decimal(10_000),
        date(2026, 11, 5): Decimal(10_000),
        date(2026, 11, 6): Decimal(10_000),
    }
    fig = known_cost_profit(sp, pairs, Decimal(200_000), daily)
    assert fig.ads_basis == "daily"
    assert fig.ads_charged == Decimal(0) + Decimal(10_000) + Decimal(5_000)
    assert fig.profit == Decimal(25_000)
