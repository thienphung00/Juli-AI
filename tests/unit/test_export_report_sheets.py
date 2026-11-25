"""The Tổng quan export answers the client's report request from Juli data (batch-1117b R1-R10,
R13). Synthetic numbers only; the builders are pure, the collector tests use the synthetic reco
shop."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from juli_backend.services.exports import report_calc as calc
from juli_backend.services.exports import report_sheets as rs
from juli_backend.services.exports import tong_quan_xlsx as tq
from juli_backend.services.exports.collect import collect_tong_quan, partition
from juli_backend.services.metrics.registry import METRICS
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_p100_exports import START, _data
from tests.unit.test_shopee_reco_plan import _USER_IDS, NOW

DASH = "—"


# ------------------------------------------------------------------------------ R2 / calendar


def test_a_whole_month_compares_with_the_previous_calendar_month():
    assert calc.previous_period(date(2026, 10, 1), date(2026, 10, 31)) == (
        date(2026, 9, 1), date(2026, 9, 30), calc.PREV_MONTH,
    )  # fmt: skip
    assert calc.previous_period(date(2026, 3, 1), date(2026, 3, 31))[:2] == (
        date(2026, 2, 1), date(2026, 2, 28),
    )  # fmt: skip


def test_any_other_period_compares_with_the_same_length_period_before():
    assert calc.previous_period(date(2026, 10, 1), date(2026, 10, 10)) == (
        date(2026, 9, 21), date(2026, 9, 30), calc.PREV_PERIOD,
    )  # fmt: skip
    assert calc.previous_period(date(2026, 10, 12), date(2026, 11, 10))[2] == calc.PREV_PERIOD


def test_months_of_a_period_are_the_month_before_then_each_month_clipped():
    assert calc.months_of(date(2026, 10, 12), date(2026, 11, 10)) == [
        (date(2026, 9, 1), date(2026, 9, 30)),
        (date(2026, 10, 12), date(2026, 10, 31)),
        (date(2026, 11, 1), date(2026, 11, 10)),
    ]


def test_overview_has_percent_of_revenue_margin_prior_period_and_goal():
    d = _data()
    d.prev_kind = calc.PREV_MONTH
    d.goal_gmv, d.goal_profit = 6_000_000.0, 1_000_000.0
    ws = tq.build(d)[tq.SHEET_OVERVIEW]
    assert [c.value for c in ws[3]] == [
        "Chỉ số", "Kỳ này", "% doanh thu thực", "Tháng trước (12/09/2026–11/10/2026)", "Thay đổi",
        "Mục tiêu (Kế hoạch)", "So với mục tiêu",
    ]  # fmt: skip
    # L3: every cost % is ÷ the covered doanh thu thực (the margin base, row 14)
    assert ws.cell(tq.OV["base"], 3).value == 1.0
    for key in ("profit", "ads", "aff", "offer", "cost"):
        r = tq.OV[key]
        assert ws.cell(r, 3).value == f'=IF(ISNUMBER(B{r}),IFERROR(B{r}/B$14,"—"),"—")'
        assert ws.cell(r, 3).number_format == "0.0%"
    r = tq.OV["margin"]
    assert ws.cell(r, 1).value == tq.MARGIN_LABEL
    assert ws.cell(r, 2).value == '=IF(AND(ISNUMBER(B7),ISNUMBER(B14)),IFERROR(B7/B14,"—"),"—")'
    assert ws["D4"].value == 4_950_000 and ws["D7"].value == 810_000  # kỳ trước, as values
    assert ws["F4"].value == 6_000_000.0 and ws["F7"].value == 1_000_000.0
    assert ws["G4"].value.startswith("=IF(AND(ISNUMBER(B4),ISNUMBER(F4))")
    assert ws["F8"].value == DASH and ws["G8"].value == DASH  # no goal for a cost line
    assert ws.cell(r, 6).value == pytest.approx(1_000_000 / 6_000_000)


def test_no_plan_means_the_goal_cells_are_a_dash():
    ws = tq.build(_data())[tq.SHEET_OVERVIEW]  # goal_gmv / goal_profit are None
    assert ws["F4"].value == DASH and ws["F7"].value == DASH and ws["F13"].value == DASH


def test_excel_labels_come_from_the_registry():
    """Owner 2026-11-20: the backend registry is the truth; every Excel metric that has a registry
    entry carries its label (Chi phí marketing, ROI, Biên lợi nhuận)."""
    assert tq.ROI_LABEL == METRICS["roi"].label_vi
    assert tq.COST_LABEL == METRICS["cost_marketing"].label_vi
    assert tq.MARGIN_LABEL == METRICS["margin"].label_vi
    wb = tq.build(_data())
    labels = {
        str(c.value)
        for ws in wb.worksheets
        for row in ws.iter_rows()
        for c in row
        if isinstance(c.value, str)
    }
    assert f"{tq.ROI_LABEL} (lần)" in labels and tq.COST_LABEL + " (đ)" in labels
    assert tq.ROI_LABEL in {c.value for c in wb[tq.SHEET_CHANNEL][3]}
    assert tq.COST_LABEL in {c.value for c in wb[tq.SHEET_DAY][3]}
    # decision #44: ROI is ÷ Tổng chi phí (the registry's cost_total), its own labelled row
    assert f"{METRICS['cost_total'].label_vi} (đ)" in labels
    assert not any("QC + AFF" in v or "không tính là chi phí" in v for v in labels)
    assert f"{METRICS['cost_marketing'].label_vi} (đ)" in rs.MONTH_HEADER


def test_roi_and_margin_cells_reproduce_the_registry_values():
    from decimal import Decimal as D

    from juli_backend.services.metrics.compute import evaluate

    comp = {
        "net_revenue_known": D(8_000_000), "cogs": D(3_000_000), "packaging": D(200_000),
        "fees": D(900_000), "shipping_net": D(100_000), "affiliate_commission": D(300_000),
        "ads_spend": D(700_000), "other_marketing": D(0), "offer_promo": D(250_000),
        "offer_voucher": D(120_000), "offer_combo": D(30_000),
    }  # fmt: skip
    profit = evaluate("profit", comp).value
    roi = evaluate("roi", comp).value
    margin = evaluate("margin", comp).value
    cost_total = evaluate("cost_total", comp).value
    fig = tq.Figures(
        gmv=9_000_000, orders=30, profit=float(profit), ads_cost=700_000, aff_cost=300_000,
        offer_cost=400_000, net_revenue_known=8_000_000, cost_total=float(cost_total),
    )  # fmt: skip
    d = _data()
    d.now = fig
    ws = tq.build(d)[tq.SHEET_OVERVIEW]
    assert ws["B8"].value + ws["B9"].value + ws["B10"].value == float(
        evaluate("cost_marketing", comp).value
    )
    assert ws["B11"].value == "=SUM(B8:B10)"
    # decision #44: ROI = Lợi nhuận ròng ÷ Tổng chi phí (row 19)
    assert ws["B12"].value == '=IFERROR(B7/B19,"—")'
    assert ws["B7"].value / ws["B19"].value == pytest.approx(float(roi), abs=0.05)
    assert ws["B7"].value / ws["B14"].value * 100 == pytest.approx(float(margin), abs=0.05)
    assert ws["B13"].value.count("B14") == 2  # the base is the known-cost net revenue, not GMV


def test_all_shops_total_recomputes_the_ratios_from_the_summed_parts():
    a, b = _data(), _data()
    b.now = tq.Figures(
        gmv=1_000_000, orders=5, profit=100_000, ads_cost=10_000, aff_cost=0, offer_cost=5_000,
        net_revenue_known=900_000,
    )  # fmt: skip
    ws = tq.build_multi([a, b])[tq.SHEET_OVERVIEW]
    r = tq.OV
    assert ws.cell(r["cost"], 2).value == f"=SUM(B{r['ads']}:B{r['offer']})"
    assert ws.cell(r["base"], 4).value == f"=SUM(B{r['base']}:C{r['base']})"
    assert ws.cell(r["margin"], 4).value == f'=IFERROR(D{r["profit"]}/D{r["base"]},"")'
    assert ws.cell(r["roi"], 4).value == f'=IFERROR(D{r["profit"]}/D{r["cost_total"]},"")'
    assert not tq.summable_row("margin")


# ------------------------------------------------------------------------------ R3 Theo tháng


def test_months_sheet_has_a_row_per_month_with_change_against_the_row_above():
    d = _data()
    d.months = [
        rs.MonthRow("09/2026", 1_000_000, 10, 100_000, 50_000),
        rs.MonthRow("10/2026", 1_500_000, 12, 180_000, 60_000),
        rs.MonthRow("11/2026"),  # the stored days do not cover it
    ]
    ws = tq.build(d)[rs.SHEET_MONTH]
    assert [c.value for c in ws[3]] == rs.MONTH_HEADER
    assert [ws.cell(r, 1).value for r in (4, 5, 6)] == ["09/2026", "10/2026", "11/2026"]
    assert ws["B5"].value == 1_500_000 and ws["C5"].value == 12 and ws["E5"].value == 180_000
    assert ws["F5"].value == 60_000
    assert ws["D5"].value.startswith("=IF(AND(ISNUMBER(B5),ISNUMBER(C5)),IFERROR(B5/C5")
    assert ws["G4"].value == DASH  # the first month has nothing before it
    assert ws["G5"].value.startswith("=IF(AND(ISNUMBER(B5),ISNUMBER(B4)),IFERROR(B5/B4-1")
    assert ws["B6"].value == DASH and ws["E6"].value == DASH  # missing is not 0


# ------------------------------------------------------------------------------ R4 Theo kênh


def test_a_basis_change_makes_the_organic_and_ads_change_a_dash():
    d = _data()
    d.now.ads_basis, d.prev.ads_basis = "overlay", "report"
    ws = tq.build(d)[tq.SHEET_CHANNEL]
    assert ws["D4"].value == DASH and ws["D5"].value == DASH and ws["D8"].value == DASH
    assert ws["D6"].value.startswith("=IFERROR(B6/")  # affiliate is on the same basis


def test_the_same_basis_keeps_the_change():
    d = _data()
    d.now.ads_basis = d.prev.ads_basis = "overlay"
    ws = tq.build(d)[tq.SHEET_CHANNEL]
    assert ws["D4"].value.startswith("=IFERROR(B4/") and ws["D5"].value.startswith("=IFERROR(B5/")


def test_channel_sheet_has_cost_to_revenue_profit_and_ratio_per_channel():
    ws = tq.build(_data())[tq.SHEET_CHANNEL]
    assert [c.value for c in ws[3]][7:] == [
        tq.ROI_LABEL, "Chi phí / doanh thu", "Lợi nhuận kênh (đ)",
    ]  # fmt: skip
    assert ws["I5"].value == "=IFERROR(G5/'Tổng quan'!$B$4,\"—\")"
    assert ws["H5"].value == '=IF(ISNUMBER(G5),IFERROR(J5/G5,"—"),"—")'
    assert ws["H4"].value == DASH  # Organic has no cost
    assert ws["J5"].value.endswith('-N(G5),"—"),"—")')
    assert ws["J7"].value == '=IF(ISNUMBER(G7),-G7,"—")'  # the ưu đãi row takes the offers
    assert ws["J8"].value == "=SUM(J4:J7)"  # the rows add up to the shop's profit
    assert ws["G8"].value == "=SUM(G4:G7)"  # chi phí marketing incl. ưu đãi
    assert "biên lợi nhuận" in ws["A10"].value


# ------------------------------------------------------------------------------ R5 products


def test_partition_makes_the_channels_add_up_to_the_gmv():
    organic, ads, aff = calc.partition_channels(1_000.0, 600.0, 500.0, 1_000.0)
    assert (organic, ads, aff) == (0.0, 500.0, 500.0)  # the old 135 %: now 100 %
    assert organic + ads + aff == 1_000.0
    assert calc.partition_channels(1_000.0, 200.0, 300.0, 9_999.0) == (500.0, 200.0, 300.0)
    assert calc.partition_channels(None, 1.0, 2.0, 3.0) == (3.0, 1.0, 2.0)
    assert calc.partition_channels(1_000.0, None, None, 700.0) == (700.0, None, None)


def test_a_product_whose_organic_was_its_full_gmv_is_repartitioned():
    fig = tq.Figures(
        {
            "organic": tq.Channel(gmv=1_000.0),
            "ads": tq.Channel(gmv=250.0),
            "affiliate": tq.Channel(gmv=100.0),
        },
        gmv=1_000.0,
    )
    got = partition(fig)
    assert [got.channel(k).gmv for k in tq.CHANNELS] == [650.0, 250.0, 100.0]
    assert sum(got.channel(k).gmv for k in tq.CHANNELS) == got.gmv


def test_product_sheet_has_share_of_shop_profit_cost_ratio_and_cost_share():
    d = _data()
    ws = tq.build(d)[tq.SHEET_PRODUCT]
    assert [c.value for c in ws[3]][9:13] == [
        "% doanh thu shop", "% lợi nhuận shop", "Chi phí / doanh thu SP",
        "% chi phí marketing shop",
    ]  # fmt: skip
    total = tq.P_FIRST + len(d.products)
    assert ws["J4"].value == f'=IFERROR(C4/C${total},"—")'
    assert ws["K4"].value == f'=IFERROR(E4/E${total},"—")'
    assert ws["L4"].value == '=IFERROR(R4/C4,"—")'
    assert ws["M4"].value == f'=IFERROR(R4/R${total},"—")'
    assert ws["B6"].value == tq.SHOP_ROW_NAME and "chưa gán sản phẩm" in ws["B6"].value


def test_a_partitioned_product_row_sums_to_its_gmv_in_the_sheet():
    d = _data()
    for p in d.products:
        p.now = partition(p.now)
    ws = tq.build(d)[tq.SHEET_PRODUCT]
    for r in range(tq.P_FIRST, tq.P_FIRST + len(d.products)):
        parts = [ws.cell(r, c).value for c in (15, 16, 17)]
        assert sum(parts) == pytest.approx(ws.cell(r, 3).value)


# ------------------------------------------------------------------------------ R6 SKU


def test_sku_sheet_fills_stock_rate_days_left_and_a_labelled_reorder_quantity():
    d = _data()
    d.skus = [
        tq.SkuRow("S1", "Đỏ", "SP", 8, 900, 90, stock=30, rate=2.0, days_left=15),
        tq.SkuRow("S2", None, "SP", 3, 300, None),  # no stock read: "—", never 0
    ]
    ws = tq.build(d)[tq.SHEET_SKU]
    head = [c.value for c in ws[3]]
    assert head[7:11] == ["Tồn kho", "Hệ số combo", "Bán / ngày", "Còn ~ (ngày)"]
    assert head[11].startswith("Cần nhập") and "7 + 14" in head[11]
    assert (ws["H4"].value, ws["J4"].value, ws["K4"].value) == (30, 2.0, 15)
    assert ws["L4"].value == '=IF(AND(ISNUMBER(J4),ISNUMBER(H4)),MAX(0,J4*(7+14)-H4),"—")'
    assert 2.0 * (calc.LEAD_DAYS + calc.COVER_DAYS) - 30 == 12  # what Excel shows for S1
    assert (ws["H5"].value, ws["J5"].value, ws["K5"].value) == (DASH, DASH, DASH)


def test_reorder_need_is_floored_at_zero_and_unknown_without_a_rate_or_stock():
    assert calc.reorder_need(2.0, 30) == 12.0
    assert calc.reorder_need(2.0, 100) == 0.0
    assert calc.reorder_need(None, 5) is None and calc.reorder_need(1.0, None) is None


def test_the_sku_gap_row_says_why():
    d = _data()
    d.skus = [tq.SkuRow("S1", None, "SP", 1, 100, 10)]
    ws = tq.build(d)[tq.SHEET_SKU]
    assert ws["A5"].value == "Chênh lệch: doanh thu dòng đơn khác Doanh số Shopee"


# ------------------------------------------------------------------------------ R7 KOC


SECTION = {
    "totals": {"gmv": 900.0},
    "rows": [
        {"kol_key": "k1", "handle": "koc_a", "channel_label": "Video", "product_name": "SP A",
         "orders": 3, "gmv": 300.0, "commission": 30.0, "profit": 60.0, "prev_gmv": 200.0,
         "prev_profit": 40.0},
        {"kol_key": "k1", "handle": "koc_a", "channel_label": "Live", "product_name": "SP B",
         "orders": 2, "gmv": 500.0, "commission": 50.0, "profit": 90.0, "prev_gmv": None,
         "prev_profit": None},
        {"kol_key": "k2", "handle": "koc_b", "channel_label": "Video", "product_name": "SP A",
         "orders": 1, "gmv": 100.0, "commission": 10.0, "profit": None, "prev_gmv": None,
         "prev_profit": None},
    ],
}  # fmt: skip


def test_koc_rows_are_the_kol_screens_rows_summed_per_koc():
    rows = {r.handle: r for r in rs.koc_rows(SECTION)}
    a = rows["koc_a"]
    assert (a.orders, a.gmv, a.commission, a.profit) == (5.0, 800.0, 80.0, 150.0)
    assert (a.prev_gmv, a.prev_profit) == (200.0, 40.0)
    assert a.channels == "Video, Live" and a.top_product == "SP B"
    assert rows["koc_b"].profit is None  # unknown, not 0
    assert sum(r.gmv for r in rows.values()) == sum(r["gmv"] for r in SECTION["rows"])
    assert [r.handle for r in rs.koc_rows(SECTION)] == ["koc_a", "koc_b"]  # biggest GMV first


def test_koc_sheet_has_the_koc_columns_and_the_affiliate_share_of_the_shop():
    d = _data()
    d.koc = rs.koc_rows(SECTION)
    d.affiliate_share = rs.AffiliateShare(500_000, 5_500_000, 300_000, 4_950_000)
    ws = tq.build(d)[rs.SHEET_KOC]
    assert [c.value for c in ws[3]] == rs.KOC_HEADER
    assert [ws["A4"].value, ws["B4"].value, ws["C4"].value, ws["D4"].value] == [
        "koc_a", "Video, Live", 5.0, 800.0,
    ]  # fmt: skip
    assert ws["M3"].value == "Sản phẩm bán nhiều nhất"
    assert ws["E4"].value == 80.0 and ws["F4"].value == 150.0 and ws["M4"].value == "SP B"
    assert ws["H4"].value == '=IFERROR(D4/G4-1,"—")' and ws["H5"].value == DASH
    assert ws["D6"].value == "=SUM(D4:D5)"
    labels = {ws.cell(r, 1).value: r for r in range(7, 16) if ws.cell(r, 1).value}
    share = labels["Tiếp thị liên kết / GMV cả shop"]
    assert ws.cell(share - 2, 2).value == 500_000 and ws.cell(share - 1, 3).value == 4_950_000
    assert ws.cell(share, 4).value.startswith("=IF(AND(ISNUMBER(B")


# ------------------------------------------------------------------------------ R8 analysis


class _Card:
    def __init__(self, code, kind_key, product_id, profit, gmv, actual=None, concl=None):
        self.code, self.kind_key, self.kind = code, kind_key, f"Loại {kind_key}"
        self.product_id, self.status = product_id, "Đang chạy"
        self.profit_mid, self.gmv_mid, self.actual_profit, self.conclusion = (
            profit,
            gmv,
            actual,
            concl,
        )


ITEMS = [
    {"kpi": "ctr", "level": "product", "product_id": "p1", "name": "SP A", "current": 0.01,
     "reference": {"value": 0.02}, "deviation_pct": -50.0, "at_stake_per_day": 12_000,
     "cause": {"stage": "ctr", "text": "Khách thấy sản phẩm nhưng ít bấm vào."},
     "change_kinds": ["cover_image", "title"]},
    {"kpi": "aov", "level": "product", "product_id": "p2", "name": "SP B", "current": 100,
     "reference": {"value": 150}, "deviation_pct": -33.3, "at_stake_per_day": 5_000,
     "cause": {"stage": "aov", "text": "Giá trị mỗi đơn thấp."}, "change_kinds": ["bundle_deal"]},
]  # fmt: skip


def test_each_critical_metric_lists_its_cards_with_expected_actual_and_status():
    cards = [
        _Card("JC-1", "cover_image", "p1", 50_000.0, 200_000.0, 40_000.0, "Trong khoảng"),
        _Card("JC-2", "title", "p1", 10_000.0, 30_000.0),
        _Card("JC-3", "cover_image", "p9", 1.0, 1.0),  # another product's card: not listed
    ]
    rows = rs.analysis_rows(ITEMS, cards)
    assert [(r.metric, r.card_code) for r in rows] == [
        ("CTR", "JC-1, JC-2"), ("AOV", rs.NO_CARD),
    ]  # fmt: skip
    first = rows[0]
    assert first.expected_profit is None and first.expected_gmv is None
    assert first.actual_profit is None and first.status == DASH
    assert first.cause == "Khách thấy sản phẩm nhưng ít bấm vào." and first.target == "SP A"
    assert "JC-1" in first.card_code and "JC-2" in first.card_code
    assert rows[1].expected_profit is None and rows[1].status == DASH


def test_analysis_sheet_writes_a_dash_for_what_is_missing():
    d = _data()
    d.analysis = rs.analysis_rows(ITEMS, [_Card("JC-1", "cover_image", "p1", 5.0, 6.0)])
    ws = tq.build(d)[rs.SHEET_ANALYSIS]
    assert [c.value for c in ws[3]] == rs.ANALYSIS_HEADER
    assert ws["A4"].value == "CTR" and ws["I4"].value == "JC-1" and ws["K4"].value == 5.0
    assert ws["M4"].value == DASH  # not measured yet
    assert ws["I5"].value == rs.NO_CARD and ws["K5"].value == DASH and ws["N5"].value == DASH
    assert ws["F4"].value == pytest.approx(-0.5)


# ------------------------------------------------------------------------------ R9 / R10 days


def test_day_sheet_never_leaves_a_channel_cell_blank_and_names_its_cost_column():
    d = _data()
    d.days = [
        tq.DayRow(START + timedelta(days=i), {k: None for k in tq.CHANNELS},
                  {k: None for k in tq.CHANNELS}, total_gmv=100.0, total_orders=1.0)
        for i in range(6)
    ]  # fmt: skip
    ws = tq.build(d)[tq.SHEET_DAY]
    assert ws.cell(3, 7).value == tq.COST_LABEL
    for r in range(tq.DAY_FIRST, tq.DAY_FIRST + 6):
        assert [ws.cell(r, c).value for c in (2, 3, 4, 7, 8)] == [DASH] * 5


# ------------------------------------------------------------------------------ collector


async def test_the_month_to_date_export_reads_the_new_sheets_and_partitions_products(session):
    """The synthetic shop has data to 07/10 only: the month is month-to-date, so the comparison is
    the same-length period (a whole month compares with the calendar month: the pure tests)."""
    seeded = await seed_reco_shop(session)
    from juli_backend.services.shopee_analytics import materialize

    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    data = await collect_tong_quan(
        session, seeded.shop_id, shop_name="Mẫu", now=NOW, period="month",
        month=f"{AS_OF:%Y-%m}",
    )  # fmt: skip
    first = AS_OF.replace(day=1)
    assert data.start == first and data.end == AS_OF
    assert data.prev_kind == calc.PREV_PERIOD
    assert [m.label for m in data.months][0] == f"{(first - timedelta(days=1)):%m/%Y}"
    assert data.months[1].gmv == data.now.gmv  # the month of the period = the period
    wb = tq.build(data)
    assert {rs.SHEET_MONTH, rs.SHEET_KOC, rs.SHEET_ANALYSIS} <= set(wb.sheetnames)
    ws = wb[tq.SHEET_PRODUCT]
    checked = 0
    for r in range(tq.P_FIRST, tq.P_FIRST + len(data.products)):
        gmv = ws.cell(r, 3).value
        parts = [ws.cell(r, c).value for c in (15, 16, 17)]
        if isinstance(gmv, int | float) and all(isinstance(x, int | float) for x in parts):
            assert sum(parts) == pytest.approx(gmv)  # the channels partition the product's GMV
            checked += 1
    assert checked >= 1
    assert data.products[-1].name == tq.SHOP_ROW_NAME


async def test_a_ten_day_export_compares_with_the_ten_days_before(session):
    seeded = await seed_reco_shop(session)
    from juli_backend.services.shopee_analytics import materialize

    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    _USER_IDS[seeded.shop_id] = seeded.user.id
    start = date(2026, 10, 1)
    data = await collect_tong_quan(
        session, seeded.shop_id, shop_name="Mẫu", now=NOW, period="custom", start=start,
        end=start + timedelta(days=9),
    )  # fmt: skip
    assert data.prev_kind == calc.PREV_PERIOD
    assert (data.prev_start, data.prev_end) == (date(2026, 9, 21), date(2026, 9, 30))
    assert tq.prev_label(data) == "Kỳ trước (21/09/2026–30/09/2026)"
