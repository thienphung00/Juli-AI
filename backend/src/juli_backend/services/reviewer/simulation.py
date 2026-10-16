"""The simulated Duyệt → Thực thi a partner reviewer walks (P32-A, D42.4).

Pure: given the card exactly as ``GET /v1/demo/decisions/{id}`` serves it, say
what a real approval and execution would send (D13: title / description through
``update_product_listing``, a cover image through ``upload_product_image`` then
the listing edit, promotions never written by Juli). Nothing here touches the
database, a queue or TikTok; the route writes only the audit row.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

Step = Literal["approve", "execute"]

#: ``integrations.tiktok.constants.product_edit_path("{product_id}")`` -- spelled
#: out so this module imports no TikTok code at all (a unit test pins the two
#: equal).
PRODUCT_EDIT_PATH = "/product/202309/products/{product_id}"

SIMULATED_LABEL = "Mô phỏng · không gửi tới TikTok"
NOTE_DRAFT_AFTER_APPROVAL = "Juli soạn nội dung mới sau khi duyệt"
_STEP_LABELS = (("approve", "Duyệt"), ("execute", "Thực thi"))

#: P41 (D47.7, owner 2026-10-16): one short line per executor, no endpoint or
#: method name -- the label is the single "simulation" disclaimer. Mirrored in
#: apps/demo/src/lib/reviewer/copy.ts `REVIEWER_SIMULATION_NOTES`.
_NOTES: Mapping[str, str] = {
    "juli": (
        "Với shop thật, Juli ghi thay đổi này lên TikTok Shop sau khi bạn xác nhận, "
        "rồi đo ở ngày 7 và 14."
    ),
    "juli_with_photo": (
        "Với shop thật, Juli đổi ảnh bìa trên TikTok Shop sau khi bạn gửi ảnh và xác nhận, "
        "rồi đo ở ngày 7 và 14."
    ),
    "juli_drafts": (
        "Với shop thật, Juli soạn kịch bản, bạn quay và đăng; Juli không ghi gì lên TikTok, "
        "chỉ đo ở ngày 7 và 14."
    ),
    "seller_center": (
        "Bạn tự áp dụng trên Seller Center; Juli không ghi gì lên TikTok, chỉ đo ở ngày 7 và 14."
    ),
}
#: The "Sau" cell when the card has no proposal yet, per executor (P41).
_AFTER_DEFAULT: Mapping[str, str] = {
    "juli": NOTE_DRAFT_AFTER_APPROVAL,
    "juli_with_photo": "Ảnh mới bạn gửi, sau khi Juli kiểm tra",
    "juli_drafts": "Juli soạn kịch bản sau khi duyệt",
    "seller_center": "Bạn áp dụng trên Seller Center",
}


def _request(executor: str, field: str) -> dict[str, Any] | None:
    """The TikTok write a real execution would make (D13); None for promotions."""
    path = PRODUCT_EDIT_PATH
    if executor == "juli":
        return {
            "method": "PUT",
            "path": path,
            "operation": "update_product_listing",
            "fields": [field],
        }
    if executor == "juli_with_photo":
        return {
            "method": "PUT",
            "path": path,
            "operation": "upload_product_image + update_product_listing",
            "fields": [field],
        }
    return None


def simulate(card_item: Mapping[str, Any], step: Step) -> dict[str, Any]:
    """The simulated response for one card (contract p32-reviewer-access.md §4)."""
    recommendation = card_item.get("recommendation") or {}
    card = recommendation.get("card") or {}
    diagnosis = recommendation.get("diagnosis") or {}
    lever = card.get("lever") or {}
    executor = str(lever.get("executor") or "seller_center")
    change_fields = card.get("change_fields") or []
    first_field = str(change_fields[0].get("field")) if change_fields else str(lever.get("code"))
    proposals = {str(p.get("field")): p for p in card.get("before_after") or []}
    fields = []
    for item in change_fields:
        code = str(item.get("field"))
        proposal = proposals.get(code) or {}
        fields.append(
            {
                "field": code,
                "label": str(item.get("label") or code),
                "before": proposal.get("before"),
                "after": proposal.get("after")
                or _AFTER_DEFAULT.get(executor, NOTE_DRAFT_AFTER_APPROVAL),
            }
        )
    done = {"approve"} if step == "approve" else {"approve", "execute"}
    return {
        "simulated": True,
        "step": step,
        "action_card_id": str(card_item.get("id")),
        "label": SIMULATED_LABEL,
        "steps": [{"key": key, "label": label, "done": key in done} for key, label in _STEP_LABELS],
        "change": {
            "executor": executor,
            "lever": {"code": lever.get("code"), "label": lever.get("label")},
            "product": {
                "title": card.get("product_title") or diagnosis.get("product_title"),
                "tiktok_product_id": diagnosis.get("tiktok_product_id"),
            },
            "request": _request(executor, first_field),
            "fields": fields,
            "note": _NOTES.get(executor, _NOTES["seller_center"]),
        },
        "enqueued": False,
        "tiktok_write": False,
    }


__all__ = ["NOTE_DRAFT_AFTER_APPROVAL", "SIMULATED_LABEL", "Step", "simulate"]
