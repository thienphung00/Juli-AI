"""P100 exports: the two workbook builders put the source values in the right cells and the
formulas point at the right ranges (synthetic numbers only)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from juli_backend.services.exports import ke_hoach_xlsx as kh
from juli_backend.services.exports import tong_quan_xlsx as tq
from juli_backend.services.exports.collect import _residual
from juli_backend.services.shopee_recommendations import month_plan

START = date(2026, 10, 12)


def _fig(scale: float, **plan) -> tq.Figures:
    ch = {
        "organic": tq.Channel(1000 * scale, 100 * scale, 10 * scale, 3_000_000 * scale),
        "ads": tq.Channel(500 * scale, 50 * scale, 6 * scale, 2_000_000 * scale, 400_000 * scale),
        "affiliate": tq.Channel(None, 20 * scale, 2 * scale, 500_000 * scale, 50_000 * scale),
    }
    return tq.Figures(
        ch, gmv=5_500_000 * scale, orders=18 * scale, profit=900_000 * scale,
        ads_cost=400_000 * scale, aff_cost=50_000 * scale, offer_cost=30_000 * scale, **plan,
    )  # fmt: skip


def _data() -> tq.TongQuanData:
    now = _fig(
        1, baseline_gmv=5_000_000, goal_gmv=5_600_000, baseline_profit=800_000, goal_profit=850_000
    )
    days = []
    for i in range(30):  # 30 equal days: the sums equal the period's channel figures
        days.append(
            tq.DayRow(
                START + timedelta(days=i),
                {"organic": 100_000.0, "ads": 2_000_000 / 30, "affiliate": 500_000 / 30},
                {"organic": 1 / 3, "ads": 0.2, "affiliate": 1 / 15},
                400_000 / 30,
                50_000 / 30,
                1_000.0,
                30_000.0,
                5_000_000 / 30,
                5_100_000 / 30,
                800_000 / 30,
                810_000 / 30,
            )  # fmt: skip
        )
    p1 = tq.ProductRow("111", "Sản phẩm A", _fig(0.4, baseline_gmv=1.0, goal_gmv=2.0), _fig(0.3))
    p2 = tq.ProductRow("222", "Sản phẩm B", _fig(0.35), _fig(0.3))
    rest = tq.ProductRow(
        tq.SHOP_ROW_LABEL,
        "",
        _residual(now, [p1.now, p2.now]),
        _residual(_fig(0.9), [p1.prev, p2.prev]),
    )
    return tq.TongQuanData(
        "Dữ liệu mẫu", START, START + timedelta(days=29), START - timedelta(days=30),
        START - timedelta(days=1), now, _fig(0.9), days, [p1, p2, rest],
    )  # fmt: skip


def test_overview_cells_and_formulas():
    wb = tq.build(_data())
    ws = wb[tq.SHEET_OVERVIEW]
    assert ws["A1"].value == (
        "TỔNG QUAN — Dữ liệu mẫu (Shopee) · 12/10/2026–10/11/2026 · so với 12/09/2026–11/10/2026"
    )
    assert [c.value for c in ws[3]][:5] == ["Chỉ số", "Kỳ này", "Thay đổi", "Mục tiêu", "% đạt"]
    assert ws.max_column == 5 and ws["A8"].value == "Chi phí quảng cáo (Báo cáo DVHT) (đ)"
    assert ws["B4"].value == 5_500_000
    assert ws["B6"].value == '=IFERROR(B4/B5,"")'
    assert ws["B11"].value == "=SUM(B8:B10)"
    assert ws["B12"].value == '=IFERROR(B7/B11,"")' and ws["B12"].number_format == "0.0"
    assert ws["C4"].value == '=IFERROR(B4/4950000.0-1,"")' and ws["C4"].number_format == "0.0%"
    assert (ws["D4"].value, ws["E4"].value) == (5_600_000, '=IFERROR(B4/D4,"")')
    assert ws["D7"].value == 850_000 and ws["E7"].value == '=IFERROR(B7/D7,"")'
    assert wb.calculation.fullCalcOnLoad is True
    assert ws["A4"].font.name == "Arial" and ws["A3"].font.bold


def test_channel_sheet_rows_columns_and_totals():
    ws = tq.build(_data())[tq.SHEET_CHANNEL]
    assert [c.value for c in ws[3]] == tq.CH_HEADER
    assert [ws.cell(r, 1).value for r in range(4, 9)] == [
        "Organic", "Quảng cáo (Lưu lượng / Báo cáo DVHT)", "Tiếp thị liên kết", "Ưu đãi", "Tổng",
    ]  # fmt: skip
    assert ws["G7"].value == 30_000 and all(ws.cell(7, c).value is None for c in (2, 3, 5, 6, 8))
    assert ws["B5"].value == 2_000_000 and ws["G5"].value == 400_000 and ws["E6"].value == 2
    assert ws["C4"].value == '=IFERROR(B4/B$8,"")' and ws["F4"].value == '=IFERROR(B4/E4,"")'
    assert ws["B8"].value == "=SUM(B4:B7)" and ws["G8"].value == "=SUM(G4:G7)"
    assert ws["D5"].value == '=IFERROR(B5/1800000.0-1,"")'  # the previous value is in the formula
    assert ws["D8"].value == '=IFERROR(B8/4950000.0-1,"")'
    assert ws["H8"].value == "='Tổng quan'!B12" and ws["H4"].value is None


def test_day_totals_equal_the_channel_sheet():
    wb = tq.build(_data())
    days, ch = wb[tq.SHEET_DAY], wb[tq.SHEET_CHANNEL]
    first, last, total = tq.DAY_FIRST, tq.DAY_FIRST + 29, tq.DAY_FIRST + 30
    assert [c.value for c in days[3]] == tq.DAY_HEADER
    assert days.cell(total, 1).value == "Tổng"
    for letter in "BCDEFGHIJ":
        assert days[f"{letter}{total}"].value == f"=SUM({letter}{first}:{letter}{last})"
    assert days["E4"].value == "=SUM(B4:D4)"
    gmv = [sum(days.cell(r, c).value for r in range(first, last + 1)) for c in (2, 3, 4)]
    assert gmv == [pytest.approx(ch.cell(r, 2).value) for r in (4, 5, 6)]
    orders = sum(days.cell(r, 6).value for r in range(first, last + 1))
    assert orders == pytest.approx(18)
    cost = sum(days.cell(r, 7).value for r in range(first, last + 1))
    assert cost == pytest.approx(450_000 + 30_000)  # quảng cáo + TTLK + ưu đãi
    assert sum(days.cell(r, 9).value for r in range(first, last + 1)) == pytest.approx(5_100_000)


def test_product_sheet_total_equals_the_shop():
    d = _data()
    ws = tq.build(d)[tq.SHEET_PRODUCT]
    assert [c.value for c in ws[3]][:13] == tq.P_HEADER
    total = tq.P_FIRST + 3
    assert ws.cell(tq.P_FIRST + 2, 1).value == "Cả shop" and ws.cell(total, 1).value == "Tổng"
    for letter in "NOPQGEH":
        assert ws[f"{letter}{total}"].value == f"=SUM({letter}{tq.P_FIRST}:{letter}{total - 1})"
    assert ws["N4"].value == d.products[0].now.channel("organic").gmv
    assert sum(ws.cell(r, 15).value for r in range(4, total)) == pytest.approx(
        d.now.channel("ads").gmv
    )
    assert ws["C4"].value == "=SUM(N4:P4)" and ws["J4"].value == '=IFERROR(N4/C4,"")'
    assert ws["M4"].value == '=IFERROR(G4/Q4,"")' and ws["E4"].value == 2.0
    assert ws["D4"].value.startswith("=IFERROR(C4/") and ws["F4"].value == '=IFERROR(C4/E4,"")'
    assert all(ws.column_dimensions[x].hidden for x in "NOPQ")


def test_residual_row_is_shop_minus_products_and_keeps_none():
    shop = _fig(1)
    parts = [_fig(0.4), _fig(0.35)]
    rest = _residual(shop, parts)
    assert rest.gmv == pytest.approx(5_500_000 * 0.25)
    assert rest.channel("affiliate").views is None
    assert rest.channel("ads").cost == pytest.approx(400_000 * 0.25)


# ---------------------------------------------------------------------------------- Kế hoạch


def _card(code, status, plan, start, end, gmv, profit, **kw) -> kh.CardRow:
    return kh.CardRow(
        code, plan, status, "Ưu đãi", "Voucher", "V1", "111", "Sản phẩm A", "AOV", start, end,
        cost=1000.0, gmv_mid=gmv, profit_mid=profit, **kw,
    )  # fmt: skip


def _kh_data() -> kh.KeHoachData:
    cards = [
        _card(
            "A", kh.RUNNING, "KH-1", date(2026, 11, 5), date(2026, 11, 18), 1_400_000.0, 140_000.0
        ),
        _card(
            "B", kh.RUNNING, "KH-1", date(2026, 11, 25), date(2026, 12, 4), 1_000_000.0, -50_000.0
        ),
        _card("C", kh.DRAFT, "KH-2", date(2026, 11, 20), date(2026, 11, 24), 500_000.0, 25_000.0),
        _card(
            "D",
            kh.MEASURED,
            None,
            date(2026, 11, 1),
            date(2026, 11, 7),
            777.0,
            7.0,
            result="+1 đ · Trong khoảng",
        ),
    ]
    first = date(2026, 11, 1)
    return kh.KeHoachData(
        "Dữ liệu mẫu", first, date(2026, 11, 10), 57_000_000.0, 9_900_000.0,
        {first + timedelta(days=i): 1_900_000.0 for i in range(10)},
        {first + timedelta(days=i): 330_000.0 for i in range(10)}, cards,
    )  # fmt: skip


def _card_dict(c: kh.CardRow) -> dict:
    return {
        "result": {"own": {
            "dates": {"from": c.start.isoformat(), "to": c.end.isoformat()},
            "days": (c.end - c.start).days + 1,
            "delta": {"p50": {"dgmv": c.gmv_mid, "dprofit": c.profit_mid}},
        }}
    }  # fmt: skip


def test_month_sums_equal_month_plans_goals_for_both_scopes():
    d = _kh_data()
    first, last = d.month_first, date(2026, 11, 30)
    rows = kh.daily_targets(d)
    assert len(rows) == 30
    for scope, cards in (("run", [c for c in d.cards if c.plan_code and c.status != kh.DRAFT]),
                         ("draft", d.cards[:3])):  # fmt: skip
        up_g, up_p, _ = month_plan.uplift_in_month([_card_dict(c) for c in cards], first, last)
        goal_g = sum(r["goal_gmv" if scope == "run" else "goal_gmv_draft"] for r in rows)
        goal_p = sum(r["goal_profit" if scope == "run" else "goal_profit_draft"] for r in rows)
        assert goal_g == pytest.approx(d.baseline_gmv + up_g)
        assert goal_p == pytest.approx(d.baseline_profit + up_p)


def test_card_sheet_values_formulas_and_totals():
    ws = kh.build(_kh_data())[kh.SHEET_CARDS]
    assert [c.value for c in ws[3]][:14] == kh.CARD_HEADER
    assert ws["B4"].value == "A" and ws["C6"].value == "Nháp" and ws["O7"].value is None
    assert ws["K4"].value == 1_400_000 and ws["J4"].value == 1000
    assert ws["M4"].value == '=IFERROR(L4/J4,"")' and ws["M4"].number_format == "0.0"
    assert ws["K8"].value == "=SUM(K4:K7)" and ws["J8"].value == "=SUM(J4:J7)"
    assert ws["H4"].number_format == "dd/mm/yyyy" and ws.column_dimensions["O"].hidden


def test_goal_sheet_formulas_reference_the_card_ranges():
    d = _kh_data()
    ws = kh.build(d)[kh.SHEET_GOAL]
    f = kh.DAY_HEADER_FIRST + 1
    assert ws.cell(f, 1).value == date(2026, 11, 1) and ws.cell(f + 29, 1).value == date(
        2026, 11, 30
    )
    assert ws.cell(f, 10).value == pytest.approx(57_000_000 / 30)  # hidden: GMV nền
    run = ws.cell(f, 11).value
    assert "SUMPRODUCT(" in run and "'Đề xuất'!$H$4:$H$7<=$A18" in run
    assert "'Đề xuất'!$K$4:$K$7/('Đề xuất'!$I$4:$I$7-'Đề xuất'!$H$4:$H$7+1)" in run
    assert '<>"Nháp"' in run and "'Đề xuất'!$O$4:$O$7" in run
    assert '="Nháp"' in ws.cell(f, 12).value and "'Đề xuất'!$L$4:$L$7" in ws.cell(f, 14).value
    assert ws.cell(f, 2).value == f"=J{f}+K{f}"  # GMV mục tiêu of the day
    assert ws.cell(f, 4).value == f"=SUM(B${f}:B{f})"
    assert ws.cell(f + 1, 5).value == f'=IF(C{f + 1}="","",SUM(C${f}:C{f + 1}))'
    assert ws.cell(f, 3).value == 1_900_000 and ws.cell(f + 15, 3).value is None
    assert [ws.cell(3 + i, 1).value for i in range(5)][0] == "GMV nền"
    assert ws["B3"].value == f"=SUM(J{f}:J{f + 29})" and ws["B4"].value == f"=SUM(B{f}:B{f + 29})"
    assert ws["B5"].value == f"=B4+SUM(L{f}:L{f + 29})"
    assert ws["A6"].value == "GMV thực tế đến 10/11/2026"
    assert f"MATCH(DATE(2026,11,10),$A{f}:$A{f + 29},0)" in ws["B7"].value
    assert "INDEX(D" in ws["B7"].value and "INDEX(H" in ws["B14"].value
    assert [c.value for c in ws[kh.DAY_HEADER_FIRST]][:9] == [
        "Ngày", "GMV mục tiêu", "GMV thực tế", "Lũy kế mục tiêu", "Lũy kế thực tế",
        "Lợi nhuận mục tiêu", "Lợi nhuận thực tế", "Lũy kế mục tiêu", "Lũy kế thực tế",
    ]  # fmt: skip


def test_split_goal_sends_a_scoped_cards_uplift_only_to_its_skus():
    from juli_backend.services.exports import sku as skumod

    a, b, c = ("p", "A", "1"), ("p", "B", "2"), ("p", "C", "3")
    base = {a: 50.0, b: 30.0, c: 20.0}
    cards = [
        {"uplift_gmv": 100.0, "sku_ids": None},
        {"uplift_gmv": 80.0, "sku_ids": ["B", "C"]},
    ]
    out = skumod.split_goal([a, b, c], base, 1000.0, cards, "uplift_gmv")
    assert out is not None
    assert sum(out.values()) == pytest.approx(1000 + 100 + 80)
    assert out[a] == pytest.approx(500 + 50)
    assert out[b] == pytest.approx(300 + 30 + 80 * 0.6)
    assert out[c] == pytest.approx(200 + 20 + 80 * 0.4)
    assert skumod.split_goal([a], {a: None}, 10.0, [], "uplift_gmv") is None  # unknown profit


def test_sku_sheet_columns_and_formulas():
    data = _data()
    data.skus = [
        tq.SkuRow("S1", "Đỏ", "SP", 10, 8, 1000, 900, 100, 90, 5, 6),
        tq.SkuRow("S2", None, "SP", None, 3, None, 300, None, None, 2, None),
    ]
    ws = tq.build(data)[tq.SHEET_SKU]
    assert [c.value for c in ws[3]] == tq.SKU_HEADER and len(tq.SKU_HEADER) == 16
    assert ws["P4"].value == '=IF(O4="","",MAX(0,O4-N4))' and ws["D6"].value == "=SUM(D4:D5)"
    assert ws["A6"].value == "Tổng"


def test_result_text_is_the_actual_and_the_verdict_of_the_measurement_row():
    from juli_backend.services.exports.collect import _result_text
    from juli_backend.services.shopee_recommendations import execution_state as es

    assert _result_text({"actual": 320000, "verdict": es.VERDICT_INSIDE}) == (
        "+320.000 đ · Trong khoảng"
    )
    assert (
        _result_text({"actual": -1500.4, "verdict": es.VERDICT_BELOW}) == "-1.500 đ · Dưới khoảng"
    )
    assert _result_text({"actual": None, "verdict": es.VERDICT_RUNNING}) == "Đang đo"
    assert _result_text({"actual": None, "verdict": es.VERDICT_NONE}) is None
