"""The execution sheet of a card (p90-plan "Assisted execution"): what a person types into
Seller Centre, exactly, and the `change` payload the `executed` event carries so the
Connector's read-back (``card_events/verification.py``) can verify it.

No automated write exists: the sheet names the page, each field with its exact before ->
after, and the time window; a person clicks Shopee's own Save and marks "Đã làm". The revert
sheet is the same steps in reverse (before value).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from juli_backend.services.shopee_recommendations.kinds import spec

BASE_URL = "https://banhang.shopee.vn"
SAVE_HINT = "Juli không bấm Lưu thay bạn."
#: Seller Centre pages the Connector already opens (``fill_queue``): the new-object forms.
VOUCHER_NEW_PATH = "/portal/marketing/vouchers/new?usecase={usecase}"
COMBO_NEW_PATH = "/portal/marketing/bundle/new"
#: Kinds that create a new object in Seller Centre: the revert deletes / ends it.
NEW_OBJECT_LABEL: dict[str, str] = {
    "min_spend_voucher": "voucher",
    "review_voucher": "voucher",
    "voucher_cap": "voucher",
    "bundle_deal": "combo",
    "combo_multi": "combo",
    "add_on": "deal sốc",
    "gift": "quà tặng kèm",
    "product_discount": "chương trình giảm giá",
    "flash_sale": "Flash Sale",
    "program_registration": "chương trình Shopee",
}
#: Raw field keys the evaluators leave in ``after`` -> the label a person reads.
FIELD_LABELS: dict[str, str] = {
    "daily_budget": "Ngân sách mỗi ngày",
    "roas_target": "ROAS mục tiêu",
    "spend_per_day": "Chi tiêu mỗi ngày",
    "addon_price": "Giá mua kèm",
    "discount_pct": "Mức giảm",
    "limit_per_order": "Giới hạn mỗi đơn",
    "commission_pct": "Hoa hồng",
}
_RAW_KEY = re.compile(r"^[a-z][a-z0-9_]*$")


def _day_text(raw: Any) -> str | None:
    """``2026-12-01`` -> ``01/12/2026``; anything else -> None."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(raw or "")[:10])
    return f"{m[3]}/{m[2]}/{m[1]}" if m else None


def _period(inputs: dict[str, Any]) -> str | None:
    """The card's own dates as ``dd/mm/yyyy – dd/mm/yyyy``; None when it has none."""
    start, end = _day_text(inputs.get("start")), _day_text(inputs.get("end"))
    return f"{start} – {end}" if start and end else None


def _start_text(inputs: dict[str, Any]) -> str:
    """The card's dates when set, else "khi bạn bấm lưu"."""
    return _period(inputs) or "khi bạn bấm lưu"


def _vnd(value: Any) -> str | None:
    try:
        return f"{int(round(float(value))):,}đ".replace(",", ".")
    except (TypeError, ValueError):
        return None


def _names_of(ids: Any, names: Mapping[str, str] | None) -> str | None:
    """Product names for ``ids`` (never a raw id: an unnamed product is skipped)."""
    out = [str(names[str(i)]) for i in (ids or []) if names and names.get(str(i))]
    return ", ".join(out) or None


def _tiers_text(value: Any) -> str | None:
    """A combo's tiers as one line: "Mua 2 giảm 3 % · Mua 3 giảm 5 %"; None when unreadable."""
    rows = value if isinstance(value, list) else [value]
    parts: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        units = row.get("units") or row.get("qty")
        off = row.get("value", row.get("discount_pct"))
        if units is None or off is None:
            continue
        parts.append(f"Mua {units} giảm {off} %")
    return " · ".join(parts) or None


def _step(
    order: int,
    field: str,
    before: Any,
    after: Any,
    unit: str | None = None,
    *,
    key: str | None = None,
) -> dict[str, Any]:
    return {
        "order": order,
        "field": field,
        "key": key,
        "before": before,
        "after": after,
        "unit": unit,
        "copy": None if after is None else str(after),
    }


def _link(page_path: str | None) -> str | None:
    return None if page_path is None else BASE_URL + page_path


def _changes(
    kind: str,
    target: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    inputs: dict[str, Any],
) -> list[dict[str, Any]]:
    s = spec(kind)
    vk = s.verify_kind
    if kind == "ads_budget":
        return [
            {
                "change_kind": "daily_budget",
                "target": {"campaign_id": target.get("campaign_id")},
                "expected": {"daily_budget": inputs.get("daily_budget")}
                if not inputs.get("unlimited")
                else {"daily_budget": None, "unlimited": True},
            }
        ]
    if kind == "ads_roas_target":
        return [
            {
                "change_kind": "roas_target",
                "target": {"campaign_id": target.get("campaign_id")},
                "expected": {"roas_target": inputs.get("roas_target")}
                if inputs.get("roas_mode") != "system"
                else {"roas_target": None, "roas_mode": "system"},
            }
        ]
    if vk == "voucher":
        expected: dict[str, Any] = {}
        if inputs.get("pct") is not None:
            expected["discount_percent"] = inputs["pct"]
        elif inputs.get("value") is not None:
            expected["discount_amount"] = inputs["value"]
        for k_in, k_out in (
            ("min_spend", "min_spend"),
            ("max_value", "max_value"),
            ("quantity", "usage_limit"),
        ):
            if inputs.get(k_in) is not None:
                expected[k_out] = inputs[k_in]
        return [
            {
                "change_kind": "voucher",
                "target": {"voucher_id": target.get("voucher_id")},
                "expected": expected,
            }
        ]
    if kind == "title":
        return [
            {
                "change_kind": "title",
                "target": {"item_id": target.get("item_id")},
                "expected": {"title": after["title"]},
            }
        ]
    if kind in D13_KINDS:
        return _planned_changes(kind, target, before, after)
    if vk == "images":
        # the new image is not known beforehand: the read-back looks for the cover URL to change
        return [
            {
                "change_kind": "images",
                "target": {"item_id": target.get("item_id")},
                "expected": {"image_urls": {"changed_from": [before.get("cover_url")]}},
            }
        ]
    if vk == "price":
        out = []
        for row in after.get("skus", []):
            out.append(
                {
                    "change_kind": "price",
                    "target": {"item_id": target.get("item_id"), "sku": row["sku"]},
                    "expected": {"current_price": row["price"]},
                }
            )
        return out
    # no read-back reader yet: the event still carries the intended change under our own kind
    return [
        {
            "change_kind": kind,
            "target": {k: v for k, v in target.items() if v is not None},
            "expected": dict(after),
        }
    ]


#: The listing kinds p91 D-13 adds (their sheets, read-backs and dependencies live below).
D13_KINDS: tuple[str, ...] = (
    "description_first_line",
    "variation_restructure",
    "listing_hide",
    "listing_relist",
)


def variation_key(row: dict[str, Any]) -> dict[str, Any]:
    """The fields of one target variation the read-back compares (name, price, SKU, stock)."""
    out: dict[str, Any] = {"name": str(row["name"]).strip(), "price": row["price"]}
    if row.get("sku"):
        out["sku"] = row["sku"]
    if row.get("stock") is not None:
        out["stock"] = row["stock"]
    return out


def sorted_variations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((variation_key(r) for r in rows), key=lambda r: r["name"].casefold())


def _planned_changes(
    kind: str, target: dict[str, Any], before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    item = {"item_id": target.get("item_id")}
    if kind == "description_first_line":
        return [
            {
                "change_kind": "description_first_line",
                "target": item,
                "expected": {"first_line": after["first_line"]},
            }
        ]
    if kind == "variation_restructure":
        return [
            {
                "change_kind": "variations",
                "target": item,
                "expected": {"variations": sorted_variations(after["variations"])},
            }
        ]
    out = [
        {
            "change_kind": "listing_status",
            "target": item,
            "expected": {"status": after["status"]},
        }
    ]
    if kind == "listing_relist" and after.get("stock") is not None:
        out.append({"change_kind": "stock", "target": item, "expected": {"stock": after["stock"]}})
    return out


def _variation_line(row: dict[str, Any]) -> str:
    parts = [str(row["name"]), f"giá {int(row['price']):,}đ".replace(",", ".")]
    if row.get("sku"):
        parts.append(f"SKU {row['sku']}")
    if row.get("stock") is not None:
        parts.append(f"tồn {row['stock']}")
    return " — ".join(parts)


def _planned_steps(
    kind: str, before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    if kind == "description_first_line":
        step = _step(
            1,
            "Dòng đầu của Mô tả sản phẩm (giữ nguyên phần còn lại)",
            before.get("first_line"),
            after.get("first_line"),
            "ký tự",
            key="first_line",
        )
        return [step]
    if kind == "variation_restructure":
        old = {str(r.get("name", "")).strip().casefold(): r for r in before.get("variations", [])}
        steps = []
        for n, row in enumerate(after["variations"], 1):
            was = old.get(str(row["name"]).strip().casefold())
            step = _step(n, f"Phân loại {n}", _variation_line(was) if was else None, None)
            step["after"] = _variation_line(row)
            step["copy"] = str(row["name"])
            steps.append(step)
        hide = after.get("hide_items") or []
        if hide:
            steps.append(
                _step(
                    len(steps) + 1,
                    "Sau khi xong: ẩn (không xoá) các sản phẩm đã gộp",
                    None,
                    ", ".join(str(i) for i in hide),
                )
            )
        return steps
    if kind == "listing_hide":
        return [_step(1, "Trạng thái sản phẩm", "Đang hiển thị", "Ẩn (không xoá)")]
    steps = [_step(1, "Trạng thái sản phẩm", "Đang ẩn", "Hiển thị lại")]
    if after.get("stock") is not None:
        steps.append(_step(2, "Số lượng tồn", before.get("stock"), after["stock"], "cái"))
    return steps


_ONE_OF_ONE = re.compile(r"\s*\(ảnh 1 trong 1\)")
_RAW_IMAGE_ID = re.compile(r"^[a-z]{2}-\d+-[0-9a-z]+-[0-9a-z]+$", re.IGNORECASE)


def _cover_before(text: Any) -> Any:
    """ "Ảnh bìa hiện tại (ảnh 1 trong 1): url" -> without "(ảnh 1 trong 1)": the listing's image
    count is the Connector's read of the cover alone, so it says nothing about the other images."""
    return _ONE_OF_ONE.sub("", text) if isinstance(text, str) else text


def _cover_after(after: dict[str, Any]) -> Any:
    """The new cover in words: the banner's text, never a raw image id."""
    text = after.get("text")
    if isinstance(text, str) and text and not _RAW_IMAGE_ID.match(text.strip()):
        return text
    banner = after.get("banner")
    if isinstance(banner, dict):
        return "Ảnh bìa mới (tải từ trình tạo banner)"
    return None if not text or _RAW_IMAGE_ID.match(str(text).strip()) else text


def _listing_steps(
    kind: str, before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    if kind in D13_KINDS:
        return _planned_steps(kind, before, after)
    if kind == "title":
        return [
            _step(1, "Tên sản phẩm", before.get("title"), after.get("title"), "ký tự", key="title")
        ]
    if kind == "keyword":
        steps = [
            _step(1, "Thêm vào từ khoá Chính", None, after.get("promote")),
        ]
        if after.get("demote"):
            steps.append(_step(2, "Chuyển xuống từ khoá Phụ", after.get("demote"), None))
        return steps
    cover = _step(
        1,
        "Ảnh bìa (ảnh đầu tiên)",
        _cover_before(before.get("text")),
        _cover_after(after),
        key="cover",
    )
    if kind == "price_display":
        cover["copy"] = after.get("line")
    else:
        cover["copy"] = None
    return [cover]


def _price_label(base: str, name: str | None, n: int, total: int) -> str:
    label = f"{base} — {name}" if name else base
    return f"{label} · phân loại {n}" if total > 1 else label


def _voucher_steps(
    before: dict[str, Any], after: dict[str, Any], inputs: dict[str, Any], items: Sequence[str]
) -> list[dict[str, Any]]:
    scope = "Voucher sản phẩm" if items else "Voucher toàn shop"
    pct, value = after.get("pct"), after.get("value")
    off: str | None
    if pct is not None:
        cap = _vnd(after.get("max_value"))
        off = f"{pct} %" + (f" (tối đa {cap})" if cap else "")
    else:
        off = _vnd(value)
    period = _period(inputs) or (f"{after['days']} ngày" if after.get("days") else None)
    rows: list[tuple[str, str, Any, str | None]] = [
        ("type", "Loại voucher", f"{scope} · Khuyến mãi", None),
        ("name", "Tên chương trình", inputs.get("name"), None),
        ("discount", "Mức giảm", off, None),
        ("min_spend", "Đơn tối thiểu", after.get("min_spend"), "VND"),
        ("quantity", "Tổng lượt sử dụng", after.get("quantity"), "lượt"),
        ("per_user", "Mỗi người mua dùng tối đa", inputs.get("per_user_limit") or 1, "lượt"),
        ("period", "Thời gian sử dụng", period, None),
        (
            "display",
            "Hiển thị",
            "Chia sẻ qua mã voucher" if items else "Hiển thị nhiều nơi",
            None,
        ),
    ]
    return [
        _step(n, field, before.get(key), v, unit, key=key)
        for n, (key, field, v, unit) in enumerate(rows, 1)
        if v is not None or key == "name"
    ]


def _combo_steps(
    before: dict[str, Any],
    after: dict[str, Any],
    inputs: dict[str, Any],
    names: Mapping[str, str] | None,
    items: Sequence[str],
) -> list[dict[str, Any]]:
    tiers = _tiers_text(inputs.get("tiers")) or _tiers_text(after.get("tiers"))
    kind = {"pct": "Giảm theo %", "amount": "Giảm theo số tiền", "special": "Giá đặc biệt"}.get(
        str(inputs.get("discount_type") or "pct")
    )
    rows: list[tuple[str, str, Any, str | None]] = [
        ("name", "Tên combo", inputs.get("name"), None),
        ("type", "Loại combo", kind, None),
        ("products", "Sản phẩm trong combo", _names_of(items, names), None),
    ]
    # the evaluator may already carry labelled lines ("Mức ưu đãi 1"): keep them as they are
    labelled = [
        (k, v)
        for k, v in after.items()
        if not _RAW_KEY.match(str(k)) and not isinstance(v, (list, dict))
    ]
    if labelled:
        rows += [(f"line:{k}", str(k), v, None) for k, v in labelled]
    elif tiers:
        rows.append(("tiers", "Mức ưu đãi", tiers, None))
    if inputs.get("limit_per_buyer") is not None:
        rows.append(("limit", "Giới hạn mua mỗi người", inputs["limit_per_buyer"], "cái"))
    rows.append(("period", "Thời gian", _period(inputs), None))
    return [
        _step(n, field, before.get(key), v, unit, key=key)
        for n, (key, field, v, unit) in enumerate(rows, 1)
        if v is not None
    ]


def _add_on_steps(
    kind: str,
    target: dict[str, Any],
    after: dict[str, Any],
    inputs: dict[str, Any],
    names: Mapping[str, str] | None,
) -> list[dict[str, Any]]:
    main = _names_of([target.get("item_id")], names)
    rows: list[tuple[str, str, Any, str | None]] = [
        ("name", "Tên chương trình", inputs.get("name"), None),
        ("main", "Sản phẩm chính", main, None),
    ]
    addons = [a for a in after.get("addons") or [] if isinstance(a, dict)]
    if kind == "gift":
        gift = inputs.get("gift_item") or inputs.get("gift")
        rows.append(("gift", "Quà tặng", _names_of([gift], names) or inputs.get("gift"), None))
        rows.append(("min_spend", "Đơn tối thiểu nhận quà", inputs.get("min_spend"), "VND"))
    else:
        rows.append(
            (
                "addon",
                "Sản phẩm mua kèm",
                _names_of(
                    [a.get("item_id") for a in addons] or [after.get("addon_item_id")], names
                ),
                None,
            )
        )
        rows.append(("addon_price", "Giá mua kèm", after.get("addon_price"), "VND"))
        rows.append(("discount_pct", "Mức giảm", after.get("discount_pct"), "%"))
        limits = [a.get("limit_per_order") for a in addons if a.get("limit_per_order")]
        rows.append(("limit", "Giới hạn mỗi đơn", limits[0] if limits else None, "cái"))
    rows.append(("period", "Thời gian", _period(inputs), None))
    return [
        _step(n, field, None, v, unit, key=key)
        for n, (key, field, v, unit) in enumerate(rows, 1)
        if v is not None
    ]


def _price_steps(
    kind: str,
    target: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    inputs: dict[str, Any],
    names: Mapping[str, str] | None,
) -> list[dict[str, Any]]:
    name = _names_of([target.get("item_id")], names)
    b_rows = {r["sku"]: r["price"] for r in before.get("skus", [])}
    rows = after.get("skus", [])
    steps: list[dict[str, Any]] = []
    if kind == "product_discount":
        steps.append(_step(1, "Tên chương trình", None, inputs.get("name"), key="name"))
        if not inputs.get("name"):
            steps.pop()
    for i, row in enumerate(rows, 1):
        steps.append(
            _step(
                len(steps) + 1,
                _price_label("Giá bán", name, i, len(rows)),
                b_rows.get(row["sku"]),
                row["price"],
                "VND",
                key=f"price:{row['sku']}",
            )
        )
    extra: list[tuple[str, str, Any, str | None]] = []
    if kind in ("product_discount", "flash_sale", "program_registration"):
        extra = [
            (
                "discount_pct",
                "Mức giảm",
                after.get("discount_pct") or inputs.get("discount_pct"),
                "%",
            ),
            ("units", "Số lượng suất", inputs.get("units") or after.get("units"), "cái"),
            (
                "limit",
                "Giới hạn mua mỗi người",
                inputs.get("limit_per_buyer") or inputs.get("per_user_limit"),
                "cái",
            ),
            ("period", "Thời gian", _period(inputs), None),
        ]
    for key, field, v, unit in extra:
        if v is not None:
            steps.append(_step(len(steps) + 1, field, None, v, unit, key=key))
    return steps


def _ads_steps(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for k, v in after.items():
        if isinstance(v, (list, dict)) or k not in FIELD_LABELS:
            continue
        unit = "VND" if k in ("daily_budget", "spend_per_day") else None
        steps.append(_step(len(steps) + 1, FIELD_LABELS[k], before.get(k), v, unit, key=k))
    return steps


def _generic_steps(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """The leftover kinds (listing combo, new listing, ...): lines the evaluator already labelled
    keep their text; a raw key is translated or left out, never shown."""
    text_keys = {k for k, v in after.items() if not isinstance(v, (list, dict))}
    steps: list[dict[str, Any]] = []
    for k, v in after.items():
        label = str(k)
        if isinstance(v, (list, dict)):
            # Structured value (combo `tiers` [{units, value}]): a step only when no text line
            # carries the tiers already, and then as text -- never a raw list (React #31).
            if text_keys:
                continue
            v = _tiers_text(v)
            if not v:
                continue
        if _RAW_KEY.match(label):
            if label not in FIELD_LABELS:
                continue
            label = FIELD_LABELS[label]
        steps.append(_step(len(steps) + 1, label, before.get(k), v, None, key=str(k)))
    return steps


def _revert_of(
    kind: str, steps: list[dict[str, Any]], after: dict[str, Any], inputs: dict[str, Any]
) -> list[dict[str, Any]]:
    """The way back. A NEW object (voucher, combo, deal sốc, shop programme) is deleted / ended
    by name; an edited field goes back to its before value (None = not known: the card page
    says which field and offers the Connector's captured value)."""
    label = NEW_OBJECT_LABEL.get(kind)
    if label is not None:
        name = next((s["after"] for s in steps if s.get("key") == "name" and s["after"]), None)
        field = f"Xoá hoặc kết thúc {label}" + (f' "{name}"' if name else "")
        return [
            {
                **_step(1, field, None, None, key="remove"),
                "action": f"Trên Seller Centre, xoá hoặc kết thúc {label} này.",
            }
        ]
    return [
        {
            **st,
            "before": st["after"],
            "after": st["before"],
            "copy": None if st["before"] is None else str(st["before"]),
        }
        for st in steps
    ]


def build_sheet(
    kind: str,
    target: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    inputs: dict[str, Any],
    *,
    time_window: dict[str, Any] | None = None,
    children: list[dict[str, Any]] | None = None,
    names: Mapping[str, str] | None = None,
    items: Sequence[str] = (),
) -> dict[str, Any]:
    s = spec(kind)
    steps: list[dict[str, Any]] = []
    if kind in ("product_discount", "price", "flash_sale", "program_registration"):
        steps = _price_steps(kind, target, before, after, inputs, names)
    elif s.family == "voucher":
        steps = _voucher_steps(before, after, inputs, items)
    elif s.family == "ads":
        steps = _ads_steps(before, after)
        if not steps:
            steps = [_step(1, s.label, None, None, key="ads")]
    elif s.family == "listing":
        steps = _listing_steps(kind, before, after)
    elif s.family == "affiliate":
        steps = [
            _step(
                1,
                "Hoa hồng chiến dịch mở rộng",
                before.get("commission_pct"),
                after.get("commission_pct"),
                "%",
                key="commission_pct",
            )
        ]
    elif kind == "mega_sale":
        for n, child in enumerate(children or [], 1):
            steps.append(
                {
                    "order": n,
                    "field": str(child["label"]),
                    "key": None,
                    "before": None,
                    "after": child.get("summary"),
                    "child_card_id": child.get("card_id"),
                    "page": child.get("page"),
                    "starts": child.get("starts"),
                    "copy": None,
                    "unit": None,
                }
            )
    elif kind in ("add_on", "gift"):
        steps = _add_on_steps(kind, target, after, inputs, names)
    elif kind == "bundle_deal":
        steps = _combo_steps(before, after, inputs, names, items)
    else:  # combo / listing combo
        steps = _generic_steps(before, after)
    changes = (
        _changes(kind, target, before, after, inputs)
        if kind != "mega_sale"
        else [c for ch in (children or []) for c in ch.get("changes", [])]
    )
    page = s.page
    reverse = _revert_of(kind, steps, after, inputs)
    item_link = None
    if page.item_path and target.get("item_id"):
        item_link = _link(page.item_path.format(item_id=target["item_id"]))
    deep = _link(page.path)
    if s.family == "voucher":
        deep = _link(VOUCHER_NEW_PATH.format(usecase=2 if items else 1))
    elif kind in ("bundle_deal", "combo_multi"):
        deep = _link(COMBO_NEW_PATH)
    elif item_link is not None:
        deep = item_link  # the product's own edit page, not the product list
    sheet_page = {
        "label": page.label,
        "path": page.path,
        "verified": page.verified,
        "deep_link": deep,
        "button": "Mở trang",
    }
    if page.item_path:
        sheet_page["item_deep_link"] = item_link
        sheet_page["item_link_verified"] = item_link is not None  # the page the Connector opens
    depends = [str(r) for r in (inputs.get("depends_on") or [])]
    period = _period(inputs)
    window = time_window or {
        "start": period or _start_text(inputs),
        "days": None if period else inputs.get("days"),
    }
    sheet: dict[str, Any] = {
        "page": sheet_page,
        "dependencies": [{"ref": r, "text": f"Chỉ làm sau khi {r} đã chạy xong."} for r in depends],
        "steps": steps,
        "time_window": window,
        "changes": changes,
        "save_hint": SAVE_HINT,
        "revert_steps": reverse,
        "readback": {
            "kinds": sorted({c["change_kind"] for c in changes}),
            "deadline_hours": 48,
            "note": "Thay đổi này nằm trong bộ từ khoá của Juli nên không có bước đọc lại tự động."
            if kind == "keyword"
            else "Connector chưa đọc được mô tả sản phẩm nên bước này bạn xác nhận bằng tay."
            if kind == "description_first_line"
            else "Connector đọc lại ở lần chạy kế tiếp; không thấy trong 48 giờ sẽ báo cho Ops.",
        },
    }
    if kind in NEW_OBJECT_LABEL:
        sheet["new_object"] = NEW_OBJECT_LABEL[kind]
    return sheet


# --------------------------------------------------------------- before values (Connector job)

_BEFORE_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "name", "product_name"),
    "first_line": ("first_line", "description_first_line", "description"),
    "daily_budget": ("daily_budget", "budget"),
    "roas_target": ("roas_target", "roas"),
    "commission_pct": ("commission_pct", "commission", "rate"),
    "cover": ("cover", "cover_url", "image", "images"),
}


def job_before_values(jobs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The Connector's captured ``before_values`` of a card's fill jobs, merged: the FIRST job
    holding a key wins (it saw the value before Juli wrote). Accepts ``{key: value}`` or
    ``[{key, value}]`` per job; read from the job's own ``before_values`` or its payload."""
    out: dict[str, Any] = {}
    for job in jobs:
        raw = job.get("before_values")
        if raw is None:
            raw = (job.get("payload") or {}).get("before_values")
        if isinstance(raw, Mapping):
            for k, v in raw.items():
                if v is not None:
                    out.setdefault(str(k), v)
        elif isinstance(raw, list):
            for row in raw:
                if isinstance(row, Mapping) and row.get("key") is not None:
                    if row.get("value") is not None:
                        out.setdefault(str(row["key"]), row["value"])
    return out


def with_job_before(sheet: dict[str, Any], jobs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The sheet with each unknown "before" filled from the Connector's capture (priority: the
    card's own stored before, then the capture; else it stays None and the revert names the
    field). Each step gets ``before_source`` = ``card`` / ``connector`` / None. Pure: returns a
    copy."""
    captured = job_before_values(jobs)
    out = {**sheet}
    new_object = bool(sheet.get("new_object"))
    steps: list[dict[str, Any]] = []
    revert = [dict(r) for r in sheet.get("revert_steps") or []]
    for n, raw in enumerate(sheet.get("steps") or []):
        st = dict(raw)
        source = "card" if st.get("before") is not None else None
        if st.get("before") is None and not new_object:
            key = str(st.get("key") or "")
            for name in (key, *_BEFORE_ALIASES.get(key, ())):
                if captured.get(name) is not None and key:
                    st["before"] = captured[name]
                    if n < len(revert):
                        revert[n]["after"] = captured[name]
                        revert[n]["copy"] = str(captured[name])
                    source = "connector"
                    break
        st["before_source"] = source
        if n < len(revert) and not new_object:
            revert[n]["before_source"] = source
        steps.append(st)
    out["steps"] = steps
    out["revert_steps"] = revert
    out["unknown_before"] = (
        []
        if new_object
        else [r["field"] for r in revert if r.get("after") is None and r.get("key")]
    )
    return out
