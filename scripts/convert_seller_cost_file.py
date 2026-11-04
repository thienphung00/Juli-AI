"""Turn a seller's internal cost file into a filled Cài đặt template (P91 D-12).

    # 1. Download the template from Cài đặt › Thông số shop (one SKU row per variation).
    # 2. Run the seller's own file through it:
    python scripts/convert_seller_cost_file.py "Tồn kho và giá.xlsx" --template mau-thong-so.xlsx
    # 3. Check the printed counts, then upload the written file through the normal import
    #    (preview -> reason -> apply). This script never touches a database.

The seller's file has the headers ``Mã nội bộ, Tên, Đơn vị tính, Giá bán, Giá vốn, Số lượng dự
báo, Số lượng hiện có, Kích thước đóng gói``. ``Mã nội bộ`` is the Shopee variation SKU of a single
item. For each template SKU row whose SKU equals a ``Mã nội bộ`` (case and surrounding spaces
ignored):

- ``giá vốn`` = ``Giá vốn`` (the cost of ONE item; a combo variation that reuses the base SKU
  is costed by its pack count in the profit, not here);
- ``số món / phân loại`` = the pack read from the variation name ("Combo 3 hộp" 3, "Set 3" 3,
  "Combo 2 30cm x5m" 2), only when it is more than 1 and the cell is empty;
- ``tồn kho`` = ``Số lượng hiện có`` (items on hand) divided by the pack, rounded down: a
  "Combo 3 hộp" listing is sold from the same shelf, 3 items per unit.

A blank, zero or unreadable ``Giá vốn`` is not a cost: that row is left as the template had it.
Nothing else in the seller's file is copied (no names, prices or sizes). The codes with no template
row are listed so the seller can add the missing listing or fix the code.

The output goes OUTSIDE the repository (default: the OS temp directory) because it holds the
client's costs; the script refuses a path inside the repo.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HEADER_MARKER = "Mã nội bộ"
COST_COLUMNS = {
    "code": "Mã nội bộ",
    "cost": "Giá vốn",
    "on_hand": "Số lượng hiện có",
}
SKU_SHEET = "SKU"
MAX_HEADER_ROWS = 10
_NUMBER_JUNK = re.compile(r"[\s ₫đ]")


def fold(text: str) -> str:
    """Lower-case without diacritics, for matching headers."""
    decomposed = unicodedata.normalize("NFD", text.strip().lower().replace("đ", "d"))
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def number(text: str | None) -> Decimal | None:
    """A cell as a number: ``12.500``, ``12,5``, ``12500đ``, ``1E5``; None when it is not one."""
    if text is None:
        return None
    cleaned = _NUMBER_JUNK.sub("", text.strip().rstrip("đ"))
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = (
            cleaned.replace(",", "")
            if re.fullmatch(r"\d{1,3}(,\d{3}){2,}", cleaned)
            else cleaned.replace(",", ".")
        )
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", cleaned):
        cleaned = cleaned.replace(".", "")
    try:
        value = Decimal(cleaned)
    except ArithmeticError:
        return None
    return value if value.is_finite() else None


@dataclass(frozen=True)
class CostRow:
    code: str
    cost: Decimal | None
    on_hand: int | None


@dataclass
class CostFile:
    rows: dict[str, CostRow] = field(default_factory=dict)
    duplicates: int = 0
    without_cost: int = 0


@dataclass
class Conversion:
    """The filled SKU sheet and the counts the operator checks before uploading."""

    rows: list[list[str | None]]
    template_rows: int = 0
    matched: int = 0
    costs_filled: int = 0
    stock_filled: int = 0
    packs_filled: int = 0
    #: Codes of the seller's file that no template row carries (original spelling).
    unmatched_codes: list[str] = field(default_factory=list)
    cost_file_codes: int = 0
    duplicates: int = 0
    without_cost: int = 0


def _key(code: str) -> str:
    return code.strip().casefold()


def read_cost_file(sheets: dict[str, list[list[str | None]]]) -> CostFile:
    """The first sheet that has the ``Mã nội bộ`` header row."""
    for rows in sheets.values():
        for index, row in enumerate(rows[:MAX_HEADER_ROWS]):
            names = [fold(c or "") for c in row]
            if fold(HEADER_MARKER) not in names:
                continue
            column = {k: names.index(fold(v)) for k, v in COST_COLUMNS.items() if fold(v) in names}
            if "cost" not in column:
                raise ValueError("the cost file has no 'Giá vốn' column")
            return _read_rows(rows[index + 1 :], column)
    raise ValueError("no 'Mã nội bộ' header row in the cost file")


def _cell(row: list[str | None], index: int | None) -> str | None:
    if index is None or index >= len(row):
        return None
    return row[index]


def _read_rows(rows: list[list[str | None]], column: dict[str, int]) -> CostFile:
    out = CostFile()
    for row in rows:
        code = (_cell(row, column["code"]) or "").strip()
        if not code:
            continue
        cost = number(_cell(row, column.get("cost")))
        on_hand_value = number(_cell(row, column.get("on_hand")))
        on_hand = (
            int(on_hand_value)
            if on_hand_value is not None
            and on_hand_value == on_hand_value.to_integral_value()
            and on_hand_value >= 0
            else None
        )
        if cost is None or cost <= 0:
            cost = None
            out.without_cost += 1
        key = _key(code)
        if key in out.rows:
            out.duplicates += 1
        out.rows[key] = CostRow(code, cost, on_hand)
    return out


def _variation_label(name: str | None) -> str | None:
    """The variation part of the template's ``tên`` cell (``<item> · <variation>``)."""
    if not name:
        return None
    return name.rsplit(" · ", 1)[1] if " · " in name else None


def convert(template: list[list[str | None]], costs: CostFile) -> Conversion:
    """Fill the template's SKU rows from ``costs``; the template is not modified."""
    from juli_backend.services.shopee_profit.pack import pack_count_from_name

    if not template:
        raise ValueError("the template's SKU sheet is empty")
    header = [fold(re.sub(r"\s*\*$", "", c or "")) for c in template[0]]

    def index_of(name: str) -> int | None:
        return header.index(fold(name)) if fold(name) in header else None

    sku_col = index_of("SKU")
    cost_col, stock_col = index_of("giá vốn"), index_of("tồn kho")
    pack_col, name_col = index_of("số món / phân loại"), index_of("tên")
    if sku_col is None or cost_col is None:
        raise ValueError("the template's SKU sheet needs the 'SKU' and 'giá vốn' columns")

    result = Conversion(
        rows=[list(template[0])],
        cost_file_codes=len(costs.rows),
        duplicates=costs.duplicates,
        without_cost=costs.without_cost,
    )
    used: set[str] = set()
    for original in template[1:]:
        row = list(original) + [None] * (len(template[0]) - len(original))
        code = (_cell(row, sku_col) or "").strip()
        cells = [(c or "").strip() for c in row]
        is_data = bool(code) and any(cells[1:])
        match = costs.rows.get(_key(code)) if is_data else None
        if match is None:
            result.rows.append(row)
            continue
        result.matched += 1
        used.add(_key(code))
        pack = pack_count_from_name(_variation_label(_cell(row, name_col))) or 1
        if match.cost is not None:
            row[cost_col] = _text(match.cost)
            result.costs_filled += 1
        if stock_col is not None and match.on_hand is not None:
            row[stock_col] = str(match.on_hand // pack)
            result.stock_filled += 1
        if pack_col is not None and pack > 1 and not (_cell(row, pack_col) or "").strip():
            row[pack_col] = str(pack)
            result.packs_filled += 1
        result.rows.append(row)
    result.template_rows = sum(
        1
        for original in template[1:]
        if (_cell(original, sku_col) or "").strip() and any((c or "").strip() for c in original[1:])
    )
    result.unmatched_codes = sorted(
        (r.code for k, r in costs.rows.items() if k not in used), key=str.casefold
    )
    return result


def _text(value: Decimal) -> str:
    return str(int(value)) if value == value.to_integral_value() else str(value.normalize())


def write_template(conversion: Conversion, path: Path) -> None:
    """The converted SKU sheet as an ``.xlsx`` the import accepts (SKU sheet only)."""
    from juli_backend.services.shop_inputs import xlsx_io

    locked = {0, 1, 2, 3, 4}  # item_id, variation_id, SKU, tên, giá niêm yết: Juli's columns
    rows: list[list[object]] = [[(c, xlsx_io.STYLE_HEADER) for c in conversion.rows[0]]]
    for row in conversion.rows[1:]:
        rows.append(
            [
                (c, xlsx_io.STYLE_LOCKED if i in locked else xlsx_io.STYLE_EDIT)
                for i, c in enumerate(row)
            ]
        )
    content = xlsx_io.write_workbook(
        [
            xlsx_io.SheetSpec(
                SKU_SHEET, rows, widths=(16, 16, 22, 44, 14, 14, 12, 16, 10, 16, 14, 14, 18, 10)
            )
        ]
    )
    path.write_bytes(content)


def output_path(requested: Path | None, source: Path) -> Path:
    """Where the file goes: the OS temp dir by default; never inside the repository."""
    target = (
        requested
        or Path(tempfile.gettempdir()) / f"cai-dat-{fold(source.stem).replace(' ', '-')}.xlsx"
    )
    resolved = target.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise SystemExit(
            f"refusing {resolved}: the output holds the client's costs and stays outside the repo"
        )
    return resolved


def summary(conversion: Conversion, *, list_codes: bool) -> str:
    lines = [
        f"template SKU rows            {conversion.template_rows}",
        f"cost file codes              {conversion.cost_file_codes}"
        f" (repeated: {conversion.duplicates},"
        f" without a usable giá vốn: {conversion.without_cost})",
        f"template rows matched        {conversion.matched}",
        f"giá vốn filled               {conversion.costs_filled}",
        f"tồn kho filled               {conversion.stock_filled}",
        f"số món / phân loại filled    {conversion.packs_filled}",
        f"cost file codes with no row  {len(conversion.unmatched_codes)}",
    ]
    if list_codes and conversion.unmatched_codes:
        lines.append("  " + ", ".join(conversion.unmatched_codes))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("cost_file", type=Path, help="the seller's internal cost file (.xlsx)")
    parser.add_argument("--template", type=Path, required=True, help="the Cài đặt template (.xlsx)")
    parser.add_argument("--out", type=Path, help="output .xlsx (default: the OS temp directory)")
    parser.add_argument(
        "--no-list-codes", action="store_true", help="print only the count of unmatched codes"
    )
    args = parser.parse_args(argv)

    from juli_backend.services.shop_inputs import xlsx_io

    try:
        costs = read_cost_file(xlsx_io.read_workbook(args.cost_file.read_bytes()))
        sheets = xlsx_io.read_workbook(args.template.read_bytes())
    except (ValueError, xlsx_io.WorkbookUnreadable) as exc:
        print(f"cannot read: {exc}", file=sys.stderr)
        return 2
    sku_sheet = next((rows for name, rows in sheets.items() if fold(name) == fold(SKU_SHEET)), None)
    if sku_sheet is None:
        print("the template has no SKU sheet", file=sys.stderr)
        return 2
    conversion = convert(sku_sheet, costs)
    target = output_path(args.out, args.cost_file)
    write_template(conversion, target)
    print(summary(conversion, list_codes=not args.no_list_codes))
    print(f"written {target} (upload it through Cài đặt › Thông số shop)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
