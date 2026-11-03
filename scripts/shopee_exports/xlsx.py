"""A minimal .xlsx reader (stdlib only): every sheet as rows of cell strings.

Seller Centre exports store numbers as formatted text ("12.345.678", "4,25%"), so cell
values are returned exactly as stored and ``parse.number`` reads them. Formulas, styles
and dates-as-serials are not needed for these files and are not handled.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
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


# -- column-selective reader (buyer-bearing exports) --------------------------------------


@dataclass
class ColumnRead:
    """One sheet read through a header allowlist (``read_columns``)."""

    header: list[str]
    #: Row number is not kept; each row maps header index -> cell string for CHOSEN columns only.
    rows: list[dict[int, str | None]]
    #: Header indexes whose cell VALUES were materialised, for the "no buyer column read" check.
    value_columns_read: set[int]


def _sheet_target(archive: zipfile.ZipFile, sheet: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {rel.get("Id"): rel.get("Target", "") for rel in rels}
    sheet_list = workbook.find("m:sheets", _NS)
    for node in sheet_list if sheet_list is not None else []:
        if node.get("name") == sheet:
            target = targets[node.get(f"{{{_REL}}}id")].lstrip("/")
            return target if target.startswith("xl/") else f"xl/{target}"
    raise ValueError(f"sheet {sheet!r} not found")


def _cells(row: ET.Element) -> Iterator[tuple[int, ET.Element]]:
    for cell in row.findall("m:c", _NS):
        yield _column_index(cell.get("r", "A1")), cell


def _raw(cell: ET.Element) -> tuple[str | None, str | None]:
    """(kind, text) of a cell; for a shared string the text is the table index."""
    kind = cell.get("t")
    if kind == "inlineStr":
        return kind, _text(cell)
    value = cell.find("m:v", _NS)
    return kind, (value.text if value is not None else None)


def _needed_strings(archive: zipfile.ZipFile, wanted: set[int]) -> dict[int, str]:
    """Only the shared strings in ``wanted`` (the others are skipped, never decoded)."""
    found: dict[int, str] = {}
    if not wanted or "xl/sharedStrings.xml" not in archive.namelist():
        return found
    index = 0
    with archive.open("xl/sharedStrings.xml") as handle:
        for _, node in ET.iterparse(handle):
            if node.tag == f"{{{_MAIN}}}si":
                if index in wanted:
                    found[index] = _text(node)
                index += 1
                node.clear()
    return found


def read_columns(
    path: Path, sheet: str, choose: Callable[[list[str]], Iterable[int]]
) -> ColumnRead:
    """Read ``sheet`` with its FIRST row as the header. ``choose(header)`` returns the header
    indexes whose values may be read (and may raise to stop the load); every other cell is
    never decoded. Cells of unchosen columns are not touched."""
    with zipfile.ZipFile(path) as archive:
        target = _sheet_target(archive, sheet)
        header: list[str] = []
        chosen: set[int] = set()
        raw_rows: list[dict[int, tuple[str | None, str | None]]] = []
        read: set[int] = set()
        wanted: set[int] = set()
        with archive.open(target) as handle:
            for _, node in ET.iterparse(handle):
                if node.tag != f"{{{_MAIN}}}row":
                    continue
                if not header:
                    # Header cells are names, not data: all of them are read.
                    cells = {i: _raw(c) for i, c in _cells(node)}
                    shared = {int(t) for k, t in cells.values() if k == "s" and t is not None}
                    names = _needed_strings(archive, shared)
                    header = [
                        (names.get(int(t), "") if k == "s" and t is not None else (t or "")).strip()
                        for i in range(max(cells) + 1)
                        for k, t in [cells.get(i, (None, None))]
                    ]
                    if not header:
                        node.clear()
                        continue
                    chosen = set(choose(header))
                else:
                    row: dict[int, tuple[str | None, str | None]] = {}
                    for index, cell in _cells(node):
                        if index in chosen:
                            kind, text = _raw(cell)
                            read.add(index)
                            row[index] = (kind, text)
                            if kind == "s" and text is not None:
                                wanted.add(int(text))
                    raw_rows.append(row)
                node.clear()
        strings = _needed_strings(archive, wanted)
    rows: list[dict[int, str | None]] = []
    for row in raw_rows:
        rows.append(
            {
                i: (strings.get(int(t)) if k == "s" and t is not None else t)
                for i, (k, t) in row.items()
            }
        )
    return ColumnRead(header=header, rows=rows, value_columns_read=read)
