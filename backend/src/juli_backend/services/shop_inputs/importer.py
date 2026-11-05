"""Parse, validate, diff and apply the seller-input template (P90 step 4).

``preview`` reads the workbook and checks every row ON ITS OWN: a bad row is rejected with
the column, the value and the reason, and keeps its old values; good rows go on to the
diff (old -> new per field). Nothing is written. ``apply`` re-reads the same file (the
service keeps no upload between calls), writes a version for every changed field of the
valid rows only -- one change set, one reason, one file hash -- and reports how many open
recommendations will be recomputed.

Rejections (``kind``): ``unknown_sku``, ``cost_ge_price``, ``cost_missing``,
``out_of_range``, ``bad_date``, ``duplicate_sku``, ``invalid_value``, ``bad_month``, and (P91 D-12)
``bad_pack`` (số món / phân loại), ``bad_vat`` (VAT %), ``unknown_component``, ``bom_self``,
``bad_quantity``, ``duplicate_component`` (sheet ``Thành phần combo``: a listing's bill of
materials is applied whole or not at all). An empty cell keeps the old value. Juli-filled columns
(tên, giá niêm yết) are not read. A ``số món`` equal to what Juli already reads from the variation
name ("Combo 3 hộp" = 3) is not a change.

P91 D-12 sheets: ``Thành phần combo`` (component SKU x quantity per listing without a SKU) and
``VAT`` (whether prices / giá vốn include VAT, shop-wide Có / Không).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shop_inputs import kol_samples, xlsx_io
from juli_backend.services.shop_inputs.affected import (
    STALE_REASON,
    AffectedRecommendations,
    StaleRequest,
    affected_recommendations,
    mark_stale,
)
from juli_backend.services.shop_inputs.catalogue import (
    FIELD_RULES,
    ITEM_FIELD_RULES,
    CatalogueSku,
    CurrentInputs,
    effective_stock,
    load_catalogue,
    load_current,
    split_scope,
)
from juli_backend.services.shop_inputs.template import (
    BOM_SHEET,
    EXCLUDE_REASON_LABELS,
    GOAL_COLUMNS,
    GOAL_SHEET,
    GROUP_LABELS,
    SKU_COLUMNS,
    SKU_SHEET,
    STATUS_LABELS,
    VAT_SETTINGS,
    VAT_SHEET,
    month_label,
)
from juli_backend.services.shop_inputs.versions import (
    Actor,
    RuleChange,
    clean_reason,
    write_versions,
)
from juli_backend.services.shop_rules.rules import (
    KOL_SAMPLE,
    MAX_COMPONENT_QTY,
    MAX_COMPONENTS,
    MAX_PACK_COUNT,
    MONTHLY_AOV,
    MONTHLY_GMV,
    MONTHLY_MARGIN_PCT,
    MONTHLY_MARKETING_CAP,
    MONTHLY_ORDERS,
    MONTHLY_RULE_KEYS,
    PACK_COMPONENTS,
    PACK_COUNT,
    SKU_COST,
    VAT_RATES_PCT,
    RuleValidationError,
    validate_rule,
)
from juli_backend.services.shopee_profit.pack import pack_count_from_name

#: Reasons the Áp dụng step offers as chips (any other text is accepted too).
SUGGESTED_REASONS: tuple[str, ...] = (
    "Giá nhập tháng 11",
    "Kiểm kho cuối tháng",
    "Sửa sai nhập liệu",
    "Khác",
)

KIND_LABELS: dict[str, str] = {
    "unknown_sku": "SKU lạ",
    "cost_ge_price": "Giá vốn ≥ giá",
    "cost_missing": "Giá vốn trống",
    "out_of_range": "Ngoài khoảng",
    "bad_date": "Ngày sai",
    "duplicate_sku": "Trùng SKU",
    "invalid_value": "Giá trị sai",
    "bad_month": "Tháng sai",
    "kol_missing": "Thiếu KOL",
    "bad_pack": "Số món sai",
    "bad_vat": "VAT sai",
    "unknown_component": "Thành phần lạ",
    "bom_self": "Thành phần trùng chính nó",
    "bad_quantity": "Số lượng sai",
    "duplicate_component": "Trùng thành phần",
}
FIELD_LABELS: dict[str, str] = {
    "cost": "Giá vốn",
    "packaging": "Đóng gói",
    "max_discount": "Giảm tối đa (%)",
    "stock": "Tồn kho",
    "restock": "Ngày nhập lại",
    "group": "Nhóm",
    "status": "Trạng thái",
    "pack": "Số món / phân loại",
    "vat": "VAT (%)",
    "excluded": "Loại trừ",
    "exclude_reason": "Lý do loại trừ",
    "bom": "Thành phần combo",
    "prices_include_vat": "Giá bán đã gồm VAT",
    "cost_includes_vat": "Giá vốn đã gồm VAT",
    MONTHLY_GMV: "GMV",
    MONTHLY_ORDERS: "Đơn",
    MONTHLY_AOV: "AOV",
    MONTHLY_MARGIN_PCT: "Biên mục tiêu (%)",
    MONTHLY_MARKETING_CAP: "Trần chi marketing/ngày",
}
FIELD_UNITS: dict[str, str] = {
    "cost": "vnd",
    "packaging": "vnd",
    "max_discount": "pct",
    "stock": "count",
    "restock": "date",
    "group": "group",
    "status": "status",
    "pack": "count",
    "vat": "pct",
    "excluded": "bool",
    "exclude_reason": "reason",
    "bom": "bom",
    "prices_include_vat": "bool",
    "cost_includes_vat": "bool",
    MONTHLY_GMV: "vnd",
    MONTHLY_ORDERS: "count",
    MONTHLY_AOV: "vnd",
    MONTHLY_MARGIN_PCT: "pct",
    MONTHLY_MARKETING_CAP: "vnd",
}
GOAL_MISMATCH_TOLERANCE = Decimal("0.05")


class ImportFileError(ValueError):
    """The file cannot be read as the template at all; the message is safe to show."""


class NothingToApply(ValueError):
    """The file holds no valid change."""


class FileMismatch(ValueError):
    """The file sent to apply is not the one that was checked."""


@dataclass(frozen=True)
class Rejection:
    sheet: str
    row: int
    sku: str
    column: str
    value: str
    reason: str
    kind: str

    @property
    def kind_label(self) -> str:
        return KIND_LABELS[self.kind]


@dataclass(frozen=True)
class FieldDiff:
    """One changed field of one SKU, or of one month."""

    scope_ref: str
    item_id: str
    variation_id: str
    sku: str
    field: str
    rule_key: str
    old: Any
    new: Any
    effect: str = ""

    @property
    def label(self) -> str:
        return FIELD_LABELS[self.field]

    @property
    def unit(self) -> str:
        return FIELD_UNITS[self.field]


@dataclass(frozen=True)
class GoalWarning:
    month: str
    message: str
    deviation: float


@dataclass
class ImportPreview:
    file_hash: str
    sku_rows: int = 0
    sku_rows_rejected: int = 0
    sku_rows_unchanged: int = 0
    sample_rows: int = 0
    sample_rows_rejected: int = 0
    sample_rows_unchanged: int = 0
    sample_diffs: list[kol_samples.SampleDiff] = field(default_factory=list)
    goal_rows: int = 0
    goal_rows_rejected: int = 0
    #: ``Thành phần combo``: component lines read / rejected; one diff per listing changed.
    bom_rows: int = 0
    bom_rows_rejected: int = 0
    rejections: list[Rejection] = field(default_factory=list)
    diffs: list[FieldDiff] = field(default_factory=list)
    goal_diffs: list[FieldDiff] = field(default_factory=list)
    bom_diffs: list[FieldDiff] = field(default_factory=list)
    #: ``VAT`` sheet: the shop-wide flags the file changes.
    shop_diffs: list[FieldDiff] = field(default_factory=list)
    warnings: list[GoalWarning] = field(default_factory=list)
    changes: list[RuleChange] = field(default_factory=list)

    @property
    def sku_rows_valid(self) -> int:
        return self.sku_rows - self.sku_rows_rejected

    @property
    def changed_scopes(self) -> list[str]:
        return sorted({d.scope_ref for d in (*self.diffs, *self.bom_diffs)})

    @property
    def sample_rows_valid(self) -> int:
        return self.sample_rows - self.sample_rows_rejected

    @property
    def changed_item_ids(self) -> list[str]:
        """Items whose open recommendations a valid change re-runs (SKU rows and samples)."""
        items = {split_scope(s)[0] for s in self.changed_scopes}
        items |= {d.item_id for d in self.sample_diffs}
        return sorted(items)

    @property
    def changed_months(self) -> list[str]:
        return sorted({d.scope_ref for d in self.goal_diffs})


# -- cell parsing -------------------------------------------------------------------------

_THOUSANDS_DOT = re.compile(r"^\d{1,3}(\.\d{3})+$")
_THOUSANDS_COMMA = re.compile(r"^\d{1,3}(,\d{3}){2,}$")
_SCIENTIFIC = re.compile(r"^[+-]?\d+(\.\d+)?[eE][+-]?\d+$")
_EXCEL_EPOCH = date(1899, 12, 30)


def _fold(text: str) -> str:
    """Lower-case without diacritics, for matching labels and headers."""
    decomposed = unicodedata.normalize("NFD", text.strip().lower().replace("đ", "d"))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _cell(row: list[str | None], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return (row[index] or "").strip()


def parse_number(text: str) -> Decimal:
    """``"104.000đ"``, ``"12,5"``, ``"100000"``, ``"1E5"`` -> ``Decimal``; ``ValueError`` else."""
    cleaned = re.sub(r"[\s ₫%]|đ$", "", text.strip())
    cleaned = cleaned.rstrip("đ")
    if not cleaned:
        raise ValueError("empty")
    if _SCIENTIFIC.match(cleaned):
        pass
    elif "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = (
            cleaned.replace(",", "")
            if _THOUSANDS_COMMA.match(cleaned)
            else cleaned.replace(",", ".")
        )
    elif _THOUSANDS_DOT.match(cleaned):
        cleaned = cleaned.replace(".", "")
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(text) from None
    if not number.is_finite():
        raise ValueError(text)
    return number


def parse_date(text: str, *, today: date | None = None) -> date:
    """``dd/mm/yyyy``, ``yyyy-mm-dd``, ``dd-mm-yyyy`` or an Excel serial; else ``ValueError``."""
    cleaned = text.strip()
    match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", cleaned)
    if match:
        return date(int(match[3]), int(match[2]), int(match[1]))
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?", cleaned)
    if match:
        return date(int(match[1]), int(match[2]), int(match[3]))
    if re.fullmatch(r"\d{5}(\.\d+)?", cleaned):
        serial = int(Decimal(cleaned))
        if 36_526 <= serial <= 73_050:  # 2000-01-01 .. 2099-12-31
            return _EXCEL_EPOCH + timedelta(days=serial)
    raise ValueError(text)


def parse_month(text: str) -> str:
    """``T12/2026``, ``12/2026``, ``2026-12`` -> ``2026-12``; else ``ValueError``."""
    cleaned = text.strip()
    match = re.fullmatch(r"[Tt]?(\d{1,2})[/-](\d{4})", cleaned) or None
    if match:
        month, year = int(match[1]), int(match[2])
    else:
        match = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?", cleaned)
        if not match:
            raise ValueError(text)
        year, month = int(match[1]), int(match[2])
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        raise ValueError(text)
    return f"{year:04d}-{month:02d}"


def _id_text(text: str) -> str:
    """An id cell: digits as typed, or Excel's float rendering of a long integer."""
    cleaned = text.strip()
    if _SCIENTIFIC.match(cleaned):
        try:
            return str(int(Decimal(cleaned)))
        except (InvalidOperation, ValueError):
            return cleaned
    if re.fullmatch(r"\d+\.0+", cleaned):
        return cleaned.split(".")[0]
    return cleaned


def _normalise_number(number: Decimal) -> int | float:
    return int(number) if number == number.to_integral_value() else float(number)


# -- headers ------------------------------------------------------------------------------


def _header_map(header: list[str | None], columns: dict[str, tuple[str, ...]]) -> dict[str, int]:
    folded = {_fold(re.sub(r"\s*\*$", "", (h or ""))): i for i, h in enumerate(header)}
    found: dict[str, int] = {}
    for key, aliases in columns.items():
        for alias in aliases:
            if _fold(alias) in folded:
                found[key] = folded[_fold(alias)]
                break
    return found


_SKU_HEADERS: dict[str, tuple[str, ...]] = {
    "item_id": ("item_id",),
    "variation_id": ("variation_id",),
    "sku": ("SKU",),
    "cost": ("giá vốn",),
    "packaging": ("đóng gói",),
    "max_discount": ("giảm tối đa (%)", "giảm tối đa"),
    "pack": ("số món / phân loại", "số món"),
    "vat": ("VAT (%)", "VAT"),
    "excluded": ("loại trừ",),
    "exclude_reason": ("lý do", "lý do loại trừ"),
    "stock": ("tồn kho",),
    "restock": ("ngày nhập lại",),
    "group": ("nhóm",),
    "status": ("trạng thái",),
}
_GOAL_HEADERS: dict[str, tuple[str, ...]] = {
    "month": ("tháng",),
    MONTHLY_GMV: ("GMV",),
    MONTHLY_ORDERS: ("đơn",),
    MONTHLY_AOV: ("AOV",),
    MONTHLY_MARGIN_PCT: ("biên mục tiêu (%)", "biên mục tiêu"),
    MONTHLY_MARKETING_CAP: ("trần chi marketing/ngày", "trần ngân sách QC/ngày"),
}
_REQUIRED_SKU = ("item_id", "sku", "cost")

_GROUP_LOOKUP = {_fold(label): code for code, label in GROUP_LABELS.items()} | {
    code: code for code in GROUP_LABELS
}
_STATUS_LOOKUP = {_fold(label): code for code, label in STATUS_LABELS.items()} | {
    code: code for code in STATUS_LABELS
}
_STATUS_LOOKUP |= {"dang ban": "ban", "ngung": "ngung", "tam ngung": "tam_dung"}
_YES = {"co", "yes", "true", "1", "x", "y"}
_NO = {"khong", "no", "false", "0", "n"}
_REASON_LOOKUP = {_fold(label): code for code, label in EXCLUDE_REASON_LABELS.items()} | {
    code: code for code in EXCLUDE_REASON_LABELS
}
_REASON_LOOKUP |= {"ngung ban": "ngung_ban", "qua tang": "qua_tang", "phan phoi": "phan_phoi"}


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _money_text(value: Any) -> str:
    if value is None:
        return "(chưa có)"
    number = Decimal(str(value))
    text = (
        f"{int(number):,}".replace(",", ".")
        if number == number.to_integral_value()
        else str(number)
    )
    return f"{text}đ"


def _margin_text(price: Decimal, cost: Decimal) -> str:
    return f"{(price - cost) / price * 100:.1f}".replace(".", ",") + "%"


# -- SKU sheet ----------------------------------------------------------------------------


@dataclass
class _SkuContext:
    catalogue: dict[tuple[str, str], CatalogueSku]
    current: CurrentInputs
    samples: dict[tuple[str, str], list[kol_samples.Shipment]] = field(default_factory=dict)


def _reject(
    out: list[Rejection],
    sheet: str,
    row: int,
    sku: str,
    column: str,
    value: str,
    reason: str,
    kind: str,
) -> None:
    out.append(Rejection(sheet, row, sku, column, value or "(trống)", reason, kind))


def _parse_sku_field(key: str, text: str) -> tuple[Any, tuple[str, str] | None]:
    """``(normalised value, None)`` or ``(None, (reason, kind))``."""
    try:
        if key in ("cost", "packaging"):
            number = parse_number(text)
            if number < 0:
                return None, ("Phải từ 0 trở lên.", "out_of_range")
            return _normalise_number(number), None
        if key == "max_discount":
            number = parse_number(text)
            if not Decimal(0) <= number <= Decimal(100):
                return None, ("Giảm tối đa phải từ 0 đến 100%.", "out_of_range")
            return _normalise_number(number), None
        if key == "stock":
            number = parse_number(text)
            if number != number.to_integral_value():
                return None, ("Tồn kho phải là số nguyên.", "invalid_value")
            if number < 0:
                return None, ("Tồn kho phải từ 0 trở lên.", "out_of_range")
            return int(number), None
        if key == "pack":
            number = parse_number(text)
            if number != number.to_integral_value():
                return None, ("Số món phải là số nguyên.", "bad_pack")
            if not 1 <= number <= MAX_PACK_COUNT:
                return None, (f"Số món phải từ 1 đến {MAX_PACK_COUNT}.", "bad_pack")
            return int(number), None
        if key == "vat":
            number = parse_number(text)
            if number != number.to_integral_value() or int(number) not in VAT_RATES_PCT:
                allowed = ", ".join(str(r) for r in VAT_RATES_PCT)
                return None, (f"VAT là một trong: {allowed} (%).", "bad_vat")
            return int(number), None
        if key == "restock":
            return parse_date(text).isoformat(), None
        if key == "excluded":
            word = _fold(text)
            if word in _YES:
                return True, None
            if word in _NO:
                return False, None
            return None, ("Loại trừ là Có hoặc Không.", "invalid_value")
        if key == "exclude_reason":
            code = _REASON_LOOKUP.get(_fold(text))
            if code is None:
                return None, (
                    "Lý do là Ngừng bán, Quà tặng, Hàng phân phối hoặc Khác.",
                    "invalid_value",
                )
            return code, None
        if key == "group":
            code = _GROUP_LOOKUP.get(_fold(text))
            if code is None:
                return None, ("Nhóm là Thương hiệu hoặc Phân phối.", "invalid_value")
            return code, None
        code = _STATUS_LOOKUP.get(_fold(text))
        if code is None:
            return None, (
                "Trạng thái là Đang bán, Tạm dừng, Ngừng bán hoặc Xả hàng.",
                "invalid_value",
            )
        return code, None
    except ValueError:
        if key == "restock":
            return None, ("Ngày không đọc được. Dùng dd/mm/yyyy.", "bad_date")
        if key == "pack":
            return None, ("Số món không đọc được thành số.", "bad_pack")
        if key == "vat":
            return None, ("VAT không đọc được thành số.", "bad_vat")
        return None, ("Không đọc được thành số.", "invalid_value")


def effective_pack(sku: CatalogueSku, old_values: dict[str, Any]) -> int:
    """The pack count in force for a SKU: the seller's, else the one the variation name states,
    else 1 (what the profit reads)."""
    stored = old_values.get(PACK_COUNT)
    if isinstance(stored, int) and not isinstance(stored, bool):
        return stored
    return pack_count_from_name(sku.variation_name) or 1


def _old_value(field_key: str, sku: CatalogueSku, old_values: dict[str, Any]) -> Any:
    """What Juli holds now for a field (stock: the platform's when not imported; pack: what the
    variation name states)."""
    if field_key == "stock":
        return effective_stock(sku, old_values)
    if field_key == "pack":
        return effective_pack(sku, old_values)
    return old_values.get(FIELD_RULES[field_key])


def _would_change(field_key: str, new: Any, sku: CatalogueSku, old_values: dict[str, Any]) -> bool:
    """Whether a cell holds something other than what Juli already has for the SKU."""
    return _old_value(field_key, sku, old_values) != new


def _effect(field_key: str, sku: CatalogueSku, old: Any, new: Any) -> str:
    if field_key == "cost" and sku.list_price:
        price = sku.list_price
        after = _margin_text(price, Decimal(str(new)))
        if old is None:
            return f"Tính được biên gộp {after} theo giá niêm yết"
        return f"Biên gộp theo giá niêm yết {_margin_text(price, Decimal(str(old)))} → {after}"
    if field_key == "stock":
        if old == 0 and new > 0:
            return "Hết hàng → còn hàng"
        if old and new == 0:
            return "Còn hàng → hết hàng"
    if field_key == "status":
        return f"Trạng thái: {STATUS_LABELS[new]}"
    if field_key == "pack":
        return f"1 đơn vị bán = {new} món; giá vốn tính ×{new}"
    return ""


def _exclusion_effect(field_key: str, new: Any) -> str:
    if field_key == "excluded":
        return (
            "Không còn thẻ, dòng sản phẩm hay cờ Phân tích; doanh số vẫn nằm trong tổng của shop"
            if new
            else "Sản phẩm trở lại thẻ, danh sách và Phân tích"
        )
    return f"Lý do: {EXCLUDE_REASON_LABELS[new]}"


def _check_exclusion(
    item_parsed: dict[str, Any],
    item_id: str,
    index: int,
    label: str,
    ctx: _SkuContext,
    item_seen: dict[tuple[str, str], tuple[Any, int]],
    rejections: list[Rejection],
    row: list[str | None],
    header: dict[str, int],
) -> None:
    """One listing, one answer: rows of the same item must say the same, and "Có" needs a reason
    (this file's, else the one already stored)."""
    old = ctx.current.per_sku.get(item_id, {})
    for field_key, value in item_parsed.items():
        seen = item_seen.get((item_id, field_key))
        if seen is not None and seen[0] != value:
            _reject(
                rejections,
                SKU_SHEET,
                index,
                label,
                _column_title(field_key),
                _cell(row, header.get(field_key)),
                f"Các dòng của cùng sản phẩm ghi khác nhau (dòng {seen[1]}). Giữ một giá trị.",
                "invalid_value",
            )
            return
        item_seen.setdefault((item_id, field_key), (value, index))
    reason = item_parsed.get("exclude_reason") or old.get("exclude_reason")
    if item_parsed.get("excluded") is True and not reason:
        _reject(
            rejections,
            SKU_SHEET,
            index,
            label,
            _column_title("exclude_reason"),
            "",
            "Loại trừ cần ghi lý do: Ngừng bán, Quà tặng, Hàng phân phối hoặc Khác.",
            "invalid_value",
        )


def _check_sku_sheet(rows: list[list[str | None]], ctx: _SkuContext, out: ImportPreview) -> None:
    if not rows:
        raise ImportFileError("Trang SKU trống")
    header = _header_map(rows[0], _SKU_HEADERS)
    missing = [k for k in _REQUIRED_SKU if k not in header]
    if missing:
        names = {"item_id": "item_id", "sku": "SKU", "cost": "giá vốn"}
        raise ImportFileError("Trang SKU thiếu cột: " + ", ".join(names[k] for k in missing))

    data: list[tuple[int, list[str | None]]] = []
    for index, row in enumerate(rows[1:], start=2):
        cells = [(c or "").strip() for c in row]
        if not any(cells):
            continue
        if not any(cells[1:]):
            continue  # a note line (first cell only), not a SKU row
        data.append((index, row))

    keys = [
        (
            _id_text(_cell(row, header["item_id"])),
            _id_text(_cell(row, header.get("variation_id"))),
        )
        for _, row in data
    ]
    counts = Counter(keys)
    positions: dict[tuple[str, str], list[int]] = {}
    for (index, _), key in zip(data, keys, strict=True):
        positions.setdefault(key, []).append(index)

    item_seen: dict[tuple[str, str], tuple[Any, int]] = {}
    item_emitted: set[tuple[str, str]] = set()
    for (index, row), key in zip(data, keys, strict=True):
        out.sku_rows += 1
        item_id, variation_id = key
        sku_text = _cell(row, header["sku"])
        rejections: list[Rejection] = []
        label = sku_text or item_id

        if counts[key] > 1:
            others = ", ".join(str(p) for p in positions[key] if p != index)
            _reject(
                rejections,
                SKU_SHEET,
                index,
                label,
                "SKU",
                sku_text,
                f"SKU xuất hiện nhiều lần (cả dòng {others}). Giữ một dòng rồi tải lại.",
                "duplicate_sku",
            )
        known = ctx.catalogue.get(key)
        if known is None:
            _reject(
                rejections,
                SKU_SHEET,
                index,
                label,
                "SKU",
                sku_text or item_id,
                "Không có SKU này trong shop. Kiểm tra lỗi gõ hoặc SKU đã xoá.",
                "unknown_sku",
            )
        elif sku_text and known.sku and sku_text.casefold() != known.sku.casefold():
            _reject(
                rejections,
                SKU_SHEET,
                index,
                label,
                "SKU",
                sku_text,
                f"SKU không khớp mã sản phẩm này (Juli có {known.sku}).",
                "unknown_sku",
            )

        parsed: dict[str, Any] = {}
        item_parsed: dict[str, Any] = {}  # P92 B-1: the listing's exclusion, read once per item
        for field_key in (*FIELD_RULES, *ITEM_FIELD_RULES):
            text = _cell(row, header.get(field_key))
            if not text:
                continue
            value, error = _parse_sku_field(field_key, text)
            if error is not None:
                _reject(rejections, SKU_SHEET, index, label, _column_title(field_key), text, *error)
            elif field_key in ITEM_FIELD_RULES:
                item_parsed[field_key] = value
            else:
                parsed[field_key] = value

        if item_parsed and not rejections:
            _check_exclusion(
                item_parsed, item_id, index, label, ctx, item_seen, rejections, row, header
            )

        if known is not None:
            old_values = ctx.current.per_sku.get(known.scope, {})
            cost_text = _cell(row, header.get("cost"))
            if "cost" in parsed and known.list_price is not None:
                pack = int(parsed.get("pack") or effective_pack(known, old_values))
                unit = Decimal(str(parsed["cost"])) * pack
                if unit >= known.list_price:
                    suffix = f" (giá vốn {pack} món)" if pack > 1 else ""
                    _reject(
                        rejections,
                        SKU_SHEET,
                        index,
                        label,
                        "giá vốn",
                        cost_text,
                        f"Giá vốn ≥ giá niêm yết {_money_text(known.list_price)}{suffix}. "
                        "Biên sẽ âm.",
                        "cost_ge_price",
                    )
            elif (
                not cost_text
                and SKU_COST not in old_values
                and any(_would_change(k, v, known, old_values) for k, v in parsed.items())
            ):
                _reject(
                    rejections,
                    SKU_SHEET,
                    index,
                    label,
                    "giá vốn",
                    "",
                    "Cột giá vốn bắt buộc, chưa có giá trị cũ để giữ.",
                    "cost_missing",
                )

        if rejections:
            out.sku_rows_rejected += 1
            out.rejections.extend(rejections)
            continue
        if known is None or not (parsed or item_parsed):
            out.sku_rows_unchanged += 1
            continue

        old_values = ctx.current.per_sku.get(known.scope, {})
        changed = 0
        for field_key, new in item_parsed.items():  # once per item: the first row that says it
            rule_key = ITEM_FIELD_RULES[field_key]
            if (item_id, field_key) in item_emitted:
                continue
            item_emitted.add((item_id, field_key))
            old = ctx.current.per_sku.get(item_id, {}).get(rule_key)
            if old == new:
                continue
            changed += 1
            out.diffs.append(
                FieldDiff(
                    scope_ref=item_id,
                    item_id=item_id,
                    variation_id="",
                    sku=known.sku or item_id,
                    field=field_key,
                    rule_key=rule_key,
                    old=old,
                    new=new,
                    effect=_exclusion_effect(field_key, new),
                )
            )
            out.changes.append(RuleChange(rule_key, item_id, new))
        for field_key, new in parsed.items():
            rule_key = FIELD_RULES[field_key]
            old = _old_value(field_key, known, old_values)
            if old == new:
                continue
            changed += 1
            out.diffs.append(
                FieldDiff(
                    scope_ref=known.scope,
                    item_id=known.item_id,
                    variation_id=known.variation_id,
                    sku=known.sku or known.item_id,
                    field=field_key,
                    rule_key=rule_key,
                    old=old,
                    new=new,
                    effect=_effect(field_key, known, old, new),
                )
            )
            out.changes.append(RuleChange(rule_key, known.scope, new))
        if not changed:
            out.sku_rows_unchanged += 1


def _column_title(field_key: str) -> str:
    for title, _, key in SKU_COLUMNS:
        if key == field_key:
            return title
    return field_key


# -- Mẫu KOL sheet ------------------------------------------------------------------------

_SAMPLE_HEADERS: dict[str, tuple[str, ...]] = {
    "kol": ("KOL (tay cầm)", "KOL", "tay cầm"),
    "product": ("Sản phẩm (mã SP hoặc SKU)", "Sản phẩm", "SKU"),
    "qty": ("Số lượng mẫu", "số lượng"),
    "sent_on": ("Ngày gửi",),
    "ship_fee": ("Phí ship gửi mẫu", "Phí ship"),
    "note": ("Ghi chú",),
}


def _find_product(ctx: _SkuContext, text: str) -> CatalogueSku | None:
    """A product cell: ``item_id``, ``item_id:variation_id``, or a seller SKU."""
    cleaned = _id_text(text)
    if (cleaned, "") in ctx.catalogue:
        return ctx.catalogue[(cleaned, "")]
    item_id, _, variation_id = cleaned.partition(":")
    if variation_id and (item_id, variation_id) in ctx.catalogue:
        return ctx.catalogue[(item_id, variation_id)]
    wanted = cleaned.casefold()
    by_sku = [s for s in ctx.catalogue.values() if s.sku and s.sku.casefold() == wanted]
    if by_sku:
        return by_sku[0]
    holders = sorted(k for k in ctx.catalogue if k[0] == cleaned)
    if holders:  # an item with variations named by its id: the item-level scope
        return CatalogueSku(
            cleaned, "", "", ctx.catalogue[holders[0]].name.split(" · ")[0], None, None
        )
    return None


def _check_sample_sheet(rows: list[list[str | None]], ctx: _SkuContext, out: ImportPreview) -> None:
    if not rows:
        return
    header = _header_map(rows[0], _SAMPLE_HEADERS)
    missing = [k for k in ("kol", "product") if k not in header]
    if missing:
        names = {"kol": "KOL", "product": "Sản phẩm"}
        raise ImportFileError("Trang Mẫu KOL thiếu cột: " + ", ".join(names[k] for k in missing))
    sheet = kol_samples.SAMPLE_SHEET

    # pair -> shipments from valid rows; pairs with any rejected row are left untouched.
    shipments: dict[tuple[str, str], list[kol_samples.Shipment]] = {}
    rejected_pairs: set[tuple[str, str]] = set()
    meta: dict[tuple[str, str], tuple[str, CatalogueSku, str]] = {}
    cleared: set[tuple[str, str]] = set()
    seen: Counter[tuple[str, str, date]] = Counter()
    for index, row in enumerate(rows[1:], start=2):
        cells = [(c or "").strip() for c in row]
        if not any(cells) or not any(cells[1:]):
            continue  # blank line, or a note line (first cell only)
        kol_text = _cell(row, header["kol"]).lstrip("@").strip()
        product_text = _cell(row, header["product"])
        qty_text = _cell(row, header.get("qty"))
        date_text = _cell(row, header.get("sent_on"))
        fee_text = _cell(row, header.get("ship_fee"))
        if not qty_text and not date_text and not fee_text:
            continue  # "chưa gửi mẫu": a listing row with nothing sent
        out.sample_rows += 1
        label = kol_text or product_text
        rejections: list[Rejection] = []
        if not kol_text or len(kol_text) > 120:
            _reject(
                rejections,
                sheet,
                index,
                label,
                "KOL (tay cầm)",
                kol_text,
                "Cần tay cầm công khai của KOL (tối đa 120 ký tự).",
                "kol_missing",
            )
        known = _find_product(ctx, product_text) if product_text else None
        if known is None:
            _reject(
                rejections,
                sheet,
                index,
                label,
                "Sản phẩm",
                product_text,
                "Không có mã sản phẩm hoặc SKU này trong shop.",
                "unknown_sku",
            )
        qty = 0
        if not qty_text:
            _reject(
                rejections,
                sheet,
                index,
                label,
                "Số lượng mẫu",
                "",
                "Có ngày hoặc phí ship nhưng thiếu số lượng mẫu.",
                "invalid_value",
            )
        else:
            try:
                number = parse_number(qty_text)
                if number != number.to_integral_value() or number < 0:
                    raise ValueError(qty_text)
                if number > 10_000:
                    _reject(
                        rejections,
                        sheet,
                        index,
                        label,
                        "Số lượng mẫu",
                        qty_text,
                        "Số lượng mẫu tối đa 10.000.",
                        "out_of_range",
                    )
                qty = int(number)
            except ValueError:
                _reject(
                    rejections,
                    sheet,
                    index,
                    label,
                    "Số lượng mẫu",
                    qty_text,
                    "Số lượng mẫu phải là số nguyên từ 0 trở lên.",
                    "invalid_value",
                )
        sent_on: date | None = None
        if qty > 0 or date_text:
            try:
                sent_on = parse_date(date_text) if date_text else None
            except ValueError:
                sent_on = None
            if sent_on is None:
                _reject(
                    rejections,
                    sheet,
                    index,
                    label,
                    "Ngày gửi",
                    date_text,
                    "Ngày gửi không đọc được. Dùng dd/mm/yyyy."
                    if date_text
                    else "Cần ngày gửi để đo trước và sau khi gửi.",
                    "bad_date",
                )
        fee = Decimal(0)
        if fee_text:
            try:
                fee = parse_number(fee_text)
                if fee < 0:
                    raise ValueError(fee_text)
            except ValueError:
                _reject(
                    rejections,
                    sheet,
                    index,
                    label,
                    "Phí ship gửi mẫu",
                    fee_text,
                    "Phí ship phải là số từ 0 trở lên.",
                    "invalid_value",
                )
        if known is None or not kol_text:
            pair = ("", product_text)
        else:
            pair = (kol_samples.make_key(kol_text), known.scope)
        if not rejections and sent_on is not None and qty > 0:
            seen[(pair[0], pair[1], sent_on)] += 1
            if seen[(pair[0], pair[1], sent_on)] > 1:
                _reject(
                    rejections,
                    sheet,
                    index,
                    label,
                    "Ngày gửi",
                    date_text,
                    "Cùng KOL, sản phẩm và ngày đã có một dòng. Gộp lại thành một dòng.",
                    "duplicate_sku",
                )
        if rejections:
            out.sample_rows_rejected += 1
            out.rejections.extend(rejections)
            rejected_pairs.add(pair)
            continue
        assert known is not None
        meta.setdefault(pair, (kol_text, known, known.scope))
        if qty == 0:
            cleared.add(pair)
            shipments.setdefault(pair, [])
        else:
            assert sent_on is not None
            shipments.setdefault(pair, []).append(kol_samples.Shipment(kol_text, qty, sent_on, fee))

    for pair, new_list in shipments.items():
        if pair in rejected_pairs:
            continue
        handle, known, sku_scope = meta[pair]
        key = pair[0]
        old_list = ctx.samples.get((key, sku_scope), [])
        ordered = sorted(new_list, key=lambda e: (e.sent_on, e.qty, e.ship_fee))
        old_ordered = sorted(old_list, key=lambda e: (e.sent_on, e.qty, e.ship_fee))
        if ordered == old_ordered:
            out.sample_rows_unchanged += 1
            continue
        unit = kol_samples.unit_cost_from_inputs(ctx.current, known, sku_scope, known.item_id)
        scope = kol_samples.scope_ref(key, sku_scope)
        out.sample_diffs.append(
            kol_samples.SampleDiff(
                scope_ref=scope,
                kol_key=key,
                handle=handle,
                item_id=known.item_id,
                sku=known.sku or known.item_id,
                old=[e.json() for e in old_ordered],
                new=[e.json() for e in ordered],
                old_cost=kol_samples.sample_cost(old_ordered, unit) if old_ordered else None,
                new_cost=kol_samples.sample_cost(ordered, unit) if ordered else Decimal(0),
                cost_label=unit.label if unit else "chưa có giá vốn",
            )
        )
        out.changes.append(RuleChange(KOL_SAMPLE, scope, [e.json() for e in ordered]))


# -- Mục tiêu sheet -----------------------------------------------------------------------


def _parse_goal_value(key: str, text: str) -> tuple[Any, tuple[str, str] | None]:
    try:
        number = parse_number(text)
    except ValueError:
        return None, ("Không đọc được thành số.", "invalid_value")
    if key == MONTHLY_MARGIN_PCT:
        if not Decimal(0) <= number < Decimal(100):
            return None, ("Biên mục tiêu phải từ 0 đến dưới 100%.", "out_of_range")
    elif number < 0:
        return None, ("Phải từ 0 trở lên.", "out_of_range")
    if key == MONTHLY_ORDERS and number != number.to_integral_value():
        return None, ("Số đơn phải là số nguyên.", "invalid_value")
    value: Any = int(number) if key == MONTHLY_ORDERS else _normalise_number(number)
    try:
        validate_rule(key, "2000-01", value)
    except RuleValidationError:
        return None, ("Giá trị ngoài khoảng cho phép.", "out_of_range")
    return value, None


def _goal_title(key: str) -> str:
    for title, column_key in GOAL_COLUMNS:
        if column_key == key:
            return title
    return key


def _check_goal_sheet(rows: list[list[str | None]], ctx: _SkuContext, out: ImportPreview) -> None:
    if not rows:
        return
    header = _header_map(rows[0], _GOAL_HEADERS)
    if "month" not in header:
        raise ImportFileError("Trang Mục tiêu thiếu cột: tháng")

    data: list[tuple[int, str, list[str | None]]] = []
    for index, row in enumerate(rows[1:], start=2):
        cells = [(c or "").strip() for c in row]
        if not any(cells):
            continue
        month_text = _cell(row, header["month"])
        if not any(cells[1:]):
            continue  # a note line, or a month typed with no value: nothing to import
        data.append((index, month_text, row))

    months: list[str | None] = []
    for _, month_text, _ in data:
        try:
            months.append(parse_month(month_text))
        except ValueError:
            months.append(None)
    counts = Counter(m for m in months if m)

    for (index, month_text, row), month in zip(data, months, strict=True):
        out.goal_rows += 1
        rejections: list[Rejection] = []
        if month is None:
            _reject(
                rejections,
                GOAL_SHEET,
                index,
                month_text,
                "tháng",
                month_text,
                "Tháng không đọc được. Dùng dạng T12/2026.",
                "bad_month",
            )
        elif counts[month] > 1:
            _reject(
                rejections,
                GOAL_SHEET,
                index,
                month_label(month),
                "tháng",
                month_text,
                "Tháng xuất hiện nhiều lần. Giữ một dòng rồi tải lại.",
                "duplicate_sku",
            )
        label = month_label(month) if month else month_text
        parsed: dict[str, Any] = {}
        for key in MONTHLY_RULE_KEYS:
            text = _cell(row, header.get(key))
            if not text:
                continue
            value, error = _parse_goal_value(key, text)
            if error is not None:
                _reject(rejections, GOAL_SHEET, index, label, _goal_title(key), text, *error)
            else:
                parsed[key] = value
        if rejections or month is None:
            out.goal_rows_rejected += 1
            out.rejections.extend(rejections)
            continue
        old_values = ctx.current.monthly.get(month, {})
        for key, new in parsed.items():
            old = old_values.get(key)
            if old == new:
                continue
            out.goal_diffs.append(
                FieldDiff(
                    scope_ref=month,
                    item_id="",
                    variation_id="",
                    sku=label,
                    field=key,
                    rule_key=key,
                    old=old,
                    new=new,
                )
            )
            out.changes.append(RuleChange(key, month, new))
        merged = {**old_values, **parsed}
        gmv, orders, aov = (merged.get(k) for k in (MONTHLY_GMV, MONTHLY_ORDERS, MONTHLY_AOV))
        if gmv and orders and aov:
            deviation = abs(Decimal(str(gmv)) / Decimal(str(orders)) / Decimal(str(aov)) - 1)
            if deviation > GOAL_MISMATCH_TOLERANCE:
                implied = Decimal(str(gmv)) / Decimal(str(orders))
                out.warnings.append(
                    GoalWarning(
                        month=month,
                        message=(
                            f"GMV ÷ đơn = {_money_text(round(implied))}, lệch "
                            f"{float(deviation) * 100:.1f}".replace(".", ",")
                            + f"% so với AOV {_money_text(aov)}. Kiểm tra lại một trong ba số. "
                            "Vẫn lưu được."
                        ),
                        deviation=float(deviation),
                    )
                )


# -- Thành phần combo sheet (P91 D-12) ------------------------------------------------------

_BOM_HEADERS: dict[str, tuple[str, ...]] = {
    "item_id": ("item_id",),
    "variation_id": ("variation_id",),
    "component": ("SKU thành phần", "thành phần"),
    "qty": ("số lượng", "SL"),
}


def _check_bom_sheet(rows: list[list[str | None]], ctx: _SkuContext, out: ImportPreview) -> None:
    """A listing's component lines are applied WHOLE: one bad line rejects the listing's lines
    (a bill of materials with a missing part would cost too little)."""
    if not rows:
        return
    header = _header_map(rows[0], _BOM_HEADERS)
    missing = [k for k in ("item_id", "component", "qty") if k not in header]
    if missing:
        names = {"item_id": "item_id", "component": "SKU thành phần", "qty": "số lượng"}
        raise ImportFileError(
            f"Trang {BOM_SHEET} thiếu cột: " + ", ".join(names[k] for k in missing)
        )
    known_skus = {s.sku.casefold(): s.sku for s in ctx.catalogue.values() if s.sku}
    groups: dict[tuple[str, str], list[tuple[int, list[str | None]]]] = {}
    for index, row in enumerate(rows[1:], start=2):
        cells = [(c or "").strip() for c in row]
        if not any(cells) or not any(cells[1:]):
            continue  # blank, or a note line (first cell only)
        key = (
            _id_text(_cell(row, header["item_id"])),
            _id_text(_cell(row, header.get("variation_id"))),
        )
        groups.setdefault(key, []).append((index, row))

    for key, lines in groups.items():
        out.bom_rows += len(lines)
        item_id, variation_id = key
        listing = ctx.catalogue.get(key)
        label = listing.sku if listing and listing.sku else item_id
        problems: list[Rejection] = []
        if listing is None:
            for index, row in lines:
                _reject(
                    problems,
                    BOM_SHEET,
                    index,
                    label,
                    "item_id",
                    item_id,
                    "Không có sản phẩm / phân loại này trong shop.",
                    "unknown_sku",
                )
        components: list[dict[str, Any]] = []
        seen: dict[str, int] = {}
        for index, row in lines:
            text = _cell(row, header["component"])
            qty_text = _cell(row, header["qty"])
            code = known_skus.get(text.casefold()) if text else None
            if not text or code is None:
                _reject(
                    problems,
                    BOM_SHEET,
                    index,
                    label,
                    "SKU thành phần",
                    text,
                    "SKU thành phần không có trong shop. Kiểm tra lỗi gõ.",
                    "unknown_component",
                )
                continue
            if listing is not None and listing.sku and code.casefold() == listing.sku.casefold():
                _reject(
                    problems,
                    BOM_SHEET,
                    index,
                    label,
                    "SKU thành phần",
                    text,
                    "Thành phần trùng SKU của chính sản phẩm này.",
                    "bom_self",
                )
                continue
            try:
                qty = parse_number(qty_text)
            except ValueError:
                qty = Decimal(-1)
            if qty != qty.to_integral_value() or not 1 <= qty <= MAX_COMPONENT_QTY:
                _reject(
                    problems,
                    BOM_SHEET,
                    index,
                    label,
                    "số lượng",
                    qty_text,
                    f"Số lượng là số nguyên từ 1 đến {MAX_COMPONENT_QTY}.",
                    "bad_quantity",
                )
                continue
            if code in seen:
                _reject(
                    problems,
                    BOM_SHEET,
                    index,
                    label,
                    "SKU thành phần",
                    text,
                    f"Thành phần xuất hiện nhiều lần (cả dòng {seen[code]}). Gộp thành một dòng.",
                    "duplicate_component",
                )
                continue
            seen[code] = index
            components.append({"sku": code, "qty": int(qty)})
        if len(components) > MAX_COMPONENTS:
            problems.append(
                Rejection(
                    BOM_SHEET,
                    lines[0][0],
                    label,
                    "SKU thành phần",
                    str(len(components)),
                    f"Tối đa {MAX_COMPONENTS} thành phần cho một sản phẩm.",
                    "out_of_range",
                )
            )
        if problems:
            out.bom_rows_rejected += len(lines)
            out.rejections.extend(problems)
            continue
        assert listing is not None
        old = ctx.current.per_sku.get(listing.scope, {}).get(PACK_COMPONENTS)
        if old == components:
            continue
        out.bom_diffs.append(
            FieldDiff(
                scope_ref=listing.scope,
                item_id=item_id,
                variation_id=variation_id,
                sku=label,
                field="bom",
                rule_key=PACK_COMPONENTS,
                old=old,
                new=components,
                effect=f"{len(components)} thành phần; giá vốn = Σ giá vốn thành phần × số lượng",
            )
        )
        out.changes.append(RuleChange(PACK_COMPONENTS, listing.scope, components))


# -- VAT sheet (P91 D-12) ------------------------------------------------------------------

_YES = {"co", "yes", "true", "1", "x", "y"}
_NO = {"khong", "no", "false", "0", "n"}


def _check_vat_sheet(rows: list[list[str | None]], ctx: _SkuContext, out: ImportPreview) -> None:
    labels = {_fold(label): key for label, key in VAT_SETTINGS}
    for index, row in enumerate(rows[1:], start=2):
        name, text = _cell(row, 0), _cell(row, 1)
        key = labels.get(_fold(name))
        if key is None or not text:
            continue
        folded = _fold(text)
        if folded in _YES:
            value = True
        elif folded in _NO:
            value = False
        else:
            _reject(
                out.rejections,
                VAT_SHEET,
                index,
                name,
                name,
                text,
                "Điền Có hoặc Không.",
                "invalid_value",
            )
            continue
        old = ctx.current.flags.get(key)
        if old == value:
            continue
        out.shop_diffs.append(
            FieldDiff(
                scope_ref="",
                item_id="",
                variation_id="",
                sku=name,
                field=key,
                rule_key=key,
                old=old,
                new=value,
                effect="Lợi nhuận tính sau VAT" if key == "prices_include_vat" and value else "",
            )
        )
        out.changes.append(RuleChange(key, "", value))


# -- entry points -------------------------------------------------------------------------


def _find_sheet(
    sheets: dict[str, list[list[str | None]]], name: str
) -> list[list[str | None]] | None:
    for title, rows in sheets.items():
        if _fold(title) == _fold(name):
            return rows
    return None


async def preview_import(session: AsyncSession, shop_id: uuid.UUID, data: bytes) -> ImportPreview:
    """Check the file against the shop's catalogue and current values; writes nothing."""
    try:
        sheets = xlsx_io.read_workbook(data)
    except xlsx_io.WorkbookUnreadable as exc:
        raise ImportFileError(f"Không đọc được tệp .xlsx: {exc}") from None
    sku_rows = _find_sheet(sheets, SKU_SHEET)
    goal_rows = _find_sheet(sheets, GOAL_SHEET)
    sample_rows = _find_sheet(sheets, kol_samples.SAMPLE_SHEET)
    bom_rows = _find_sheet(sheets, BOM_SHEET)
    vat_rows = _find_sheet(sheets, VAT_SHEET)
    if all(sheet is None for sheet in (sku_rows, goal_rows, sample_rows, bom_rows, vat_rows)):
        raise ImportFileError("Tệp cần có trang SKU, Mục tiêu, Mẫu KOL, Thành phần combo hoặc VAT")

    catalogue = {(s.item_id, s.variation_id): s for s in await load_catalogue(session, shop_id)}
    ctx = _SkuContext(
        catalogue=catalogue,
        current=await load_current(session, shop_id),
        samples=await kol_samples.load_samples(session, shop_id) if sample_rows else {},
    )
    out = ImportPreview(file_hash=file_hash(data))
    if sku_rows is not None:
        _check_sku_sheet(sku_rows, ctx, out)
    if sample_rows is not None:
        _check_sample_sheet(sample_rows, ctx, out)
    if goal_rows is not None:
        _check_goal_sheet(goal_rows, ctx, out)
    if bom_rows is not None:
        _check_bom_sheet(bom_rows, ctx, out)
    if vat_rows is not None:
        _check_vat_sheet(vat_rows, ctx, out)
    return out


def is_shop_wide(preview: ImportPreview) -> bool:
    """Whether the file moves a monthly target that every price / voucher / ads proposal
    is judged against."""
    return bool(preview.shop_diffs) or any(
        d.rule_key in (MONTHLY_MARGIN_PCT, MONTHLY_MARKETING_CAP) for d in preview.goal_diffs
    )


async def preview_affected(
    session: AsyncSession, shop_id: uuid.UUID, preview: ImportPreview
) -> AffectedRecommendations:
    """The open recommendations this file's valid changes would re-run."""
    return await affected_recommendations(
        session,
        shop_id,
        item_ids=set(preview.changed_item_ids),
        shop_wide=is_shop_wide(preview),
    )


@dataclass(frozen=True)
class ApplyResult:
    preview: ImportPreview
    versions_written: int
    skus_changed: int
    samples_changed: int
    months_changed: int
    affected: AffectedRecommendations
    applied_at: datetime
    reason: str
    boms_changed: int = 0
    flags_changed: int = 0


async def apply_import(
    session: AsyncSession,
    shop_id: uuid.UUID,
    data: bytes,
    *,
    actor: Actor,
    reason: str,
    expected_hash: str | None = None,
    now: datetime | None = None,
) -> ApplyResult:
    """Write the valid rows' changes as one change set. Flush, no commit.

    Rejected rows write nothing. The reason is required.
    """
    why = clean_reason(reason, required=True)
    assert why is not None
    preview = await preview_import(session, shop_id, data)
    if expected_hash is not None and expected_hash != preview.file_hash:
        raise FileMismatch("Tệp khác với tệp đã kiểm tra. Kiểm tra lại tệp trước khi áp dụng.")
    if not preview.changes:
        raise NothingToApply("Tệp không có thay đổi hợp lệ nào để áp dụng")
    moment = now or datetime.now(UTC)
    written = await write_versions(
        session,
        shop_id,
        preview.changes,
        actor=actor,
        reason=why,
        import_file_hash=preview.file_hash,
        now=moment,
    )
    shop_wide = is_shop_wide(preview)
    affected = await preview_affected(session, shop_id, preview)
    await mark_stale(
        session,
        shop_id,
        StaleRequest(
            item_ids=affected.item_ids,
            shop_wide=shop_wide,
            reason=STALE_REASON,
            changed_at=moment,
            import_file_hash=preview.file_hash,
        ),
    )
    return ApplyResult(
        preview=preview,
        versions_written=len(written),
        skus_changed=len(preview.changed_scopes),
        samples_changed=len(preview.sample_diffs),
        months_changed=len(preview.changed_months),
        affected=affected,
        applied_at=moment,
        reason=why,
        boms_changed=len(preview.bom_diffs),
        flags_changed=len(preview.shop_diffs),
    )


__all__ = [
    "ApplyResult",
    "FieldDiff",
    "FileMismatch",
    "ImportFileError",
    "ImportPreview",
    "NothingToApply",
    "Rejection",
    "apply_import",
    "parse_date",
    "parse_month",
    "parse_number",
    "preview_import",
]
