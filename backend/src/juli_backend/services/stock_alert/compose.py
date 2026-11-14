"""The stock e-mail (Part S): subject, HTML and text parts. Pure, no DB, no network.

Three kinds: ``alert`` (n SKU sắp hết hàng), ``empty`` (none), ``no_read`` (Juli has no usable
stock read). One row per variation: "{product} · {variation}", then "Còn 42 · Bán ~6/ngày · Hết
khoảng 22/11 (còn 7 ngày)", or "Đã hết hàng từ 13/11 · Bán ~6/ngày". No image, no card line, no
restock quantity. One button "Mở Juli"; the footer says when the stock was read (and how many
orders were subtracted since) and carries the member's own "Huỷ nhận email này" link.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from juli_backend.models.stock_alert import KIND_ALERT, KIND_EMPTY, KIND_NO_READ
from juli_backend.services.stock_alert.eligibility import AlertRow
from juli_backend.services.stock_alert.stock_basis import local

PREFIX = "[Juli - Báo cáo tồn kho]"
NO_READ_BODY = "Mở Seller Centre trên Chrome để Juli Connector đọc tồn kho."
BUTTON = "Mở Juli"
UNSUBSCRIBE = "Huỷ nhận email này"


def dm(d: date) -> str:
    return f"{d.day:02d}/{d.month:02d}"


def dm_hm(at: datetime) -> str:
    """Naive UTC -> "15/11 06:31" in GMT+7."""
    t = local(at)
    return f"{t.day:02d}/{t.month:02d} {t.hour:02d}:{t.minute:02d}"


def per_day(u: float) -> str:
    """6.0 -> "6", 0.5 -> "0,5", 12.4 -> "12"."""
    if u >= 10:
        return str(round(u))
    text = f"{u:.1f}".replace(".", ",")
    return text[:-2] if text.endswith(",0") else text


def subject(kind: str, n: int, today: date, *, no_read_since: date | None = None) -> str:
    if kind == KIND_NO_READ:
        return f"{PREFIX} Juli chưa đọc được tồn kho từ {dm(no_read_since or today)}"
    if kind == KIND_EMPTY or n == 0:
        return f"{PREFIX} Không có SKU sắp hết hàng trên Shopee · {dm(today)}"
    return f"{PREFIX} {n} SKU sắp hết hàng trên Shopee · {dm(today)}"


def row_title(r: AlertRow) -> str:
    f = r.facts
    return f"{f.product_name} · {f.variation_name}" if f.variation_name else f.product_name


def row_line(r: AlertRow) -> str:
    rate = f"Bán ~{per_day(r.facts.base)}/ngày"
    if r.out_of_stock:
        return f"Đã hết hàng từ {dm(r.out_since or date.today())} · {rate}"
    fc = r.forecast
    assert fc.runs_out_on is not None and fc.days_left is not None
    return (
        f"Còn {r.facts.stock} · {rate} · Hết khoảng {dm(fc.runs_out_on)} (còn {fc.days_left} ngày)"
    )


def read_line(read_at: datetime | None, deducted_orders: int) -> str | None:
    if read_at is None:
        return None
    line = f"Tồn kho đọc lúc {dm_hm(read_at)}"
    return f"{line} · đã trừ {deducted_orders} đơn từ lúc đó" if deducted_orders else line


@dataclass(frozen=True)
class Composed:
    subject: str
    text: str
    html: str


def compose(
    kind: str,
    rows: Sequence[AlertRow],
    *,
    today: date,
    alert_days: int,
    open_url: str,
    unsubscribe_url: str,
    read_at: datetime | None = None,
    deducted_orders: int = 0,
    no_read_since: date | None = None,
) -> Composed:
    subj = subject(kind, len(rows), today, no_read_since=no_read_since)
    if kind == KIND_NO_READ:
        body = [NO_READ_BODY]
    elif kind == KIND_EMPTY or not rows:
        body = [f"Tất cả SKU còn đủ hàng hơn {alert_days} ngày."]
    else:
        body = []
    items = [] if kind != KIND_ALERT else [(row_title(r), row_line(r)) for r in rows]
    footer = read_line(read_at, deducted_orders) if kind != KIND_NO_READ else None

    text_lines: list[str] = []
    text_lines += body
    for title, line in items:
        text_lines += [title, line, ""]
    text_lines += ["", f"{BUTTON}: {open_url}", ""]
    if footer:
        text_lines.append(footer)
    text_lines.append(f"{UNSUBSCRIBE}: {unsubscribe_url}")
    text = "\n".join(text_lines).strip() + "\n"

    e = html.escape
    parts = [
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1f2328;'
        'max-width:560px">'
    ]
    parts += [f'<p style="margin:0 0 16px">{e(b)}</p>' for b in body]
    for title, line in items:
        parts.append(
            '<div style="padding:10px 0;border-bottom:1px solid #e5e7eb">'
            f'<div style="font-weight:600">{e(title)}</div>'
            f'<div style="color:#57606a">{e(line)}</div></div>'
        )
    parts.append(
        f'<p style="margin:20px 0"><a href="{e(open_url, quote=True)}" '
        'style="display:inline-block;background:#ee4d2d;color:#ffffff;text-decoration:none;'
        f'padding:10px 18px;border-radius:8px;font-weight:600">{e(BUTTON)}</a></p>'
    )
    small = 'style="margin:4px 0;color:#6e7781;font-size:12px"'
    if footer:
        parts.append(f"<p {small}>{e(footer)}</p>")
    parts.append(
        f'<p {small}><a href="{e(unsubscribe_url, quote=True)}" style="color:#6e7781">'
        f"{e(UNSUBSCRIBE)}</a></p>"
    )
    parts.append("</div>")
    return Composed(subj, text, "".join(parts))


__all__ = ["Composed", "compose", "dm", "dm_hm", "per_day", "row_line", "row_title", "subject"]
