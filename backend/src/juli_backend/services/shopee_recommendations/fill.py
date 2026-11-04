"""What the Connector may put into a Seller Centre edit page for one approved card (p91 D-13).

The Demo / Ops button "Điền bằng Connector" opens the product's edit page with only the card's
code in the address (``#juli-fill=JC-2611-0007``). The Connector -- paired with the shop, on its
pilot list, flag ``fill_listing`` on -- asks for that code here and gets the approved text. It
types the text into the title / first line of the description, highlights the fields and shows
"Juli đã điền — kiểm tra rồi bấm Lưu của Shopee". It never clicks Save / Cập nhật / Xác nhận /
Ẩn: a person does, and marks "Đã làm".

Nothing here reads Seller Centre; the answer is the card's own approved sheet: product title /
description text, the cover image's address, the steps. No buyer data.

Server-side kill switch: environment ``CONNECTOR_FILL_LISTING`` (default off).
"""

from __future__ import annotations

import os
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shop_proposals import STATUS_APPROVED, ShopProposal
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_recommendations import codes, config, service, store

ENV_FLAG = "CONNECTOR_FILL_LISTING"
ERROR_DISABLED = "fill_disabled"
ERROR_BAD_CODE = "fill_bad_code"
ERROR_UNKNOWN = "fill_unknown_card"
ERROR_STATE = "fill_not_approved"
ERROR_KIND = "fill_not_supported"

#: change kind -> what the Connector does with it
FIELD_KINDS = ("title", "description_first_line")
PAGE_KINDS = ("cover_image", "variation_restructure", "listing_hide", "listing_relist")
FIELDS: dict[str, dict[str, Any]] = {
    "title": {
        "key": "title",
        "label": "Tên sản phẩm",
        "mode": "replace",
        "max_chars": config.MAX_TITLE_CHARS,
    },
    "description_first_line": {
        "key": "description_first_line",
        "label": "Mô tả sản phẩm",
        "mode": "first_line",
        "max_chars": 500,
    },
}
_HTTPS = re.compile(r"^https://[^\s]+$", re.IGNORECASE)


def enabled() -> bool:
    return os.environ.get(ENV_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def _expected(sheet: dict[str, Any], kind: str) -> dict[str, Any]:
    wanted = {"title": "title", "description_first_line": "description_first_line"}[kind]
    for change in sheet.get("changes") or []:
        if change.get("change_kind") == wanted:
            return dict(change.get("expected") or {})
    return {}


async def fill_request(session: AsyncSession, shop_id: uuid.UUID, code: str) -> dict[str, Any]:
    """The fill request for an approved card of the shop; raises :class:`ProposalError`."""
    if not enabled():
        raise ProposalError(ERROR_DISABLED, 404)
    parsed = codes.parse_code(code)
    if parsed is None or parsed[1] is not None:
        raise ProposalError(ERROR_BAD_CODE, 422)
    p = await session.scalar(
        select(ShopProposal).where(ShopProposal.shop_id == shop_id, ShopProposal.code == parsed[0])
    )
    card = await store.card_payload(session, shop_id, p.id) if p is not None else None
    if p is None or card is None:
        raise ProposalError(ERROR_UNKNOWN, 404)
    kind = str(card.get("change_kind"))
    if kind not in FIELD_KINDS + PAGE_KINDS:
        raise ProposalError(ERROR_KIND, 422, f"{kind} is not filled by the Connector")
    if p.status != STATUS_APPROVED:
        raise ProposalError(ERROR_STATE, 409, f"a {p.status} card is not filled")
    approved = await service._approved_with(session, shop_id, p.id)
    sheet = dict((approved or {}).get("execution_sheet") or card["execution_sheet"])
    item = (card["scope"].get("product_ids") or [None])[0]
    fields: list[dict[str, Any]] = []
    if kind in FIELD_KINDS:
        key = "title" if kind == "title" else "first_line"
        value = str(_expected(sheet, kind).get(key) or "").strip()
        if not value or len(value) > int(FIELDS[kind]["max_chars"]):
            raise ProposalError(ERROR_KIND, 422, "the approved text cannot be filled")
        fields.append({**FIELDS[kind], "value": value})
    downloads = [
        {"label": str(d.get("label") or "Tải ảnh"), "url": d["url"]}
        for d in sheet.get("downloads") or []
        if isinstance(d.get("url"), str) and _HTTPS.match(d["url"])
    ]
    steps = [
        {
            "order": s.get("order"),
            "field": s.get("field"),
            "after": None if s.get("after") is None else str(s["after"]),
            "copy": s.get("copy"),
        }
        for s in sheet.get("steps") or []
    ]
    return {
        "code": p.code,
        "card_id": str(p.id),
        "item_id": str(item) if item is not None else None,
        "change_kind": kind,
        "title": card.get("title"),
        "fields": fields,
        "downloads": downloads,
        "steps": steps,
        "dependencies": [str(d.get("ref")) for d in sheet.get("dependencies") or []],
        "checklist": steps if kind == "variation_restructure" else [],
        "page_only": kind in ("listing_hide", "listing_relist"),
    }
