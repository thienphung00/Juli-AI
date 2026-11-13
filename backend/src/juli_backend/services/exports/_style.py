"""Shared workbook formatting: Arial 10, bold header on a light fill, frozen header, formats."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

FONT = Font(name="Arial", size=10)
BOLD = Font(name="Arial", size=10, bold=True)
TITLE = Font(name="Arial", size=12, bold=True)
FILL = PatternFill("solid", start_color="E8EEF4", end_color="E8EEF4")
MONEY = "#,##0"
PCT = "0.0%"
POINTS = "0.0"
DATE = "dd/mm/yyyy"
INT = "#,##0"


def new_workbook() -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)
    wb.calculation.fullCalcOnLoad = True
    return wb


def col(n: int) -> str:
    return get_column_letter(n)


def put(
    ws: Worksheet, row: int, column: int, value: Any, fmt: str | None = None, *, bold: bool = False
):
    """Write one cell (a ``date`` keeps the date format, ``None`` stays empty)."""
    cell = ws.cell(row=row, column=column)
    if value is not None:
        cell.value = value
    cell.font = BOLD if bold else FONT
    if fmt is not None:
        cell.number_format = fmt
    elif isinstance(value, date):
        cell.number_format = DATE
    return cell


def header(ws: Worksheet, row: int, labels: Sequence[str], first_col: int = 1) -> None:
    for i, label in enumerate(labels):
        c = ws.cell(row=row, column=first_col + i, value=label)
        c.font = BOLD
        c.fill = FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def widths(ws: Worksheet, values: dict[int, float] | Sequence[float], default: float = 14) -> None:
    items = values.items() if isinstance(values, dict) else enumerate(values, start=1)
    for i, w in items:
        ws.column_dimensions[col(i)].width = w
    for i in range(1, ws.max_column + 1):
        if col(i) not in ws.column_dimensions or ws.column_dimensions[col(i)].width is None:
            ws.column_dimensions[col(i)].width = default


def finish(ws: Worksheet, freeze: str) -> None:
    ws.freeze_panes = freeze
    ws.sheet_view.showGridLines = True


def save_bytes(wb: Workbook) -> bytes:
    import io

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
