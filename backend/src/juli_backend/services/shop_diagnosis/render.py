"""The shop diagnosis page: one self-contained Vietnamese HTML file — ADR-108 d.1, 4–10.

Inline CSS and inline SVG only; no script, no external stylesheet or font, no
backend field name, endpoint, file name or code identifier anywhere on the page
(notes explain each calculation in words). CSS classes and element ids are
hyphenated so the page carries no snake_case token at all; a test pins it.

Page order: Bước 1 GMV theo 5 kênh → Bước 2 phễu từng kênh → Bước 3 dòng thời gian
→ Bước 4 năm sản phẩm chủ lực → các mục cấp shop → ghi chú.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from html import escape

from juli_backend.services.optimize_product.live_video import Appearance
from juli_backend.services.shop_diagnosis.channels import CHANNEL_LABELS, Channel
from juli_backend.services.shop_diagnosis.confidence import Confidence
from juli_backend.services.shop_diagnosis.decomposition import (
    FACTOR_LABELS,
    Conclusion,
    FunnelComparison,
)
from juli_backend.services.shop_diagnosis.heroes import ENTERED, RANKING_LABELS
from juli_backend.services.shop_diagnosis.promotions import (
    Band,
    FlashAnalysis,
    OrderDiscountShare,
    PromoKind,
    VoucherSummary,
)
from juli_backend.services.shop_diagnosis.report import (
    ChannelRow,
    HeroProfile,
    ShopDiagnosis,
)
from juli_backend.services.shop_diagnosis.timeline import ChannelTimeline, RollingPoint

NOT_PROVIDED = "TikTok không cung cấp"
ESTIMATED = "ước tính"
BUY_NOW = "khách mua ngay"
CTOR_DIRECT = "gồm khách mua thẳng"
SALE_DAY = "Ngày sale nền tảng"

# --------------------------------------------------------------------------
# number formatting (Vietnamese: "." thousands, "," decimals)
# --------------------------------------------------------------------------


def _vn(text: str) -> str:
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def num(value: float | None, decimals: int | None = None) -> str:
    if value is None:
        return "—"
    if decimals is None:
        decimals = 0 if abs(value) >= 100 else 1
    return _vn(f"{value:,.{decimals}f}")


def money(value: float | None) -> str:
    return "—" if value is None else _vn(f"{round(value):,}") + " ₫"


def signed_money(value: float | None) -> str:
    if value is None:
        return "—"
    return ("+" if value >= 0 else "−") + money(abs(value))


def pct(value: float | None, decimals: int = 2) -> str:
    return "—" if value is None else _vn(f"{value * 100:.{decimals}f}") + " %"


def change(prior: float | None, last: float | None) -> tuple[str, str]:
    """``(text, css class)`` of the relative change ``last / prior − 1``."""
    if prior is None or last is None or prior == 0:
        return "—", "flat"
    ratio = last / prior - 1
    css = "up" if ratio > 0.005 else "down" if ratio < -0.005 else "flat"
    sign = "+" if ratio >= 0 else "−"
    return f"{sign}{_vn(f'{abs(ratio) * 100:.1f}')} %", css


def _chip(prior: float | None, last: float | None) -> str:
    text, css = change(prior, last)
    return f'<span class="chg {css}">{text}</span>'


def _conf(label: Confidence | None) -> str:
    if label is None:
        return '<span class="conf conf-none">—</span>'
    css = {
        Confidence.CLEAR: "conf-clear",
        Confidence.REFERENCE: "conf-ref",
        Confidence.INSUFFICIENT: "conf-none",
    }[label]
    return f'<span class="conf {css}">{escape(label.value)}</span>'


def _d(day: date) -> str:
    return day.strftime("%d/%m")


def _dy(day: date) -> str:
    return day.strftime("%d/%m/%Y")


# --------------------------------------------------------------------------
# styles
# --------------------------------------------------------------------------

CSS = """
:root{--bg:#f4f6f8;--surface:#fff;--fg:#16202a;--muted:#5c6b78;--line:#d6dde4;--accent:#0b6e6e;
--accent-soft:#e0f1ef;--good:#1d7a45;--good-soft:#e2f4e8;--bad:#b23a2e;--bad-soft:#fbe7e4;
--flat:#6b7682;--flat-soft:#eceff2;--warn:#8a5a00;--warn-soft:#fff3d6;--c0:#0b6e6e;--c1:#3f8fd1;
--c2:#b07ad6;--c3:#e08a2c;--c4:#8a9a3a;--flash:#e08a2c;--disc:#3f8fd1;--vouch:#b07ad6}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#0f1519;--surface:#161e24;
--fg:#e8eef2;--muted:#9fb0bd;--line:#2a3640;--accent:#4fc1b7;--accent-soft:#143634;--good:#7fd49a;
--good-soft:#163a24;--bad:#f2928a;--bad-soft:#3d1f1c;--flat:#a5b0ba;--flat-soft:#232d35;
--warn:#f0c060;--warn-soft:#3a2e12;--c0:#4fc1b7;--c1:#6fb2ea;--c2:#c79ee6;--c3:#f0a95a;--c4:#b5c460;
--flash:#f0a95a;--disc:#6fb2ea;--vouch:#c79ee6;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0f1519;--surface:#161e24;--fg:#e8eef2;--muted:#9fb0bd;--line:#2a3640;
--accent:#4fc1b7;--accent-soft:#143634;--good:#7fd49a;--good-soft:#163a24;--bad:#f2928a;
--bad-soft:#3d1f1c;--flat:#a5b0ba;--flat-soft:#232d35;--warn:#f0c060;--warn-soft:#3a2e12;
--c0:#4fc1b7;--c1:#6fb2ea;--c2:#c79ee6;--c3:#f0a95a;--c4:#b5c460;--flash:#f0a95a;--disc:#6fb2ea;
--vouch:#c79ee6;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,-apple-system,"Segoe UI",
Roboto,sans-serif;font-size:14px;line-height:1.5;padding:28px 16px 60px}
.wrap{max-width:1240px;margin:0 auto;display:grid;gap:28px}
h1,h2,h3,h4{margin:0;text-wrap:balance}h1{font-size:clamp(24px,4vw,34px);font-weight:800}
h2{font-size:20px;font-weight:800}h3{font-size:16px;font-weight:700}h4{font-size:14px;
font-weight:700}
.eyebrow{font-size:12px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
font-weight:600}
.lede{margin:0;max-width:85ch;color:var(--muted)}
.nav{display:flex;flex-wrap:wrap;gap:8px}.nav a{font-size:13px;padding:4px 10px;border:1px
solid var(--line);
border-radius:999px;color:var(--fg);text-decoration:none;background:var(--surface)}
.nav a:hover,.nav a:focus-visible{border-color:var(--accent)}
section.step{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px;
display:grid;gap:14px;min-width:0}
.hero{border-top:4px solid var(--accent)}
.tbl{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:13px}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}
th:first-child,td:first-child,th.t,td.t{text-align:left}
th{font-size:12px;color:var(--muted);font-weight:600}
tr.group td{font-weight:700;background:var(--accent-soft)}
tr.sub td:first-child{padding-left:26px;color:var(--muted)}
tr.total td{font-weight:800;border-top:2px solid var(--fg)}
.chg{display:inline-block;font-size:11.5px;font-weight:600;padding:0 6px;border-radius:999px}
.chg.up{background:var(--good-soft);color:var(--good)}.chg.down{background:var(--bad-soft);
color:var(--bad)}
.chg.flat{background:var(--flat-soft);color:var(--flat)}
.conf{display:inline-block;font-size:11px;font-weight:600;padding:0 6px;border-radius:4px;
white-space:nowrap}
.conf-clear{background:var(--accent);color:var(--surface)}.conf-ref{background:var(--warn-soft);
color:var(--warn)}
.conf-none{background:var(--flat-soft);color:var(--flat)}
.note{font-size:12px;color:var(--muted)}
.warn{background:var(--warn-soft);color:var(--warn);border-radius:8px;padding:8px 12px;
font-weight:600}
.verdict{display:grid;gap:4px;padding:12px;border-radius:10px;background:var(--accent-soft)}
.verdict .v{font-weight:800;font-size:15px}
.rows{display:grid;gap:10px;overflow-x:auto}
.frow{display:grid;grid-template-columns:170px 1fr;gap:6px 12px;align-items:center;border:1px
solid var(--line);
border-radius:10px;padding:10px;min-width:1100px}
.frow .cn{font-weight:800}.frow .cs{font-size:11.5px;color:var(--muted)}
.flow{display:grid;grid-template-columns:repeat(9,minmax(0,1fr));gap:4px}
.box{border:1px solid var(--line);border-radius:8px;padding:6px;text-align:center;
font-variant-numeric:tabular-nums}
.box.na{opacity:.6}.box .bl{font-size:11px;color:var(--muted)}.box .bv{font-weight:800;
font-size:14px}
.box .bp{font-size:11px;color:var(--muted)}
.frow .contrib{grid-column:2}
.contrib{font-size:12.5px;display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--muted)}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;
vertical-align:-1px}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px}
.chart{border:1px solid var(--line);border-radius:8px;padding:6px}
.chart .ct{font-size:12px;font-weight:600}.chart svg{width:100%;height:auto;display:block}
.lane-label{font-size:10px;fill:var(--muted)}
.tags{display:flex;flex-wrap:wrap;gap:4px}.tag{font-size:11px;border:1px solid var(--line);
border-radius:999px;padding:0 6px}
ul.notes{margin:0;padding-left:18px;display:grid;gap:4px}
footer{font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:12px}
"""


# --------------------------------------------------------------------------
# step 1 — GMV by channel
# --------------------------------------------------------------------------


def _gmv_row(label: str, comparison: FunnelComparison, share: float | None, css: str = "") -> str:
    p, q = comparison.prior.gmv, comparison.last.gmv
    return (
        f'<tr class="{css}"><td>{escape(label)}</td><td>{money(p)}</td><td>{money(q)}</td>'
        f"<td>{signed_money(q - p)} {_chip(p, q)}</td><td>{pct(share, 0)}</td>"
        f"<td>{_conf(comparison.gmv_confidence)}</td></tr>"
    )


def _stacked_bars(report: ShopDiagnosis) -> str:
    """Two horizontal stacked bars of the four additive channels, prior and last."""
    rows = [r for r in report.channels if r.additive]
    colors = ["var(--c0)", "var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)"]
    scale = max(report.total.prior.gmv, report.total.last.gmv) or 1
    width, bar = 760, 26
    parts = [f'<svg viewBox="0 0 {width} 92" role="img" aria-label="GMV mỗi ngày theo kênh">']
    for i, (label, attr) in enumerate((("30 ngày trước", "prior"), ("30 ngày gần đây", "last"))):
        y = 8 + i * 42
        parts.append(f'<text x="0" y="{y + 18}" class="lane-label">{label}</text>')
        x = 110.0
        for j, row in enumerate(rows):
            value = getattr(row.comparison, attr).gmv
            w = (width - 120) * value / scale
            parts.append(
                f'<rect x="{x:.1f}" y="{y}" width="{max(w, 0):.1f}" height="{bar}" '
                f'fill="{colors[j]}"><title>{escape(CHANNEL_LABELS[row.channel])}: '
                f"{money(value)}</title></rect>"
            )
            x += w
    parts.append("</svg>")
    legend = "".join(
        f'<span><i style="background:{colors[j]}"></i>{escape(CHANNEL_LABELS[r.channel])}</span>'
        for j, r in enumerate(rows)
    )
    return f'<div class="legend">{legend}</div>' + "".join(parts)


def _step1(report: ShopDiagnosis) -> str:
    by_channel = {r.channel: r for r in report.channels}
    body: list[str] = []
    for group in report.groups:
        body.append(_gmv_row(group.label, group.comparison, group.share_of_change, "group"))
        for channel in group.channels:
            row = by_channel[channel]
            label = CHANNEL_LABELS[channel] + (" *" if not row.additive else "")
            body.append(_gmv_row(label, row.comparison, row.share_of_change))
            if channel is Channel.AFFILIATE:
                for sub in report.affiliate_rows:
                    body.append(_gmv_row(CHANNEL_LABELS[sub.channel], sub.comparison, None, "sub"))
    body.append(_gmv_row("Tất cả kênh (toàn shop)", report.total, 1.0, "total"))
    return f"""
<section class="step" id="buoc-1">
<p class="eyebrow">Bước 1</p><h2>GMV của shop chia theo 5 kênh</h2>
<p class="lede">GMV trung bình mỗi ngày của từng kênh trong 30 ngày gần đây so với 30 ngày trước,
và phần mỗi kênh góp vào thay đổi GMV của cả shop. Hai nhóm: <b>Nhóm khách tự tìm đến</b> (nơi việc
sửa trang sản phẩm, giá và voucher tác động; CTOR là chỉ số chính) và <b>Nhóm nội dung</b> (lượt
hiển thị sản phẩm và GMV là chỉ số chính).</p>
{_stacked_bars(report)}
<div class="tbl"><table>
<thead><tr><th>Kênh</th><th>GMV/ngày · 30 ngày trước</th><th>GMV/ngày · 30 ngày gần đây</th>
<th>Thay đổi</th><th>Góp vào thay đổi GMV shop</th><th>Mức tin cậy</th></tr></thead>
<tbody>{"".join(body)}</tbody></table></div>
<p class="note">* Tab Cửa hàng được TikTok báo riêng và trùng một phần với các kênh khác, nên không
cộng vào tổng shop; cột "góp vào thay đổi" của bốn kênh còn lại cộng lại đúng bằng thay đổi của
shop.
Dòng Nhóm khách tự tìm đến cộng cả Tab Cửa hàng.</p>
</section>"""


# --------------------------------------------------------------------------
# step 2 — funnels
# --------------------------------------------------------------------------


def _box(label: str, prior: str, last: str, chip: str, extra: str = "", na: bool = False) -> str:
    css = "box na" if na else "box"
    return (
        f'<div class="{css}"><div class="bl">{escape(label)}</div><div class="bv">{last}</div>'
        f'<div class="bp">trước: {prior}</div>{chip}{extra}</div>'
    )


def _note(text: str) -> str:
    return f'<div class="bp">{escape(text)}</div>'


def _funnel_boxes(channel: Channel, c: FunnelComparison) -> str:
    p, q = c.prior, c.last
    boxes = [
        _box(
            "Lượt hiển thị sản phẩm",
            num(p.impressions),
            num(q.impressions),
            _chip(p.impressions, q.impressions),
        ),
        _box("CTR (Tỷ lệ nhấp)", pct(p.ctr), pct(q.ctr), _chip(p.ctr, q.ctr)),
        _box("Lượt nhấp vào sản phẩm", num(p.clicks), num(q.clicks), _chip(p.clicks, q.clicks)),
    ]
    if p.add_to_cart is None or q.add_to_cart is None:
        boxes.append(_box("Tỷ lệ thêm vào giỏ hàng", "—", NOT_PROVIDED, "", na=True))
        boxes.append(_box("Số lượt thêm vào giỏ hàng", "—", NOT_PROVIDED, "", na=True))
    else:
        boxes.append(
            _box(
                "Tỷ lệ thêm vào giỏ hàng",
                pct(p.add_to_cart_rate),
                pct(q.add_to_cart_rate),
                _chip(p.add_to_cart_rate, q.add_to_cart_rate),
            )
        )
        boxes.append(
            _box(
                "Số lượt thêm vào giỏ hàng",
                num(p.add_to_cart),
                num(q.add_to_cart),
                _chip(p.add_to_cart, q.add_to_cart),
            )
        )
    if p.sku_orders is None or q.sku_orders is None:
        boxes += [_box(k, "—", "—", "", na=True) for k in ("Đơn hàng SKU", "CTOR", "AOV (SKU)")]
    else:
        orders_note = _note(ESTIMATED) if p.orders_estimated else ""
        if channel in (Channel.SELLER_VIDEO, Channel.SELLER_LIVE):
            orders_note = _note(f"đơn trên thêm giỏ: {BUY_NOW}")
        ctor_note = (
            _note(CTOR_DIRECT) if channel in (Channel.SELLER_VIDEO, Channel.SELLER_LIVE) else ""
        )
        boxes.append(
            _box(
                "Đơn hàng SKU",
                num(p.sku_orders),
                num(q.sku_orders),
                _chip(p.sku_orders, q.sku_orders),
                orders_note,
            )
        )
        boxes.append(_box("CTOR", pct(p.ctor), pct(q.ctor), _chip(p.ctor, q.ctor), ctor_note))
        boxes.append(_box("AOV (SKU)", money(p.aov), money(q.aov), _chip(p.aov, q.aov)))
    boxes.append(_box("GMV", money(p.gmv), money(q.gmv), _chip(p.gmv, q.gmv)))
    return '<div class="flow">' + "".join(boxes) + "</div>"


def _contrib_line(c: FunnelComparison) -> str:
    if not c.factors or c.factors[0].contribution is None:
        return (
            '<div class="contrib note">Không tách được thay đổi GMV thành bốn yếu tố '
            "(một kỳ không có đơn).</div>"
        )
    items = "".join(
        f"<span>{escape(FACTOR_LABELS[f.factor])}: <b>{signed_money(f.contribution)}</b> "
        f"{_conf(f.confidence)}</span>"
        for f in c.factors
    )
    return (
        f'<div class="contrib"><span class="note">Góp vào thay đổi GMV/ngày '
        f"({signed_money(c.gmv_change)}):</span>{items}</div>"
    )


def _funnel_row(
    label: str, sub: str, channel: Channel, c: FunnelComparison, contrib: bool = True
) -> str:
    return (
        f'<div class="frow"><div><div class="cn">{escape(label)}</div><div '
        f'class="cs">{escape(sub)}</div></div>'
        f"{_funnel_boxes(channel, c)}{_contrib_line(c) if contrib else ''}</div>"
    )


def _sub_rows_table(rows: Iterable[ChannelRow]) -> str:
    body = "".join(
        f"<tr class='sub'><td>{escape(CHANNEL_LABELS[r.channel])}</td>"
        f"<td>{num(r.comparison.prior.impressions)} → {num(r.comparison.last.impressions)}</td>"
        f"<td>{pct(r.comparison.prior.ctr)} → {pct(r.comparison.last.ctr)}</td>"
        f"<td>{num(r.comparison.prior.clicks)} → {num(r.comparison.last.clicks)}</td>"
        f"<td>{money(r.comparison.prior.gmv)} → {money(r.comparison.last.gmv)}</td></tr>"
        for r in rows
    )
    return (
        "<div class='tbl'><table><thead><tr><th>Liên kết chia theo</th><th>Lượt hiển thị sản "
        "phẩm</th>"
        "<th>CTR (Tỷ lệ nhấp)</th><th>Lượt nhấp vào sản phẩm</th><th>GMV</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


SUBTITLES = {
    Channel.PRODUCT_CARD: "Nhóm khách tự tìm đến · CTOR là chỉ số chính",
    Channel.SHOP_TAB: "Nhóm khách tự tìm đến · không có số liệu thêm vào giỏ",
    Channel.SELLER_VIDEO: "Nhóm nội dung · CTOR chỉ để tham khảo",
    Channel.SELLER_LIVE: "Nhóm nội dung · CTOR chỉ để tham khảo",
    Channel.AFFILIATE: "Nhóm nội dung · chỉ để hiểu toàn shop",
    Channel.TOTAL: "Toàn shop",
}


def _step2(report: ShopDiagnosis) -> str:
    rows = [_funnel_row("Tất cả kênh", SUBTITLES[Channel.TOTAL], Channel.TOTAL, report.total)]
    rows += [
        _funnel_row(CHANNEL_LABELS[r.channel], SUBTITLES[r.channel], r.channel, r.comparison)
        for r in report.channels
    ]
    return f"""
<section class="step" id="buoc-2">
<p class="eyebrow">Bước 2</p><h2>Phễu của từng kênh: từ lượt hiển thị sản phẩm đến GMV</h2>
<p class="lede">Mỗi ô ghi số trung bình mỗi ngày của 30 ngày gần đây, số của 30 ngày trước và mức
thay đổi. Thay đổi GMV của mỗi kênh được tách thành bốn phần: Lượt hiển thị sản phẩm, CTR, CTOR và
AOV (SKU); bốn phần cộng lại đúng bằng thay đổi GMV.</p>
<div class="rows">{"".join(rows)}</div>
{_sub_rows_table(report.affiliate_rows)}
<p class="note">Video và LIVE liên kết không có số đơn riêng nên không có CTOR.</p>
</section>"""


# --------------------------------------------------------------------------
# step 3 — timeline
# --------------------------------------------------------------------------

CHART_W, CHART_H, PAD = 300, 96, 6


def _x(index: int, count: int) -> float:
    return PAD + (CHART_W - 2 * PAD) * index / max(count - 1, 1)


def _line_chart(
    title: str,
    days: list[date],
    points: dict[date, float | None],
    fmt,
    flash_days: set[date],
    boundary: date,
    sale: list[date],
) -> str:
    values = [v for v in points.values() if v is not None]
    parts = [f'<div class="chart"><div class="ct">{escape(title)}</div>']
    parts.append(
        f'<svg viewBox="0 0 {CHART_W} {CHART_H + 14}" role="img" aria-label="{escape(title)}">'
    )
    n = len(days)
    step = (CHART_W - 2 * PAD) / max(n - 1, 1)
    for i, day in enumerate(days):
        if day in flash_days:
            parts.append(
                f'<rect x="{_x(i, n) - step / 2:.1f}" y="0" width="{step:.1f}" height="{CHART_H}" '
                'fill="var(--flash)" opacity="0.13"/>'
            )
        if day in sale:
            parts.append(
                f'<line x1="{_x(i, n):.1f}" x2="{_x(i, n):.1f}" y1="0" y2="{CHART_H}" '
                'stroke="var(--bad)" stroke-dasharray="2 2"><title>' + SALE_DAY + "</title></line>"
            )
        if day == boundary:
            parts.append(
                f'<line x1="{_x(i, n):.1f}" x2="{_x(i, n):.1f}" y1="0" y2="{CHART_H}" '
                'stroke="var(--muted)" stroke-width="1"/>'
            )
    if values:
        lo, hi = min(values), max(values)
        span = (hi - lo) or abs(hi) or 1
        segments: list[list[str]] = [[]]
        for i, day in enumerate(days):
            value = points.get(day)
            if value is None:
                segments.append([])
                continue
            y = PAD + (CHART_H - 2 * PAD) * (1 - (value - lo) / span)
            segments[-1].append(f"{_x(i, n):.1f},{y:.1f}")
        for seg in segments:
            if len(seg) > 1:
                parts.append(
                    f'<polyline points="{" ".join(seg)}" fill="none" stroke="var(--accent)" '
                    'stroke-width="1.8"/>'
                )
        parts.append(
            f'<text x="{PAD}" y="{CHART_H + 12}" class="lane-label">thấp nhất {fmt(lo)} · cao '
            f"nhất {fmt(hi)}</text>"
        )
    else:
        parts.append(
            f'<text x="{PAD}" y="{CHART_H / 2}" class="lane-label">Không có số liệu</text>'
        )
    parts.append("</svg></div>")
    return "".join(parts)


LANE_COLORS = {
    PromoKind.FLASH: "var(--flash)",
    PromoKind.DISCOUNT: "var(--disc)",
    PromoKind.VOUCHER: "var(--vouch)",
}


def _band_strip(days: list[date], bands: Iterable[Band], coverage: dict[date, float]) -> str:
    """Three lanes over the 60 days: flash coverage per day, product discounts, vouchers."""
    width, lane = 900, 16
    n = len(days)
    left = 130
    usable = width - left - 10
    step = usable / max(n, 1)
    index = {d: i for i, d in enumerate(days)}
    parts = [
        f'<svg viewBox="0 0 {width} {3 * (lane + 6) + 20}" role="img" aria-label="Lịch khuyến mãi">'
    ]
    lanes = (PromoKind.FLASH, PromoKind.DISCOUNT, PromoKind.VOUCHER)
    for row, kind in enumerate(lanes):
        y = row * (lane + 6)
        parts.append(f'<text x="0" y="{y + 12}" class="lane-label">{escape(kind.value)}</text>')
        parts.append(
            f'<rect x="{left}" y="{y}" width="{usable:.1f}" height="{lane}" '
            'fill="var(--flat-soft)"/>'
        )
        if kind is PromoKind.FLASH:
            for day, share in coverage.items():
                if share > 0 and day in index:
                    parts.append(
                        f'<rect x="{left + index[day] * step:.1f}" y="{y}" width="{step:.1f}" '
                        f'height="{lane}" '
                        f'fill="{LANE_COLORS[kind]}" opacity="{0.25 + 0.75 * share:.2f}">'
                        f"<title>{_d(day)}: {pct(share, 0)} thời gian có flash sale</title></rect>"
                    )
            continue
        for band in bands:
            if band.kind is not kind or band.first not in index or band.last not in index:
                continue
            x = left + index[band.first] * step
            w = (index[band.last] - index[band.first] + 1) * step
            parts.append(
                f'<rect x="{x:.1f}" y="{y + 3}" width="{w:.1f}" height="{lane - 6}" '
                f'fill="{LANE_COLORS[kind]}" '
                f'opacity="0.7"><title>{escape(band.title)}: '
                f"{_d(band.first)}–{_d(band.last)}</title></rect>"
            )
    y = 3 * (lane + 6) + 12
    for i, day in enumerate(days):
        if i % 7 == 0 or i == n - 1:
            parts.append(
                f'<text x="{left + i * step:.1f}" y="{y}" class="lane-label">{_d(day)}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _bands_table(bands: Iterable[Band]) -> str:
    rows = [b for b in bands if b.kind is not PromoKind.FLASH]
    if not rows:
        return '<p class="note">Không có giảm giá sản phẩm hay voucher nào trong 60 ngày.</p>'
    body = "".join(
        f"<tr><td>{escape(b.kind.value)}</td><td "
        f"class='t'>{escape(b.title)}</td><td>{_d(b.first)}</td>"
        f"<td>{_d(b.last)}</td><td>{b.days_prior}</td><td>{b.days_last}</td></tr>"
        for b in rows
    )
    return (
        "<div class='tbl'><table><thead><tr><th>Loại</th><th "
        "class='t'>Tên</th><th>Từ</th><th>Đến</th>"
        "<th>Số ngày trong 30 ngày trước</th><th>Số ngày trong 30 ngày gần đây</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def _flash_count(bands: Iterable[Band]) -> str:
    flashes = [b for b in bands if b.kind is PromoKind.FLASH]
    if not flashes:
        return "Không có flash sale nào trong 60 ngày."
    prior = sum(1 for b in flashes if b.days_prior)
    last = sum(1 for b in flashes if b.days_last)
    return (
        f"{len(flashes)} đợt flash sale trong 60 ngày ({prior} đợt chạm 30 ngày trước, "
        f"{last} đợt chạm 30 ngày gần đây)."
    )


def _depth(true_depth: float | None) -> str:
    if true_depth is not None and true_depth < 0:
        return f"<b>giá flash cao hơn giá đang giảm sẵn {pct(-true_depth, 1)}</b>"
    return f"<b>{pct(true_depth, 1)}</b>"


def _flash_section(flash: FlashAnalysis, bands: Iterable[Band], shop_level: bool) -> str:
    weekly = "".join(
        f"<tr><td>tuần từ {_d(monday)}</td><td>{pct(share, 0)}</td></tr>"
        for monday, share in flash.weekly
    )
    cells = "".join(
        f"<tr><td>{escape(c.group.value)}</td><td>{c.days}</td><td>{num(c.sku_orders, 0)}</td>"
        + (
            f"<td>{pct(c.ctor)}</td><td>{pct(c.orders_per_cart, 1)}</td>"
            if c.sufficient
            else f"<td>{_conf(Confidence.INSUFFICIENT)}</td>"
            f"<td>{_conf(Confidence.INSUFFICIENT)}</td>"
        )
        + "</tr>"
        for c in flash.cells
    )
    flags = "".join(f'<span class="tag">{escape(f.value)}</span>' for f in flash.flags) or (
        '<span class="note">Không có cờ nào.</span>'
    )
    scope = "toàn shop" if shop_level else "sản phẩm này"
    unattributed = (
        f'<p class="note">{flash.unattributed} đợt flash sale không có danh sách sản phẩm; '
        "các đợt này được tính là áp dụng cho mọi sản phẩm.</p>"
        if flash.unattributed
        else ""
    )
    days = (
        f"30 ngày trước: {flash.flash_days_prior} ngày flash; "
        f"30 ngày gần đây: {flash.flash_days_last} ngày flash"
    )
    return f"""
<h4>Flash sale ({scope})</h4>
<p>{escape(_flash_count(bands))} Thời gian có flash sale: {pct(flash.coverage_prior, 0)} của 30
ngày trước,
{pct(flash.coverage_last, 0)} của 30 ngày gần đây ({days}).
Độ sâu thật (giá flash so với giá đã giảm sẵn): {_depth(flash.true_depth)}; so với giá
niêm yết:
{pct(flash.list_depth, 1)}.</p>
<div class="tags">{flags}</div>{unattributed}
<div class="charts"><div class="tbl"><table><thead><tr><th>Tuần</th><th>Thời gian có flash
sale</th></tr></thead>
<tbody>{weekly}</tbody></table></div>
<div class="tbl"><table><thead><tr><th>Nhóm ngày (Thẻ sản phẩm của người bán)</th><th>Số ngày</th>
<th>Đơn hàng SKU</th><th>CTOR</th><th>Đơn trên lượt thêm vào
giỏ</th></tr></thead><tbody>{cells}</tbody>
</table></div></div>"""


def _voucher_section(summary: VoucherSummary) -> str:
    if summary.yardstick is None:
        return '<h4>Voucher</h4><p class="note">Không đủ đơn một món để phân loại voucher.</p>'
    stick = summary.yardstick
    rows = "".join(
        f"<tr><td>{escape(a.voucher.title)}</td><td class='t'>{escape(a.voucher_class.value)}"
        f"{' · Riêng sản phẩm' if a.specific_products else ''}</td>"
        f"<td>{money(a.voucher.threshold) if a.voucher.threshold else 'không có'}</td>"
        f"<td>{_d(a.first)}–{_d(a.last)}</td><td>{pct(a.discount_share, 1)}</td>"
        f"<td>{pct(a.near_threshold_share, 0)}</td>"
        f"<td>{pct(a.above_before, 0)} → {pct(a.above_after, 0)}</td>"
        f"<td>{a.redemptions_upper} đơn · {money(a.cost_upper)}</td>"
        f"<td>{'chưa tách được khỏi flash sale' if a.overlaps_flash else ''}</td></tr>"
        for a in summary.live
    )
    older = "".join(
        f"<tr><td>{escape(month)}</td><td class='t'>{escape(label)}</td><td>{count}</td></tr>"
        for month, label, count in summary.older_by_month
    )
    older_table = (
        "<div class='tbl'><table><thead><tr><th>Tháng bắt đầu</th><th "
        "class='t'>Loại</th><th>Số voucher</th></tr>"
        f"</thead><tbody>{older}</tbody></table></div>"
        if older
        else ""
    )
    return f"""
<h4>Voucher</h4>
<p>Giá một món phổ biến (30 ngày gần đây): <b>{money(stick.common_price)}</b>, từ
{stick.sample} đơn một món;
75 % đơn một món có giá trị từ {money(stick.closing_cut)} trở lên.</p>
<div class="tbl"><table><thead><tr><th>Voucher</th><th class="t">Loại</th><th>Ngưỡng
đơn</th><th>Thời gian</th>
<th>Mức giảm so với giá một món</th><th>Đơn sát dưới ngưỡng</th><th>Đơn đạt ngưỡng: trước → sau
khi bắt đầu</th>
<th>Số lượt dùng tối đa (ước tính)</th><th>Ghi
chú</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="note">Dữ liệu đơn không cho biết đơn nào dùng voucher nào, nên số lượt dùng và chi
phí là mức tối đa:
mọi đơn đạt ngưỡng trong thời gian voucher chạy.</p>
{older_table}"""


TIMELINE_METRICS = (
    ("Lượt hiển thị sản phẩm", "impressions", lambda v: num(v)),
    ("CTR (Tỷ lệ nhấp)", "ctr", lambda v: pct(v)),
    ("CTOR", "ctor", lambda v: pct(v)),
    ("AOV (SKU)", "aov", lambda v: money(v)),
)


def _timeline_panel(timeline: ChannelTimeline, report: ShopDiagnosis, flash_days: set[date]) -> str:
    days = report.windows.all_days()
    by_day: dict[date, RollingPoint] = {p.day: p for p in timeline.points}
    charts = "".join(
        _line_chart(
            title,
            days,
            {d: getattr(by_day[d], attr) if d in by_day else None for d in days},
            fmt,
            flash_days,
            report.windows.last_first,
            list(report.sale_days),
        )
        for title, attr, fmt in TIMELINE_METRICS
    )
    return f"<h3>{escape(CHANNEL_LABELS[timeline.channel])}</h3><div class='charts'>{charts}</div>"


def _step3(report: ShopDiagnosis) -> str:
    flash = report.shop_flash
    flash_days = {d for d, s in flash.coverage.items() if s >= 0.5}
    panels = "".join(_timeline_panel(t, report, flash_days) for t in report.timelines)
    return f"""
<section class="step" id="buoc-3">
<p class="eyebrow">Bước 3</p><h2>Dòng thời gian sự kiện</h2>
<p class="lede">Đây là phần duy nhất xem theo ngày. Mỗi đường là trung bình 7 ngày liền trước
của từng
kênh; nền cam là ngày có flash sale, vạch dọc liền là ngày bắt đầu 30 ngày gần đây, vạch đỏ nét
đứt là
ngày sale nền tảng.</p>
<div class="legend"><span><i style="background:var(--flash)"></i>Flash sale (đậm hơn = chạy lâu
hơn trong ngày)</span>
<span><i style="background:var(--disc)"></i>Giảm giá sản phẩm</span><span><i
style="background:var(--vouch)"></i>Voucher</span></div>
{_band_strip(report.windows.all_days(), report.shop_bands, flash.coverage)}
{_bands_table(report.shop_bands)}
{panels}
{_flash_section(flash, report.shop_bands, True)}
{_voucher_section(report.vouchers)}
</section>"""


# --------------------------------------------------------------------------
# step 4 — hero products
# --------------------------------------------------------------------------

KPI_ROWS: tuple[tuple[str, str, str], ...] = (
    ("Lượt hiển thị sản phẩm", "impressions", "num"),
    ("CTR (Tỷ lệ nhấp)", "ctr", "pct"),
    ("Lượt nhấp vào sản phẩm", "clicks", "num"),
    ("Tỷ lệ thêm vào giỏ hàng", "add_to_cart_rate", "pct"),
    ("Số lượt thêm vào giỏ hàng", "add_to_cart", "num"),
    ("Đơn hàng SKU", "sku_orders", "num"),
    ("CTOR", "ctor", "pct"),
    ("AOV (SKU)", "aov", "money"),
    ("GMV", "gmv", "money"),
    ("Số món trên đơn", "items_per_order", "dec"),
    ("Hoàn tiền ÷ GMV", "refund_share", "pct"),
)


def _fmt(kind: str, value: float | None) -> str:
    if kind == "pct":
        return pct(value)
    if kind == "money":
        return money(value)
    if kind == "dec":
        return num(value, 2)
    return num(value)


def _kpi_confidence(comparison: FunnelComparison, attr: str) -> Confidence | None:
    by_attr = {
        "impressions": comparison.factors[0].confidence,
        "ctr": comparison.factors[1].confidence,
        "ctor": comparison.factors[2].confidence,
        "aov": comparison.factors[3].confidence,
        "gmv": comparison.gmv_confidence,
        "add_to_cart_rate": comparison.add_to_cart_rate_confidence,
    }
    return by_attr.get(attr)


def _kpi_table(comparison: FunnelComparison, with_extras: bool = True) -> str:
    body = []
    for label, attr, kind in KPI_ROWS:
        if not with_extras and attr in ("items_per_order", "refund_share"):
            continue
        prior = getattr(comparison.prior, attr)
        last = getattr(comparison.last, attr)
        if prior is None and last is None:
            body.append(f"<tr><td>{escape(label)}</td><td colspan='4'>{NOT_PROVIDED}</td></tr>")
            continue
        body.append(
            f"<tr><td>{escape(label)}</td><td>{_fmt(kind, prior)}</td><td>{_fmt(kind, last)}</td>"
            f"<td>{_chip(prior, last)}</td><td>{_conf(_kpi_confidence(comparison, attr))}</td></tr>"
        )
    return (
        "<div class='tbl'><table><thead><tr><th>Chỉ số (trung bình mỗi ngày)</th><th>30 ngày "
        "trước</th>"
        "<th>30 ngày gần đây</th><th>Thay đổi</th><th>Mức tin cậy</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _verdict(conclusion: Conclusion) -> str:
    return (
        f'<div class="verdict"><div class="v">{escape(conclusion.headline)}</div>'
        f"<div><b>Cần xem tiếp:</b> {escape(conclusion.look_next)}</div></div>"
    )


def _cell(prior: float | None, last: float | None, fmt) -> str:
    if prior is None and last is None:
        return "—"
    return f"{fmt(prior)} → {fmt(last)}"


def _channel_table(profile: HeroProfile) -> str:
    rows = []
    for r in profile.channels:
        p, q = r.comparison.prior, r.comparison.last
        if p.add_to_cart is None:
            cart = NOT_PROVIDED
        else:
            cart = _cell(p.add_to_cart_rate, q.add_to_cart_rate, pct)
        orders = _cell(p.sku_orders, q.sku_orders, num) + (
            f" ({ESTIMATED})" if p.orders_estimated else ""
        )
        ctor = _cell(p.ctor, q.ctor, pct)
        if r.channel in (Channel.SELLER_VIDEO, Channel.SELLER_LIVE):
            ctor += f" ({CTOR_DIRECT})"
        tags = "".join(f'<span class="tag">{escape(t)}</span>' for t in r.tags)
        rows.append(
            f"<tr><td>{escape(CHANNEL_LABELS[r.channel])}</td>"
            f"<td>{_cell(p.impressions, q.impressions, num)}</td>"
            f"<td>{_cell(p.ctr, q.ctr, pct)}</td><td>{_cell(p.clicks, q.clicks, num)}</td>"
            f"<td>{cart}</td>"
            f"<td>{orders}</td><td>{ctor}</td><td>{_cell(p.aov, q.aov, money)}</td>"
            f"<td>{_cell(p.gmv, q.gmv, money)}</td><td class='t'><div "
            f"class='tags'>{tags}</div></td></tr>"
        )
        if r.channel is Channel.AFFILIATE:
            for sub in profile.affiliate_rows:
                sp, sq = sub.comparison.prior, sub.comparison.last
                rows.append(
                    f"<tr class='sub'><td>{escape(CHANNEL_LABELS[sub.channel])}</td>"
                    f"<td>{_cell(sp.impressions, sq.impressions, num)}</td>"
                    f"<td>{_cell(sp.ctr, sq.ctr, pct)}</td>"
                    f"<td>{_cell(sp.clicks, sq.clicks, num)}</td>"
                    "<td></td><td></td><td></td><td></td>"
                    f"<td>{_cell(sp.gmv, sq.gmv, money)}</td><td></td></tr>"
                )
    return (
        "<div class='tbl'><table><thead><tr><th>Kênh</th><th>Lượt hiển thị sản "
        "phẩm</th><th>CTR (Tỷ lệ nhấp)</th>"
        "<th>Lượt nhấp vào sản phẩm</th><th>Tỷ lệ thêm vào giỏ hàng</th><th>Đơn hàng "
        "SKU</th><th>CTOR</th>"
        "<th>AOV (SKU)</th><th>GMV</th><th class='t'>Nhận xét</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _share_table(profile: HeroProfile) -> str:
    body = "".join(
        f"<tr><td>{escape(CHANNEL_LABELS[ch])}{' *' if ch is Channel.SHOP_TAB else ''}</td>"
        f"<td>{pct(a, 0)}</td><td>{pct(b, 0)}</td></tr>"
        for ch, (a, b) in profile.gmv_share.items()
    )
    return (
        "<div class='tbl'><table><thead><tr><th>Tỷ trọng GMV theo kênh</th><th>30 ngày trước</th>"
        f"<th>30 ngày gần đây</th></tr></thead><tbody>{body}</tbody></table></div>"
    )


def _discount_table(prior: OrderDiscountShare, last: OrderDiscountShare) -> str:
    return (
        "<div class='tbl'><table><thead><tr><th>Giảm giá trên đơn</th><th>30 ngày trước</th>"
        "<th>30 ngày gần đây</th></tr></thead><tbody>"
        f"<tr><td>Số món đã bán (theo đơn)</td><td>{prior.items}</td><td>{last.items}</td></tr>"
        "<tr><td>Món có giảm giá từ "
        f"TikTok</td><td>{pct(prior.platform_share, 0)}</td>"
        f"<td>{pct(last.platform_share, 0)}</td></tr>"
        "<tr><td>Món có giảm giá từ người "
        f"bán</td><td>{pct(prior.seller_share, 0)}</td><td>{pct(last.seller_share, 0)}</td></tr>"
        "</tbody></table></div>"
    )


def _slash_date(iso_day: str) -> str:
    """``2025-11-03`` → ``03/11/2025``; anything else is shown as given."""
    try:
        return _dy(date.fromisoformat(iso_day))
    except ValueError:
        return iso_day


def _appearance_list(title: str, items: Iterable[Appearance], none_count: int, unit: str) -> str:
    rows = "".join(
        f"<tr><td>{escape(a.title) or '(không tên)'}</td><td>{escape(_slash_date(a.day))}</td>"
        f"<td>{a.orders}</td></tr>"
        for a in items
    )
    body = (
        f"<div class='tbl'><table><thead><tr><th>{escape(title)}</th><th>Ngày</th>"
        f"<th>{escape(unit)}</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        if rows
        else f"<p class='note'>Không có {escape(title.lower())} nào có đơn của sản phẩm này.</p>"
    )
    return (
        body + f"<p class='note'>{none_count} {escape(title.lower())} "
        "có sản phẩm nhưng không có đơn.</p>"
    )


def _promo_bars(profile: HeroProfile, report: ShopDiagnosis) -> str:
    return _band_strip(
        report.windows.all_days(), profile.bands, profile.flash.coverage
    ) + _bands_table(profile.bands)


def _hero(profile: HeroProfile, report: ShopDiagnosis) -> str:
    title = profile.title or f"Sản phẩm {profile.rank}"
    a = profile.appearances
    return f"""
<section class="step hero" id="san-pham-{profile.rank}">
<p class="eyebrow">Sản phẩm chủ lực {profile.rank}</p><h2>{escape(title)}</h2>
<h3>1. Kết luận</h3>{_verdict(profile.conclusion)}
<p class="note">{escape(profile.content_note)}</p>
<h3>2. Chỉ số 30 ngày gần đây so với 30 ngày trước (mọi kênh)</h3>
{_kpi_table(profile.total)}{_share_table(profile)}
<h3>3. Phễu theo từng kênh</h3>
<p><b>Cách đọc:</b> {escape(profile.reading)}</p>
{_channel_table(profile)}
<p class="note">Nhóm khách tự tìm đến (Thẻ sản phẩm của người bán và Tab Cửa hàng), phần góp
vào thay đổi GMV:</p>
{_contrib_line(profile.self_search)}
<h3>4. Khuyến mãi trên sản phẩm này</h3>
{_promo_bars(profile, report)}
{_flash_section(profile.flash, profile.bands, False)}
<h3>5. Giảm giá trên đơn</h3>
{_discount_table(profile.discounts_prior, profile.discounts_last)}
<h3>6. LIVE và video có nhiều đơn nhất</h3>
{_appearance_list("Phiên LIVE", a.top_live, a.live_without_orders, "Đơn hàng SKU")}
{_appearance_list("Video", a.top_videos, a.videos_without_orders, "Số món bán (từ khi đăng)")}
</section>"""


def _step4(report: ShopDiagnosis) -> str:
    sel = report.selection
    movers = "".join(
        f"<li>{escape(report.titles.get(pid) or 'Sản phẩm chưa có tên')}: "
        f"{'vào top' if move == ENTERED else 'rơi khỏi top'}</li>"
        for pid, move in sel.movers
    )
    dispersed = (
        '<p class="warn">Shop phân tán, top 5 chưa đại diện: năm sản phẩm chỉ chiếm '
        f"{pct(sel.gmv_share, 0)} GMV.</p>"
        if sel.dispersed
        else ""
    )
    return f"""
<section class="step" id="buoc-4">
<p class="eyebrow">Bước 4</p><h2>Năm sản phẩm chủ lực</h2>
<p class="lede">Xếp hạng theo: <b>{escape(RANKING_LABELS[sel.ranking])}</b> (GMV mọi kênh). Năm
sản phẩm chiếm
{pct(sel.gmv_share, 0)} GMV của shop trong khoảng xếp hạng. Kết luận của mỗi sản phẩm dựa trên
Nhóm khách tự
tìm đến; chỉ yếu tố có mức tin cậy "Rõ" mới được chọn làm nguyên nhân chính.</p>
{dispersed}
{"<p>Thay đổi trong top 5 giữa hai kỳ:</p><ul>" + movers + "</ul>" if movers else ""}
</section>
{"".join(_hero(p, report) for p in report.profiles)}"""


# --------------------------------------------------------------------------
# shop-level sections and notes
# --------------------------------------------------------------------------


def _shop_sections(report: ShopDiagnosis) -> str:
    self_search = next(g for g in report.groups if g.label == "Nhóm khách tự tìm đến")
    watch_rows = "".join(
        f"<tr><td>{escape(w.title or 'Sản phẩm chưa có tên')}</td><td "
        f"class='t'>{escape(w.reason)}</td>"
        f"<td>{money(w.gmv_prior)}</td><td>{money(w.gmv_last)}</td></tr>"
        for w in report.watch
    )
    watch = (
        "<div class='tbl'><table><thead><tr><th>Sản phẩm</th><th class='t'>Lý "
        "do</th><th>GMV/ngày · 30 ngày trước</th>"
        f"<th>GMV/ngày · 30 ngày gần đây</th></tr></thead><tbody>{watch_rows}</tbody></table></div>"
        if watch_rows
        else '<p class="note">Không có sản phẩm nào ngoài top 5 thay đổi đáng kể.</p>'
    )
    return f"""
<section class="step" id="chi-so-shop">
<p class="eyebrow">Toàn shop</p><h2>Chỉ số trung bình của shop</h2>
<h3>Tất cả kênh</h3>{_kpi_table(report.total)}
<h3>Nhóm khách tự tìm đến</h3>{_kpi_table(self_search.comparison, with_extras=False)}
{_contrib_line(self_search.comparison)}
</section>
<section class="step" id="phan-con-lai">
<p class="eyebrow">Toàn shop</p><h2>Phần còn lại ngoài top 5</h2>
{_verdict(report.rest_conclusion)}
<h3>Tất cả kênh</h3>{_kpi_table(report.rest_total)}
<h3>Nhóm khách tự tìm đến</h3>{_kpi_table(report.rest_self_search, with_extras=False)}
{_contrib_line(report.rest_self_search)}
</section>
<section class="step" id="can-theo-doi">
<p class="eyebrow">Toàn shop</p><h2>Sản phẩm cần theo dõi</h2>{watch}
</section>"""


NOTES = (
    "Mọi số trong bảng là trung bình mỗi ngày của từng khoảng 30 ngày, cộng từ số liệu từng "
    "ngày của TikTok.",
    "Tỷ lệ của một khoảng thời gian được tính từ tổng của khoảng đó (ví dụ CTR = tổng lượt "
    "nhấp chia tổng lượt "
    "hiển thị), giống cách Trung tâm người bán tính, không lấy trung bình các tỷ lệ từng ngày.",
    "CTR = lượt nhấp vào sản phẩm chia lượt hiển thị sản phẩm. Tỷ lệ thêm vào giỏ hàng = số "
    "lượt thêm vào giỏ "
    "chia lượt nhấp. CTOR = đơn hàng SKU chia lượt nhấp. AOV (SKU) = GMV chia đơn hàng SKU.",
    "GMV là GMV của TikTok, đã gồm đơn bị hủy và hoàn tiền; không trừ gì thêm.",
    "Thay đổi GMV được tách thành bốn phần theo tỷ lệ lôgarit của từng yếu tố; bốn phần cộng "
    "lại đúng bằng "
    "thay đổi GMV.",
    "Tab Cửa hàng không có số liệu thêm vào giỏ hàng; đơn hàng SKU của kênh này được ước tính "
    "bằng CTOR nhân "
    "lượt nhấp. Kênh này trùng một phần với các kênh khác nên không cộng vào tổng shop.",
    "Ở Video và LIVE của người bán, khách thường mua ngay không qua giỏ hàng, nên CTOR gồm cả "
    "khách mua thẳng.",
    'Mức tin cậy: "Rõ" khi mỗi kỳ có từ 30 đơn trở lên và khoảng tin cậy 90 % của chênh lệch '
    "không chứa 0; "
    '"Tham khảo" khi một kỳ có 10 đến 29 đơn hoặc chênh lệch nằm trong biên độ nhiễu; "Chưa đủ '
    'dữ liệu" khi '
    "một kỳ có dưới 10 đơn. Tỷ lệ dùng kiểm định hai tỷ lệ; lượt hiển thị, GMV và AOV dùng "
    "chuỗi số từng ngày.",
    "Kết luận sản phẩm: GMV đổi dưới 10 % là Ổn định; dưới 30 đơn hàng SKU trong một kỳ là "
    "Chưa đủ dữ liệu; nếu "
    "yếu tố lớn nhất là lượt hiển thị thì xét yếu tố tiếp theo; nếu là CTOR thì tách thành "
    "trước giỏ (tỷ lệ thêm "
    "vào giỏ) và sau giỏ (đơn trên lượt thêm vào giỏ).",
    "Một ngày là ngày flash sale khi flash sale chạy từ nửa ngày trở lên. Độ sâu thật so giá "
    "flash với giá đã "
    "giảm sẵn bởi chương trình giảm giá sản phẩm đang chạy, không so với giá niêm yết.",
    "Voucher được phân loại theo cấu hình (ngưỡng đơn, phạm vi, số lượt) so với giá một món "
    "phổ biến, là trung vị "
    "giá trị các đơn một món trong 30 ngày gần đây; không dựa vào tên voucher.",
    "Ngày sale nền tảng (ngày trùng tháng như 9/9, 10/10) được đánh dấu, không bị loại khỏi số "
    "liệu.",
    "Số liệu đơn hàng lấy theo ngày tạo đơn, theo giờ Việt Nam.",
)


def _notes(report: ShopDiagnosis) -> str:
    missing = (
        f"<li>Thiếu số liệu {len(report.missing_days)} ngày: "
        f"{', '.join(_d(d) for d in report.missing_days)}; trung bình chỉ tính trên các ngày "
        "có số liệu.</li>"
        if report.missing_days
        else ""
    )
    orders = (
        ""
        if report.orders_present
        else "<li>Chưa có dữ liệu đơn hàng: các mục voucher và giảm giá trên đơn bị bỏ trống.</li>"
    )
    items = "".join(f"<li>{escape(n)}</li>" for n in NOTES)
    return f"""
<section class="step" id="ghi-chu"><p class="eyebrow">Ghi chú</p><h2>Cách tính</h2>
<ul class="notes">{items}{missing}{orders}</ul></section>"""


def render_html(report: ShopDiagnosis) -> str:
    w = report.windows
    sale = ", ".join(_d(d) for d in report.sale_days) or "không có"
    shop = escape(report.shop_name) if report.shop_name else "shop"
    nav = "".join(
        f'<a href="#{anchor}">{escape(label)}</a>'
        for anchor, label in (
            ("buoc-1", "Bước 1 · GMV theo kênh"),
            ("buoc-2", "Bước 2 · Phễu"),
            ("buoc-3", "Bước 3 · Dòng thời gian"),
            ("buoc-4", "Bước 4 · Sản phẩm chủ lực"),
            ("chi-so-shop", "Chỉ số shop"),
            ("phan-con-lai", "Ngoài top 5"),
            ("can-theo-doi", "Cần theo dõi"),
            ("ghi-chu", "Ghi chú"),
        )
    )
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1">
<title>Chẩn đoán shop {shop}</title><style>{CSS}</style></head>
<body><main class="wrap">
<header><p class="eyebrow">Báo cáo nội bộ · không gửi nguyên văn cho người bán</p>
<h1>Chẩn đoán shop {shop}</h1>
<p class="lede">30 ngày gần đây: {_dy(w.last_first)}–{_dy(w.last_last)} · 30 ngày trước:
{_dy(w.prior_first)}–{_dy(w.prior_last)}.
Mọi số trong bảng là trung bình mỗi ngày. Ngày sale nền tảng trong 60 ngày: {sale}.</p>
<nav class="nav">{nav}</nav></header>
{_step1(report)}{_step2(report)}{_step3(report)}{_step4(report)}{_shop_sections(report)}{_notes(report)}
<footer>Số liệu từ TikTok Shop, đọc ở chế độ chỉ đọc. Trang này không đề xuất hành động; mỗi
sản phẩm kết thúc
bằng kết luận và chỗ cần xem tiếp.</footer>
</main></body></html>
"""
