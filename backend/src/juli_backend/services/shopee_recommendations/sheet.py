"""The execution sheet of a card (p90-plan "Assisted execution"): what a person types into
Seller Centre, exactly, and the `change` payload the `executed` event carries so the
Connector's read-back (``card_events/verification.py``) can verify it.

No automated write exists: the sheet names the page, each field with its exact before ->
after, and the time window; a person clicks Shopee's own Save and marks "Đã làm". The revert
sheet is the same steps in reverse (before value).
"""

from __future__ import annotations

from typing import Any

from juli_backend.services.shopee_recommendations.kinds import spec

BASE_URL = "https://banhang.shopee.vn"
SAVE_HINT = "Bấm nút Lưu / Áp dụng / Xác nhận của chính Shopee; Juli không bấm thay bạn."


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
    order: int, field: str, before: Any, after: Any, unit: str | None = None
) -> dict[str, Any]:
    return {
        "order": order,
        "field": field,
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


def _listing_steps(
    kind: str, before: dict[str, Any], after: dict[str, Any]
) -> list[dict[str, Any]]:
    if kind in D13_KINDS:
        return _planned_steps(kind, before, after)
    if kind == "title":
        return [_step(1, "Tên sản phẩm", before.get("title"), after.get("title"), "ký tự")]
    if kind == "keyword":
        steps = [
            _step(1, "Thêm vào từ khoá Chính", None, after.get("promote")),
        ]
        if after.get("demote"):
            steps.append(_step(2, "Chuyển xuống từ khoá Phụ", after.get("demote"), None))
        return steps
    cover = _step(1, "Ảnh bìa (ảnh đầu tiên)", before.get("text"), after.get("text"))
    if kind == "price_display":
        cover["copy"] = after.get("line")
    else:
        cover["copy"] = None
    return [cover]


def build_sheet(
    kind: str,
    target: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    inputs: dict[str, Any],
    *,
    time_window: dict[str, Any] | None = None,
    children: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    s = spec(kind)
    steps: list[dict[str, Any]] = []
    n = 0
    if kind in ("product_discount", "price", "flash_sale", "program_registration"):
        b_rows = {r["sku"]: r["price"] for r in before.get("skus", [])}
        for row in after.get("skus", []):
            n += 1
            steps.append(
                _step(n, f"Giá bán — {row['sku']}", b_rows.get(row["sku"]), row["price"], "VND")
            )
        if inputs.get("units") is not None:
            n += 1
            steps.append(_step(n, "Số lượng suất", None, inputs["units"], "cái"))
    elif s.family == "voucher":
        for field, key, unit in (
            ("Giá trị giảm (VND)", "value", "VND"),
            ("Giảm theo % đơn", "pct", "%"),
            ("Mức giảm tối đa", "max_value", "VND"),
            ("Đơn tối thiểu", "min_spend", "VND"),
            ("Số lượng voucher", "quantity", "cái"),
        ):
            if after.get(key) is not None or before.get(key) is not None:
                n += 1
                steps.append(_step(n, field, before.get(key), after.get(key), unit))
        n += 1
        steps.append(_step(n, "Thời gian áp dụng", None, f"{after.get('days')} ngày", None))
    elif s.family == "ads":
        for k, v in after.items():
            if isinstance(v, (list, dict)):
                continue
            n += 1
            steps.append(_step(n, k, before.get(k), v, None))
    elif s.family == "listing":
        steps = _listing_steps(kind, before, after)
        n = len(steps)
    elif s.family == "affiliate":
        n += 1
        steps.append(
            _step(n, "Hoa hồng (%)", before.get("commission_pct"), after.get("commission_pct"), "%")
        )
    elif kind == "mega_sale":
        for child in children or []:
            n += 1
            steps.append(
                {
                    "order": n,
                    "field": f"{child['label']} ({child['change_kind']})",
                    "before": None,
                    "after": child.get("summary"),
                    "child_card_id": child.get("card_id"),
                    "page": child.get("page"),
                    "starts": child.get("starts"),
                    "copy": None,
                    "unit": None,
                }
            )
    else:  # combo
        text_keys = {k for k, v in after.items() if not isinstance(v, (list, dict))}
        for k, v in after.items():
            if isinstance(v, (list, dict)):
                # Structured value (combo `tiers` [{units, value}]): a step only when no text line
                # carries the tiers already, and then as text -- never a raw list (React #31).
                if text_keys:
                    continue
                v = _tiers_text(v)
                if not v:
                    continue
            n += 1
            steps.append(_step(n, k, before.get(k), v, None))
    changes = (
        _changes(kind, target, before, after, inputs)
        if kind != "mega_sale"
        else [c for ch in (children or []) for c in ch.get("changes", [])]
    )
    page = s.page
    reverse = [
        {
            **st,
            "before": st["after"],
            "after": st["before"],
            "copy": None if st["before"] is None else str(st["before"]),
        }
        for st in steps
    ]
    item_link = None
    if page.item_path and target.get("item_id"):
        item_link = _link(page.item_path.format(item_id=target["item_id"]))
    sheet_page = {
        "label": page.label,
        "path": page.path,
        "verified": page.verified,
        "deep_link": _link(page.path),
        "button": "Mở trang để sửa",
    }
    if page.item_path:
        # the item's own page: the shape is not recon-verified yet (kinds.Page.item_path)
        sheet_page["item_deep_link"] = item_link
        sheet_page["item_link_verified"] = False
    depends = [str(r) for r in (inputs.get("depends_on") or [])]
    return {
        "page": sheet_page,
        "dependencies": [{"ref": r, "text": f"Chỉ làm sau khi {r} đã chạy xong."} for r in depends],
        "steps": steps,
        "time_window": time_window or {"start": "khi bạn bấm lưu", "days": inputs.get("days")},
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
