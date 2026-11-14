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

from juli_backend.services.shopee_builder import multi
from juli_backend.services.shopee_builder import specs as sp
from juli_backend.services.shopee_builder.context import BuilderContext, SpecRefused
from juli_backend.services.shopee_builder.engine import engine
from juli_backend.services.shopee_recommendations import evaluate
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
    #: P96: typed warnings ({type, code, message}) beside the free-text notes
    warnings: list[dict[str, Any]] = field(default_factory=list)
    #: P97 D85.13: the single-target translations of a many-target version, ``(target id, tr)``
    parts: list[tuple[str, Translation]] = field(default_factory=list)
    #: P97 D85.13: ``sum`` / ``joint`` when the version names several targets
    multi: str | None = None


def _label(spec: sp.VersionSpec, fallback: str) -> str:
    return spec.label or getattr(spec, "name", None) or fallback


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
        if discount:
            _refuse_unless_below_today(ctx, item_id, key, row)
        out.append(row)
    return out


def _refuse_unless_below_today(
    ctx: BuilderContext, item_id: str, key: str, row: dict[str, Any]
) -> None:
    """P100: %GIẢM of Chương Trình Của Shop / Flash Sale is taken off Giá gốc. A product already
    in a deeper programme (ORY: Giảm giá trực tiếp sản phẩm 15/06-12/12) then gets a price ABOVE
    what buyers pay today; the engine modelled that as a price rise with a discount's CTOR uplift
    and no cost. Refuse with today's price and the smallest %GIẢM that lowers it."""
    current = ctx.env.current_price(key)
    listed = ctx.env.list_price(key)
    after = evaluate.new_price(ctx.env, "product_discount", key, row)
    if current is None or after is None or after < current:
        return
    min_pct = ""
    if listed and listed > current:
        min_pct = str(int((1 - current / listed) * 100) + 1)
    raise SpecRefused(f"discount_not_below_current:{item_id}:{int(current)}:{int(after)}:{min_pct}")


def _sold_sku(ctx: BuilderContext, item_id: str, variation_id: str) -> str | None:
    """The cost key of a variation the seller named, refused when it is the product's own variation
    but has no order in the window (P96: out of stock, say) -- the evaluators price a variation
    from its newest order line, so it could only be called "unknown" later."""
    key = ctx.sku_key(item_id, variation_id)
    if key is not None and variation_id and key not in ctx.env.skus_of(item_id):
        raise SpecRefused(f"sku_no_orders:{key}")
    return key


def _core_keywords(ctx: BuilderContext, item_id: str) -> list[str]:
    li = ctx.env.listings.get(item_id)
    return [k.keyword for k in li.core()] if li is not None else []


def _multi(spec: sp.VersionSpec, ctx: BuilderContext, mode: str) -> Translation:
    """P97 D85.13: a version that names several targets. ``sum``: each target is built as its own
    single-target version and the variant carries the list; ``joint``: one voucher over a product
    list is the ordinary voucher variant, the list only rides along for the rows and the fill."""
    singles = multi.expand(spec, ctx)
    kind = multi.target_kind(spec)
    parts: list[tuple[str, Translation]] = []
    entries: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    first_code: str | None = None
    for tid, single in singles:
        name = multi.target_name(ctx, spec, tid)
        try:
            tr = to_variant(single, ctx)
        except SpecRefused as exc:
            first_code = first_code or exc.code
            refused.append({"id": tid, "kind": kind, "name": name, "refusal": _refusal(exc.code)})
            continue
        parts.append((tid, tr))
        entries.append({"id": tid, "kind": kind, "name": name, "variant": tr.variant})
    if not parts:
        raise SpecRefused(first_code or "no_target")
    if mode == multi.JOINT:
        whole = to_variant(spec, ctx, _flat=True)
        whole.variant["joint_targets"] = [e["id"] for e in entries]
        whole.parts, whole.multi = parts, mode
        whole.details = {**whole.details, "refused_targets": refused}
        return whole
    head = parts[0][1]
    variant = {
        **head.variant,
        "items": list(dict.fromkeys(i for _, t in parts for i in t.variant.get("items") or [])),
        "targets": entries,
        "refused_targets": refused,
    }
    details: dict[str, Any] = {"refused_targets": refused}
    samples = [t.details["sample"] for _, t in parts if t.details.get("sample")]
    if samples:
        totals = [s["total"] for s in samples if s.get("total") is not None]
        details["sample"] = {
            **samples[0],
            "qty": sum(s["qty"] for s in samples),
            "total": sum(totals) if len(totals) == len(samples) else None,
        }
    return Translation(
        variant,
        head.card_kind,
        notes=list(dict.fromkeys(n for _, t in parts for n in t.notes)),
        details=details,
        items=list(dict.fromkeys(i for _, t in parts for i in t.items)),
        warnings=[w for _, t in parts[:1] for w in t.warnings],
        parts=parts,
        multi=mode,
    )


def _refusal(code: str) -> dict[str, str]:
    from juli_backend.services.shopee_recommendations import manual

    return manual.refusal(code)


def to_variant(spec: sp.VersionSpec, ctx: BuilderContext, *, _flat: bool = False) -> Translation:
    mode = None if _flat else multi.mode(spec)
    if mode is not None:
        return _multi(spec, ctx, mode)
    env = ctx.env
    if isinstance(spec, sp.VoucherSpec):
        if spec.scope in ("follower", "livestream"):
            # P96 (owner decision 2026-11-05): the order history does not record which orders
            # used a follower / livestream voucher, so its reach cannot be estimated
            raise SpecRefused("voucher_scope_no_data")
        if spec.discount_type == "amount" and spec.min_spend > 0 and spec.value >= spec.min_spend:
            raise SpecRefused("voucher_value_over_min_spend")
        # P99: the saved version keeps the spec's own days; a voucher without dates is evaluated
        # on the same 30-day horizon as its OptionResult ("30 ngày đầu"), not the engine's 14
        days = spec.days or engine.DEFAULT_DAYS
        inputs = _voucher_inputs(spec.discount_type, spec.value, spec.min_spend, spec.max_value)
        if spec.usage_limit is not None:
            inputs["quantity"] = spec.usage_limit
        if spec.per_buyer_limit is not None:
            inputs["per_user_limit"] = spec.per_buyer_limit
        inputs["days"] = days
        if spec.start and spec.end:
            inputs["start"], inputs["end"] = spec.start.isoformat(), spec.end.isoformat()
        notes: list[str] = []
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
        inputs = {
            "discount_type": spec.discount_type,
            "tiers": [
                {"qty": t.qty, "value": int(t.value) if t.value == int(t.value) else t.value}
                for t in sorted(spec.tiers, key=lambda t: t.qty)
            ],
        }
        if spec.name:
            inputs["name"] = spec.name
        if spec.purchase_limit:
            inputs["limit_per_buyer"] = spec.purchase_limit
        if spec.start:
            inputs["start"] = spec.start.isoformat()
        if spec.end:
            inputs["end"] = spec.end.isoformat()
        return Translation(
            {
                "label": _label(spec, "Combo khuyến mãi"),
                "change_kind": "bundle_deal",
                "items": list(spec.item_ids),
                "inputs": inputs,
            },
            "bundle_deal",
            items=list(spec.item_ids),
            details={"days": spec.days},
        )
    if isinstance(spec, sp.ListingComboSpec):
        inputs = {
            "title": spec.title,
            "price": spec.price,
            "stock": spec.stock,
            "image_refs": list(spec.image_refs),
        }
        if spec.sku:
            inputs["sku"] = spec.sku
        return Translation(
            {
                "label": _label(spec, spec.title),
                "change_kind": "listing_combo",
                "items": list(spec.member_ids),
                "inputs": inputs,
            },
            "listing_combo",
            items=list(spec.member_ids),
        )
    if isinstance(spec, sp.AddOnSpec):
        addons = []
        for a in spec.addons:
            row: dict[str, Any] = {"item_id": a.item_id, "limit": a.limit_per_order}
            key = _sold_sku(ctx, a.item_id, a.variation_id)
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
        if spec.gift.packaging is not None:  # P96: typed packaging counts for a listing gift too
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
        item = spec.item_id or ""
        if not spec.variations:
            raise SpecRefused("variations_required")
        inputs = {"variations": _variation_inputs(ctx, item, spec.variations, discount=True)}
        if spec.days:
            inputs["days"] = spec.days
        if spec.per_buyer_limit:
            inputs["per_buyer_limit"] = spec.per_buyer_limit
        return Translation(
            {
                "label": _label(spec, "Giảm giá"),
                "change_kind": "product_discount",
                "items": [item],
                "inputs": inputs,
            },
            "product_discount",
            items=[item],
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
    if isinstance(spec, sp.AdsNewSpec):
        return _ads_new(spec, ctx)
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
        item = spec.item_id or ""
        kind = "affiliate_target_campaign" if spec.target_campaign else "affiliate_commission"
        details: dict[str, Any] = {}
        aff_inputs: dict[str, Any] = {"commission_pct": spec.commission_pct}
        if spec.sample_qty:
            details["sample"] = _sample_cost(ctx, spec, item)
            if details["sample"]["total"] is not None:  # P96: samples come out of the profit
                aff_inputs["sample_cost"] = details["sample"]["total"]
        return Translation(
            {
                "label": _label(spec, "Liên kết"),
                "change_kind": kind,
                "items": [item],
                "inputs": aff_inputs,
            },
            kind,
            items=[item],
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
        stock = env.stock(spec.item_id)
        if spec.item_id in env.view.active_items and (stock is None or stock > 0):
            # P96: "Đưa lại listing" is for a hidden or sold-out listing
            raise SpecRefused("listing_already_live")
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


def _sample_cost(ctx: BuilderContext, spec: sp.AffiliateSpec, item_id: str) -> dict[str, Any]:
    """P91 D-9 / D-11: a sample costs giá vốn + đóng gói (+ the shipping of the parcel)."""
    from juli_backend.services.shopee_recommendations.unit_cost import gift_cost_of, unit_cost

    rows = ctx.rows(item_id)
    best = max(rows, key=lambda r: r["selling_price"] or 0, default=None)
    cost = unit_cost(
        ctx.env.rules,
        item_id,
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
    taken = {str(v) for r in rows for v in (r.get("sku"), r.get("sku_key")) if v}
    warnings: list[dict[str, Any]] = []
    for nv in spec.new_variations:
        if nv.sku and nv.sku.strip() in taken:  # P96: a new variation needs its own SKU
            raise SpecRefused("sku_duplicate")
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
        if unit_price and pack > 1 and per_unit >= unit_price:
            warnings.append(
                {
                    "type": "note",
                    "code": "set_dearer_than_single",
                    "message": f"{nv.name}: giá mỗi đơn vị không rẻ hơn mua lẻ.",
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
        warnings=warnings,
    )


def _ads_warnings(spec: sp.AdsSpec, ctx: BuilderContext) -> list[dict[str, Any]]:
    """Shopee's own cautions of the edit form (recon 2026-11-09): a custom ROAS above the hint, and
    a second ROAS change within a week (that week's performance support is lost)."""
    out: list[dict[str, Any]] = []
    if spec.lever != "roas":
        return out
    if spec.roas_target is not None and spec.roas_target > sp.ADS_ROAS_HINT:
        out.append(
            {
                "type": "ads_roas_above_hint",
                "code": "ads_roas_above_hint",
                "hint": sp.ADS_ROAS_HINT,
                "message": f"Vui lòng đặt ≤ {sp.ADS_ROAS_HINT:g} (gợi ý của Shopee): ROAS mục "
                "tiêu càng cao, quảng cáo càng ít được hiển thị.",
            }
        )
    setting = ctx.env.setting_for(spec.campaign_key) if spec.campaign_key else None
    if setting is not None and setting.roas_changes_7d >= 1:
        out.append(
            {
                "type": "ads_roas_second_change",
                "code": "ads_roas_second_change",
                "message": "Chiến dịch này đã đổi ROAS trong 7 ngày qua. Đổi ROAS hoặc cách đặt "
                "giá thầu từ 2 lần trong một tuần thì tuần đó mất hỗ trợ hiệu suất của Shopee.",
            }
        )
    return out


def _ads_new(spec: sp.AdsNewSpec, ctx: BuilderContext) -> Translation:
    """P99: a new Hiển thị Sản phẩm campaign as a card (``ads_new_campaign``): its certain layer
    is the spend (daily budget × days) against the cap; its numbers are the OptionResult's
    (measured extra orders only, else "chưa ước tính được — cần chạy thử")."""
    for item in spec.item_ids:
        if item in ctx.env.excluded:
            raise SpecRefused("item_excluded")
    days = spec.days or engine.DEFAULT_DAYS
    inputs: dict[str, Any] = {
        "daily_budget": spec.daily_budget,
        "roas_target": spec.roas_target,
        "roas_mode": "system" if spec.roas_target is None else "custom",
        "campaign": spec.campaign,
        "days": days,
        "start": spec.start.isoformat(),
    }
    if spec.end:
        inputs["end"] = spec.end.isoformat()
    if spec.name:
        inputs["name"] = spec.name
    items = list(spec.item_ids)
    return Translation(
        {
            "label": _label(spec, spec.name or "Quảng cáo mới"),
            "change_kind": "ads_new_campaign",
            "items": items,
            "inputs": inputs,
        },
        "ads_new_campaign",
        items=items,
        details={"days": days, "total_budget": spec.daily_budget * days},
    )


def _ads(spec: sp.AdsSpec, ctx: BuilderContext) -> Translation:
    base: dict[str, Any] = {"label": _label(spec, "Quảng cáo"), "campaign_key": spec.campaign_key}
    schedule = {k: v.isoformat() for k, v in (("start", spec.start), ("end", spec.end)) if v}
    if spec.lever in ("budget", "roas") and not spec.campaign_key:
        raise SpecRefused("no_campaign_report")
    warnings = _ads_warnings(spec, ctx)
    if spec.lever == "budget":
        if spec.daily_budget is not None and spec.daily_budget < sp.ADS_MIN_BUDGET:
            raise SpecRefused("ads_budget_below_min")
        inputs: dict[str, Any] = (
            {"daily_budget": None, "unlimited": True}
            if spec.unlimited
            else {"daily_budget": spec.daily_budget}
        )
        return Translation(
            {**base, "change_kind": "ads_budget", "items": [], "inputs": {**inputs, **schedule}},
            "ads_budget",
            warnings=warnings,
        )
    if spec.lever == "roas":
        inputs = (
            {"roas_mode": "system"}
            if spec.roas_mode == "system"
            else {"roas_target": spec.roas_target, "roas_mode": "custom"}
        )
        return Translation(
            {
                **base,
                "change_kind": "ads_roas_target",
                "items": [],
                "inputs": {**inputs, **schedule},
            },
            "ads_roas_target",
            warnings=warnings,
        )
    if not spec.campaign_key:
        raise SpecRefused("no_campaign_report")
    kind = "ads_add_product" if spec.lever == "add_product" else "ads_remove_product"
    return Translation(
        {**base, "change_kind": kind, "items": [spec.item_id], "inputs": schedule},
        kind,
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
