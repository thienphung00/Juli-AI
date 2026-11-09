"""P97 D85.15: Combo khuyến mãi in Shopee's own shape.

One combo = a list of products (no per-item quantity or variation), a discount type (giảm %, giảm
số tiền, giá đặc biệt) and tiers "Mua N sản phẩm → x". A buyer who puts N units of ANY listed
products in the order gets the best tier N reaches. It is the same ``bundle_deal`` kind the engine
generates (there with one product and the tiers 2 and 3 as ``tier2_pct`` / ``tier3_pct``); the
generated card keeps its own path in ``evaluate.eval_bundle``.

The arithmetic, deliberately simple and stated on the card:

- every tier is turned into an effective percent of the listed products' average unit price in the
  window (a percent is itself; an amount ``d`` off N units = d / (N x avg); a special price ``p``
  for N units = 1 - p / (N x avg)) -- so all three types are priced by the same lines;
- the certain cost is what the tier would have given on the orders of the window that already hold
  enough listed units: ``floor(units / N)`` combos of N units at the effective percent;
- the floor check prices one bundle line per listed product at the tier's effective percent;
- the predicted range comes from the existing lift model (sim kind ``combo_pack``, AOV lift).

"Giới hạn đặt hàng" (combos per buyer) has no per-buyer data behind it: it rides along on the
card for the fill and is named in the notes, not in the numbers.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.fmt import num, pct
from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div, to_dong
from juli_backend.services.shopee_profit.order_profit import OrderLine, profit_lines
from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.evaluate import (
    D,
    _bundle_line,
    _five,
    _refuse,
    _scope_ad_spend,
    _scope_gmv_per_day,
    _scope_orders,
    _spend_check,
    _unknown_floors,
    scope_snapshot,
)
from juli_backend.services.shopee_recommendations.model import Candidate, Evaluation, ProfitModel

TYPES = ("pct", "amount", "special_price")
TYPE_LABELS = {
    "pct": "Giảm giá theo %",
    "amount": "Giảm giá theo số tiền",
    "special_price": "Giảm giá đặc biệt",
}
MAX_TIERS = 5
MIN_QTY, MAX_QTY = 2, 9999
MAX_PRODUCTS = 100
MAX_DISCOUNT_SHARE = Decimal(90)
MAX_NAME = 25
MIN_SPECIAL_PRICE = Decimal(1000)


@dataclass(frozen=True)
class Tier:
    qty: int
    value: Decimal


def tiers_of(inputs: Mapping[str, Any]) -> list[Tier]:
    """The tiers of the inputs, by quantity; raises ``ValueError`` on a malformed row."""
    raw = inputs.get("tiers")
    if not isinstance(raw, Sequence) or isinstance(raw, str) or not raw:
        raise ValueError("no tiers")
    out = [Tier(int(t["qty"]), D(t["value"])) for t in raw]
    return sorted(out, key=lambda t: t.qty)


def tier_text(dtype: str, tier: Tier) -> str:
    """The row as Shopee words it: "Mua 2 sản phẩm để được giảm 5 %" / "… chỉ với giá 90.000đ"."""
    value = f"{int(tier.value):,}".replace(",", ".")
    if dtype == "pct":
        return f"Mua {tier.qty} sản phẩm để được giảm {tier.value.normalize():f}%"
    if dtype == "amount":
        return f"Mua {tier.qty} sản phẩm để được giảm {value}đ"
    return f"Mua {tier.qty} sản phẩm chỉ với giá {value}đ"


def effective_pct(dtype: str, tier: Tier, avg_price: Decimal) -> Decimal:
    """The tier as a percent off ``avg_price`` x N; raises ``ValueError(code)`` when it is no
    discount or takes more than 90 % off."""
    base = avg_price * tier.qty
    if dtype == "pct":
        eff = tier.value
    elif dtype == "amount":
        eff = tier.value / base * 100 if base > 0 else Decimal(100)
    else:
        if tier.value < MIN_SPECIAL_PRICE:  # almost always a percent typed in the wrong mode
            raise ValueError("combo_price_too_low")
        eff = (1 - tier.value / base) * 100 if base > 0 else Decimal(-1)
        if eff <= 0:
            raise ValueError("combo_price_not_below_value")
    if eff > MAX_DISCOUNT_SHARE:
        raise ValueError("combo_discount_over_max")
    return eff


def best_tier(units: int, tiers: Sequence[Tier]) -> Tier | None:
    eligible = [t for t in tiers if t.qty <= units]
    return eligible[-1] if eligible else None


def eval_bundle_tiers(
    env: RecoEnv, cand: Candidate, inputs: Mapping[str, Any], predicted: Any = None
) -> Evaluation:
    """The certain layer of a ``bundle_deal`` candidate in Shopee's shape (see the module)."""
    del predicted
    items = list(dict.fromkeys(cand.items))
    dtype = str(inputs.get("discount_type", "pct"))
    if not items or len(items) > MAX_PRODUCTS:
        return _refuse("combo_needs_products")
    if dtype not in TYPES:
        return _refuse("combo_discount_type_invalid")
    try:
        tiers = tiers_of(inputs)
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return _refuse("combo_tiers_invalid")
    if len({t.qty for t in tiers}) != len(tiers) or not all(
        MIN_QTY <= t.qty <= MAX_QTY and t.value > 0 for t in tiers
    ):
        return _refuse("combo_tiers_invalid")
    wanted = set(items)
    lines = env.lines_for(items)
    listed = [ln for ln in lines if ln.product_id in wanted]
    if not listed:
        return _refuse("no_order_lines")
    units_total = sum(ln.qty for ln in listed)
    avg_price = sum((ln.order_value for ln in listed), ZERO) / Decimal(units_total)
    try:
        eff = {t.qty: effective_pct(dtype, t, avg_price) for t in tiers}
    except ValueError as exc:
        return _refuse(str(exc))

    # one reference line per listed product that sold: its best-selling SKU, newest line
    refs: dict[str, OrderLine] = {}
    for item in items:
        mine = [ln for ln in listed if ln.product_id == item]
        if not mine:
            continue
        by_sku: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for ln in mine:
            by_sku[ln.sku] += ln.order_value
        sku = max(by_sku, key=lambda s: by_sku[s])
        refs[item] = max((ln for ln in mine if ln.sku == sku), key=lambda ln: ln.order_date)
    breaches: list[dict[str, Any]] = []
    tier_rows: list[dict[str, Any]] = []
    rate_of: dict[int, Decimal | None] = {}
    for t in tiers:
        rows: list[dict[str, Any]] = []
        revenue = contribution = ZERO
        known = True
        for item, ref in refs.items():
            pb = profit_lines(
                [_bundle_line(ref, t.qty, eff[t.qty])], env.costs, schedule=env.schedule(item)
            )[0][1]
            unit_paid = pb.buyer_paid / t.qty
            floor_px = env.floor_price(item, ref.sku)
            below = floor_px is not None and unit_paid < floor_px
            floor = env.floors(item).get(ref.sku)
            if below and floor is not None:
                breaches.append(
                    {
                        "sku": ref.sku,
                        "kind": "operating" if floor.operating_floor is not None else "absolute",
                        "floor": num(floor_px),
                        "min_unit_price": num(unit_paid),
                        "lines": 1,
                        "tier": t.qty,
                        "item_id": item,
                    }
                )
            revenue += pb.buyer_paid
            if pb.contribution is None:
                known = False
            else:
                contribution += pb.contribution
            rows.append(
                {
                    "item_id": item,
                    "unit_price_after": num(unit_paid),
                    "margin_pct": pct(pct_points(safe_div(pb.contribution, pb.buyer_paid)))
                    if pb.contribution is not None
                    else None,
                    "below_floor": bool(below),
                }
            )
        rate_of[t.qty] = safe_div(contribution, revenue) if known and revenue > 0 else None
        tier_rows.append(
            {
                "units": t.qty,
                "value": num(t.value),
                "text": tier_text(dtype, t),
                "discount_pct": num(eff[t.qty]),
                "items": rows,
                "margin_pct": pct(pct_points(safe_div(contribution, revenue)))
                if known and revenue > 0
                else None,
                "below_floor": any(r["below_floor"] for r in rows),
            }
        )

    # the certain cost: what each tier gives on the orders of the window that already qualify
    by_order: dict[str, list[OrderLine]] = defaultdict(list)
    for ln in listed:
        by_order[ln.order_id].append(ln)
    extra_cost = ZERO
    qualifying = 0
    discount_of: dict[tuple[str, int], Decimal] = {}
    for oid, group in by_order.items():
        units = sum(ln.qty for ln in group)
        tier = best_tier(units, tiers)
        if tier is None:
            continue
        qualifying += 1
        covered = Decimal((units // tier.qty) * tier.qty) / Decimal(units)
        for ln in group:
            cut = to_dong(ln.order_value * covered * eff[tier.qty] / 100)
            discount_of[(oid, id(ln))] = cut
            extra_cost += cut
    window = Decimal(env.window_days)
    orders_scope = _scope_orders(env, items)
    gmv_scope = sum((ln.order_value for ln in listed), ZERO)
    aov = safe_div(gmv_scope, Decimal(orders_scope)) if orders_scope else None
    ppg = rate_of[tiers[-1].qty]
    profit = ProfitModel(
        effect_days=config.DAYS_PER_MONTH,
        base_gmv_per_day=_scope_gmv_per_day(env, items),
        base_orders_per_day=Decimal(orders_scope) / window,
        aov=aov,
        profit_per_gmv=ppg,
        extra_cost_per_day=extra_cost / window,
        dchi_per_day=extra_cost / window,
    )
    # five numbers: the listed lines of the qualifying orders carry their discount
    after_lines = [
        replace(ln, bundle_discount=discount_of[(ln.order_id, id(ln))])
        if (ln.order_id, id(ln)) in discount_of
        else ln
        for ln in lines
    ]
    spend = _scope_ad_spend(env, items)
    pairs_before = profit_lines(lines, env.costs, schedule=env.schedule(items[0]))
    snap = scope_snapshot(env, items, pairs_before, spend)
    snap_after = scope_snapshot(
        env, items, profit_lines(after_lines, env.costs, schedule=env.schedule(items[0])), spend
    )
    _, five_dict = _five(env, snap, snap_after, needs_volume=True)
    extra_month = extra_cost / window * Decimal(config.DAYS_PER_MONTH)
    per_order_profit = None if ppg is None or aov is None else ppg * aov
    be: int | None = None
    be_reason: str | None = None
    if per_order_profit is None or per_order_profit <= 0:
        be_reason = "contribution_not_positive"
    else:
        be = max(1, math.ceil(extra_month / per_order_profit))
    limit = inputs.get("limit_per_buyer")
    notes = [
        "Mỗi mức giảm áp cho số sản phẩm đủ N trong đơn, tính trên đơn giá trung bình của các "
        "sản phẩm trong combo.",
    ]
    if limit:
        notes.append(
            f"Giới hạn đặt hàng {int(limit)} combo mỗi người mua: chưa có dữ liệu theo người mua "
            "nên không tính vào kết quả."
        )
    missing = [i for i in items if i not in refs]
    if missing:
        notes.append(
            f"{len(missing)} sản phẩm chưa có đơn trong kỳ nên chưa tính giá sàn cho sản phẩm đó."
        )
    certain = {
        "kind": "combo",
        "bundle_tiers": True,
        "discount_type": dtype,
        "discount_type_label": TYPE_LABELS[dtype],
        "products": len(items),
        "tiers": tier_rows,
        "avg_unit_price": num(avg_price),
        "qualifying_orders": qualifying,
        "total_orders": orders_scope,
        "extra_cost_on_existing_orders": num(extra_cost),
        "aov_now": num(aov),
        "break_even_extra_orders": be,
        "break_even_reason": be_reason,
    }
    after: dict[str, Any] = {}
    if inputs.get("name"):
        after["Tên Combo Khuyến Mãi"] = str(inputs["name"])
    after["Loại Combo"] = TYPE_LABELS[dtype]
    after["Sản phẩm của Combo"] = ", ".join(env.name(i) for i in items)
    for n, t in enumerate(tiers, 1):
        after[f"Mức ưu đãi {n}"] = tier_text(dtype, t)
    if limit:
        after["Giới hạn đặt hàng"] = f"{int(limit)} combo mỗi người mua"
    if inputs.get("start") or inputs.get("end"):
        after["Thời gian chạy Combo"] = f"{inputs.get('start') or '…'} → {inputs.get('end') or '…'}"
    return Evaluation(
        certain=certain,
        five=five_dict,
        breaches=breaches,
        profit=profit,
        before={"tiers": []},
        after={**after, "tiers": [{"units": t.qty, "value": num(t.value)} for t in tiers]},
        target={"item_id": items[0], "item_ids": items},
        spend_check=_spend_check(env, profit.dchi_per_day),
        notes=notes,
        floor_unknown_skus=_unknown_floors(env, items),
    )


__all__ = [
    "MAX_NAME",
    "MAX_PRODUCTS",
    "MAX_TIERS",
    "TYPES",
    "TYPE_LABELS",
    "Tier",
    "best_tier",
    "effective_pct",
    "eval_bundle_tiers",
    "tier_text",
    "tiers_of",
]
