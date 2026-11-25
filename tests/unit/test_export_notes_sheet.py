"""The Tổng quan export's "Ghi chú" sheet (how each core metric is computed, from the registry) and
the empty-sheet totals (batch-1125-b t4). Synthetic data only; the builders are pure."""

from __future__ import annotations

import re

import pytest

from juli_backend.services.exports import notes_sheet as ns
from juli_backend.services.exports import report_sheets as rs
from juli_backend.services.exports import tong_quan_xlsx as tq
from juli_backend.services.exports._style import save_bytes
from juli_backend.services.metrics.components import COMPONENTS
from juli_backend.services.metrics.registry import METRICS, refs
from tests.unit.test_p100_exports import _data

DASH = "—"


@pytest.mark.parametrize("sheet", [tq.SHEET_SKU, rs.SHEET_KOC])
def test_an_empty_sku_or_koc_sheet_has_a_dash_total_that_never_reads_itself(sheet):
    d = _data()
    d.skus, d.koc = [], []
    wb = tq.build(d)
    ws = wb[sheet]
    total = next(r for r in range(4, 8) if ws.cell(r, 1).value == "Tổng")
    cells = [c for c in ws[total][1:] if c.value is not None]
    assert cells and all(c.value == DASH for c in cells)  # missing is "—", never 0
    assert not any(c.data_type == "f" and c.row == total for c in ws[total])  # no self-sum
    save_bytes(wb, strict=True)  # every formula of the empty sheets evaluates


def test_a_sheet_with_rows_keeps_its_total_formulas():
    d = _data()
    d.skus = [tq.SkuRow("S1", None, "SP", 8, 900, 90)]
    d.koc = rs.koc_rows(
        {
            "rows": [
                {"kol_key": "k", "handle": "a", "channel_label": "Video", "orders": 1, "gmv": 5.0}
            ]
        }
    )
    wb = tq.build(d)
    assert wb[tq.SHEET_SKU]["D6"].value == "=SUM(D4:D5)"  # the gap row is inside
    assert wb[rs.SHEET_KOC]["D5"].value == "=SUM(D4:D4)"


def test_the_notes_sheet_is_the_last_sheet_with_one_row_per_metric_from_the_registry():
    wb = tq.build(_data())
    assert wb.sheetnames[-1] == ns.SHEET_NOTES == "Ghi chú"
    ws = wb[ns.SHEET_NOTES]
    assert [c.value for c in ws[3]] == ["Chỉ số", "Cách tính", "Nguồn số liệu"]
    rows = [tuple(c.value for c in ws[r][:3]) for r in range(4, 4 + len(ns.NOTE_METRICS))]
    assert [r[0] for r in rows] == [METRICS[m].label_vi for m in ns.NOTE_METRICS]
    assert {m for m in ns.NOTE_METRICS} >= {
        "gmv", "orders", "aov", "cost_ads", "cost_affiliate", "cost_offers", "cost_marketing",
        "cost_total", "gross_profit", "contribution", "profit", "margin_gross",
        "margin_contribution", "margin",
    }  # fmt: skip
    tail = [tuple(c.value for c in ws[r][:3]) for r in range(4 + len(rows), ws.max_row + 1)]
    assert tail == [ns.BASE_NOTE, *ns.ASSUMPTIONS]
    assert "roi" not in ns.NOTE_METRICS  # held until its parts share one confirmed basis
    assert not any("File " in r[2] for r in [*rows, *tail])
    by_label = {r[0]: r for r in rows}
    assert by_label["Lợi nhuận ròng"][1].startswith(
        "Lợi nhuận đóng góp − Quảng cáo phần của các đơn đủ chi phí"
    )
    assert by_label["Biên lợi nhuận"][1].startswith(
        "Lợi nhuận ròng ÷ Doanh thu thực của đơn đủ chi phí"
    )
    assert by_label["Chi phí marketing"][1].startswith(
        "Quảng cáo + Hoa hồng tiếp thị liên kết + Ưu đãi"
    )


@pytest.mark.parametrize("metric_id", ns.NOTE_METRICS)
def test_each_note_is_pinned_to_the_registry_components_of_its_metric(metric_id):
    m = METRICS[metric_id]
    cach_tinh, nguon = ns.note_of(metric_id)
    if isinstance(m.formula, str):  # a platform figure: hand-written text, pinned to its component
        assert m.formula == m.components[0] and len(m.components) == 1
        assert metric_id in ns.BASE_TEXT and ns.BASE_TEXT[metric_id] in cach_tinh
    else:  # a derived metric: the text is rendered from the formula, every operand is named
        for ref in refs(m.formula):
            label = METRICS[ref].label_vi if ref in METRICS else ns.COMPONENT_LABELS[ref]
            assert label in cach_tinh, (metric_id, ref)
    assert set(refs(m.formula)) == set(m.components)  # the registry's own component set
    leaves = ns.leaf_components(metric_id)
    assert leaves and set(leaves) <= set(COMPONENTS)
    datasets = {COMPONENTS[c].sources[ns.SHOPEE].dataset for c in leaves}
    assert datasets <= set(ns.DATASET_TEXT)  # a new dataset must get a Vietnamese name
    assert all(ns.DATASET_TEXT[d] in nguon for d in datasets)


def test_the_notes_are_text_only_without_shop_numbers_or_names():
    d = _data()
    wb = tq.build(d)
    cells = [c.value for row in wb[ns.SHEET_NOTES].iter_rows() for c in row if c.value is not None]
    assert cells and all(isinstance(v, str) for v in cells)
    assert not any(re.search(r"\d", v) for v in cells)  # no figures, periods or ids
    assert not any(d.shop_name in v for v in cells)
    assert not any(c.data_type == "f" for row in wb[ns.SHEET_NOTES].iter_rows() for c in row)


def test_the_all_shops_export_gets_the_notes_sheet_once_and_last():
    wb = tq.build_multi([_data(), _data()])
    assert wb.sheetnames == [tq.SHEET_OVERVIEW, ns.SHEET_NOTES]
    assert wb.sheetnames.count(ns.SHEET_NOTES) == 1
    assert wb[ns.SHEET_NOTES]["A4"].value == METRICS["gmv"].label_vi
    save_bytes(wb, strict=True)


def test_unknown_marketing_cost_and_empty_day_product_sheets_show_a_dash():
    d = _data()
    d.days, d.products = [], []
    d.now.ads_cost = d.now.aff_cost = d.now.offer_cost = None
    wb = tq.build(d)
    assert wb[tq.SHEET_OVERVIEW].cell(tq.OV["cost"], 2).value == DASH  # missing is never 0
    assert wb[tq.SHEET_DAY].cell(tq.DAY_FIRST, 2).value == DASH
    assert wb[tq.SHEET_PRODUCT].cell(tq.P_FIRST, 5).value == DASH
    save_bytes(wb, strict=True)  # no total reads its own cell
    multi = tq.build_multi([d, _data()])[tq.SHEET_OVERVIEW]
    assert multi.cell(tq.OV["cost"], 2).value == DASH
    assert str(multi.cell(tq.OV["cost"], 3).value).startswith("=SUM(")
