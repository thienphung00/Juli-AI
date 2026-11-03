"""The seller-input template: ``.xlsx`` with sheets ``SKU`` and ``Mục tiêu``.

Pre-filled with what Juli holds: one row per SKU of the shop's catalogue (list price
read-only, from the latest product snapshot), the seller's current values written back,
and the months already set. Empty cell = keep the old value. No buyer data is in the file.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.services.shop_inputs import xlsx_io
from juli_backend.services.shop_inputs.catalogue import (
    CatalogueSku,
    effective_stock,
    load_catalogue,
    load_current,
)
from juli_backend.services.shop_rules.rules import (
    ITEM_STATUS,
    MAX_DISCOUNT_PCT,
    MONTHLY_AOV,
    MONTHLY_GMV,
    MONTHLY_MARGIN_PCT,
    MONTHLY_MARKETING_CAP,
    MONTHLY_ORDERS,
    PACKAGING,
    PRODUCT_GROUP,
    RESTOCK_DATE,
    SKU_COST,
)

SKU_SHEET = "SKU"
GOAL_SHEET = "Mục tiêu"

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
)
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
    ]


async def build_template(session: AsyncSession, shop_id: uuid.UUID) -> TemplateResult:
    catalogue = await load_catalogue(session, shop_id)
    current = await load_current(session, shop_id)

    header_style = xlsx_io.STYLE_HEADER
    sku_rows: list[list[Any]] = [
        [(f"{title} *" if required else title, header_style) for title, required, _ in SKU_COLUMNS]
    ]
    prefilled = 0
    for sku in catalogue:
        values = current.per_sku.get(sku.scope, {})
        if SKU_COST in values:
            prefilled += 1
        sku_rows.append(sku_row(sku, values))
    sku_rows.append([])
    sku_rows.append([(NOTE_SKU, xlsx_io.STYLE_NOTE)])
    sku_rows.append([(NOTE_VALUES, xlsx_io.STYLE_NOTE)])

    goal_rows: list[list[Any]] = [[(title, header_style) for title, _ in GOAL_COLUMNS]]
    for month in sorted(current.monthly):
        values = current.monthly[month]
        goal_rows.append(
            [(month_label(month), xlsx_io.STYLE_EDIT)]
            + [(_plain(values.get(key)), xlsx_io.STYLE_EDIT) for _, key in GOAL_COLUMNS[1:]]
        )
    goal_rows.append([])
    goal_rows.append([(NOTE_GOALS, xlsx_io.STYLE_NOTE)])

    content = xlsx_io.write_workbook(
        [
            xlsx_io.SheetSpec(
                SKU_SHEET,
                sku_rows,
                widths=(16, 16, 22, 44, 14, 14, 12, 16, 10, 16, 14, 14),
                protect=True,
            ),
            xlsx_io.SheetSpec(GOAL_SHEET, goal_rows, widths=(12, 16, 10, 12, 18, 24)),
        ]
    )
    return TemplateResult(
        content=content,
        sku_rows=len(catalogue),
        item_count=len({s.item_id for s in catalogue}),
        prefilled_cost=prefilled,
        goal_rows=len(goal_rows) - 3,
    )
