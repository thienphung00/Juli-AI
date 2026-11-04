"""A minimal .xlsx writer and reader (stdlib only) for the seller-input template.

The writer emits two kinds of cell -- text (inline strings) and numbers -- with a bold
header, a grey read-only look for the columns Juli fills, and sheet protection that locks
only those columns (no password: it guards against a stray edit, not against the seller).
The reader returns every cell as the string stored, so ``importer`` parses numbers and
dates itself. Formulas are not evaluated: a formula cell reads as its cached value.

The reader refuses oversized files before parsing (size, uncompressed size, row count).
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS = {"m": _MAIN}
_COLUMN = re.compile(r"[A-Z]+")

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 60 * 1024 * 1024
MAX_ROWS = 20_000

Cell = str | int | float | Decimal | None
Rows = list[list[str | None]]

#: Cell styles (indexes into ``cellXfs`` below).
STYLE_PLAIN = 0
STYLE_HEADER = 1
STYLE_LOCKED = 2  # filled by Juli, not for editing
STYLE_EDIT = 3  # the seller fills it in (unlocked on a protected sheet)
STYLE_NOTE = 4

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font>\
<font><b/><sz val="11"/><name val="Calibri"/></font>\
<font><i/><sz val="10"/><color rgb="FF6B6B76"/><name val="Calibri"/></font></fonts>
<fills count="4"><fill><patternFill patternType="none"/></fill>\
<fill><patternFill patternType="gray125"/></fill>\
<fill><patternFill patternType="solid"><fgColor rgb="FFF0EEF0"/>\
<bgColor indexed="64"/></patternFill></fill>\
<fill><patternFill patternType="solid"><fgColor rgb="FFFDEEF4"/>
<bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5">\
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>\
<xf numFmtId="0" fontId="1" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"/>\
<xf numFmtId="0" fontId="0" fillId="2" borderId="0" xfId="0" applyFill="1"/>\
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyProtection="1">\
<protection locked="0"/></xf>\
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


@dataclass
class SheetSpec:
    """One sheet: ``rows`` of ``(value, style)`` pairs or bare values (plain style)."""

    name: str
    rows: Sequence[Sequence[Cell | tuple[Cell, int]]]
    widths: Sequence[int] = ()
    #: Lock the whole sheet (cells in ``STYLE_EDIT`` stay editable).
    protect: bool = False
    freeze_header: bool = True
    extra: dict[str, str] = field(default_factory=dict)


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _cell_xml(ref: str, value: Cell, style: int) -> str:
    if value is None or value == "":
        return f'<c r="{ref}" s="{style}"/>' if style else ""
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int | float | Decimal):
        return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
    text = escape(str(value))
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(spec: SheetSpec) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    out.append(f'<worksheet xmlns="{_MAIN}">')
    if spec.freeze_header:
        out.append(
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
            'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        )
    if spec.widths:
        out.append("<cols>")
        for i, width in enumerate(spec.widths, start=1):
            out.append(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>')
        out.append("</cols>")
    out.append("<sheetData>")
    for r, row in enumerate(spec.rows, start=1):
        cells = []
        for c, item in enumerate(row):
            value, style = item if isinstance(item, tuple) else (item, STYLE_PLAIN)
            cells.append(_cell_xml(f"{_column_letter(c)}{r}", value, style))
        out.append(f'<row r="{r}">{"".join(cells)}</row>')
    out.append("</sheetData>")
    if spec.protect:
        out.append('<sheetProtection sheet="1" objects="1" scenarios="1"/>')
    out.append("</worksheet>")
    return "".join(out)


def write_workbook(sheets: Sequence[SheetSpec]) -> bytes:
    """The workbook as ``.xlsx`` bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
            'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{overrides}</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        sheet_tags = "".join(
            f'<sheet name="{escape(spec.name)}" sheetId="{i}" r:id="rId{i}"/>'
            for i, spec in enumerate(sheets, start=1)
        )
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<workbook xmlns="{_MAIN}" xmlns:r="{_REL}"><sheets>{sheet_tags}</sheets></workbook>',
        )
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/'
            f'2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        n = len(sheets) + 1
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{rels}<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/'
            f'officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        )
        archive.writestr("xl/styles.xml", _STYLES)
        for i, spec in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(spec))
    return buffer.getvalue()


class WorkbookUnreadable(ValueError):
    """The upload is not a readable .xlsx within the size limits."""


def _parse_xml(data: bytes) -> ET.Element:
    """Parse one part of an uploaded workbook. A real .xlsx part never declares a DTD; refusing any
    ``<!DOCTYPE`` / ``<!ENTITY`` rules out entity-expansion bombs before expat sees the bytes
    (expat itself never fetches external entities)."""
    head = data.upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise WorkbookUnreadable("not an .xlsx file")
    return ET.fromstring(data)  # nosec B314 - DTDs refused above; no external entity fetch


def _column_index(ref: str) -> int:
    match = _COLUMN.match(ref)
    if match is None:
        raise WorkbookUnreadable(f"bad cell reference {ref!r}")
    index = 0
    for char in match.group():
        index = index * 26 + ord(char) - 64
    return index - 1


def _text(node: ET.Element) -> str:
    return "".join(t.text or "" for t in node.iter(f"{{{_MAIN}}}t"))


def read_workbook(data: bytes) -> dict[str, Rows]:
    """``{sheet name: rows}``; a row is a list of cell strings (``None`` = empty cell)."""
    if len(data) > MAX_FILE_BYTES:
        raise WorkbookUnreadable("file too large")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise WorkbookUnreadable("not an .xlsx file") from None
    with archive:
        if sum(i.file_size for i in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
            raise WorkbookUnreadable("file too large once unpacked")
        names = set(archive.namelist())
        if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
            raise WorkbookUnreadable("not an .xlsx file")
        try:
            shared: list[str] = []
            if "xl/sharedStrings.xml" in names:
                root = _parse_xml(archive.read("xl/sharedStrings.xml"))
                shared = [_text(item) for item in root.findall("m:si", _NS)]
            workbook = _parse_xml(archive.read("xl/workbook.xml"))
            rels = _parse_xml(archive.read("xl/_rels/workbook.xml.rels"))
            targets = {rel.get("Id"): rel.get("Target", "") for rel in rels}
            sheets: dict[str, Rows] = {}
            sheet_list = workbook.find("m:sheets", _NS)
            for sheet in sheet_list if sheet_list is not None else []:
                target = targets[sheet.get(f"{{{_REL}}}id")].lstrip("/")
                target = target if target.startswith("xl/") else f"xl/{target}"
                rows: Rows = []
                for row in _parse_xml(archive.read(target)).iter(f"{{{_MAIN}}}row"):
                    if len(rows) >= MAX_ROWS:
                        raise WorkbookUnreadable("too many rows")
                    cells: dict[int, str | None] = {}
                    for cell in row.findall("m:c", _NS):
                        kind, value = cell.get("t"), cell.find("m:v", _NS)
                        if kind == "s":
                            text = shared[int(value.text or 0)] if value is not None else None
                        elif kind == "inlineStr":
                            text = _text(cell)
                        elif kind == "e":
                            text = "#ERR"
                        else:
                            text = value.text if value is not None else None
                        cells[_column_index(cell.get("r", "A1"))] = text
                    row_number = int(row.get("r") or len(rows) + 1)
                    while len(rows) < row_number - 1:
                        rows.append([])
                    rows.append([cells.get(i) for i in range(max(cells) + 1)] if cells else [])
                sheets[sheet.get("name", "")] = rows
        except (ET.ParseError, KeyError, IndexError, ValueError) as exc:
            if isinstance(exc, WorkbookUnreadable):
                raise
            raise WorkbookUnreadable("not a readable .xlsx file") from None
        return sheets
