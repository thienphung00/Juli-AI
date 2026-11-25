"""The "Ghi chú" sheet of the Tổng quan export: how each core metric is computed and where its
figures come from. Text only: no figure, period or name of a shop.

The registry is the source of truth (owner 2026-11-20): the labels are ``METRICS[..].label_vi``,
a derived metric's "Cách tính" is rendered from its registry formula, and "Nguồn số liệu" from the
datasets of the components the formula reads. A platform figure (a bare component) has a
hand-written text, pinned by ``tests/unit/test_export_notes_sheet.py`` to its registry component,
so a registry change fails that test instead of leaving the sheet stale.
"""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Alignment

from juli_backend.services.exports._style import TITLE, finish, header, put, widths
from juli_backend.services.metrics.components import COMPONENTS
from juli_backend.services.metrics.registry import METRICS, Expr, Platform

SHEET_NOTES = "Ghi chú"
NOTES_TITLE = "GHI CHÚ — cách tính các chỉ số"
NOTES_HEADER = ["Chỉ số", "Cách tính", "Nguồn số liệu"]
NOTES_FIRST = 4
SHOPEE = Platform.shopee

#: the metrics the sheet explains, in reading order (every id is a registry metric)
NOTE_METRICS = (
    "gmv", "orders", "aov", "cost_ads", "cost_affiliate", "cost_offers", "cost_marketing",
    "cost_total", "gross_profit", "contribution", "profit", "margin_gross",
    "margin_contribution", "margin",
)  # fmt: skip

#: Vietnamese names of the components a formula reads that are not metrics themselves
COMPONENT_LABELS = {
    "ads_spend": METRICS["cost_ads"].label_vi,
    "affiliate_commission": "Hoa hồng tiếp thị liên kết",
    "cogs": "Giá vốn",
    "packaging": "Đóng gói",
    "fees": "Phí sàn",
    "shipping_net": "Vận chuyển shop chịu (ròng)",
    "other_marketing": "Chi phí marketing khác",
    "net_revenue_known": "Doanh thu thực của đơn đủ chi phí",
}

#: a platform figure is read as is: its text (the registry formula is the bare component)
BASE_TEXT = {
    "gmv": "Tổng giá trị đơn đặt của shop trong kỳ, do Shopee tính sẵn.",
    "orders": "Số đơn đặt của shop trong kỳ, do Shopee tính sẵn.",
    "cost_ads": "Tổng chi phí quảng cáo (DVHT) trong kỳ, mọi ngày kể cả ngày không có đơn.",
    "cost_affiliate": (
        "Tổng hoa hồng của các dòng đơn tiếp thị liên kết đã giao và đủ chi phí trong kỳ."
    ),
}

#: a derived metric whose rendered formula would mislead: the text Session A confirmed (25/11).
#: ROI is left out until its denominator parts are confirmed to share one basis.
OVERRIDE_TEXT = {
    "cost_offers": "Khuyến mãi + Voucher + Combo do shop chịu, trên các đơn không hủy.",
    "profit": (
        "Lợi nhuận đóng góp − Quảng cáo phần của các đơn đủ chi phí và của ngày không có đơn "
        "− Hoa hồng tiếp thị liên kết − Chi phí marketing khác."
    ),
}

#: the margins' base: a component, so it has no registry label
BASE_NOTE = (
    COMPONENT_LABELS["net_revenue_known"],
    "Giá trị đơn sau Khuyến mãi, Voucher, Combo do shop chịu; đơn hoàn được chấp nhận tính bằng "
    "không.",
    "Đơn hàng Shopee",
)

#: what counts as an assumption (no rate, floor or coverage rule here)
ASSUMPTIONS = (
    ("Giả định: Đóng gói", "Chưa nhập thì tính bằng không và ghi là giả định.", "Thông số shop"),
    ("Giả định: Phí sàn", "Chưa quyết toán thì tính theo biểu phí.", "Biểu phí Shopee"),
)

#: where a component's dataset comes from, as the seller knows it
DATASET_TEXT = {
    "shop_overview": "Số liệu tổng quan shop của Shopee",
    "ads_report": "Báo cáo Dịch vụ hiển thị (DVHT)",
    "affiliate_lines": "Dòng đơn tiếp thị liên kết",
    "order_lines": "Đơn hàng Shopee",
    "order_income": "Quyết toán Shopee",
    "shop_rules": "Thông số shop",
}

_OPS = {"sum": " + ", "div": " ÷ ", "mul": " × "}


def label_of(ref: str) -> str:
    return METRICS[ref].label_vi if ref in METRICS else COMPONENT_LABELS[ref]


def render(expr: Expr) -> str:
    """A registry formula as text: operands by label, operators + − × ÷."""
    if isinstance(expr, str):
        return label_of(expr)
    op, *args = expr
    parts = [f"({render(a)})" if isinstance(a, tuple) else render(a) for a in args]
    if op == "sub":
        return " − ".join(parts)
    return _OPS[op].join(parts)


def leaf_components(metric_id: str) -> tuple[str, ...]:
    """The components a metric ends in (through the metrics its formula reads), in order."""
    out: list[str] = []

    def walk(mid: str) -> None:
        f = METRICS[mid].formula
        for ref in (f,) if isinstance(f, str) else _refs(f):
            if ref in COMPONENTS:
                if ref not in out:
                    out.append(ref)
            else:
                walk(ref)

    walk(metric_id)
    return tuple(out)


def _refs(expr: Expr) -> list[str]:
    from juli_backend.services.metrics.registry import refs

    return list(refs(expr))


def note_of(metric_id: str) -> tuple[str, str]:
    """(Cách tính, Nguồn số liệu) of one metric."""
    m = METRICS[metric_id]
    if isinstance(m.formula, str):
        how = BASE_TEXT[metric_id]
    else:
        how = OVERRIDE_TEXT.get(metric_id) or render(m.formula) + "."
    datasets = dict.fromkeys(
        COMPONENTS[c].sources[SHOPEE].dataset for c in leaf_components(metric_id)
    )
    return how, "; ".join(DATASET_TEXT[d] for d in datasets)


def note_rows() -> list[tuple[str, str, str]]:
    """Every row of the sheet: the metrics, the margins' base, the assumptions."""
    rows = [(METRICS[m].label_vi, *note_of(m)) for m in NOTE_METRICS]
    return [*rows, BASE_NOTE, *ASSUMPTIONS]


def notes_sheet(wb: Workbook) -> None:
    ws = wb.create_sheet(SHEET_NOTES)
    put(ws, 1, 1, NOTES_TITLE).font = TITLE
    header(ws, 3, NOTES_HEADER)
    for r, row in enumerate(note_rows(), start=NOTES_FIRST):
        for c, text in enumerate(row, start=1):
            put(ws, r, c, text, bold=c == 1)
            ws.cell(r, c).alignment = Alignment(wrap_text=True, vertical="top")
    widths(ws, {1: 30, 2: 80, 3: 50})
    finish(ws, "A4")
