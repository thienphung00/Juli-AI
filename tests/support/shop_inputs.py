"""Synthetic Shopee catalogue and template-editing helpers for the P90 step 4 tests."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Shop
from juli_backend.models.platform_data import PlatformItem
from juli_backend.models.shopee_profit import PlatformItemSnapshot
from juli_backend.services.shop_inputs import xlsx_io

NOW = datetime(2026, 11, 3, 12, 0)

#: (item_id, variation_id, seller SKU, name, list price, platform stock)
CATALOGUE: list[tuple[str, str, str, str, int, int | None]] = [
    ("1001", "", "GL-001", "Găng tay cao su", 74_000, 120),
    ("1002", "", "NR-002", "Nước rửa chén 750ml", 106_000, 0),
    ("2001", "2001-a", "BEP-S5-CB", "Bộ 5 món · Cơ bản", 200_000, 214),
    ("2001", "2001-b", "BEP-S5-L", "Bộ 5 món · Găng size L", 185_000, 96),
    ("2002", "", "BEP-S3", "Bộ 3 món", 129_000, 9),
]


async def seed_catalogue(session: AsyncSession, shop: Shop, rows=CATALOGUE) -> None:
    for item_id, variation_id, sku, name, price, stock in rows:
        session.add(
            PlatformItem(
                id=uuid.uuid4(),
                shop_id=shop.id,
                platform="shopee",
                item_id=item_id,
                variation_id=variation_id,
                name=name if not variation_id else "Bộ 5 món",
                variation_name=name.split("· ")[-1] if variation_id else None,
                seller_sku=sku,
                source="file",
                source_rank=2,
                source_version="t",
                captured_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            PlatformItemSnapshot(
                id=uuid.uuid4(),
                shop_id=shop.id,
                platform="shopee",
                item_id=item_id,
                variation_id=variation_id,
                captured_at=NOW,
                title=name,
                list_price=Decimal(price),
                stock=stock,
                source="file",
                source_rank=2,
            )
        )
    await session.commit()


def edit_workbook(content: bytes, edits: dict[str, dict[tuple[int, int], object]]) -> bytes:
    """Rewrite ``content`` with cell edits: ``{sheet: {(row, col): value}}``, 0-based.

    Rows beyond the sheet's end are appended; a value of ``None`` clears the cell.
    """
    sheets = xlsx_io.read_workbook(content)
    out = []
    for name, rows in sheets.items():
        grid = [list(r) for r in rows]
        for (r, c), value in edits.get(name, {}).items():
            while len(grid) <= r:
                grid.append([])
            while len(grid[r]) <= c:
                grid[r].append(None)
            grid[r][c] = value
        out.append(xlsx_io.SheetSpec(name, grid))
    return xlsx_io.write_workbook(out)


def sheet_rows(content: bytes, name: str):
    return xlsx_io.read_workbook(content)[name]


def find_row(rows, sku: str) -> int:
    """Index of the row whose SKU column (index 2) is ``sku``."""
    return next(i for i, row in enumerate(rows) if len(row) > 2 and row[2] == sku)


#: SKU sheet column indexes.
COL = {
    "item_id": 0,
    "variation_id": 1,
    "sku": 2,
    "name": 3,
    "list_price": 4,
    "cost": 5,
    "packaging": 6,
    "max_discount": 7,
    "stock": 8,
    "restock": 9,
    "group": 10,
    "status": 11,
}
