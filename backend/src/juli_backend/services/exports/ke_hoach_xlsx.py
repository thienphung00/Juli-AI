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
    "STT", "Mã thẻ", "Trạng thái", "Nhóm", "Phương án", "Sản phẩm", "Chỉ số tác động", "Bắt đầu",
    "Kết thúc", "Chi phí (đ)", "Δ GMV (đ)", "Δ lợi nhuận (đ)", "ROI", "Kết quả",
]  # fmt: skip
CARD_NAMES = ["stt", "code", "status", "group", "version", "name", "metrics", "start", "end",
              "cost", "g_mid", "p_mid", "roi", "result"]  # fmt: skip
C = {n: col(i) for i, n in enumerate([*CARD_NAMES, "plan"], start=1)}  # "plan" = hidden helper
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
    #: "<Δ lợi nhuận thực tế> · <kết luận>" of the stored measurement; ``None`` = not measured
    result: str | None = None


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
    header(ws, 3, [*CARD_HEADER, "Mã kế hoạch"])
    r = CARD_FIRST - 1
    for r, c in enumerate(data.cards, start=CARD_FIRST):
        put(ws, r, 1, r - CARD_FIRST + 1)
        for name, v in (
            ("code", c.code), ("status", c.status), ("group", c.group), ("version", c.version),
            ("name", c.product_name), ("metrics", c.metrics), ("result", c.result),
            ("plan", c.plan_code),
        ):  # fmt: skip
            put(ws, r, _idx(name), v)
        put(ws, r, _idx("start"), c.start, DATE)
        put(ws, r, _idx("end"), c.end, DATE)
        for name, amount in (("cost", c.cost), ("g_mid", c.gmv_mid), ("p_mid", c.profit_mid)):
            put(ws, r, _idx(name), amount, MONEY)
        put(ws, r, _idx("roi"), f'=IFERROR({C["p_mid"]}{r}/{C["cost"]}{r},"")', POINTS)
    last = max(r, CARD_FIRST - 1)
    total = last + 1
    put(ws, total, 1, "Tổng", bold=True)
    for name in ("cost", "g_mid", "p_mid"):
        L = C[name]
        put(
            ws, total, _idx(name), f"=SUM({L}{CARD_FIRST}:{L}{max(last, CARD_FIRST)})", MONEY,
            bold=True,
        )  # fmt: skip
    widths(ws, [6, 14, 11, 10, 24, 36, 16, 12, 12, 14, 14, 14, 8, 30, 14])
    ws.column_dimensions[C["plan"]].hidden = True
    finish(ws, "C4")
    return last


def _idx(name: str) -> int:
    from openpyxl.utils import column_index_from_string

    return column_index_from_string(C[name])


# ----------------------------------------------------------------------------- Mục tiêu

DAY_HEADER_FIRST = 17  # header row of the daily table
TOP = {"gmv": 3, "profit": 10}  # first row of the GMV / Lợi nhuận top block
SCOPE_NAME = {"gmv": "GMV", "profit": "Lợi nhuận"}
#: visible daily columns: first column of the GMV block (B..E) and the Lợi nhuận block (F..I);
#: each block = mục tiêu, thực tế, lũy kế mục tiêu, lũy kế thực tế
SCOPE_COL = {"gmv": 2, "profit": 6}
#: hidden helper columns the targets are built from: nền, Δ đang chạy, Δ nháp of each scope
HELP_COL = {"gmv": 10, "profit": 13}


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
    delta = {"gmv": _rng(C["g_mid"], last_card), "profit": _rng(C["p_mid"], last_card)}

    def sumproduct(a: str, kind: str, scope: str) -> str:
        """Σ over the cards running on day ``a`` of their Δ / their days (computed here from
        Bắt đầu / Kết thúc)."""
        who = f'({plan}<>"")*({status}<>"{DRAFT}")' if kind == "run" else f'({status}="{DRAFT}")'
        per_day = f"{delta[scope]}/({end}-{start}+1)"
        return f"=SUMPRODUCT(({start}<={a})*({end}>={a})*{who}*{per_day})"

    group_row = DAY_HEADER_FIRST - 1
    for scope, c0 in SCOPE_COL.items():
        header(ws, group_row, [SCOPE_NAME[scope] + " (đ)"], c0)
        ws.merge_cells(start_row=group_row, start_column=c0, end_row=group_row, end_column=c0 + 3)
    header(ws, DAY_HEADER_FIRST, ["Ngày"])
    base = {"gmv": data.baseline_gmv, "profit": data.baseline_profit}
    actual = {"gmv": data.actual_gmv, "profit": data.actual_profit}
    for scope, c0 in SCOPE_COL.items():
        name = SCOPE_NAME[scope]
        header(
            ws, DAY_HEADER_FIRST,
            [f"{name} mục tiêu", f"{name} thực tế", "Lũy kế mục tiêu", "Lũy kế thực tế"], c0,
        )  # fmt: skip
        h0 = HELP_COL[scope]
        header(ws, DAY_HEADER_FIRST, [f"{name} nền", f"Δ {name} đang chạy", f"Δ {name} nháp"], h0)
        goal_l, act_l, cum_g, cum_a = (col(c0 + k) for k in range(4))
        nền, run, dr = (col(h0 + k) for k in range(3))
        for i, d in enumerate(data.month_days):
            r = f + i
            put(ws, r, h0, base[scope] / n, MONEY)
            put(ws, r, h0 + 1, sumproduct(f"$A{r}", "run", scope), MONEY)
            put(ws, r, h0 + 2, sumproduct(f"$A{r}", "draft", scope), MONEY)
            put(ws, r, c0, f"={nền}{r}+{run}{r}", MONEY)
            put(ws, r, c0 + 1, actual[scope].get(d), MONEY)
            put(ws, r, c0 + 2, f"=SUM({goal_l}${f}:{goal_l}{r})", MONEY)
            put(ws, r, c0 + 3, f'=IF({act_l}{r}="","",SUM({act_l}${f}:{act_l}{r}))', MONEY)
    for i, d in enumerate(data.month_days):
        put(ws, f + i, 1, d, DATE)
    total = last + 1
    put(ws, total, 1, "Tổng", bold=True)
    for scope, c0 in SCOPE_COL.items():
        for k in (0, 1):
            L = col(c0 + k)
            put(ws, total, c0 + k, f"=SUM({L}{f}:{L}{last})", MONEY, bold=True)
    # the top blocks of the month
    ld = data.last_data_day
    at = f"DATE({ld.year},{ld.month},{ld.day})"
    for scope, top in TOP.items():
        name, c0, h0 = SCOPE_NAME[scope], SCOPE_COL[scope], HELP_COL[scope]
        dr_c = col(h0 + 2)

        def rng(k: int, c0: int = c0) -> str:
            return f"{col(c0 + k)}{f}:{col(c0 + k)}{last}"

        lines = [
            (f"{name} nền", f"=SUM({col(h0)}{f}:{col(h0)}{last})", MONEY),
            (f"Mục tiêu {name} (đang chạy)", f"=SUM({rng(0)})", MONEY),
            (
                f"Mục tiêu {name} nếu áp dụng nháp",
                f"=B{top + 1}+SUM({dr_c}{f}:{dr_c}{last})", MONEY,
            ),
            (f"{name} thực tế đến {ld:%d/%m/%Y}", f"=SUM({rng(1)})", MONEY),
            (
                "% đạt so với mục tiêu đến ngày",
                f'=IFERROR(B{top + 3}/INDEX({rng(2)},MATCH({at},$A{f}:$A{last},0)),"")', PCT,
            ),
        ]  # fmt: skip
        for i, (label, formula, fmt) in enumerate(lines):
            put(ws, top + i, 1, label)
            put(ws, top + i, 2, formula, fmt)
    widths(ws, {1: 44}, 15)
    _hide(ws, *(col(c) for h in HELP_COL.values() for c in range(h, h + 3)))
    finish(ws, f"B{DAY_HEADER_FIRST + 1}")


def _hide(ws, *letters: str) -> None:
    for letter in letters:
        ws.column_dimensions[letter].hidden = True


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
