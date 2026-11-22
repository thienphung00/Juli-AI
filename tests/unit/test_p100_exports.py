"""P100 exports: the two workbook builders put the source values in the right cells and the
formulas point at the right ranges (synthetic numbers only)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from juli_backend.services.exports import ke_hoach_xlsx as kh
from juli_backend.services.exports import tong_quan_xlsx as tq
from juli_backend.services.exports.collect import _residual
from juli_backend.services.metrics.registry import METRICS

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
        net_revenue_known=4_500_000 * scale,
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
    assert [c.value for c in ws[3]][:3] == ["Chỉ số", "Kỳ này", "% doanh thu"]
    assert ws.max_column == 7 and ws["A8"].value == "Chi phí quảng cáo (Báo cáo DVHT) (đ)"
    assert ws["B4"].value == 5_500_000
    assert ws["B6"].value == '=IFERROR(B4/B5,"—")'
    assert ws["B11"].value == "=SUM(B8:B10)"  # QC + TTLK + ưu đãi (registry cost_marketing)
    assert ws["A10"].value == tq.OFFER_LABEL
    assert ws["B12"].value == '=IFERROR(B7/B11,"—")' and ws["B12"].number_format == "0.0"
    assert ws["A12"].value == f"{METRICS['roi'].label_vi} (lần)"
    assert ws["A11"].value == f"{METRICS['cost_marketing'].label_vi} (đ)"
    assert ws["A13"].value == METRICS["margin"].label_vi
    assert ws["B13"].value.endswith('IFERROR(B7/B14,"—"),"—")')  # profit ÷ net_revenue_known
    assert ws["B14"].value == 4_500_000
    assert ws["D4"].value == 4_950_000 and ws["E4"].number_format == "0.0%"
    assert ws["E4"].value.startswith("=IF(AND(ISNUMBER(B4),ISNUMBER(D4)),IFERROR(B4/D4-1")
    assert ws["D3"].value == "Kỳ trước (12/09/2026–11/10/2026)"
    assert wb.calculation.fullCalcOnLoad is True
    assert ws["A4"].font.name == "Arial" and ws["A3"].font.bold


def test_channel_sheet_rows_columns_and_totals():
    ws = tq.build(_data())[tq.SHEET_CHANNEL]
    assert [c.value for c in ws[3]] == tq.CH_HEADER and tq.CH_HEADER[7] == tq.ROI_LABEL
    assert [ws.cell(r, 1).value for r in range(4, 9)] == [
        "Organic",
        "Quảng cáo (Lưu lượng / Báo cáo DVHT)",
        "Tiếp thị liên kết",
        "Ưu đãi của shop (thuộc chi phí marketing)",
        "Tổng",
    ]
    assert ws["G7"].value == 30_000 and all(ws.cell(7, c).value in (None, "—") for c in (2, 5, 8))
    assert ws["B5"].value == 2_000_000 and ws["G5"].value == 400_000 and ws["E6"].value == 2
    assert ws["C4"].value == '=IFERROR(B4/B$8,"—")' and ws["F4"].value == '=IFERROR(B4/E4,"—")'
    assert ws["B8"].value == "=SUM(B4:B6)" and ws["G8"].value == "=SUM(G4:G7)"  # cost incl. ưu đãi
    assert ws["D5"].value == '=IFERROR(B5/1800000.0-1,"—")'  # the previous value is in the formula
    assert ws["D8"].value == '=IFERROR(B8/4950000.0-1,"—")'
    assert ws["H8"].value == "='Tổng quan'!B12" and ws["H4"].value == "—"


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
    assert cost == pytest.approx(480_000)  # quảng cáo + TTLK + ưu đãi (30 x 1_000 / day)
    assert days.max_column == 8 and "mục tiêu" not in " ".join(tq.DAY_HEADER)


def test_product_sheet_total_equals_the_shop():
    d = _data()
    ws = tq.build(d)[tq.SHEET_PRODUCT]
    assert [ws.cell(3, c).value for c in range(1, 14)] == tq.P_HEADER_MAIN
    assert [ws.cell(3, c).value for c in (tq.P_ISSUE_COL, tq.P_ISSUE_COL + 1)] == tq.P_HEADER_ISSUE
    total = tq.P_FIRST + 3
    assert ws.cell(tq.P_FIRST + 2, 1).value == "Cả shop" and ws.cell(total, 1).value == "Tổng"
    for letter in "OPQRE":
        assert ws[f"{letter}{total}"].value == f"=SUM({letter}{tq.P_FIRST}:{letter}{total - 1})"
    assert ws["O4"].value == d.products[0].now.channel("organic").gmv
    assert sum(ws.cell(r, 16).value for r in range(4, total)) == pytest.approx(
        d.now.channel("ads").gmv
    )
    # GMV = the product's own order GMV (not Σ its channels: their reports can disagree)
    assert ws["C4"].value == d.products[0].now.gmv and ws["F4"].value == '=IFERROR(O4/C4,"—")'
    assert ws[f"C{total}"].value == f"=SUM(C{tq.P_FIRST}:C{total - 1})"
    assert ws["I4"].value == '=IFERROR(E4/R4,"—")' and "mục tiêu" not in " ".join(tq.P_HEADER)
    assert ws["D4"].value.startswith("=IFERROR(C4/")
    assert all(ws.column_dimensions[x].hidden for x in "OPQR")


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
              actual_profit=100_000.0, conclusion="Trong khoảng",
              figures={"profit": (1_000_000.0, 1_140_000.0, 1_100_000.0)},
              days_measured=5, days_total=14, measured_with=["VC-P2", "B-7"]),
        _card("C", kh.DRAFT, date(2026, 11, 20), date(2026, 11, 24), 500_000.0, 25_000.0),
        _card("K", kh.MEASURED, date(2026, 11, 1), date(2026, 11, 7), 7.0, 7.0,
              kind_key="ads_budget", family="ads", plan_code=None,
              tailored={"CPA": (20_000.0, 18_000.0), "ROAS": (4.0, 4.5),
                        "CPA hoà vốn": (25_000.0, None), "ROAS hoà vốn": (3.2, None)}),
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
    assert head[:7] == ["STT", "Mã thẻ", "Mã gốc", "Nguồn", "Shop", "Nền tảng", "Trạng thái"]
    assert head[15:19] == [
        "Lợi nhuận hiện tại", "Lợi nhuận dự kiến", "Lợi nhuận thực tế", "Lợi nhuận chênh lệch",
    ]  # fmt: skip
    assert not any(str(h).startswith("Δ") for h in head)  # no Δ-only columns
    assert head[-4:] == ["Chi phí", "Đã đo", "Đo chung với", "Kết luận"]
    assert not any("khoảng" in str(h).lower() for h in head)
    assert [ws.cell(r, 7).value for r in (4, 5, 6)] == ["Đang chạy", "Trong nháp", "Đã đo"]
    assert ws["O4"].value == '=IF(OR(M4="",N4=""),"",N4-M4+1)' and ws["M4"].value == date(
        2026, 11, 5
    )
    assert [ws.cell(4, c).value for c in (16, 17, 18)] == [1_000_000.0, 1_140_000.0, 1_100_000.0]
    assert ws["S4"].value == '=IF(OR(Q4="",R4=""),"",R4-Q4)'  # a formula string, recalculated
    assert ws["R5"].value is None and ws["P5"].value is None  # unknown stays empty, never 0
    assert ws.cell(4, 36).value == "Trong khoảng"


def test_history_has_dao_do_and_do_chung_voi_and_empty_when_unmeasured():
    ws = kh.build(_kh_data())[kh.SHEET_HISTORY]
    assert (ws.cell(4, 34).value, ws.cell(4, 35).value) == ("5/14 ngày", "VC-P2, B-7")
    assert ws.cell(5, 34).value is None and ws.cell(5, 35).value is None


def test_ads_sheet_fills_cpa_and_roas_where_the_reading_has_them_and_never_zero():
    ws = kh.build(_kh_data())["Quảng cáo"]
    head = [c.value for c in ws[3]]
    cpa, be_cpa = head.index("CPA dự kiến") + 1, head.index("CPA hoà vốn dự kiến") + 1
    roas, be_roas = head.index("ROAS dự kiến") + 1, head.index("ROAS hoà vốn dự kiến") + 1
    assert (ws.cell(4, cpa).value, ws.cell(4, cpa + 1).value) == (20_000.0, 18_000.0)
    assert (ws.cell(4, roas).value, ws.cell(4, roas + 1).value) == (4.0, 4.5)
    assert (ws.cell(4, be_cpa).value, ws.cell(4, be_cpa + 1).value) == (25_000.0, None)
    assert (ws.cell(4, be_roas).value, ws.cell(4, be_roas + 1).value) == (3.2, None)
    assert ws.cell(4, head.index("Lượt nhấp dự kiến") + 1).value is None


def test_nguon_and_ma_goc_columns_on_the_history_and_kind_sheets():
    data = _kh_data()
    data.cards[0].source, data.cards[0].external_ref = "Làm ngoài Juli", "VC-P1"
    data.cards[1].source = kh.SOURCE_LABELS["engine"]
    wb = kh.build(data)
    assert kh.SOURCE_LABELS == {
        "engine": "Juli",
        "manual": "Tự tạo",
        "agent": "Từ tab Juli",
        "external": "Làm ngoài Juli",
    }
    for ws in (wb[kh.SHEET_HISTORY], wb["Voucher"]):
        head = [c.value for c in ws[3]]
        assert head[1:4] == ["Mã thẻ", "Mã gốc", "Nguồn"]
    ws = wb[kh.SHEET_HISTORY]
    assert (ws["C4"].value, ws["D4"].value) == ("VC-P1", "Làm ngoài Juli")
    assert ws["D5"].value == "Juli" and ws["C5"].value is None


def test_nguon_labels_a_juli_tab_card_and_never_prints_a_raw_origin():
    assert kh.source_label("agent") == "Từ tab Juli"
    assert kh.source_label(None) == "Juli"
    assert kh.source_label("manual") == "Tự tạo"
    assert kh.source_label("something_new") == "Khác"
    data = _kh_data()
    data.cards[0].source = kh.source_label("agent")
    ws = kh.build(data)[kh.SHEET_HISTORY]
    assert ws["D4"].value == "Từ tab Juli"


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
    # registry roi_kol: (lợi nhuận KOL − chi phí mẫu) ÷ (hoa hồng + chi phí mẫu)
    assert kol["C4"].value == "kol_a" and kol["I3"].value == "Chi phí mẫu"
    assert kol["J4"].value == '=IFERROR((H4-N(I4))/(G4+N(I4)),"")'
    assert kol["I4"].value is None and kol["K4"].value == 1
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
    assert [c.value for c in ws[3]] == tq.SKU_HEADER and len(tq.SKU_HEADER) == 12
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
    assert ws.cell(r, 2).value == "—" and ws.cell(r, 4).value == "—"
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


def test_the_profit_sheet_lists_each_cost_once_and_sums_to_the_profit():
    from juli_backend.services.exports.profit_bridge import ProfitBridge

    b = ProfitBridge(
        gmv=1_000_000, orders=10, lost_gmv=60_000, lost_orders=1, pending_gmv=0, pending_orders=0,
        refund_gmv=40_000, refund_orders=1, refunds_in_gmv=True,
        paid_success=850_000,
        success_orders=9, offers=50_000, payout=600_000, payout_orders=9, known_orders=9,
        known_gmv_share_pct=90.0, revenue=800_000, vat_output=50_000, fees=200_000,
        fees_real_pct=100.0, cogs=300_000, cogs_real_pct=50.0, packaging=0, packaging_real_pct=0.0,
        commission=10_000, shipping_other=5_000, ads=85_000, ads_no_order_days=15_000,
        other_marketing=0, profit=200_000, margin_pct=25.0,
    )  # fmt: skip
    data = _data()
    data.bridge = b
    wb = tq.build(data)
    assert wb.sheetnames[:2] == [tq.SHEET_OVERVIEW, tq.SHEET_PROFIT]
    ws = wb[tq.SHEET_PROFIT]
    rows = {ws.cell(r, 1).value: r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value}
    base = rows["Doanh thu tính lợi nhuận (sau VAT đầu ra)"]
    profit = rows["Lợi nhuận bán hàng trên sàn"]
    assert ws.cell(profit, 2).value == f"=SUM(B{base}:B{profit - 1})"
    # the costs below the revenue are negatives that sum to the profit; no marketing-other row
    values = [ws.cell(r, 2).value for r in range(base, profit)]
    assert sum(values) == 200_000 and "− Chi phí marketing khác" not in rows
    offer = next(k for k in rows if k.startswith("Ưu đãi của shop"))
    # the Tổng quan sheet's ưu đãi figure, so the two sheets never show two numbers
    assert "thuộc chi phí marketing" in offer and ws.cell(rows[offer], 2).value == 30_000
    assert ws.cell(rows["− Đóng gói"], 2).value == 0  # never "-0"
    assert ws.cell(rows["− Đóng gói"], 5).value == "Giả định — chưa nhập"
    assert ws.cell(rows["− Giá vốn (đã trừ VAT đầu vào)"], 5).value.startswith("Thật 50,0 %")
    ads = next(k for k in rows if k.startswith("− Quảng cáo"))
    assert ws.cell(rows[ads], 5).value.endswith("gồm 15.000đ ngày không có đơn")
    # Shopee's total still holds the refund order: the bridge subtracts it once, beside the
    # cancelled one, and the in-transit row stays
    assert ws.cell(rows["− Đơn hoàn tiền / trả hàng"], 2).value == -40_000
    assert ws.cell(rows["− Đơn hủy"], 2).value == -60_000 and "− Đơn đang giao" in rows
    margin = rows[tq.MARGIN_LABEL]
    assert ws.cell(margin, 2).value == f'=IFERROR(B{profit}/B{base},"—")'
    # the headline from the sale lines already leaves the refund orders out: no refund row
    data.bridge = replace(b, refunds_in_gmv=False)
    lines_ws = tq.build(data)[tq.SHEET_PROFIT]
    labels = {lines_ws.cell(r, 1).value for r in range(1, lines_ws.max_row + 1)}
    assert "− Đơn hoàn tiền / trả hàng" not in labels and "− Đơn hủy" in labels
