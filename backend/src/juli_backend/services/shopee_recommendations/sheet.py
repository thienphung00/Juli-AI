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
                "expected": {"daily_budget": inputs["daily_budget"]},
            }
        ]
    if kind == "ads_roas_target":
        return [
            {
                "change_kind": "roas_target",
                "target": {"campaign_id": target.get("campaign_id")},
                "expected": {"roas_target": inputs["roas_target"]},
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
            n += 1
            steps.append(_step(n, k, before.get(k), v, None))
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
        for k, v in after.items():
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
    return {
        "page": {
            "label": page.label,
            "path": page.path,
            "verified": page.verified,
            "deep_link": _link(page.path),
            "button": "Mở trang để sửa",
        },
        "steps": steps,
        "time_window": time_window or {"start": "khi bạn bấm lưu", "days": inputs.get("days")},
        "changes": changes,
        "save_hint": SAVE_HINT,
        "revert_steps": reverse,
        "readback": {
            "kinds": sorted({c["change_kind"] for c in changes}),
            "deadline_hours": 48,
            "note": "Connector đọc lại ở lần chạy kế tiếp; không thấy trong 48 giờ sẽ báo cho Ops.",
        },
    }
