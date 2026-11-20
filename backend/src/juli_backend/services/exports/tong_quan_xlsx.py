"""The Tổng quan export: a pure builder, plain dataclasses in, an openpyxl Workbook / bytes out.

Sheets: "Tổng quan" (the shop's numbers, this period vs the previous), "Lợi nhuận" (shop level:
revenue lines and the profit bridge, one cost per line, see ``profit_bridge``), "Theo kênh"
(Organic / Quảng cáo / Tiếp thị liên kết), "Theo ngày", "Theo sản phẩm", "Theo SKU". No Kế hoạch
baseline or goal: those are in the Kế hoạch export (UI grill G21).

Every number is an input; the ratios (AOV, CTR, CTOR, % GMV, ROI, Thay đổi, % đạt) and the
totals are Excel formulas over the cells of the sheet, so the file recomputes when a figure is
edited. ``fullCalcOnLoad`` is set (no cached values are stored). Only Excel-2007 functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from openpyxl import Workbook

from juli_backend.services.exports import report_sheets as rs
from juli_backend.services.exports._style import (
    DATE,
    FONT,
    INT,
    MONEY,
    PCT,
    POINTS,
    TITLE,
    col,
    finish,
    header,
    new_workbook,
    put,
    save_bytes,
    widths,
)
from juli_backend.services.exports.profit_bridge import ProfitBridge
from juli_backend.services.exports.report_calc import (
    COVER_DAYS,
    DASH,
    LEAD_DAYS,
    PREV_MONTH,
    PREV_PERIOD,
)
from juli_backend.services.metrics.registry import METRICS

CHANNELS = ("organic", "ads", "affiliate")
CHANNEL_LABELS = {"organic": "Organic", "ads": "Quảng cáo", "affiliate": "Tiếp thị liên kết"}
SHOP_ROW_LABEL = "Cả shop"
#: what the "Cả shop" row holds: the shop's figures minus the products' (ads and costs that no
#: product owns, order lines without a product)
SHOP_ROW_NAME = "Cả shop — quảng cáo và chi phí chưa gán sản phẩm"
#: the labels of the metrics that have a registry entry come from the registry (owner 2026-11-20:
#: the backend is the source of truth, the Excel follows it)
ROI_LABEL = METRICS["roi"].label_vi
COST_LABEL = METRICS["cost_marketing"].label_vi
MARGIN_LABEL = METRICS["margin"].label_vi
#: the margin's base is a component, which has no label of its own in the registry
BASE_LABEL = "Doanh thu thực của đơn đủ chi phí"

SHEET_OVERVIEW = "Tổng quan"
SHEET_CHANNEL = "Theo kênh"
SHEET_DAY = "Theo ngày"
SHEET_PRODUCT = "Theo sản phẩm"
SHEET_SKU = "Theo SKU"
SHEET_PROFIT = "Lợi nhuận"
#: the offers are part of Chi phí marketing (registry cost_marketing = QC + TTLK + Ưu đãi)
OFFER_LABEL = "Ưu đãi của shop (đ)"


@dataclass
class Channel:
    """One channel of one period. ``None`` = no data (the cell stays empty)."""

    views: float | None = None
    clicks: float | None = None
    orders: float | None = None
    gmv: float | None = None
    cost: float | None = None


@dataclass
class Figures:
    """One scope (shop or product) over one period."""

    channels: dict[str, Channel] = field(default_factory=dict)
    gmv: float | None = None
    orders: float | None = None
    profit: float | None = None
    ads_cost: float | None = None
    aff_cost: float | None = None
    offer_cost: float | None = None
    #: the margin base (registry ``net_revenue_known``): the buyer paid, after output VAT, of the
    #: orders whose every cost is known; ``None`` = unknown (the margin is then "—")
    net_revenue_known: float | None = None
    #: "overlay" (Seller Centre's ads overlay) | "report" (ads report): the basis of the Quảng cáo
    #: GMV; periods on different bases do not compare ("—")
    ads_basis: str | None = None

    def channel(self, key: str) -> Channel:
        return self.channels.get(key) or Channel()


@dataclass
class DayRow:
    day: date
    gmv: dict[str, float | None]
    orders: dict[str, float | None]
    ads_cost: float | None = None
    aff_cost: float | None = None
    offer_cost: float | None = None
    profit: float | None = None
    #: the day's own GMV / orders (the stored daily order totals): what the GMV / Đơn columns
    #: show, so the days add up to the period even on a day without traffic-source rows
    total_gmv: float | None = None
    total_orders: float | None = None


@dataclass
class ProductRow:
    product_id: str
    name: str
    now: Figures
    prev: Figures


@dataclass
class SkuRow:
    """One SKU of the "Theo SKU" sheet; ``None`` = unknown (the cell stays empty)."""

    sku: str
    variation: str | None
    product_name: str
    units: float | None = None
    revenue: float | None = None
    profit: float | None = None
    stock: float | None = None
    #: units / day and days of stock left as the stock alert forecasts them (None = no forecast)
    rate: float | None = None
    days_left: float | None = None
    #: units per variation of a combo SKU ("G500001×10" -> sku "G500001", combo 10)
    combo: float | None = None


@dataclass
class TongQuanData:
    shop_name: str
    start: date
    end: date
    prev_start: date
    prev_end: date
    now: Figures
    prev: Figures
    days: list[DayRow] = field(default_factory=list)
    #: one row per product, then the "Cả shop" row (shop minus the products), so the product
    #: sheet's Tổng row equals the shop
    products: list[ProductRow] = field(default_factory=list)
    platform: str = "Shopee"
    #: set at the Sản phẩm level: the sheets then hold this product only
    product_name: str | None = None
    product_id: str | None = None
    skus: list[SkuRow] = field(default_factory=list)
    #: ``PREV_MONTH`` (the previous calendar month) or ``PREV_PERIOD`` (the same-length period)
    prev_kind: str = PREV_PERIOD
    #: Mục tiêu: the Kế hoạch's expected GMV / lợi nhuận of the period (``None`` = no plan)
    goal_gmv: float | None = None
    goal_profit: float | None = None
    months: list[rs.MonthRow] = field(default_factory=list)
    koc: list[rs.KocRow] = field(default_factory=list)
    affiliate_share: rs.AffiliateShare | None = None
    analysis: list[rs.AnalysisRow] = field(default_factory=list)
    #: the "Lợi nhuận" sheet (shop level only; ``None`` = no sheet)
    bridge: ProfitBridge | None = None


def _d(x: date) -> str:
    return f"{x:%d/%m/%Y}"


def prev_label(data: TongQuanData) -> str:
    span = f"{_d(data.prev_start)}–{_d(data.prev_end)}"
    return f"Tháng trước ({span})" if data.prev_kind == PREV_MONTH else f"Kỳ trước ({span})"


def title_of(data: TongQuanData) -> str:
    level = f" · {data.product_name}" if data.product_name else ""
    return (
        f"TỔNG QUAN — {data.shop_name} ({data.platform}){level} · {_d(data.start)}–{_d(data.end)}"
        f" · so với {_d(data.prev_start)}–{_d(data.prev_end)}"
    )


def file_name(data: TongQuanData) -> str:
    name = data.shop_name.replace(" ", "")
    sku = f"_{data.product_id}" if data.product_id else ""
    return f"Juli_TongQuan_{name}{sku}_{data.start:%d%m%Y}_{data.end:%d%m%Y}.xlsx"


def _sum(*vals: float | None) -> float | None:
    known = [v for v in vals if v is not None]
    return sum(known) if known else None


def _div(a: float | None, b: float | None) -> float | None:
    return None if a is None or not b else a / b


def _change_vs(ref: str, prev: float | None) -> str:
    """Thay đổi = this period's cell / the previous period's value - 1; the previous value sits
    inside the formula (the file does not carry a "Kỳ trước" column)."""
    return DASH if prev is None else f'=IFERROR({ref}/{float(prev)!r}-1,"{DASH}")'


def _hide(ws, *letters: str) -> None:
    for letter in letters:
        ws.column_dimensions[letter].hidden = True


def gmv_of(fig: Figures) -> float | None:
    """GMV of a scope = Σ its channels' GMV (what Theo kênh / Theo sản phẩm show)."""
    return _sum(*(fig.channel(k).gmv for k in CHANNELS))


def cost_of(fig: Figures) -> float | None:
    """Chi phí marketing (registry ``cost_marketing``) = quảng cáo + tiếp thị liên kết + ưu đãi."""
    return _sum(fig.ads_cost, fig.aff_cost, fig.offer_cost)


# ----------------------------------------------------------------------------- Tổng quan

OVERVIEW_HEADER = [
    "Chỉ số", "Kỳ này", "% doanh thu", "Kỳ trước", "Thay đổi", "Mục tiêu (Kế hoạch)",
    "So với mục tiêu",
]  # fmt: skip
OV = {  # row of each metric on the "Tổng quan" sheet
    "gmv": 4, "orders": 5, "aov": 6, "profit": 7, "ads": 8, "aff": 9, "offer": 10, "cost": 11,
    "roi": 12, "margin": 13, "base": 14,
}  # fmt: skip
#: rows that are costs / profit: shown as a % of the revenue (GMV)
SHARE_ROWS = ("profit", "ads", "aff", "offer", "cost")
#: the rows Chi phí marketing sums (the registry's cost_marketing)
COST_ROWS = ("ads", "aff", "offer")


def _overview_values(fig: Figures) -> dict[str, float | None]:
    cost = cost_of(fig)
    return {
        "gmv": fig.gmv, "orders": fig.orders, "aov": _div(fig.gmv, fig.orders),
        "profit": fig.profit, "ads": fig.ads_cost, "aff": fig.aff_cost, "offer": fig.offer_cost,
        "cost": cost or 0.0, "roi": None if fig.profit is None else _div(fig.profit, cost),
        "margin": None if fig.profit is None else _div(fig.profit, fig.net_revenue_known),
        "base": fig.net_revenue_known,
    }  # fmt: skip


def _dash(v: float | None) -> float | str:
    return DASH if v is None else v


def _overview(wb: Workbook, data: TongQuanData) -> None:
    ws = wb.create_sheet(SHEET_OVERVIEW)
    put(ws, 1, 1, title_of(data)).font = TITLE
    header(ws, 3, [*OVERVIEW_HEADER[:3], prev_label(data), *OVERVIEW_HEADER[4:]])
    rows = [
        ("gmv", "GMV — doanh thu (đ)", MONEY), ("orders", "Đơn", INT), ("aov", "AOV (đ)", MONEY),
        ("profit", "Lợi nhuận (đ)", MONEY),
        ("ads", "Chi phí quảng cáo (Báo cáo DVHT) (đ)", MONEY),
        ("aff", "Chi phí tiếp thị liên kết (đ)", MONEY), ("offer", OFFER_LABEL, MONEY),
        ("cost", f"{COST_LABEL} (đ)", MONEY),
        ("roi", f"{ROI_LABEL} (lần)", POINTS), ("margin", MARGIN_LABEL, PCT),
        ("base", f"{BASE_LABEL} (đ)", MONEY),
    ]  # fmt: skip
    prev = _overview_values(data.prev)
    now = _overview_values(data.now)
    goals = {"gmv": data.goal_gmv, "profit": data.goal_profit}
    goals["margin"] = _div(data.goal_profit, data.goal_gmv)
    g = OV["gmv"]
    for key, label, fmt in rows:
        r = OV[key]
        put(ws, r, 1, label)
        if key == "aov":
            v: object = f'=IFERROR(B{OV["gmv"]}/B{OV["orders"]},"{DASH}")'
        elif key == "cost":
            v = f"=SUM(B{OV['ads']}:B{OV['offer']})"
        elif key == "roi":
            v = f'=IFERROR(B{OV["profit"]}/B{OV["cost"]},"{DASH}")'
        elif key == "margin":
            b = OV["base"]
            v = (
                f"=IF(AND(ISNUMBER(B{OV['profit']}),ISNUMBER(B{b})),"
                f'IFERROR(B{OV["profit"]}/B{b},"{DASH}"),"{DASH}")'
            )
        else:
            v = _dash(now[key])
        put(ws, r, 2, v, fmt)
        if key in SHARE_ROWS:
            put(ws, r, 3, f'=IF(ISNUMBER(B{r}),IFERROR(B{r}/B${g},"{DASH}"),"{DASH}")', PCT)
        elif key == "gmv":
            put(ws, r, 3, 1.0, PCT)
        put(ws, r, 4, _dash(prev[key]), fmt)
        if key == "margin":  # a rate: the change is in points
            put(ws, r, 5, f'=IF(AND(ISNUMBER(B{r}),ISNUMBER(D{r})),B{r}-D{r},"{DASH}")', PCT)
        else:
            put(
                ws, r, 5,
                f'=IF(AND(ISNUMBER(B{r}),ISNUMBER(D{r})),IFERROR(B{r}/D{r}-1,"{DASH}"),"{DASH}")',
                PCT,
            )  # fmt: skip
        if key in goals:
            put(ws, r, 6, _dash(goals[key]), fmt)
            if key == "margin":
                put(ws, r, 7, f'=IF(AND(ISNUMBER(B{r}),ISNUMBER(F{r})),B{r}-F{r},"{DASH}")', PCT)
            else:
                put(
                    ws, r, 7,
                    f'=IF(AND(ISNUMBER(B{r}),ISNUMBER(F{r})),IFERROR(B{r}/F{r},"{DASH}"),"{DASH}")',
                    PCT,
                )  # fmt: skip
        else:
            put(ws, r, 6, DASH)
            put(ws, r, 7, DASH)
    note = OV["base"] + 2
    put(
        ws,
        note,
        1,
        "Thay đổi của Biên lợi nhuận tính bằng điểm %; So với mục tiêu = Kỳ này ÷ Mục tiêu.",
    )
    put(
        ws,
        note + 1,
        1,
        "Mục tiêu = kết quả Juli dự kiến khi áp dụng các thẻ của Kế hoạch; “—” = chưa có kế hoạch.",
    )
    widths(ws, [40, 16, 12, 24, 12, 20, 16])
    finish(ws, "B4")


# ----------------------------------------------------------------------------- Lợi nhuận

PROFIT_HEADER = ["Khoản", "Số tiền (đ)", "% doanh thu", "Số đơn", "Nguồn số liệu"]
#: the profit block's first row: revenue, then one row per cost, then the profit and the margin
PROFIT_COSTS = (
    ("fees", "− Phí Shopee (phí cố định, dịch vụ, thanh toán)", "fees_real_pct", "file thu nhập"),
    ("cogs", "− Giá vốn (đã trừ VAT đầu vào)", "cogs_real_pct", "giá vốn shop nhập"),
    ("packaging", "− Đóng gói", "packaging_real_pct", "Thông số shop"),
    ("commission", "− Hoa hồng tiếp thị liên kết (AFF)", None, "file thu nhập / đơn hàng"),
    ("shipping_other", "− Vận chuyển shop chịu và chi phí khác trên sàn", None, "file thu nhập"),
    ("ads", "− Quảng cáo (mọi ngày, cả ngày không có đơn)", None, "Báo cáo DVHT / Connector"),
    ("other_marketing", "− Chi phí marketing khác", None, "Thông số shop"),
)


def _source(real_pct: float | None, what: str) -> str:
    if real_pct is None:
        return what
    if real_pct >= 100:
        return f"Thật ({what})"
    if real_pct <= 0:
        return "Giả định — chưa nhập" if what == "Thông số shop" else f"Giả định ({what})"
    return f"Thật {real_pct:.1f} % ({what}), còn lại giả định".replace(".", ",")


def _profit(wb: Workbook, data: TongQuanData, b: ProfitBridge) -> None:
    """Doanh thu, then Lợi nhuận bán hàng trên sàn line by line (see ``profit_bridge``)."""
    ws = wb.create_sheet(SHEET_PROFIT)
    put(ws, 1, 1, title_of(data)).font = TITLE
    header(ws, 3, PROFIT_HEADER)
    r = 4
    put(ws, r, 1, "DOANH THU", bold=True)
    # GMV - cancelled - in transit - refunds (only while the headline is Shopee's own total,
    # which still holds them; the sale lines leave them out) = the delivered orders' GMV
    refunds = (
        (("− Đơn hoàn tiền / trả hàng", -b.refund_gmv, b.refund_orders, "file đơn hàng"),)
        if b.refunds_in_gmv
        else ()
    )
    top = (
        ("GMV (giá trị đơn đặt)", b.gmv, b.orders, "Shopee"),
        ("− Đơn hủy", -b.lost_gmv, b.lost_orders, "file đơn hàng"),
        ("− Đơn đang giao", -b.pending_gmv, b.pending_orders, "file đơn hàng"),
        *refunds,
        ("Doanh thu đơn thành công (khách trả, gồm VAT)", b.paid_success, b.success_orders,
         "file đơn hàng"),
        # the same figure as the Tổng quan sheet's ưu đãi row (every order line of the window)
        ("Ưu đãi của shop (thuộc chi phí marketing)",
         data.now.offer_cost if data.now.offer_cost is not None else b.offers, None,
         "file đơn hàng"),
        ("Thực nhận từ Shopee (đơn có file thu nhập)", b.payout, b.payout_orders, "file thu nhập"),
    )  # fmt: skip
    for label, value, orders, src in top:
        r += 1
        put(ws, r, 1, label)
        put(ws, r, 2, _dash(value), MONEY)
        put(ws, r, 4, DASH if orders is None else orders, INT)
        put(ws, r, 5, src)
    r += 2
    share = (
        "" if b.known_gmv_share_pct is None
        else f", {b.known_gmv_share_pct:.1f} % GMV".replace(".", ",")
    )  # fmt: skip
    put(
        ws, r, 1, f"LỢI NHUẬN BÁN HÀNG TRÊN SÀN ({b.known_orders} đơn đủ chi phí{share})", bold=True
    )
    r += 1
    base = r
    put(ws, r, 1, "Doanh thu tính lợi nhuận (sau VAT đầu ra)")
    put(ws, r, 2, b.revenue, MONEY)
    put(ws, r, 3, 1.0, PCT)
    put(ws, r, 4, b.known_orders, INT)
    put(ws, r, 5, f"đã trừ VAT đầu ra {b.vat_output:,.0f}đ".replace(",", "."))
    for key, label, pct_key, what in PROFIT_COSTS:
        value = getattr(b, key)
        if key == "other_marketing" and not value:
            continue
        r += 1
        put(ws, r, 1, label)
        put(ws, r, 2, _dash(None if value is None else -value if value else 0.0), MONEY)
        put(ws, r, 3, f'=IFERROR(-B{r}/B${base},"{DASH}")', PCT)
        src = _source(getattr(b, pct_key) if pct_key else None, what)
        if key == "ads" and b.ads_no_order_days:
            src += f"; gồm {b.ads_no_order_days:,.0f}đ ngày không có đơn".replace(",", ".")
        put(ws, r, 5, src)
    last_cost = r
    r += 1
    profit = r
    put(ws, r, 1, "Lợi nhuận bán hàng trên sàn", bold=True)
    ok = b.profit is not None and b.ads is not None
    put(ws, r, 2, f"=SUM(B{base}:B{last_cost})" if ok else DASH, MONEY, bold=True)
    r += 1
    put(ws, r, 1, MARGIN_LABEL, bold=True)
    put(ws, r, 2, f'=IFERROR(B{profit}/B{base},"{DASH}")' if ok else DASH, PCT, bold=True)
    r += 2
    notes = (
        "Lợi nhuận bán hàng trên sàn = doanh thu − các chi phí trên; bằng lợi nhuận trên màn hình "
        "Tổng quan. Lợi nhuận ròng (chi phí ngoài sàn) do shop tự quản lý.",
        "Chỉ tính đơn đã giao có đủ chi phí; đơn hủy, đơn đang hoàn và đơn chưa có kết quả "
        "không vào lợi nhuận.",
        "Giá bán và giá vốn đã gồm VAT: doanh thu trừ VAT đầu ra, giá vốn trừ VAT đầu vào.",
    )
    for i, text_ in enumerate(notes):
        put(ws, r + i, 1, text_)
    widths(ws, [58, 16, 12, 10, 52])
    finish(ws, "B4")


# ----------------------------------------------------------------------------- Theo kênh

CH_FIRST, CH_OFFER, CH_TOTAL = 4, 7, 8  # rows: Organic, Quảng cáo, TTLK = 4..6; Ưu đãi; Tổng
CH_HEADER = [
    "Kênh", "GMV (đ)", "% GMV", "Thay đổi", "Đơn", "AOV (đ)", "Chi phí (đ)", ROI_LABEL,
    "Chi phí / doanh thu", "Lợi nhuận kênh (đ)",
]  # fmt: skip
CH_LABELS = {**CHANNEL_LABELS, "ads": "Quảng cáo (Lưu lượng / Báo cáo DVHT)"}
CH_NOTE = (
    "Lợi nhuận kênh = GMV kênh × biên lợi nhuận của shop trước chi phí marketing "
    "((lợi nhuận + chi phí marketing) ÷ GMV) − chi phí của kênh; dòng Ưu đãi nhận phần ưu đãi "
    "của shop, các dòng cộng lại bằng lợi nhuận của shop. Thay đổi = “—” khi kỳ trước tính kênh "
    "Quảng cáo trên cơ sở khác."
)


def basis_differs(now: Figures, prev: Figures) -> bool:
    """The two periods read the Quảng cáo GMV from different bases (so Organic, which is what is
    left, is not comparable either)."""
    return (
        now.ads_basis is not None
        and prev.ads_basis is not None
        and (now.ads_basis != prev.ads_basis)
    )


def _channels(wb: Workbook, data: TongQuanData) -> None:
    ws = wb.create_sheet(SHEET_CHANNEL)
    put(ws, 1, 1, title_of(data)).font = TITLE
    header(ws, 3, CH_HEADER)
    prev_total = _sum(*(data.prev.channel(k).gmv for k in CHANNELS))
    differs = basis_differs(data.now, data.prev)
    ov = f"'{SHEET_OVERVIEW}'!"
    margin0 = f"({ov}$B${OV['profit']}+{ov}$B${OV['cost']})/{ov}$B${OV['gmv']}"
    for i, key in enumerate(CHANNELS):
        r = CH_FIRST + i
        ch = data.now.channel(key)
        put(ws, r, 1, CH_LABELS[key])
        put(ws, r, 2, _dash(ch.gmv), MONEY)
        comparable = not (differs and key in ("organic", "ads"))
        put(ws, r, 4, _change_vs(f"B{r}", data.prev.channel(key).gmv) if comparable else DASH, PCT)
        put(ws, r, 5, _dash(ch.orders), INT)
        put(
            ws, r, 7, ch.cost if ch.cost is not None else (0.0 if key == "organic" else DASH), MONEY
        )
        put(
            ws, r, 10,
            f'=IF(AND(ISNUMBER({ov}$B${OV["profit"]}),ISNUMBER(B{r})),'
            f'IFERROR(B{r}*{margin0}-N(G{r}),"{DASH}"),"{DASH}")',
            MONEY,
        )  # fmt: skip
        has_cost = key != "organic"
        put(
            ws,
            r,
            8,
            f'=IF(ISNUMBER(G{r}),IFERROR(J{r}/G{r},"{DASH}"),"{DASH}")' if has_cost else DASH,
            POINTS,
        )
    put(ws, CH_OFFER, 1, "Ưu đãi của shop (thuộc chi phí marketing)")
    put(ws, CH_OFFER, 2, DASH)
    put(ws, CH_OFFER, 7, _dash(data.now.offer_cost), MONEY)
    put(ws, CH_OFFER, 10, f'=IF(ISNUMBER(G{CH_OFFER}),-G{CH_OFFER},"{DASH}")', MONEY)
    put(ws, CH_TOTAL, 1, "Tổng", bold=True)
    for c, fmt in ((2, MONEY), (5, INT), (7, MONEY), (10, MONEY)):
        L = col(c)
        last = (
            CH_OFFER if c in (7, 10) else CH_OFFER - 1
        )  # the cost and profit rows take the offers
        put(ws, CH_TOTAL, c, f"=SUM({L}{CH_FIRST}:{L}{last})", fmt, bold=True)
    put(ws, CH_TOTAL, 4, DASH if differs else _change_vs(f"B{CH_TOTAL}", prev_total), PCT)
    put(ws, CH_TOTAL, 8, f"={ov}B{OV['roi']}", POINTS)
    for r in (*range(CH_FIRST, CH_OFFER), CH_TOTAL):
        put(ws, r, 3, f'=IFERROR(B{r}/B${CH_TOTAL},"{DASH}")', PCT)
        put(ws, r, 6, f'=IFERROR(B{r}/E{r},"{DASH}")', MONEY)
    for r in (*range(CH_FIRST, CH_OFFER + 1), CH_TOTAL):
        put(ws, r, 9, f'=IFERROR(G{r}/{ov}$B${OV["gmv"]},"{DASH}")', PCT)
    put(ws, CH_TOTAL + 2, 1, CH_NOTE)
    widths(ws, {1: 38}, 14)
    finish(ws, "B4")


# ----------------------------------------------------------------------------- Theo ngày

DAY_HEADER = [
    "Ngày", "GMV Organic", "GMV Quảng cáo", "GMV TTLK", "GMV", "Đơn", COST_LABEL, "Lợi nhuận",
]  # fmt: skip
DAY_FIRST = 4  # first data row


def _days(wb: Workbook, data: TongQuanData) -> None:
    ws = wb.create_sheet(SHEET_DAY)
    put(ws, 1, 1, title_of(data)).font = TITLE
    header(ws, 3, DAY_HEADER)
    r = DAY_FIRST - 1
    for r, d in enumerate(data.days, start=DAY_FIRST):
        put(ws, r, 1, d.day, DATE)
        for i, key in enumerate(CHANNELS):
            put(ws, r, 2 + i, _dash(d.gmv.get(key)), MONEY)
        gmv = d.total_gmv if d.total_gmv is not None else f"=SUM(B{r}:D{r})"
        put(ws, r, 5, gmv, MONEY)
        orders = d.total_orders if d.total_orders is not None else _sum(*d.orders.values())
        put(ws, r, 6, _dash(orders), INT)
        put(ws, r, 7, _dash(_sum(d.ads_cost, d.aff_cost, d.offer_cost)), MONEY)
        put(ws, r, 8, _dash(d.profit), MONEY)
    total = r + 1
    put(ws, total, 1, "Tổng", bold=True)
    first, last = DAY_FIRST, max(r, DAY_FIRST)
    for c in range(2, 9):
        L = col(c)
        put(ws, total, c, f"=SUM({L}{first}:{L}{last})", INT if c == 6 else MONEY, bold=True)
    widths(ws, {1: 12}, 15)
    finish(ws, "B4")


# ----------------------------------------------------------------------------- Theo sản phẩm

P_HEADER = [
    "Mã SP", "Sản phẩm", "GMV", "Thay đổi", "Lợi nhuận", "% GMV Organic", "% GMV Quảng cáo",
    "% GMV TTLK", ROI_LABEL, "% doanh thu shop", "% lợi nhuận shop", "Chi phí / doanh thu SP",
    f"% {COST_LABEL.lower()} shop",
]  # fmt: skip
#: hidden helper columns the formulas read: GMV Organic, Quảng cáo, TTLK (they add up to the GMV),
#: Chi phí marketing
P_HELP = ["O", "P", "Q", "R"]
P_HELP_HEADER = ["GMV Organic", "GMV Quảng cáo", "GMV TTLK", COST_LABEL]
P_HELP_COL = 15
P_FIRST = 4


def _product_formulas(ws, r: int, total: int, gmv: float | str | None = None) -> None:
    """GMV = the product's own order GMV when known (``gmv``), else the sum of its channels."""
    put(ws, r, 3, gmv if gmv is not None else f"=SUM(O{r}:Q{r})", MONEY)
    for c, h in ((6, "O"), (7, "P"), (8, "Q")):
        put(ws, r, c, f'=IFERROR({h}{r}/C{r},"{DASH}")', PCT)
    put(ws, r, 9, f'=IFERROR(E{r}/R{r},"{DASH}")', POINTS)
    put(ws, r, 10, f'=IFERROR(C{r}/C${total},"{DASH}")', PCT)
    put(ws, r, 11, f'=IFERROR(E{r}/E${total},"{DASH}")', PCT)
    put(ws, r, 12, f'=IFERROR(R{r}/C{r},"{DASH}")', PCT)
    put(ws, r, 13, f'=IFERROR(R{r}/R${total},"{DASH}")', PCT)


def _products(wb: Workbook, data: TongQuanData) -> None:
    ws = wb.create_sheet(SHEET_PRODUCT)
    put(ws, 1, 1, title_of(data)).font = TITLE
    header(ws, 3, P_HEADER)
    header(ws, 3, P_HELP_HEADER, P_HELP_COL)
    total = P_FIRST + len(data.products)
    r = P_FIRST - 1
    for r, p in enumerate(data.products, start=P_FIRST):
        put(ws, r, 1, p.product_id)
        put(ws, r, 2, p.name or (SHOP_ROW_NAME if p.product_id == SHOP_ROW_LABEL else ""))
        prev_gmv = p.prev.gmv if p.prev.gmv is not None else gmv_of(p.prev)
        put(ws, r, 4, _change_vs(f"C{r}", prev_gmv), PCT)
        put(ws, r, 5, _dash(p.now.profit), MONEY)
        for c, key in zip((15, 16, 17), CHANNELS, strict=True):
            put(ws, r, c, _dash(p.now.channel(key).gmv), MONEY)
        put(ws, r, 18, cost_of(p.now), MONEY)
        _product_formulas(ws, r, total, p.now.gmv)
    last = max(r, P_FIRST)
    put(ws, total, 1, "Tổng", bold=True)
    for c in (5, 15, 16, 17, 18):
        L = col(c)
        put(ws, total, c, f"=SUM({L}{P_FIRST}:{L}{last})", MONEY, bold=True)
    prev_total = _sum(
        *((p.prev.gmv if p.prev.gmv is not None else gmv_of(p.prev)) for p in data.products)
    )
    put(ws, total, 4, _change_vs(f"C{total}", prev_total), PCT)
    _product_formulas(ws, total, total, f"=SUM(C{P_FIRST}:C{last})")
    widths(ws, {1: 16, 2: 44}, 15)
    _hide(ws, *P_HELP)
    finish(ws, "C4")


# ----------------------------------------------------------------------------- Theo SKU

SKU_HEADER = [
    "Mã SKU", "Phân loại", "Sản phẩm", "Số lượng bán", "Doanh thu", "Lợi nhuận", "Biên",
    "Tồn kho", "Hệ số combo", "Bán / ngày", "Còn ~ (ngày)",
    f"Cần nhập (= bán/ngày × ({LEAD_DAYS} + {COVER_DAYS}) − tồn kho, tối thiểu 0)",
]  # fmt: skip
SKU_FIRST = 4
#: the row that brings Σ Doanh thu to the period's GMV (returns, lines without a SKU)
SKU_GAP_LABEL = "Chênh lệch: doanh thu dòng đơn khác Doanh số Shopee"


def _skus(wb: Workbook, data: TongQuanData) -> None:
    ws = wb.create_sheet(SHEET_SKU)
    put(ws, 1, 1, title_of(data)).font = TITLE
    header(ws, 3, SKU_HEADER)
    r = SKU_FIRST - 1
    for r, k in enumerate(data.skus, start=SKU_FIRST):
        put(ws, r, 1, k.sku)
        put(ws, r, 2, k.variation)
        put(ws, r, 3, k.product_name)
        for c, v, fmt in (
            (4, k.units, INT), (5, k.revenue, MONEY), (6, k.profit, MONEY), (8, k.stock, INT),
            (9, k.combo, INT), (10, k.rate, "#,##0.0"), (11, k.days_left, INT),
        ):  # fmt: skip
            put(ws, r, c, DASH if v is None and c in (8, 10, 11) else v, fmt)
        _sku_formulas(ws, r)
    if data.skus:
        r += 1
        put(ws, r, 1, SKU_GAP_LABEL)
        put(ws, r, 5, f"='{SHEET_OVERVIEW}'!B{OV['gmv']}-SUM(E{SKU_FIRST}:E{r - 1})", MONEY)
    total, last = r + 1, max(r, SKU_FIRST)
    put(ws, total, 1, "Tổng", bold=True)
    for c, fmt in ((4, INT), (5, MONEY), (6, MONEY), (8, INT)):
        L = col(c)
        put(ws, total, c, f"=SUM({L}{SKU_FIRST}:{L}{last})", fmt, bold=True)
    _sku_formulas(ws, total, need=False)
    widths(ws, {1: 18, 2: 22, 3: 38, 12: 30}, 15)
    finish(ws, "D4")


def _sku_formulas(ws, r: int, need: bool = True) -> None:
    if need:
        put(
            ws,
            r,
            12,
            f'=IF(AND(ISNUMBER(J{r}),ISNUMBER(H{r})),MAX(0,J{r}*({LEAD_DAYS}+{COVER_DAYS})-H{r}),"{DASH}")',
            INT,
        )
    put(ws, r, 7, f'=IF(AND(F{r}<>"",E{r}<>0),F{r}/E{r},"")', PCT)


# ----------------------------------------------------------------------------- Tất cả shop

#: the overview row -> its metric id in the registry (the row is summable when the registry says so)
ROW_METRIC = {
    "gmv": "gmv", "orders": "orders", "profit": "profit", "ads": "cost_ads",
    "aff": "cost_affiliate", "offer": "cost_offers", "cost": "cost_marketing", "aov": "aov",
    "roi": "roi", "margin": "margin",
}  # fmt: skip
#: ratio rows: never summed or averaged; the Tổng column recomputes them from its own parts
RATIO_ROWS = ("aov", "roi", "margin")
MULTI_FIRST = 4  # first metric row of the all-shops sheet


def summable_row(key: str) -> bool:
    if key == "base":  # the margin's base is a component (a sum), not a metric
        return True
    return key not in RATIO_ROWS and METRICS[ROW_METRIC[key]].summable


def title_multi(datas: list[TongQuanData]) -> str:
    first = datas[0]
    return f"TỔNG QUAN — Tất cả shop · {_d(first.start)}–{_d(first.end)}"


def file_name_multi(datas: list[TongQuanData]) -> str:
    return f"Juli_TongQuan_TatCaShop_{datas[0].start:%d%m%Y}_{datas[0].end:%d%m%Y}.xlsx"


def _multi(wb: Workbook, datas: list[TongQuanData]) -> None:
    """One sheet: a column per shop and a Tổng column. Tổng = the SUM of the shops for a metric the
    registry marks summable; a ratio (AOV, ROI) is recomputed from the Tổng parts, never averaged;
    anything else stays empty (per shop only)."""
    ws = wb.create_sheet(SHEET_OVERVIEW)
    put(ws, 1, 1, title_multi(datas)).font = TITLE
    n = len(datas)
    total_col = 2 + n
    header(ws, 3, ["Chỉ số", *(f"{d.shop_name} ({d.platform})" for d in datas), "Tổng"])
    labels = {
        "gmv": ("GMV (đ)", MONEY), "orders": ("Đơn", INT), "aov": ("AOV (đ)", MONEY),
        "profit": ("Lợi nhuận (đ)", MONEY),
        "ads": ("Chi phí quảng cáo (Báo cáo DVHT) (đ)", MONEY),
        "aff": ("Chi phí tiếp thị liên kết (đ)", MONEY), "offer": (OFFER_LABEL, MONEY),
        "cost": (f"{COST_LABEL} (đ)", MONEY),
        "roi": (f"{ROI_LABEL} (lần)", POINTS), "margin": (MARGIN_LABEL, PCT),
        "base": (f"{BASE_LABEL} (đ)", MONEY),
    }  # fmt: skip
    values = [_overview_values(d.now) for d in datas]
    row = {k: OV[k] for k in OV}  # the single-shop layout: same rows
    for key, (label, fmt) in labels.items():
        r = row[key]
        put(ws, r, 1, label)
        for j in range(n):
            L = col(2 + j)
            if key == "aov":
                v: object = f'=IFERROR({L}{row["gmv"]}/{L}{row["orders"]},"")'
            elif key == "cost":
                v = f"=SUM({L}{row['ads']}:{L}{row['offer']})"
            elif key == "roi":
                v = f'=IFERROR({L}{row["profit"]}/{L}{row["cost"]},"")'
            elif key == "margin":
                v = f'=IFERROR({L}{row["profit"]}/{L}{row["base"]},"")'
            else:
                v = values[j][key]
            put(ws, r, 2 + j, v, fmt)
        T, first, last = col(total_col), col(2), col(1 + n)
        if key == "aov":
            total: object = f'=IFERROR({T}{row["gmv"]}/{T}{row["orders"]},"")'
        elif key == "roi":
            total = f'=IFERROR({T}{row["profit"]}/{T}{row["cost"]},"")'
        elif key == "margin":
            total = f'=IFERROR({T}{row["profit"]}/{T}{row["base"]},"")'
        elif summable_row(key):
            total = f"=SUM({first}{r}:{last}{r})"
        else:
            total = None
        put(ws, r, total_col, total, fmt, bold=True)
    # GMV by channel: summable like the GMV it splits
    for i, key in enumerate(CHANNELS):
        r = OV["base"] + 1 + i
        put(ws, r, 1, f"GMV {CHANNEL_LABELS[key]} (đ)")
        for j, d in enumerate(datas):
            put(ws, r, 2 + j, d.now.channel(key).gmv, MONEY)
        put(ws, r, total_col, f"=SUM({col(2)}{r}:{col(1 + n)}{r})", MONEY, bold=True)
    widths(ws, {1: 40}, 20)
    finish(ws, "B4")


def build_multi(datas: list[TongQuanData]) -> Workbook:
    wb = new_workbook()
    _multi(wb, datas)
    for ws in wb.worksheets:
        for r in ws.iter_rows():
            for c in r:
                if c.font is None or c.font.name != "Arial":
                    c.font = FONT
    return wb


def build_multi_bytes(datas: list[TongQuanData]) -> bytes:
    return save_bytes(build_multi(datas))


def build(data: TongQuanData) -> Workbook:
    wb = new_workbook()
    _overview(wb, data)
    if data.bridge is not None:
        _profit(wb, data, data.bridge)
    _channels(wb, data)
    _days(wb, data)
    _products(wb, data)
    _skus(wb, data)
    title = title_of(data)
    rs.months_sheet(wb, title, data.months)
    rs.koc_sheet(wb, title, data.koc, data.affiliate_share or rs.AffiliateShare())
    rs.analysis_sheet(wb, title, data.analysis)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.font is None or c.font.name != "Arial":
                    c.font = FONT
    return wb


def build_bytes(data: TongQuanData) -> bytes:
    return save_bytes(build(data))
