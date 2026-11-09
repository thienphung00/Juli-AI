"""P97 D85.16: a new listing that sells existing products together ("Listing combo mới").

It is a listing, not a promotion: its own title, images, price, stock and SKU. Its estimate starts
from nothing -- no sales history and no search ranking -- so Juli does **not** add orders from the
listing's own appeal. What it can say is where the first sales come from: the singles it contains.
The assumption, stated on the card and in the UI:

- the only demand modelled is the orders of the last 30 days that already hold every member
  product (the baskets that could be bought as the combo instead); no new orders;
- of those baskets none / half / all switch to the combo across the range (a symmetric ignorance
  range, not a measurement; the P50 is half);
- a switched basket pays the combo price instead of the members' prices: the GMV and the profit
  change by the difference, priced with the shop's fee formula and the members' giá vốn.

A combo priced at or above the sum of its members gives a buyer no reason to switch: it is priced
at 0 change and says so. The card carries ``image_refs`` (file names or references, never bytes);
filling the "Thêm sản phẩm" form in is for later (recon pending).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.fmt import num, pct
from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div
from juli_backend.services.shopee_profit.order_profit import OrderLine, profit_lines
from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations.combo import ComboOffer, apply_offer, combo_lines
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.evaluate import (
    D,
    _refuse,
    _spend_check,
    _unknown_floors,
)
from juli_backend.services.shopee_recommendations.model import Candidate, Evaluation, ProfitModel

KIND = "listing_combo"
MIN_MEMBERS, MAX_MEMBERS = 2, 20
MIN_PRICE = Decimal(1000)
#: share of the existing baskets that switch across the range (an assumption, not a measurement)
SWITCH_SHARE = (0.0, 0.5, 1.0)

ASSUMPTION = (
    "Giả định: listing mới chưa có lịch sử bán và chưa có thứ hạng tìm kiếm nên Juli không cộng "
    "đơn mới. Chỉ tính các đơn 30 ngày qua đã mua đủ các sản phẩm thành phần cùng nhau "
    "({baskets} đơn). Khoảng dự kiến chạy từ không đơn nào đến tất cả các đơn đó chuyển sang mua "
    "combo với giá combo (cannibalize); giữa khoảng (P50) là một nửa."
)
NO_BASKETS = (
    "Chưa có đơn nào trong 30 ngày qua mua đủ các sản phẩm này cùng nhau, nên chưa có đơn nào để "
    "chuyển sang combo. Listing mới phải tự tạo nhu cầu; Juli không ước tính điều đó."
)


def eval_listing_combo(
    env: RecoEnv, cand: Candidate, inputs: Mapping[str, Any], predicted: Any = None
) -> Evaluation:
    del predicted
    members = list(dict.fromkeys(cand.items))
    if not MIN_MEMBERS <= len(members) <= MAX_MEMBERS:
        return _refuse("listing_combo_members")
    try:
        price = D(inputs["price"])
    except (KeyError, ArithmeticError):
        return _refuse("listing_combo_price")
    if price < MIN_PRICE:
        return _refuse("combo_price_too_low")
    # the baskets of the window that hold every member: ``k`` combos each = the smallest quantity
    by_order: dict[str, dict[str, list[OrderLine]]] = defaultdict(lambda: defaultdict(list))
    for ln, _ in env.view.pairs:
        if ln.product_id in members:
            by_order[ln.order_id][ln.product_id].append(ln)
    baskets: list[int] = []
    for held in by_order.values():
        if all(m in held for m in members):
            baskets.append(min(sum(x.qty for x in held[m]) for m in members))
    combos_in_window = sum(baskets)
    if not any(env.skus_of(m) for m in members):
        return _refuse("item_no_data")
    try:
        lines = combo_lines(env, [{"item_id": m, "qty": 1} for m in members])
    except Exception as exc:  # ComboRefusal: a member with no order line at all
        code = getattr(exc, "code", None)
        return _refuse(code or "item_no_data")
    value_now = sum((ln.order_value for ln in lines), ZERO)
    schedule = env.schedule(max(lines, key=lambda ln: ln.order_value).product_id)
    base_pairs = profit_lines(list(lines), env.costs, schedule=schedule)
    base_contribution = sum((pb.contribution or ZERO for _, pb in base_pairs), ZERO)
    unknown_cost = any(pb.contribution is None for _, pb in base_pairs)
    cheaper = price < value_now
    breaches: list[dict[str, Any]] = []
    if cheaper:
        offered, disc, _ = apply_offer(lines, ComboOffer("fixed_price", price))
        pairs = profit_lines(offered, env.costs, schedule=schedule)
        unknown_cost = unknown_cost or any(pb.contribution is None for _, pb in pairs)
        for ln, pb in pairs:
            floor_px = env.floor_price(ln.product_id, ln.sku)
            unit_paid = pb.buyer_paid / ln.qty
            if floor_px is not None and unit_paid < floor_px:
                breaches.append(
                    {
                        "sku": ln.sku,
                        "item_id": ln.product_id,
                        "kind": "operating",
                        "floor": num(floor_px),
                        "min_unit_price": num(unit_paid),
                        "lines": 1,
                    }
                )
        contribution = sum((pb.contribution or ZERO for _, pb in pairs), ZERO)
        buyer_pays = sum((pb.buyer_paid for _, pb in pairs), ZERO)
    else:
        disc = ZERO
        contribution, buyer_pays = base_contribution, price
    window = Decimal(env.window_days)
    d_gmv = price - value_now if cheaper else ZERO
    d_profit = contribution - base_contribution
    if unknown_cost:
        ppg = None
    elif d_gmv != 0:
        ppg = safe_div(d_profit, d_gmv)
    else:
        ppg = ZERO
    base_gmv_day = value_now * Decimal(combos_in_window) / window
    ratio = (d_gmv / value_now * 100) if value_now > 0 and cheaper else ZERO
    profit = ProfitModel(
        effect_days=config.DAYS_PER_MONTH,
        base_gmv_per_day=base_gmv_day,
        base_orders_per_day=Decimal(len(baskets)) / window,
        aov=None,
        profit_per_gmv=ppg,
    )
    notes = [ASSUMPTION.format(baskets=len(baskets)) if baskets else NO_BASKETS]
    if not cheaper:
        notes.append(
            "Giá combo không thấp hơn tổng giá lẻ hiện tại của các sản phẩm thành phần: khách "
            "không có lý do chuyển sang combo nên Juli tính 0 thay đổi."
        )
    if unknown_cost:
        notes.append("Thiếu giá vốn hoặc phí của một sản phẩm thành phần: lợi nhuận chưa tính.")
    stock = inputs.get("stock")
    if stock is not None and baskets and int(stock) < combos_in_window // 2:
        notes.append(
            f"Tồn kho {int(stock)} thấp hơn mức chuyển đổi P50 dự kiến "
            f"({combos_in_window // 2} combo trong 30 ngày)."
        )
    names = [
        {
            "item_id": m,
            "name": env.name(m),
            "orders_30d": len({ln.order_id for ln, _ in env.view.pairs if ln.product_id == m}),
            "price": num(next((ln.deal_price for ln in lines if ln.product_id == m), None)),
        }
        for m in members
    ]
    certain = {
        "kind": "listing_combo",
        "members": names,
        "combo_price": num(price),
        "value_now": num(value_now),
        "combo_discount": num(disc),
        "savings_pct": pct(pct_points(safe_div(disc, value_now))) if value_now > 0 else None,
        "contribution": num(contribution),
        "contribution_without_offer": num(base_contribution),
        "margin_pct": pct(pct_points(safe_div(contribution, buyer_pays)))
        if buyer_pays > 0 and not unknown_cost
        else None,
        "existing_baskets": len(baskets),
        "combos_in_window": combos_in_window,
        "switch_share": {"p10": SWITCH_SHARE[0], "p50": SWITCH_SHARE[1], "p90": SWITCH_SHARE[2]},
        "assumption": notes[0],
        "magnitude_pct": float(ratio),
        "aov_now": num(
            safe_div(
                sum((ln.order_value for ln, _ in env.view.pairs), ZERO),
                Decimal(max(env.shop_orders_30d, 1)),
            )
        ),
    }
    after: dict[str, Any] = {
        "Tên listing": str(inputs.get("title") or ""),
        "Giá bán": f"{int(price):,}".replace(",", ".") + "đ",
        "Tồn kho": str(inputs.get("stock", "")),
        "Sản phẩm thành phần": ", ".join(env.name(m) for m in members),
    }
    if inputs.get("sku"):
        after["SKU"] = str(inputs["sku"])
    if inputs.get("image_refs"):
        after["Ảnh"] = f"{len(inputs['image_refs'])} ảnh"
    return Evaluation(
        certain=certain,
        five=None,
        breaches=breaches,
        profit=profit,
        before={},
        after=after,
        target={"item_id": members[0], "item_ids": members},
        spend_check=_spend_check(env, ZERO),
        notes=notes,
        floor_unknown_skus=_unknown_floors(env, members),
    )


__all__ = ["KIND", "MAX_MEMBERS", "MIN_MEMBERS", "eval_listing_combo"]
