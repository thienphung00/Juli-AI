"""P100 exports: the two workbook builders put the source values in the right cells and the
formulas point at the right ranges (synthetic numbers only)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from juli_backend.services.exports import ke_hoach_xlsx as kh
from juli_backend.services.exports import tong_quan_xlsx as tq
from juli_backend.services.exports.collect import _residual

START = date(2026, 10, 12)


def _fig(scale: float) -> tq.Figures:
    ch = {
        "organic": tq.Channel(1000 * scale, 100 * scale, 10 * scale, 3_000_000 * scale),
        "ads": tq.Channel(500 * scale, 50 * scale, 6 * scale, 2_000_000 * scale, 400_000 * scale),
        "affiliate": tq.Channel(None, 20 * scale, 2 * scale, 500_000 * scale, 50_000 * scale),
    }
    return tq.Figures(
        ch, gmv=5_500_000 * scale, orders=18 * scale, profit=900_000 * scale,
        ads_cost=400_000 * scale, aff_cost=50_000 * scale, offer_cost=30_000 * scale,
    )  # fmt: skip


def _data() -> tq.TongQuanData:
    now = _fig(1)
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
            )  # fmt: skip
        )
    p1 = tq.ProductRow("111", "Sản phẩm A", _fig(0.4), _fig(0.3))
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
    assert [c.value for c in ws[3]][:3] == ["Chỉ số", "Kỳ này", "Thay đổi"]
    assert ws.max_column == 3 and ws["A8"].value == "Chi phí quảng cáo (Báo cáo DVHT) (đ)"
    assert ws["B4"].value == 5_500_000
    assert ws["B6"].value == '=IFERROR(B4/B5,"")'
    assert ws["B11"].value == "=SUM(B8:B10)"
    assert ws["B12"].value == '=IFERROR(B7/B11,"")' and ws["B12"].number_format == "0.0"
    assert ws["C4"].value == '=IFERROR(B4/4950000.0-1,"")' and ws["C4"].number_format == "0.0%"
    assert tq.OVERVIEW_HEADER == ["Chỉ số", "Kỳ này", "Thay đổi"]  # no Kế hoạch goal (G21)
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
    for letter in "BCDEFGH":
        assert days[f"{letter}{total}"].value == f"=SUM({letter}{first}:{letter}{last})"
    assert days["E4"].value == "=SUM(B4:D4)"
    gmv = [sum(days.cell(r, c).value for r in range(first, last + 1)) for c in (2, 3, 4)]
    assert gmv == [pytest.approx(ch.cell(r, 2).value) for r in (4, 5, 6)]
    orders = sum(days.cell(r, 6).value for r in range(first, last + 1))
    assert orders == pytest.approx(18)
    cost = sum(days.cell(r, 7).value for r in range(first, last + 1))
    assert cost == pytest.approx(450_000 + 30_000)  # quảng cáo + TTLK + ưu đãi
    assert days.max_column == 8 and "mục tiêu" not in " ".join(tq.DAY_HEADER)


def test_product_sheet_total_equals_the_shop():
    d = _data()
    ws = tq.build(d)[tq.SHEET_PRODUCT]
    assert [c.value for c in ws[3]][:9] == tq.P_HEADER
    total = tq.P_FIRST + 3
    assert ws.cell(tq.P_FIRST + 2, 1).value == "Cả shop" and ws.cell(total, 1).value == "Tổng"
    for letter in "JKLME":
        assert ws[f"{letter}{total}"].value == f"=SUM({letter}{tq.P_FIRST}:{letter}{total - 1})"
    assert ws["J4"].value == d.products[0].now.channel("organic").gmv
    assert sum(ws.cell(r, 11).value for r in range(4, total)) == pytest.approx(
        d.now.channel("ads").gmv
    )
    # GMV = the product's own order GMV (not Σ its channels: their reports can disagree)
    assert ws["C4"].value == d.products[0].now.gmv and ws["F4"].value == '=IFERROR(J4/C4,"")'
    assert ws[f"C{total}"].value == f"=SUM(C{tq.P_FIRST}:C{total - 1})"
    assert ws["I4"].value == '=IFERROR(E4/M4,"")' and "mục tiêu" not in " ".join(tq.P_HEADER)
    assert ws["D4"].value.startswith("=IFERROR(C4/")
    assert all(ws.column_dimensions[x].hidden for x in "JKLM")


def test_residual_row_is_shop_minus_products_and_keeps_none():
    shop = _fig(1)
    parts = [_fig(0.4), _fig(0.35)]
    rest = _residual(shop, parts)
    assert rest.gmv == pytest.approx(5_500_000 * 0.25)
    assert rest.channel("affiliate").views is None
    assert rest.channel("ads").cost == pytest.approx(400_000 * 0.25)


# ---------------------------------------------------------------------------------- Kế hoạch


def _card(code, status, start, end, gmv, profit, **kw) -> kh.CardRow:
    base = dict(
        code=code, plan_code="KH-1", status=status, group="Ưu đãi", kind="Voucher", version="V1",
        product_id="111", product_name="Sản phẩm A", metrics="AOV", start=start, end=end,
        kind_key="min_spend_voucher", family="voucher", shop="Shop A", cost=1000.0,
        gmv_mid=gmv, profit_mid=profit, orders_mid=3.0,
    )  # fmt: skip
    return kh.CardRow(**{**base, **kw})


def _kh_data(shops=("Shop A",)) -> kh.KeHoachData:
    cards = [
        _card("A", kh.RUNNING, date(2026, 11, 5), date(2026, 11, 18), 1_400_000.0, 140_000.0,
              actual_profit=100_000.0, conclusion="Trong khoảng"),
        _card("C", kh.DRAFT, date(2026, 11, 20), date(2026, 11, 24), 500_000.0, 25_000.0),
        _card("K", kh.MEASURED, date(2026, 11, 1), date(2026, 11, 7), 7.0, 7.0,
              kind_key="ads_budget", family="ads", plan_code=None),
    ]  # fmt: skip
    goals = [kh.GoalRow(s, "Shopee", 100.0, 120.0, 90.0, 10.0, 12.0, 9.0) for s in shops]
    return kh.KeHoachData(
        date(2026, 11, 1), date(2026, 11, 30), list(shops), cards, goals,
        [kh.GoalDay("Shop A", date(2026, 11, 1), 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)],
        [kh.KolRow("Shop A", "Shopee", "kol_a", 10.0, 2.0, 500.0, 50.0, 90.0, 1)],
    )  # fmt: skip


def test_workbook_has_the_history_goal_kind_and_kol_sheets_and_no_draft_sheet():
    names = kh.build(_kh_data()).sheetnames
    assert names == [kh.SHEET_HISTORY, kh.SHEET_GOAL, "Voucher", "Quảng cáo", kh.SHEET_KOL]
    assert "Kế hoạch nháp" not in names


def test_history_row_has_status_dates_core_rows_and_a_difference_formula():
    ws = kh.build(_kh_data())[kh.SHEET_HISTORY]
    head = [c.value for c in ws[3]]
    assert head[:5] == ["STT", "Mã thẻ", "Shop", "Nền tảng", "Trạng thái"]
    assert "Δ lợi nhuận dự kiến" in head and "Δ lợi nhuận chênh lệch" in head
    assert head[-1] == "Kết luận" and not any("khoảng" in str(h).lower() for h in head)
    assert [ws.cell(r, 5).value for r in (4, 5, 6)] == ["Đang chạy", "Trong nháp", "Đã đo"]
    assert ws["M4"].value == '=IF(OR(K4="",L4=""),"",L4-K4+1)' and ws["K4"].value == date(
        2026, 11, 5
    )
    assert ws["N4"].value == 140_000 and ws["O4"].value == 100_000  # Dự kiến, Thực tế
    assert ws["P4"].value == '=IF(OR(N4="",O4=""),"",O4-N4)'
    assert ws["O5"].value is None  # unread real value stays empty, never 0
    assert ws.cell(4, 26).value == "Trong khoảng"


def test_goal_sheet_gives_a_business_total_only_when_every_shop_has_a_target():
    ws = kh.build(_kh_data(("Shop A", "Shop B")))[kh.SHEET_GOAL]
    assert [ws.cell(r, 1).value for r in (4, 5, 6)] == ["Shop A", "Shop B", "Tổng"]
    assert ws["D6"].value == 240.0 and ws["C6"].value == 200.0
    data = _kh_data(("Shop A", "Shop B"))
    data.goals[1].goal_gmv = None
    ws = kh.build(data)[kh.SHEET_GOAL]
    assert ws["D6"].value is None and ws["C6"].value == 200.0
    assert kh.business_total([], "goal_gmv") is None


def test_a_card_is_in_the_range_when_proposed_ran_or_was_measured_on_any_day_of_it():
    c = _card("A", kh.RUNNING, date(2026, 11, 10), date(2026, 11, 20), 1.0, 1.0,
              proposed=date(2026, 11, 8), measure_end=date(2026, 11, 25))  # fmt: skip
    assert kh.active_in(c, date(2026, 11, 1), date(2026, 11, 8))  # only proposed
    assert kh.active_in(c, date(2026, 11, 22), date(2026, 11, 30))  # only measured
    assert kh.active_in(c, date(2026, 11, 12), date(2026, 11, 13))  # running
    assert not kh.active_in(c, date(2026, 11, 26), date(2026, 12, 5))
    assert not kh.active_in(c, date(2026, 10, 1), date(2026, 11, 7))
    open_card = _card("B", kh.MEASURING, date(2026, 11, 1), None, 1.0, 1.0, measure_end=None)
    assert kh.active_in(open_card, date(2026, 12, 1), date(2026, 12, 3))


def test_kind_sheets_carry_their_tailored_rows_and_the_kol_sheet_one_row_per_kol():
    wb = kh.build(_kh_data())
    ads = [c.value for c in wb["Quảng cáo"][3]]
    assert "CPA hoà vốn dự kiến" in ads and "Lượt nhấp thực tế" in ads
    assert "Lượt dùng dự kiến" in [c.value for c in wb["Voucher"][3]]
    kol = wb[kh.SHEET_KOL]
    assert kol["C4"].value == "kol_a" and kol["I4"].value == '=IFERROR(H4/G4,"")'
    assert kol["A5"].value is None


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
        tq.SkuRow("S1", "Đỏ", "SP", 8, 900, 90, 5),
        tq.SkuRow("S2", None, "SP", 3, 300, None, 2),
    ]
    data.skus.append(tq.SkuRow("G500001", "Combo 10 hộp", "SP", units=2, revenue=500, combo=10))
    ws = tq.build(data)[tq.SHEET_SKU]
    assert [c.value for c in ws[3]] == tq.SKU_HEADER and len(tq.SKU_HEADER) == 9
    assert ws["G4"].value == '=IF(AND(F4<>"",E4<>0),F4/E4,"")' and ws["I6"].value == 10
    # the GMV gap row brings Σ Doanh thu thực tế to the overview's GMV, then the Tổng row
    assert ws["A7"].value == tq.SKU_GAP_LABEL
    assert ws["E7"].value == f"='{tq.SHEET_OVERVIEW}'!B{tq.OV['gmv']}-SUM(E4:E6)"
    assert ws["A8"].value == "Tổng" and ws["E8"].value == "=SUM(E4:E7)"
    assert ws["D8"].value == "=SUM(D4:D7)"


def test_split_sku_takes_the_combo_factor_off_the_code():
    from juli_backend.services.exports.collect import split_sku

    assert split_sku("G500001×10") == ("G500001", 10.0)
    assert split_sku("G700010") == ("G700010", None)
    assert split_sku("Không có SKU") == ("Không có SKU", None)
    assert split_sku("A×b") == ("A×b", None)


def test_day_sheet_takes_the_days_own_gmv_and_orders():
    """ORY Oct export: from 05/10 a day had no traffic-source rows, so GMV = Σ channels counted
    affiliate only (5,96 tr of 21,68 tr). The day's stored order totals now fill GMV / Đơn."""
    data = _data()
    d0 = data.days[0]
    data.days = [
        tq.DayRow(d0.day, {k: None for k in tq.CHANNELS}, {k: None for k in tq.CHANNELS},
                  total_gmv=1_200_000.0, total_orders=7.0),
        tq.DayRow(d0.day, {"organic": 100.0, "ads": 50.0, "affiliate": 25.0},
                  {"organic": 1.0, "ads": 1.0, "affiliate": 1.0}),
    ]  # fmt: skip
    ws = tq.build(data)[tq.SHEET_DAY]
    r = tq.DAY_FIRST
    assert ws.cell(r, 5).value == 1_200_000.0 and ws.cell(r, 6).value == 7.0
    assert ws.cell(r, 2).value is None and ws.cell(r, 4).value is None
    assert ws.cell(r + 1, 5).value == f"=SUM(B{r + 1}:D{r + 1})" and ws.cell(r + 1, 6).value == 3.0


def test_residual_channel_past_the_shop_is_unknown_not_negative():
    shop = _fig(1)
    parts = [_fig(0.8), _fig(0.6)]  # the products' reports add up past the shop
    rest = _residual(shop, parts)
    assert rest.channel("organic").gmv is None and rest.channel("ads").gmv is None
    assert rest.gmv == pytest.approx(5_500_000 * -0.4)  # the GMV residual itself is kept


# ---------------------------------------------------------------------------------- Tất cả shop


def test_all_shops_overview_has_a_column_per_shop_and_a_total_from_the_registry_flags():
    a, b = _data(), _data()
    b.shop_name, b.platform = "Shop B", "TikTok"
    b.now = _fig(2)
    ws = tq.build_multi([a, b])[tq.SHEET_OVERVIEW]
    assert [c.value for c in ws[3]] == [
        "Chỉ số", "Dữ liệu mẫu (Shopee)", "Shop B (TikTok)", "Tổng",
    ]  # fmt: skip
    r = tq.OV
    # summable metrics (registry flag): the SUM of the shops
    for key in ("gmv", "orders", "profit", "ads", "aff", "offer", "cost"):
        assert ws.cell(r[key], 4).value == f"=SUM(B{r[key]}:C{r[key]})", key
    # ratios: recomputed from the Tổng parts, never summed or averaged
    assert ws.cell(r["aov"], 4).value == f'=IFERROR(D{r["gmv"]}/D{r["orders"]},"")'
    assert ws.cell(r["roi"], 4).value == f'=IFERROR(D{r["profit"]}/D{r["cost"]},"")'
    assert ws.cell(r["aov"], 3).value == f'=IFERROR(C{r["gmv"]}/C{r["orders"]},"")'
    assert ws.cell(r["gmv"], 2).value == 5_500_000 and ws.cell(r["gmv"], 3).value == 11_000_000
    assert tq.summable_row("gmv") and not tq.summable_row("aov") and not tq.summable_row("roi")
    assert tq.file_name_multi([a, b]).startswith("Juli_TongQuan_TatCaShop_")
