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
    assert [c.value for c in ws[3]][:4] == ["Chỉ số", "Kỳ này", "Kỳ trước", "Thay đổi"]
    assert ws["B4"].value == 5_500_000 and ws["C4"].value == pytest.approx(4_950_000)
    assert ws["B6"].value == '=IFERROR(B4/B5,"")'
    assert ws["B11"].value == "=SUM(B8:B10)"
    assert ws["B12"].value == '=IFERROR(B7/B11,"")' and ws["B12"].number_format == "0.0"
    assert ws["D4"].value == '=IFERROR(B4/C4-1,"")' and ws["D4"].number_format == "0.0%"
    assert (ws["E4"].value, ws["F4"].value, ws["G4"].value) == (5_000_000, 5_600_000, "=B4")
    assert ws["H4"].value == '=IFERROR(G4/F4,"")'
    assert ws["F7"].value == 850_000 and ws["H7"].value == '=IFERROR(G7/F7,"")'
    assert wb.calculation.fullCalcOnLoad is True
    assert ws["A4"].font.name == "Arial" and ws["A3"].font.bold


def test_channel_sheet_rows_columns_and_totals():
    ws = tq.build(_data())[tq.SHEET_CHANNEL]
    assert [ws.cell(r, 1).value for r in range(5, 9)] == [
        "Organic",
        "Quảng cáo",
        "Tiếp thị liên kết",
        "Tổng",
    ]
    assert ws["B5"].value == 1000 and ws["G6"].value == 2_000_000 and ws["J6"].value == 400_000
    assert ws["B7"].value is None  # TTLK has no views
    assert ws["D5"].value == '=IFERROR(C5/B5,"")' and ws["F5"].value == '=IFERROR(E5/C5,"")'
    assert ws["H5"].value == '=IFERROR(G5/E5,"")' and ws["I5"].value == '=IFERROR(G5/G$8,"")'
    assert ws["G8"].value == "=SUM(G5:G7)" and ws["J8"].value == "=SUM(J5:J7)"
    assert ws["P6"].value == pytest.approx(1_800_000)  # Kỳ trước GMV, block K..S
    assert ws["T5"].value == '=IFERROR(G5/P5-1,"")' and ws["U5"].value == '=IFERROR(E5/N5-1,"")'


def test_day_totals_equal_the_channel_sheet():
    wb = tq.build(_data())
    days, ch = wb[tq.SHEET_DAY], wb[tq.SHEET_CHANNEL]
    first, last, total = tq.DAY_FIRST, tq.DAY_FIRST + 29, tq.DAY_FIRST + 30
    assert days.cell(total, 1).value == "Tổng"
    for letter in "BCDFGHJKLMNOPQ":
        assert days[f"{letter}{total}"].value == f"=SUM({letter}{first}:{letter}{last})"
    assert days["E4"].value == "=SUM(B4:D4)" and days["I4"].value == "=SUM(F4:H4)"
    gmv = [sum(days.cell(r, c).value for r in range(first, last + 1)) for c in (2, 3, 4)]
    orders = [sum(days.cell(r, c).value for r in range(first, last + 1)) for c in (6, 7, 8)]
    assert gmv == [pytest.approx(ch.cell(r, 7).value) for r in (5, 6, 7)]
    assert orders == [pytest.approx(ch.cell(r, 5).value) for r in (5, 6, 7)]
    assert sum(days.cell(r, 10).value for r in range(first, last + 1)) == pytest.approx(
        ch["J6"].value
    )
    assert sum(days.cell(r, 15).value for r in range(first, last + 1)) == pytest.approx(5_100_000)


def test_product_sheet_total_equals_the_shop_and_targets_have_a_place():
    d = _data()
    ws = tq.build(d)[tq.SHEET_PRODUCT]
    total = tq.P_FIRST + 3
    assert ws.cell(tq.P_FIRST + 2, 1).value == "Cả shop" and ws.cell(total, 1).value == "Tổng"
    g = tq.col(tq.P_NOW + tq.PB["g_ads"])
    assert ws[f"{g}{total}"].value == f"=SUM({g}{tq.P_FIRST}:{g}{total - 1})"
    for key in ("g_org", "g_ads", "g_aff", "views", "clicks", "profit", "c_ads", "c_offer"):
        c = tq.P_NOW + tq.PB[key]
        vals = [ws.cell(r, c).value for r in range(tq.P_FIRST, total)]
        shop = {
            "g_org": d.now.channel("organic").gmv, "g_ads": d.now.channel("ads").gmv,
            "g_aff": d.now.channel("affiliate").gmv, "profit": d.now.profit,
            "c_ads": d.now.ads_cost, "c_offer": d.now.offer_cost,
        }  # fmt: skip
        if key in shop:
            assert sum(v for v in vals if v is not None) == pytest.approx(shop[key])
    assert (
        ws.cell(tq.P_FIRST, tq.P_PLAN).value == 1.0
        and ws.cell(tq.P_FIRST, tq.P_PLAN + 1).value == 2.0
    )
    assert ws.cell(total, tq.P_PLAN + 2).value.startswith("=IFERROR(")


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
        cost=1000.0, gmv_low=gmv * 0.5, gmv_mid=gmv, gmv_high=gmv * 2, profit_low=profit * 0.5,
        profit_mid=profit, profit_high=profit * 2, orders=3.0, **kw,
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
            actual_profit=1.0,
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
    assert [c.value for c in ws[3]][:4] == ["STT", "Mã thẻ", "Mã kế hoạch", "Trạng thái"]
    assert ws["B4"].value == "A" and ws["D6"].value == "Nháp" and ws["C7"].value is None
    assert ws["P4"].value == 1_400_000 and ws["O4"].value == 700_000 and ws["Q4"].value == 2_800_000
    assert ws["M4"].value == '=IF(AND(K4<>"",L4<>""),L4-K4+1,"")'
    assert ws["V4"].value == "=IFERROR(P4/M4,0)" and ws["W4"].value == "=IFERROR(S4/M4,0)"
    assert ws["X4"].value == '=IFERROR(S4/N4,"")' and ws["X4"].number_format == "0.0"
    assert 'IF(Y4="","",IF(Y4<R4' in ws["Z4"].value
    assert ws["P8"].value == "=SUM(P4:P7)" and ws["N8"].value == "=SUM(N4:N7)"
    assert ws["K4"].number_format == "dd/mm/yyyy"


def test_goal_sheet_formulas_reference_the_card_ranges():
    d = _kh_data()
    ws = kh.build(d)[kh.SHEET_GOAL]
    f = kh.DAY_HEADER_FIRST + 1
    assert ws.cell(f, 1).value == date(2026, 11, 1) and ws.cell(f + 29, 1).value == date(
        2026, 11, 30
    )
    assert ws.cell(f, 2).value == pytest.approx(57_000_000 / 30)
    run = ws.cell(f, 3).value
    assert (
        "SUMPRODUCT(" in run and "'Đề xuất'!$K$4:$K$7<=$A22" in run and "'Đề xuất'!$V$4:$V$7" in run
    )
    assert '<>"Nháp"' in run and "'Đề xuất'!$C$4:$C$7" in run
    assert '="Nháp"' in ws.cell(f, 4).value and "'Đề xuất'!$W$4:$W$7" in ws.cell(f, 12).value
    assert ws.cell(f, 5).value == f"=B{f}+C{f}" and ws.cell(f, 6).value == f"=B{f}+C{f}+D{f}"
    assert ws.cell(f, 7).value == 1_900_000 and ws.cell(f + 15, 7).value is None
    assert ws.cell(f + 1, 8).value == f"=SUM(E${f}:E{f + 1})"
    assert (
        ws["A8"].value == "GMV thực tế đến 10/11/2026" and ws["B3"].value == f"=SUM(B{f}:B{f + 29})"
    )
    assert ws["B5"].value == "=B3+B4" and ws["B7"].value == "=B5+B6"
    assert f"MATCH(DATE(2026,11,10),$A{f}:$A{f + 29},0)" in ws["B9"].value
    assert "INDEX(H" in ws["B9"].value and "INDEX(P" in ws["B17"].value
