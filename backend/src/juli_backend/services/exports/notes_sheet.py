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
    "cost_total", "roi", "gross_profit", "contribution", "profit", "margin_gross",
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
        "Tổng hoa hồng trả cho tiếp thị liên kết (TTLK) trên các dòng đơn có cờ TTLK trong kỳ."
    ),
}

#: where a component's dataset comes from, as the seller knows it
DATASET_TEXT = {
    "shop_overview": "Số liệu tổng quan shop của Shopee",
    "ads_report": "Báo cáo Dịch vụ hiển thị (DVHT)",
    "affiliate_lines": "Dòng đơn tiếp thị liên kết",
    "order_lines": "File đơn hàng",
    "order_income": "File thu nhập",
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
    how = BASE_TEXT[metric_id] if isinstance(m.formula, str) else render(m.formula) + "."
    datasets = dict.fromkeys(
        COMPONENTS[c].sources[SHOPEE].dataset for c in leaf_components(metric_id)
    )
    return how, "; ".join(DATASET_TEXT[d] for d in datasets)


def notes_sheet(wb: Workbook) -> None:
    ws = wb.create_sheet(SHEET_NOTES)
    put(ws, 1, 1, NOTES_TITLE).font = TITLE
    header(ws, 3, NOTES_HEADER)
    for i, metric_id in enumerate(NOTE_METRICS):
        r = NOTES_FIRST + i
        how, source = note_of(metric_id)
        put(ws, r, 1, METRICS[metric_id].label_vi, bold=True)
        put(ws, r, 2, how)
        put(ws, r, 3, source)
        for c in (1, 2, 3):
            ws.cell(r, c).alignment = Alignment(wrap_text=True, vertical="top")
    widths(ws, {1: 30, 2: 80, 3: 50})
    finish(ws, "A4")
