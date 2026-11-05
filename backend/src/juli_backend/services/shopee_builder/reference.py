"""A listing nobody bought in the window still has a price, a giá vốn and a fee formula, so the
unit economics of a change (profit per order, margin, break-even extra orders) can be computed.

The evaluators read order lines; a listing with none would be refused. For such a listing the
builder gives its environment ONE reference order per variation at the catalogue price (qty 1).
These lines exist only in the builder's copy of the environment, never in the shop's numbers, and
every outcome built on them reports the basis as ``insufficient`` (no volume is predicted from a
reference order).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    OrderStatus,
    SkuCost,
    profit_lines,
)
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.unit_cost import unit_cost


def zero_order_items(env: RecoEnv, items: Iterable[str]) -> list[str]:
    have = {ln.product_id for ln, _ in env.view.pairs}
    return [i for i in dict.fromkeys(items) if i and i not in have and i not in env.excluded]


def with_reference_lines(
    env: RecoEnv, rows_by_item: Mapping[str, Sequence[Mapping[str, Any]]], items: Iterable[str]
) -> tuple[RecoEnv, set[str]]:
    """``(env, reference items)``: ``env`` is a copy carrying the reference orders (the same object
    when no item needs one)."""
    wanted = zero_order_items(env, items)
    pairs = list(env.view.pairs)
    costs = dict(env.view.costs.by_key)
    list_price = dict(env.view.costs.list_price)
    done: set[str] = set()
    for item in wanted:
        for row in rows_by_item.get(item, ()):
            listed, selling = row.get("list_price"), row.get("selling_price")
            if listed is None and selling is None:
                continue
            listed_d = Decimal(str(listed if listed is not None else selling))
            selling_d = Decimal(str(selling if selling is not None else listed))
            key = str(row["sku_key"])
            vid = str(row.get("variation_id") or "")
            cost = unit_cost(
                env.rules,
                item,
                vid,
                seller_sku=row.get("sku"),
                variation_name=row.get("name"),
            )
            costs[key] = SkuCost(key, cost.cogs, cost.packaging, vat=cost.vat)
            list_price[key] = listed_d
            line = OrderLine(
                order_id=f"ref:{item}:{vid}",
                sku=key,
                product_id=item,
                order_date=env.as_of,
                qty=1,
                original_price=max(listed_d, selling_d),
                deal_price=selling_d,
                status=OrderStatus.DELIVERED,
            )
            pairs.extend(profit_lines([line], costs, schedule=env.schedule(item)))
            done.add(item)
    if not done:
        return env, set()
    view = replace(
        env.view,
        pairs=pairs,
        costs=replace(env.view.costs, by_key=costs, list_price=list_price),
    )
    return replace(env, view=view, _floor_cache={}), done


__all__ = ["with_reference_lines", "zero_order_items"]
