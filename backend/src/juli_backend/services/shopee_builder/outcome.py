"""P92 B-3: the same outcome for every version.

``shape`` turns one built card (``cards.build_card`` through ``manual.build_variant``) into the
block the compare table and the builder panel show:

- ``driver`` -- the metric(s) the strategy moves, CTOR naming (orders / clicks);
- ``delta`` -- Δ GMV, Δ orders, Δ profit per month as ``{low, p50, high}`` (P10 / P50 / P90);
- ``margin_after_pct`` -- the margin after the change;
- ``cost`` -- the cost of the change (combo: the discount given to buyers x expected combos);
- ``break_even`` -- extra orders AND the CTOR they take ("≥ 18 đơn, CTOR ≥ 2,71 %");
- ``basis`` -- where the estimate comes from: ``product_history`` | ``shop`` | ``prior`` |
  ``insufficient``;
- ``warnings`` -- a floor or spend-cap breach, an unknown giá vốn ...: they warn, never block.

A listing without a giá vốn can be built: profit and margin are ``None`` with
``profit_status = "chua_tinh"`` (B-7.1), GMV and orders are still shown. Pure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from juli_backend.services.shopee_builder.context import BuilderContext
from juli_backend.services.shopee_builder.traffic import break_even_ctor, scope_traffic
from juli_backend.services.shopee_builder.translate import Translation
from juli_backend.services.shopee_recommendations import config

METRIC_LABELS: dict[str, str] = {
    "aov": "AOV",
    "ctor": "CTOR",
    "orders": "Số đơn",
    "spend": "Chi quảng cáo",
    "gmv": "GMV",
    "roas": "ROAS",
    "views": "Lượt xem",
    "ctr": "CTR",
    "affiliate_orders": "Đơn liên kết",
}
#: P92 B-3: the driver metric(s) per strategy.
DRIVERS: dict[str, tuple[str, ...]] = {
    "min_spend_voucher": ("aov", "ctor"),
    "combo_multi": ("aov", "ctor"),
    "add_on": ("aov",),
    "gift": ("ctor", "orders"),
    "product_discount": ("ctor", "orders"),
    "price": ("ctor", "orders"),
    "flash_sale": ("ctor", "orders"),
    "ads_budget": ("spend", "gmv", "roas"),
    "ads_roas_target": ("spend", "gmv", "roas"),
    "ads_add_product": ("spend", "gmv", "roas"),
    "ads_remove_product": ("spend", "gmv", "roas"),
    "ads_keywords": ("spend", "gmv", "roas"),
    "title": ("views", "ctr"),
    "cover_image": ("ctr",),
    "description_first_line": ("ctor",),
    "variation_restructure": ("aov", "ctor"),
    "variation_set": ("aov", "ctor"),
    "affiliate_commission": ("affiliate_orders",),
    "affiliate_target_campaign": ("affiliate_orders",),
    "price_display": ("ctr", "ctor"),
    "listing_hide": ("views",),
    "listing_relist": ("views",),
}
BASIS_LABELS: dict[str, str] = {
    "product_history": "từ lịch sử sản phẩm",
    "shop": "của shop",
    "prior": "ước tính chung",
    "insufficient": "không đủ dữ liệu",
}
#: Lift source (``Lift.source``) -> estimate basis.
_SOURCE_BASIS = {
    "product_history": "product_history",
    "shop_products": "shop",
    "shop": "shop",
    "prior": "prior",
}


#: P96: every reason code the outcome carries, as the sentence a person reads. The codes stay in
#: the JSON; clients print ``*_text`` and never a code.
REASON_TEXT: dict[str, str] = {
    "not_applicable": "Thay đổi này không có chi phí trực tiếp để hoà vốn; đo sau khi chạy.",
    "no_flow_data": "Chưa có lưu lượng theo nguồn để tính CTOR cần đạt.",
    "no_clicks": "Chưa có lượt nhấp để tính CTOR cần đạt.",
    "no_extra_cost": "Không tốn thêm chi phí nên không cần thêm đơn.",
    "profit_per_order_unknown": "Chưa biết lợi nhuận mỗi đơn (thiếu giá vốn hoặc phí).",
    "profit_unknown": "Chưa biết lợi nhuận mỗi đơn (thiếu giá vốn hoặc phí).",
    "profit_per_order_non_positive": (
        "Mỗi đơn đang lỗ hoặc hoà vốn, thêm đơn không bù được chi phí."
    ),
    "no_qualifying_orders": "Chưa có đơn nào đạt đơn tối thiểu.",
    "no_margin": "Đơn dùng voucher không có lãi nên giỏ hàng lớn hơn không bù được chi phí.",
}
GENERIC_REASON_TEXT = "Chưa tính được điểm hoà vốn cho thay đổi này."


def reason_text(code: str | None) -> str | None:
    """The sentence for a reason code; an unknown code gets a general sentence, never itself."""
    if code is None:
        return None
    return REASON_TEXT.get(code.split(":", 1)[0], GENERIC_REASON_TEXT)


def _band(total: Mapping[str, Any], key: str) -> dict[str, float | None]:
    return {
        "low": total["p10"][key],
        "p50": total["p50"][key],
        "high": total["p90"][key],
    }


def _band_of(block: Mapping[str, Any], key: str) -> dict[str, float | None]:
    return {"low": block["p10"][key], "p50": block["p50"][key], "high": block["p90"][key]}


def _per_day(card: Mapping[str, Any], cost_known: bool) -> dict[str, Any] | None:
    block = card["predicted"]["money_per_month"].get("per_day")
    if not block:
        return None
    total = block["total"]
    profit = _band_of(total, "dprofit")
    return {
        "gmv": _band_of(total, "dgmv"),
        "orders": _band_of(total, "dorders"),
        "profit": profit if cost_known else {"low": None, "p50": None, "high": None},
        "cost": block["certain"]["dchi"],
    }


def _period(card: Mapping[str, Any], cost_known: bool) -> dict[str, Any] | None:
    block = card["predicted"]["money_per_month"].get("period")
    if not block:
        return None
    total = block["total"]
    return {
        "days": block["days"],
        "gmv": _band_of(total, "dgmv"),
        "orders": _band_of(total, "dorders"),
        "profit": _band_of(total, "dprofit")
        if cost_known
        else {"low": None, "p50": None, "high": None},
        "cost": block["certain"]["dchi"],
    }


def _per_order(card: Mapping[str, Any], cost_known: bool) -> dict[str, Any] | None:
    block = card["predicted"]["money_per_month"].get("per_order")
    if not block:
        return None
    return {
        "basis": block["basis"],
        "orders": block["orders_in_period"],
        "cost": block["certain"]["cost"],
        "profit": _band_of(block["total"], "dprofit")
        if cost_known
        else {"low": None, "p50": None, "high": None},
    }


def basis_of(card: Mapping[str, Any]) -> dict[str, Any]:
    """Where the card's estimate comes from. ``insufficient`` when no volume could be predicted
    (no traffic base, or a kind without a prior) and the certain layer is empty too."""
    lift = card["predicted"]["lift"]
    money = card["predicted"]["money_per_month"]
    total = money["total"]
    flat = all(total[q]["dgmv"] == 0 for q in ("p10", "p50", "p90"))
    has_certain = money["certain"]["dprofit"] != 0 or money["certain"]["dgmv"] != 0
    source = str(lift.get("source") or "prior")
    if flat and not has_certain:
        return {
            "key": "insufficient",
            "label": BASIS_LABELS["insufficient"],
            "detail": "Chưa có căn cứ để dự kiến lượt xem, đơn hay doanh thu cho thay đổi này.",
            "volume_estimate": False,
        }
    key = _SOURCE_BASIS.get(source, "prior")
    detail = {
        "product_history": "Đơn của chính sản phẩm khi từng giảm giá trước đây.",
        "shop": "Kết quả đã đo của các sản phẩm khác trong shop.",
        "prior": "Mức ước tính chung, chưa có đủ lịch sử của shop.",
    }[key]
    return {
        "key": key,
        "label": BASIS_LABELS[key],
        "detail": detail,
        "volume_estimate": not flat,
    }


def _items_cost_known(ctx: BuilderContext, items: Sequence[str]) -> tuple[bool, list[str]]:
    """Every listing the version touches has a real giá vốn (per its SKUs' cost source)."""
    env = ctx.env
    missing = []
    for item in dict.fromkeys(items):
        skus = env.skus_of(item)
        if skus and all(env.view.costs.cogs_is_real(s) for s in skus):
            continue
        if not skus and all(r["has_cost"] for r in ctx.rows(item)) and ctx.rows(item):
            continue
        missing.append(item)
    return not missing, missing


def _period_days(card: Mapping[str, Any]) -> int:
    return int(card["predicted"]["money_per_month"].get("days") or config.DAYS_PER_MONTH)


def _cost(card: Mapping[str, Any], tr: Translation, p50_orders: float | None) -> dict[str, Any]:
    kind = card["change_kind"]
    certain = card["certain"]
    out: dict[str, Any] = {"amount": None, "period_days": None, "label": None, "per_unit": None}
    if kind == "min_spend_voucher":
        out.update(
            amount=certain.get("voucher_cost_scenario"),
            period_days=certain.get("days"),
            label="Voucher ở mức dùng dự kiến",
        )
    elif kind == "combo_multi":
        per = (certain.get("combo_discount") or 0) + (certain.get("voucher_discount") or 0)
        baskets = certain.get("existing_combo_baskets") or 0
        extra = max(round(p50_orders or 0), 0)
        units = baskets + extra
        out.update(
            amount=per * max(units, 1),
            per_unit=per,
            period_days=config.DAYS_PER_MONTH,
            label="Mức giảm cho khách × số combo dự kiến trong tháng",
            expected_units=max(units, 1),
            expected_units_basis="history" if units else "minimum_one",
        )
    elif kind == "add_on":
        # P96: the discount on today's attaches and on the attaches the deal is expected to bring
        period = card["predicted"]["money_per_month"].get("period") or {}
        days = period.get("days") or config.DAYS_PER_MONTH
        existing = -((period.get("certain") or {}).get("dprofit") or 0)
        gained = ((period.get("total") or {}).get("p50") or {}).get("dgmv") or 0
        rate = certain.get("discount_per_attach_gmv") or 0
        out.update(
            amount=round(existing + max(gained, 0) * rate),
            period_days=days,
            label="Giảm cho khách trên các lần mua kèm hiện có và dự kiến",
            existing=certain.get("discount_cost_on_existing"),
        )
    elif kind == "gift":
        gift = certain.get("gift") or {}
        out.update(
            amount=gift.get("gift_cost_window"),
            per_unit=gift.get("cost_per_gift"),
            period_days=config.DAYS_PER_MONTH,
            label="Giá vốn + đóng gói của quà × số đơn đủ điều kiện",
        )
    elif kind in ("product_discount", "price", "flash_sale"):
        delta = certain.get("profit_delta_same_volume")
        period = card["predicted"]["money_per_month"].get("period")
        if delta is not None and period:  # P96: over the change's own days (a flash: its slot)
            out.update(amount=max(-period["certain"]["dprofit"], 0), period_days=period["days"])
        else:
            out.update(
                amount=None if delta is None else max(-delta, 0), period_days=_period_days(card)
            )
        out["label"] = "Lợi nhuận mất đi nếu số đơn không đổi"
    elif kind.startswith("ads_"):
        spend = card.get("spend") or {}
        out.update(
            amount=None
            if spend.get("card_dchi_per_day") is None
            else spend["card_dchi_per_day"] * config.DAYS_PER_MONTH,
            period_days=config.DAYS_PER_MONTH,
            label="Chênh lệch chi quảng cáo trong tháng",
        )
    elif kind.startswith("affiliate_"):
        before = certain.get("commission_cost_before")
        after = certain.get("commission_cost_after")
        sample = (tr.details.get("sample") or {}).get("total")
        commission = None if before is None or after is None else after - before
        total = None
        if commission is not None or sample is not None:
            total = (commission or 0) + (sample or 0)
        out.update(
            amount=total,
            period_days=config.DAYS_PER_MONTH,
            label="Hoa hồng tăng thêm + mẫu gửi KOL (giá vốn + đóng gói + ship)",
        )
        if tr.details.get("sample"):
            out["sample"] = tr.details["sample"]
    return out


def _break_even(
    card: Mapping[str, Any], ctx: BuilderContext, items: Sequence[str]
) -> dict[str, Any]:
    kind = card["change_kind"]
    certain = card["certain"]
    extra: int | None = None
    period = config.DAYS_PER_MONTH
    reason: str | None = None
    if kind == "min_spend_voucher" and certain.get("break_even_aov") is not None:
        # P96: a basket-size lever pays back through the basket, not through extra orders
        aov = certain["break_even_aov"]
        return {
            "applies": True,
            "basis": "aov",
            "extra_orders": None,
            "aov_now": aov["aov_now"],
            "aov_needed": aov["aov_needed"],
            "period_days": int(certain.get("days") or config.VOUCHER_DAYS),
            "reason": aov["reason"],
            "reason_text": reason_text(aov["reason"]),
        }
    if kind == "min_spend_voucher":
        extra, reason = certain.get("break_even_extra_orders"), certain.get("break_even_reason")
        period = int(certain.get("days") or config.VOUCHER_DAYS)
    elif kind in ("combo_multi", "add_on", "product_discount", "price", "flash_sale"):
        extra = certain.get("break_even_extra_orders")
        reason = certain.get("break_even_reason")
        period = _period_days(card) if kind == "product_discount" else config.DAYS_PER_MONTH
    elif kind == "gift":
        extra = (certain.get("gift") or {}).get("break_even_extra_orders")
    else:
        return {
            "extra_orders": None,
            "applies": False,
            "reason": "not_applicable",
            "reason_text": reason_text("not_applicable"),
        }
    scope = [] if kind == "min_spend_voucher" and not items else list(items)
    if (
        kind == "gift"
        and ((certain.get("gift") or {}).get("trigger") or {}).get("type") != "buy_item"
    ):
        scope = list(items)
    traffic = scope_traffic(ctx.env, scope)
    ctor = break_even_ctor(traffic, extra, period)
    out: dict[str, Any] = {
        "applies": True,
        "extra_orders": extra,
        "period_days": period,
        "reason": reason,
        "reason_text": reason_text(reason),
        **{k: v for k, v in ctor.items() if k != "reason"},
        "ctor_reason": ctor["reason"],
        "ctor_reason_text": reason_text(ctor["reason"]),
    }
    if kind == "add_on":
        out["attach"] = [
            {
                "item_id": a["item_id"],
                "attach_rate_now": a["attach_rate_now"],
                "attach_rate_break_even": a["attach_rate_break_even"],
                "extra_attaches": a["break_even_extra_attaches"],
            }
            for a in certain.get("addons") or []
        ]
    return out


def _margin(card: Mapping[str, Any]) -> tuple[float | None, float | None]:
    """``(before, after)`` margin percent of the scope, from the five numbers or the kind's own
    figures."""
    five = card.get("five_numbers")
    certain = card["certain"]
    if five:
        m = five["margin"]
        return m["pct_before"], m["pct_after"]
    kind = card["change_kind"]
    if kind == "combo_multi":
        value, base = certain.get("value_now"), certain.get("contribution_without_offer")
        before = round(base / value * 100, 1) if value and base is not None else None
        return before, certain.get("margin_pct")
    if kind == "add_on":
        return None, (certain.get("addon") or {}).get("margin_pct")
    if kind == "gift":
        gift = certain.get("gift") or {}
        return gift.get("margin_before_pct"), gift.get("margin_after_pct")
    return None, None


def _driver(
    card: Mapping[str, Any],
    ctx: BuilderContext,
    items: Sequence[str],
    dorders_p50: float | None,
) -> dict[str, Any]:
    kind = card["change_kind"]
    certain = card["certain"]
    five = card.get("five_numbers") or {}
    lift = card["predicted"]["lift"]
    metric = lift["metric"]
    # P96d: the same size scaling the money carries, so a bigger voucher shows a bigger AOV after
    scale = float(card["predicted"].get("lift_scale") or 1.0)
    p50 = lift["lift"]["p50"] * scale if metric != "none" else 0.0
    traffic = scope_traffic(ctx.env, [] if kind == "min_spend_voucher" and not items else items)
    window = ctx.env.window_days
    rows: list[dict[str, Any]] = []
    for key in DRIVERS.get(kind, ()):
        before = after = None
        unit = "vnd"
        if key == "aov":
            aov = five.get("aov") or {}
            before = aov.get("before")
            if kind == "combo_multi":
                before = certain.get("aov_shop_now")
            elif kind == "add_on":
                before = certain.get("aov_now")
            if before is not None:
                after = round(before * (1 + p50), 2) if metric == "aov" else before
        elif key == "ctor":
            unit = "pct"
            if traffic is not None and traffic.ctor is not None:
                before = round(traffic.ctor * 100, 3)
                if metric == "ctor":
                    after = round(before * (1 + p50), 3)
                elif metric in ("orders", "views", "ctr") and dorders_p50 is not None:
                    gain = dorders_p50 * window / config.DAYS_PER_MONTH
                    after = round((traffic.orders + gain) / traffic.clicks * 100, 3)
                elif metric == "aov":
                    after = before  # a basket lever does not add orders
        elif key == "orders":
            unit = "count"
            orders = (five.get("orders") or {}).get("before")
            if orders is None and kind == "gift":  # P96: the gift's own order lines
                orders = (certain.get("gift") or {}).get("total_orders")
            if orders is None and traffic is not None:
                orders = traffic.orders
            before = orders
            if orders is not None and dorders_p50 is not None:
                after = round(orders + dorders_p50 * window / config.DAYS_PER_MONTH, 1)
        elif key == "views":
            unit = "count"
            if traffic is not None and traffic.views:
                before = traffic.views
                after = round(before * (1 + p50)) if metric == "views" else before
        elif key == "ctr":
            unit = "pct"
            if traffic is not None and traffic.ctr is not None:
                before = round(traffic.ctr * 100, 3)
                after = round(before * (1 + p50), 3) if metric == "ctr" else before
        elif key == "affiliate_orders":
            unit = "count"
            before = certain.get("affiliate_orders")
        elif key == "spend":
            before, after = certain.get("spend_per_day_now"), certain.get("spend_per_day_after")
            unit = "vnd_per_day"
        elif key == "roas":
            unit = "ratio"
            before = certain.get("roas_direct")
            target = certain.get("target_roas_vs_break_even") or {}
            after = target.get("target")
        rows.append(
            {
                "key": key,
                "label": METRIC_LABELS[key],
                "unit": unit,
                "before": before,
                "after_p50": after,
            }
        )
    return {
        "metrics": rows,
        "target_metric": metric,
        "relative_lift": lift["lift"] if metric != "none" else None,
    }


def _base(
    card: Mapping[str, Any],
    tr: Translation,
    items: Sequence[str],
    driver: Mapping[str, Any],
    margin_before: float | None,
) -> dict[str, Any]:
    """P96d: the orders a version's "hôm nay" figures stand on. A shop-wide voucher reads the whole
    shop; anything else reads its products. Same scope -> same figures, so two columns that differ
    here say so instead of looking like the same baseline."""
    shop_wide = card["change_kind"] == "min_spend_voucher" and not tr.items
    scope_items = [] if shop_wide or not items else [i for i in items if i]
    aov = next((m["before"] for m in driver["metrics"] if m["key"] == "aov"), None)
    if aov is None:
        aov = ((card.get("five_numbers") or {}).get("aov") or {}).get("before")
    return {
        "scope": "product" if scope_items else "shop",
        "items": scope_items,
        "aov": aov,
        "margin_pct": margin_before,
    }


def _warnings(
    card: Mapping[str, Any],
    tr: Translation,
    cost_known: bool,
    missing_cost: list[str],
    delta_profit: Mapping[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if cost_known and delta_profit["p50"] is None and card["predicted"]["lift"]["metric"] != "none":
        out.append(
            {
                "type": "profit_unknown",
                "message": "Chưa tính được lợi nhuận dự kiến: thiếu phí hoặc giá vốn.",
            }
        )
    for b in card["floor"]["breaches"]:
        out.append({"type": "floor", **b})
    spend = card.get("spend") or {}
    if spend.get("over_cap"):
        out.append(
            {
                "type": "spend_cap",
                "spend_per_day_after": spend.get("shop_chi_per_day_after"),
                "cap": spend.get("cap"),
                "cap_rule": "daily_marketing_cap",
            }
        )
    if not cost_known:
        out.append(
            {
                "type": "cost_unknown",
                "items": missing_cost,
                "message": "Chưa có giá vốn trong Thông số shop: lợi nhuận và biên là “chưa tính”.",
            }
        )
    if card["floor"].get("unknown_skus"):
        out.append({"type": "floor_unknown", "skus": card["floor"]["unknown_skus"]})
    for note in [*tr.notes, *card.get("notes", [])]:
        out.append({"type": "note", "message": note})
    out.extend(dict(w) for w in tr.warnings)
    return out


def shape(
    card: Mapping[str, Any],
    tr: Translation,
    ctx: BuilderContext,
    *,
    index: int,
    kind: str,
    label: str,
    estimate_card: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The outcome block of one version. ``estimate_card`` carries the numbers when the saved card
    has none of its own (a variation set)."""
    numbers = estimate_card or card
    pm = numbers["predicted"]["money_per_month"]
    # P96: the bands cover the change's own days (``period``, up to 90), not a month capped at 30
    total = (pm.get("period") or pm)["total"]
    items = list(dict.fromkeys([*tr.items, *card["scope"]["product_ids"]]))
    cost_known, missing = _items_cost_known(ctx, [i for i in items if i])
    p50_orders = pm["total"]["p50"]["dorders"]  # per month: the driver and combo cost read it
    margin_before, margin_after = _margin(numbers)
    delta_profit = _band(total, "dprofit")
    orders_band = _band(total, "dorders")
    orders_note = None
    if numbers["predicted"]["lift"]["metric"] == "aov":
        # a basket-size lever moves AOV, not the number of orders
        orders_band = {"low": 0.0, "p50": 0.0, "high": 0.0}
        orders_note = "Đòn bẩy này tăng giá trị mỗi đơn, không tăng số đơn."
    basis = basis_of(numbers)
    if card["change_kind"] == "listing_hide" and basis["key"] != "insufficient":
        basis = {  # P96: the loss is the listing's own last 30 days, not an estimate
            "key": "product_history",
            "label": BASIS_LABELS["product_history"],
            "detail": "GMV và lợi nhuận 30 ngày qua của sản phẩm: mất khi ẩn sản phẩm.",
            "volume_estimate": False,
        }
    if items and all(i in ctx.reference_items for i in items if i):
        basis = {
            "key": "insufficient",
            "label": BASIS_LABELS["insufficient"],
            "detail": "Sản phẩm chưa có đơn trong kỳ: chỉ tính chi phí và hoà vốn trên một đơn mẫu "
            "theo giá hiện tại, không dự kiến số đơn hay doanh thu.",
            "volume_estimate": False,
        }
    delta_gmv = _band(total, "dgmv")
    if basis["key"] == "insufficient":  # no volume could be predicted: null, not a flat 0
        null = {"low": None, "p50": None, "high": None}
        delta_gmv, orders_band, delta_profit = dict(null), dict(null), dict(null)
    if cost_known and tr.card_kind == "variation_restructure" and delta_profit["p50"] is None:
        delta_profit = set_profit_band(delta_gmv, tr.details.get("new_variations") or [])
    if not cost_known:
        delta_profit = {"low": None, "p50": None, "high": None}
        margin_before = margin_after = None
    certain_profit = None if not cost_known else (pm.get("period") or pm)["certain"]["dprofit"]
    driver = _driver(numbers, ctx, items, p50_orders)
    return {
        "index": index,
        "kind": kind,
        "change_kind": card["change_kind"],
        "card_kind": tr.card_kind,
        "label": label,
        "ok": True,
        "refusal": None,
        "title": card["title"],
        "driver": driver,
        "base": _base(numbers, tr, items, driver, margin_before),
        "delta": {
            "gmv": delta_gmv,
            "orders": orders_band,
            "profit": delta_profit,
            "certain_profit": certain_profit,
            "orders_note": orders_note,
            # the figures above cover ``days`` days (the change's own, up to 30), not a month
            "per": "period",
            "days": pm.get("period", {}).get("days", pm["days"]),
            "per_day": _per_day(numbers, cost_known),
            "period": _period(numbers, cost_known),
            "per_order": _per_order(numbers, cost_known),
        },
        "voucher": (numbers.get("certain") or {}).get("voucher_detail"),
        "margin_before_pct": margin_before,
        "margin_after_pct": margin_after,
        "profit_status": "ok" if cost_known else "chua_tinh",
        "cost_known": cost_known,
        "cost": _cost(numbers, tr, p50_orders),
        "break_even": _break_even(numbers, ctx, items),
        "basis": basis,
        "warnings": _warnings(numbers, tr, cost_known, missing, delta_profit),
        "breach": bool(card["floor"]["breaches"])
        or bool((card.get("spend") or {}).get("over_cap")),
        "details": {**card["certain"], **tr.details},
    }


def set_profit_band(
    delta_gmv: Mapping[str, float | None], new_variations: Sequence[Mapping[str, Any]]
) -> dict[str, float | None]:
    """P96: a set's Δ profit from its own margin when the estimate card has none -- the extra GMV
    is set revenue at the margin computed for the biggest new set (``translate._variation_set``)."""
    known = [v for v in new_variations if v.get("margin_pct") is not None]
    if not known:
        return {"low": None, "p50": None, "high": None}
    rate = max(known, key=lambda v: v.get("pack_count") or 1)["margin_pct"] / 100
    return {
        k: None if delta_gmv.get(k) is None else round(float(delta_gmv[k] or 0) * rate, 2)
        for k in ("low", "p50", "high")
    }


def refused(index: int, kind: str, label: str, refusal: Mapping[str, str]) -> dict[str, Any]:
    return {
        "index": index,
        "kind": kind,
        "label": label,
        "ok": False,
        "refusal": dict(refusal),
        "warnings": [{"type": "refused", **refusal}],
    }


__all__ = [
    "BASIS_LABELS",
    "DRIVERS",
    "METRIC_LABELS",
    "REASON_TEXT",
    "basis_of",
    "reason_text",
    "refused",
    "shape",
]
