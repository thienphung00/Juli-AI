"""W4 fast-track: Tổng quan export gaps (synthetic numbers only)."""

from __future__ import annotations

import pytest

from juli_backend.services.exports import report_sheets as rs
from juli_backend.services.exports import tong_quan_xlsx as tq
from juli_backend.services.exports.collect import _goal_rows_for_products
from juli_backend.services.exports.report_sheets import koc_effective_count
from juli_backend.services.shopee_recommendations import kinds
from tests.unit.test_export_report_sheets import SECTION, _Card
from tests.unit.test_p100_exports import _data

DASH = "—"


# ------------------------------------------------------------------------------ A1


def test_vs_muc_tieu_is_dash_without_a_ke_hoach_goal():
    ws = tq.build(_data())[tq.SHEET_OVERVIEW]
    assert ws["F4"].value == DASH and ws["G4"].value == DASH
    assert ws["F7"].value == DASH and ws["G7"].value == DASH


def test_vs_muc_tieu_compares_when_collector_has_goals():
    d = _data()
    d.goal_gmv, d.goal_profit = 6_000_000.0, 900_000.0
    ws = tq.build(d)[tq.SHEET_OVERVIEW]
    assert ws["F4"].value == 6_000_000.0
    assert ws["G4"].value.startswith("=IF(AND(ISNUMBER(B4),ISNUMBER(F4))")
    assert ws["G7"].value.startswith("=IF(AND(ISNUMBER(B7),ISNUMBER(F7))")


# ------------------------------------------------------------------------------ A2


def test_channel_and_day_show_ads_gmv_when_attribution_exists():
    d = _data()
    ads = 2_000_000.0
    d.now.channels["ads"] = tq.Channel(gmv=ads, orders=50, cost=400_000)
    d.days[0] = tq.DayRow(
        d.days[0].day,
        {"organic": 800_000.0, "ads": ads / 30, "affiliate": 500_000 / 30},
        {"organic": 1.0, "ads": 1.0, "affiliate": 1.0},
    )
    wb = tq.build(d)
    assert wb[tq.SHEET_CHANNEL]["B5"].value == ads
    assert wb[tq.SHEET_DAY]["C4"].value == pytest.approx(ads / 30)


def test_channel_and_day_stay_dash_when_ads_gmv_unknown():
    d = _data()
    d.now.channels["ads"] = tq.Channel(gmv=None, cost=400_000)
    d.days[0] = tq.DayRow(
        d.days[0].day,
        {k: None for k in tq.CHANNELS},
        {k: None for k in tq.CHANNELS},
        total_gmv=1_000_000.0,
        total_orders=5.0,
    )
    wb = tq.build(d)
    assert wb[tq.SHEET_CHANNEL]["B5"].value == DASH
    assert wb[tq.SHEET_DAY]["C4"].value == DASH


# ------------------------------------------------------------------------------ A3


def test_koc_sheet_counts_effective_kocs_and_shows_roi():
    d = _data()
    d.koc = rs.koc_rows(SECTION)
    for row in d.koc:
        if row.handle == "koc_a":
            row.sample_cost = 20_000.0
    ws = tq.build(d)[rs.SHEET_KOC]
    assert "Chi phí mẫu (đ)" in [c.value for c in ws[3]]
    assert "ROI KOL" in [c.value for c in ws[3]]
    assert koc_effective_count(d.koc) == 2
    by_label = {ws.cell(r, 1).value: r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value}
    assert ws.cell(by_label["Số KOC có đơn"], 2).value == 2
    roi_col = [c.value for c in ws[3]].index("ROI KOL") + 1
    assert ws.cell(4, roi_col).value.startswith("=IF(")


def test_koc_prev_columns_fill_when_previous_figures_exist():
    rows = rs.koc_rows(SECTION)
    assert rows[0].prev_gmv == 200.0 and rows[0].prev_profit == 40.0


# ------------------------------------------------------------------------------ A4


def _eight_issues():
    items = []
    for i in range(8):
        items.append(
            {
                "id": f"issue-{i}",
                "kpi": "ctr" if i % 2 == 0 else "ctor",
                "level": "product",
                "product_id": f"p{i}",
                "name": f"Sản phẩm {i}",
                "current": 0.01,
                "reference": {"value": 0.02},
                "deviation_pct": -50.0,
                "at_stake_per_day": 1000 + i,
                "cause": {"text": f"Nguyên nhân {i}"},
                "change_kinds": ["cover_image", "title"] if i % 2 == 0 else ["product_discount"],
            }
        )
    return items


def test_analysis_one_row_per_issue_lists_all_cards():
    cards = [
        _Card(f"JC-{i}-{j}", k, f"p{i}", 10.0 * j, 20.0 * j)
        for i in range(8)
        for j, k in enumerate(["cover_image", "title", "product_discount"], start=1)
        if (i % 2 == 0 and k in ("cover_image", "title"))
        or (i % 2 == 1 and k == "product_discount")
    ]
    rows = rs.analysis_rows(_eight_issues(), cards)
    assert len(rows) == 8
    by_target = {r.target: r for r in rows}
    even = by_target["Sản phẩm 0"]
    assert even.card_code == "JC-0-1, JC-0-2"
    assert "Loại cover_image" in even.card_kind
    assert even.expected_profit is None and even.expected_gmv is None


def test_analysis_du_kien_delta_stays_dash_without_numbers():
    rows = rs.analysis_rows(
        _eight_issues()[:1],
        [_Card("JC-1", "cover_image", "p0", None, None)],
    )
    ws = tq.build(_data())
    ws.parent = None
    d = _data()
    d.analysis = rows
    sheet = tq.build(d)[rs.SHEET_ANALYSIS]
    assert sheet["K4"].value == DASH and sheet["L4"].value == DASH


# ------------------------------------------------------------------------------ A5


def test_product_sheet_shows_cause_and_fix_only_from_inputs():
    d = _data()
    p = d.products[0]
    p.cause = "Khách thấy sản phẩm nhưng ít bấm vào."
    p.fix = ", ".join(kinds.KINDS[k].label for k in ("cover_image", "title"))
    ws = tq.build(d)[tq.SHEET_PRODUCT]
    assert ws.cell(3, tq.P_ISSUE_COL).value == "Nguyên nhân"
    assert ws.cell(3, tq.P_ISSUE_COL + 1).value == "Đề xuất"
    assert ws.cell(4, tq.P_ISSUE_COL).value == p.cause
    assert ws.cell(4, tq.P_ISSUE_COL + 1).value == p.fix

    p.cause = DASH
    p.fix = DASH
    ws = tq.build(d)[tq.SHEET_PRODUCT]
    assert ws.cell(4, tq.P_ISSUE_COL).value == DASH
    assert ws.cell(4, tq.P_ISSUE_COL + 1).value == DASH


def test_product_fix_labels_from_critical_change_kinds():
    item = {
        "id": "product:111:gmv:previous",
        "product_id": "111",
        "at_stake_per_day": 5000,
        "cause": {"text": "Doanh số giảm."},
        "change_kinds": ["cover_image", "title"],
    }
    cause, fix = _goal_rows_for_products([item])["111"]
    assert cause == "Doanh số giảm."
    assert fix == f"{kinds.KINDS['cover_image'].label}, {kinds.KINDS['title'].label}"


# ------------------------------------------------------------------------------ A6


def test_lo2_columns_are_absent_from_export_headers():
    wb = tq.build(_data())
    headers = [
        str(c.value)
        for ws in wb.worksheets
        for row in ws.iter_rows(min_row=3, max_row=3)
        for c in row
        if isinstance(c.value, str)
    ]
    joined = " ".join(headers)
    assert "Nguồn dự đoán" not in joined
    assert "ROAS Tùy chỉnh" not in joined
    assert "Chi phí dự kiến" not in joined
