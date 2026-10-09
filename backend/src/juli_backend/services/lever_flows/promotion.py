"""Seller Center promotions: rules check, proposal, instructions (fast track P10-B, §5).

Juli never writes a promotion to TikTok (D13). For the four Seller Center levers
it proposes one promotion that respects the seller's own rules, tells the seller
exactly how to create it, and later verifies it read-only.

**Rules (``shop_rules``).** ``product_cost`` (this product) is required: a
promotion card is only produced for a product with a cost (D18), so a run
without one is a bug and fails loudly (``PromotionRulesMissing``).
``min_margin_pct`` is the margin floor (unset: 0 %, never below cost);
``max_discount_pct`` is the per-SKU cap (the smallest cap over the product's
SKUs applies; unset: the margin floor alone limits the discount).

**Proposal.** ``P`` = the product's lowest SKU price, ``C`` its cost, ``m`` the
margin floor. The deepest discount that keeps the floor is
``h = 1 − C / (P × (1 − m))``; the proposal uses ``⌊min(h, cap, 50 %)⌋`` whole
percent, and is refused (nothing to apply) below 1 %:

- product discount: sale price ``P × (1 − d)`` rounded down to 1.000 ₫, 30 days;
- flash sale: the same price, one slot within the next 7 days;
- shipping discount: ``P × d`` (rounded down to 1.000 ₫, at most 30.000 ₫) off
  shipping for orders from ``P``, 14 days;
- buy more save more: one tier, "mua từ 2 giảm d %", 30 days.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services import shop_rules

PRODUCT_DISCOUNT = "product_discount"
FLASH_SALE = "flash_sale"
SHIPPING_DISCOUNT = "shipping_discount"
BUY_MORE_SAVE_MORE = "buy_more_save_more"

TYPE_LABELS_VI: Mapping[str, str] = {
    PRODUCT_DISCOUNT: "Giảm giá sản phẩm",
    FLASH_SALE: "Flash sale",
    SHIPPING_DISCOUNT: "Giảm phí vận chuyển",
    BUY_MORE_SAVE_MORE: "Mua nhiều giảm nhiều",
}

DURATION_DAYS: Mapping[str, int] = {
    PRODUCT_DISCOUNT: 30,
    FLASH_SALE: 7,
    SHIPPING_DISCOUNT: 14,
    BUY_MORE_SAVE_MORE: 30,
}

#: Seller Center's marketing tools (VN). Deep links per tool are not published
#: by TikTok; every type opens the promotion management page (DEBT P10-B).
SELLER_CENTER_PROMOTIONS_URL = "https://seller-vn.tiktok.com/promotion/marketing-tools/management"

MAX_DISCOUNT = Decimal("0.50")
MAX_SHIPPING_DISCOUNT_VND = Decimal(30000)
_THOUSAND = Decimal(1000)


class PromotionRulesMissing(RuntimeError):  # noqa: N818 - an invariant breach, named for it
    """A promotion run for a product with no cost: the card should not exist."""


@dataclass(frozen=True)
class PromotionRules:
    cost: Decimal
    min_margin: Decimal  # fraction, 0 when unset
    min_margin_set: bool
    #: TikTok SKU id -> cap (fraction).
    caps_by_sku: Mapping[str, Decimal] = field(default_factory=dict)


async def load_rules(session: AsyncSession, shop_id: Any, tiktok_product_id: str) -> PromotionRules:
    """The seller's rules for this product, or ``PromotionRulesMissing`` without a cost."""
    rules = await shop_rules.get_rules(session, shop_id)
    cost_rule = rules.product_cost.get(tiktok_product_id)
    if cost_rule is None:
        raise PromotionRulesMissing(
            f"promotion run for product {tiktok_product_id} but the shop has no product_cost "
            "for it; promotion cards require a cost (D18)"
        )
    margin = rules.min_margin_pct
    return PromotionRules(
        cost=Decimal(str(cost_rule.value)),
        min_margin=Decimal(str(margin.value)) / 100 if margin is not None else Decimal(0),
        min_margin_set=margin is not None,
        caps_by_sku={
            sku: Decimal(str(value.value)) / 100 for sku, value in rules.max_discount_pct.items()
        },
    )


@dataclass(frozen=True)
class SkuPrice:
    sku_id: str
    seller_sku: str | None
    price: Decimal


def sku_prices(product_detail: Mapping[str, Any] | None) -> list[SkuPrice]:
    """Each SKU's sale price from a raw ``products.get_details`` payload."""
    prices: list[SkuPrice] = []
    for sku in (product_detail or {}).get("skus") or []:
        if not isinstance(sku, Mapping):
            continue
        price: Mapping[str, Any] = sku["price"] if isinstance(sku.get("price"), Mapping) else {}
        raw = price.get("sale_price") or price.get("tax_exclusive_price") or price.get("amount")
        try:
            amount = Decimal(str(raw))
        except Exception:
            continue
        if amount > 0:
            prices.append(
                SkuPrice(
                    sku_id=str(sku.get("id") or ""),
                    seller_sku=str(sku["seller_sku"]) if sku.get("seller_sku") else None,
                    price=amount,
                )
            )
    return prices


def _floor_thousand(value: Decimal) -> Decimal:
    return (value / _THOUSAND).to_integral_value(rounding=ROUND_FLOOR) * _THOUSAND


def _pct(fraction: Decimal) -> int:
    return int((fraction * 100).to_integral_value(rounding=ROUND_FLOOR))


@dataclass(frozen=True)
class PromotionProposal:
    """What Juli asks the seller to apply, already checked against the rules."""

    lever: str
    ok: bool
    price: Decimal | None = None
    cost: Decimal | None = None
    discount_pct: int = 0
    new_price: Decimal | None = None
    shipping_discount: Decimal | None = None
    min_order: Decimal | None = None
    margin_after_pct: int | None = None
    min_margin_pct: int | None = None
    cap_pct: int | None = None
    start: date | None = None
    end: date | None = None
    seller_sku: str | None = None
    refusal_vi: str | None = None

    def to_json(self) -> dict[str, Any]:
        def num(value: Decimal | None) -> float | None:
            return None if value is None else float(value)

        return {
            "lever": self.lever,
            "ok": self.ok,
            "price": num(self.price),
            "cost": num(self.cost),
            "discount_pct": self.discount_pct,
            "new_price": num(self.new_price),
            "shipping_discount": num(self.shipping_discount),
            "min_order": num(self.min_order),
            "margin_after_pct": self.margin_after_pct,
            "min_margin_pct": self.min_margin_pct,
            "cap_pct": self.cap_pct,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "seller_sku": self.seller_sku,
            "refusal_vi": self.refusal_vi,
        }

    @classmethod
    def from_json(cls, blob: Mapping[str, Any] | None) -> PromotionProposal | None:
        if not isinstance(blob, Mapping) or not blob.get("lever"):
            return None

        def dec(key: str) -> Decimal | None:
            value = blob.get(key)
            return None if value is None else Decimal(str(value))

        def day(key: str) -> date | None:
            value = blob.get(key)
            return date.fromisoformat(value) if isinstance(value, str) else None

        return cls(
            lever=str(blob["lever"]),
            ok=bool(blob.get("ok")),
            price=dec("price"),
            cost=dec("cost"),
            discount_pct=int(blob.get("discount_pct") or 0),
            new_price=dec("new_price"),
            shipping_discount=dec("shipping_discount"),
            min_order=dec("min_order"),
            margin_after_pct=blob.get("margin_after_pct"),
            min_margin_pct=blob.get("min_margin_pct"),
            cap_pct=blob.get("cap_pct"),
            start=day("start"),
            end=day("end"),
            seller_sku=blob.get("seller_sku"),
            refusal_vi=blob.get("refusal_vi"),
        )


def propose(
    lever: str,
    rules: PromotionRules,
    product_detail: Mapping[str, Any] | None,
    *,
    today: date,
) -> PromotionProposal:
    """The promotion to ask for, or a refusal (``ok=False``) in Vietnamese."""
    prices = sku_prices(product_detail)
    min_margin_pct = _pct(rules.min_margin) if rules.min_margin_set else None
    if not prices:
        return PromotionProposal(
            lever=lever,
            ok=False,
            cost=rules.cost,
            min_margin_pct=min_margin_pct,
            refusal_vi="Juli không đọc được giá sản phẩm nên chưa đề xuất khuyến mãi.",
        )
    cheapest = min(prices, key=lambda p: p.price)
    price = cheapest.price
    caps = [rules.caps_by_sku[p.sku_id] for p in prices if p.sku_id in rules.caps_by_sku]
    cap = min(caps) if caps else None
    floor_price = rules.cost / (1 - rules.min_margin) if rules.min_margin < 1 else None
    headroom = 1 - floor_price / price if floor_price is not None else Decimal(0)
    limit = min([headroom, MAX_DISCOUNT, *([cap] if cap is not None else [])])
    discount_pct = max(0, _pct(limit))
    base = PromotionProposal(
        lever=lever,
        ok=False,
        price=price,
        cost=rules.cost,
        min_margin_pct=min_margin_pct,
        cap_pct=_pct(cap) if cap is not None else None,
        seller_sku=cheapest.seller_sku,
    )
    if discount_pct < 1:
        reason = (
            "trần giảm giá bạn đặt là 0 %"
            if cap is not None and cap <= 0
            else "biên lợi nhuận sau giảm sẽ thấp hơn mức tối thiểu bạn đặt"
        )
        return _replace(base, refusal_vi=f"Không đề xuất khuyến mãi: {reason}.")

    fraction = Decimal(discount_pct) / 100
    start = today
    end = today + timedelta(days=DURATION_DAYS[lever] - 1)
    new_price: Decimal | None = None
    shipping: Decimal | None = None
    min_order: Decimal | None = None
    if lever in (PRODUCT_DISCOUNT, FLASH_SALE, BUY_MORE_SAVE_MORE):
        new_price = _floor_thousand(price * (1 - fraction))
        if lever == BUY_MORE_SAVE_MORE:
            new_price = price * (1 - fraction)
        revenue = new_price
    else:  # SHIPPING_DISCOUNT: the seller pays part of the shipping fee
        shipping = min(_floor_thousand(price * fraction), MAX_SHIPPING_DISCOUNT_VND)
        if shipping < _THOUSAND:
            return _replace(
                base, refusal_vi="Không đề xuất khuyến mãi: mức giảm phí vận chuyển dưới 1.000 ₫."
            )
        min_order = price
        revenue = price - shipping
    margin_after = (revenue - rules.cost) / revenue if revenue > 0 else Decimal(-1)
    if margin_after < rules.min_margin:
        return _replace(
            base,
            refusal_vi=(
                "Không đề xuất khuyến mãi: biên lợi nhuận sau giảm sẽ thấp hơn mức tối thiểu "
                "bạn đặt."
            ),
        )
    return _replace(
        base,
        ok=True,
        discount_pct=discount_pct,
        new_price=new_price if lever != BUY_MORE_SAVE_MORE else None,
        shipping_discount=shipping,
        min_order=min_order,
        margin_after_pct=_pct(margin_after),
        start=start,
        end=end,
    )


def _replace(proposal: PromotionProposal, **changes: Any) -> PromotionProposal:
    from dataclasses import replace

    return replace(proposal, **changes)


# --- seller-facing copy (VI) ---------------------------------------------------------


def money_vi(value: Decimal | None) -> str:
    """``259000`` -> ``259.000 ₫``."""
    if value is None:
        return "—"
    return f"{int(value):,}".replace(",", ".") + " ₫"


def short_money_vi(value: Decimal | None) -> str:
    """``259000`` -> ``259k``; ``2100000`` -> ``2,1 tr``."""
    if value is None:
        return "—"
    amount = float(value)
    if abs(amount) >= 1_000_000:
        return f"{amount / 1_000_000:.1f}".replace(".", ",") + " tr"
    if abs(amount) >= 1000:
        return f"{math.floor(amount / 1000)}k"
    return f"{int(amount)}"


def date_vi(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "—"


def rules_sentence(proposal: PromotionProposal) -> str:
    """Step "Kiểm tra quy tắc bạn đặt": what was checked, in numbers."""
    if not proposal.ok:
        return f"Kiểm tra quy tắc bạn đặt: {proposal.refusal_vi}"
    parts = []
    if proposal.margin_after_pct is not None:
        floor = (
            f" ≥ {proposal.min_margin_pct} %"
            if proposal.min_margin_pct is not None
            else " (chưa đặt mức tối thiểu)"
        )
        parts.append(f"biên lợi nhuận sau giảm {proposal.margin_after_pct} %{floor}")
    cap = (
        f"giảm {proposal.discount_pct} % ≤ trần {proposal.cap_pct} %"
        if proposal.cap_pct is not None
        else f"giảm {proposal.discount_pct} % (chưa đặt trần giảm giá)"
    )
    parts.append(cap)
    return "Kiểm tra quy tắc bạn đặt: " + " · ".join(parts)


@dataclass(frozen=True)
class Instructions:
    steps: list[str]
    deep_link: str
    summary: str


def instructions(proposal: PromotionProposal, *, product_name: str) -> Instructions:
    """The 4 Seller Center steps for this promotion type (VI)."""
    product = (
        f"{proposal.seller_sku} · {product_name}" if proposal.seller_sku else product_name
    ).strip(" ·")
    span = f"từ {date_vi(proposal.start)} đến {date_vi(proposal.end)}"
    lever = proposal.lever
    label = TYPE_LABELS_VI[lever]
    days = DURATION_DAYS[lever]
    margin = (
        f"biên lợi nhuận còn {proposal.margin_after_pct} %"
        + (
            f" (≥ {proposal.min_margin_pct} % bạn đặt)"
            if proposal.min_margin_pct is not None
            else ""
        )
        if proposal.margin_after_pct is not None
        else ""
    )
    cap = f"trong trần giảm {proposal.cap_pct} % bạn đặt" if proposal.cap_pct is not None else ""
    if lever == PRODUCT_DISCOUNT:
        steps = [
            "Vào Marketing › Khuyến mãi › Giảm giá sản phẩm › Tạo khuyến mãi",
            f"Chọn sản phẩm {product}",
            f"Đặt giá giảm {money_vi(proposal.new_price)}, {span}",
            "Bấm Lưu và kiểm tra khuyến mãi ở trạng thái Đang diễn ra",
        ]
        head = (
            f"Giá {short_money_vi(proposal.price)} → {short_money_vi(proposal.new_price)} "
            f"(−{proposal.discount_pct} %) · {days} ngày"
        )
    elif lever == FLASH_SALE:
        steps = [
            "Vào Marketing › Khuyến mãi › Flash sale › Tạo flash sale",
            "Chọn một khung giờ trong 7 ngày tới (ví dụ 20:00–22:00)",
            f"Thêm sản phẩm {product}, giá flash {money_vi(proposal.new_price)} "
            f"(−{proposal.discount_pct} %)",
            "Bấm Lưu và kiểm tra flash sale ở trạng thái Sắp diễn ra hoặc Đang diễn ra",
        ]
        head = (
            f"Giá flash {short_money_vi(proposal.new_price)} (−{proposal.discount_pct} % so với "
            f"{short_money_vi(proposal.price)})"
        )
    elif lever == SHIPPING_DISCOUNT:
        steps = [
            "Vào Marketing › Khuyến mãi › Giảm phí vận chuyển › Tạo khuyến mãi",
            f"Chọn sản phẩm {product}",
            f"Giảm {money_vi(proposal.shipping_discount)} phí vận chuyển cho đơn từ "
            f"{money_vi(proposal.min_order)}, {span}",
            "Bấm Lưu và kiểm tra khuyến mãi ở trạng thái Đang diễn ra",
        ]
        head = (
            f"Giảm {short_money_vi(proposal.shipping_discount)} phí vận chuyển cho đơn từ "
            f"{short_money_vi(proposal.min_order)} · {days} ngày"
        )
    else:  # BUY_MORE_SAVE_MORE
        steps = [
            "Vào Marketing › Khuyến mãi › Mua nhiều giảm nhiều › Tạo khuyến mãi",
            f"Chọn sản phẩm {product}",
            f"Đặt một bậc: mua từ 2 sản phẩm giảm {proposal.discount_pct} %, {span}",
            "Bấm Lưu và kiểm tra khuyến mãi ở trạng thái Đang diễn ra",
        ]
        head = f"Mua 2 giảm {proposal.discount_pct} % (một bậc) · {days} ngày"
    summary = " · ".join(part for part in (head, margin, cap) if part) + "."
    return Instructions(
        steps=steps, deep_link=SELLER_CENTER_PROMOTIONS_URL, summary=f"{label}: {summary}"
    )


# --- verification ----------------------------------------------------------------------


def new_promotions(
    initial: Mapping[str, Any] | None, latest: Mapping[str, Any] | None
) -> list[Mapping[str, Any]]:
    """Promotions in ``latest`` that were not there when the run started."""
    seen = {
        str(p.get("ref")) for p in (initial or {}).get("promotions") or [] if isinstance(p, Mapping)
    }
    return [
        p
        for p in (latest or {}).get("promotions") or []
        if isinstance(p, Mapping) and str(p.get("ref")) not in seen
    ]


def found_sentence(found: Mapping[str, Any]) -> str:
    begin = found.get("begin_date")
    end = found.get("end_date")

    def fmt(value: object) -> str:
        if isinstance(value, str) and len(value) == 10:
            return f"{value[8:10]}/{value[5:7]}"
        return "…"

    return f"Tìm thấy: {found.get('type_label') or 'khuyến mãi'} · {fmt(begin)} → {fmt(end)}"


__all__ = [
    "BUY_MORE_SAVE_MORE",
    "FLASH_SALE",
    "PRODUCT_DISCOUNT",
    "SELLER_CENTER_PROMOTIONS_URL",
    "SHIPPING_DISCOUNT",
    "TYPE_LABELS_VI",
    "Instructions",
    "PromotionProposal",
    "PromotionRules",
    "PromotionRulesMissing",
    "found_sentence",
    "instructions",
    "load_rules",
    "money_vi",
    "new_promotions",
    "propose",
    "rules_sentence",
    "short_money_vi",
    "sku_prices",
]
