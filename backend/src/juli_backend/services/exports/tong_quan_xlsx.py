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


def _change(ref_now: str, ref_prev: str) -> str:
    return f'=IFERROR({ref_now}/{ref_prev}-1,"")'


# ----------------------------------------------------------------------------- Tổng quan

OVERVIEW_HEADER = [
    "Chỉ số",
    "Kỳ này",
    "Kỳ trước",
    "Thay đổi",
    "Nền",
    "Mục tiêu",
    "Thực tế",
    "% đạt",
]
OV = {  # row of each metric on the "Tổng quan" sheet
    "gmv": 4, "orders": 5, "aov": 6, "profit": 7, "ads": 8, "aff": 9, "offer": 10, "cost": 11,
    "roi": 12,
}  # fmt: skip


def _overview(wb: Workbook, data: TongQuanData) -> None:
    ws = wb.create_sheet(SHEET_OVERVIEW)
    put(ws, 1, 1, title_of(data)).font = TITLE
    header(ws, 3, OVERVIEW_HEADER)
    rows = [
        ("gmv", "GMV (đ)", MONEY), ("orders", "Đơn", INT), ("aov", "AOV (đ)", MONEY),
        ("profit", "Lợi nhuận (đ)", MONEY), ("ads", "Chi phí quảng cáo (báo cáo DVHT) (đ)", MONEY),
        ("aff", "Chi phí tiếp thị liên kết (đ)", MONEY), ("offer", "Chi phí ưu đãi (đ)", MONEY),
        ("cost", "Tổng chi phí (đ)", MONEY), ("roi", "ROI", POINTS),
    ]  # fmt: skip
    for key, label, fmt in rows:
        r = OV[key]
        put(ws, r, 1, label)
        for c, fig in ((2, data.now), (3, data.prev)):
            L = col(c)
            if key == "aov":
                v: object = f'=IFERROR({L}{OV["gmv"]}/{L}{OV["orders"]},"")'
            elif key == "cost":
                v = f"=SUM({L}{OV['ads']}:{L}{OV['offer']})"
            elif key == "roi":
                v = f'=IFERROR({L}{OV["profit"]}/{L}{OV["cost"]},"")'
            else:
                v = {
                    "gmv": fig.gmv, "orders": fig.orders, "profit": fig.profit,
                    "ads": fig.ads_cost, "aff": fig.aff_cost, "offer": fig.offer_cost,
                }[key]  # fmt: skip
            put(ws, r, c, v, fmt)
        put(ws, r, 4, _change(f"B{r}", f"C{r}"), PCT)
    for key, base, goal in (
        ("gmv", data.now.baseline_gmv, data.now.goal_gmv),
        ("profit", data.now.baseline_profit, data.now.goal_profit),
    ):
        r = OV[key]
        put(ws, r, 5, base, MONEY)
        put(ws, r, 6, goal, MONEY)
        put(ws, r, 7, f"=B{r}", MONEY)
        put(ws, r, 8, f'=IFERROR(G{r}/F{r},"")', PCT)
    widths(ws, [40, 16, 16, 12, 16, 16, 16, 10])
    finish(ws, "B4")


# ----------------------------------------------------------------------------- Theo kênh

CH_FIRST, CH_TOTAL = 5, 8  # rows: Organic, Quảng cáo, TTLK = 5..7; Tổng = 8
CH_NOW, CH_PREV = 2, 11  # first column of the two period blocks (9 columns each)
CH_HEADER = [
    "Lượt xem",
    "Lượt nhấp",
    "CTR",
    "Đơn",
    "CTOR",
    "GMV (đ)",
    "AOV (đ)",
    "% GMV",
    "Chi phí (đ)",
]
CH_CHANGE_GMV, CH_CHANGE_ORDERS = 20, 21


def _channel_block(ws, c0: int, fig: Figures) -> None:
    v, k, ctr, o, ctor, g, aov, share, cost = (col(c0 + i) for i in range(9))
    last = CH_TOTAL - 1
    for i, key in enumerate(CHANNELS):
        r = CH_FIRST + i
        ch = fig.channel(key)
        put(ws, r, c0, ch.views, INT)
        put(ws, r, c0 + 1, ch.clicks, INT)
        put(ws, r, c0 + 3, ch.orders, INT)
        put(ws, r, c0 + 5, ch.gmv, MONEY)
        put(ws, r, c0 + 8, ch.cost, MONEY)
    for r in range(CH_FIRST, CH_TOTAL + 1):
        put(ws, r, c0 + 2, f'=IFERROR({k}{r}/{v}{r},"")', PCT)
        put(ws, r, c0 + 4, f'=IFERROR({o}{r}/{k}{r},"")', PCT)
        put(ws, r, c0 + 6, f'=IFERROR({g}{r}/{o}{r},"")', MONEY)
        put(ws, r, c0 + 7, f'=IFERROR({g}{r}/{g}${CH_TOTAL},"")', PCT)
    for off, fmt in ((0, INT), (1, INT), (3, INT), (5, MONEY), (8, MONEY)):
        L = col(c0 + off)
        put(ws, CH_TOTAL, c0 + off, f"=SUM({L}{CH_FIRST}:{L}{last})", fmt, bold=True)


def _channels(wb: Workbook, data: TongQuanData) -> None:
    ws = wb.create_sheet(SHEET_CHANNEL)
    put(ws, 1, 1, title_of(data)).font = TITLE
    header(ws, 3, ["Kỳ này"], CH_NOW)
    header(ws, 3, ["Kỳ trước"], CH_PREV)
    ws.merge_cells(start_row=3, start_column=CH_NOW, end_row=3, end_column=CH_NOW + 8)
    ws.merge_cells(start_row=3, start_column=CH_PREV, end_row=3, end_column=CH_PREV + 8)
    header(ws, 4, ["Kênh"])
    header(ws, 4, CH_HEADER, CH_NOW)
    header(ws, 4, CH_HEADER, CH_PREV)
    header(ws, 4, ["Thay đổi GMV", "Thay đổi Đơn"], CH_CHANGE_GMV)
    for i, key in enumerate(CHANNELS):
        put(ws, CH_FIRST + i, 1, CHANNEL_LABELS[key])
    put(ws, CH_TOTAL, 1, "Tổng", bold=True)
    _channel_block(ws, CH_NOW, data.now)
    _channel_block(ws, CH_PREV, data.prev)
    for r in range(CH_FIRST, CH_TOTAL + 1):
        put(ws, r, CH_CHANGE_GMV, _change(f"G{r}", f"P{r}"), PCT)
        put(ws, r, CH_CHANGE_ORDERS, _change(f"E{r}", f"N{r}"), PCT)
    widths(ws, {1: 20}, 12)
    finish(ws, "B5")


# ----------------------------------------------------------------------------- Theo ngày

DAY_HEADER = [
    "Ngày", "GMV Organic", "GMV Quảng cáo", "GMV TTLK", "GMV", "Đơn Organic", "Đơn Quảng cáo",
    "Đơn TTLK", "Đơn", "Chi phí quảng cáo", "Chi phí TTLK", "Chi phí ưu đãi", "Lợi nhuận",
    "GMV nền", "GMV mục tiêu", "Lợi nhuận nền", "Lợi nhuận mục tiêu",
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
            put(ws, r, 6 + i, d.orders.get(key), INT)
        put(ws, r, 5, f"=SUM(B{r}:D{r})", MONEY)
        put(ws, r, 9, f"=SUM(F{r}:H{r})", INT)
        for c, v in (
            (10, d.ads_cost), (11, d.aff_cost), (12, d.offer_cost), (13, d.profit),
            (14, d.baseline_gmv), (15, d.goal_gmv), (16, d.baseline_profit), (17, d.goal_profit),
        ):  # fmt: skip
            put(ws, r, c, v, MONEY)
    total = r + 1
    put(ws, total, 1, "Tổng", bold=True)
    first, last = DAY_FIRST, max(r, DAY_FIRST)
    for c in range(2, 18):
        L = col(c)
        put(ws, total, c, f"=SUM({L}{first}:{L}{last})", INT if 6 <= c <= 9 else MONEY, bold=True)
    widths(ws, {1: 12}, 15)
    finish(ws, "B4")


# ----------------------------------------------------------------------------- Theo sản phẩm

P_BLOCK = [
    "GMV Organic", "GMV Quảng cáo", "GMV TTLK", "Đơn Organic", "Đơn Quảng cáo", "Đơn TTLK",
    "Lượt xem", "Lượt nhấp", "CTR", "Đơn", "CTOR", "AOV", "GMV", "Lợi nhuận", "Chi phí quảng cáo",
    "Chi phí TTLK", "Chi phí ưu đãi", "ROI",
]  # fmt: skip
P_NOW = 3  # first column of Kỳ này (18 columns), then Kỳ trước
P_PREV = P_NOW + len(P_BLOCK)
P_CHANGE = P_PREV + len(P_BLOCK)  # Thay đổi GMV / Đơn / Lợi nhuận
P_PLAN = P_CHANGE + 3  # GMV nền, GMV mục tiêu, % đạt, Lợi nhuận nền, Lợi nhuận mục tiêu, % đạt
P_FIRST = 5
#: block offsets of the cells (0-based within a period block)
PB = {n: i for i, n in enumerate(
    ["g_org", "g_ads", "g_aff", "o_org", "o_ads", "o_aff", "views", "clicks", "ctr", "orders",
     "ctor", "aov", "gmv", "profit", "c_ads", "c_aff", "c_offer", "roi"]
)}  # fmt: skip


def _views_clicks(fig: Figures) -> tuple[float | None, float | None]:
    def tot(name: str) -> float | None:
        vals = [getattr(fig.channel(k), name) for k in CHANNELS]
        known = [v for v in vals if v is not None]
        return sum(known) if known else None

    return tot("views"), tot("clicks")


def _product_block(ws, r: int, c0: int, fig: Figures) -> None:
    views, clicks = _views_clicks(fig)
    vals = {
        "g_org": fig.channel("organic").gmv, "g_ads": fig.channel("ads").gmv,
        "g_aff": fig.channel("affiliate").gmv, "o_org": fig.channel("organic").orders,
        "o_ads": fig.channel("ads").orders, "o_aff": fig.channel("affiliate").orders,
        "views": views, "clicks": clicks, "profit": fig.profit, "c_ads": fig.ads_cost,
        "c_aff": fig.aff_cost, "c_offer": fig.offer_cost,
    }  # fmt: skip
    for n, v in vals.items():
        put(
            ws,
            r,
            c0 + PB[n],
            v,
            INT if n in ("o_org", "o_ads", "o_aff", "views", "clicks") else MONEY,
        )
    _product_formulas(ws, r, c0)


def _product_formulas(ws, r: int, c0: int) -> None:
    cc = {n: col(c0 + i) for n, i in PB.items()}
    put(ws, r, c0 + PB["ctr"], f'=IFERROR({cc["clicks"]}{r}/{cc["views"]}{r},"")', PCT)
    put(ws, r, c0 + PB["orders"], f"=SUM({cc['o_org']}{r}:{cc['o_aff']}{r})", INT)
    put(ws, r, c0 + PB["ctor"], f'=IFERROR({cc["orders"]}{r}/{cc["clicks"]}{r},"")', PCT)
    put(ws, r, c0 + PB["aov"], f'=IFERROR({cc["gmv"]}{r}/{cc["orders"]}{r},"")', MONEY)
    put(ws, r, c0 + PB["gmv"], f"=SUM({cc['g_org']}{r}:{cc['g_aff']}{r})", MONEY)
    put(
        ws, r, c0 + PB["roi"],
        f'=IFERROR({cc["profit"]}{r}/SUM({cc["c_ads"]}{r}:{cc["c_offer"]}{r}),"")', POINTS,
    )  # fmt: skip


def _plan_cells(ws, r: int, now: Figures) -> None:
    g = col(P_NOW + PB["gmv"])
    p = col(P_NOW + PB["profit"])
    put(ws, r, P_PLAN, now.baseline_gmv, MONEY)
    put(ws, r, P_PLAN + 1, now.goal_gmv, MONEY)
    put(ws, r, P_PLAN + 2, f'=IFERROR({g}{r}/{col(P_PLAN + 1)}{r},"")', PCT)
    put(ws, r, P_PLAN + 3, now.baseline_profit, MONEY)
    put(ws, r, P_PLAN + 4, now.goal_profit, MONEY)
    put(ws, r, P_PLAN + 5, f'=IFERROR({p}{r}/{col(P_PLAN + 4)}{r},"")', PCT)


def _changes(ws, r: int) -> None:
    for i, n in enumerate(("gmv", "orders", "profit")):
        a, b = col(P_NOW + PB[n]), col(P_PREV + PB[n])
        put(ws, r, P_CHANGE + i, _change(f"{a}{r}", f"{b}{r}"), PCT)


def _products(wb: Workbook, data: TongQuanData) -> None:
    ws = wb.create_sheet(SHEET_PRODUCT)
    put(ws, 1, 1, title_of(data)).font = TITLE
    header(ws, 3, ["Kỳ này"], P_NOW)
    header(ws, 3, ["Kỳ trước"], P_PREV)
    header(ws, 3, ["Thay đổi"], P_CHANGE)
    header(ws, 3, ["Kế hoạch đang chạy"], P_PLAN)
    for c0, n in ((P_NOW, len(P_BLOCK)), (P_PREV, len(P_BLOCK)), (P_CHANGE, 3), (P_PLAN, 6)):
        ws.merge_cells(start_row=3, start_column=c0, end_row=3, end_column=c0 + n - 1)
    header(ws, 4, ["Mã SP", "Sản phẩm"])
    header(ws, 4, P_BLOCK, P_NOW)
    header(ws, 4, P_BLOCK, P_PREV)
    header(ws, 4, ["Thay đổi GMV", "Thay đổi Đơn", "Thay đổi Lợi nhuận"], P_CHANGE)
    header(
        ws, 4,
        [
            "GMV nền", "GMV mục tiêu", "% đạt GMV", "Lợi nhuận nền", "Lợi nhuận mục tiêu",
            "% đạt Lợi nhuận",
        ],
        P_PLAN,
    )  # fmt: skip
    r = P_FIRST - 1
    for r, p in enumerate(data.products, start=P_FIRST):
        put(ws, r, 1, p.product_id)
        put(ws, r, 2, p.name)
        _product_block(ws, r, P_NOW, p.now)
        _product_block(ws, r, P_PREV, p.prev)
        _changes(ws, r)
        _plan_cells(ws, r, p.now)
    total, last = r + 1, max(r, P_FIRST)
    put(ws, total, 1, "Tổng", bold=True)
    for c0 in (P_NOW, P_PREV):
        for key in ("g_org", "g_ads", "g_aff", "o_org", "o_ads", "o_aff", "views", "clicks",
                    "profit", "c_ads", "c_aff", "c_offer"):  # fmt: skip
            L = col(c0 + PB[key])
            put(ws, total, c0 + PB[key], f"=SUM({L}{P_FIRST}:{L}{last})", MONEY, bold=True)
        _product_formulas(ws, total, c0)
    _changes(ws, total)
    for c in (P_PLAN, P_PLAN + 1, P_PLAN + 3, P_PLAN + 4):
        L = col(c)
        put(ws, total, c, f"=SUM({L}{P_FIRST}:{L}{last})", MONEY, bold=True)
    g, p_ = col(P_NOW + PB["gmv"]), col(P_NOW + PB["profit"])
    put(ws, total, P_PLAN + 2, f'=IFERROR({g}{total}/{col(P_PLAN + 1)}{total},"")', PCT)
    put(ws, total, P_PLAN + 5, f'=IFERROR({p_}{total}/{col(P_PLAN + 4)}{total},"")', PCT)
    widths(ws, {1: 16, 2: 38}, 13)
    finish(ws, "C5")


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
