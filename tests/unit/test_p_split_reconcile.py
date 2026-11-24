"""Batch 1124-B (decisions #54 / #55): the channel split's GMV and đơn reconcile to the Tổng quan
totals, and ONE affiliate cost (the commission of the lines in the profit basis) feeds KPI, split
and exports. Synthetic lines only."""

from __future__ import annotations

from decimal import Decimal as D
from types import SimpleNamespace as NS

from juli_backend.services.shopee_analytics.channel_split import (
    SPLIT_CHANNELS,
    affiliate_cost,
    profit_split,
)
from juli_backend.services.shopee_profit.order_profit import OrderStatus, line_profit
from juli_backend.services.shopee_profit.shop_profit import AdsFigures, product_profits
from tests.unit.test_shopee_profit import COST, SCHEDULE, line


def _pair(oid: str, product: str, **kw):
    ln = line(oid, product_id=product, **kw)
    return ln, line_profit(ln, COST, schedule=SCHEDULE)


def _view(pairs, ads: dict[str, AdsFigures] | None = None):
    spend = {"P1": D(0), "P2": D(0)}
    return NS(
        pairs=pairs,
        ads=NS(product_figures=ads or {}),
        profit=NS(
            products=product_profits(pairs, spend),
            total_ad_spend=D(0),
            other_marketing_costs=D(0),
        ),
    )


def _pairs():
    return [
        _pair("o1", "P1"),
        _pair("o1", "P2"),  # one order, two products
        _pair("o2", "P1"),
        _pair("o3", "P1", affiliate=True, commission=D(9000)),
        _pair("o4", "P2", affiliate=True, commission=D(8000)),
        _pair("o4", "P1", affiliate=True, commission=D(7000)),  # one affiliate order, 2 products
        _pair("o5", "P2"),
        _pair("o6", "P1", affiliate=True, commission=D(5000), status=OrderStatus.RETURNED),
    ]


def _totals(pairs):
    sale = [ln for ln, _ in pairs if ln.status is None or ln.status != OrderStatus.RETURNED]
    return sum((ln.order_value for ln in sale), D(0)), D(len({ln.order_id for ln in sale}))


def test_split_gmv_and_orders_add_up_to_the_kpi_totals_shop_and_product_level():
    pairs = _pairs()
    gmv, orders = _totals(pairs)
    view = _view(pairs, {"P1": AdsFigures(D(10000), D(300000), D(250000))})
    split = profit_split(view, kpi_gmv=gmv, kpi_orders=orders)
    for col, want in (("gmv", gmv), ("orders", orders)):
        assert sum(split["rows"][ch][col] for ch in SPLIT_CHANNELS) == want
        assert split["total"][col] == want
    # an order counts once per channel: o4 has two affiliate lines, one TTLK đơn (o3 + o4)
    assert split["rows"]["affiliate"]["orders"] == 2
    p2_gmv, p2_orders = _totals([p for p in pairs if p[0].product_id == "P2"])
    p2 = profit_split(view, "P2", kpi_gmv=p2_gmv, kpi_orders=p2_orders)
    assert p2["total"]["gmv"] == p2_gmv and p2["total"]["orders"] == p2_orders
    assert all(p2["rows"][ch]["orders"] >= 0 for ch in SPLIT_CHANNELS)


def test_organic_is_the_kpi_remainder_clamped_at_zero():
    pairs = _pairs()
    gmv, orders = _totals(pairs)
    smaller = gmv / 4  # a KPI total below the lines' own TTLK GMV: TTLK is capped, organic >= 0
    split = profit_split(_view(pairs), kpi_gmv=smaller, kpi_orders=orders)
    assert split["rows"]["organic"]["gmv"] >= 0
    assert sum(split["rows"][ch]["gmv"] for ch in SPLIT_CHANNELS) == smaller


def test_profit_columns_stay_line_based_and_add_up():
    pairs = _pairs()
    gmv, orders = _totals(pairs)
    view = _view(pairs)
    plain = profit_split(view)
    rec = profit_split(view, kpi_gmv=gmv, kpi_orders=orders)
    for col in (
        "net_revenue",
        "cost_offers",
        "contribution",
        "cost_ads",
        "cost_affiliate",
        "profit",
    ):
        assert rec["total"][col] == plain["total"][col], col


def test_one_affiliate_cost_is_the_covered_lines_commission_everywhere():
    covered = _pairs()
    # an affiliate line whose costs are unknown is outside the profit basis: no commission counted
    uncovered = (
        line("u1", product_id="P1", affiliate=True, commission=D(50000)),
        line_profit(
            line("u1", product_id="P1", affiliate=True, commission=D(50000)),
            None,
            schedule=SCHEDULE,
        ),
    )
    pairs = [*covered, uncovered]
    assert uncovered[1].organic_contribution is None
    aff = affiliate_cost(pairs)
    assert aff == D(9000) + D(8000) + D(7000)  # not the returned line, not the uncovered one
    split = profit_split(_view(pairs))
    assert split["total"]["cost_affiliate"] == aff
    assert affiliate_cost([p for p in pairs if p[0].product_id == "P2"]) == D(8000)
    assert affiliate_cost([]) is None


def test_exports_read_the_one_affiliate_cost_not_a_second_commission_sum():
    from pathlib import Path

    import juli_backend.services.exports.collect as collect

    src = Path(collect.__file__).read_text(encoding="utf-8")
    assert "channel_split.affiliate_cost(" in src and "ln.commission" not in src


def test_the_plans_split_block_adds_up_to_the_same_kpi_totals():
    from juli_backend.services.shopee_recommendations.plan_aggregate import _split_block

    pairs = _pairs()
    gmv, orders = _totals(pairs)
    view = _view(pairs)
    p2_gmv, p2_orders = _totals([p for p in pairs if p[0].product_id == "P2"])
    shop = NS(gmv=gmv + D(1000), orders=int(orders) + 1)
    view.metrics = NS(
        gmv=shop.gmv,
        orders=shop.orders,
        split=lambda pid: NS(gmv=p2_gmv, orders=int(p2_orders)) if pid == "P2" else None,
    )
    env = NS(view=view)
    j = NS(result_basis=1, horizon=1, leaves=[], counted={})
    block = _split_block(env, j, None)
    assert block is not None
    for col, want in (("gmv", shop.gmv), ("orders", D(shop.orders))):
        assert sum(block["today"]["rows"][ch][col] for ch in SPLIT_CHANNELS) == want
    p2 = _split_block(env, j, "P2")
    assert p2 is not None and p2["today"]["total"]["gmv"] == p2_gmv
