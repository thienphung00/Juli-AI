"""Draft plans that build on each other (P92 B-10): the steps of one product, in order.

A product's cards in a plan are a sequence -- **giá** (price, flash sale, Shopee programme) ->
**giảm giá** (product discount) -> **voucher** -> **combo / mua kèm / quà tặng** -> **quảng cáo**.
Step *k* is evaluated ON TOP of steps 1..k-1: the first *k* cards are re-priced together on the
same history orders through the joint evaluation of the plan (``plan_aggregate.joint`` ->
``mega.evaluate_mega``: the new price first, the voucher on the new basket, platform fees
recomputed once per order on the new buyer-paid amount, the floor check on the stacked price). So
the fees are the same size-dependent formula as the per-strategy margin of B-9, not a sum of the
cards' own figures.

Per step the payload gives the margin and the profit change after it:

- ``margin_pct_after`` -- the margin of the product's orders after steps 1..k at the CERTAIN
  layer (same orders, no volume change). From the joint evaluation's five numbers; for a prefix
  made only of cards the stacking does not model (add-on, gift, multi-product combo) it is
  derived from the baseline profit and buyer-paid plus the cards' certain profit and GMV change;
  ``None`` ("chưa tính") when there is no baseline.
- ``dprofit_total_p50`` / ``dprofit_total_certain`` -- Δ lợi nhuận / tháng after steps 1..k
  (predicted P50 on top of the certain layer / the certain layer alone); ``dprofit_step_p50`` is
  what step k adds over step k-1.

The order is the plan order of the product's cards. A card joins at its canonical slot
(``slot_for``); moving a card (``POST .../plan/cards/{id}/move``) makes the order custom
(``custom_order``). Reordering or removing a card re-evaluates every prefix. The final step equals
the product's joint total, so the steps always add up to the plan's number for the product.
Pure apart from the callable that evaluates a prefix.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from juli_backend.services.shopee_recommendations.kinds import KINDS

STEP_ORDER: tuple[str, ...] = ("price", "giam_gia", "voucher", "combo", "ads")
STEP_LABELS: dict[str, str] = {
    "price": "Giá bán",
    "giam_gia": "Giảm giá",
    "voucher": "Voucher",
    "combo": "Combo / mua kèm / quà tặng",
    "ads": "Quảng cáo",
    "other": "Khác",
}
_PRICE_KINDS = frozenset({"price", "flash_sale", "program_registration"})
MARGIN_BASIS = (
    "Biên của các đơn của sản phẩm sau các bước tới đây, trên cùng các đơn cũ (chưa tính thay "
    "đổi lượng đơn dự kiến); phí sàn tính lại theo giá và giỏ hàng mới."
)


def step_of(change_kind: str) -> str:
    if change_kind in _PRICE_KINDS:
        return "price"
    if change_kind == "product_discount":
        return "giam_gia"
    spec = KINDS.get(change_kind)
    family = spec.family if spec else ""
    return {"voucher": "voucher", "combo": "combo", "ads": "ads"}.get(family, "other")


def rank(change_kind: str) -> int:
    step = step_of(change_kind)
    return STEP_ORDER.index(step) if step in STEP_ORDER else len(STEP_ORDER)


def canonical(kinds: Sequence[str]) -> list[int]:
    """Indexes of ``kinds`` in canonical step order (stable)."""
    return sorted(range(len(kinds)), key=lambda i: (rank(kinds[i]), i))


def slot_for(existing_kinds: Sequence[str], new_kind: str) -> int:
    """Where a new card goes among a product's cards (already in plan order): after the last
    card whose step is not later than its own. Index in ``existing_kinds`` terms (0..len)."""
    wanted = rank(new_kind)
    slot = 0
    for i, kind in enumerate(existing_kinds):
        if rank(kind) <= wanted:
            slot = i + 1
    return slot


def _margin_pct(five: dict[str, Any] | None, key: str) -> float | None:
    if not five:
        return None
    value = five.get("margin", {}).get(key)
    return None if value is None else float(value)


def _derived_margin(
    base: tuple[float, float] | None, certain_dprofit: float, certain_dgmv: float
) -> float | None:
    if base is None:
        return None
    profit, paid = base
    after_paid = paid + certain_dgmv
    return None if after_paid <= 0 else round((profit + certain_dprofit) / after_paid * 100, 2)


def build_steps(
    cards: Sequence[dict[str, Any]],
    joint_of: Callable[[Sequence[str]], Any],
) -> dict[str, Any]:
    """The ``steps`` block of one product. ``cards``: per card in plan order
    ``{card_id, code, title, change_kind, version_label}``; ``joint_of(ids)`` returns the joint
    evaluation (``plan_aggregate.Joint``) of those cards."""
    kinds = [c["change_kind"] for c in cards]
    ids = [c["card_id"] for c in cards]
    custom = canonical(kinds) != list(range(len(kinds)))
    joints = [joint_of(ids[: k + 1]) for k in range(len(ids))]
    # baseline margin of the product's orders: profit and buyer-paid before any step
    base: tuple[float, float] | None = None
    base_pct: float | None = None
    for j in joints:
        five = j.five
        pct_before = _margin_pct(five, "pct_before")
        profit_before = None if not five else five.get("margin", {}).get("profit_before")
        if pct_before not in (None, 0) and profit_before is not None:
            base = (float(profit_before), float(profit_before) / pct_before * 100)
            base_pct = pct_before
            break
    items: list[dict[str, Any]] = []
    prev_p50: float | None = 0.0
    for k, (card, j) in enumerate(zip(cards, joints, strict=True)):
        total_p50 = j.total["p50"]["dprofit"]
        step_p50 = None if total_p50 is None or prev_p50 is None else round(total_p50 - prev_p50, 2)
        margin_after = _margin_pct(j.five, "pct_after")
        if margin_after is None:
            margin_after = _derived_margin(base, j.certain["dprofit"], j.certain["dgmv"])
        items.append(
            {
                "index": k + 1,
                "step": step_of(card["change_kind"]),
                "step_label": STEP_LABELS[step_of(card["change_kind"])],
                "card_id": card["card_id"],
                "code": card.get("code"),
                "title": card.get("title"),
                "change_kind": card["change_kind"],
                "version_label": card.get("version_label"),
                "margin_pct_before": base_pct if k == 0 else items[k - 1]["margin_pct_after"],
                "margin_pct_after": margin_after,
                "dprofit_step_p50": step_p50,
                "dprofit_total_p50": None if total_p50 is None else round(total_p50, 2),
                "dprofit_total_certain": round(j.certain["dprofit"], 2),
                "dgmv_total_p50": _round(j.total["p50"]["dgmv"]),
                "cost_month_total": round(j.certain["dchi"], 2),
                "floor_ok": j.floor_ok,
            }
        )
        prev_p50 = total_p50
    last = items[-1]
    return {
        "order": list(STEP_ORDER),
        "custom_order": custom,
        "margin_basis": MARGIN_BASIS,
        "items": items,
        "total": {
            "margin_pct_before": base_pct,
            "margin_pct_after": last["margin_pct_after"],
            "dprofit_p50": last["dprofit_total_p50"],
            "dprofit_certain": last["dprofit_total_certain"],
            "dgmv_p50": last["dgmv_total_p50"],
            "floor_ok": last["floor_ok"],
        },
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


__all__ = [
    "STEP_LABELS",
    "STEP_ORDER",
    "build_steps",
    "canonical",
    "rank",
    "slot_for",
    "step_of",
]
