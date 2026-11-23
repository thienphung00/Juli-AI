"""The fill queue (P97 D85.6): an approval queues one job per page the Connector must open.

``enqueue_for_approval`` is called by ``service._decide`` after a card version is approved and by
the group approval (T4). It turns the approved card into plain job rows (``shopee_fill_jobs``):
what the Connector types, validated here, and where (a Seller Centre path). The Connector polls
``GET /v1/ingest/fill-jobs`` for its token's shop only, opens the page with ``#juli-fill=<job id>``,
types, highlights and reports. The person presses Shopee's own save. Nothing here talks to Shopee.

Kinds filled: ``title`` / ``description_first_line`` (product edit page), ``voucher`` (new shop or
product voucher), ``ads_edit`` (budget / ROAS pencils of one campaign), ``affiliate_commission``
(bulk edit of the open campaign's commission), ``combo`` (new Combo Khuyến Mãi: type, tiers "Mua N",
order limit, name, dates, product list; D85.15). A combo saved as a fixed basket (``combo_multi``,
legacy) is not filled: its job is failed with a Vietnamese reason. Read-back of a combo stays
``executed_no_readback`` (no bundle list reader exists).

Server-side kill switch: ``CONNECTOR_FILL_LISTING`` (off: nothing is queued or served).

More than one computer (batch-1118e R7, migration 135): a poll claims the open jobs for its token
(``claimed_by_token_id``, ``lease_until`` = now + ``connector_state.FILL_LEASE``) in one
``UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)``. A job another live token holds
under an unexpired lease is not served, and its report is refused (409 ``fill_job_leased``). The
holder's poll and reports extend the lease; an expired lease, or one held by a revoked, superseded
or expired token, is free.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import IngestToken, PlatformDailyMetric
from juli_backend.models.platform_data import PlatformPromotion
from juli_backend.models.shop_proposals import (
    STATUS_APPROVED,
    STATUS_EXECUTED,
    STATUS_PLANNED,
    ShopProposal,
    ShopProposalApproval,
)
from juli_backend.models.shopee_fill import (
    OPEN_STATUSES,
    STATUS_CANCELLED,
    STATUS_CAPTURED,
    STATUS_FAILED,
    STATUS_FILLED,
    STATUS_OPENED,
    STATUS_QUEUED,
    STATUS_SAVED,
    ShopeeFillJob,
)
from juli_backend.services.shop_proposals.cycle import ProposalError
from juli_backend.services.shopee_recommendations import codes, config, store, versions
from juli_backend.services.shopee_recommendations.connector_state import FILL_LEASE

logger = logging.getLogger(__name__)

ENV_FLAG = "CONNECTOR_FILL_LISTING"  # same switch as fill.py (not imported: fill imports service)
_REF = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ERROR_JOB_UNKNOWN = "fill_job_unknown"
ERROR_JOB_STATE = "fill_job_state"
ERROR_JOB_BAD = "fill_job_bad"
#: R7: another computer holds the job under a live lease.
ERROR_JOB_LEASED = "fill_job_leased"

MIN_DAILY_BUDGET = 100_000
MAX_PRODUCTS = 100
MAX_VOUCHER_NAME = 100
ICT = timedelta(hours=7)
_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

#: change kinds this queue fills, and the job kind each one becomes
_KIND_OF = {
    "title": "title",
    "description_first_line": "description_first_line",
    "min_spend_voucher": "voucher",
    "review_voucher": "voucher",
    "ads_budget": "ads_edit",
    "ads_roas_target": "ads_edit",
    "affiliate_commission": "affiliate_commission",
    "bundle_deal": "combo",
    "combo_multi": "combo",
    # batch-1123-a F (owner decision #5, 23/11)
    "price": "price",
    "product_discount": "product_discount",
    "flash_sale": "flash_sale",
    "add_on": "add_on",
    "gift": "gift",
    "cover_image": "cover_image",
    "variation_restructure": "variation_set",
}
COMBO_OPEN_PATH = "/portal/marketing/bundle/new"
MAX_COMBO_NAME = 25
MAX_COMBO_TIERS = 5
MAX_COMBO_QTY = 9999
MAX_PURCHASE_LIMIT = 999_999_999
#: decision #13 (23/11): each Shopee form's own name limit, said in Vietnamese with the limit
COMBO_NAME_TOO_LONG = "Tên Combo Khuyến Mãi tối đa 25 ký tự"
TEXT_TOO_LONG = {
    "title": "Tên sản phẩm tối đa {} ký tự",
    "description_first_line": "Dòng đầu mô tả tối đa {} ký tự",
}
COMBO_LEGACY_ERROR = "Combo kiểu cũ — tạo lại theo mức ưu đãi của Shopee"
_COMBO_TYPES = ("pct", "amount", "special_price")
_TEXT_FIELDS = {
    "title": {
        "key": "title",
        "label": "Tên sản phẩm",
        "mode": "replace",
        "max_chars": config.MAX_TITLE_CHARS,
        "expected": "title",
    },
    "description_first_line": {
        "key": "description_first_line",
        "label": "Mô tả sản phẩm",
        "mode": "first_line",
        "max_chars": config.MAX_DESCRIPTION_FIRST_LINE_CHARS,
        "expected": "first_line",
    },
}
#: forward transitions the Connector may report (anything may fail)
_NEXT = {
    STATUS_QUEUED: {STATUS_OPENED, STATUS_FILLED, STATUS_FAILED},
    STATUS_OPENED: {STATUS_OPENED, STATUS_FILLED, STATUS_SAVED, STATUS_FAILED},
    STATUS_FILLED: {STATUS_FILLED, STATUS_SAVED, STATUS_CAPTURED, STATUS_FAILED},
    STATUS_SAVED: {STATUS_SAVED, STATUS_CAPTURED, STATUS_FAILED},
}


def enabled() -> bool:
    """The switch, and never inside a partner reviewer's request (P100 S2-G): a sample-shop
    reviewer's Duyệt / plan confirm writes Juli's rows only -- no job for the Connector."""
    from juli_backend.integrations.tiktok import reviewer_session_active

    if reviewer_session_active():
        return False
    return os.environ.get(ENV_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def supported(change_kind: str) -> bool:
    return change_kind in _KIND_OF


def voucher_code_suffix(card_code: str, version: int) -> str:
    """Up to 5 characters A-Z 0-9 from the card code and version, stable and readable
    (``JC-2611-0007`` V1 -> base 36 of 2611 0007 x 8 + 0)."""
    parsed = codes.parse_code(card_code)
    if parsed is None:
        raise ValueError("not a card code")
    m = codes.CODE_RE.match(parsed[0])
    assert m is not None
    n = (int(m["yymm"]) * 10_000 + int(m["seq"])) * 8 + (max(version, 1) - 1) % 8
    n %= 36**5
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = _B36[r] + out
    return out or "0"


def _shopee_time(moment: datetime) -> str:
    return moment.strftime("%H:%M %d-%m-%Y")


def voucher_window(now: datetime, days: int) -> tuple[str, str]:
    """Start at the next full hour GMT+7 at least an hour ahead; end one minute before ``days``
    days later. Format of Seller Centre's pickers: ``HH:mm DD-MM-YYYY``."""
    local = (now if now.tzinfo is None else now.astimezone(UTC).replace(tzinfo=None)) + ICT
    start = local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
    end = start + timedelta(days=max(int(days), 1)) - timedelta(minutes=1)
    return _shopee_time(start), _shopee_time(end)


def _chosen_day(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10]) if raw else None
    except ValueError:
        return None


def chosen_voucher_window(inputs: dict[str, Any], now: datetime) -> tuple[str, str] | None:
    """The start / end the seller picked in Tự tạo (``inputs["start"]`` / ``["end"]``, ISO days):
    00:00 of the start day to 23:59 of the end day, GMT+7. ``None`` unless the start is still in the
    future (Seller Centre refuses a past start), so the caller keeps :func:`voucher_window`."""
    start, end = _chosen_day(inputs.get("start")), _chosen_day(inputs.get("end"))
    if start is None or end is None or end < start:
        return None
    local_now = (now if now.tzinfo is None else now.astimezone(UTC).replace(tzinfo=None)) + ICT
    begins = datetime(start.year, start.month, start.day)
    if begins <= local_now:
        return None
    finish = datetime(end.year, end.month, end.day, 23, 59)
    return _shopee_time(begins), _shopee_time(finish)


def _ids(raw: Any) -> list[str]:
    out: list[str] = []
    for v in raw or []:
        s = str(v).strip()
        if re.fullmatch(r"\d{1,20}", s) and s not in out:
            out.append(s)
    return out[:MAX_PRODUCTS]


def _num(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value) if float(value) == int(value) else float(value)


def _voucher_payload(
    card: dict[str, Any], inputs: dict[str, Any], code: str, version: int, now: datetime,
    product_ids: list[str],
) -> dict[str, Any] | None:  # fmt: skip
    pct, value = _num(inputs.get("pct")), _num(inputs.get("value"))
    if pct is None and (value is None or value <= 0):
        return None
    days = int(_num(inputs.get("days")) or config.VOUCHER_DAYS)
    starts, ends = chosen_voucher_window(inputs, now) or voucher_window(now, days)
    discount: dict[str, Any]
    if pct is not None:
        mx = _num(inputs.get("max_value"))
        discount = {
            "type": "percent",
            "value": pct,
            "max": {"mode": "limited", "value": int(mx)} if mx else {"mode": "unlimited"},
        }
    else:
        discount = {"type": "amount", "value": int(value or 0)}
    usage = int(_num(inputs.get("quantity")) or 0)
    if usage < 1:
        return None
    return {
        "usecase": 2 if product_ids else 1,
        "name": f"{code} V{version} — {card.get('title') or 'voucher'}"[:MAX_VOUCHER_NAME],
        "code_suffix": voucher_code_suffix(code, version),
        "starts_at": starts,
        "ends_at": ends,
        "voucher_type": "promotion",
        "discount": discount,
        "min_spend": int(_num(inputs.get("min_spend")) or 0),
        "usage_total": usage,
        "per_buyer": int(_num(inputs.get("per_user_limit")) or 1),
        "display": "code" if product_ids else "multi",  # = the sheet: "Chia sẻ qua mã voucher"
        "product_ids": product_ids,
        # Mã giảm giá thông minh: off unless the card says so
        "smart": bool(inputs.get("smart") or card.get("smart")),
    }


def _combo_tiers(inputs: dict[str, Any]) -> tuple[str, list[dict[str, int]]] | None:
    """``(discount_type, tiers)`` of a combo card, or None when it is not fillable: quantities
    ascending and different (2..9999), a percent in 1..99, an amount or a special price above 0
    (whole dong). Cards the engine generated carry ``tier2_pct`` / ``tier3_pct`` (type percent)."""
    dtype = str(inputs.get("discount_type") or "pct")
    raw = inputs.get("tiers")
    if raw is None:
        raw = [
            {"qty": q, "value": inputs[k]}
            for q, k in ((2, "tier2_pct"), (3, "tier3_pct"))
            if inputs.get(k) is not None
        ]
    if dtype not in _COMBO_TYPES or not isinstance(raw, list):
        return None
    tiers: list[dict[str, int]] = []
    for row in raw:
        qty = _num(row.get("qty")) if isinstance(row, dict) else None
        value = _num(row.get("value")) if isinstance(row, dict) else None
        if qty is None or value is None or qty != int(qty) or value != int(value):
            return None
        tiers.append({"qty": int(qty), "value": int(value)})
    if not 1 <= len(tiers) <= MAX_COMBO_TIERS:
        return None
    if any(not 2 <= t["qty"] <= MAX_COMBO_QTY or t["value"] <= 0 for t in tiers):
        return None
    if dtype == "pct" and any(t["value"] > 99 for t in tiers):
        return None
    qtys = [t["qty"] for t in tiers]
    return (dtype, tiers) if qtys == sorted(set(qtys)) else None


def _combo_window(inputs: dict[str, Any], now: datetime) -> tuple[str, str]:
    """The card's dates (``YYYY-MM-DD``) as Seller Centre's pickers show them: from 00:00 of the
    start to 23:59 of the end. Anything missing, past or reversed becomes the default window."""
    floor_start, default_end = voucher_window(now, config.VOUCHER_DAYS)
    try:
        start = datetime.fromisoformat(str(inputs.get("start"))).replace(hour=0, minute=0)
        end = datetime.fromisoformat(str(inputs.get("end"))).replace(hour=23, minute=59)
    except ValueError:
        return floor_start, default_end
    earliest = datetime.strptime(floor_start, "%H:%M %d-%m-%Y")
    start = max(start, earliest)
    if end <= start:
        return floor_start, default_end
    return _shopee_time(start), _shopee_time(end)


def _combo_payload(
    card: dict[str, Any], inputs: dict[str, Any], code: str, version: int, now: datetime,
    product_ids: list[str],
) -> dict[str, Any] | None:  # fmt: skip
    parsed = _combo_tiers(inputs)
    if parsed is None or not product_ids:
        return None
    limit = _num(inputs.get("limit_per_buyer"))
    if limit is not None and not 1 <= limit <= MAX_PURCHASE_LIMIT:
        return None
    name = str(inputs.get("name") or "").strip() or f"{code} V{version}"
    if len(name) > MAX_COMBO_NAME:
        return None
    starts, ends = _combo_window(inputs, now)
    payload: dict[str, Any] = {
        "open_path": COMBO_OPEN_PATH,
        "name": name,
        "starts_at": starts,
        "ends_at": ends,
        "discount_type": parsed[0],
        "tiers": parsed[1],
        "product_ids": product_ids,
    }
    if limit is not None:
        payload["purchase_limit"] = int(limit)
    return payload


# ------------------------------------------------- batch-1123-a F: price, programmes, product page
#
# Giá (``price``), Chương Trình Của Shop (``product_discount``), Flash Sale Của Shop
# (``flash_sale``), Mua Kèm Deal Sốc / Mua Để Nhận Quà (``add_on`` / ``gift``, one Shopee form),
# Ảnh bìa (``cover_image``) and Phân loại hàng (``variation_set``, the card's
# ``variation_restructure``). The builder's spec of the approved version (its ``spec``) is read
# first, the card's inputs second. Anything Shopee would refuse is a failed job with a Vietnamese
# reason (at most 64 characters, the column), never a guessed value.

DISCOUNT_OPEN_PATH = "/portal/marketing/discount/create"
FLASH_SALE_OPEN_PATH = "/portal/marketing/shop-flash-sale/create"
DEAL_OPEN_PATH = "/portal/marketing/add-on-deal/create"
DISCOUNT_LIST_PATH = "/portal/marketing/list/discount"
#: D2 (capture 23/11): the Deal Sốc rows live on the discount list's addondeal tab; the Chương
#: Trình Của Shop tab's own discountType is not captured yet (E108), so its undo opens "all"
DEAL_LIST_OPEN_PATH = DISCOUNT_LIST_PATH + "?discountType=addondeal&status=all&page=1"
DISCOUNT_LIST_OPEN_PATH = DISCOUNT_LIST_PATH + "?discountType=all&status=all&page=1"
FLASH_SALE_LIST_PATH = "/portal/marketing/shop-flash-sale/list"
MAX_PROGRAMME_NAME = 150
#: Shopee's Deal Sốc name box has maxlength 25 (capture 03, 23/11)
MAX_DEAL_NAME = 25
MAX_DEAL_ADDON_LIMIT = 100
MAX_GIFT_QTY = 49
MAX_VARIATIONS = 40
#: Flash Sale Của Shop: Shopee's fixed daily slots (capture 01): start hour -> the picker's label
FLASH_SLOTS = {
    0: "00:00:00 - 02:00:00",
    2: "02:00:00 - 09:00:00",
    9: "09:00:00 - 12:00:00",
    12: "12:00:00 - 15:00:00",
    15: "15:00:00 - 17:00:00",
    17: "17:00:00 - 19:00:00",
    19: "19:00:00 - 21:00:00",
    21: "21:00:00 - 00:00:00",
}
FLASH_SLOT_HOURS = {0: 2, 2: 7, 9: 3, 12: 3, 15: 2, 17: 2, 19: 2, 21: 3}
#: about a week ahead: on 23/11 the picker offered 24-30/11
FLASH_MAX_DAYS_AHEAD = 7
FLASH_MAX_STOCK = 1000
FLASH_MIN_PCT, FLASH_MAX_PCT = 5, 90

ERR_PRICE = "Thiếu giá mới của phân loại"
ERR_NO_VARIATION = "Sản phẩm không có phân loại: sửa giá bằng tay"
ERR_DISCOUNT = "Thiếu mức giảm của phân loại"
ERR_WINDOW = "Kết thúc phải sau bắt đầu ít nhất 1 giờ"
ERR_FLASH_NO_SLOT = "Chưa chọn khung giờ Flash Sale"
ERR_FLASH_BAD_SLOT = "Khung giờ không có trên Shopee"
ERR_FLASH_DAY = "Ngày Flash Sale ngoài 7 ngày Shopee cho đặt"
ERR_FLASH_PCT = "Mức giảm Flash Sale phải từ 5% đến 90%"
ERR_FLASH_STOCK = "SL khuyến mãi phải từ 1 đến 1000"
ERR_DEAL_NAME = "Tên Deal Sốc tối đa 25 ký tự"
ERR_PROGRAMME_NAME = "Tên chương trình khuyến mãi tối đa 150 ký tự"
ERR_DEAL_ADDONS = "Thiếu sản phẩm chính hoặc sản phẩm mua kèm"
ERR_GIFT_SPEND = "Thiếu mức «Mua ₫X» của quà tặng"
ERR_GIFT_UNSOLD = "Quà không bán: Shopee cần quà là sản phẩm của shop"
ERR_COVER = "Thiếu ảnh bìa hiện tại để hoàn tác"
ERR_OPTIONS = "Thiếu phân loại mới (tên, giá)"

#: what reads the object back after the save (F9): only the voucher and combo lists today; the
#: others are ``unsupported`` so Juli shows "Chưa thấy" rather than a match nobody read
READBACK_OF_KIND = {
    "title": "item_catalog",
    "description_first_line": "item_catalog",
    "voucher": "voucher_list",
    "combo": "combo_list",
    "affiliate_commission": "item_catalog",
}
READBACK_UNSUPPORTED = "unsupported"
#: F5: the Connector's check key that turns ✓ once step 1 of a Deal Sốc was saved by the person
DEAL_STEP1_KEY = "step1_saved"
DEAL_ABANDONED = "Chương trình trống trên Shopee — cần Kết thúc"
DEAL_ABANDON_AFTER = timedelta(hours=24)


#: F7: the Connector's check that a running promotion greys the product page's fields
PROMOTION_LOCK_KEY = "promotion_lock"
PROMOTION_LOCKED = "Bị khoá vì chương trình khuyến mãi đang chạy"


def promotion_locked(field_checks: list[dict[str, Any]] | None) -> bool:
    return any(
        isinstance(c, dict) and c.get("key") == PROMOTION_LOCK_KEY and c.get("ok") is False
        for c in field_checks or []
    )


#: D5: what a save confirmed only by the Connector's own signal says (never "Khớp")
SAVED_NOT_READ = "Đã lưu trên Shopee · chưa đọc lại"
_SAVED_ONLY_KINDS = ("combo_end", "discount_end", "flash_sale_end", "deal_end")


def saved_only(j: ShopeeFillJob) -> bool:
    """No reader confirms this job's save: an end of a list row, or a kind without a read-back."""
    return j.kind in _SAVED_ONLY_KINDS or (
        j.kind != "readback" and readback_of(j.kind) == READBACK_UNSUPPORTED
    )


def readback_of(kind: str) -> str:
    return READBACK_OF_KIND.get(kind, READBACK_UNSUPPORTED)


def _spec_of(card: dict[str, Any], version: int) -> dict[str, Any]:
    """The builder spec of the approved version (``{}`` for an engine card)."""
    vlist = card.get("versions") or []
    if 1 <= version <= len(vlist) and isinstance(vlist[version - 1], dict):
        spec = vlist[version - 1].get("spec")
        if isinstance(spec, dict):
            return dict(spec)
    spec = card.get("spec")
    return dict(spec) if isinstance(spec, dict) else {}


def _extra_of(card: dict[str, Any], version: int) -> dict[str, Any]:
    vlist = card.get("versions") or []
    out = dict(card.get("candidate_extra") or {})
    if 1 <= version <= len(vlist) and isinstance(vlist[version - 1], dict):
        out.update(vlist[version - 1].get("extra") or {})
    return out


def _local_now(now: datetime) -> datetime:
    return (now if now.tzinfo is None else now.astimezone(UTC).replace(tzinfo=None)) + ICT


def programme_window(
    spec: dict[str, Any], inputs: dict[str, Any], now: datetime
) -> tuple[str, str] | None:
    """Start / end of a programme form (``HH:mm DD-MM-YYYY``, GMT+7): the spec's days and hours
    (no hour: 00:00 / 23:59); a start in the past moves to the earliest Shopee takes. ``None``
    when the end is not at least an hour after the start (Shopee's rule)."""
    floor_start, default_end = voucher_window(now, config.VOUCHER_DAYS)
    earliest = datetime.strptime(floor_start, "%H:%M %d-%m-%Y")
    start_day = _chosen_day(spec.get("start") or inputs.get("start"))
    end_day = _chosen_day(spec.get("end") or inputs.get("end"))
    if start_day is None or end_day is None:
        return floor_start, default_end
    sh, eh = spec.get("start_hour"), spec.get("end_hour")
    start = datetime(
        start_day.year, start_day.month, start_day.day, int(sh) if sh is not None else 0
    )
    end = (
        datetime(end_day.year, end_day.month, end_day.day, int(eh))
        if eh is not None
        else datetime(end_day.year, end_day.month, end_day.day, 23, 59)
    )
    start = max(start, earliest)
    if end - start < timedelta(hours=1):
        return None
    return _shopee_time(start), _shopee_time(end)


async def catalog_variations(
    session: AsyncSession | None, shop_id: uuid.UUID, item_id: str
) -> dict[str, dict[str, Any]]:
    """variation id -> ``{name, selling, listed}`` of one item from the newest catalogue and
    snapshot reads (the price fill's names and the undo's old prices). Empty without a session."""
    if session is None:
        return {}
    from juli_backend.models.platform_data import PlatformItem
    from juli_backend.repositories import PlatformItemSnapshotsRepo

    out: dict[str, dict[str, Any]] = {}
    for row in await session.scalars(
        select(PlatformItem).where(PlatformItem.shop_id == shop_id, PlatformItem.item_id == item_id)
    ):
        if row.variation_id:
            out.setdefault(row.variation_id, {})["name"] = row.variation_name
    for snap in await PlatformItemSnapshotsRepo(session).latest_per_item(shop_id, [item_id]):
        if not snap.variation_id:
            continue
        own = out.setdefault(snap.variation_id, {})
        own["selling"] = _num(_int_or_none(snap.current_price))
        own["listed"] = _num(_int_or_none(snap.list_price))
    return out


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _unique_names(catalog: dict[str, dict[str, Any]]) -> dict[str, str]:
    """variation id -> its name, only for names no other variation of the item has (F2: a name
    that is not unique would let one variation take another's price)."""
    names = [str(v.get("name") or "").strip() for v in catalog.values()]
    return {
        vid: str(v.get("name")).strip()
        for vid, v in catalog.items()
        if str(v.get("name") or "").strip() and names.count(str(v.get("name")).strip()) == 1
    }


def _variation_rows(spec: dict[str, Any], inputs: dict[str, Any]) -> list[dict[str, Any]]:
    rows = spec.get("variations")
    if not isinstance(rows, list) or not rows:
        rows = inputs.get("variations")
    return [r for r in rows or [] if isinstance(r, dict)][:MAX_VARIATIONS]


def price_payload(
    item_id: str, spec: dict[str, Any], inputs: dict[str, Any], catalog: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], str | None]:
    """F2: one new price per variation (the builder's ``PriceSpec``), each from that variation's
    own price; ``old_prices`` (the catalogue's) is what Hoàn tác puts back."""
    from juli_backend.services.shopee_builder.variations import quote_variation_price

    names = _unique_names(catalog)
    variations: list[dict[str, Any]] = []
    old: list[dict[str, Any]] = []
    rows = _variation_rows(spec, inputs)
    for row in rows:
        vid = str(row.get("variation_id") or "")
        if not vid:
            return {}, ERR_NO_VARIATION
        own = catalog.get(vid) or {}
        pct = _num(row.get("new_price_pct"))
        change = _num(row.get("change_pct"))
        if change is None and pct is not None:
            change = float(pct) - 100
        price = quote_variation_price(
            _int_or_none(own.get("selling")),
            _int_or_none(own.get("listed")),
            change_pct=change,
            final_price=_int_or_none(row.get("final_price")),
        )
        if not price or price <= 0:
            return {}, ERR_PRICE
        variations.append(
            {
                "variation_id": vid,
                "price": int(price),
                **({"name": names[vid]} if vid in names else {}),
            }
        )
        if own.get("selling"):
            old.append(
                {
                    "variation_id": vid,
                    "price": int(own["selling"]),
                    **({"name": names[vid]} if vid in names else {}),
                }
            )
    if not variations:
        return {}, ERR_PRICE
    return {
        "open_path": f"/portal/product/{item_id}",
        "item_id": item_id,
        "variations": variations,
        "old_prices": old,
    }, None


def _discount_rows(
    rows: list[dict[str, Any]], names: dict[str, str]
) -> list[dict[str, Any]] | None:
    """Per variation Giá sau giảm (``final_price``) OR %GIẢM (``discount_pct``), never both."""
    out: list[dict[str, Any]] = []
    for row in rows:
        vid = str(row.get("variation_id") or "")
        final, pct = _int_or_none(row.get("final_price")), _num(row.get("discount_pct"))
        if not vid or (final is None) == (pct is None):
            return None
        value = {"final_price": final} if final is not None else {"discount_pct": pct}
        if (final is not None and final <= 0) or (pct is not None and not 0 < pct <= 90):
            return None
        out.append({"variation_id": vid, **value, **({"name": names[vid]} if vid in names else {})})
    return out


def _programme_name(spec: dict[str, Any], inputs: dict[str, Any], code: str, version: int) -> str:
    return str(spec.get("name") or inputs.get("name") or "").strip() or f"{code} V{version}"


def product_discount_payload(
    spec: dict[str, Any], inputs: dict[str, Any], code: str, version: int, now: datetime,
    product_ids: list[str], catalog: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], str | None]:  # fmt: skip
    """F3: Chương Trình Của Shop. A one-product card names its variations' Giá sau giảm / %; a
    many-target (or engine) card one % for every variation of each product (``all_pct``)."""
    window = programme_window(spec, inputs, now)
    if window is None:
        return {}, ERR_WINDOW
    name = _programme_name(spec, inputs, code, version)
    if len(name) > MAX_PROGRAMME_NAME:
        return {}, ERR_PROGRAMME_NAME
    payload: dict[str, Any] = {
        "open_path": DISCOUNT_OPEN_PATH,
        "name": name,
        "starts_at": window[0],
        "ends_at": window[1],
        "product_ids": product_ids,
        "variations": [],
    }
    rows = _variation_rows(spec, inputs)
    if rows and len(product_ids) == 1:
        found = _discount_rows(rows, _unique_names(catalog))
        if not found:
            return {}, ERR_DISCOUNT
        payload["variations"] = found
    else:
        pct = _num(
            spec.get("discount_pct")
            if spec.get("discount_pct") is not None
            else inputs.get("discount_pct")
        )
        if pct is None or not 0 < pct <= 90:
            return {}, ERR_DISCOUNT
        payload["all_pct"] = pct
    for key in ("promo_qty", "per_buyer_limit"):
        value = _int_or_none(spec.get(key) if spec.get(key) is not None else inputs.get(key))
        if value is not None and value > 0:
            payload[key] = value
    return payload, None


def flash_slot(raw: Any, now: datetime) -> tuple[dict[str, Any] | None, str | None]:
    """F4: ``slot_start`` ("YYYY-MM-DDTHH:mm", GMT+7) -> ``{day, label, starts}``: the fixed
    Shopee slot that starts at that hour, on a day Shopee lets the shop book (tomorrow .. a week
    ahead). Never a stored slot id: the Connector picks by day + label."""
    if not raw:
        return None, ERR_FLASH_NO_SLOT
    try:
        moment = datetime.fromisoformat(str(raw).strip().replace(" ", "T")[:16])
    except ValueError:
        return None, ERR_FLASH_BAD_SLOT
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None) + ICT
    if moment.minute != 0 or moment.hour not in FLASH_SLOTS:
        return None, ERR_FLASH_BAD_SLOT
    today = _local_now(now).date()
    ahead = (moment.date() - today).days
    if not 1 <= ahead <= FLASH_MAX_DAYS_AHEAD:
        return None, ERR_FLASH_DAY
    return {
        "day": moment.date().isoformat(),
        "label": FLASH_SLOTS[moment.hour],
        "starts_at": _shopee_time(moment),
        "hours": FLASH_SLOT_HOURS[moment.hour],
    }, None


def flash_sale_payload(
    item_id: str, spec: dict[str, Any], inputs: dict[str, Any], now: datetime,
    catalog: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], str | None]:  # fmt: skip
    slot, error = flash_slot(spec.get("slot_start") or inputs.get("slot_start"), now)
    if slot is None:
        return {}, error
    rows = _discount_rows(_variation_rows(spec, inputs), _unique_names(catalog))
    if not rows:
        return {}, ERR_DISCOUNT
    if any(
        r.get("discount_pct") is not None
        and not FLASH_MIN_PCT <= r["discount_pct"] <= FLASH_MAX_PCT
        for r in rows
    ):
        return {}, ERR_FLASH_PCT
    units = _int_or_none(
        spec.get("units") if spec.get("units") is not None else inputs.get("units")
    )
    if units is None or not 1 <= units <= FLASH_MAX_STOCK * max(len(rows), 1):
        return {}, ERR_FLASH_STOCK
    payload: dict[str, Any] = {
        "open_path": FLASH_SALE_OPEN_PATH,
        "item_id": item_id,
        "product_ids": [item_id],
        "slot": slot,
        "variations": rows,
        "units": units,
    }
    # SL sản phẩm khuyến mãi is per variation on Shopee: one variation takes the card's units;
    # several are split by the person (a guided step), never invented here
    if len(rows) == 1:
        if units > FLASH_MAX_STOCK:
            return {}, ERR_FLASH_STOCK
        rows[0]["stock"] = units
    limit = _int_or_none(spec.get("purchase_limit"))
    if limit is not None and limit > 0:
        payload["purchase_limit"] = limit
    return payload, None


def deal_payload(
    kind: str, spec: dict[str, Any], inputs: dict[str, Any], code: str, version: int,
    now: datetime, card: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:  # fmt: skip
    """F5: step 1 of the Deal Sốc form (the only part fillable before the person's Lưu): the
    type card, Tên (at most 25), dates, and Giới hạn sản phẩm mua kèm or "Mua ₫X để nhận N"; then
    the products the person picks in steps 2-3."""
    name = _programme_name(spec, inputs, code, version)
    if len(name) > MAX_DEAL_NAME:
        return {}, ERR_DEAL_NAME
    window = programme_window(spec, inputs, now)
    if window is None:
        return {}, ERR_WINDOW
    payload: dict[str, Any] = {
        "open_path": DEAL_OPEN_PATH,
        "deal_type": kind,
        "name": name,
        "starts_at": window[0],
        "ends_at": window[1],
    }
    if kind == "add_on":
        main = (
            _ids([spec.get("main_item_id")])
            or _ids((card.get("scope") or {}).get("product_ids"))[:1]
        )
        addons = spec.get("addons") or inputs.get("addons") or []
        addon_ids = _ids([a.get("item_id") for a in addons if isinstance(a, dict)])
        if not main or not addon_ids:
            return {}, ERR_DEAL_ADDONS
        payload["main_product_ids"] = main
        payload["addon_product_ids"] = [i for i in addon_ids if i not in main]
        # step 3 (capture 03, edit mode): per add-on Giá Mua Kèm OR %, and its Giới hạn đặt hàng
        rows = [_addon_row(a) for a in addons if isinstance(a, dict) and a.get("item_id")]
        if any(r is None for r in rows):
            return {}, ERR_DEAL_ADDONS
        payload["addons"] = rows
        limit = _int_or_none(spec.get("addon_limit"))
        if limit is not None:
            if not 1 <= limit <= MAX_DEAL_ADDON_LIMIT:
                return {}, ERR_DEAL_ADDONS
            payload["addon_limit"] = limit
        return payload, None
    gift = spec.get("gift") or inputs.get("gift") or {}
    trigger = spec.get("trigger") or inputs.get("trigger") or {}
    gift_ids = _ids([gift.get("item_id")]) if isinstance(gift, dict) else []
    if not gift_ids:
        return {}, ERR_GIFT_UNSOLD
    amount = _int_or_none(trigger.get("amount")) if isinstance(trigger, dict) else None
    if amount is None or amount <= 0:
        return {}, ERR_GIFT_SPEND
    qty = _int_or_none(gift.get("qty")) or 1
    if not 1 <= qty <= MAX_GIFT_QTY:
        return {}, ERR_DEAL_ADDONS
    payload.update({"min_spend": amount, "gift_qty": qty, "gift_product_ids": gift_ids})
    main = _ids([trigger.get("item_id")]) if isinstance(trigger, dict) else []
    if main:
        payload["main_product_ids"] = main
    return payload, None


def _addon_row(a: dict[str, Any]) -> dict[str, Any] | None:
    """One add-on of the card: its Giá Mua Kèm (whole đồng) OR % off, and the per-order limit."""
    price, pct = _int_or_none(a.get("price")), _num(a.get("pct"))
    if (price is None) == (pct is None) or (price is not None and price <= 0):
        return None
    if pct is not None and not 0 <= pct <= 90:
        return None
    raw_limit = a.get("limit_per_order") if a.get("limit_per_order") is not None else a.get("limit")
    limit = _int_or_none(raw_limit)
    row: dict[str, Any] = {"item_id": str(a["item_id"])}
    row.update({"price": price} if price is not None else {"pct": pct})
    if limit is not None and limit > 0:
        row["limit"] = limit
    return row


_HTTPS = re.compile(r"^https://\S+$")


def cover_payload(
    item_id: str, extra: dict[str, Any], card: dict[str, Any] | None = None
) -> tuple[dict[str, Any], str | None]:
    """F6: the new cover goes onto the image grid's file box (the Connector fetches it from
    ``new_cover_url`` when the card has one, else the person downloads it from the Juli card);
    dragging it first stays the person's. The old cover's address rides along for Hoàn tác."""
    old = str(extra.get("cover_url") or "")
    if not _HTTPS.match(old):
        return {}, ERR_COVER
    payload = {"open_path": f"/portal/product/{item_id}", "item_id": item_id, "old_cover_url": old}
    sheet = (card or {}).get("execution_sheet") or {}
    urls = [str(d.get("url") or "") for d in sheet.get("downloads") or [] if isinstance(d, dict)]
    new = next((u for u in urls if _HTTPS.match(u)), None)
    if new:
        payload["new_cover_url"] = new
    return payload, None


def variation_set_payload(
    item_id: str, inputs: dict[str, Any], extra: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    """F7: the new options (name, Giá, Kho hàng, SKU); the card's current variations are kept for
    Hoàn tác (delete the added options, put the old prices back)."""
    options: list[dict[str, Any]] = []
    for row in inputs.get("variations") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        price = _int_or_none(row.get("price"))
        if not name or len(name) > 100 or price is None or price <= 0:
            return {}, ERR_OPTIONS
        option: dict[str, Any] = {"name": name, "price": price}
        if row.get("sku"):
            option["sku"] = str(row["sku"])[:100]
        stock = _int_or_none(row.get("stock"))
        if stock is not None and stock >= 0:
            option["stock"] = stock
        options.append(option)
    if not options or len(options) > 12:
        return {}, ERR_OPTIONS
    old = [
        {k: v.get(k) for k in ("name", "price", "sku", "stock") if v.get(k) is not None}
        for v in extra.get("current_variations") or []
        if isinstance(v, dict)
    ]
    return {
        "open_path": f"/portal/product/{item_id}",
        "item_id": item_id,
        "options": options,
        "old_variations": old,
    }, None


def deal_step1_saved(j: ShopeeFillJob) -> bool:
    """The Connector saw step 1 of the Deal Sốc saved (its check ``step1_saved`` is ✓)."""
    return j.kind in ("add_on", "gift") and any(
        isinstance(c, dict) and c.get("key") == DEAL_STEP1_KEY and c.get("ok") is True
        for c in (j.payload or {}).get("fill_check") or []
    )


def deal_abandoned(j: ShopeeFillJob, now: datetime | None = None) -> bool:
    """F5: step 1 was saved (an empty programme now exists on Shopee) and the job never reached
    the final save: it failed, was cancelled, or has not moved for a day."""
    if not deal_step1_saved(j) or j.status in (STATUS_SAVED, STATUS_CAPTURED):
        return False
    if j.status in (STATUS_FAILED, STATUS_CANCELLED):
        return True
    moment = _naive_now(now)
    return j.updated_at is not None and moment - j.updated_at > DEAL_ABANDON_AFTER


async def campaign_id_of(
    session: AsyncSession, shop_id: uuid.UUID, campaign_key: str | None
) -> tuple[str | None, str | None]:
    """``(campaign_id, page variant)`` of a report campaign: the newest ``ads_campaign_daily``
    row of that segment carries ``extra.campaign_id``; a group campaign ("Chiến dịch nhóm")
    is edited on ``manual-mpd``, the others on ``manual``."""
    if not campaign_key:
        return None, None
    rows = (
        await session.scalars(
            select(PlatformDailyMetric)
            .where(
                PlatformDailyMetric.shop_id == shop_id,
                PlatformDailyMetric.dataset == "ads_campaign_daily",
                PlatformDailyMetric.segment == campaign_key,
            )
            .order_by(PlatformDailyMetric.day.desc(), PlatformDailyMetric.captured_at.desc())
            .limit(5)
        )
    ).all()
    for r in rows:
        cid = (r.extra or {}).get("campaign_id")
        if cid is not None and re.fullmatch(r"\d{1,20}", str(cid)):
            group = "nhóm" in (r.platform_source or "").casefold()
            return str(cid), "manual-mpd" if group else "manual"
    return None, None


def _ads_payload(
    kind: str, inputs: dict[str, Any], campaign_id: str, variant: str
) -> tuple[dict[str, Any] | None, str | None]:
    """``(payload, error)``: a budget under Shopee's minimum is a failed job, not a payload."""
    payload: dict[str, Any] = {
        "campaign_id": campaign_id,
        "variant": variant,
        "open_path": f"/portal/marketing/pas/product/{variant}/{campaign_id}",
    }
    if kind == "ads_budget":
        budget = _num(inputs.get("daily_budget"))
        if budget is None:
            return None, "budget_missing"
        if budget == 0:
            payload["budget"] = {"mode": "unlimited"}
        elif budget < MIN_DAILY_BUDGET:
            return None, "budget_below_minimum"
        else:
            payload["budget"] = {"mode": "daily", "value": int(budget)}
    else:
        roas = _num(inputs.get("roas_target"))
        if roas is None or not 0 < roas <= 100:
            return None, "roas_missing"
        payload["roas"] = {"mode": "custom", "value": float(roas)}
    return payload, None


def _card_text(card: dict[str, Any], change_kind: str) -> str:
    spec = _TEXT_FIELDS[change_kind]
    for change in (card.get("execution_sheet") or {}).get("changes") or []:
        if change.get("change_kind") == change_kind:
            return str((change.get("expected") or {}).get(spec["expected"]) or "").strip()
    return ""


def _card_targets(card: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """P97 T4 many-target cards (D85.13): ``card["targets"]`` rows ``{id, kind, ...}``; refused
    rows carry ``refusal`` and are skipped. A bulk fill (affiliate commission, one voucher over a
    product list) is one target holding every product; otherwise one target per row."""
    rows = [
        r
        for r in (card.get("targets") or [])
        if isinstance(r, dict) and r.get("id") and not r.get("refusal") and r.get("ok", True)
    ]
    if not rows:
        return []
    if rows[0].get("kind") == "campaign":
        return [{"campaign_key": str(r["id"])} for r in rows]
    ids = [str(r["id"]) for r in rows]
    mode = (card.get("fill") or {}).get("mode")
    if mode == "bulk" or kind in ("voucher", "affiliate_commission", "combo", "product_discount"):
        return [{"product_ids": ids}]
    return [{"item_id": i} for i in ids]


async def build_jobs(
    session: AsyncSession,
    shop_id: uuid.UUID,
    p: ShopProposal,
    card: dict[str, Any],
    version: int,
    targets: list[dict[str, Any]] | None,
    now: datetime,
) -> list[dict[str, Any]]:
    """Plain dicts ``{kind, target, target_key, payload, status, error}`` (no database writes)."""
    change_kind = str(card.get("change_kind"))
    kind = _KIND_OF.get(change_kind)
    if kind is None or not p.code:
        return []
    base_inputs = dict(card.get("inputs") or {})
    scope_items = _ids(card.get("scope", {}).get("product_ids"))
    given = [t for t in (targets or []) if isinstance(t, dict)] or _card_targets(card, kind)
    jobs: list[dict[str, Any]] = []

    def job(target: dict[str, Any], key: str, payload: dict[str, Any], error: str | None = None):
        jobs.append(
            {
                "kind": kind,
                "target": target,
                "target_key": key[:80],
                "payload": payload,
                "status": STATUS_FAILED if error else STATUS_QUEUED,
                "error": error,
            }
        )

    if kind in _TEXT_FIELDS:
        spec = _TEXT_FIELDS[kind]
        value = _card_text(card, kind)
        items = [_ids([t.get("item_id")]) for t in given] or [scope_items[:1]]
        for item_ids in items:
            if not item_ids:
                continue
            limit = int(str(spec["max_chars"]))
            ok = bool(value) and "\n" not in value and len(value) <= limit
            # decision #13: an over-limit text is refused naming Shopee's limit
            too_long = len(value) > limit
            text_error = TEXT_TOO_LONG[kind].format(limit) if too_long else "text_not_fillable"
            field = {k: spec[k] for k in ("key", "label", "mode", "max_chars")}
            job(
                {"item_id": item_ids[0]},
                f"{kind}:{item_ids[0]}",
                {
                    "open_path": f"/portal/product/{item_ids[0]}",
                    "fields": [{**field, "value": value}],
                },
                None if ok else text_error,
            )
    elif kind == "voucher":
        groups = [_ids(t.get("product_ids") or [t.get("item_id")]) for t in given]
        if not groups:
            # a Tự tạo card has no targets: a product-level voucher keeps its product(s); only a
            # shop-scope voucher is shop-wide
            level = (card.get("scope") or {}).get("level")
            # F2.2 / E40: a Tự tạo "Voucher sản phẩm" is a product voucher (usecase 2 with the
            # card's products) although the kind's default scope level is "shop"
            product_voucher = (card.get("candidate_extra") or {}).get("voucher_scope") == "product"
            groups = [scope_items] if scope_items and (level != "shop" or product_voucher) else [[]]
        for n, vids in enumerate(groups):
            inputs = {**base_inputs, **((given[n].get("inputs") or {}) if given else {})}
            payload = _voucher_payload(card, inputs, p.code, version, now, vids)
            usecase = 2 if vids else 1
            key = f"voucher:{usecase}:{','.join(vids) or 'shop'}"
            if payload is None:
                job({"product_ids": vids}, key, {}, "voucher_incomplete")
                continue
            payload["open_path"] = f"/portal/marketing/vouchers/new?usecase={usecase}"
            job({"product_ids": vids}, key, payload)
    elif kind == "ads_edit":
        scope = card.get("scope") or {}
        change_target = (card.get("change") or {}).get("target") or {}
        wanted = given or [{}]
        for t in wanted:
            cid = str(t.get("campaign_id") or change_target.get("campaign_id") or "")
            variant = str(t.get("variant") or "")
            if not cid:
                cid_found, variant_found = await campaign_id_of(
                    session, shop_id, str(t.get("campaign_key") or scope.get("campaign_key") or "")
                )
                cid, variant = cid_found or "", variant or variant_found or ""
            if not re.fullmatch(r"\d{1,20}", cid):
                job({"campaign_key": scope.get("campaign_key")}, f"ads:{scope.get('campaign_key')}",
                    {}, "campaign_unknown")  # fmt: skip
                continue
            payload, error = _ads_payload(
                change_kind, {**base_inputs, **(t.get("inputs") or {})}, cid,
                variant if variant in ("manual", "manual-mpd") else "manual",
            )  # fmt: skip
            job({"campaign_id": cid}, f"ads:{change_kind}:{cid}", payload or {}, error)
    elif kind == "combo":
        if change_kind == "combo_multi":
            job({"product_ids": scope_items}, "combo:legacy", {}, COMBO_LEGACY_ERROR)
            return jobs
        cids: list[str] = []
        for t in given:
            cids += _ids(t.get("product_ids") or [t.get("item_id")])
        cids = list(dict.fromkeys(cids or scope_items))[:MAX_PRODUCTS]
        key = "combo:" + ",".join(cids)[:60]
        payload = _combo_payload(card, base_inputs, p.code, version, now, cids)
        named = str(base_inputs.get("name") or "").strip()
        combo_error = COMBO_NAME_TOO_LONG if len(named) > MAX_COMBO_NAME else "combo_incomplete"
        job({"product_ids": cids}, key, payload or {}, None if payload else combo_error)
    elif kind == "affiliate_commission":
        ids: list[str] = []
        for t in given:
            ids += _ids(t.get("product_ids") or [t.get("item_id")])
        ids = list(dict.fromkeys(ids or scope_items))[:MAX_PRODUCTS]
        pct = _num(base_inputs.get("commission_pct"))
        error = None if ids and pct is not None and 0 < pct <= 50 else "commission_incomplete"
        job(
            {"product_ids": ids},
            "affiliate:" + ",".join(ids)[:60],
            {
                "open_path": "/portal/web-seller-affiliate/open_campaign",
                "product_ids": ids,
                "commission_pct": pct,
            }
            if not error
            else {},
            error,
        )
    elif kind in _PROMO_KINDS:
        await _promo_jobs(
            session, shop_id, p.code, card, version, now, kind, given, scope_items, job
        )
    return jobs


_PROMO_KINDS = (
    "price",
    "product_discount",
    "flash_sale",
    "add_on",
    "gift",
    "cover_image",
    "variation_set",
)


async def _promo_jobs(
    session: AsyncSession | None,
    shop_id: uuid.UUID,
    code: str,
    card: dict[str, Any],
    version: int,
    now: datetime,
    kind: str,
    given: list[dict[str, Any]],
    scope_items: list[str],
    job: Any,
) -> None:
    """batch-1123-a F: the jobs of the price / programme / product-page kinds (one per page)."""
    spec = _spec_of(card, version)
    inputs = dict(card.get("inputs") or {})
    extra = _extra_of(card, version)
    ids: list[str] = []
    for t in given:
        ids += _ids(t.get("product_ids") or [t.get("item_id")])
    ids = list(dict.fromkeys(ids or _ids([spec.get("item_id")]) or scope_items))[:MAX_PRODUCTS]
    if kind in ("add_on", "gift"):
        payload, error = deal_payload(kind, spec, inputs, code, version, now, card)
        key = (
            f"{kind}:"
            + ",".join(payload.get("main_product_ids") or payload.get("gift_product_ids") or ids)[
                :60
            ]
        )
        job({"product_ids": ids}, key, payload, error)
        return
    if kind == "product_discount":
        catalog = await catalog_variations(session, shop_id, ids[0]) if len(ids) == 1 else {}
        payload, error = product_discount_payload(spec, inputs, code, version, now, ids, catalog)
        job(
            {"product_ids": ids},
            "product_discount:" + ",".join(ids)[:60],
            payload,
            error if ids else ERR_DISCOUNT,
        )
        return
    for item in ids[:1] if kind == "flash_sale" else ids:
        target = {"item_id": item}
        if kind == "price":
            payload, error = price_payload(
                item, spec, inputs, await catalog_variations(session, shop_id, item)
            )
        elif kind == "flash_sale":
            payload, error = flash_sale_payload(
                item, spec, inputs, now, await catalog_variations(session, shop_id, item)
            )
        elif kind == "cover_image":
            payload, error = cover_payload(item, extra, card)
        else:
            payload, error = variation_set_payload(item, inputs, extra)
        job(target, f"{kind}:{item}", payload, error)


async def _card_for(
    session: AsyncSession, shop_id: uuid.UUID, p: ShopProposal, version: int
) -> dict[str, Any] | None:
    card = await store.card_payload(session, shop_id, p.id)
    if card is None:
        return None
    vlist = versions.versions_of(card)
    if version != 1 and 1 <= version <= len(vlist):
        return versions.overlay(card, vlist[version - 1])
    return card


async def enqueue_for_approval(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    proposal_id: uuid.UUID,
    version: int,
    targets: list[dict[str, Any]] | None = None,
    group_code: str | None = None,
    card: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> list[ShopeeFillJob]:
    """Queue the fill jobs of one approved card version. Idempotent per (card, version, target).

    ``targets``: optional list of ``{item_id | product_ids | campaign_id | campaign_key,
    inputs?}`` (a card with many targets, D85.13); none = the card's own scope. ``card``: the
    final card when the caller already holds it (adjusted inputs). Returns the rows (new and
    existing). Does nothing unless ``CONNECTOR_FILL_LISTING`` is on."""
    if not enabled():
        return []
    p = await session.scalar(
        select(ShopProposal).where(ShopProposal.id == proposal_id, ShopProposal.shop_id == shop_id)
    )
    if p is None:
        raise ProposalError("reco_unknown_card", 404)
    final = card or await _card_for(session, shop_id, p, version)
    if final is None:
        raise ProposalError("reco_unknown_card", 404)
    when = now or datetime.now(UTC)
    specs = await build_jobs(session, shop_id, p, final, version, targets, when)
    existing = {
        j.target_key: j
        for j in await session.scalars(
            select(ShopeeFillJob).where(
                ShopeeFillJob.shop_id == shop_id,
                ShopeeFillJob.proposal_id == proposal_id,
                ShopeeFillJob.version == version,
            )
        )
    }
    base_seq = len(existing)
    out: list[ShopeeFillJob] = list(existing.values()) if not specs else []
    for n, s in enumerate(specs):
        row = existing.get(s["target_key"])
        if row is None:
            row = ShopeeFillJob(
                shop_id=shop_id,
                proposal_id=proposal_id,
                version=version,
                group_code=group_code,
                kind=s["kind"],
                target=s["target"],
                target_key=s["target_key"],
                seq=base_seq + n,
                payload=s["payload"],
                status=s["status"],
                error=s["error"],
                created_at=when.replace(tzinfo=None),
                updated_at=when.replace(tzinfo=None),
            )
            session.add(row)
        out.append(row)
    await session.flush()
    return out


async def enqueue_after_decision(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    proposal_id: uuid.UUID,
    picked: list[int],
    final_card: dict[str, Any],
    group_name: str | None,
    now: datetime,
) -> None:
    """The single hook ``service._decide`` calls after an approval: queue the first version from
    the card the person approved (adjusted inputs kept), the others of a group from the card.
    A queue failure never undoes the approval (logged; the card can still be filled by hand)."""
    if not enabled():
        return
    try:
        async with session.begin_nested():
            for n, version in enumerate(picked):
                await enqueue_for_approval(
                    session,
                    shop_id=shop_id,
                    proposal_id=proposal_id,
                    version=version,
                    group_code=group_name,
                    card=final_card if n == 0 else None,
                    now=now,
                )
    except (SQLAlchemyError, RuntimeError, ArithmeticError, LookupError, TypeError, ValueError):
        # the approval stands whatever the queue does
        logger.exception("fill_enqueue_failed", extra={"shop_id": str(shop_id)})


# ----------------------------------------------------------------------------- reading / reporting


def job_json(j: ShopeeFillJob, code: str | None = None, title: str | None = None) -> dict[str, Any]:
    return {
        "id": str(j.id),
        "card_id": str(j.proposal_id),
        "code": code,
        "title": title,
        "version": j.version,
        "group_code": j.group_code,
        "kind": j.kind,
        "target": j.target,
        "seq": j.seq,
        "status": j.status,
        "captured_ref": j.captured_ref,
        "error": j.error,
        "payload": j.payload,
        "open_path": (j.payload or {}).get("open_path"),
        # Connector 0.3.24: each field's value before the Connector wrote it (the revert puts
        # it back), whether a time-bound form's period holds the card's dates, the last reads
        "before_values": (j.payload or {}).get("before_values") or {},
        "period_ok": (j.payload or {}).get("period_ok"),
        "fill_check": (j.payload or {}).get("fill_check") or [],
        # batch-1123-a F9: which reader confirms the save ("unsupported": Juli shows Chưa thấy)
        "readback": readback_of(j.kind),
        # F5: an empty Deal Sốc left on Shopee after step 1 was saved
        "notice": DEAL_ABANDONED if deal_abandoned(j) else None,
        # D5: a save no reader confirms is never a read-back match
        "status_note": SAVED_NOT_READ
        if j.status in (STATUS_SAVED, STATUS_CAPTURED) and saved_only(j)
        else None,
    }


async def resolve_voucher_captures(session: AsyncSession, shop_id: uuid.UUID) -> int:
    """Fallback capture (D85.6): the Connector's voucher list reader has posted the new voucher
    (``extra.voucher_code`` ENDS WITH our code suffix): its ``voucher_id``
    becomes the filled / saved job's ``captured_ref``. Nothing is typed by the person."""
    pending = (
        await session.scalars(
            select(ShopeeFillJob).where(
                ShopeeFillJob.shop_id == shop_id,
                ShopeeFillJob.kind == "voucher",
                ShopeeFillJob.status.in_((STATUS_FILLED, STATUS_SAVED)),
            )
        )
    ).all()
    if not pending:
        return 0
    rows = (
        await session.scalars(
            select(PlatformPromotion)
            .where(PlatformPromotion.shop_id == shop_id, PlatformPromotion.promo_type == "voucher")
            .order_by(PlatformPromotion.captured_at.desc())
            .limit(400)
        )
    ).all()
    codes: list[tuple[str, str]] = []  # (full code, voucher id), newest capture first
    for r in rows:
        extra = r.extra or {}
        vid, vcode = extra.get("voucher_id"), str(extra.get("voucher_code") or "").upper()
        if vid is not None and vcode:
            codes.append((vcode, str(vid)))
    done = 0
    for j in pending:
        # Seller Centre prefixes the code with a shop-specific prefix: match by the suffix typed
        suffix = str((j.payload or {}).get("code_suffix") or "").upper()
        found = next((vid for code, vid in codes if suffix and code.endswith(suffix)), None)
        if found and _REF.match(found):
            j.captured_ref, j.status = found, STATUS_CAPTURED
            j.updated_at = datetime.now(UTC).replace(tzinfo=None)
            done += 1
    if done:
        await session.flush()
    return done


def _naive_now(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).replace(tzinfo=None)


def _live_tokens(shop_id: uuid.UUID, now: datetime) -> Any:
    """The shop's tokens that can still poll (not revoked, superseded or expired)."""
    return select(IngestToken.id).where(
        IngestToken.shop_id == shop_id,
        IngestToken.revoked_at.is_(None),
        IngestToken.superseded_at.is_(None),
        IngestToken.expires_at > now,
    )


#: The card statuses whose fill jobs the Connector may be served. ONE place: F3 adds the revert
#: jobs of executed cards here (batch-1118f F1.2).
SERVABLE_CARD_STATUSES: tuple[str, ...] = (STATUS_APPROVED, STATUS_PLANNED)
REVERT_PREFIX = "revert:"
READBACK_PREFIX = "readback:"


def is_aux(j: ShopeeFillJob) -> bool:
    """A revert or read-back job: never part of the forward checklist, progress or state."""
    return j.target_key.startswith((REVERT_PREFIX, READBACK_PREFIX))


def _servable_card_jobs() -> Any:
    """SQL condition: the job may be served. An approved / planned card serves its forward jobs
    (and read-backs); an EXECUTED card serves only its revert and read-back jobs (batch-1118g
    F3: ``target_key`` prefixes ``revert:`` / ``readback:``); withdrawn, reverted or superseded
    cards serve nothing."""
    key = ShopeeFillJob.target_key

    def card(*statuses: str) -> Any:
        return ShopeeFillJob.proposal_id.in_(
            select(ShopProposal.id).where(ShopProposal.status.in_(statuses))
        )

    revert, readback = key.like(f"{REVERT_PREFIX}%"), key.like(f"{READBACK_PREFIX}%")
    return or_(
        and_(card(*SERVABLE_CARD_STATUSES), ~revert),
        and_(card(STATUS_EXECUTED), or_(revert, readback)),
    )


async def cancel_open_jobs(
    session: AsyncSession, shop_id: uuid.UUID, proposal_id: uuid.UUID, *, now: datetime
) -> int:
    """Cancel the card's open fill jobs (queued / opened / filled / saved). A withdrawn, reverted
    or superseded card must not be worked on any more. Returns the number cancelled."""
    n = 0
    rows = await session.scalars(
        select(ShopeeFillJob).where(
            ShopeeFillJob.shop_id == shop_id,
            ShopeeFillJob.proposal_id == proposal_id,
            ShopeeFillJob.status.in_(OPEN_STATUSES),
        )
    )
    for j in rows:
        j.status = STATUS_CANCELLED
        j.updated_at = _naive_now(now)
        n += 1
    await session.flush()
    return n


async def _claim(
    session: AsyncSession, shop_id: uuid.UUID, token_id: uuid.UUID, now: datetime, limit: int
) -> list[uuid.UUID]:
    """Lease the open jobs ``token_id`` may work on (its own, unclaimed, expired, or held by a
    dead token), oldest approval first, in one statement; rows another poll is claiming right now
    are skipped (``SKIP LOCKED``)."""
    claimable = (
        select(ShopeeFillJob.id)
        .where(
            ShopeeFillJob.shop_id == shop_id,
            ShopeeFillJob.status.in_(OPEN_STATUSES),
            _servable_card_jobs(),
            or_(
                ShopeeFillJob.claimed_by_token_id.is_(None),
                ShopeeFillJob.claimed_by_token_id == token_id,
                ShopeeFillJob.lease_until.is_(None),
                ShopeeFillJob.lease_until <= now,
                ShopeeFillJob.claimed_by_token_id.not_in(_live_tokens(shop_id, now)),
            ),
        )
        .order_by(ShopeeFillJob.created_at, ShopeeFillJob.seq)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    claimed = await session.execute(
        update(ShopeeFillJob)
        .where(ShopeeFillJob.id.in_(claimable))
        .values(claimed_by_token_id=token_id, lease_until=now + FILL_LEASE)
        .returning(ShopeeFillJob.id)
        .execution_options(synchronize_session=False)
    )
    return [row[0] for row in claimed.all()]


async def jobs_for_shop(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    limit: int = 20,
    token_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Jobs the Connector may still work on, oldest approval first (the route checks the switch).
    With the polling ``token_id`` only the jobs it now holds (claimed or extended) are served."""
    await resolve_voucher_captures(session, shop_id)
    await resolve_voucher_captures(session, shop_id)
    query = (
        select(ShopeeFillJob, ShopProposal.code, ShopProposal.subject_label)
        .join(ShopProposal, ShopProposal.id == ShopeeFillJob.proposal_id)
        .where(
            ShopeeFillJob.shop_id == shop_id,
            ShopeeFillJob.status.in_(OPEN_STATUSES),
            _servable_card_jobs(),
        )
        .order_by(ShopeeFillJob.created_at, ShopeeFillJob.seq)
        .limit(limit)
    )
    if token_id is not None:
        ids = await _claim(session, shop_id, token_id, _naive_now(now), limit)
        if not ids:
            return []
        query = query.where(ShopeeFillJob.id.in_(ids)).execution_options(populate_existing=True)
    rows = (await session.execute(query)).all()
    return [job_json(j, c, t) for j, c, t in rows]


async def _held_by_other(
    session: AsyncSession, j: ShopeeFillJob, token_id: uuid.UUID, now: datetime
) -> bool:
    """Another live token holds ``j`` under an unexpired lease."""
    holder = j.claimed_by_token_id
    if holder is None or holder == token_id or j.lease_until is None or j.lease_until <= now:
        return False
    live = await session.scalar(
        _live_tokens(j.shop_id, now).where(IngestToken.id == holder).limit(1)
    )
    return live is not None


async def jobs_of_card(
    session: AsyncSession, shop_id: uuid.UUID, proposal_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Every job of a card (the Demo checklist), approval order."""
    await resolve_voucher_captures(session, shop_id)
    await resolve_voucher_captures(session, shop_id)
    rows = (
        await session.scalars(
            select(ShopeeFillJob)
            .where(ShopeeFillJob.shop_id == shop_id, ShopeeFillJob.proposal_id == proposal_id)
            .order_by(ShopeeFillJob.version, ShopeeFillJob.seq)
        )
    ).all()
    return [job_json(j) for j in rows]


async def report(
    session: AsyncSession,
    shop_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    status: str,
    captured_ref: str | None = None,
    error: str | None = None,
    progress: dict[str, int] | None = None,
    before_values: dict[str, str] | None = None,
    period_ok: bool | None = None,
    field_checks: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
    token_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """The Connector's progress on one job (own shop only). ``progress`` (``{filled, total}``,
    Connector 0.3.18) is kept in ``payload["progress"]`` for Thực hiện's "3/4 đã điền".

    Connector 0.3.24 (batch-1117b X2): ``before_values`` (``{field_key: value}``, what each field
    held before the Connector wrote it) is merged into ``payload["before_values"]`` with the FIRST
    capture of a key kept (a second open of the page would otherwise record Juli's own value as
    the "before"); ``period_ok`` (False: the form's period was not filled to the card's dates) and
    ``field_checks`` (``[{key, ok, seen}]``, the last read of every field) replace the previous
    report's. No migration: all of it lives in the job's JSON payload.

    R7: with the reporting ``token_id``, a job another live token holds under its lease is refused
    (409 ``fill_job_leased``); otherwise the reporter holds it and the lease is extended."""
    moment = _naive_now(now)
    j = await session.scalar(
        select(ShopeeFillJob)
        .where(ShopeeFillJob.id == job_id, ShopeeFillJob.shop_id == shop_id)
        .with_for_update()
    )
    if j is None:
        raise ProposalError(ERROR_JOB_UNKNOWN, 404)
    if token_id is not None:
        if await _held_by_other(session, j, token_id, moment):
            raise ProposalError(ERROR_JOB_LEASED, 409)
        j.claimed_by_token_id = token_id
        j.lease_until = moment + FILL_LEASE
    if captured_ref is not None and not _REF.match(captured_ref):
        raise ProposalError(ERROR_JOB_BAD, 422)
    allowed = set(_NEXT.get(j.status, set()))
    if j.kind == "readback" and j.status in (STATUS_QUEUED, STATUS_OPENED):
        allowed.add(STATUS_CAPTURED)  # a read-back posts its dataset and is done
    if status not in allowed and status != j.status:
        raise ProposalError(ERROR_JOB_STATE, 409, f"{j.status} -> {status}")
    if progress is not None:
        if progress["filled"] > progress["total"]:
            raise ProposalError(ERROR_JOB_BAD, 422)
        j.payload = {
            **(j.payload or {}),
            "progress": {"filled": progress["filled"], "total": progress["total"]},
        }
    if before_values or period_ok is not None or field_checks is not None:
        payload = dict(j.payload or {})
        if before_values:
            kept = dict(payload.get("before_values") or {})
            for key, value in before_values.items():
                kept.setdefault(key, value)
            payload["before_values"] = kept
        if period_ok is not None:
            payload["period_ok"] = period_ok
        if field_checks is not None:
            payload["fill_check"] = field_checks
        j.payload = payload
    if status != STATUS_FAILED and promotion_locked(field_checks):
        # F7: the product page greys the field (a running promotion): the job ends, nothing saved
        status, error = STATUS_FAILED, PROMOTION_LOCKED
    j.status = status
    if captured_ref is not None:
        j.captured_ref = captured_ref
    if status == STATUS_FAILED:
        j.error = (error or "failed")[:64]
    j.updated_at = moment
    await session.flush()
    if j.target_key.startswith(READBACK_PREFIX):
        return job_json(j)
    if j.target_key.startswith(REVERT_PREFIX):
        if status in (STATUS_SAVED, STATUS_CAPTURED):  # F3.2: read the object back again
            from juli_backend.services.shopee_recommendations import revert_fill

            await revert_fill.queue_readback_after_revert(session, shop_id, j, now=j.updated_at)
        return job_json(j)
    if status in (STATUS_SAVED, STATUS_CAPTURED):
        await auto_execute(session, shop_id, j.proposal_id, now=j.updated_at)
    return job_json(j)


async def auto_execute(
    session: AsyncSession, shop_id: uuid.UUID, proposal_id: uuid.UUID, *, now: datetime
) -> bool:
    """The Connector saw Shopee accept the save of EVERY page of the card: record "Đã làm" itself
    (the same ``mark_executed`` as the button, so the read-back starts) and let the existing
    read-back decide khớp / lệch; the measurement clock starts at the match. Idempotent (a card
    that is no longer ``approved`` is left alone), a voucher still waiting for its captured id
    waits for the next report, and it never runs inside a reviewer request."""
    if not enabled():
        return False
    from juli_backend.services.shopee_recommendations import service

    latest = await session.scalar(
        select(func.max(ShopeeFillJob.version)).where(
            ShopeeFillJob.shop_id == shop_id,
            ShopeeFillJob.proposal_id == proposal_id,
            ~ShopeeFillJob.target_key.like(f"{REVERT_PREFIX}%"),
            ~ShopeeFillJob.target_key.like(f"{READBACK_PREFIX}%"),
        )
    )
    jobs = (
        await session.scalars(
            select(ShopeeFillJob).where(
                ShopeeFillJob.shop_id == shop_id,
                ShopeeFillJob.proposal_id == proposal_id,
                ShopeeFillJob.version == latest,
                ShopeeFillJob.status != STATUS_CANCELLED,
                ~ShopeeFillJob.target_key.like(f"{REVERT_PREFIX}%"),
                ~ShopeeFillJob.target_key.like(f"{READBACK_PREFIX}%"),
            )
        )
    ).all()
    if not jobs or any(j.status not in (STATUS_SAVED, STATUS_CAPTURED) for j in jobs):
        return False
    approver = await session.scalar(
        select(ShopProposalApproval.decided_by_user_id)
        .where(
            ShopProposalApproval.shop_id == shop_id,
            ShopProposalApproval.proposal_id == proposal_id,
            ShopProposalApproval.decision == "approved",
            ShopProposalApproval.decided_by_user_id.is_not(None),
        )
        .order_by(ShopProposalApproval.decided_at.desc())
        .limit(1)
    )
    if approver is None:  # an execution is recorded under a person: the one who approved
        return False
    try:
        async with session.begin_nested():
            await service.mark_executed(
                session,
                shop_id,
                proposal_id,
                now=now,
                user_id=approver,
                payload_extra={"auto": True, "source": "connector"},
                auto_plan=True,
            )
    except ProposalError as exc:  # already executed (bad state) or a voucher id still missing
        logger.info("fill_auto_execute_skipped", extra={"code": exc.code})
        return False
    return True


async def cancel(session: AsyncSession, shop_id: uuid.UUID, job_id: uuid.UUID) -> dict[str, Any]:
    j = await session.scalar(
        select(ShopeeFillJob).where(ShopeeFillJob.id == job_id, ShopeeFillJob.shop_id == shop_id)
    )
    if j is None:
        raise ProposalError(ERROR_JOB_UNKNOWN, 404)
    if j.status in (STATUS_CAPTURED, STATUS_CANCELLED):
        raise ProposalError(ERROR_JOB_STATE, 409)
    j.status = STATUS_CANCELLED
    await session.flush()
    return job_json(j)


#: the voucher form's fill_check keys -> the fields the read-back compares (verification)
_SEEN_FIELD = {"min_spend": "min_spend", "usage_total": "usage_limit"}


async def seen_voucher_values(
    session: AsyncSession, shop_id: uuid.UUID, proposal_id: uuid.UUID
) -> dict[str, int]:
    """F2.3 / E46: what the Connector last read on the SAVED voucher form where it differs from
    what Juli filled (the person changed it by hand): ``{expected field: number}``. Empty when
    every field matches or the Connector read nothing."""
    j = await session.scalar(
        select(ShopeeFillJob)
        .where(
            ShopeeFillJob.shop_id == shop_id,
            ShopeeFillJob.proposal_id == proposal_id,
            ShopeeFillJob.kind == "voucher",
            ~ShopeeFillJob.target_key.like(f"{REVERT_PREFIX}%"),
        )
        .order_by(ShopeeFillJob.updated_at.desc())
        .limit(1)
    )
    out: dict[str, int] = {}
    for check in ((j.payload or {}).get("fill_check") or []) if j else []:
        name = _SEEN_FIELD.get(str(check.get("key")))
        digits = re.sub(r"\D", "", str(check.get("seen") or ""))
        if name and check.get("ok") is False and digits:
            out[name] = int(digits)
    return out


async def captured_ref_of(
    session: AsyncSession, shop_id: uuid.UUID, proposal_id: uuid.UUID, kind: str
) -> str | None:
    """The id the Connector captured after the person saved (newest first), so read-back
    starts without the person typing it (``mark_executed`` falls back to this)."""
    return await session.scalar(
        select(ShopeeFillJob.captured_ref)
        .where(
            ShopeeFillJob.shop_id == shop_id,
            ShopeeFillJob.proposal_id == proposal_id,
            ShopeeFillJob.kind == kind,
            ShopeeFillJob.captured_ref.is_not(None),
        )
        .order_by(ShopeeFillJob.updated_at.desc())
        .limit(1)
    )
