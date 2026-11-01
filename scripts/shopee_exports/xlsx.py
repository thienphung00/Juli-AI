"""A minimal .xlsx reader (stdlib only): every sheet as rows of cell strings.

Seller Centre exports store numbers as formatted text ("12.345.678", "4,25%"), so cell
values are returned exactly as stored and ``parse.number`` reads them. Formulas, styles
and dates-as-serials are not needed for these files and are not handled.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {"m": _MAIN}
_COLUMN = re.compile(r"[A-Z]+")

Rows = list[list[str | None]]


def _column_index(ref: str) -> int:
    match = _COLUMN.match(ref)
    if match is None:
        raise ValueError(f"bad cell reference {ref!r}")
    index = 0
    for char in match.group():
        index = index * 26 + ord(char) - 64
    return index - 1


def _text(node: ET.Element) -> str:
    return "".join(t.text or "" for t in node.iter(f"{{{_MAIN}}}t"))


def read_workbook(path: Path) -> dict[str, Rows]:
    """``{sheet name: rows}``; a row is a list of cell strings (None = empty cell)."""
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = [_text(item) for item in root.findall("m:si", _NS)]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.get("Id"): rel.get("Target", "") for rel in rels}
        sheets: dict[str, Rows] = {}
        sheet_list = workbook.find("m:sheets", _NS)
        for sheet in sheet_list if sheet_list is not None else []:
            target = targets[sheet.get(f"{{{_REL}}}id")].lstrip("/")
            target = target if target.startswith("xl/") else f"xl/{target}"
            rows: Rows = []
            for row in ET.fromstring(archive.read(target)).iter(f"{{{_MAIN}}}row"):
                cells: dict[int, str | None] = {}
                for cell in row.findall("m:c", _NS):
                    kind, value = cell.get("t"), cell.find("m:v", _NS)
                    if kind == "s":
                        text = shared[int(value.text or 0)] if value is not None else None
                    elif kind == "inlineStr":
                        text = _text(cell)
                    else:
                        text = value.text if value is not None else None
                    cells[_column_index(cell.get("r", "A1"))] = text
                rows.append([cells.get(i) for i in range(max(cells) + 1)] if cells else [])
            sheets[sheet.get("name", "")] = rows
        return sheets
