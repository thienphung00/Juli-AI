"""The answer's reading rules (owner #110, approved mock 2026-11-26), applied once, by code, to
one intent's structured events before they reach the seller; the Chat page only lays them out.

1. One answer sentence first, the main number in it (`lead`); no "Đang tìm hiểu" header.
2. The period, the data date and the sale days ONCE, on top, one small line (`meta`); a block
   whose period is the one above repeats none of it.
3. Equal-length periods (`windows.build_windows`: a month not over runs against the same days).
4. No % change on a thin base (`fmt.delta`: "Kỳ trước chưa đủ dữ liệu").
5. At most 3 number tiles (label, value, one comparison line `compare_vi`); more figures are one
   table (`metric_list`).
6. Lists are tables with the numbers right-aligned (the page; rows carry `value_vi`).
7. No card that only says "chưa có": a no-card line without a card to open is dropped; a list
   without rows is marked `empty` (the page draws no box, the lead says it); a single missing
   number is "—" (`fmt.NODATA`).
8. Next steps are buttons (`next_steps` -> the `more` event), never a question back.
"""

from __future__ import annotations

from typing import Any

from juli_backend.services.analytics_agent import fmt

MAX_TILES = 3
#: the events one intent's answer holds until it is shaped (status and text stream live)
HELD = frozenset({"data_answer", "path", "label", "no_card", "card", "meta"})
META_KEYS = ("window_vi", "fresh_vi", "sale_vi")


def compare_vi(ev: dict[str, Any]) -> str | None:
    """A tile's one comparison line: the change and the figure it is measured against."""
    delta = ev.get("delta") or {}
    text = str(delta.get("text_vi") or "")
    if not text or text in ("–", "-"):
        return None
    if delta.get("dir") == "flat":  # "Kỳ trước chưa đủ dữ liệu" / "Chưa đủ dữ liệu"
        return text
    before = ev.get("before_vi")
    if before and before != fmt.NODATA:
        return f"{text} so với {before}"
    return f"{text} so với kỳ trước"


def meta_of(ev: dict[str, Any]) -> dict[str, Any] | None:
    got = {k: ev[k] for k in META_KEYS if ev.get(k)}
    return {"type": "meta", **got} if got.get("window_vi") or got.get("fresh_vi") else None


def _empty_list(ev: dict[str, Any]) -> bool:
    if ev.get("kind") == "metric_total":
        return False  # one number: shown as "—" when missing, never dropped
    return not ev.get("rows") and not ev.get("series")


def lead_vi(events: list[dict[str, Any]]) -> str | None:
    """The one answer sentence: the first figure of the answer, said plainly."""
    for ev in events:
        if ev.get("type") == "data_answer":
            title = str(ev.get("title_vi") or "")
            if ev.get("kind") in ("metric_total", "metric_list") and ev.get("value") is not None:
                value = str(ev.get("value"))
                if value == fmt.NODATA:
                    return f"{title}: chưa tính được cho kỳ này."
                delta = ev.get("delta") or {}
                move = (
                    f", {delta['text_vi']} so với kỳ trước"
                    if delta.get("dir") in ("up", "down") and delta.get("text_vi")
                    else ""
                )
                return f"{title} là {value}{move}."
            rows = ev.get("rows") or []
            if ev.get("empty"):
                return f"{title}: chưa có sản phẩm nào trong kỳ này."
            if rows:
                top = rows[0]
                return f"{title}: đứng đầu là {top.get('label_vi')} ({top.get('value_vi')})."
            series = [p for p in ev.get("series") or [] if p.get("value") is not None]
            if series:
                top = max(series, key=lambda p: float(p["value"]))
                return f"{title}: cao nhất {top.get('label_vi')} ({top.get('value_vi')})."
        if ev.get("type") == "path" and ev.get("steps"):
            head = ev["steps"][0]
            delta = head.get("delta") or {}
            move = (
                f", {delta['text_vi']} so với kỳ trước"
                if delta.get("dir") in ("up", "down") and delta.get("text_vi")
                else ""
            )
            return f"{head.get('label_vi')} là {head.get('value_vi')}{move}."
    return None


def _metric_list(extra: list[dict[str, Any]]) -> dict[str, Any]:
    first = extra[0]
    return {
        "type": "data_answer",
        "kind": "metric_list",
        "title_vi": "Các chỉ số khác",
        **{k: first[k] for k in META_KEYS if first.get(k)},
        "rows": [
            {
                "label_vi": str(e.get("title_vi") or ""),
                "value_vi": str(e.get("value") or fmt.NODATA),
                **({"detail_vi": c} if (c := e.get("compare_vi")) else {}),
            }
            for e in extra
        ],
    }


def shape(
    held: list[dict[str, Any]], last_meta: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """One intent's held events -> the events the seller gets (meta, lead, then the rest), and
    the meta now on screen. `last_meta` is the line already above (an earlier intent's)."""
    out: list[dict[str, Any]] = []
    meta: dict[str, Any] | None = None
    tiles = 0
    extra: list[dict[str, Any]] = []
    for ev in held:
        kind = ev.get("type")
        if kind == "meta":
            meta = meta or ev
            continue
        if kind == "no_card" and not ev.get("existing_card_code"):
            continue  # rule 7: a box that only says there is no card
        if kind == "data_answer":
            ev = dict(ev)
            if _empty_list(ev):
                ev["empty"] = True  # rule 7: no box that only says there is nothing
            meta = meta or meta_of(ev)
            if ev.get("kind") == "metric_total":
                if (c := compare_vi(ev)) is not None:
                    ev["compare_vi"] = c
                tiles += 1
                if tiles > MAX_TILES:  # rule 5: the 4th figure on goes into one table
                    extra.append(ev)
                    continue
        out.append(ev)
    if extra:
        out.append(_metric_list(extra))
    head: list[dict[str, Any]] = []
    shown = last_meta
    if meta is not None:
        key = {k: meta.get(k) for k in META_KEYS}
        if last_meta is None or key != {k: last_meta.get(k) for k in META_KEYS}:
            head.append(meta)
            shown = meta
    lead = lead_vi(out)
    if lead:
        head.append({"type": "lead", "text_vi": lead})
    return head + out, shown


def next_steps(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Rule 8: the next steps of a one-number shop answer as buttons (asked as a new question)."""
    answers = [e for e in events if e.get("type") == "data_answer"]
    if len(answers) != 1 or answers[0].get("kind") != "metric_total":
        return []
    a = answers[0]
    title = str(a.get("title_vi") or "")
    if " · " in title or not title:  # one product's figure: no shop drill-down
        return []
    cur = str(a.get("window_vi") or "").split(" so với ")[0]
    when = f" {cur}" if cur else ""
    return [
        {"label_vi": "Theo sản phẩm", "text": f"{title} theo sản phẩm{when}"},
        {"label_vi": "Theo ngày", "text": f"{title} theo ngày{when}"},
    ]


__all__ = ["HELD", "MAX_TILES", "compare_vi", "lead_vi", "meta_of", "next_steps", "shape"]
