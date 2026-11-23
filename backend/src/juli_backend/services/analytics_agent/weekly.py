"""The weekly analysis ("tuần sau shop nên làm gì?"): a free question answered in sections by
code, from the same readers every other answer uses. No template id, no LLM numbers.

Sections: this week vs last week vs a normal week (a sale week is never the baseline); ads ROAS
against ROAS hoà vốn; under-budget days with 0 orders; the traffic source that fell; product
share, margin change and titles naming an ended deal; giá vốn gaps; then the actions, each an
existing Đề xuất card (duplicates flagged) or a Juli DRAFT card. The agent never sends or
executes anything.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from juli_backend.services.analytics_agent import cards as cardstage
from juli_backend.services.analytics_agent import fmt
from juli_backend.services.analytics_agent.chains import bucket
from juli_backend.services.analytics_agent.entities import (
    campaign_order,
    campaign_row,
    campaign_verdict,
)
from juli_backend.services.analytics_agent.registry_reads import roas as registry_roas
from juli_backend.services.analytics_agent.types import (
    CardEnginePort,
    DataPort,
    JevPort,
    LabelTable,
)
from juli_backend.services.analytics_agent.windows import (
    anchor_for,
    build_windows,
    clip_to_freshness,
    is_sale_day,
    sale_days_vi,
)

PRESET = "last_full_week_vs_week_before"
TOP = 5
_DEAL_IN_TITLE = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?!\d)")
_COVERAGE_OK = 99.5


def _sum(rows: list[dict[str, Any]], key: str, win: tuple[date, date]) -> float | None:
    vals = [
        r[key]
        for r in rows
        if win[0] <= r["day"] <= win[1] and r.get("complete", True) and r.get(key) is not None
    ]
    return float(sum(vals)) if vals else None


def rng(win: tuple[date, date]) -> str:
    """ "16–22/11" or "30/10–05/11": a date range, never a relative word."""
    a, b = win
    return f"{a:%d}–{b:%d/%m}" if (a.month, a.year) == (b.month, b.year) else f"{a:%d/%m}–{b:%d/%m}"


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _section(w: Any, latest: date, title: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "data_answer",
        "kind": "top_products",  # the UI's ranked-list kind: label / value / detail rows
        "title_vi": title,
        "window_vi": w.label(),
        "fresh_vi": f"Số liệu đến hết {latest:%d/%m}",
        "rows": rows,
        "stop": "data_answer",
    }
    if sale := sale_days_vi(w):
        out["sale_vi"] = sale
    return out


def ended_deal_in(title: str, today: date) -> str | None:
    """A "11.11" / "12/12" in a listing title whose sale day is already over (a stale deal)."""
    for m in _DEAL_IN_TITLE.finditer(title or ""):
        d, mo = int(m.group(1)), int(m.group(2))
        if d == mo and 1 <= mo <= 12:
            try:
                day = date(today.year, mo, d)
            except ValueError:
                continue
            if day < today and is_sale_day(day):
                return m.group(0)
    return None


def _same_change(open_card: dict[str, Any], kind: str, item: str | None, title: str | None) -> str:
    """ "same" = kind + target (+ the change itself); "kind" = same kind and target, other change;
    "" = none. (The target value is the card's `change_after`.)"""
    if cardstage.coarse(open_card["kind"]) != cardstage.coarse(kind):
        return ""
    if (open_card.get("item_id") or None) != (item or None):
        return ""
    same = open_card["kind"] == kind and bool(title) and open_card.get("change_after") == title
    return "same" if same else "kind"


async def run_weekly(
    data: DataPort,
    engine: CardEnginePort | None,
    jev: JevPort,
    labels: LabelTable,
    as_of: date,
) -> tuple[list[dict[str, Any]], cardstage.CardOutcome]:
    """The events of the analysis ([] = no shop data) and the draft cards made."""
    out = cardstage.CardOutcome()
    rows = await data.shop_daily(as_of)
    latest = max((r["day"] for r in rows if r["complete"]), default=None)
    if latest is None:
        return [], out
    w = build_windows(PRESET, anchor_for(PRESET, as_of, latest), sale_aware=True)
    w = clip_to_freshness(w, latest)  # no sum past the day the footer names
    assert w.prev is not None
    last_week = w.sale_prev or w.prev  # the week before, sale or not
    events: list[dict[str, Any]] = []
    actions: list[tuple[str, str | None, str]] = []  # (kind, item, why)

    # 1. this week vs last week vs a normal week
    def val(metric: str, win: tuple[date, date]) -> float | None:
        if metric == "roas":
            g, c = _sum(rows, "ads_gmv", win), _sum(rows, "ads_spend", win)
            return registry_roas(g, c) if g is not None and c else None
        return _sum(rows, metric, win)

    table = []
    for m, label in (
        ("gmv", "GMV"),
        ("orders", "Đơn"),
        ("ads_spend", "Chi phí QC"),
        ("roas", "ROAS"),
    ):
        now, lw, nw = val(m, w.cur), val(m, last_week), val(m, w.prev)
        detail = f"{rng(last_week)} {fmt.value(m, lw)}"
        if w.sale_prev:
            detail += f" (có ngày sale) · {rng(w.prev)} {fmt.value(m, nw)}"
        table.append(
            {
                "label_vi": label,
                "value_vi": fmt.value(m, now),
                "detail_vi": detail,
                "delta": fmt.delta(m, now, nw),
            }
        )
    title = f"{rng(w.cur)} so với {rng(last_week)}"
    if w.sale_prev:
        title += f" và tuần thường {rng(w.prev)}"
    events.append(_section(w, latest, title, table))

    # 2. ads ROAS vs ROAS hoà vốn (registry), per campaign
    camps = await data.campaign_rows(*w.cur)
    below = [c for c in camps if campaign_verdict(c) == "Lỗ"]
    if camps:
        events.append(
            _section(
                w,
                latest,
                "Quảng cáo: ROAS so với ROAS hoà vốn",
                [
                    campaign_row(c, "Dưới hoà vốn · " if c in below else "")
                    for c in sorted(camps, key=campaign_order)[:TOP]
                ],
            )
        )
    for c in below[:2]:
        actions.append(("ads_roas_target", None, f"{c['name']} dưới ROAS hoà vốn"))

    # 3. under-budget days with 0 orders
    orders_by_day = {r["day"]: r.get("orders") for r in rows if w.cur[0] <= r["day"] <= w.cur[1]}
    idle = [
        b
        for b in await data.budget_days(*w.cur)
        if b["budget"] is not None
        and float(b["spend"]) < float(b["budget"])
        and (orders_by_day.get(b["day"]) in (0, 0.0))
    ]
    if idle:
        events.append(
            _section(
                w,
                latest,
                "Ngày chi dưới ngân sách và không có đơn",
                [
                    {
                        "label_vi": f"{b['day']:%d/%m}",
                        "value_vi": fmt.value("ads_spend", _f(b["spend"])),
                        "detail_vi": f"ngân sách {fmt.value('ads_spend', _f(b['budget']))}",
                    }
                    for b in idle
                ],
            )
        )
        actions.append(("ads_budget", None, "ngày chi dưới ngân sách không có đơn"))

    # 4. which traffic source fell
    def by_source(win: tuple[date, date], srows: list[dict[str, Any]]) -> dict[str, float]:
        t: dict[str, float] = {}
        for r in srows:
            if win[0] <= r["day"] <= win[1] and r.get("gmv") is not None:
                t[bucket(r["source"])] = t.get(bucket(r["source"]), 0.0) + float(r["gmv"])
        return t

    srows = await data.source_daily(w.prev[0], w.cur[1])
    sn, sb = by_source(w.cur, srows), by_source(w.prev, srows)
    fell = sorted(
        ((k, sn.get(k, 0.0) - v) for k, v in sb.items() if sn.get(k, 0.0) < v), key=lambda t: t[1]
    )
    if fell:
        events.append(
            _section(
                w,
                latest,
                "Kênh lưu lượng giảm",
                [
                    {
                        "label_vi": labels.source(k),
                        "value_vi": "▼ " + fmt.value("gmv", abs(d)),
                        "detail_vi": f"{fmt.value('gmv', sb[k])} → "
                        f"{fmt.value('gmv', sn.get(k, 0.0))}",
                    }
                    for k, d in fell[:TOP]
                ],
            )
        )

    # 5 + 6. products: share, margin change, stale deal titles; giá vốn gaps
    cur: dict[str, float] = {}
    for r in await data.product_daily(*w.cur):
        cur[r["item_id"]] = cur.get(r["item_id"], 0.0) + float(r["gmv"] or 0)
    total = sum(cur.values())
    top = sorted(cur, key=lambda k: -cur[k])[:TOP]
    names = await data.item_names(top)
    prow, gaps = [], []
    for k in top:
        now_p = await data.product_profit(k, *w.cur)
        old_p = await data.product_profit(k, *w.prev)
        parts = [f"{100 * cur[k] / total:.0f}% GMV".replace(".", ",")] if total else []
        m_now = _f(now_p["margin_pct"]) if now_p else None
        m_old = _f(old_p["margin_pct"]) if old_p else None
        if m_now is not None and m_old is not None:
            parts.append("biên " + fmt.delta("margin", m_now / 100, m_old / 100)["text_vi"])
        stale = ended_deal_in(names.get(k, ""), as_of + timedelta(days=1))
        if stale:
            parts.append(f"tên còn “{stale}” đã hết")
            actions.append(("title", k, f"tên sản phẩm còn “{stale}”"))
        if (
            now_p
            and now_p.get("coverage_pct") is not None
            and float(now_p["coverage_pct"]) < _COVERAGE_OK
        ):
            gaps.append(k)
        prow.append(
            {
                "label_vi": names.get(k, k),
                "value_vi": fmt.value("gmv", cur[k]),
                "detail_vi": " · ".join(parts),
                "link": {"kind": "product", "item_id": k},
            }
        )
    if prow:
        events.append(_section(w, latest, "Sản phẩm: tỷ trọng, biên và tên", prow))
    if gaps:
        events.append(
            _section(
                w,
                latest,
                "Thiếu giá vốn: lợi nhuận chưa đáng tin",
                [
                    {
                        "label_vi": names.get(k, k),
                        "value_vi": "Hãy điền giá vốn",
                        "detail_vi": "",
                    }
                    for k in gaps
                ],
            )
        )

    # 7. actions -> an existing Đề xuất card (duplicates flagged) or a Juli DRAFT card
    open_cards = await data.open_cards()
    arows: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for kind, item, why in actions:
        if (kind, item) in seen:
            continue
        seen.add((kind, item))
        card: dict[str, Any] = {}
        if engine is not None:
            eng = await engine.engine_card(kind, item, as_of)
            card = eng.get("card") or {} if eng.get("ok") else {}
        card_title = card.get("title")
        match = [(c, _same_change(c, kind, item, card_title)) for c in open_cards]
        match = [(c, m) for c, m in match if m]
        same = next((c for c, m in match if m == "same"), None)
        if same is not None:
            arows.append(
                {
                    "label_vi": labels.kind(kind),
                    "value_vi": f"Đã có thẻ {same.get('code') or ''}".strip(),
                    "detail_vi": why + " · trùng, không tạo lại",
                }
            )
            continue
        if not card or not cardstage.estimable(card, kind):
            # no draft Juli can price: point to the open card of the same kind and target, if any
            theirs = next((c for c, _ in match), None)
            arows.append(
                {
                    "label_vi": labels.kind(kind),
                    "value_vi": f"Đã có thẻ {theirs.get('code') or ''}".strip()
                    if theirs
                    else "Chưa có phương án",
                    "detail_vi": why,
                }
            )
            continue
        ev = await cardstage.draft_event(out, data, jev, labels, kind, item, card)
        note = next((c for c, _ in match), None)
        arows.append(
            {
                "label_vi": labels.kind(kind),
                "value_vi": "Thẻ nháp",
                "detail_vi": why
                + (f" · đã có thẻ cùng loại {note.get('code') or ''}" if note else ""),
            }
        )
        events.append(ev)
    if arows:
        events.insert(
            len(events) - len(out.events),
            _section(w, latest, "Việc nên làm tuần sau", arows),
        )
    return events, out
