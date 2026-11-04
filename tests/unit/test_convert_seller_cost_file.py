"""P91 D-12: ``scripts/convert_seller_cost_file.py`` - the seller's internal cost file into a
filled Cài đặt template, for the normal import (it never writes a database).

Synthetic files only: the cost file has the real header row (``Mã nội bộ, Tên, Đơn vị tính, Giá
bán, Giá vốn, Số lượng dự báo, Số lượng hiện có, Kích thước đóng gói``), every code, name and amount
is invented.
"""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from juli_backend.services.shop_inputs import xlsx_io
from scripts import convert_seller_cost_file as convert

COST_HEADER = [
    "Mã nội bộ",
    "Tên",
    "Đơn vị tính",
    "Giá bán",
    "Giá vốn",
    "Số lượng dự báo",
    "Số lượng hiện có",
    "Kích thước đóng gói",
]
TEMPLATE_HEADER = [
    "item_id *",
    "variation_id *",
    "SKU *",
    "tên",
    "giá niêm yết",
    "giá vốn *",
    "đóng gói",
    "giảm tối đa (%)",
    "tồn kho",
    "ngày nhập lại",
    "nhóm",
    "trạng thái",
    "số món / phân loại",
    "VAT (%)",
]


def _cost_file(rows: list[list[object]], *, preface: int = 0) -> dict[str, list[list[str | None]]]:
    data = xlsx_io.write_workbook(
        [
            xlsx_io.SheetSpec(
                "Sheet1",
                [*[[f"ghi chú {i}"] for i in range(preface)], COST_HEADER, *rows],
                freeze_header=False,
            )
        ]
    )
    return xlsx_io.read_workbook(data)


def _template(rows: list[list[object]]) -> list[list[str | None]]:
    data = xlsx_io.write_workbook([xlsx_io.SheetSpec("SKU", [TEMPLATE_HEADER, *rows])])
    return xlsx_io.read_workbook(data)["SKU"]


def _cost_row(code, cost, on_hand, name="CANARY-ten-noi-bo", price=99_999):
    return [code, name, "Hộp", price, cost, 50, on_hand, "20x10x5"]


def _t(item, variation, sku, name, price=100_000, **cells):
    row: list[object] = [item, variation, sku, name, price] + [None] * 9
    for column, value in cells.items():
        row[TEMPLATE_HEADER.index(column)] = value
    return row


# ------------------------------------------------------------------ reading the cost file


def test_the_cost_file_is_read_by_header_after_any_title_lines():
    costs = convert.read_cost_file(
        _cost_file([_cost_row("G500001", "30.000", 120), _cost_row("N1", "12.5", "7")], preface=2)
    )
    assert set(costs.rows) == {"g500001", "n1"}
    assert costs.rows["g500001"].cost == Decimal(30_000) and costs.rows["g500001"].on_hand == 120
    assert costs.rows["n1"].cost == Decimal("12.5") and costs.rows["n1"].on_hand == 7


@pytest.mark.parametrize("cost", [None, "", "0", "abc", "-5"])
def test_a_blank_zero_or_unreadable_cost_is_not_a_cost(cost):
    costs = convert.read_cost_file(_cost_file([_cost_row("A1", cost, 5)]))
    assert costs.rows["a1"].cost is None and costs.without_cost == 1


def test_a_repeated_code_keeps_the_last_row_and_is_counted():
    costs = convert.read_cost_file(
        _cost_file([_cost_row("A1", 10, 1), _cost_row(" a1 ", 20, 2), _cost_row("", 5, 5)])
    )
    assert len(costs.rows) == 1 and costs.duplicates == 1
    assert costs.rows["a1"].cost == Decimal(20) and costs.rows["a1"].on_hand == 2


def test_on_hand_must_be_a_whole_number_of_at_least_zero():
    costs = convert.read_cost_file(
        _cost_file([_cost_row("A", 10, "1,5"), _cost_row("B", 10, -3), _cost_row("C", 10, None)])
    )
    assert [costs.rows[k].on_hand for k in ("a", "b", "c")] == [None, None, None]


def test_a_file_without_the_header_is_refused():
    with pytest.raises(ValueError, match="Mã nội bộ"):
        convert.read_cost_file({"S": [["a", "b"], ["1", "2"]]})
    with pytest.raises(ValueError, match="Giá vốn"):
        convert.read_cost_file({"S": [["Mã nội bộ", "Tên"], ["1", "2"]]})


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("12.500", 12500),
        ("12,5", Decimal("12.5")),
        ("1.234,5", Decimal("1234.5")),
        ("1,234.5", Decimal("1234.5")),
        ("12500đ", 12500),
        ("1,234,567", 1234567),
        (" 7 ", 7),
        ("1E3", 1000),
    ],
)
def test_numbers_are_read_the_way_a_vietnamese_sheet_writes_them(text, value):
    assert convert.number(text) == Decimal(value)


@pytest.mark.parametrize("text", [None, "", "abc", "NaN", "1.2.3a"])
def test_other_cells_are_not_numbers(text):
    assert convert.number(text) is None


# ----------------------------------------------------------------------- the conversion


def _convert(template_rows, cost_rows):
    return convert.convert(_template(template_rows), convert.read_cost_file(_cost_file(cost_rows)))


def test_cost_and_stock_are_filled_for_matching_skus_only():
    result = _convert(
        [_t("10", "", "G1", "Găng"), _t("11", "", "N1", "Nước"), _t("12", "", "X9", "Lạ")],
        [_cost_row("g1 ", 30_000, 120), _cost_row("N1", 12_000, 8), _cost_row("Z0", 1, 1)],
    )
    cost, stock = TEMPLATE_HEADER.index("giá vốn *"), TEMPLATE_HEADER.index("tồn kho")
    rows = {r[2]: r for r in result.rows[1:]}
    assert (rows["G1"][cost], rows["G1"][stock]) == ("30000", "120")
    assert (rows["N1"][cost], rows["N1"][stock]) == ("12000", "8")
    assert rows["X9"][cost] is None and rows["X9"][stock] is None  # untouched
    assert (result.template_rows, result.matched, result.costs_filled, result.stock_filled) == (
        3,
        2,
        2,
        2,
    )
    assert result.unmatched_codes == ["Z0"]


def test_combo_variations_that_share_a_sku_get_the_same_cost_a_pack_and_a_share_of_the_stock():
    result = _convert(
        [
            _t("500", "5003", "G500001", "Giấy ăn · Combo 3 hộp"),
            _t("500", "5010", "G500001", "Giấy ăn · Combo 10 hộp"),
            _t("500", "5001", "G500001", "Giấy ăn · Hộp lẻ"),
        ],
        [_cost_row("G500001", 20_000, 100)],
    )
    cost, stock, pack = (
        TEMPLATE_HEADER.index(h) for h in ("giá vốn *", "tồn kho", "số món / phân loại")
    )
    by_variation = {r[1]: r for r in result.rows[1:]}
    assert [by_variation[v][cost] for v in ("5003", "5010", "5001")] == ["20000"] * 3
    assert [by_variation[v][pack] for v in ("5003", "5010", "5001")] == ["3", "10", None]
    assert [by_variation[v][stock] for v in ("5003", "5010", "5001")] == ["33", "10", "100"]
    assert result.packs_filled == 2 and result.unmatched_codes == []


def test_a_pack_the_seller_already_typed_is_left_alone():
    result = _convert(
        [_t("500", "5003", "G500001", "Giấy ăn · Combo 3 hộp", **{"số món / phân loại": "4"})],
        [_cost_row("G500001", 20_000, 100)],
    )
    pack = TEMPLATE_HEADER.index("số món / phân loại")
    assert result.rows[1][pack] == "4" and result.packs_filled == 0


def test_a_row_without_a_usable_cost_keeps_what_the_template_had_but_takes_the_stock():
    result = _convert(
        [_t("10", "", "G1", "Găng", **{"giá vốn *": "9000"})], [_cost_row("G1", "", 15)]
    )
    cost, stock = TEMPLATE_HEADER.index("giá vốn *"), TEMPLATE_HEADER.index("tồn kho")
    assert (result.rows[1][cost], result.rows[1][stock]) == ("9000", "15")
    assert result.costs_filled == 0 and result.stock_filled == 1 and result.without_cost == 1


def test_the_template_is_not_modified_and_note_lines_are_not_rows():
    template = _template([_t("10", "", "G1", "Găng"), ["Chú thích chỉ ở ô đầu"]])
    before = [list(r) for r in template]
    result = convert.convert(template, convert.read_cost_file(_cost_file([_cost_row("G1", 5, 5)])))
    assert template == before
    assert result.template_rows == 1 and result.rows[2] == ["Chú thích chỉ ở ô đầu"] + [None] * 13


def test_a_template_without_the_needed_columns_is_refused():
    with pytest.raises(ValueError, match="SKU"):
        convert.convert([["a", "b"]], convert.CostFile())
    with pytest.raises(ValueError, match="empty"):
        convert.convert([], convert.CostFile())


# ------------------------------------------------------------ the written file and the CLI


def test_the_written_file_goes_through_the_normal_import(tmp_path):
    """The output is read by the same importer a seller's upload goes through."""
    result = _convert(
        [_t("10", "", "G1", "Găng"), _t("11", "", "N1", "Nước", 60_000)],
        [_cost_row("G1", 30_000, 12)],
    )
    out = tmp_path / "out.xlsx"
    convert.write_template(result, out)
    sheets = xlsx_io.read_workbook(out.read_bytes())
    assert list(sheets) == ["SKU"]
    rows = sheets["SKU"]
    assert [h.rstrip(" *") for h in rows[0]][:6] == [
        "item_id",
        "variation_id",
        "SKU",
        "tên",
        "giá niêm yết",
        "giá vốn",
    ]
    assert rows[1][5] == "30000" and rows[1][8] == "12"


def test_the_output_never_lands_inside_the_repository(tmp_path):
    inside = convert.REPO_ROOT / "tests" / "out.xlsx"
    with pytest.raises(SystemExit, match="outside the repo"):
        convert.output_path(inside, tmp_path / "Tồn kho.xlsx")
    with pytest.raises(SystemExit):
        convert.output_path(convert.REPO_ROOT, tmp_path / "x.xlsx")
    default = convert.output_path(None, tmp_path / "Tồn kho và giá.xlsx")
    assert default.suffix == ".xlsx" and default.parent == Path(tempfile.gettempdir()).resolve()
    assert convert.REPO_ROOT not in default.parents
    assert (
        convert.output_path(tmp_path / "ok.xlsx", tmp_path / "x.xlsx")
        == (tmp_path / "ok.xlsx").resolve()
    )


def test_the_cli_prints_counts_lists_unmatched_codes_and_writes_outside_the_repo(tmp_path, capsys):
    cost_path = tmp_path / "cost.xlsx"
    cost_path.write_bytes(
        xlsx_io.write_workbook(
            [
                xlsx_io.SheetSpec(
                    "S", [COST_HEADER, _cost_row("G1", 30_000, 12), _cost_row("ZZ-9", 5, 5)]
                )
            ]
        )
    )
    template_path = tmp_path / "template.xlsx"
    template_path.write_bytes(
        xlsx_io.write_workbook(
            [xlsx_io.SheetSpec("SKU", [TEMPLATE_HEADER, _t("10", "", "G1", "Găng")])]
        )
    )
    out = tmp_path / "filled.xlsx"
    code = convert.main([str(cost_path), "--template", str(template_path), "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 0 and out.exists()
    assert "template rows matched        1" in text and "ZZ-9" in text
    assert "CANARY" not in text  # nothing of the seller's names is echoed
    again = convert.main(
        [str(cost_path), "--template", str(template_path), "--out", str(out), "--no-list-codes"]
    )
    assert again == 0 and "ZZ-9" not in capsys.readouterr().out


def test_the_cli_reports_an_unreadable_file_without_a_traceback(tmp_path, capsys):
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"not a workbook")
    assert convert.main([str(bad), "--template", str(bad)]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_the_converter_never_touches_a_database():
    source = open(convert.__file__, encoding="utf-8").read()
    for word in ("sqlalchemy", "create_engine", "AsyncSession", "psycopg", "asyncpg"):
        assert word not in source
