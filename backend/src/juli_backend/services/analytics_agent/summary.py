"""A written summary for every answer that is not a "why" chain (J-H1).

The chain path writes its own explanation (`writer.write_explanation`). A lookup, an entity list
(campaigns, vouchers, products), the weekly plan and a drafted card return structured events only;
this module adds 2-4 Vietnamese sentences generated from those events. One writer call per answer
(no rewrite), through the same guards as the chain writer: `writer.sanitise`, `writer.alignment`
(the summary names each card it mentions and recommends no other action) and a numbers check
(every number in the text traces to a value in the structured result). The text must name the
window and the freshness day ("Số liệu đến hết dd/mm"). Any failure, or an unavailable LLM, falls
back to `template_text`, which only restates the result.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from juli_backend.services.analytics_agent import facts, writer
from juli_backend.services.analytics_agent.types import LLMPort

SUMMARY_SYSTEM = (
    "Bạn là Juli, viết phần tóm tắt 2-4 câu bằng tiếng Việt cho người bán hàng Shopee, xưng 'bạn'. "
    "Chỉ dùng dữ liệu trong KẾT QUẢ: mọi con số lấy nguyên văn (đã định dạng sẵn), không tự tính, "
    "không thêm số nào khác. Câu đầu nêu kỳ (KỲ) và ngày số liệu (SỐ_LIỆU_ĐẾN, viết đúng như đã "
    "cho, ví dụ 'Số liệu đến hết 22/11'). Không đưa lời khuyên ngoài kết quả; chỉ nhắc tới các thẻ "
    "trong THẺ (gọi đúng loại thẻ và sản phẩm), không viết giá trị hay dự báo của thẻ. Với kế "
    "hoạch tuần: điều gì đã xảy ra, việc nên làm trước, và thẻ nào cần mở. Gọi đúng đối tượng "
    "(số của một sản phẩm không gọi là của shop). Tên sản phẩm chép nguyên văn, đầy đủ, đúng như "
    "trong KẾT QUẢ, không rút gọn. Không dùng từ kỹ thuật, không mã, không tiếng "
    "Anh."
)

_DATE = re.compile(r"\b\d{1,2}/\d{1,2}\b")
_ROW_KEYS = ("label_vi", "value_vi", "detail_vi", "note_vi")
MAX_ROWS = 8


def _clean(v: Any) -> Any:
    return v if isinstance(v, str) and v else None


def digest(events: list[dict[str, Any]]) -> dict[str, Any]:
    """What the writer sees: the strings the seller already sees, never ids or raw numbers.
    `cards` carries the card kind and product only (a card's values are never written)."""
    answers: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    for e in events:
        if e.get("type") == "data_answer":
            a: dict[str, Any] = {
                "tiêu_đề": _clean(e.get("title_vi")),
                "kỳ": _clean(e.get("window_vi")),
                "số_liệu_đến": _clean(e.get("fresh_vi")),
                "ngày_sale": _clean(e.get("sale_vi")),
                "giá_trị": _clean(e.get("value")),
                "kỳ_trước": _clean(e.get("before_vi")),
                "thay_đổi": _clean((e.get("delta") or {}).get("text_vi")),
                "đóng_góp": _clean(e.get("contribution_vi")),
                "dòng": [
                    {k: r[k] for k in _ROW_KEYS if _clean(r.get(k))}
                    for r in (e.get("rows") or [])[:MAX_ROWS]
                ],
            }
            if e.get("series"):
                a["theo_ngày"] = [
                    f"{r.get('label_vi')}: {r.get('value_vi')}" for r in e["series"][:MAX_ROWS]
                ]
            answers.append({k: v for k, v in a.items() if v})
        elif e.get("type") == "card":
            cards.append(
                {
                    "ref": e.get("draft_ref", ""),
                    "kind": e.get("kind", ""),
                    "kind_vi": e.get("kind_vi"),
                    "item_name": e.get("item_name"),
                }
            )
    return {"answers": answers, "cards": cards}


def given_facts(dg: dict[str, Any]) -> facts.Facts:
    """Every checkable number of the digest, in its own unit (the same tokens the check reads)."""
    f = facts.Facts()
    for _raw, value, _tol, is_pct in facts._tokens(json.dumps(dg["answers"], ensure_ascii=False)):
        if is_pct:
            f.pct += [value, abs(value)]
        else:
            f.plain += [value, abs(value)]
    return f


def required_mentions(dg: dict[str, Any]) -> list[str]:
    """The dates the text must name: the main window and the freshness day."""
    out: list[str] = []
    for a in dg["answers"]:
        win = str(a.get("kỳ") or "").split(" so với ")[0]
        out += _DATE.findall(win) + _DATE.findall(str(a.get("số_liệu_đến") or ""))
    return list(dict.fromkeys(out))


def _names(dg: dict[str, Any]) -> list[str]:
    names = [c["item_name"] for c in dg["cards"] if c.get("item_name")]
    for a in dg["answers"]:
        names += [r["label_vi"] for r in a.get("dòng", []) if r.get("label_vi")]
        names += [str(a["tiêu_đề"])] if a.get("tiêu_đề") else []
    return names


def check(text: str, dg: dict[str, Any], f: facts.Facts) -> list[str]:
    """Issues that block the text: leaks, advice outside the result, an untraced number, a missing
    window / freshness day. Empty = shown."""
    if not text.strip():
        return ["empty"]
    names = _names(dg)
    clean, leaks = writer.sanitise(text, None, names)
    issues = [f"leak:{x}" for x in leaks] + writer.alignment(clean, dg["cards"])
    masked = clean
    for n in sorted(names, key=len, reverse=True):  # digits in a product name are not claims
        masked = masked.replace(n, " ")
    # numbers_check skips a first line (the chain's restated question): give it one to skip
    issues += [f"number:{x}" for x in facts.numbers_check("-\n" + masked, f, card_figures=[])]
    issues += [f"missing:{d}" for d in required_mentions(dg) if d not in clean]
    return issues


def template_text(dg: dict[str, Any]) -> str:
    """The code-rendered fallback: window and freshness first, then each answer's own figures, then
    the cards to open. Only values from the result."""
    parts: list[str] = []
    first = dg["answers"][0] if dg["answers"] else {}
    head = " · ".join(str(first[k]) for k in ("kỳ", "số_liệu_đến") if first.get(k))
    if head:
        parts.append(head + ".")
    for a in dg["answers"][:3]:
        bits = [str(a[k]) for k in ("giá_trị", "thay_đổi", "đóng_góp") if a.get(k)]
        rows = [
            f"{r['label_vi']} ({r['value_vi']})"
            for r in a.get("dòng", [])[:2]
            if r.get("label_vi") and r.get("value_vi")
        ]
        title = str(a.get("tiêu_đề") or "Kết quả")
        if bits:
            parts.append(f"{title}: {' · '.join(bits)}.")
        elif rows:
            parts.append(f"{title}: {', '.join(rows)}.")
        else:
            parts.append(f"{title}.")
    if dg["cards"]:
        c = dg["cards"][0]
        parts.append(
            f"Mở thẻ {str(c.get('kind_vi') or '').lower()} · {c.get('item_name') or 'shop'}."
        )
    return " ".join(parts)


async def write_summary(
    llm: LLMPort,
    emit_delta: Callable[[str], Awaitable[None]],
    emit_replace: Callable[[str], Awaitable[None]],
    events: list[dict[str, Any]],
    fresh_vi: str | None = None,
) -> dict[str, Any] | None:
    """Stream one summary for `events`; None when there is nothing to summarise. Returns
    {"template", "issues", "text"}: `template` is True when the guards (or the LLM) failed and the
    code-rendered text was shown."""
    dg = digest(events)
    if not dg["answers"] and not dg["cards"]:
        return None
    if dg["cards"] and not dg["answers"] and fresh_vi:  # a card answer: only the freshness day
        dg["answers"].append({"số_liệu_đến": fresh_vi})
    f = given_facts(dg)
    payload = {
        "KẾT QUẢ": dg["answers"],
        "THẺ": [{"loại": c["kind_vi"], "sản_phẩm": c["item_name"]} for c in dg["cards"]],
        "NHẮC": required_mentions(dg),
    }
    streamed: list[str] = []
    try:
        async for d in llm.stream_text(SUMMARY_SYSTEM, json.dumps(payload, ensure_ascii=False)):
            if d:
                streamed.append(d)
                await emit_delta(d)
    except Exception:  # the LLM is unavailable: the template, never an empty answer
        streamed = []
    text = "".join(streamed).strip()
    issues = check(text, dg, f) if text else ["llm_unavailable"]
    if not issues:
        clean = writer.sanitise(text, None, _names(dg))[0]
        if clean != text:
            await emit_replace(clean)
        return {"template": False, "issues": [], "text": clean}
    fallback = template_text(dg)
    await emit_replace(fallback)
    return {"template": True, "issues": issues, "text": fallback}
