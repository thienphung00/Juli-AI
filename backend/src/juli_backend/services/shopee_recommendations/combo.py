"""p91 D-3: the combo calculator -- 2-6 DIFFERENT products (each SKU x qty) sold as one order
at a combo discount, with an optional stacked shop voucher and an optional gift item.

Pure arithmetic over ``services/shopee_profit`` (no database, no forecast):

- list value = today's deal price x qty summed; the discount is a % of it, an amount (d) or a
  fixed combo price (d), spread over the lines by value (remainder on the last line);
- the stacked voucher is the existing :class:`VoucherRule` (same ``discount_for`` as
  ``evaluate.eval_voucher``) applied to the value left after the combo discount, spread the
  same way;
- the platform fees go through :func:`profit_lines`: per-order fees (fixed amounts, transaction
  fee) are computed ONCE on the whole combo order and split over its lines by value (contract
  4/10). One fee schedule serves the whole order: the one of the combo's biggest line;
- contribution = sum of the lines' contribution - the gift's cost (giá vốn + đóng gói);
- cost per combo order = what the same basket would have earned at today's prices minus what
  the combo earns (discount, voucher, gift, net of the fees that fall with the price).

``eval_combo`` is the environment glue the evaluator registry calls for ``combo_multi``; the
predicted range comes from the existing lift model (sim kind ``combo_pack``) in ``build_card``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from juli_backend.services.shopee_analytics.fmt import num, pct
from juli_backend.services.shopee_profit.fees import FeeSchedule
from juli_backend.services.shopee_profit.money import ZERO, pct_points, safe_div, to_dong
from juli_backend.services.shopee_profit.order_profit import (
    OrderLine,
    OrderStatus,
    PromoKind,
    SkuCost,
    profit_lines,
)
from juli_backend.services.shopee_profit.whatif import VoucherRule
from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations.env import RecoEnv
from juli_backend.services.shopee_recommendations.evaluate import (
    D,
    _refuse,
    _scope_gmv_per_day,
    _scope_orders,
    _spend_check,
    _unknown_floors,
    voucher_rule_from,
)
from juli_backend.services.shopee_recommendations.model import Candidate, Evaluation, ProfitModel

KIND = "combo_multi"
DISCOUNT_TYPES = ("pct", "amount", "fixed_price")
MIN_LINES, MAX_LINES = 2, 6  # P92 B-4: 2-6 products (P91 allowed 2-3)
MAX_QTY = 20

REFUSALS: dict[str, str] = {
    "combo_needs_2_to_6_products": "Combo cần từ 2 đến 6 sản phẩm.",
    "combo_needs_distinct_products": "Các sản phẩm trong combo phải khác nhau.",
    "combo_qty_out_of_range": "Số lượng mỗi món từ 1 đến 20.",
    "combo_discount_type_invalid": "Kiểu giảm giá phải là %, số tiền hoặc giá combo cố định.",
    "combo_discount_value_invalid": "Mức giảm không hợp lệ.",
    "combo_price_not_below_value": "Giá combo cố định phải thấp hơn tổng giá bán hiện tại.",
    "combo_no_offer": "Combo chưa có ưu đãi nào (giảm giá, voucher hoặc quà).",
    "combo_voucher_invalid": "Voucher kèm theo không hợp lệ.",
    "item_no_data": "Sản phẩm chưa có đơn trong kỳ phân tích nên chưa tính được.",
    "sku_unknown": "SKU không thuộc sản phẩm đã chọn hoặc phân loại này chưa có đơn để tính.",
    "cost_or_fee_unknown": "Thiếu giá vốn, đóng gói hoặc công thức phí của một món trong combo.",
    "gift_cost_unknown": "Chưa biết giá vốn của quà tặng nên chưa tính được.",
}


def refusal_text(code: str) -> str:
    head = code.split(":", 1)[0]
    return REFUSALS.get(head, code)


@dataclass(frozen=True)
class ComboOffer:
    discount_type: str  # pct | amount | fixed_price
    discount_value: Decimal
    voucher: VoucherRule | None = None
    #: giá vốn + đóng gói of the gift, per combo order; None = no gift
    gift_cost: Decimal | None = None
    gift_label: str | None = None
    gift_packaging_known: bool = True


class ComboRefusal(ValueError):
    """The combo cannot be priced; ``code`` is a key of :data:`REFUSALS` (+ ``:detail``)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _spread(total: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """``total`` over ``weights`` in whole đồng, remainder on the last: shares sum exactly."""
    out: list[Decimal] = []
    left = total
    w_sum = sum(weights, ZERO)
    for i, w in enumerate(weights):
        if i == len(weights) - 1:
            share = left
        elif w_sum > 0:
            share = to_dong(total * w / w_sum)
        else:
            share = ZERO
        left -= share
        out.append(share)
    return out


def combo_discount(offer: ComboOffer, value: Decimal) -> Decimal:
    """The combo discount (đ) on a list value."""
    if offer.discount_type == "pct":
        if not (ZERO <= offer.discount_value <= 90):
            raise ComboRefusal("combo_discount_value_invalid")
        return to_dong(value * offer.discount_value / 100)
    if offer.discount_type == "amount":
        if offer.discount_value < 0:
            raise ComboRefusal("combo_discount_value_invalid")
        return min(to_dong(offer.discount_value), value)
    if offer.discount_type == "fixed_price":
        if offer.discount_value <= 0:
            raise ComboRefusal("combo_discount_value_invalid")
        if offer.discount_value >= value:
            raise ComboRefusal("combo_price_not_below_value")
        return value - to_dong(offer.discount_value)
    raise ComboRefusal("combo_discount_type_invalid")


def apply_offer(
    lines: Sequence[OrderLine], offer: ComboOffer
) -> tuple[list[OrderLine], Decimal, Decimal]:
    """The combo order's lines with the combo discount and the stacked voucher spread by value.

    Returns ``(lines, combo_discount, voucher_discount)``."""
    value = sum((ln.order_value for ln in lines), ZERO)
    disc = combo_discount(offer, value)
    shares = _spread(disc, [ln.order_value for ln in lines])
    after_combo = value - disc
    v_disc = offer.voucher.discount_for(after_combo) if offer.voucher is not None else ZERO
    v_shares = _spread(v_disc, [ln.order_value - s for ln, s in zip(lines, shares, strict=True)])
    out = [
        replace(ln, bundle_discount=s, shop_voucher_share=v)
        for ln, s, v in zip(lines, shares, v_shares, strict=True)
    ]
    return out, disc, v_disc


def price_combo(
    lines: Sequence[OrderLine],
    offer: ComboOffer,
    costs: Mapping[str, SkuCost],
    schedule: FeeSchedule | None,
    *,
    floors: Mapping[str, Decimal | None] | None = None,
) -> dict[str, Any]:
    """One combo order, priced. ``lines`` are the combo's lines at today's prices (one shared
    ``order_id``); ``floors`` maps SKU -> floor price per unit (None / missing = unknown).
    Raises :class:`ComboRefusal`."""
    if not MIN_LINES <= len(lines) <= MAX_LINES:
        raise ComboRefusal("combo_needs_2_to_6_products")
    if len({ln.product_id for ln in lines}) != len(lines):
        raise ComboRefusal("combo_needs_distinct_products")
    if any(not 1 <= ln.qty <= MAX_QTY for ln in lines):
        raise ComboRefusal("combo_qty_out_of_range")
    offered, disc, v_disc = apply_offer(lines, offer)
    if disc <= 0 and v_disc <= 0 and offer.gift_cost is None:
        raise ComboRefusal("combo_no_offer")
    pairs = profit_lines(offered, costs, schedule=schedule)
    base_pairs = profit_lines(list(lines), costs, schedule=schedule)
    missing = sorted({m for _, pb in pairs for m in pb.missing if m != "ads_allocation"})
    if missing or any(pb.contribution is None for _, pb in pairs):
        raise ComboRefusal("cost_or_fee_unknown:" + ",".join(missing))
    gift = offer.gift_cost or ZERO
    value = sum((ln.order_value for ln in lines), ZERO)
    list_value = sum((ln.list_value for ln in lines), ZERO)
    buyer_pays = sum((pb.buyer_paid for _, pb in pairs), ZERO)
    fees = sum((pb.fees_total or ZERO for _, pb in pairs), ZERO)
    cogs = sum((pb.cogs or ZERO for _, pb in pairs), ZERO)
    packaging = sum((pb.packaging or ZERO for _, pb in pairs), ZERO)
    contribution = sum((pb.contribution or ZERO for _, pb in pairs), ZERO) - gift
    base_contribution = sum((pb.contribution or ZERO for _, pb in base_pairs), ZERO)
    rows: list[dict[str, Any]] = []
    breaches: list[dict[str, Any]] = []
    unknown_floor: list[str] = []
    for ln, pb in pairs:
        unit_paid = pb.buyer_paid / ln.qty
        floor_px = (floors or {}).get(ln.sku)
        below = floor_px is not None and unit_paid < floor_px
        if floor_px is None:
            unknown_floor.append(ln.sku)
        if below:
            assert floor_px is not None
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
        rows.append(
            {
                "item_id": ln.product_id,
                "sku": ln.sku,
                "qty": ln.qty,
                "unit_price_now": num(ln.deal_price),
                "line_value": num(ln.order_value),
                "combo_discount": num(ln.bundle_discount),
                "voucher_share": num(ln.shop_voucher_share),
                "buyer_paid": num(pb.buyer_paid),
                "unit_paid": num(unit_paid),
                "fees_share": num(pb.fees_total),
                "cogs": num(pb.cogs),
                "packaging": num(pb.packaging),
                "contribution": num(pb.contribution),
                "floor": num(floor_px),
                "below_floor": bool(below),
            }
        )
    margin = pct_points(safe_div(contribution, buyer_pays)) if buyer_pays > 0 else None
    cost_per_order = base_contribution - contribution
    return {
        "lines": rows,
        "list_value": num(list_value),
        "value_now": num(value),
        "combo_discount": num(disc),
        "savings_pct": pct(pct_points(safe_div(disc, value))) if value > 0 else None,
        "voucher_discount": num(v_disc),
        "voucher_applies": v_disc > 0 if offer.voucher is not None else None,
        "buyer_pays": num(buyer_pays),
        "platform_fees": num(fees),
        "cogs": num(cogs),
        "packaging": num(packaging),
        "gift_cost": num(gift) if offer.gift_cost is not None else None,
        "contribution": num(contribution),
        "margin_pct": pct(margin),
        "contribution_without_offer": num(base_contribution),
        "cost_per_combo_order": num(cost_per_order),
        "breaches": breaches,
        "floor_unknown_skus": unknown_floor,
        # exact values for the caller's arithmetic (not serialised)
        "_buyer_pays": buyer_pays,
        "_contribution": contribution,
        "_cost_per_order": cost_per_order,
    }


def break_even_extra_orders(
    existing_baskets: int, cost_per_order: Decimal, contribution: Decimal
) -> tuple[int | None, str | None]:
    """Extra combo orders (over the history window) that pay back what the offer costs:
    ``ceil(combo cost in the window / contribution per combo order)`` (owner 2026-11-04).

    The combo cost in the window is the offer's cost per combo order times the baskets that take
    it. When no past basket held every product (``existing_baskets`` 0) the offer still gives
    its discount to the first combo order it sells, so one basket is counted: the answer is
    never 0 only because history has no such basket. ``None`` + a reason when a combo order does
    not earn anything."""
    if contribution <= 0:
        return None, "contribution_not_positive"
    baskets = max(existing_baskets, 1)
    give_away = max(cost_per_order, ZERO) * baskets
    return max(1, math.ceil(give_away / contribution)), None


# ------------------------------------------------------------------ environment glue


def _lines_of(inputs: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = inputs.get("lines")
    return list(raw) if isinstance(raw, Sequence) and not isinstance(raw, str) else []


def combo_lines(env: RecoEnv, spec_lines: Sequence[Mapping[str, Any]]) -> list[OrderLine]:
    """The combo order's lines at today's prices, from each product's newest order line."""
    out: list[OrderLine] = []
    for entry in spec_lines:
        item = str(entry.get("item_id", ""))
        skus = env.skus_of(item)
        if not skus:
            raise ComboRefusal(f"item_no_data:{item}")
        history = env.lines_for([item])
        sku = entry.get("sku")
        if sku is None:
            sku = max(
                skus, key=lambda s: sum((ln.order_value for ln in history if ln.sku == s), ZERO)
            )
        elif sku not in skus:
            raise ComboRefusal(f"sku_unknown:{sku}")
        ref = max(
            (ln for ln in history if ln.product_id == item and ln.sku == sku),
            key=lambda ln: ln.order_date,
        )
        out.append(
            replace(
                ref,
                qty=int(entry.get("qty", 1)),
                shop_voucher_share=ZERO,
                bundle_discount=ZERO,
                promo_kind=PromoKind.NONE,
                ad_attributed=False,
                affiliate=False,
                commission=None,
                actual_fees=None,
                buyer_shipping_fee=None,
                bank_promo=None,
                status=OrderStatus.DELIVERED,
            )
        )
    day = max((ln.order_date for ln in out), default=None)
    return [replace(ln, order_id="combo:order", order_date=day) for ln in out if day is not None]


def _gift_cost(env: RecoEnv, gift_item: str) -> tuple[Decimal, bool]:
    skus = env.skus_of(gift_item)
    cost = env.costs.get(skus[0]) if skus else None
    if cost is None or cost.cogs is None:
        raise ComboRefusal("gift_cost_unknown")
    return cost.cogs + (cost.packaging or ZERO), cost.packaging is not None


def offer_from(env: RecoEnv, inputs: Mapping[str, Any]) -> ComboOffer:
    dtype = str(inputs.get("discount_type", "pct"))
    if dtype not in DISCOUNT_TYPES:
        raise ComboRefusal("combo_discount_type_invalid")
    try:
        value = D(inputs.get("discount_value", 0))
    except ArithmeticError:
        raise ComboRefusal("combo_discount_value_invalid") from None
    voucher = None
    v_in = inputs.get("voucher")
    if v_in:
        try:
            voucher = voucher_rule_from(v_in)
        except (ValueError, ArithmeticError, TypeError):
            raise ComboRefusal("combo_voucher_invalid") from None
    gift_cost, packaging_known, label = None, True, None
    gift_item = inputs.get("gift_item")
    if gift_item:
        gift_cost, packaging_known = _gift_cost(env, str(gift_item))
        label = env.name(str(gift_item))
    return ComboOffer(dtype, value, voucher, gift_cost, label, packaging_known)


def _vn_money(v: Decimal | int | float | None) -> str:
    return "?" if v is None else f"{int(v):,}".replace(",", ".") + "đ"


def eval_combo(
    env: RecoEnv, cand: Candidate, inputs: Mapping[str, Any], predicted: Any = None
) -> Evaluation:
    """The certain layer of a ``combo_multi`` candidate (see the module docstring).

    ``inputs``: ``lines`` [{item_id, sku?, qty}], ``discount_type``, ``discount_value``,
    optional ``voucher`` {value | pct, min_spend, max_value} and ``gift_item``."""
    try:
        lines = combo_lines(env, _lines_of(inputs))
        offer = offer_from(env, inputs)
        items = [ln.product_id for ln in lines]
        main = max(lines, key=lambda ln: ln.order_value).product_id
        floors = {ln.sku: env.floor_price(ln.product_id, ln.sku) for ln in lines}
        priced = price_combo(lines, offer, env.costs, env.schedule(main), floors=floors)
    except ComboRefusal as exc:
        return _refuse(exc.code)
    buyer_pays: Decimal = priced.pop("_buyer_pays")
    contribution: Decimal = priced.pop("_contribution")
    cost_per_order: Decimal = priced.pop("_cost_per_order")
    window = Decimal(env.window_days)
    order_sets: dict[str, set[str]] = {}
    for ln, _ in env.view.pairs:
        order_sets.setdefault(ln.order_id, set()).add(ln.product_id)
    existing = sum(1 for s in order_sets.values() if set(items) <= s)
    be, be_reason = break_even_extra_orders(existing, cost_per_order, contribution)
    cost_existing = max(cost_per_order, ZERO) * existing
    shop_aov = (
        safe_div(env.shop_gmv_30d, Decimal(env.shop_orders_30d)) if env.shop_orders_30d else None
    )
    orders_scope = _scope_orders(env, items)
    gmv_scope_day = _scope_gmv_per_day(env, items)
    aov_scope = safe_div(gmv_scope_day * window, Decimal(orders_scope)) if orders_scope else None
    profit = ProfitModel(
        effect_days=config.DAYS_PER_MONTH,
        base_gmv_per_day=gmv_scope_day,
        base_orders_per_day=Decimal(orders_scope) / window,
        aov=aov_scope,
        profit_per_gmv=safe_div(contribution, buyer_pays) if buyer_pays > 0 else None,
        extra_cost_per_day=cost_existing / window,
        dchi_per_day=cost_existing / window,
    )
    notes = ["Phí sàn tính một lần trên cả đơn combo rồi chia theo giá trị từng món."]
    if offer.gift_cost is not None and not offer.gift_packaging_known:
        notes.append("Chưa có chi phí đóng gói của quà tặng: tính 0đ.")
    if offer.voucher is not None and not priced["voucher_applies"]:
        notes.append("Đơn combo chưa đạt mức tối thiểu của voucher nên voucher không được trừ.")
    if existing == 0:
        notes.append("Chưa có đơn nào trong kỳ mua đủ các món này cùng nhau.")
    certain = {
        "kind": "combo",
        "combo_multi": True,
        **priced,
        "discount_type": offer.discount_type,
        "discount_value": num(offer.discount_value),
        "aov_combo": num(buyer_pays),
        "aov_shop_now": num(shop_aov),
        "aov_delta_vs_shop": num(buyer_pays - shop_aov) if shop_aov is not None else None,
        "existing_combo_baskets": existing,
        "cost_on_existing_baskets": num(cost_existing),
        "break_even_extra_orders": be,
        "break_even_reason": be_reason,
        "extra_orders_label": "Đơn combo thêm cần để hoà vốn",
    }
    labels = " + ".join(f"{env.name(ln.product_id)} x{ln.qty}" for ln in lines)
    dtype_label = {"pct": "%", "amount": "đ", "fixed_price": "giá cố định"}[offer.discount_type]
    after: dict[str, Any] = {
        "Sản phẩm trong combo": labels,
        "Kiểu giảm": dtype_label,
        "Mức giảm": _vn_money(offer.discount_value)
        if offer.discount_type != "pct"
        else f"{num(offer.discount_value)}%",
        "Khách trả mỗi combo": _vn_money(buyer_pays),
    }
    if offer.voucher is not None:
        after["Voucher kèm"] = "có"
    if offer.gift_label:
        after["Quà tặng"] = offer.gift_label
    return Evaluation(
        certain=certain,
        five=None,
        breaches=priced["breaches"],
        profit=profit,
        before={},
        after=after,
        target={"item_id": items[0], "item_ids": items},
        spend_check=_spend_check(env, profit.dchi_per_day),
        notes=notes,
        floor_unknown_skus=_unknown_floors(env, items) or list(priced["floor_unknown_skus"]),
    )


__all__ = [
    "ComboOffer",
    "ComboRefusal",
    "KIND",
    "apply_offer",
    "break_even_extra_orders",
    "combo_discount",
    "eval_combo",
    "price_combo",
    "refusal_text",
]
