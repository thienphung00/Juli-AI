"""The report sheets of the Tổng quan export that hold their own rows: "Theo tháng", "KOC",
"Phân tích & đề xuất". Pure builders over plain dataclasses; every figure is an input (read from
the app's own services by ``collect``), the ratios and changes are Excel formulas.

A figure that is unknown is the text "—", never an empty cell or a 0.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from openpyxl import Workbook

from juli_backend.services.exports._style import (
    INT,
    MONEY,
    PCT,
    POINTS,
    TITLE,
    col,
    finish,
    header,
    put,
    widths,
)
from juli_backend.services.exports.report_calc import DASH
from juli_backend.services.metrics.registry import METRICS
from juli_backend.services.shopee_recommendations import kinds

SHEET_MONTH = "Theo tháng"
SHEET_KOC = "KOC"
SHEET_ANALYSIS = "Phân tích & đề xuất"

MONTH_HEADER = [
    "Tháng", "GMV (đ)", "Đơn", "AOV (đ)", "Lợi nhuận (đ)",
    f"{METRICS['cost_marketing'].label_vi} (đ)",
    "Thay đổi GMV", "Thay đổi đơn", "Thay đổi AOV", "Thay đổi lợi nhuận", "Thay đổi chi phí",
]  # fmt: skip
MONTH_FIRST = 4


def _v(x: float | None) -> float | str:
    return DASH if x is None else x


@dataclass
class MonthRow:
    label: str
    gmv: float | None = None
    orders: float | None = None
    profit: float | None = None
    cost: float | None = None


def _change(r: int, c: int, prev_r: int | None) -> str:
    if prev_r is None:
        return DASH
    a, b = f"{col(c)}{r}", f"{col(c)}{prev_r}"
    return f'=IF(AND(ISNUMBER({a}),ISNUMBER({b})),IFERROR({a}/{b}-1,"{DASH}"),"{DASH}")'


def months_sheet(wb: Workbook, title: str, months: Sequence[MonthRow]) -> None:
    """One row per calendar month (the month before first); Thay đổi = against the row above."""
    ws = wb.create_sheet(SHEET_MONTH)
    put(ws, 1, 1, title).font = TITLE
    header(ws, 3, MONTH_HEADER)
    for i, m in enumerate(months):
        r = MONTH_FIRST + i
        prev = None if i == 0 else r - 1
        put(ws, r, 1, m.label)
        put(ws, r, 2, _v(m.gmv), MONEY)
        put(ws, r, 3, _v(m.orders), INT)
        put(
            ws,
            r,
            4,
            f'=IF(AND(ISNUMBER(B{r}),ISNUMBER(C{r})),IFERROR(B{r}/C{r},"{DASH}"),"{DASH}")',
            MONEY,
        )
        put(ws, r, 5, _v(m.profit), MONEY)
        put(ws, r, 6, _v(m.cost), MONEY)
        for k, src in enumerate((2, 3, 4, 5, 6)):
            put(ws, r, 7 + k, _change(r, src, prev), PCT)
    widths(ws, {1: 26}, 16)
    finish(ws, "B4")


# ----------------------------------------------------------------------------- KOC

KOC_HEADER = [
    "KOC", "Kênh", "Đơn", "GMV (đ)", "Hoa hồng (đ)", "Lợi nhuận (đ)", "GMV kỳ trước (đ)",
    "Thay đổi GMV", "Lợi nhuận kỳ trước (đ)", "Thay đổi lợi nhuận", "Chi phí mẫu (đ)",
    f"{METRICS['roi_kol'].label_vi}", "Sản phẩm bán nhiều nhất",
]  # fmt: skip
KOC_FIRST = 4


@dataclass
class KocRow:
    handle: str
    channels: str = DASH
    orders: float | None = None
    gmv: float | None = None
    commission: float | None = None
    profit: float | None = None
    prev_gmv: float | None = None
    prev_profit: float | None = None
    sample_cost: float | None = None
    top_product: str | None = None


@dataclass
class AffiliateShare:
    """Tiếp thị liên kết GMV as a share of the shop's GMV, this period and the one before."""

    gmv: float | None = None
    shop_gmv: float | None = None
    prev_gmv: float | None = None
    prev_shop_gmv: float | None = None
    prev_label: str = "kỳ trước"


def koc_rows(section: Mapping[str, Any]) -> list[KocRow]:
    """One row per KOC from the Phân tích › KOL section (``metric_view.kol_section``): its rows
    (KOC x sản phẩm x kênh) summed, so each figure is the sum of the screen's rows. A figure the
    screen has for none of a KOC's rows stays ``None``."""
    by: dict[str, KocRow] = {}
    chans: dict[str, list[str]] = {}
    best: dict[str, tuple[float, str]] = {}
    for r in section.get("rows") or []:
        key = str(r["kol_key"])
        k = by.setdefault(key, KocRow(str(r.get("handle") or key)))
        for attr, src in (
            ("orders", "orders"), ("gmv", "gmv"), ("commission", "commission"),
            ("profit", "profit"), ("prev_gmv", "prev_gmv"), ("prev_profit", "prev_profit"),
            ("sample_cost", "sample_cost"),
        ):  # fmt: skip
            v = r.get(src)
            if v is not None:
                setattr(k, attr, (getattr(k, attr) or 0.0) + float(v))
        label = r.get("channel_label")
        if label and label not in chans.setdefault(key, []):
            chans[key].append(str(label))
        g = float(r.get("gmv") or 0.0)
        if r.get("product_name") and g >= best.get(key, (-1.0, ""))[0]:
            best[key] = (g, str(r["product_name"]))
    for key, k in by.items():
        k.channels = ", ".join(chans.get(key, [])) or DASH
        k.top_product = best[key][1] if key in best else None
    return sorted(by.values(), key=lambda k: (-(k.gmv or 0.0), k.handle))


def koc_effective_count(rows: Sequence[KocRow]) -> int:
    """KOCs that had at least one affiliate order in the period."""
    return sum(1 for k in rows if k.orders is not None and k.orders > 0)


def koc_sheet(wb: Workbook, title: str, rows: Sequence[KocRow], share: AffiliateShare) -> None:
    ws = wb.create_sheet(SHEET_KOC)
    put(ws, 1, 1, title).font = TITLE
    header(ws, 3, KOC_HEADER)
    r = KOC_FIRST - 1
    for r, k in enumerate(rows, start=KOC_FIRST):
        put(ws, r, 1, k.handle)
        put(ws, r, 2, k.channels)
        put(ws, r, 3, _v(k.orders), INT)
        put(ws, r, 4, _v(k.gmv), MONEY)
        put(ws, r, 5, _v(k.commission), MONEY)
        put(ws, r, 6, _v(k.profit), MONEY)
        put(ws, r, 7, _v(k.prev_gmv), MONEY)
        put(
            ws,
            r,
            8,
            _change(r, 4, None) if k.prev_gmv is None else f'=IFERROR(D{r}/G{r}-1,"{DASH}")',
            PCT,
        )
        put(ws, r, 9, _v(k.prev_profit), MONEY)
        put(
            ws,
            r,
            10,
            DASH if k.prev_profit is None else f'=IFERROR(F{r}/I{r}-1,"{DASH}")',
            PCT,
        )
        put(ws, r, 11, _v(k.sample_cost), MONEY)
        put(
            ws,
            r,
            12,
            f"=IF(AND(ISNUMBER(F{r}),ISNUMBER(E{r}),ISNUMBER(K{r})),"
            f'IFERROR((F{r}-K{r})/(E{r}+K{r}),"{DASH}"),"{DASH}")',
            POINTS,
        )
        put(ws, r, 13, k.top_product or DASH)
    total = r + 1
    put(ws, total, 1, "Tổng", bold=True)
    tot_cols = ((3, INT), (4, MONEY), (5, MONEY), (6, MONEY), (7, MONEY), (9, MONEY), (11, MONEY))
    for c, fmt in tot_cols:
        # no rows: "—" (a SUM over its own cell is circular, and missing is not 0)
        v = f"=SUM({col(c)}{KOC_FIRST}:{col(c)}{r})" if rows else DASH
        put(ws, total, c, v, fmt, bold=True)
    s = total + 2
    put(ws, s, 1, "Số KOC có đơn", bold=True)
    put(ws, s, 2, koc_effective_count(rows), INT, bold=True)
    s += 1
    put(ws, s, 1, "Tiếp thị liên kết so với cả shop", bold=True)
    header(ws, s + 1, ["", "Kỳ này", share.prev_label.capitalize(), "Thay đổi (điểm %)"])
    put(ws, s + 2, 1, "GMV tiếp thị liên kết (đ)")
    put(ws, s + 2, 2, _v(share.gmv), MONEY)
    put(ws, s + 2, 3, _v(share.prev_gmv), MONEY)
    put(ws, s + 3, 1, "GMV cả shop (đ)")
    put(ws, s + 3, 2, _v(share.shop_gmv), MONEY)
    put(ws, s + 3, 3, _v(share.prev_shop_gmv), MONEY)
    put(ws, s + 4, 1, "Tiếp thị liên kết / GMV cả shop")
    for c in (2, 3):
        L = col(c)
        a, b = f"{L}{s + 2}", f"{L}{s + 3}"
        put(
            ws, s + 4, c,
            f'=IF(AND(ISNUMBER({a}),ISNUMBER({b})),IFERROR({a}/{b},"{DASH}"),"{DASH}")',
            PCT,
        )  # fmt: skip
    put(
        ws,
        s + 4,
        4,
        f'=IF(AND(ISNUMBER(B{s + 4}),ISNUMBER(C{s + 4})),B{s + 4}-C{s + 4},"{DASH}")',
        PCT,
    )
    widths(ws, {1: 30, 2: 28, 11: 36}, 16)
    finish(ws, "B4")


# ----------------------------------------------------------------------------- Phân tích & đề xuất

ANALYSIS_HEADER = [
    "Chỉ số quan trọng", "Phạm vi", "Sản phẩm / luồng", "Hiện tại", "Mức tham chiếu",
    "Lệch (%)", "₫ / ngày đang bị ảnh hưởng", "Nguyên nhân (theo Juli)", "Mã thẻ", "Loại thẻ",
    "Dự kiến Δ lợi nhuận (đ)", "Dự kiến Δ GMV (đ)", "Thực tế Δ lợi nhuận (đ)", "Trạng thái",
]  # fmt: skip
ANALYSIS_FIRST = 4
NO_CARD = "Chưa có thẻ"


@dataclass
class AnalysisRow:
    metric: str
    scope: str
    target: str = DASH
    current: float | None = None
    reference: float | None = None
    deviation_pct: float | None = None
    at_stake_per_day: float | None = None
    cause: str = DASH
    card_code: str = NO_CARD
    card_kind: str = DASH
    expected_profit: float | None = None
    expected_gmv: float | None = None
    actual_profit: float | None = None
    status: str = DASH
    extra: dict[str, str] = field(default_factory=dict)


def analysis_sheet(wb: Workbook, title: str, rows: Sequence[AnalysisRow]) -> None:
    """Each row = one critical metric -> one card Juli created for it (a metric without a card is
    one row with "Chưa có thẻ") -> Dự kiến -> Thực tế -> Trạng thái. No text is generated."""
    ws = wb.create_sheet(SHEET_ANALYSIS)
    put(ws, 1, 1, title).font = TITLE
    header(ws, 3, ANALYSIS_HEADER)
    for r, a in enumerate(rows, start=ANALYSIS_FIRST):
        put(ws, r, 1, a.metric)
        put(ws, r, 2, a.scope)
        put(ws, r, 3, a.target)
        put(ws, r, 4, _v(a.current), "#,##0.##")
        put(ws, r, 5, _v(a.reference), "#,##0.##")
        put(ws, r, 6, DASH if a.deviation_pct is None else a.deviation_pct / 100, PCT)
        put(ws, r, 7, _v(a.at_stake_per_day), MONEY)
        put(ws, r, 8, a.cause)
        put(ws, r, 9, a.card_code)
        put(ws, r, 10, a.card_kind)
        put(ws, r, 11, _v(a.expected_profit), MONEY)
        put(ws, r, 12, _v(a.expected_gmv), MONEY)
        put(ws, r, 13, _v(a.actual_profit), MONEY)
        put(ws, r, 14, a.status)
    widths(ws, {1: 24, 3: 34, 8: 50, 10: 24, 14: 18}, 16)
    finish(ws, "D4")


# ----------------------------------------------------------------------------- analysis rows

KPI_LABELS = {
    "views": "Lượt xem", "ctr": "CTR", "ctor": "CTOR", "aov": "AOV", "orders": "Đơn",
    "gmv": "GMV", "bien": "Biên lợi nhuận", "roas": "ROAS", "floor": "Giá sàn",
}  # fmt: skip
LEVEL_LABELS = {"shop": "Cả shop", "flow": "Luồng", "product": "Sản phẩm"}


def _num(x: Any) -> float | None:
    return None if x is None else float(x)


def _fix_labels(change_kinds: Sequence[str]) -> str:
    labels = [kinds.KINDS[k].label for k in change_kinds if k in kinds.KINDS]
    return ", ".join(labels) if labels else DASH


def product_issue_texts(
    items: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[str, str]]:
    """Per product id: (cause, fix) from the critical item with the largest at-stake."""
    best: dict[str, tuple[float, Mapping[str, Any]]] = {}
    for it in items:
        pid = it.get("product_id")
        if not pid:
            continue
        stake = float(it.get("at_stake_per_day") or 0)
        if pid not in best or stake > best[pid][0]:
            best[str(pid)] = (stake, it)
    out: dict[str, tuple[str, str]] = {}
    for pid, (_, it) in best.items():
        cause = str((it.get("cause") or {}).get("text") or DASH)
        fix = _fix_labels(it.get("change_kinds") or [])
        out[pid] = (cause, fix)
    return out


def _aggregate_cards(
    mine: Sequence[Any],
) -> tuple[str, str, float | None, float | None, float | None, str]:
    codes = ", ".join(c.code for c in mine)
    kinds_seen: list[str] = []
    for c in mine:
        if c.kind not in kinds_seen:
            kinds_seen.append(c.kind)
    kind_s = ", ".join(kinds_seen) if kinds_seen else DASH
    if len(mine) == 1:
        c = mine[0]
        exp_p, exp_g, actual = c.profit_mid, c.gmv_mid, c.actual_profit
        status = c.conclusion or c.status
    else:
        exp_p = exp_g = actual = None
        statuses = {c.conclusion or c.status for c in mine}
        status = next(iter(statuses)) if len(statuses) == 1 else DASH
    return codes, kind_s, exp_p, exp_g, actual, status if status else DASH


def analysis_rows(items: Sequence[Mapping[str, Any]], cards: Sequence[Any]) -> list[AnalysisRow]:
    """One row per critical issue (``items`` entry): its cards are listed on that row. Dự kiến Δ
    stays "—" when there is no single card or the card has no figure."""
    out: list[AnalysisRow] = []
    for it in items:
        pid = it.get("product_id")
        kpi = str(it.get("kpi") or "")
        ref = it.get("reference") or {}
        base = AnalysisRow(
            metric=KPI_LABELS.get(kpi, kpi.upper() or DASH),
            scope=LEVEL_LABELS.get(str(it.get("level")), str(it.get("level") or DASH)),
            target=str(it.get("name") or it.get("flow_label") or "Cả shop"),
            current=_num(it.get("current")),
            reference=_num(ref.get("value")),
            deviation_pct=_num(it.get("deviation_pct")),
            at_stake_per_day=_num(it.get("at_stake_per_day")),
            cause=str((it.get("cause") or {}).get("text") or DASH),
        )
        kind_keys = set(it.get("change_kinds") or [])
        mine = [
            c for c in cards if c.kind_key in kind_keys and (pid is None or c.product_id == pid)
        ]
        if not mine:
            out.append(base)
            continue
        code, kind, exp_p, exp_g, actual, status = _aggregate_cards(mine)
        out.append(
            AnalysisRow(
                **{
                    **base.__dict__,
                    "card_code": code,
                    "card_kind": kind,
                    "expected_profit": exp_p,
                    "expected_gmv": exp_g,
                    "actual_profit": actual,
                    "status": status,
                }
            )
        )
    return out
