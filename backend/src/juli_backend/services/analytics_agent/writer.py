"""Writer, alignment check and sanitiser (E6).

The writer (`LLMPort.stream_text`) gets pre-formatted values only (8.728.160đ, 42,8%, 3,07%), starts
with the restated line "Đang tìm hiểu: ", writes the explanation only, mentions only accepted cards
and
never writes a card's values or forecasts. The alignment check (port of agent2.alignment) allows one
rewrite through `text_replace`, then the code template with metric-formatted values. Every
explanation
passes the sanitiser before display.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from juli_backend.services.analytics_agent import facts, fmt
from juli_backend.services.analytics_agent.types import LabelTable

LEVER_VI: dict[str, list[str]] = {
    "product_discount": ["giảm giá"],
    "price": ["giá"],
    "min_spend_voucher": ["voucher"],
    "review_voucher": ["voucher"],
    "voucher_cap": ["voucher"],
    "flash_sale": ["flash sale", "deal"],
    "program_registration": ["chương trình"],
    "bundle_deal": ["combo", "mua nhiều"],
    "add_on": ["mua kèm"],
    "gift": ["quà"],
    "variation_set": ["bộ", "phân loại"],
    "ads_budget": ["quảng cáo", "ngân sách", "dịch vụ hiển thị"],
    "ads_roas_target": ["quảng cáo", "roas", "dịch vụ hiển thị"],
    "ads_pause": ["quảng cáo", "dịch vụ hiển thị"],
    "ads_purpose": ["quảng cáo", "dịch vụ hiển thị"],
    "ads_add_product": ["quảng cáo", "dịch vụ hiển thị"],
    "title": ["tiêu đề"],
    "keyword": ["từ khoá", "từ khóa"],
    "cover_image": ["ảnh"],
    "price_display": ["giá hiển thị", "ảnh"],
    "affiliate_commission": ["hoa hồng", "tiếp thị liên kết"],
    "affiliate_target_campaign": ["tiếp thị liên kết", "hoa hồng"],
}
ACTION_WORDS = [
    "giảm giá",
    "tăng giá",
    "voucher",
    "flash sale",
    "combo",
    "quảng cáo",
    "ngân sách",
    "hoa hồng",
    "tiêu đề",
    "ảnh bìa",
    "mua kèm",
    "quà tặng",
]
_ADVICE = re.compile(
    r"\b(nên|hãy|cần)\s+(chạy|tăng|giảm|tạo|áp dụng|thêm|đổi|bật|tắt|dừng|đăng ký|tham "
    r"gia|mở|chỉnh|đặt)"
)

STOP_VI = {
    "explained": "đã tìm ra phần chính gây thay đổi",
    "within_noise": "trong mức dao động bình thường",
    "unexplained": "chưa rõ nguyên nhân",
    "data_missing": "thiếu dữ liệu",
    "data_stale": "dữ liệu chưa cập nhật",
}

WRITER_SYSTEM = (
    "Bạn là Juli, viết lời giải thích ngắn cho người bán hàng Shopee bằng tiếng Việt, xưng 'bạn'. "
    "Dòng đầu tiên PHẢI là đúng dòng được đưa (bắt đầu bằng 'Đang tìm hiểu: '). Chỉ giải thích "
    "nguyên nhân dựa trên "
    "FINDINGS; mọi con số lấy nguyên văn từ FINDINGS (đã định dạng sẵn), không tự tính. Chỉ nhắc "
    "tới các thẻ đã được "
    "chấp nhận (ACCEPTED_CARDS); không viết giá trị hay dự báo của thẻ; không đề xuất hành động "
    "nào ngoài các thẻ đó. "
    "Hết kho chỉ nhắc, không đề xuất. Không dùng từ kỹ thuật, không mã, không tên trường, không "
    "tiếng Anh."
)


def alignment(expl: str, accepted: list[dict[str, Any]]) -> list[str]:
    """The explanation names each accepted card's product + lever and recommends no other action."""
    t = (expl or "").lower()
    issues: list[str] = []
    levers_ok: set[str] = set()
    for c in accepted:
        words = LEVER_VI.get(c["kind"], [])
        levers_ok |= set(words)
        name = (c.get("item_name") or "").lower()
        tokens = [w for w in re.split(r"[\s,\-\[\]\.]+", name) if len(w) >= 4][:6]
        if name and not any(tok in t for tok in tokens):
            issues.append(f"card {c.get('ref', '')}: product not named in the explanation")
        if words and not any(w in t for w in words):
            issues.append(f"card {c.get('ref', '')}: lever '{words[0]}' not in the explanation")
    for c in accepted:  # product names may contain lever words
        if c.get("item_name"):
            t = t.replace(c["item_name"].lower(), " ")
    t = re.sub(r"\[deal [^\]]*\]|combo \d[\d, ]*(hộp|cuộn|chai)?", " ", t)
    for sent in re.split(r"[.\n]", t):
        if not _ADVICE.search(sent) or re.search(r"không (đưa ra|đề xuất|khuyên)", sent):
            continue
        for w in ACTION_WORDS:
            if w in sent and w not in levers_ok:
                issues.append(f"recommends '{w}' without a card: «{sent.strip()[:80]}»")
    return issues


# ------------------------------------------------------------------ sanitiser

_INTERNAL_WORDS = re.compile(r"\b(hệ thống|jev|llm|chuỗi|gate|stop_reason|findings)\b", re.I)
_SNAKE = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")
_JSON = re.compile(r"[{}\[\]]|\"\s*:\s*")
_URL = re.compile(
    r"https?://|www\.|(?:^|\s)/[\w\-./]*[a-z][\w\-./]*|\b[a-z][\w\-]*/[\w\-]+/[\w\-./]*"
)
_ENDPOINT = re.compile(
    r"\b(metric[-_ ]view|channel[-_ ]split|critical|ranking|product[-_ ]page|overview|"
    r"endpoint|tool[_ ]call|propose_card|list_cards)\b",
    re.I,
)
_EVIDENCE = re.compile(r"\b(lmdi|rate_mix|additive|evidence)[:_]\S*", re.I)
# more than 2 decimals: "101,891404", "0.079365"; "183.755" is a Vietnamese thousands group
_LONG_DECIMAL = re.compile(r"\d[\d.]*,\d{3,}|(?<![\d.])(?:0\.\d{3,}|\d+\.\d{4,})(?![\d.])")
_BIG_ID = re.compile(r"\b\d{9,}\b")
_ENGLISH_RUN = re.compile(r"\b(?:[A-Za-z]{3,}\s+){2,}[A-Za-z]{3,}\b")
_PLACEHOLDER = re.compile(r"placeholder|lorem ipsum|^\s*Tôi hiểu\s*:", re.I | re.M)
_FIRST_LINE = re.compile(r"^Đang tìm hiểu: .+")
# Latin words the Vietnamese copy legitimately keeps (brands / metrics / product names handled by
# caller)
_ALLOWED_ENGLISH = {
    "gmv",
    "aov",
    "ctr",
    "ctor",
    "roas",
    "flash",
    "sale",
    "voucher",
    "shop",
    "combo",
    "live",
    "video",
}


def sanitise(
    text: str, id_names: dict[str, str] | None = None, allowed_names: list[str] | None = None
) -> tuple[str, list[str]]:
    """Returns (text with 9+ digit ids replaced by product names, leak issues). Issues must be 0 to
    show."""
    names = id_names or {}
    out = text
    for i, n in names.items():
        out = out.replace(i, n)
    issues: list[str] = []
    probe = out
    for n in allowed_names or []:  # product names verbatim may contain anything
        probe = probe.replace(n, " ")
    for name, pat in (
        ("snake_case", _SNAKE),
        ("json", _JSON),
        ("url_or_path", _URL),
        ("endpoint", _ENDPOINT),
        ("evidence_ref", _EVIDENCE),
        ("decimals", _LONG_DECIMAL),
        ("internal_word", _INTERNAL_WORDS),
        ("long_id", _BIG_ID),
        ("placeholder", _PLACEHOLDER),
    ):
        if pat.search(probe):
            issues.append(name)
    for m in _ENGLISH_RUN.finditer(probe):
        words = {w.lower() for w in m.group(0).split()}
        if not words <= _ALLOWED_ENGLISH:
            issues.append("english_run")
            break
    try:
        from juli_backend.services.agent.sanitize import guard_outbound_agent_output

        guard_outbound_agent_output(probe)
    except Exception:  # BannedPatternGuardFailure or a scan failure: both fail closed
        issues.append("banned_pattern")
    return out, issues


# ------------------------------------------------------------------ prompt inputs and template


def template_text(first_line: str, chain_json: dict[str, Any], labels: LabelTable) -> str:
    """Code-rendered fallback: metric-formatted values, no LLM."""
    m = chain_json["metric"]
    head = chain_json["findings"][0] if chain_json["findings"] else {}
    parts = [
        first_line,
        f"Kỳ: {chain_json['window']['label_vi']}. {head.get('node_vi', labels.metric(m))}: "
        f"{fmt.value(m, head.get('before'))} → {fmt.value(m, head.get('now'))}.",
    ]
    for f in chain_json["findings"][1:4]:
        if f.get("contribution_pct") is not None:
            parts.append(
                f"- {f['node_vi']}: {fmt.decimal(abs(f['contribution_pct']), 0)}% mức thay đổi"
            )
    parts.append(f"Kết luận: {STOP_VI.get(chain_json['stop_reason'], chain_json['stop_reason'])}.")
    return "\n".join(parts)


async def write_explanation(
    llm: Any,
    emit_delta: Callable[[str], Awaitable[None]],
    emit_replace: Callable[[str], Awaitable[None]],
    first_line: str,
    chains_json: list[dict[str, Any]],
    accepted: list[dict[str, Any]],
    labels: LabelTable,
    id_names: dict[str, str],
    card_note: list[dict[str, Any]] | None = None,
    card_figures: list[float] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Stream the writer; check alignment + sanitiser; one rewrite via text_replace; then the
    template.
    Returns (final text, {"rewrites", "template", "issues", "cost_usd"})."""
    import json

    pairs = [facts.writer_input(c, labels) for c in chains_json]
    all_facts = [f for _, f in pairs]
    payload = {
        "FIRST_LINE": first_line,
        "FINDINGS": [p for p, _ in pairs],
        "ACCEPTED_CARDS": [
            {"loại": c.get("kind_vi"), "sản_phẩm": c.get("item_name")} for c in accepted
        ],
        "CARD_NOTE": card_note or [],
    }
    user = json.dumps(payload, ensure_ascii=False)
    names = [c["item_name"] for c in accepted if c.get("item_name")] + list(id_names.values())
    streamed: list[str] = []
    async for d in llm.stream_text(WRITER_SYSTEM, user):
        streamed.append(d)
        await emit_delta(d)
    text = "".join(streamed).strip()

    numbers_failed: list[str] = []

    def check(t: str) -> tuple[str, list[str]]:
        clean, leaks = sanitise(t, id_names, names)
        iss = alignment(clean, accepted) + [f"leak:{x}" for x in leaks]
        bad_numbers = facts.numbers_check(clean, all_facts, card_figures=card_figures or [])
        numbers_failed.extend(bad_numbers)
        iss += [f"number:{x}" for x in bad_numbers]
        if not _FIRST_LINE.match(clean.splitlines()[0] if clean else ""):
            iss.append("first_line")
        return clean, iss

    text, issues = check(text)
    if not issues and text != "".join(streamed).strip():
        await emit_replace(text)  # ids swapped for product names
    meta: dict[str, Any] = {
        "rewrites": 0,
        "template": False,
        "issues": list(issues),
        "cost_usd": 0.0,
        "numbers_failed": numbers_failed,
    }
    if issues:
        meta["rewrites"] = 1
        fixed, usage = await llm.text(
            WRITER_SYSTEM, json.dumps({**payload, "FIX": "; ".join(issues)}, ensure_ascii=False)
        )
        meta["cost_usd"] += usage.cost_usd
        text, issues = check(fixed.strip())
        await emit_replace(text)
    if issues:
        meta["template"] = True
        text = "\n\n".join(template_text(first_line, c, labels) for c in chains_json)
        await emit_replace(text)
        meta["issues"] += issues
    return text, meta
