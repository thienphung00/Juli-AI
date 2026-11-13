"""The Kế hoạch export: a pure builder, plain dataclasses in, an openpyxl Workbook / bytes out.

Sheets: "Đề xuất" (one row per card of the executed and draft plans, plus the measuring /
measured cards of the month) and "Mục tiêu" (the month's baseline, goals and daily table).

The goals follow ``month_plan``: goal = baseline + uplift, the baseline per day = the month's
baseline / days of the month, the uplift of a card = its own P50 Δ / its own days, counted on the
days it runs inside the month. In the file the daily Δ columns are SUMPRODUCT formulas over the
"Đề xuất" rows: running = the rows with a plan code whose status is not "Nháp"; draft = the rows
with status "Nháp". Only Excel-2007 functions. ``fullCalcOnLoad`` is set.
"""

from __future__ import annotations

import calendar
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

SHEET_CARDS = "Đề xuất"
SHEET_GOAL = "Mục tiêu"
DRAFT = "Nháp"
RUNNING = "Đang chạy"
MEASURING = "Đang đo"
MEASURED = "Đã đo"

CARD_HEADER = [
    "STT", "Mã thẻ", "Mã kế hoạch", "Trạng thái", "Nhóm", "Loại", "Phương án", "Mã SP",
    "Sản phẩm", "Chỉ số tác động", "Ngày bắt đầu", "Ngày kết thúc", "Số ngày",
    "Chi phí cả kỳ (đ)", "Δ GMV kỳ vọng (đ)", "Δ lợi nhuận kỳ vọng (đ)", "Δ đơn",
    "Δ GMV / ngày (đ)", "Δ lợi nhuận / ngày (đ)", "ROI", "Δ lợi nhuận thực tế (đ)",
]  # fmt: skip
C = {  # column letter of each card column
    n: col(i) for i, n in enumerate(
        ["stt", "code", "plan", "status", "group", "kind", "version", "item", "name", "metrics",
         "start", "end", "days", "cost", "g_mid", "p_mid",
         "orders", "g_day", "p_day", "roi", "actual"], start=1)
}  # fmt: skip
CARD_FIRST = 4


@dataclass
class CardRow:
    code: str
    plan_code: str | None
    status: str  # Đang chạy | Nháp | Đang đo | Đã đo
    group: str  # Ưu đãi | Listing | Truy cập
    kind: str
    version: str | None
    product_id: str | None
    product_name: str | None
    metrics: str | None
    start: date | None
    end: date | None
    cost: float | None = None
    gmv_mid: float | None = None
    profit_mid: float | None = None
    orders: float | None = None
    actual_profit: float | None = None


@dataclass
class KeHoachData:
    shop_name: str
    month_first: date
    last_data_day: date
    baseline_gmv: float
    baseline_profit: float
    actual_gmv: dict[date, float] = field(default_factory=dict)
    actual_profit: dict[date, float] = field(default_factory=dict)
    cards: list[CardRow] = field(default_factory=list)
    platform: str = "Shopee"

    @property
    def days_in_month(self) -> int:
        return calendar.monthrange(self.month_first.year, self.month_first.month)[1]

    @property
    def month_days(self) -> list[date]:
        return [self.month_first + timedelta(days=i) for i in range(self.days_in_month)]


def file_name(data: KeHoachData) -> str:
    name = data.shop_name.replace(" ", "")
    return f"Juli_KeHoach_{name}_Tháng {data.month_first:%m-%Y}.xlsx"


def _running(c: CardRow) -> bool:
    return bool(c.plan_code) and c.status != DRAFT


def card_days(c: CardRow) -> int | None:
    return None if c.start is None or c.end is None else (c.end - c.start).days + 1


def daily_targets(data: KeHoachData) -> list[dict[str, float | date | None]]:
    """What the "Mục tiêu" daily formulas compute, in Python: per day of the month the baseline,
    the running and draft Δ (GMV and profit) and the goals. The test pins the month sums to
    ``month_plan``'s goals."""
    out: list[dict[str, float | date | None]] = []
    n = data.days_in_month
    for d in data.month_days:
        row: dict[str, float | date | None] = {
            "day": d,
            "base_gmv": data.baseline_gmv / n,
            "base_profit": data.baseline_profit / n,
        }
        sums: dict[str, float] = {}
        for key, pick in (("run", _running), ("draft", lambda c: c.status == DRAFT)):
            g = p = 0.0
            for c in data.cards:
                days = card_days(c)
                if not pick(c) or not days or c.start is None or c.end is None:
                    continue
                if c.start <= d <= c.end:
                    g += (c.gmv_mid or 0.0) / days
                    p += (c.profit_mid or 0.0) / days
            row[f"{key}_gmv"], row[f"{key}_profit"] = g, p
            sums[f"{key}_gmv"], sums[f"{key}_profit"] = g, p
        goal_gmv = data.baseline_gmv / n + sums["run_gmv"]
        goal_profit = data.baseline_profit / n + sums["run_profit"]
        row["goal_gmv"], row["goal_profit"] = goal_gmv, goal_profit
        row["goal_gmv_draft"] = goal_gmv + sums["draft_gmv"]
        row["goal_profit_draft"] = goal_profit + sums["draft_profit"]
        out.append(row)
    return out


# ----------------------------------------------------------------------------- Đề xuất


def _cards(wb: Workbook, data: KeHoachData) -> int:
    """Writes the sheet; returns the last card row (``CARD_FIRST - 1`` when there is none)."""
    ws = wb.create_sheet(SHEET_CARDS)
    put(
        ws, 1, 1,
        f"ĐỀ XUẤT — {data.shop_name} ({data.platform}) · Tháng {data.month_first:%m/%Y}",
    ).font = TITLE  # fmt: skip
    header(ws, 3, CARD_HEADER)
    r = CARD_FIRST - 1
    for r, c in enumerate(data.cards, start=CARD_FIRST):
        put(ws, r, 1, r - CARD_FIRST + 1)
        for name, v in (
            ("code", c.code), ("plan", c.plan_code), ("status", c.status), ("group", c.group),
            ("kind", c.kind), ("version", c.version), ("item", c.product_id),
            ("name", c.product_name), ("metrics", c.metrics),
        ):  # fmt: skip
            put(ws, r, _idx(name), v)
        put(ws, r, _idx("start"), c.start, DATE)
        put(ws, r, _idx("end"), c.end, DATE)
        K, L = C["start"], C["end"]
        put(ws, r, _idx("days"), f'=IF(AND({K}{r}<>"",{L}{r}<>""),{L}{r}-{K}{r}+1,"")', INT)
        for name, amount in (
            ("cost", c.cost), ("g_mid", c.gmv_mid), ("p_mid", c.profit_mid),
            ("orders", c.orders), ("actual", c.actual_profit),
        ):  # fmt: skip
            put(ws, r, _idx(name), amount, INT if name == "orders" else MONEY)
        put(ws, r, _idx("g_day"), f"=IFERROR({C['g_mid']}{r}/{C['days']}{r},0)", MONEY)
        put(ws, r, _idx("p_day"), f"=IFERROR({C['p_mid']}{r}/{C['days']}{r},0)", MONEY)
        put(ws, r, _idx("roi"), f'=IFERROR({C["p_mid"]}{r}/{C["cost"]}{r},"")', POINTS)
    last = max(r, CARD_FIRST - 1)
    total = last + 1
    put(ws, total, 1, "Tổng", bold=True)
    for name in ("cost", "g_mid", "p_mid", "orders", "g_day", "p_day", "actual"):  # fmt: skip
        L = C[name]
        put(
            ws, total, _idx(name), f"=SUM({L}{CARD_FIRST}:{L}{max(last, CARD_FIRST)})",
            INT if name == "orders" else MONEY, bold=True,
        )  # fmt: skip
    widths(
        ws,
        [6, 14, 14, 11, 10, 28, 24, 16, 36, 16, 12, 12, 8, 14, 14, 14, 9, 14, 14, 8, 14],
    )  # fmt: skip
    finish(ws, "C4")
    return last


def _idx(name: str) -> int:
    from openpyxl.utils import column_index_from_string

    return column_index_from_string(C[name])


# ----------------------------------------------------------------------------- Mục tiêu

DAY_HEADER_FIRST = 21  # header row of the daily table
SCOPE_GMV, SCOPE_PROFIT = 2, 10  # first column of the GMV block (B..I) / Lợi nhuận block (J..Q)
BLOCK_HEADER = [
    "nền", "Δ đang chạy", "Δ nháp", "Mục tiêu", "Mục tiêu + nháp", "thực tế", "Lũy kế mục tiêu",
    "Lũy kế thực tế",
]  # fmt: skip


def _rng(letter: str, last: int) -> str:
    return f"'{SHEET_CARDS}'!${letter}${CARD_FIRST}:${letter}${last}"


def _goal(wb: Workbook, data: KeHoachData, last_card: int) -> None:
    ws = wb.create_sheet(SHEET_GOAL)
    put(
        ws, 1, 1,
        f"MỤC TIÊU — {data.shop_name} ({data.platform}) · Tháng {data.month_first:%m/%Y}",
    ).font = TITLE  # fmt: skip
    n = data.days_in_month
    f = DAY_HEADER_FIRST + 1
    last = f + n - 1
    last_card = max(last_card, CARD_FIRST)
    start, end = _rng(C["start"], last_card), _rng(C["end"], last_card)
    status, plan = _rng(C["status"], last_card), _rng(C["plan"], last_card)
    day_of = {"gmv": _rng(C["g_day"], last_card), "profit": _rng(C["p_day"], last_card)}

    def sumproduct(a: str, kind: str, scope: str) -> str:
        who = f'({plan}<>"")*({status}<>"{DRAFT}")' if kind == "run" else f'({status}="{DRAFT}")'
        return f"=SUMPRODUCT(({start}<={a})*({end}>={a})*{who}*{day_of[scope]})"

    header(ws, DAY_HEADER_FIRST - 1, ["GMV (đ)"], SCOPE_GMV)
    header(ws, DAY_HEADER_FIRST - 1, ["Lợi nhuận (đ)"], SCOPE_PROFIT)
    ws.merge_cells(
        start_row=DAY_HEADER_FIRST - 1,
        start_column=SCOPE_GMV,
        end_row=DAY_HEADER_FIRST - 1,
        end_column=SCOPE_GMV + 7,
    )
    ws.merge_cells(
        start_row=DAY_HEADER_FIRST - 1,
        start_column=SCOPE_PROFIT,
        end_row=DAY_HEADER_FIRST - 1,
        end_column=SCOPE_PROFIT + 7,
    )
    header(ws, DAY_HEADER_FIRST, ["Ngày"])
    for c0, scope in ((SCOPE_GMV, "GMV"), (SCOPE_PROFIT, "Lợi nhuận")):
        labels = [f"{scope} {BLOCK_HEADER[0]}", f"Δ {scope} đang chạy", f"Δ {scope} nháp",
                  f"Mục tiêu {scope}", f"Mục tiêu {scope} + nháp", f"{scope} thực tế",
                  f"Lũy kế mục tiêu {scope}", f"Lũy kế thực tế {scope}"]  # fmt: skip
        header(ws, DAY_HEADER_FIRST, labels, c0)
    actual = {"gmv": data.actual_gmv, "profit": data.actual_profit}
    base = {"gmv": data.baseline_gmv, "profit": data.baseline_profit}
    for i, d in enumerate(data.month_days):
        r = f + i
        put(ws, r, 1, d, DATE)
        for c0, scope in ((SCOPE_GMV, "gmv"), (SCOPE_PROFIT, "profit")):
            b, run, dr, goal, goal_d, act, cum_g, cum_a = (col(c0 + k) for k in range(8))
            put(ws, r, c0, base[scope] / n, MONEY)
            put(ws, r, c0 + 1, sumproduct(f"$A{r}", "run", scope), MONEY)
            put(ws, r, c0 + 2, sumproduct(f"$A{r}", "draft", scope), MONEY)
            put(ws, r, c0 + 3, f"={b}{r}+{run}{r}", MONEY)
            put(ws, r, c0 + 4, f"={b}{r}+{run}{r}+{dr}{r}", MONEY)
            put(ws, r, c0 + 5, actual[scope].get(d), MONEY)
            put(ws, r, c0 + 6, f"=SUM({goal}${f}:{goal}{r})", MONEY)
            put(ws, r, c0 + 7, f'=IF({act}{r}="","",SUM({act}${f}:{act}{r}))', MONEY)
    total = last + 1
    put(ws, total, 1, "Tổng", bold=True)
    for c0 in (SCOPE_GMV, SCOPE_PROFIT):
        for k in range(6):
            L = col(c0 + k)
            put(ws, total, c0 + k, f"=SUM({L}{f}:{L}{last})", MONEY, bold=True)
    # the header block of the month
    ld = data.last_data_day
    at = f"DATE({ld.year},{ld.month},{ld.day})"
    for block, (scope_name, c0) in enumerate((("GMV", SCOPE_GMV), ("Lợi nhuận", SCOPE_PROFIT))):
        cols = [col(c0 + k) for k in range(8)]
        top = 3 + block * 8
        lines = [
            (f"{scope_name} nền", f"=SUM({cols[0]}{f}:{cols[0]}{last})", MONEY),
            (f"Δ {scope_name} đang chạy", f"=SUM({cols[1]}{f}:{cols[1]}{last})", MONEY),
            (f"Mục tiêu {scope_name} (đang chạy)", f"=B{top}+B{top + 1}", MONEY),
            (f"Δ {scope_name} nháp", f"=SUM({cols[2]}{f}:{cols[2]}{last})", MONEY),
            (f"Mục tiêu {scope_name} nếu áp dụng nháp", f"=B{top + 2}+B{top + 3}", MONEY),
            (
                f"{scope_name} thực tế đến {ld:%d/%m/%Y}",
                f"=SUM({cols[5]}{f}:{cols[5]}{last})",
                MONEY,
            ),
            (
                "% đạt so với mục tiêu đến ngày",
                f'=IFERROR(B{top + 5}/INDEX({cols[6]}{f}:{cols[6]}{last},'
                f'MATCH({at},$A{f}:$A{last},0)),"")',
                PCT,
            ),
        ]  # fmt: skip
        for i, (label, formula, fmt) in enumerate(lines):
            put(ws, top + i, 1, label)
            put(ws, top + i, 2, formula, fmt)
    widths(ws, {1: 44}, 15)
    finish(ws, f"B{DAY_HEADER_FIRST + 1}")


def build(data: KeHoachData) -> Workbook:
    wb = new_workbook()
    last = _cards(wb, data)
    _goal(wb, data, last)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.font is None or c.font.name != "Arial":
                    c.font = FONT
    return wb


def build_bytes(data: KeHoachData) -> bytes:
    return save_bytes(build(data))
