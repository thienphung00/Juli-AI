"""P92 B-4: a typed version -> the variant the recommendation machinery builds a card from.

``to_variant`` is where every kind's inputs meet the existing evaluators (``shopee_recommendations
.evaluate`` / ``combo``): the builder never forks a formula. A version either becomes one variant
(``change_kind`` + ``items`` + ``extra`` + ``inputs``, the shape ``manual.build_variant`` takes) or
is refused with a code. ``Translation.estimate`` is a second, shadow variant for kinds whose card
has no estimate of its own (a variation set is saved as a ``variation_restructure`` table but its
numbers come from the set model).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.context import BuilderContext, SpecRefused
from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations import listing as lst


@dataclass
class Translation:
    variant: dict[str, Any]
    #: the change_kind the "chọn" card is saved as
    card_kind: str
    #: a shadow variant that carries the numbers when the saved card has none
    estimate: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)
    #: kind-specific figures the outcome shows beside the card's (static economics ...)
    details: dict[str, Any] = field(default_factory=dict)
    #: items the cost-known check covers
    items: list[str] = field(default_factory=list)


def _label(spec: sp.VersionSpec, fallback: str) -> str:
    return spec.label or fallback


def _voucher_inputs(
    discount_type: str, value: float, min_spend: int, max_value: int | None
) -> dict[str, Any]:
    out: dict[str, Any] = {"min_spend": min_spend}
    if discount_type == "pct":
        out["pct"] = value
        if max_value is not None:
            out["max_value"] = max_value
    else:
        out["value"] = int(value) if value == int(value) else value
    return out


def _variation_inputs(
    ctx: BuilderContext,
    item_id: str,
    variations: list[sp.VariationPrice],
    *,
    discount: bool,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for v in variations:
        key = ctx.sku_key(item_id, v.variation_id)
        if key is None:
            raise SpecRefused("variation_required")
        row: dict[str, Any] = {"sku": key}
        if v.final_price is not None:
            row["final_price"] = v.final_price
            listed = (ctx.variation(item_id, v.variation_id) or {}).get("list_price")
            if discount and listed and v.final_price >= listed:
                raise SpecRefused("final_price_not_below_list")
        elif v.discount_pct is not None:
            row["discount_pct"] = v.discount_pct
        else:
            row["new_price_pct"] = 100 + float(v.change_pct or 0)
        out.append(row)
    return out


def _core_keywords(ctx: BuilderContext, item_id: str) -> list[str]:
    li = ctx.env.listings.get(item_id)
    return [k.keyword for k in li.core()] if li is not None else []


def to_variant(spec: sp.VersionSpec, ctx: BuilderContext) -> Translation:
    env = ctx.env
    if isinstance(spec, sp.VoucherSpec):
        days = spec.days or config.VOUCHER_DAYS
        inputs = _voucher_inputs(spec.discount_type, spec.value, spec.min_spend, spec.max_value)
        if spec.usage_limit is not None:
            inputs["quantity"] = spec.usage_limit
        if spec.per_buyer_limit is not None:
            inputs["per_user_limit"] = spec.per_buyer_limit
        inputs["days"] = days
        notes = []
        if spec.scope in ("follower", "livestream"):
            notes.append(
                "Lịch sử đơn không ghi đơn nào dùng voucher theo dõi / livestream, nên số đơn đủ "
                "điều kiện tính trên mọi đơn của shop: đây là mức tối đa, không phải mức dự kiến."
            )
        return Translation(
            {
                "label": _label(spec, "Voucher"),
                "change_kind": "min_spend_voucher",
                "items": list(spec.item_ids),
                "extra": {"voucher_scope": spec.scope},
                "inputs": inputs,
            },
            "min_spend_voucher",
            notes=notes,
            items=list(spec.item_ids),
            details={"voucher_scope": spec.scope, "days": days},
        )
    if isinstance(spec, sp.ComboSpec):
        lines = []
        for line in spec.items:
            entry: dict[str, Any] = {"item_id": line.item_id, "qty": line.qty}
            key = ctx.sku_key(line.item_id, line.variation_id)
            if key is not None:
                entry["sku"] = key
            lines.append(entry)
        extra: dict[str, Any] = {
            "combo_items": lines,
            "discount_type": spec.pricing,
            "discount_value": int(spec.value) if spec.value == int(spec.value) else spec.value,
        }
        if spec.voucher is not None:
            extra["voucher"] = _voucher_inputs(
                spec.voucher.discount_type,
                spec.voucher.value,
                spec.voucher.min_spend,
                spec.voucher.max_value,
            )
        if spec.gift_item_id:
            extra["gift_item"] = spec.gift_item_id
        return Translation(
            {
                "label": _label(spec, "Combo"),
                "change_kind": "combo_multi",
                "items": [line.item_id for line in spec.items],
                "extra": extra,
                "inputs": {"combo_target": spec.target},
            },
            "combo_multi",
            items=[line.item_id for line in spec.items],
            details={"target": spec.target},
        )
    if isinstance(spec, sp.AddOnSpec):
        addons = []
        for a in spec.addons:
            row: dict[str, Any] = {"item_id": a.item_id, "limit": a.limit_per_order}
            key = ctx.sku_key(a.item_id, a.variation_id)
            if key is not None:
                row["sku"] = key
            if a.price is not None:
                row["price"] = a.price
            else:
                row["pct"] = a.pct
            addons.append(row)
        return Translation(
            {
                "label": _label(spec, "Mua kèm"),
                "change_kind": "add_on",
                "items": [spec.main_item_id],
                "inputs": {"addons": addons},
            },
            "add_on",
            items=[spec.main_item_id, *[a.item_id for a in spec.addons]],
        )
    if isinstance(spec, sp.GiftSpec):
        gift: dict[str, Any] = {"qty": spec.gift.qty}
        extra = {}
        if spec.gift.item_id:
            gift["item_id"] = spec.gift.item_id
            extra["gift_item"] = spec.gift.item_id
        else:
            gift["unit_cost"] = spec.gift.unit_cost
            gift["label"] = spec.gift.label or "Quà không bán"
            if spec.gift.packaging:
                gift["packaging"] = spec.gift.packaging
        trigger = spec.trigger.model_dump(exclude_none=True)
        items = (
            [spec.trigger.item_id]
            if spec.trigger.type == "buy_item" and spec.trigger.item_id
            else []
        )
        return Translation(
            {
                "label": _label(spec, "Quà tặng"),
                "change_kind": "gift",
                "items": items,
                "extra": extra,
                "inputs": {"gift": gift, "trigger": trigger},
            },
            "gift",
            items=[*items, *([spec.gift.item_id] if spec.gift.item_id else [])],
        )
    if isinstance(spec, sp.ProductDiscountSpec):
        if not spec.variations:
            raise SpecRefused("variations_required")
        inputs = {
            "variations": _variation_inputs(ctx, spec.item_id, spec.variations, discount=True)
        }
        if spec.days:
            inputs["days"] = spec.days
        if spec.per_buyer_limit:
            inputs["per_buyer_limit"] = spec.per_buyer_limit
        return Translation(
            {
                "label": _label(spec, "Giảm giá"),
                "change_kind": "product_discount",
                "items": [spec.item_id],
                "inputs": inputs,
            },
            "product_discount",
            items=[spec.item_id],
        )
    if isinstance(spec, sp.PriceSpec):
        return Translation(
            {
                "label": _label(spec, "Đổi giá"),
                "change_kind": "price",
                "items": [spec.item_id],
                "inputs": {
                    "variations": _variation_inputs(
                        ctx, spec.item_id, spec.variations, discount=False
                    )
                },
            },
            "price",
            items=[spec.item_id],
        )
    if isinstance(spec, sp.FlashSaleSpec):
        if not spec.variations:
            raise SpecRefused("variations_required")
        return Translation(
            {
                "label": _label(spec, "Flash Sale"),
                "change_kind": "flash_sale",
                "items": [spec.item_id],
                "inputs": {
                    "variations": _variation_inputs(
                        ctx, spec.item_id, spec.variations, discount=True
                    ),
                    "units": spec.units,
                    "slot_days": max(1, math.ceil(spec.slot_hours / 24)),
                    "slot_start": spec.slot_start,
                    "slot_hours": spec.slot_hours,
                },
            },
            "flash_sale",
            items=[spec.item_id],
        )
    if isinstance(spec, sp.VariationSetSpec):
        return _variation_set(spec, ctx)
    if isinstance(spec, sp.AdsSpec):
        return _ads(spec, ctx)
    if isinstance(spec, sp.TitleSpec):
        li = env.listings.get(spec.item_id)
        if li is None or not li.title:
            raise SpecRefused("no_listing")
        return Translation(
            {
                "label": _label(spec, "Tiêu đề"),
                "change_kind": "title",
                "items": [spec.item_id],
                "inputs": {"title": spec.title},
                "extra": {
                    "current_title": li.title,
                    "core": _core_keywords(ctx, spec.item_id),
                    "notes": [],
                },
            },
            "title",
            items=[spec.item_id],
            details={"keywords": list(spec.keywords)},
        )
    if isinstance(spec, sp.CoverSpec):
        return _cover(spec, ctx, "cover_image")
    if isinstance(spec, sp.PriceDisplaySpec):
        return _price_display(spec, ctx)
    if isinstance(spec, sp.DescriptionSpec):
        return Translation(
            {
                "label": _label(spec, "Dòng đầu mô tả"),
                "change_kind": "description_first_line",
                "items": [spec.item_id],
                "inputs": {"first_line": spec.first_line},
                "extra": {"current_first_line": None},
            },
            "description_first_line",
            items=[spec.item_id],
        )
    if isinstance(spec, sp.AffiliateSpec):
        kind = "affiliate_target_campaign" if spec.target_campaign else "affiliate_commission"
        details: dict[str, Any] = {}
        if spec.sample_qty:
            details["sample"] = _sample_cost(ctx, spec)
        return Translation(
            {
                "label": _label(spec, "Liên kết"),
                "change_kind": kind,
                "items": [spec.item_id],
                "inputs": {"commission_pct": spec.commission_pct},
            },
            kind,
            items=[spec.item_id],
            details=details,
        )
    if isinstance(spec, sp.HideSpec):
        return Translation(
            {
                "label": _label(spec, "Ẩn sản phẩm"),
                "change_kind": "listing_hide",
                "items": [spec.item_id],
                "inputs": {},
            },
            "listing_hide",
            items=[spec.item_id],
        )
    if isinstance(spec, sp.RelistSpec):
        inputs = {} if spec.stock is None else {"stock": spec.stock}
        return Translation(
            {
                "label": _label(spec, "Đưa sản phẩm trở lại"),
                "change_kind": "listing_relist",
                "items": [spec.item_id],
                "inputs": inputs,
                "extra": {"current_stock": env.stock(spec.item_id)},
            },
            "listing_relist",
            items=[spec.item_id],
        )
    raise SpecRefused("unknown_kind")


def _sample_cost(ctx: BuilderContext, spec: sp.AffiliateSpec) -> dict[str, Any]:
    """P91 D-9 / D-11: a sample costs giá vốn + đóng gói (+ the shipping of the parcel)."""
    from juli_backend.services.shopee_recommendations.unit_cost import gift_cost_of, unit_cost

    rows = ctx.rows(spec.item_id)
    best = max(rows, key=lambda r: r["selling_price"] or 0, default=None)
    cost = unit_cost(
        ctx.env.rules,
        spec.item_id,
        best["variation_id"] if best else "",
        seller_sku=best["sku"] if best else None,
        variation_name=best["name"] if best else None,
    )
    unit = gift_cost_of(cost)
    total = None if unit is None else float(unit) * spec.sample_qty + spec.sample_ship_fee
    return {
        "qty": spec.sample_qty,
        "unit_cost": None if unit is None else float(unit),
        "ship_fee": spec.sample_ship_fee,
        "total": total,
        "label": "giá vốn + đóng gói + phí ship" if unit is not None else "chưa tính",
    }


def _variation_set(spec: sp.VariationSetSpec, ctx: BuilderContext) -> Translation:
    rows = ctx.rows(spec.item_id)
    unit_price = max((r["price_per_unit"] or 0 for r in rows), default=0)
    new_rows = []
    details: list[dict[str, Any]] = []
    best: tuple[int, float] | None = None
    from decimal import Decimal

    from juli_backend.services.shopee_builder.variations import unit_margin
    from juli_backend.services.shopee_profit.pack import pack_count_from_name
    from juli_backend.services.shopee_recommendations.unit_cost import UnitCost, unit_cost

    base_row = max(rows, key=lambda r: r["selling_price"] or 0, default=None)
    base_cost = unit_cost(
        ctx.env.rules,
        spec.item_id,
        base_row["variation_id"] if base_row else "",
        seller_sku=base_row["sku"] if base_row else None,
        variation_name=base_row["name"] if base_row else None,
    )
    single_cost = None if base_cost.cogs is None else base_cost.cogs / max(base_cost.pack_count, 1)
    schedule = ctx.env.schedule(spec.item_id)
    for nv in spec.new_variations:
        pack = nv.pack_count or pack_count_from_name(nv.name) or 1
        new_rows.append({"name": nv.name, "price": nv.price, "sku": nv.sku, "stock": nv.stock})
        per_unit = nv.price / pack
        margin = profit = None
        if single_cost is not None:
            cost = UnitCost(
                single_cost * pack,
                base_cost.packaging,
                pack,
                "name",
                False,
                base_cost.vat,
            )
            m, p, _ = unit_margin(
                spec.item_id,
                nv.sku or f"new:{nv.name}",
                cost,
                Decimal(nv.price),
                Decimal(nv.price),
                schedule,
                ctx.env.as_of,
            )
            margin, profit = m, p
        details.append(
            {
                "name": nv.name,
                "price": nv.price,
                "pack_count": pack,
                "price_per_unit": round(per_unit, 2),
                "margin_pct": None if margin is None else round(float(margin) * 100, 1),
                "profit_per_unit": None if profit is None else float(profit),
                "margin_label": None if margin is not None else "chưa tính",
            }
        )
        if unit_price and pack > 1 and (best is None or pack > best[0]):
            best = (pack, max(0.0, (1 - per_unit / unit_price) * 100))
    variant = {
        "label": _label(spec, "Phân loại / set"),
        "change_kind": "variation_restructure",
        "items": [spec.item_id],
        "inputs": {"variations": new_rows, "hide_items": list(spec.hide_item_ids)},
        "extra": {
            "current_variations": [
                {
                    "name": r["name"],
                    "price": r["selling_price"],
                    "sku": r["sku"],
                    "stock": r["stock"],
                }
                for r in rows
            ]
        },
    }
    estimate = None
    if best is not None and best[1] > 0:
        estimate = {
            "label": variant["label"],
            "change_kind": "variation_set",
            "items": [spec.item_id],
            "inputs": {"set_size": best[0], "set_discount_pct": round(best[1], 1)},
        }
    notes = []
    if estimate is None:
        notes.append("Chưa có phân loại nào rẻ hơn đơn giá hiện tại nên chưa ước tính được AOV.")
    return Translation(
        variant,
        "variation_restructure",
        estimate=estimate,
        notes=notes,
        items=[spec.item_id],
        details={"new_variations": details},
    )


def _ads(spec: sp.AdsSpec, ctx: BuilderContext) -> Translation:
    base: dict[str, Any] = {"label": _label(spec, "Quảng cáo"), "campaign_key": spec.campaign_key}
    if spec.lever in ("budget", "roas") and not spec.campaign_key:
        raise SpecRefused("no_campaign_report")
    if spec.lever == "budget":
        return Translation(
            {
                **base,
                "change_kind": "ads_budget",
                "items": [],
                "inputs": {"daily_budget": spec.daily_budget},
            },
            "ads_budget",
        )
    if spec.lever == "roas":
        return Translation(
            {
                **base,
                "change_kind": "ads_roas_target",
                "items": [],
                "inputs": {"roas_target": spec.roas_target},
            },
            "ads_roas_target",
        )
    if spec.lever in ("add_product", "remove_product"):
        if not spec.campaign_key:
            raise SpecRefused("no_campaign_report")
        kind = "ads_add_product" if spec.lever == "add_product" else "ads_remove_product"
        return Translation(
            {**base, "change_kind": kind, "items": [spec.item_id], "inputs": {}},
            kind,
            items=[spec.item_id] if spec.item_id else [],
        )
    keywords = [
        {
            "keyword": k.keyword,
            "bid": k.bid,
            "match": k.match,
            **{f: v for f, v in (ctx.keyword_facts.get(lst_fold(k.keyword)) or {}).items()},
        }
        for k in spec.keywords
    ]
    return Translation(
        {
            **base,
            "change_kind": "ads_keywords",
            "items": [spec.item_id] if spec.item_id else [],
            "inputs": {"keywords": keywords},
        },
        "ads_keywords",
        items=[spec.item_id] if spec.item_id else [],
    )


def lst_fold(text: str) -> str:
    from juli_backend.services.shopee_analytics.fee_table import fold

    return fold(text).strip()


def _overlay_text(o: sp.CoverOverlay) -> str:
    bits = []
    if o.price_vnd:
        bits.append(f"giá {lst.vnd(o.price_vnd)}")
    if o.original_price_vnd:
        bits.append(f"giá gốc {lst.vnd(o.original_price_vnd)}")
    if o.discount_pct:
        bits.append(f"-{o.discount_pct:g}%")
    for text in (o.voucher_text, o.pack_text, o.badge_text, o.hook_text):
        if text:
            bits.append(text)
    return "Ghi lên ảnh bìa (" + o.layout + "): " + "; ".join(bits)


def _cover(spec: sp.CoverSpec, ctx: BuilderContext, kind: str) -> Translation:
    li = ctx.env.listings.get(spec.item_id)
    if li is None or not li.cover_url:
        raise SpecRefused("no_listing")
    return Translation(
        {
            "label": _label(spec, "Ảnh bìa"),
            "change_kind": kind,
            "items": [spec.item_id],
            "inputs": {},
            "extra": {
                "cover_url": li.cover_url,
                "image_count": li.image_count,
                "before_text": f"Ảnh bìa hiện tại (ảnh 1 trong {li.image_count}): {li.cover_url}",
                "after_text": _overlay_text(spec.overlay),
                "overlay": spec.overlay.model_dump(exclude_none=True),
            },
        },
        kind,
        items=[spec.item_id],
        details={"overlay": spec.overlay.model_dump(exclude_none=True)},
    )


def _price_display(spec: sp.PriceDisplaySpec, ctx: BuilderContext) -> Translation:
    li = ctx.env.listings.get(spec.item_id)
    if li is None or not li.cover_url:
        raise SpecRefused("no_listing")
    row = ctx.variation(spec.item_id, spec.variation_id) or (
        ctx.rows(spec.item_id)[0] if ctx.rows(spec.item_id) else None
    )
    line = spec.text
    if not line and row and row["price_per_unit"]:
        line = f"{lst.vnd(row['price_per_unit'])} / đơn vị"
    return Translation(
        {
            "label": _label(spec, "Hiển thị giá"),
            "change_kind": "price_display",
            "items": [spec.item_id],
            "inputs": {},
            "extra": {
                "cover_url": li.cover_url,
                "image_count": li.image_count,
                "before_text": f"Ảnh bìa hiện tại chưa nêu đơn giá: {li.cover_url}",
                "after_text": f"Ghi thêm lên ảnh bìa: “{line}”." if line else "",
                "line": line,
            },
        },
        "price_display",
        items=[spec.item_id],
    )


__all__ = ["Translation", "to_variant"]
