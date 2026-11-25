"""The xlsx exports carry each formula's computed result beside the formula (batch-1125-b X1-X5).

openpyxl writes ``<f>`` with an empty ``<v>``, so Protected View, phones and previews showed 0.
Expected values here are worked out by hand, not by the evaluator. Synthetic numbers only."""

from __future__ import annotations

import io
import logging
import re
import time
import zipfile
from datetime import date

import pytest
from openpyxl import Workbook, load_workbook

from juli_backend.services.exports import _cached_values as cv
from juli_backend.services.exports import ke_hoach_xlsx as kh
from juli_backend.services.exports import report_sheets as rs
from juli_backend.services.exports import tong_quan_xlsx as tq
from juli_backend.services.exports._style import save_bytes
from tests.unit.test_export_report_sheets import SECTION
from tests.unit.test_p100_exports import _data, _kh_data

DASH = "—"


def _eval(cells: dict[str, object], other: dict[str, object] | None = None) -> dict[str, object]:
    """Evaluate ``cells`` (A1 -> value or formula) on sheet 'Dữ liệu' (+ an optional 2nd sheet)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Dữ liệu"
    for k, v in cells.items():
        ws[k] = v
    if other:
        w2 = wb.create_sheet("Sheet 2")
        for k, v in other.items():
            w2[k] = v
    out = cv.evaluate_workbook(wb)
    assert out.failed == {}
    return {c: v for (s, c), v in out.values.items() if s == "Dữ liệu"}


# ---------------------------------------------------------------- X2: each function, by hand


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("=A1+A2*2", 40.0),
        ("=A1-A2", -5.0),
        ("=(A1+A2)/5", 5.0),
        ("=-A1+1", -9.0),
        ("=50%", 0.5),
        ("=A1/A2*100%", 2 / 3),
        ("=A1^2", 100.0),
        ("=SUM(A1:A2)", 25.0),
        ("=SUM(A1:A4)", 25.0),  # text and empty cells in a range are ignored
        ("=SUM(A1,A2,5)", 30.0),
        ("=SUM(B1:B2)", 0.0),  # nothing to add
        ("=MAX(A1:A2)", 15.0),
        ("=MAX(0,A1*2-30)", 0.0),
        ("=MAX(B1:B2)", 0.0),
        ("=MIN(A1:A2)", 10.0),
        ("=ABS(A1-A2)", 5.0),
        ("=N(A1)", 10.0),
        ("=N(A3)", 0.0),  # text
        ("=N(B1)", 0.0),  # empty
        ("=ISNUMBER(A1)", True),
        ("=ISNUMBER(A3)", False),
        ("=ISNUMBER(B1)", False),
        ("=ISNUMBER(A1/0)", False),
        ("=AND(A1>5,A2>5)", True),
        ("=AND(A1>5,A2>50)", False),
        ("=OR(A1>50,A2>5)", True),
        ("=OR(A1>50,A2>50)", False),
        ("=AND(ISNUMBER(A1),ISNUMBER(A3))", False),
        ('=IF(A1>5,"big","small")', "big"),
        ('=IF(A1>50,"big","small")', "small"),
        ("=IF(A1>50,1)", False),
        ('=IF(AND(ISNUMBER(A1),ISNUMBER(A2)),A1/A2-1,"—")', 10 / 15 - 1),
        ('=IF(AND(ISNUMBER(A1),ISNUMBER(A3)),A1/A3-1,"—")', DASH),
        ('=IFERROR(A1/B1,"—")', DASH),  # division by an empty cell
        ('=IFERROR(A1/0,"")', ""),
        ('=IFERROR(A1/A2,"—")', 10 / 15),
        ('=IFERROR(A1/A3,"—")', DASH),  # text in arithmetic is #VALUE!
        ('=IFERROR(A1/1800000.0-1,"—")', 10 / 1800000.0 - 1),
        ('=IF(OR(B1="",A1=""),"",A1-B1)', ""),  # an empty ref equals ""
        ('=IF(OR(A1="",A2=""),"",A2-A1)', 5.0),
        ('=IF(AND(A1<>"",A2<>0),A1/A2,"")', 10 / 15),
        ('=IFERROR((A2-N(B1))/(A1+N(B1)),"")', 1.5),
        ("=B1", 0.0),  # a formula that points at an empty cell shows 0, as Excel does
        ("=A3", "text"),
        ('=A3&"!"&A1', "text!10"),
        ("=A1=10", True),
        ('=A3="TEXT"', True),  # text comparison ignores case
        ("=A3>A1", True),  # text sorts after numbers
        ("='Sheet 2'!B1+1", 8.0),
        ("=SUM('Sheet 2'!B1:B2)", 12.0),
        ("=$A$1+A$2+$A2", 40.0),
        ("=A1/0", cv.DIV0),
        ("=A3+1", cv.VALUE),
        ("=SUM(A1:A2)/(A1-10)", cv.DIV0),
        ('=IFERROR(1/0,"x")&"y"', "xy"),
        ("=D1+5", 12.0),  # D1 is itself a formula; its date input counts as a serial
        ("=D2-D3+1", 31.0),
    ],
)
def test_each_function_gives_the_number_excel_gives(formula, expected):
    cells = {
        "A1": 10, "A2": 15, "A3": "text", "C1": formula,
        "D1": "=A1-3",
        "D2": date(2026, 10, 31), "D3": date(2026, 10, 1),
    }  # fmt: skip
    got = _eval(cells, {"B1": 7, "B2": 5})["C1"]
    if isinstance(expected, float):
        assert got == pytest.approx(expected)
    else:
        assert got == expected
    assert type(got) is type(expected)


def test_precedents_run_first_and_a_long_running_total_is_fast_without_recursion():
    got = _eval({"A1": "=SUM(A2:A3)", "A2": "=A3*2", "A3": 4, "B1": "=A1+A2"})
    assert (got["A1"], got["A2"], got["B1"]) == (12.0, 8.0, 20.0)  # a range of formulas
    cells: dict[str, object] = {"B1": 1}
    for r in range(2, 3001):
        cells[f"B{r}"] = f"=B{r - 1}+SUM(A{r}:A{r})"
        cells[f"A{r}"] = 2
    t0 = time.perf_counter()
    got = _eval(cells)
    assert got["B3000"] == 1 + 2 * 2999
    assert time.perf_counter() - t0 < 5


# ---------------------------------------------------------------- X3: what it cannot compute


def _wb_with_bad_formulas() -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "S"
    ws["A1"] = 4
    ws["B1"] = "=A1*2"
    ws["B2"] = "=VLOOKUP(A1,A1:A2,1,0)"  # not supported
    ws["B3"] = "=B2+1"  # depends on the unsupported one
    ws["B4"] = "=IFERROR(B2,0)"  # an error handler must not turn it into a number
    ws["C1"] = "=C2+1"
    ws["C2"] = "=C1+1"  # circular
    return wb


def test_a_formula_the_evaluator_cannot_compute_fails_strict_mode():
    wb = _wb_with_bad_formulas()
    with pytest.raises(cv.UnsupportedFormula) as exc:
        save_bytes(wb, strict=True)
    assert "VLOOKUP" in str(exc.value) and "circular" in str(exc.value)
    out = cv.evaluate_workbook(wb)
    assert set(out.failed) == {("S", c) for c in ("B2", "B3", "B4", "C1", "C2")}
    assert out.values == {("S", "B1"): 8.0}


def test_in_production_it_is_logged_the_file_still_opens_and_the_cell_has_no_value(
    caplog, monkeypatch
):
    wb = _wb_with_bad_formulas()
    with caplog.at_level(logging.WARNING, logger=cv.logger.name):
        data = save_bytes(wb)
    assert "no cached value" in caplog.text and "VLOOKUP" in caplog.text
    assert zipfile.ZipFile(io.BytesIO(data)).testzip() is None
    cached = load_workbook(io.BytesIO(data), data_only=True)["S"]
    assert cached["B1"].value == 8  # computed
    assert [cached[c].value for c in ("B2", "B3", "B4", "C1", "C2")] == [None] * 5  # never a 0
    formulas = load_workbook(io.BytesIO(data))["S"]
    assert formulas["B2"].value == "=VLOOKUP(A1,A1:A2,1,0)"

    def boom(_wb):
        raise RuntimeError("boom")

    monkeypatch.setattr(cv, "evaluate_workbook", boom)  # a crash must not break the download
    with caplog.at_level(logging.ERROR, logger=cv.logger.name):
        data = save_bytes(_wb_with_bad_formulas())
    assert "cached values skipped" in caplog.text
    assert load_workbook(io.BytesIO(data))["S"]["B1"].value == "=A1*2"


# ---------------------------------------------------------------- X1/X2/X4/X5: the real exports


def _full_tong_quan() -> Workbook:
    d = _data()
    d.skus = [
        tq.SkuRow("S1", "Đỏ", "SP", 8, 900, 90, stock=30, rate=2.0, days_left=15),
        tq.SkuRow("S2", None, "SP", 3, 300, None),
    ]
    d.koc = rs.koc_rows(SECTION)
    d.affiliate_share = rs.AffiliateShare(500_000, 5_500_000, 300_000, 4_950_000)
    d.months = []
    return tq.build(d)


def _workbooks() -> dict[str, Workbook]:
    return {
        "tong_quan": _full_tong_quan(),
        "tong_quan_many_shops": tq.build_multi([_data(), _data()]),
        "ke_hoach": kh.build(_kh_data()),
        "ke_hoach_two_shops": kh.build(_kh_data(("Shop A", "Shop B"))),
    }


@pytest.mark.parametrize(
    "name", ["tong_quan", "tong_quan_many_shops", "ke_hoach", "ke_hoach_two_shops"]
)
def test_every_formula_cell_carries_its_result_and_the_formulas_are_unchanged(name):
    wb = _workbooks()[name]
    before = {
        (ws.title, c.coordinate): c.value
        for ws in wb.worksheets
        for row in ws.iter_rows()
        for c in row
        if c.data_type == "f"
    }
    assert before
    blank = {k for k, v in cv.evaluate_workbook(wb).values.items() if v == ""}
    data = save_bytes(wb, strict=True)  # strict: every formula was evaluated
    assert zipfile.ZipFile(io.BytesIO(data)).testzip() is None

    formulas = load_workbook(io.BytesIO(data))
    cached = load_workbook(io.BytesIO(data), data_only=True)
    assert formulas.calculation.fullCalcOnLoad is True
    for (sheet, coord), text in before.items():
        assert formulas[sheet][coord].value == text  # X1: formula unchanged
        if (sheet, coord) not in blank:  # a "" result reads back as None, see the XML below
            assert cached[sheet][coord].value is not None, (sheet, coord)  # X1: has a value
    zf = zipfile.ZipFile(io.BytesIO(data))
    xml = "".join(zf.read(n).decode() for n in zf.namelist() if n.startswith("xl/worksheets/"))
    assert "<v />" not in xml  # no formula cell is left without a result
    assert len(re.findall(r't="str"><f>[^<]*</f><v></v></c>', xml)) == len(blank)


def test_the_tong_quan_cached_numbers_equal_a_hand_sum_of_the_cells_they_add():
    data = save_bytes(_full_tong_quan(), strict=True)
    ws = load_workbook(io.BytesIO(data), data_only=True)
    ch = ws[tq.SHEET_CHANNEL]
    gmv = [ch.cell(r, 2).value for r in (4, 5, 6)]
    assert ch["B8"].value == pytest.approx(sum(gmv))  # =SUM(B4:B6)
    assert ch["C4"].value == pytest.approx(gmv[0] / sum(gmv))
    days = ws[tq.SHEET_DAY]
    first, last, total = tq.DAY_FIRST, tq.DAY_FIRST + 29, tq.DAY_FIRST + 30
    for letter in "BCD":
        col = days[f"{letter}{first}" : f"{letter}{last}"]
        assert days[f"{letter}{total}"].value == pytest.approx(sum(r[0].value for r in col))
    assert days["E4"].value == pytest.approx(sum(days.cell(4, c).value for c in (2, 3, 4)))
    sku = ws[tq.SHEET_SKU]
    assert sku["D7"].value == 11 and sku["F7"].value == 90  # Σ units; profit ignores the "—"
    assert sku["G4"].value == pytest.approx(90 / 900)
    ov = ws[tq.SHEET_OVERVIEW]
    assert ov["B4"].value == 5_500_000  # GMV is a value, not a formula
    assert ov["C4"].value == 1.0  # =IF(...B4/B$4...) -> 100 % of revenue
    assert ov["E4"].value == pytest.approx(5_500_000 / 4_950_000 - 1)
    assert ov["F4"].value == DASH  # no goal: the text result keeps its dash, never a 0
    assert ov["G4"].value == DASH


def test_text_results_are_stored_as_text_cells_and_numbers_as_plain_numbers():
    data = save_bytes(_full_tong_quan(), strict=True)
    z = zipfile.ZipFile(io.BytesIO(data))
    xml = z.read("xl/worksheets/sheet1.xml").decode()
    assert re.search(r'<c r="E4"[^>]*><f>[^<]*</f><v>[-0-9.e]+</v></c>', xml)  # number: no t=
    assert re.search(rf'<c r="[A-Z]+[0-9]+"[^>]* t="str"><f>[^<]*</f><v>{DASH}</v></c>', xml)


def test_errors_and_booleans_use_the_right_cell_types():
    wb = Workbook()
    ws = wb.active
    ws["A1"] = 0
    ws["B1"] = "=1/A1"
    ws["B2"] = "=A1=0"
    ws["B3"] = '=IFERROR(B1,"a&b")'
    data = save_bytes(wb, strict=True)
    xml = zipfile.ZipFile(io.BytesIO(data)).read("xl/worksheets/sheet1.xml").decode()
    assert re.search(r'<c r="B1"[^>]* t="e"><f>1/A1</f><v>#DIV/0!</v>', xml)
    assert re.search(r'<c r="B2"[^>]* t="b"><f>A1=0</f><v>1</v>', xml)
    assert "<v>a&amp;b</v>" in xml
    cached = load_workbook(io.BytesIO(data), data_only=True).active
    assert (cached["B1"].value, cached["B2"].value, cached["B3"].value) == ("#DIV/0!", True, "a&b")

    plain_wb = Workbook()  # no formulas: the file parts survive the rewrite
    plain_wb.active["A1"] = "plain"
    raw = io.BytesIO()
    plain_wb.save(raw)
    out = save_bytes(plain_wb, strict=True)
    assert sorted(zipfile.ZipFile(io.BytesIO(out)).namelist()) == sorted(
        zipfile.ZipFile(io.BytesIO(raw.getvalue())).namelist()
    )


def test_the_export_builders_return_bytes_that_already_carry_the_values():
    cached = load_workbook(io.BytesIO(tq.build_bytes(_data())), data_only=True)
    assert cached[tq.SHEET_CHANNEL]["B8"].value is not None
    kcached = load_workbook(io.BytesIO(kh.build_bytes(_kh_data())), data_only=True)
    plain = load_workbook(io.BytesIO(kh.build_bytes(_kh_data())))
    formula_cells = [
        (ws.title, c.coordinate) for ws in plain.worksheets for r in ws.iter_rows() for c in r
        if c.data_type == "f"
    ]  # fmt: skip
    assert formula_cells
    blank = {k for k, v in cv.evaluate_workbook(kh.build(_kh_data())).values.items() if v == ""}
    assert all(kcached[s][c].value is not None for s, c in formula_cells if (s, c) not in blank)
