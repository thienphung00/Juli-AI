"""The Tổng quan export: a pure builder, plain dataclasses in, an openpyxl Workbook / bytes out.

Sheets: "Tổng quan" (the shop's numbers, this period vs the previous, with the Kế hoạch baseline
and goal), "Theo kênh" (Organic / Quảng cáo / Tiếp thị liên kết), "Theo ngày", "Theo sản phẩm",
"Theo SKU".

Every number is an input; the ratios (AOV, CTR, CTOR, % GMV, ROI, Thay đổi, % đạt) and the
totals are Excel formulas over the cells of the sheet, so the file recomputes when a figure is
edited. ``fullCalcOnLoad`` is set (no cached values are stored). Only Excel-2007 functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from openpyxl import Workbook

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

CHANNELS = ("organic", "ads", "affiliate")
CHANNEL_LABELS = {"organic": "Organic", "ads": "Quảng cáo", "affiliate": "Tiếp thị liên kết"}
SHOP_ROW_LABEL = "Cả shop"

SHEET_OVERVIEW = "Tổng quan"
SHEET_CHANNEL = "Theo kênh"
SHEET_DAY = "Theo ngày"
SHEET_PRODUCT = "Theo sản phẩm"
SHEET_SKU = "Theo SKU"


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
    """One scope (shop or product) over one period. ``baseline_*`` / ``goal_*`` = the Kế hoạch
    baseline and goal (running plans) for the same days; ``None`` when no card is running."""

    channels: dict[str, Channel] = field(default_factory=dict)
    gmv: float | None = None
    orders: float | None = None
    profit: float | None = None
    ads_cost: float | None = None
    aff_cost: float | None = None
    offer_cost: float | None = None
    baseline_gmv: float | None = None
    goal_gmv: float | None = None
    baseline_profit: float | None = None
    goal_profit: float | None = None

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
    baseline_gmv: float | None = None
    goal_gmv: float | None = None
    baseline_profit: float | None = None
    goal_profit: float | None = None


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
    units_goal: float | None = None
    units: float | None = None
    revenue_goal: float | None = None
    revenue: float | None = None
    profit_goal: float | None = None
    profit: float | None = None
    stock: float | None = None
    need: float | None = None  # units still to sell until the end of the period


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


def _d(x: date) -> str:
    return f"{x:%d/%m/%Y}"


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


def _change_vs(ref: str, prev: float | None) -> str | None:
    """Thay đổi = this period's cell / the previous period's value - 1; the previous value sits
    inside the formula (the file does not carry a "Kỳ trước" column)."""
    return None if prev is None else f'=IFERROR({ref}/{float(prev)!r}-1,"")'


def _hide(ws, *letters: str) -> None:
    for letter in letters:
        ws.column_dimensions[letter].hidden = True


def gmv_of(fig: Figures) -> float | None:
    """GMV of a scope = Σ its channels' GMV (what Theo kênh / Theo sản phẩm show)."""
    return _sum(*(fig.channel(k).gmv for k in CHANNELS))


def cost_of(fig: Figures) -> float | None:
    return _sum(fig.ads_cost, fig.aff_cost, fig.offer_cost)


# ----------------------------------------------------------------------------- Tổng quan

OVERVIEW_HEADER = ["Chỉ số", "Kỳ này", "Thay đổi", "Mục tiêu", "% đạt"]
OV = {  # row of each metric on the "Tổng quan" sheet
    "gmv": 4, "orders": 5, "aov": 6, "profit": 7, "ads": 8, "aff": 9, "offer": 10, "cost": 11,
    "roi": 12,
}  # fmt: skip


def _overview_values(fig: Figures) -> dict[str, float | None]:
    cost = _sum(fig.ads_cost, fig.aff_cost, fig.offer_cost)
    return {
        "gmv": fig.gmv, "orders": fig.orders, "aov": _div(fig.gmv, fig.orders),
        "profit": fig.profit, "ads": fig.ads_cost, "aff": fig.aff_cost, "offer": fig.offer_cost,
        "cost": cost or 0.0, "roi": None if fig.profit is None else _div(fig.profit, cost),
    }  # fmt: skip


def _overview(wb: Workbook, data: TongQuanData) -> None:
    ws = wb.create_sheet(SHEET_OVERVIEW)
    put(ws, 1, 1, title_of(data)).font = TITLE
    header(ws, 3, OVERVIEW_HEADER)
    rows = [
        ("gmv", "GMV (đ)", MONEY), ("orders", "Đơn", INT), ("aov", "AOV (đ)", MONEY),
        ("profit", "Lợi nhuận (đ)", MONEY),
        ("ads", "Chi phí quảng cáo (Báo cáo DVHT) (đ)", MONEY),
        ("aff", "Chi phí tiếp thị liên kết (đ)", MONEY), ("offer", "Chi phí ưu đãi (đ)", MONEY),
        ("cost", "Tổng chi phí (đ)", MONEY), ("roi", "ROI", POINTS),
    ]  # fmt: skip
    prev = _overview_values(data.prev)
    for key, label, fmt in rows:
        r = OV[key]
        put(ws, r, 1, label)
        if key == "aov":
            v: object = f'=IFERROR(B{OV["gmv"]}/B{OV["orders"]},"")'
        elif key == "cost":
            v = f"=SUM(B{OV['ads']}:B{OV['offer']})"
        elif key == "roi":
            v = f'=IFERROR(B{OV["profit"]}/B{OV["cost"]},"")'
        else:
            v = _overview_values(data.now)[key]
        put(ws, r, 2, v, fmt)
        put(ws, r, 3, _change_vs(f"B{r}", prev[key]), PCT)
    for key, goal in (("gmv", data.now.goal_gmv), ("profit", data.now.goal_profit)):
        r = OV[key]
        put(ws, r, 4, goal, MONEY)
        put(ws, r, 5, f'=IFERROR(B{r}/D{r},"")', PCT)
    widths(ws, [40, 16, 12, 16, 10])
    finish(ws, "B4")


# ----------------------------------------------------------------------------- Theo kênh

CH_FIRST, CH_TOTAL = 4, 7  # rows: Organic, Quảng cáo, TTLK = 4..6; Tổng = 7
CH_HEADER = ["Kênh", "GMV (đ)", "% GMV", "Thay đổi", "Đơn", "AOV (đ)", "Chi phí (đ)", "ROI"]
CH_LABELS = {**CHANNEL_LABELS, "ads": "Quảng cáo (Lưu lượng / Báo cáo DVHT)"}


def _channels(wb: Workbook, data: TongQuanData) -> None:
    ws = wb.create_sheet(SHEET_CHANNEL)
    put(ws, 1, 1, title_of(data)).font = TITLE
    header(ws, 3, CH_HEADER)
    last = CH_TOTAL - 1
    prev_total = _sum(*(data.prev.channel(k).gmv for k in CHANNELS))
    for i, key in enumerate(CHANNELS):
        r = CH_FIRST + i
        ch = data.now.channel(key)
        put(ws, r, 1, CH_LABELS[key])
        put(ws, r, 2, ch.gmv, MONEY)
        put(ws, r, 4, _change_vs(f"B{r}", data.prev.channel(key).gmv), PCT)
        put(ws, r, 5, ch.orders, INT)
        put(ws, r, 7, ch.cost, MONEY)
    put(ws, CH_TOTAL, 1, "Tổng", bold=True)
    for c, fmt in ((2, MONEY), (5, INT), (7, MONEY)):
        L = col(c)
        put(ws, CH_TOTAL, c, f"=SUM({L}{CH_FIRST}:{L}{last})", fmt, bold=True)
    put(ws, CH_TOTAL, 4, _change_vs(f"B{CH_TOTAL}", prev_total), PCT)
    put(ws, CH_TOTAL, 8, f"='{SHEET_OVERVIEW}'!B{OV['roi']}", POINTS)
    for r in range(CH_FIRST, CH_TOTAL + 1):
        put(ws, r, 3, f'=IFERROR(B{r}/B${CH_TOTAL},"")', PCT)
        put(ws, r, 6, f'=IFERROR(B{r}/E{r},"")', MONEY)
    widths(ws, {1: 38}, 14)
    finish(ws, "B4")


# ----------------------------------------------------------------------------- Theo ngày

DAY_HEADER = [
    "Ngày", "GMV Organic", "GMV Quảng cáo", "GMV TTLK", "GMV", "Đơn", "Chi phí", "Lợi nhuận",
    "GMV mục tiêu", "Lợi nhuận mục tiêu",
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
            put(ws, r, 2 + i, d.gmv.get(key), MONEY)
        put(ws, r, 5, f"=SUM(B{r}:D{r})", MONEY)
        put(ws, r, 6, _sum(*d.orders.values()), INT)
        put(ws, r, 7, _sum(d.ads_cost, d.aff_cost, d.offer_cost), MONEY)
        put(ws, r, 8, d.profit, MONEY)
        put(ws, r, 9, d.goal_gmv, MONEY)
        put(ws, r, 10, d.goal_profit, MONEY)
    total = r + 1
    put(ws, total, 1, "Tổng", bold=True)
    first, last = DAY_FIRST, max(r, DAY_FIRST)
    for c in range(2, 11):
        L = col(c)
        put(ws, total, c, f"=SUM({L}{first}:{L}{last})", INT if c == 6 else MONEY, bold=True)
    widths(ws, {1: 12}, 15)
    finish(ws, "B4")


# ----------------------------------------------------------------------------- Theo sản phẩm

P_HEADER = [
    "Mã SP", "Sản phẩm", "GMV", "Thay đổi", "GMV mục tiêu", "% đạt", "Lợi nhuận",
    "Lợi nhuận mục tiêu", "% đạt", "% GMV Organic", "% GMV Quảng cáo", "% GMV TTLK", "ROI",
]  # fmt: skip
#: hidden helper columns the % GMV / ROI formulas read: GMV Organic, Quảng cáo, TTLK, Tổng chi phí
P_HELP = ["N", "O", "P", "Q"]
P_HELP_HEADER = ["GMV Organic", "GMV Quảng cáo", "GMV TTLK", "Tổng chi phí"]
P_FIRST = 4


def _product_formulas(ws, r: int) -> None:
    put(ws, r, 3, f"=SUM(N{r}:P{r})", MONEY)
    put(ws, r, 6, f'=IFERROR(C{r}/E{r},"")', PCT)
    put(ws, r, 9, f'=IFERROR(G{r}/H{r},"")', PCT)
    for c, h in ((10, "N"), (11, "O"), (12, "P")):
        put(ws, r, c, f'=IFERROR({h}{r}/C{r},"")', PCT)
    put(ws, r, 13, f'=IFERROR(G{r}/Q{r},"")', POINTS)


def _products(wb: Workbook, data: TongQuanData) -> None:
    ws = wb.create_sheet(SHEET_PRODUCT)
    put(ws, 1, 1, title_of(data)).font = TITLE
    header(ws, 3, P_HEADER)
    header(ws, 3, P_HELP_HEADER, 14)
    r = P_FIRST - 1
    for r, p in enumerate(data.products, start=P_FIRST):
        put(ws, r, 1, p.product_id)
        put(ws, r, 2, p.name)
        put(ws, r, 4, _change_vs(f"C{r}", gmv_of(p.prev)), PCT)
        put(ws, r, 5, p.now.goal_gmv, MONEY)
        put(ws, r, 7, p.now.profit, MONEY)
        put(ws, r, 8, p.now.goal_profit, MONEY)
        for c, key in zip((14, 15, 16), CHANNELS, strict=True):
            put(ws, r, c, p.now.channel(key).gmv, MONEY)
        put(ws, r, 17, cost_of(p.now), MONEY)
        _product_formulas(ws, r)
    total, last = r + 1, max(r, P_FIRST)
    put(ws, total, 1, "Tổng", bold=True)
    for c in (5, 7, 8, 14, 15, 16, 17):
        L = col(c)
        put(ws, total, c, f"=SUM({L}{P_FIRST}:{L}{last})", MONEY, bold=True)
    prev_total = _sum(*(gmv_of(p.prev) for p in data.products))
    put(ws, total, 4, _change_vs(f"C{total}", prev_total), PCT)
    _product_formulas(ws, total)
    widths(ws, {1: 16, 2: 38}, 15)
    _hide(ws, *P_HELP)
    finish(ws, "C4")


# ----------------------------------------------------------------------------- Theo SKU

SKU_HEADER = [
    "Mã SKU", "Phân loại", "Sản phẩm", "Số lượng bán mục tiêu", "Số lượng bán thực tế", "% đạt",
    "Doanh thu mục tiêu", "Doanh thu thực tế", "% đạt", "Lợi nhuận mục tiêu",
    "Lợi nhuận thực tế", "% đạt", "Biên", "Tồn kho", "Cần bán đến cuối kỳ", "Cần nhập",
]  # fmt: skip
SKU_FIRST = 4


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
            (4, k.units_goal, INT), (5, k.units, INT), (7, k.revenue_goal, MONEY),
            (8, k.revenue, MONEY), (10, k.profit_goal, MONEY), (11, k.profit, MONEY),
            (14, k.stock, INT), (15, k.need, INT),
        ):  # fmt: skip
            put(ws, r, c, v, fmt)
        _sku_formulas(ws, r)
    total, last = r + 1, max(r, SKU_FIRST)
    put(ws, total, 1, "Tổng", bold=True)
    for c, fmt in ((4, INT), (5, INT), (7, MONEY), (8, MONEY), (10, MONEY), (11, MONEY),
                   (14, INT), (15, INT)):  # fmt: skip
        L = col(c)
        put(ws, total, c, f"=SUM({L}{SKU_FIRST}:{L}{last})", fmt, bold=True)
    _sku_formulas(ws, total)
    widths(ws, {1: 18, 2: 22, 3: 38}, 15)
    finish(ws, "D4")


def _sku_formulas(ws, r: int) -> None:
    for c, a, g in ((6, "E", "D"), (9, "H", "G"), (12, "K", "J")):
        put(ws, r, c, f'=IF(AND({g}{r}<>"",{g}{r}<>0),{a}{r}/{g}{r},"")', PCT)
    put(ws, r, 13, f'=IF(AND(K{r}<>"",H{r}<>0),K{r}/H{r},"")', PCT)
    put(ws, r, 16, f'=IF(O{r}="","",MAX(0,O{r}-N{r}))', INT)


def build(data: TongQuanData) -> Workbook:
    wb = new_workbook()
    _overview(wb, data)
    _channels(wb, data)
    _days(wb, data)
    _products(wb, data)
    _skus(wb, data)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.font is None or c.font.name != "Arial":
                    c.font = FONT
    return wb


def build_bytes(data: TongQuanData) -> bytes:
    return save_bytes(build(data))
