"""The Kế hoạch export: a pure builder, plain dataclasses in, an openpyxl Workbook / bytes out.

Sheets (UI grill G20 / G22 / G23):

- "Lịch sử thẻ": every card active on a day of the range (proposed, ran or measured), one row each,
  with its shop and platform, status (including "Trong nháp"), dates, run days, the core rows
  Dự kiến (the P50 only, no range: forecast grill F4) · Thực tế · Chênh lệch for Δ lợi nhuận,
  Δ GMV, Δ đơn and Chi phí, and Kết luận;
- "Mục tiêu": per shop the range's baseline, goal and actual (GMV, Lợi nhuận), then the daily
  table; a business total row only when every shop has a goal for the metric;
- one sheet per card kind group (:data:`KIND_SHEETS`) with its tailored rows (UI grill G19);
- "KOL": one row per KOL.

There is no "Kế hoạch nháp" sheet: a draft card is a row of "Lịch sử thẻ" with status "Trong nháp".
Per metric (Lợi nhuận, GMV, Đơn, AOV) the columns are Hiện tại · Dự kiến · Thực tế · Chênh lệch
(F7 data: the card's stored forecast and its running measurement, all over the measured days, one
amount, no range); Chênh lệch is the one formula (Thực tế - Dự kiến, empty when either is empty).
Then Chi phí, Đã đo ("k/N ngày"), Đo chung với (the card's change group) and Kết luận. An unknown
value is an empty cell, never 0. ``fullCalcOnLoad`` is set. Only Excel-2007 functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

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

SHEET_HISTORY = "Lịch sử thẻ"
SHEET_GOAL = "Mục tiêu"
SHEET_KOL = "KOL"
DRAFT = "Trong nháp"
RUNNING = "Đang chạy"
MEASURING = "Đang đo"
MEASURED = "Đã đo"
BUSINESS_TOTAL = "Tổng"

#: card family / kind -> (sheet, tailored rows of UI grill G19). The first match wins: a kind key,
#: then the family; a kind that matches nothing goes to the "Khác" sheet with no tailored rows.
KIND_SHEETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "ads": ("Quảng cáo", ("CPA", "CPA hoà vốn", "ROAS", "ROAS hoà vốn", "Lượt nhấp")),
    "voucher": ("Voucher", ("Lượt dùng", "Đơn đủ điều kiện", "AOV", "Tiền giảm")),
    "combo": ("Combo - Deal Sốc", ("Đơn có combo", "SP/đơn", "AOV", "Tiền giảm")),
    "promotion": ("Giá - Chương trình - Flash", ("Giá bán TB", "SP bán", "Biên", "Tiền giảm")),
    "sale": ("Giá - Chương trình - Flash", ("Giá bán TB", "SP bán", "Biên", "Tiền giảm")),
    "variation_restructure": ("Phân loại", ("Đơn phân loại mới", "AOV", "SP/đơn")),
    "listing": ("Listing", ("Lượt xem", "CTR", "CTOR")),
    "affiliate": ("Liên kết - KOL", ("Đơn liên kết", "Hoa hồng", "ROI KOL", "Chi phí mẫu")),
}
OTHER_SHEET = "Thẻ khác"

#: the metrics of every card (F7): label, key. Each has Hiện tại · Dự kiến · Thực tế · Chênh lệch.
CORE = (("Lợi nhuận", "profit"), ("GMV", "gmv"), ("Đơn", "orders"), ("AOV", "aov"))
CORE_FORMAT = {"profit": MONEY, "gmv": MONEY, "orders": INT, "aov": MONEY}
PHASES = ("hiện tại", "dự kiến", "thực tế", "chênh lệch")
TAIL = ("Chi phí", "Đã đo", "Đo chung với", "Kết luận")


@dataclass
class CardRow:
    code: str
    plan_code: str | None
    status: str  # Đang chạy | Trong nháp | Đang đo | Đã đo
    group: str  # Ưu đãi | Listing | Truy cập
    kind: str  # the kind's label
    version: str | None
    product_id: str | None
    product_name: str | None
    metrics: str | None
    start: date | None
    end: date | None
    #: the card's kind key and family (``kinds.KINDS``): the kind sheet it belongs to
    kind_key: str = ""
    family: str = ""
    shop: str = ""
    platform: str = "Shopee"
    #: the day it was proposed (added to a plan / created) and the last day of its measurement
    proposed: date | None = None
    measure_end: date | None = None
    #: Dự kiến: the P50 of the card's own days (no range, F4); Chi phí is the card's cost
    cost: float | None = None
    gmv_mid: float | None = None
    profit_mid: float | None = None
    orders_mid: float | None = None
    #: Nguồn: where the card came from (``SOURCE_LABELS`` of its origin) and, for a card imported
    #: from the owner's sheet, its original Mã (``external_ref``)
    source: str = ""
    external_ref: str | None = None
    #: Thực tế Δ lợi nhuận of the stored measurement (``None`` = not measured) and Kết luận
    actual_profit: float | None = None
    conclusion: str | None = None
    #: F7 figures per metric key: (hiện tại, dự kiến, thực tế) over the measured days; ``None`` =
    #: unknown. A key missing = all three unknown.
    figures: dict[str, tuple[float | None, float | None, float | None]] = field(
        default_factory=dict
    )
    #: Đã đo: days measured / days of the window; Đo chung với: the other codes of the change group
    days_measured: int | None = None
    days_total: int | None = None
    measured_with: list[str] = field(default_factory=list)
    #: tailored rows of the kind sheet: label -> (Dự kiến, Thực tế); absent / ``None`` = "—"
    tailored: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)

    @property
    def run_days(self) -> int | None:
        return None if self.start is None or self.end is None else (self.end - self.start).days + 1

    @property
    def active_from(self) -> date | None:
        days = [d for d in (self.proposed, self.start) if d is not None]
        return min(days) if days else None

    @property
    def active_to(self) -> date | None:
        days = [d for d in (self.end, self.measure_end) if d is not None]
        return max(days) if days else None


@dataclass
class GoalRow:
    """One shop's baseline / goal / actual over the range (running plans only); ``None`` = the shop
    has none (no running card, or a platform without a plan collector)."""

    shop: str
    platform: str = "Shopee"
    baseline_gmv: float | None = None
    goal_gmv: float | None = None
    actual_gmv: float | None = None
    baseline_profit: float | None = None
    goal_profit: float | None = None
    actual_profit: float | None = None


@dataclass
class GoalDay:
    shop: str
    day: date
    baseline_gmv: float | None = None
    goal_gmv: float | None = None
    actual_gmv: float | None = None
    baseline_profit: float | None = None
    goal_profit: float | None = None
    actual_profit: float | None = None


@dataclass
class KolRow:
    shop: str
    platform: str
    kol: str
    clicks: float | None = None
    orders: float | None = None
    gmv: float | None = None
    commission: float | None = None
    profit: float | None = None
    cards: int = 0
    sample_cost: float | None = None


@dataclass
class KeHoachData:
    start: date
    end: date
    #: every shop of the export (one for a single shop), in the order of the file
    shops: list[str]
    cards: list[CardRow] = field(default_factory=list)
    goals: list[GoalRow] = field(default_factory=list)
    days: list[GoalDay] = field(default_factory=list)
    kols: list[KolRow] = field(default_factory=list)
    #: built under the "Tất cả shop" gate (even when the user has a single shop)
    all_shops: bool = False

    @property
    def multi(self) -> bool:
        return self.all_shops or len(self.shops) > 1


def _d(x: date) -> str:
    return f"{x:%d/%m/%Y}"


def title_of(data: KeHoachData, what: str) -> str:
    who = "Tất cả shop" if data.multi else data.shops[0]
    return f"{what} — {who} · {_d(data.start)}–{_d(data.end)}"


def file_name(data: KeHoachData) -> str:
    name = "TatCaShop" if data.multi else data.shops[0].replace(" ", "")
    return f"Juli_KeHoach_{name}_{data.start:%d%m%Y}_{data.end:%d%m%Y}.xlsx"


def active_in(c: CardRow, start: date, end: date) -> bool:
    """G22: the card was proposed, ran or was measured on at least one day of ``start..end``. A
    card with no dates at all is not in any range; a card still open (no end) runs to the range's
    end."""
    first, last = c.active_from, c.active_to
    if first is None:
        return False
    if last is None:
        last = max(first, end)
    return first <= end and last >= start


def sheet_of(c: CardRow) -> tuple[str, tuple[str, ...]]:
    return KIND_SHEETS.get(c.kind_key) or KIND_SHEETS.get(c.family) or (OTHER_SHEET, ())


def figures_of(c: CardRow, key: str) -> tuple[float | None, float | None, float | None]:
    """(Hiện tại, Dự kiến, Thực tế) of one metric of one card; unknown = ``None``, never 0."""
    return c.figures.get(key, (None, None, None))


def measured_text(c: CardRow) -> str | None:
    if c.days_measured is None or c.days_total is None:
        return None
    return f"{c.days_measured}/{c.days_total} ngày"


def measured_with_text(c: CardRow) -> str | None:
    return ", ".join(c.measured_with) if c.measured_with else None


def _metric_cells(ws, r: int, c0: int, c: CardRow, key: str, *, with_gap: bool) -> int:
    """Hiện tại · Dự kiến · Thực tế (and the Chênh lệch formula) of one metric from ``c0``;
    returns the next free column."""
    now, exp, act = figures_of(c, key)
    fmt = CORE_FORMAT[key]
    put(ws, r, c0, now, fmt)
    put(ws, r, c0 + 1, exp, fmt)
    put(ws, r, c0 + 2, act, fmt)
    if not with_gap:
        return c0 + 3
    e, a = col(c0 + 1), col(c0 + 2)
    put(ws, r, c0 + 3, f'=IF(OR({e}{r}="",{a}{r}=""),"",{a}{r}-{e}{r})', fmt)
    return c0 + 4


def _tail(ws, r: int, c0: int, c: CardRow) -> None:
    put(ws, r, c0, c.cost, MONEY)
    put(ws, r, c0 + 1, measured_text(c))
    put(ws, r, c0 + 2, measured_with_text(c))
    put(ws, r, c0 + 3, c.conclusion)


def _core_head() -> list[str]:
    return [f"{label} {phase}" for label, _ in CORE for phase in PHASES]


# ----------------------------------------------------------------------------- Lịch sử thẻ

HISTORY_LEAD = [
    "STT", "Mã thẻ", "Mã gốc", "Nguồn", "Shop", "Nền tảng", "Trạng thái", "Nhóm", "Phương án",
    "Phiên bản", "Sản phẩm", "Đề xuất", "Bắt đầu", "Kết thúc", "Số ngày chạy",
]  # fmt: skip
LEAD_WIDTHS = [6, 14, 14, 14, 22, 10, 12, 10, 28, 12, 34, 12, 12, 12, 9]
#: Nguồn of a card by its origin: the engine's ("Juli"), the seller's own ("Tự tạo") and one
#: imported from work done outside Juli ("Làm ngoài Juli")
SOURCE_LABELS = {
    "engine": "Juli",
    "manual": "Tự tạo",
    "agent": "Từ tab Juli",
    "external": "Làm ngoài Juli",
}
#: An origin with no label never reaches the sheet as a raw key.
SOURCE_UNKNOWN = "Khác"


def source_label(origin: str | None) -> str:
    """Nguồn for a card's origin (none = the engine's); an unknown origin reads "Khác"."""
    return SOURCE_LABELS.get(origin or "engine", SOURCE_UNKNOWN)


def _lead(ws, r: int, i: int, c: CardRow) -> None:
    put(ws, r, 1, i)
    for k, v in enumerate((c.code, c.external_ref, c.source, c.shop, c.platform, c.status,
                           c.group, c.kind, c.version, c.product_name), start=2):  # fmt: skip
        put(ws, r, k, v)
    first = HISTORY_LEAD.index("Đề xuất") + 1
    for k, day in ((first, c.proposed), (first + 1, c.start), (first + 2, c.end)):
        put(ws, r, k, day, DATE)
    a, b = col(first + 1), col(first + 2)
    put(ws, r, first + 3, f'=IF(OR({a}{r}="",{b}{r}=""),"",{b}{r}-{a}{r}+1)', INT)


def _history(wb: Workbook, data: KeHoachData) -> None:
    ws = wb.create_sheet(SHEET_HISTORY)
    put(ws, 1, 1, title_of(data, "LỊCH SỬ THẺ")).font = TITLE
    header(ws, 3, [*HISTORY_LEAD, *_core_head(), *TAIL])
    first = 4
    for i, c in enumerate(data.cards, start=1):
        r = first + i - 1
        _lead(ws, r, i, c)
        c0 = len(HISTORY_LEAD) + 1
        for _, key in CORE:
            c0 = _metric_cells(ws, r, c0, c, key, with_gap=True)
        _tail(ws, r, c0, c)
    widths(ws, LEAD_WIDTHS, 14)
    ws.column_dimensions[col(len(HISTORY_LEAD) + 1 + 4 * len(CORE) + 3)].width = 22
    ws.column_dimensions[col(len(HISTORY_LEAD) + 1 + 4 * len(CORE) + 2)].width = 22
    finish(ws, "C4")


# ----------------------------------------------------------------------------- kind sheets


def _kind_sheet(wb: Workbook, data: KeHoachData, name: str, tailored: tuple[str, ...],
                cards: list[CardRow]) -> None:  # fmt: skip
    ws = wb.create_sheet(name)
    put(ws, 1, 1, title_of(data, name.upper())).font = TITLE
    head = [*HISTORY_LEAD, *_core_head(), "Chi phí", "Đã đo", "Đo chung với"]
    for label in tailored:
        head += [f"{label} dự kiến", f"{label} thực tế"]
    header(ws, 3, [*head, "Kết luận"])
    for i, c in enumerate(cards, start=1):
        r = 3 + i
        _lead(ws, r, i, c)
        c0 = len(HISTORY_LEAD) + 1
        for _, key in CORE:
            c0 = _metric_cells(ws, r, c0, c, key, with_gap=True)
        put(ws, r, c0, c.cost, MONEY)
        put(ws, r, c0 + 1, measured_text(c))
        put(ws, r, c0 + 2, measured_with_text(c))
        t0 = c0 + 3
        for k, label in enumerate(tailored):
            want, got = c.tailored.get(label, (None, None))
            put(ws, r, t0 + 2 * k, want, POINTS)
            put(ws, r, t0 + 2 * k + 1, got, POINTS)
        put(ws, r, t0 + 2 * len(tailored), c.conclusion)
    widths(ws, LEAD_WIDTHS, 14)
    finish(ws, "C4")


# ----------------------------------------------------------------------------- Mục tiêu

GOAL_HEADER = [
    "Shop", "Nền tảng", "GMV nền", "GMV mục tiêu", "GMV thực tế", "% đạt GMV", "Lợi nhuận nền",
    "Lợi nhuận mục tiêu", "Lợi nhuận thực tế", "% đạt lợi nhuận",
]  # fmt: skip
DAY_HEADER = [
    "Shop", "Ngày", "GMV nền", "GMV mục tiêu", "GMV thực tế", "Lợi nhuận nền",
    "Lợi nhuận mục tiêu", "Lợi nhuận thực tế",
]  # fmt: skip
#: the (nền, mục tiêu, thực tế) triple of each scope on a GoalRow
GOAL_SCOPES = (("baseline_gmv", "goal_gmv", "actual_gmv"),
               ("baseline_profit", "goal_profit", "actual_profit"))  # fmt: skip


def business_total(rows: list[GoalRow], attr: str) -> float | None:
    """The business total of one goal figure: the sum over the shops, but only when EVERY shop has
    one (G23): a shop with no target would make the total look like a smaller goal."""
    vals = [getattr(r, attr) for r in rows]
    return None if not vals or any(v is None for v in vals) else float(sum(vals))


def _goals(wb: Workbook, data: KeHoachData) -> None:
    ws = wb.create_sheet(SHEET_GOAL)
    put(ws, 1, 1, title_of(data, "MỤC TIÊU")).font = TITLE
    header(ws, 3, GOAL_HEADER)
    r = 3
    for r, g in enumerate(data.goals, start=4):
        put(ws, r, 1, g.shop)
        put(ws, r, 2, g.platform)
        for k, attrs in enumerate(GOAL_SCOPES):
            c0 = 3 + 4 * k
            for j, attr in enumerate(attrs):
                put(ws, r, c0 + j, getattr(g, attr), MONEY)
            put(ws, r, c0 + 3, f'=IFERROR({col(c0 + 2)}{r}/{col(c0 + 1)}{r},"")', PCT)
    if data.multi and data.goals:
        t = r + 1
        put(ws, t, 1, BUSINESS_TOTAL, bold=True)
        for k, attrs in enumerate(GOAL_SCOPES):
            c0 = 3 + 4 * k
            for j, attr in enumerate(attrs):
                put(ws, t, c0 + j, business_total(data.goals, attr), MONEY, bold=True)
            put(ws, t, c0 + 3, f'=IFERROR({col(c0 + 2)}{t}/{col(c0 + 1)}{t},"")', PCT)
        r = t
    d0 = r + 3
    put(ws, d0 - 1, 1, "Theo ngày", bold=True)
    header(ws, d0, DAY_HEADER)
    for i, d in enumerate(data.days, start=1):
        row = d0 + i
        put(ws, row, 1, d.shop)
        put(ws, row, 2, d.day, DATE)
        for k, v in enumerate((d.baseline_gmv, d.goal_gmv, d.actual_gmv, d.baseline_profit,
                               d.goal_profit, d.actual_profit), start=3):  # fmt: skip
            put(ws, row, k, v, MONEY)
    widths(ws, {1: 24}, 16)
    finish(ws, "C4")


# ----------------------------------------------------------------------------- KOL

KOL_HEADER = [
    "Shop", "Nền tảng", "KOL", "Lượt nhấp", "Đơn liên kết", "GMV", "Hoa hồng", "Lợi nhuận",
    "Chi phí mẫu", "ROI KOL", "Số thẻ",
]  # fmt: skip


def _kols(wb: Workbook, data: KeHoachData) -> None:
    ws = wb.create_sheet(SHEET_KOL)
    put(ws, 1, 1, title_of(data, "KOL")).font = TITLE
    header(ws, 3, KOL_HEADER)
    for r, k in enumerate(data.kols, start=4):
        for c, text in ((1, k.shop), (2, k.platform), (3, k.kol)):
            put(ws, r, c, text)
        for c, v, fmt in ((4, k.clicks, INT), (5, k.orders, INT), (6, k.gmv, MONEY),
                          (7, k.commission, MONEY), (8, k.profit, MONEY),
                          (9, k.sample_cost, MONEY)):  # fmt: skip
            put(ws, r, c, v, fmt)
        # registry roi_kol = (lợi nhuận KOL − chi phí mẫu) ÷ (hoa hồng + chi phí mẫu)
        put(ws, r, 10, f'=IFERROR((H{r}-N(I{r}))/(G{r}+N(I{r})),"")', POINTS)
        put(ws, r, 11, k.cards, INT)
    widths(ws, {1: 24, 3: 28}, 14)
    finish(ws, "D4")


def build(data: KeHoachData) -> Workbook:
    wb = new_workbook()
    _history(wb, data)
    _goals(wb, data)
    by_sheet: dict[str, tuple[tuple[str, ...], list[CardRow]]] = {}
    for c in data.cards:
        name, tailored = sheet_of(c)
        by_sheet.setdefault(name, (tailored, []))[1].append(c)
    for name, (tailored, cards) in by_sheet.items():
        _kind_sheet(wb, data, name, tailored, cards)
    _kols(wb, data)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.font is None or cell.font.name != "Arial":
                    cell.font = FONT
    return wb


def build_bytes(data: KeHoachData) -> bytes:
    return save_bytes(build(data))


def days_of(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
