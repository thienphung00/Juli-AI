"""D7: profit / margin that Chat reads (product and campaign) count delivered orders only
(owner 23/11, fact profit_delivered_only). An in-transit order changes đơn / GMV, never profit."""

from __future__ import annotations

from decimal import Decimal as D
from types import SimpleNamespace
from typing import Any, cast

from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    OrderStatus,
    SkuCost,
    profit_lines,
)
from juli_backend.services.shopee_profit.shop_profit import AdsFigures, product_profits
from juli_backend.services.shopee_recommendations.evaluate import campaign_profile
from tests.unit.test_shopee_profit_p90 import DAY, SCHEDULE

COSTS = {"S1": SkuCost("S1", D(40000), D(0))}


def _profits(statuses: list[OrderStatus]) -> dict[str, Any]:
    lines = [
        OrderLine(f"o{i}", "S1", "P1", DAY, 1, D(100000), D(100000), status=st)
        for i, st in enumerate(statuses)
    ]
    return product_profits(profit_lines(lines, COSTS, schedule=SCHEDULE), {"P1": D(10000)})


def test_in_transit_order_moves_orders_and_gmv_but_not_profit_or_margin() -> None:
    base = _profits([OrderStatus.DELIVERED, OrderStatus.DELIVERED])["P1"]
    more = _profits([OrderStatus.DELIVERED, OrderStatus.DELIVERED, OrderStatus.IN_TRANSIT])["P1"]
    assert (base.orders, more.orders) == (2, 3)
    assert more.gmv > base.gmv
    assert more.contribution == base.contribution
    assert more.profit == base.profit and more.margin_pct == base.margin_pct


def test_campaign_profit_before_ads_ignores_in_transit_orders() -> None:
    def read(statuses: list[OrderStatus]) -> dict[str, Any]:
        profits = _profits(statuses)
        alloc = SimpleNamespace(
            key="c1", spend=D(10000), direct_gmv=D(100000), products={"P1": D(10000)}
        )
        env = SimpleNamespace(
            view=SimpleNamespace(
                ads=SimpleNamespace(
                    campaigns=[alloc],
                    product_figures={"P1": AdsFigures(D(10000), D(100000), D(100000))},
                    product_spend={"P1": D(10000)},
                )
            ),
            window_days=7,
            product=lambda item: profits.get(item),
        )
        got = campaign_profile(cast(Any, env), "c1")
        assert got is not None
        return got

    a = read([OrderStatus.DELIVERED, OrderStatus.DELIVERED])
    b = read([OrderStatus.DELIVERED, OrderStatus.DELIVERED, OrderStatus.IN_TRANSIT])
    assert a["profit_before_ads_per_day"] == b["profit_before_ads_per_day"]
    assert a["break_even_roas"] == b["break_even_roas"]
