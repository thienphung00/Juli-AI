"""Cards done outside Juli, read from the owner's sheet (pure): "Nhập thẻ đã làm ngoài Juli".

The file is untrusted input. :func:`read_sheet` opens it with openpyxl in read-only mode after
the size and zip checks (and refuses any XML part declaring a DTD or an entity), finds the header
row ("STT", "Mã", "Hạng mục" ...), and reads only the allowlisted columns of each data row; every
other column is never decoded. Reading stops at the first blank row (the sheet's own summary
block below the rows is not read) or at ``config.EXTERNAL_IMPORT_MAX_ROWS``.

:func:`plan_row` turns one row into the builder specs (``shopee_builder.specs``) of the card(s)
it becomes, the same specs a Tự tạo card is chosen from, or a skip reason. The Hạng mục ->
change kind map and the skip list are config (``shopee_recommendations.config``).
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from juli_backend.services.planned_changes import rows as pr
from juli_backend.services.shop_inputs import xlsx_io
from juli_backend.services.shopee_analytics.fee_table import fold
from juli_backend.services.shopee_recommendations import config
from juli_backend.services.shopee_recommendations.kinds import KINDS

SHEET = "Tổng hợp đề xuất"
MAX_FILE_BYTES = xlsx_io.MAX_FILE_BYTES
MAX_UNCOMPRESSED_BYTES = xlsx_io.MAX_UNCOMPRESSED_BYTES
MAX_CELL_CHARS = 2000
HEADER_SCAN_ROWS = 12

#: folded header -> field (the allowlist: no other column is ever read)
HEADERS: Mapping[str, str] = {
    "stt": "stt",
    "ma": "ref",
    "hang muc": "category",
    "ma sp": "items",
    "phuong an": "plan",
    "du lieu cu the": "data",
    "ngay thuc hien": "on",
    "trang thai": "status",
    "thoi gian do ngay": "days",
    "chi tiet trang thai": "detail",
}
REQUIRED: tuple[str, ...] = ("ref", "category", "items", "plan", "on", "status", "days")

STATUS_DONE = "done"
STATUS_RUNNING = "running"
STATUS_PROPOSED = "proposed"
STATUS_CANCELLED = "cancelled"
STATUS_UNKNOWN = "unknown"
STATUS_LABELS: Mapping[str, str] = {
    STATUS_DONE: "Đã thực hiện",
    STATUS_RUNNING: "Đang thử nghiệm",
    STATUS_PROPOSED: "Đề xuất",
    STATUS_CANCELLED: "Đã huỷ",
    STATUS_UNKNOWN: "Không rõ",
}
EXECUTED_STATUSES = (STATUS_DONE, STATUS_RUNNING)

SKIP_LABELS: Mapping[str, str] = {
    "nothing_to_measure": "Không có gì để đo (nghiên cứu / báo cáo / trao đổi / cài đặt)",
    "cancelled": "Đã huỷ",
    "unknown_category": "Hạng mục chưa có loại thẻ trong Juli",
    "unknown_status": "Không đọc được trạng thái",
    "no_item": "Cần một mã sản phẩm",
    "no_date": "Thiếu ngày thực hiện",
    "future_execution": "Ngày thực hiện chưa tới",
    "no_title": "Không có tiêu đề mới (dòng 'Sau:')",
    "no_voucher": "Không đọc được mức voucher (giảm ... cho đơn từ ...)",
    "no_roas": "Không đọc được ROAS mục tiêu",
    "no_campaign": "Không tìm thấy chiến dịch quảng cáo của dòng này",
    "no_price": "Không đọc được giá mới",
    "variation_unknown": "Không xác định được phân loại",
    "no_tiers": "Không đọc được các bậc combo (mua N giảm X%)",
    "no_addon": "Cần sản phẩm chính và sản phẩm mua kèm",
    "no_gift_cost": "Không đọc được chi phí quà",
    "no_commission": "Không đọc được % hoa hồng",
    "invalid_spec": "Các giá trị không hợp lệ",
    "duplicate_ref": "Mã bị trùng trong tệp",
    "exists": "Đã nhập trước đó",
    "build_failed": "Không tạo được thẻ",
}


class SheetError(ValueError):
    """The file cannot be read as the import sheet at all."""


@dataclass(frozen=True)
class SheetRow:
    row: int
    ref: str
    category: str
    items: tuple[str, ...]
    shop_wide: bool
    plan: str
    data: str
    on: date | None
    status: str
    status_text: str
    days: int | None
    detail: str = ""

    @property
    def category_key(self) -> str:
        return _key(self.category)


@dataclass(frozen=True)
class CardPlan:
    """One card a row becomes: its own ``external_ref``, the change kind and the builder spec."""

    ref: str
    kind: str
    spec: dict[str, Any]


@dataclass
class RowPlan:
    row: SheetRow
    cards: list[CardPlan] = field(default_factory=list)
    skip: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class Campaign:
    key: str
    name: str
    products: tuple[str, ...] = ()
    spend: float = 0.0


@dataclass(frozen=True)
class Facts:
    """What the row specs need from the shop: today, the ads campaigns, the variations."""

    today: date
    campaigns: Sequence[Campaign] = ()
    #: item id -> [{"variation_id", "name"}]
    variations: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=dict)


# ------------------------------------------------------------------------------- reading


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9+]+", " ", fold(text)).strip()


def _check_archive(data: bytes) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise SheetError("file too large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SheetError("not an .xlsx file") from None
    with archive:
        infos = archive.infolist()
        if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
            raise SheetError("file too large once unpacked")
        if "xl/workbook.xml" not in {i.filename for i in infos}:
            raise SheetError("not an .xlsx file")
        for info in infos:
            if not info.filename.endswith((".xml", ".rels")):
                continue
            head = archive.read(info.filename)
            if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
                raise SheetError("the workbook declares a DTD")


def _text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, int | str):
        return str(value).strip()[:MAX_CELL_CHARS]
    return ""


def _day(value: Any, today: date) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    return pr.parse_date(text, today) if text else None


def _days(value: Any) -> int | None:
    text = _text(value).replace(",", ".")
    try:
        n = int(float(text))
    except ValueError:
        return None
    return n if 1 <= n <= 365 else None


def parse_status(text: str) -> str:
    t = _key(text)
    if "huy" in t.split():
        return STATUS_CANCELLED
    if t.startswith("da thuc hien"):
        return STATUS_DONE
    if t.startswith("dang thu nghiem") or t.startswith("dang chay"):
        return STATUS_RUNNING
    if t.startswith("de xuat") or t.startswith("cho"):
        return STATUS_PROPOSED
    return STATUS_UNKNOWN


def parse_items(text: str) -> tuple[tuple[str, ...], bool]:
    """``(item ids, shop-wide)``: "Toàn shop (gồm 6 SP)" and "*" are the whole shop."""
    t = fold(text)
    if t.startswith("toan shop") or t.strip() == "*":
        return (), True
    return tuple(dict.fromkeys(re.findall(r"\d{3,}", text))), False


def _header(rows: Sequence[Sequence[Any]]) -> tuple[int, dict[str, int]] | None:
    for n, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        cols: dict[str, int] = {}
        for i, cell in enumerate(row):
            name = HEADERS.get(_key(_text(cell)))
            if name and name not in cols:
                cols[name] = i
        if {"ref", "category"} <= cols.keys():
            return n, cols
    return None


def rows_from_cells(
    cells: Sequence[Sequence[Any]], today: date
) -> tuple[list[SheetRow], list[str]]:
    """``(rows, missing required columns)`` from the raw cell values of the sheet."""
    found = _header(cells)
    if found is None:
        return [], list(REQUIRED)
    start, cols = found
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        return [], missing

    def cell(row: Sequence[Any], name: str) -> Any:
        i = cols.get(name)
        return row[i] if i is not None and i < len(row) else None

    out: list[SheetRow] = []
    for n, row in enumerate(cells[start + 1 :], start=start + 2):
        ref = _text(cell(row, "ref"))
        category = _text(cell(row, "category"))
        if not ref and not category:
            break  # the first blank row ends the table
        if len(out) >= config.EXTERNAL_IMPORT_MAX_ROWS:
            raise SheetError("too many rows")
        items, shop_wide = parse_items(_text(cell(row, "items")))
        status_text = _text(cell(row, "status"))
        out.append(
            SheetRow(
                row=n,
                ref=ref[:64],
                category=category,
                items=items,
                shop_wide=shop_wide,
                plan=_text(cell(row, "plan")),
                data=_text(cell(row, "data")),
                on=_day(cell(row, "on"), today),
                status=parse_status(status_text),
                status_text=status_text,
                days=_days(cell(row, "days")),
                detail=_text(cell(row, "detail")),
            )
        )
    return out, []


def read_sheet(data: bytes, today: date) -> tuple[list[SheetRow], list[str]]:
    """Open the workbook (openpyxl, read-only, values only) and read the import sheet."""
    _check_archive(data)
    import zipfile

    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    unreadable = (InvalidFileException, zipfile.BadZipFile, KeyError, ValueError, OSError)
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except unreadable as exc:  # a reader failure is "not a readable sheet"
        raise SheetError(f"unreadable workbook ({type(exc).__name__})") from None
    try:
        ws = wb[SHEET] if SHEET in wb.sheetnames else wb.active
        if ws is None:
            raise SheetError("the workbook has no sheet")
        cells: list[tuple[Any, ...]] = []
        for row in ws.iter_rows(values_only=True):
            cells.append(row)
            if len(cells) > config.EXTERNAL_IMPORT_MAX_ROWS + HEADER_SCAN_ROWS + 1:
                break
            if len(cells) > HEADER_SCAN_ROWS and not any(v is not None for v in row[:3]):
                break
        return rows_from_cells(cells, today)
    finally:
        wb.close()


# ------------------------------------------------------------------------------- planning


def _skipped(row: SheetRow) -> str | None:
    if row.ref.upper() in {r.upper() for r in config.EXTERNAL_IMPORT_SKIP_REFS}:
        return "nothing_to_measure"
    plan = _key(row.plan)
    if any(plan.startswith(p) for p in config.EXTERNAL_IMPORT_SKIP_PHRASES):
        return "nothing_to_measure"
    return None


def _money(text: str) -> int | None:
    return pr.parse_money(text.strip().rstrip(".").replace("đ", "").replace("₫", ""))


_MONEY = r"(\d[\d.,]*\s*(?:k|tr|đ|d)?)"


def voucher_tiers(text: str) -> list[tuple[int, int]]:
    """``[(value, min_spend)]``: "giảm 7.500đ cho đơn từ 149.000đ" or "179k giảm 8k / 269k …"."""
    out: list[tuple[int, int]] = []
    for value, minimum in re.findall(rf"giảm\s*{_MONEY}\s*cho đơn từ\s*{_MONEY}", text, re.I):
        v, m = _money(value), _money(minimum)
        if v and m:
            out.append((v, m))
    if not out:
        for minimum, value in re.findall(rf"{_MONEY}\s*giảm\s*{_MONEY}", text, re.I):
            v, m = _money(value), _money(minimum)
            if v and m and v < m:
                out.append((v, m))
    return out


def _number(text: str) -> float | None:
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def roas_target(plan: str, data: str) -> float | None:
    """The ROAS target: "ROAS mục tiêu X" / "Mục tiêu X", "ROAS X từ <day>", else the plan's first
    "ROAS X" (never a "ROAS hoà vốn" or today's reading in the data)."""
    num = r"(\d+(?:[.,]\d+)?)"
    for text in (data, plan):
        m = re.search(rf"(?:roas\s*)?mục tiêu\s*{num}", text, re.I)
        if m:
            return _number(m.group(1))
    m = re.search(rf"roas\s*{num}\s*từ", data, re.I)
    if m:
        return _number(m.group(1))
    m = re.search(rf"roas\s*{num}", plan, re.I)
    return _number(m.group(1)) if m else None


def pick_campaign(row: SheetRow, campaigns: Sequence[Campaign]) -> Campaign | None:
    """By the campaign's name in the plan ("CDN/01"), else the busiest campaign of the product."""
    token = re.search(r"\b([A-Za-z]{2,6}/\d+)\b", row.plan)
    if token:
        want = fold(token.group(1))
        named = [c for c in campaigns if want in fold(c.name)]
        if named:
            return named[0]
    holding = [c for c in campaigns if any(i in c.products for i in row.items)]
    return max(holding, key=lambda c: c.spend) if holding else None


def new_title(data: str) -> str | None:
    for line in data.splitlines():
        m = re.match(r"\s*sau\s*:\s*(.+)$", fold(line))
        if m:
            text = line.split(":", 1)[1].strip()
            return text[: config.MAX_TITLE_CHARS] or None
    return None


def _pct_all(text: str) -> list[tuple[int, float]]:
    return [
        (int(q), float(v.replace(",", ".")))
        for q, v in re.findall(r"mua\s*(\d+)\s*giảm\s*(\d+(?:[.,]\d+)?)\s*%", text, re.I)
    ]


def _window(row: SheetRow) -> dict[str, str]:
    if row.on is None:
        return {}
    days = row.days or 1
    return {"start": row.on.isoformat(), "end": (row.on + timedelta(days=days - 1)).isoformat()}


def _variation(row: SheetRow, facts: Facts, item: str) -> str | None:
    rows = list(facts.variations.get(item) or [])
    label = _key(row.plan.split(":", 1)[0]) if ":" in row.plan else ""
    if label:
        for r in rows:
            if label and label in _key(str(r.get("name") or "")):
                return str(r.get("variation_id") or "")
    if len(rows) <= 1:
        return ""
    return None


def _specs(row: SheetRow, facts: Facts, kinds: tuple[str, ...]) -> list[CardPlan] | str:
    head = kinds[0]
    text = f"{row.plan}\n{row.data}"
    item = row.items[0] if row.items else None
    needs_item = head not in ("min_spend_voucher", "ads_roas_target")
    if needs_item and item is None:
        return "no_item"
    assert item is not None or not needs_item
    if head == "title":
        title = new_title(row.data)
        if title is None:
            return "no_title"
        return [CardPlan(row.ref, "title", {"kind": "title", "item_id": item, "title": title})]
    if head == "cover_image":
        hook = re.sub(r"\s+", " ", row.plan).strip()[:60] or "Ảnh bìa mới"
        out = [
            CardPlan(
                row.ref,
                "cover_image",
                {
                    "kind": "cover_image",
                    "item_id": item,
                    "overlay": {"layout": "banner_top", "hook_text": hook},
                },
            )
        ]
        title = new_title(row.data)
        if title is not None and "title" in kinds:
            out.append(
                CardPlan(
                    f"{row.ref}/TD", "title", {"kind": "title", "item_id": item, "title": title}
                )
            )
        return out
    if head == "min_spend_voucher":
        tiers = voucher_tiers(row.plan) or voucher_tiers(row.data)
        if not tiers:
            return "no_voucher"
        base: dict[str, Any] = {"kind": "voucher", "discount_type": "amount", **_window(row)}
        if row.items and not row.shop_wide:
            base.update({"scope": "product", "item_ids": list(row.items)})
        else:
            base["scope"] = "shop"
        return [
            CardPlan(
                row.ref if len(tiers) == 1 else f"{row.ref}/{n}",
                "min_spend_voucher",
                {**base, "value": value, "min_spend": minimum},
            )
            for n, (value, minimum) in enumerate(tiers, start=1)
        ]
    if head == "ads_roas_target":
        roas = roas_target(row.plan, row.data)
        if roas is None or roas <= 0:
            return "no_roas"
        camp = pick_campaign(row, facts.campaigns)
        if camp is None:
            return "no_campaign"
        spec = {
            "kind": "ads",
            "lever": "roas",
            "campaign_key": camp.key,
            "roas_mode": "custom",
            "roas_target": roas,
            **_window(row),
        }
        return [CardPlan(row.ref, "ads_roas_target", spec)]
    if head == "price":
        prices = [_money(m) for m in re.findall(rf"→\s*{_MONEY}", row.plan)]
        price = next((p for p in reversed(prices) if p), None)
        if price is None:
            return "no_price"
        assert item is not None
        variation = _variation(row, facts, item)
        if variation is None:
            return "variation_unknown"
        spec = {
            "kind": "price",
            "item_id": item,
            "variations": [{"variation_id": variation, "final_price": price}],
        }
        return [CardPlan(row.ref, "price", spec)]
    if head == "bundle_deal":
        combo_tiers = _pct_all(text)
        if not combo_tiers:
            return "no_tiers"
        spec = {
            "kind": "combo",
            "item_ids": [item],
            "discount_type": "pct",
            "tiers": [{"qty": q, "value": v} for q, v in sorted(combo_tiers)],
            **_window(row),
        }
        return [CardPlan(row.ref, "bundle_deal", spec)]
    if head == "add_on" and (len(row.items) >= 2 or "tặng" not in row.plan.lower()):
        if len(row.items) < 2:
            return "no_addon"
        m = re.search(r"giảm\s*(\d+(?:[.,]\d+)?)\s*%", row.plan, re.I)
        addon: dict[str, Any] = {"item_id": row.items[1]}
        if m:
            addon["pct"] = float(m.group(1).replace(",", "."))
        else:
            return "no_addon"
        spec = {"kind": "add_on", "main_item_id": item, "addons": [addon], **_window(row)}
        return [CardPlan(row.ref, "add_on", spec)]
    if head in ("add_on", "gift"):
        m = re.search(rf"{_MONEY}\s*quà", text, re.I) or re.search(
            rf"giá vốn[^\d]*{_MONEY}", text, re.I
        )
        cost = _money(m.group(1)) if m else None
        if not cost:
            return "no_gift_cost"
        g = re.search(r"tặng\s*(?:\d+\s*)?([^·|\n]+)", row.plan, re.I)
        label = (g.group(1).strip() if g else "Quà tặng")[:80]
        spec = {
            "kind": "gift",
            "gift": {"unit_cost": cost, "label": label, "qty": 1},
            "trigger": {"type": "buy_item", "item_id": item},
            **_window(row),
        }
        return [CardPlan(row.ref, "gift", spec)]
    if head == "affiliate_commission":
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", row.plan)
        if not m:
            return "no_commission"
        target = _key(row.plan).startswith("chien dich muc tieu")
        spec = {
            "kind": "affiliate",
            "item_id": item,
            "commission_pct": float(m.group(1).replace(",", ".")),
            "target_campaign": target,
        }
        kind = "affiliate_target_campaign" if target else "affiliate_commission"
        return [CardPlan(row.ref, kind, spec)]
    return "unknown_category"


def plan_row(row: SheetRow, facts: Facts) -> RowPlan:
    """The card(s) one row becomes, or why it is skipped."""
    if row.status == STATUS_CANCELLED:
        return RowPlan(row, skip="cancelled")
    why = _skipped(row)
    if why:
        return RowPlan(row, skip=why)
    kinds = config.EXTERNAL_IMPORT_KINDS.get(row.category_key)
    if not kinds or any(k not in KINDS for k in kinds):
        return RowPlan(row, skip="unknown_category")
    if row.status == STATUS_UNKNOWN:
        return RowPlan(row, skip="unknown_status")
    if row.status in EXECUTED_STATUSES:
        if row.on is None:
            return RowPlan(row, skip="no_date")
        if row.on > facts.today:
            return RowPlan(row, skip="future_execution")
    got = _specs(row, facts, kinds)
    if isinstance(got, str):
        return RowPlan(row, skip=got)
    return RowPlan(row, cards=got)


def plan_rows(rows: Sequence[SheetRow], facts: Facts) -> list[RowPlan]:
    out: list[RowPlan] = []
    seen: set[str] = set()
    for row in rows:
        if not row.ref or row.ref in seen:
            out.append(RowPlan(row, skip="duplicate_ref"))
            continue
        seen.add(row.ref)
        out.append(plan_row(row, facts))
    return out


__all__ = [
    "SHEET",
    "SKIP_LABELS",
    "STATUS_LABELS",
    "Campaign",
    "CardPlan",
    "Facts",
    "RowPlan",
    "SheetError",
    "SheetRow",
    "new_title",
    "parse_status",
    "plan_row",
    "plan_rows",
    "read_sheet",
    "roas_target",
    "rows_from_cells",
    "voucher_tiers",
]
