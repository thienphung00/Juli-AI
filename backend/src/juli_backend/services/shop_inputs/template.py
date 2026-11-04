"""The seller-input template: ``.xlsx`` with sheets ``SKU``, ``Mục tiêu``, ``Thành phần combo``
and ``VAT``.

Pre-filled with what Juli holds: one row per SKU of the shop's catalogue (list price
read-only, from the latest product snapshot), the seller's current values written back,
and the months already set. Empty cell = keep the old value. No buyer data is in the file.

P91 D-12: the SKU sheet gains ``số món / phân loại`` (single items in one sold unit; the
default shown is read from the variation name, "Combo 3 hộp" -> 3, and a blank cell keeps
whatever Juli reads from the name) and ``VAT (%)``; ``Thành phần combo`` is the bill of
materials of a listing that has no SKU of its own (component SKU x quantity); ``VAT`` holds the
two shop flags - whether the listing prices and the giá vốn already include VAT.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shop_inputs import kol_samples, xlsx_io
from juli_backend.services.shop_inputs.catalogue import (
    CatalogueSku,
    effective_stock,
    load_catalogue,
    load_current,
)
from juli_backend.services.shop_rules.rules import (
    COST_INCLUDES_VAT,
    ITEM_STATUS,
    MAX_DISCOUNT_PCT,
    MONTHLY_AOV,
    MONTHLY_GMV,
    MONTHLY_MARGIN_PCT,
    MONTHLY_MARKETING_CAP,
    MONTHLY_ORDERS,
    PACK_COMPONENTS,
    PACK_COUNT,
    PACKAGING,
    PRICES_INCLUDE_VAT,
    PRODUCT_GROUP,
    RESTOCK_DATE,
    SKU_COST,
    VAT_RATE,
)
from juli_backend.services.shopee_profit.pack import pack_count_from_name

SKU_SHEET = "SKU"
GOAL_SHEET = "Mục tiêu"
BOM_SHEET = "Thành phần combo"
VAT_SHEET = "VAT"

#: (header, required, key) of the ``SKU`` sheet; ``key`` names the field in ``importer``.
SKU_COLUMNS: tuple[tuple[str, bool, str], ...] = (
    ("item_id", True, "item_id"),
    ("variation_id", True, "variation_id"),
    ("SKU", True, "sku"),
    ("tên", False, "name"),
    ("giá niêm yết", False, "list_price"),
    ("giá vốn", True, "cost"),
    ("đóng gói", False, "packaging"),
    ("giảm tối đa (%)", False, "max_discount"),
    ("tồn kho", False, "stock"),
    ("ngày nhập lại", False, "restock"),
    ("nhóm", False, "group"),
    ("trạng thái", False, "status"),
    ("số món / phân loại", False, "pack"),
    ("VAT (%)", False, "vat"),
)
#: (header, key) of the ``Thành phần combo`` sheet.
BOM_COLUMNS: tuple[tuple[str, str], ...] = (
    ("item_id", "item_id"),
    ("variation_id", "variation_id"),
    ("tên", "name"),
    ("SKU thành phần", "component"),
    ("số lượng", "qty"),
)
#: (label, rule key) of the two shop flags on the ``VAT`` sheet.
VAT_SETTINGS: tuple[tuple[str, str], ...] = (
    ("giá bán đã gồm VAT", PRICES_INCLUDE_VAT),
    ("giá vốn đã gồm VAT", COST_INCLUDES_VAT),
)
YES_NO_LABELS: dict[bool, str] = {True: "Có", False: "Không"}
GOAL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("tháng", "month"),
    ("GMV", MONTHLY_GMV),
    ("đơn", MONTHLY_ORDERS),
    ("AOV", MONTHLY_AOV),
    ("biên mục tiêu (%)", MONTHLY_MARGIN_PCT),
    ("trần chi marketing/ngày", MONTHLY_MARKETING_CAP),
)

GROUP_LABELS: dict[str, str] = {"thuong_hieu": "Thương hiệu", "phan_phoi": "Phân phối"}
STATUS_LABELS: dict[str, str] = {
    "ban": "Đang bán",
    "tam_dung": "Tạm dừng",
    "ngung": "Ngừng bán",
    "xa_hang": "Xả hàng",
}

NOTE_SKU = (
    "Cột nền hồng là bắt buộc, cột xám do Juli điền, không sửa. Ô trống giữ nguyên giá trị "
    "cũ. Không có tên, số điện thoại hay địa chỉ khách trong tệp."
)
NOTE_VALUES = (
    "nhóm: Thương hiệu hoặc Phân phối. trạng thái: Đang bán, Tạm dừng, Ngừng bán, Xả hàng. "
    "ngày nhập lại: dd/mm/yyyy. giảm tối đa: 0 đến 100."
)
NOTE_PACK = (
    "giá vốn là giá vốn của 1 món. số món / phân loại: số món trong 1 đơn vị bán ("
    "Combo 3 hộp = 3). Ô trống: Juli tự đọc từ tên phân loại (Combo N, Set N), không có thì là 1. "
    "VAT (%): 0, 5, 8 hoặc 10."
)
NOTE_BOM = (
    "Dùng cho sản phẩm không có SKU riêng (combo nhiều sản phẩm): mỗi dòng một thành phần. "
    "SKU thành phần là SKU có sẵn của shop; giá vốn = tổng giá vốn thành phần × số lượng. "
    "Một sản phẩm / phân loại có mặt trong trang này sẽ được thay toàn bộ thành phần."
)
NOTE_VAT = (
    "Chỉ điền khi chắc chắn. Có / Không. Để trống: Juli hiển thị lợi nhuận trước VAT và ghi rõ."
)
NOTE_GOALS = "Mỗi tháng một dòng, dạng T12/2026 hoặc 12/2026. Ô trống giữ nguyên giá trị cũ."


def format_date_vi(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def month_label(month: str) -> str:
    """``2026-12`` -> ``T12/2026``."""
    year, _, number = month.partition("-")
    return f"T{number}/{year}"


def _plain(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


@dataclass(frozen=True)
class TemplateResult:
    content: bytes
    sku_rows: int
    item_count: int
    prefilled_cost: int
    goal_rows: int
    sample_rows: int = 0
    bom_rows: int = 0
    pack_rows: int = 0


def pack_prefill(sku: CatalogueSku, current: dict[str, Any]) -> int | None:
    """The seller's pack count, else the one the variation name states; blank when neither."""
    value = current.get(PACK_COUNT)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return pack_count_from_name(sku.variation_name)


def sku_row(
    sku: CatalogueSku, current: dict[str, Any]
) -> list[xlsx_io.Cell | tuple[xlsx_io.Cell, int]]:
    """The cells of one SKU row, in ``SKU_COLUMNS`` order."""
    locked, edit = xlsx_io.STYLE_LOCKED, xlsx_io.STYLE_EDIT
    restock = current.get(RESTOCK_DATE)
    group = current.get(PRODUCT_GROUP)
    status = current.get(ITEM_STATUS)
    return [
        (sku.item_id, locked),
        (sku.variation_id, locked),
        (sku.sku, locked),
        (sku.name, locked),
        (_plain(sku.list_price), locked),
        (_plain(current.get(SKU_COST)), edit),
        (_plain(current.get(PACKAGING)), edit),
        (_plain(current.get(MAX_DISCOUNT_PCT)), edit),
        (effective_stock(sku, current), edit),
        (format_date_vi(restock) if isinstance(restock, str) else None, edit),
        (GROUP_LABELS.get(group) if isinstance(group, str) else None, edit),
        (STATUS_LABELS.get(status) if isinstance(status, str) else None, edit),
        (pack_prefill(sku, current), edit),
        (_plain(current.get(VAT_RATE)), edit),
    ]


async def build_template(session: AsyncSession, shop_id: uuid.UUID) -> TemplateResult:
    catalogue = await load_catalogue(session, shop_id)
    current = await load_current(session, shop_id)

    header_style = xlsx_io.STYLE_HEADER
    edit_style = xlsx_io.STYLE_EDIT
    sku_rows: list[list[Any]] = [
        [(f"{title} *" if required else title, header_style) for title, required, _ in SKU_COLUMNS]
    ]
    prefilled = 0
    pack_rows = 0
    for sku in catalogue:
        values = current.per_sku.get(sku.scope, {})
        if SKU_COST in values:
            prefilled += 1
        if pack_prefill(sku, values) is not None:
            pack_rows += 1
        sku_rows.append(sku_row(sku, values))
    sku_rows.append([])
    sku_rows.append([(NOTE_SKU, xlsx_io.STYLE_NOTE)])
    sku_rows.append([(NOTE_VALUES, xlsx_io.STYLE_NOTE)])
    sku_rows.append([(NOTE_PACK, xlsx_io.STYLE_NOTE)])

    goal_rows: list[list[Any]] = [[(title, header_style) for title, _ in GOAL_COLUMNS]]
    for month in sorted(current.monthly):
        values = current.monthly[month]
        goal_rows.append(
            [(month_label(month), xlsx_io.STYLE_EDIT)]
            + [(_plain(values.get(key)), xlsx_io.STYLE_EDIT) for _, key in GOAL_COLUMNS[1:]]
        )
    goal_rows.append([])
    goal_rows.append([(NOTE_GOALS, xlsx_io.STYLE_NOTE)])

    sample_rows, sample_count = await _sample_rows(session, shop_id, catalogue)
    by_scope = {s.scope: s for s in catalogue}
    bom_rows: list[list[Any]] = [[(title, header_style) for title, _ in BOM_COLUMNS]]
    for scope in sorted(s for s, v in current.per_sku.items() if PACK_COMPONENTS in v):
        listing = by_scope.get(scope)
        item_id, _, variation_id = scope.partition(":")
        for component in current.per_sku[scope][PACK_COMPONENTS]:
            bom_rows.append(
                [
                    (item_id, xlsx_io.STYLE_EDIT),
                    (variation_id or None, xlsx_io.STYLE_EDIT),
                    (listing.name if listing else None, xlsx_io.STYLE_LOCKED),
                    (component["sku"], xlsx_io.STYLE_EDIT),
                    (component["qty"], xlsx_io.STYLE_EDIT),
                ]
            )
    bom_count = len(bom_rows) - 1
    bom_rows.append([])
    bom_rows.append([(NOTE_BOM, xlsx_io.STYLE_NOTE)])

    vat_rows: list[list[Any]] = [
        [("thiết lập", header_style), ("giá trị", header_style)],
        *[
            [
                (label, xlsx_io.STYLE_LOCKED),
                (
                    YES_NO_LABELS.get(current.flags[key]) if key in current.flags else None,
                    edit_style,
                ),
            ]
            for label, key in VAT_SETTINGS
        ],
        [],
        [(NOTE_VAT, xlsx_io.STYLE_NOTE)],
    ]

    content = xlsx_io.write_workbook(
        [
            xlsx_io.SheetSpec(
                SKU_SHEET,
                sku_rows,
                widths=(16, 16, 22, 44, 14, 14, 12, 16, 10, 16, 14, 14, 18, 10),
                protect=True,
            ),
            xlsx_io.SheetSpec(GOAL_SHEET, goal_rows, widths=(12, 16, 10, 12, 18, 24)),
            xlsx_io.SheetSpec(
                kol_samples.SAMPLE_SHEET, sample_rows, widths=(24, 26, 14, 14, 18, 30)
            ),
            xlsx_io.SheetSpec(BOM_SHEET, bom_rows, widths=(16, 16, 44, 22, 12)),
            xlsx_io.SheetSpec(VAT_SHEET, vat_rows, widths=(28, 14)),
        ]
    )
    return TemplateResult(
        content=content,
        sku_rows=len(catalogue),
        item_count=len({s.item_id for s in catalogue}),
        prefilled_cost=prefilled,
        goal_rows=len(goal_rows) - 3,
        sample_rows=sample_count,
        bom_rows=bom_count,
        pack_rows=pack_rows,
    )


async def _sample_rows(
    session: AsyncSession, shop_id: uuid.UUID, catalogue: list[CatalogueSku]
) -> tuple[list[list[Any]], int]:
    """The Mẫu KOL sheet: one row per shipment sent, and one blank row per KOL x product pair
    that already sold (so the seller only types quantity, date and shipping)."""
    by_scope = {c.scope: c for c in catalogue}
    header_style = xlsx_io.STYLE_HEADER
    edit = xlsx_io.STYLE_EDIT

    def product_ref(scope: str) -> str:
        sku = by_scope.get(scope)
        return (sku.sku or scope) if sku else scope

    rows: list[list[Any]] = [
        [
            (f"{title} *" if required else title, header_style)
            for title, required, _ in kol_samples.SAMPLE_COLUMNS
        ]
    ]
    sent = await kol_samples.load_samples(session, shop_id)
    have: set[tuple[str, str]] = set()
    count = 0
    for (key, scope), shipments in sorted(sent.items()):
        have.add((key, scope))
        for shipment in shipments:
            count += 1
            rows.append(
                [
                    (shipment.handle, edit),
                    (product_ref(scope), edit),
                    (shipment.qty, edit),
                    (format_date_vi(shipment.sent_on.isoformat()), edit),
                    (_plain(shipment.ship_fee), edit),
                    (None, edit),
                ]
            )
    for handle, item_id in await kol_samples.known_pairs(session, shop_id):
        if (kol_samples.make_key(handle), item_id) in have:
            continue
        rows.append(
            [
                (handle, edit),
                (product_ref(item_id), edit),
                (None, edit),
                (None, edit),
                (None, edit),
                (None, edit),
            ]
        )
    rows.append([])
    rows.append([(kol_samples.NOTE_SAMPLE, xlsx_io.STYLE_NOTE)])
    return rows, count
