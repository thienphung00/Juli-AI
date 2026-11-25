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
from juli_backend.services.analytics_agent.entities import (
    campaign_order,
    campaign_row,
    campaign_verdict,
)
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


def rng(win: tuple[date, date]) -> str:
    """ "16–22/11" or "30/10–05/11": a date range, never a relative word."""
    a, b = win
    return f"{a:%d}–{b:%d/%m}" if (a.month, a.year) == (b.month, b.year) else f"{a:%d/%m}–{b:%d/%m}"


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


async def source_gmv(data: DataPort, win: tuple[date, date]) -> dict[str, float]:
    """GMV per traffic source over `win`, as `query(group_by="source")` returns it (a source with
    no figure is absent, never 0)."""
    return {
        str(r["source"]): float(r["gmv"])
        for r in await data.source_totals(*win)
        if r.get("gmv") is not None
    }


IDLE_SPEND_SHARE = 0.30  # owner #53: an idle budget day spends under 30 % of the daily budget


def idle_days(
    budget_rows: list[dict[str, Any]], shop_rows: list[dict[str, Any]], win: tuple[date, date]
) -> list[dict[str, Any]]:
    """Idle budget days (owner #53): ad spend under 30 % of the daily budget and no ad orders.
    A row without ad orders (an older reader) falls back to the shop's orders that day."""
    orders = {r["day"]: r.get("orders") for r in shop_rows if win[0] <= r["day"] <= win[1]}

    def no_orders(b: dict[str, Any]) -> bool:
        ad = b.get("ad_orders")
        return float(ad) == 0.0 if ad is not None else orders.get(b["day"]) in (0, 0.0)

    return [
        b
        for b in budget_rows
        if b["budget"] is not None
        and float(b["spend"]) < IDLE_SPEND_SHARE * float(b["budget"])
        and no_orders(b)
    ]


def has_cogs_gap(profit: dict[str, Any] | None) -> bool:
    """Giá vốn covers < 99,5 % of the product's GMV (profit not trusted)."""
    return bool(
        profit
        and profit.get("coverage_pct") is not None
        and float(profit["coverage_pct"]) < _COVERAGE_OK
    )


#: The table rows: (label, Chat metric key for formatting, registry id read from `query()`).
WEEK_ROWS = (
    ("GMV", "gmv", "gmv"),
    ("Đơn", "orders", "orders"),
    ("Chi phí QC", "ads_spend", "cost_ads"),
    ("ROAS", "roas", "roas"),
)


async def week_table(data: DataPort, w: Any, last_week: tuple[date, date]) -> list[dict[str, Any]]:
    """GMV / Đơn / Chi phí QC / ROAS this window vs last week (vs a normal week when the last one
    held a sale day). Every value is `query()`'s window total; nothing is summed here."""
    ids = [rid for _, _, rid in WEEK_ROWS]
    got = {
        name: (await data.metrics(ids, *win)).get("values") or {}
        for name, win in (("cur", w.cur), ("last", last_week), ("prev", w.prev))
    }
    table: list[dict[str, Any]] = []
    for label, m, rid in WEEK_ROWS:
        now, lw, nw = (_f(got[k].get(rid)) for k in ("cur", "last", "prev"))
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
    return table


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


async def resolve_action(
    out: cardstage.CardOutcome,
    data: DataPort,
    engine: CardEnginePort | None,
    jev: JevPort,
    labels: LabelTable,
    as_of: date,
    open_cards: list[dict[str, Any]],
    kind: str,
    item: str | None,
) -> dict[str, Any]:
    """One action -> an existing Đề xuất card or a Juli DRAFT. `status`: "same" (an identical open
    card: no new one), "none" (nothing Juli can price; `code` = an open card of that kind and
    target, if any) or "draft" (`event` = the card event, `ref` = its draft ref; `code` = an open
    card of the same kind). Nothing is sent or executed."""
    card: dict[str, Any] = {}
    reason = "no_engine"
    if engine is not None:
        eng = await engine.engine_card(kind, item, as_of)
        card = eng.get("card") or {} if eng.get("ok") else {}
        reason = str(eng.get("reason") or "engine_refused")
    card_title = card.get("title")
    match = [(c, _same_change(c, kind, item, card_title)) for c in open_cards]
    match = [(c, m) for c, m in match if m]
    same = next((c for c, m in match if m == "same"), None)
    if same is not None:
        return {"status": "same", "code": same.get("code"), "event": None, "ref": None}
    theirs = next((c for c, _ in match), None)
    code = theirs.get("code") if theirs else None
    if not card or not cardstage.estimable(card, kind):
        why_none = reason if not card else "not_estimable"
        return {"status": "none", "code": code, "event": None, "ref": None, "reason": why_none}
    ev = await cardstage.draft_event(out, data, jev, labels, kind, item, card)
    return {"status": "draft", "code": code, "event": ev, "ref": out.accepted[-1]["ref"]}


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
    table = await week_table(data, w, last_week)
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
    idle = idle_days(await data.budget_days(*w.cur), rows, w.cur)
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
    sn, sb = await source_gmv(data, w.cur), await source_gmv(data, w.prev)
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
    cur = {r["item_id"]: float(r["gmv"]) for r in await data.product_daily(*w.cur) if r["gmv"]}
    total = _f(((await data.metrics(["gmv"], *w.cur)).get("values") or {}).get("gmv"))
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
        if has_cogs_gap(now_p):
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
        res = await resolve_action(out, data, engine, jev, labels, as_of, open_cards, kind, item)
        code = res["code"] or ""
        if res["status"] == "same":
            arows.append(
                {
                    "label_vi": labels.kind(kind),
                    "value_vi": f"Đã có thẻ {code}".strip(),
                    "detail_vi": why + " · trùng, không tạo lại",
                }
            )
        elif res["status"] == "none":
            arows.append(
                {
                    "label_vi": labels.kind(kind),
                    "value_vi": f"Đã có thẻ {code}".strip() if code else "Chưa có phương án",
                    "detail_vi": why,
                }
            )
        else:
            arows.append(
                {
                    "label_vi": labels.kind(kind),
                    "value_vi": "Thẻ nháp",
                    "detail_vi": why + (f" · đã có thẻ cùng loại {code}" if code else ""),
                }
            )
            events.append(res["event"])
    if arows:
        events.insert(
            len(events) - len(out.events),
            _section(w, latest, "Việc nên làm tuần sau", arows),
        )
    return events, out
