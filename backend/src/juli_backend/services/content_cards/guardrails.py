"""Checks a draft must pass before the seller sees it (contract §3, D24.16).

Deterministic, no model. A draft is shown only when every check passes; the
same checks run again on the seller's own edits ("bạn sửa trực tiếp được").

- **banned** — generic claim patterns a seller must not say on TikTok (cure /
  guarantee / "number one" / "cheapest", view or sales promises), Juli's own
  founder voice (a seller's script never talks about Juli), and the seller's
  banned words from Quy tắc;
- **protected** — a protected term (brand, product line) that appears is
  written exactly as the seller wrote it, not respelled;
- **facts** — every price in the text is one of the product's prices (or that
  price after the offer's discount); a stock count ("còn 50") never exceeds the
  inventory; nothing else numeric about the product is invented;
- **discount** — the LIVE offer's discount ≤ the seller's cap; no discount at
  all when the seller set no cap; no "giảm N %" above the cap in any text;
- **length** — the video runs 15–60 s in 2–8 scenes from 0 s, the hook ≤ 12
  words and works muted (an on-screen line), each line short; the product is
  on screen by 3 s; LIVE sections ≤ 600 characters, basket positions 1..n with
  the product first.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from juli_backend.services.content_cards.schemas import LivePlan, VideoScript

#: Generic claim patterns (lower-case, matched on word boundaries, accents kept).
BANNED_PATTERNS: tuple[str, ...] = (
    "cam kết 100",
    "hiệu quả 100",
    "100 % hiệu quả",
    "tốt nhất thị trường",
    "số 1 việt nam",
    "rẻ nhất",
    "duy nhất trên thị trường",
    "chữa khỏi",
    "trị dứt điểm",
    "khỏi hẳn",
    "thần kỳ",
    "thần dược",
    "đảm bảo lên xu hướng",
    "chắc chắn viral",
    "triệu view",
    "các bạn ơi",
    "hãy follow",
    "hẹn gặp lại",
    "cảm ơn các bạn đã theo dõi",
    "juli",
    "mình xây",
)

MAX_HOOK_WORDS = 12
MIN_VIDEO_S = 15
MAX_VIDEO_S = 60
MAX_SCENES = 8
MIN_SCENES = 2
MAX_LINE_CHARS = 220
MAX_ON_SCREEN_CHARS = 80
MAX_LIVE_SECTION_CHARS = 600
MAX_HASHTAGS = 6
MAX_BASKET = 10
PRODUCT_ON_SCREEN_BY_S = 3.0

CHECK_LABELS: dict[str, str] = {
    "banned": "không có từ cấm",
    "protected": "giữ từ bảo vệ của bạn",
    "facts": "đúng thông tin sản phẩm",
    "discount": "trong trần giảm giá",
    "length": "độ dài phù hợp",
}
CHECKS_LINE_VI = (
    "Đã kiểm tra: không có từ cấm, giữ từ bảo vệ của bạn, đúng thông tin sản phẩm, "
    "trong trần giảm giá."
)


@dataclass(frozen=True)
class ContentRules:
    """The seller's rules that bind a script (Quy tắc)."""

    tone: str | None = None
    banned_terms: tuple[str, ...] = ()
    protected_terms: tuple[str, ...] = ()
    discount_cap_pct: float | None = None


@dataclass(frozen=True)
class DraftFacts:
    """What the script may state about the product."""

    product_label: str
    product_title: str
    prices_vnd: tuple[int, ...] = ()
    inventory: int | None = None
    #: Seller SKUs (or short names) the basket order may name; the product first.
    basket_skus: tuple[str, ...] = ()


@dataclass
class CheckResult:
    key: str
    ok: bool
    detail: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": CHECK_LABELS[self.key],
            "ok": self.ok,
            "detail": self.detail,
        }


@dataclass
class Verdict:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def failures(self) -> list[CheckResult]:
        return [check for check in self.checks if not check.ok]

    def to_json(self) -> list[dict[str, Any]]:
        return [check.to_json() for check in self.checks]


def _fold(text: str) -> str:
    """Lower-case, accents stripped, đ→d — to spot a respelled protected term."""
    stripped = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn")


def _contains(text: str, needle: str) -> bool:
    if not needle.strip():
        return False
    return re.search(rf"(?<!\w){re.escape(needle.lower())}(?!\w)", text.lower()) is not None


def _texts_video(script: VideoScript) -> list[str]:
    out = [*script.hook_options, script.cta, script.music_hint, *script.hashtags]
    for scene in script.scenes:
        out += [scene.visual, scene.voiceover, scene.on_screen]
    return out


def _texts_live(plan: LivePlan) -> list[str]:
    return [
        plan.opening,
        plan.show,
        plan.close,
        plan.offer.text,
        *(b.pin_at for b in plan.basket_order),
    ]


def check_banned(texts: Iterable[str], rules: ContentRules) -> CheckResult:
    joined = "\n".join(texts)
    hits = [p for p in BANNED_PATTERNS if _contains(joined, p)]
    hits += [t for t in rules.banned_terms if _contains(joined, t)]
    return CheckResult("banned", not hits, ", ".join(dict.fromkeys(hits)))


def check_protected(texts: Iterable[str], rules: ContentRules) -> CheckResult:
    joined = "\n".join(texts)
    folded = _fold(joined)
    bad: list[str] = []
    for term in rules.protected_terms:
        if not term.strip():
            continue
        exact = term in joined
        loose = re.search(rf"(?<!\w){re.escape(_fold(term))}(?!\w)", folded) is not None
        if loose and not exact:
            bad.append(term)
    return CheckResult("protected", not bad, ", ".join(bad))


_MONEY = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+|\d+)\s*(k|nghìn|ngàn|đ|₫|vnđ|vnd|đồng)(?!\w)",
    re.IGNORECASE,
)
_PERCENT_OFF = re.compile(
    r"(?:giảm|sale|off|−|-)\s*(\d{1,3}(?:[.,]\d+)?)\s*%|(\d{1,3}(?:[.,]\d+)?)\s*%\s*(?:off|giảm)",
    re.IGNORECASE,
)
_STOCK = re.compile(r"(?:còn|chỉ còn|còn lại)\s+(\d+)", re.IGNORECASE)


def _money_values(text: str) -> list[int]:
    values: list[int] = []
    for number, unit in _MONEY.findall(text):
        digits = int(re.sub(r"[.,]", "", number))
        values.append(digits * 1000 if unit.lower() in ("k", "nghìn", "ngàn") else digits)
    return values


def _percents(text: str) -> list[float]:
    out: list[float] = []
    for a, b in _PERCENT_OFF.findall(text):
        raw = a or b
        out.append(float(raw.replace(",", ".")))
    return out


def _price_ok(value: int, prices: Sequence[int], discount_pct: float | None) -> bool:
    candidates = set(prices)
    if discount_pct:
        candidates |= {round(p * (1 - discount_pct / 100)) for p in prices}
    # A price said as "69k" is rounded to the thousand.
    return any(abs(value - p) <= max(1000, p * 0.01) for p in candidates)


def check_facts(
    texts: Iterable[str], facts: DraftFacts, *, discount_pct: float | None = None
) -> CheckResult:
    joined = "\n".join(texts)
    bad: list[str] = []
    for value in _money_values(joined):
        if not facts.prices_vnd or not _price_ok(value, facts.prices_vnd, discount_pct):
            bad.append(f"giá {value:,}".replace(",", "."))
    for count in _STOCK.findall(joined):
        if facts.inventory is None or int(count) > facts.inventory:
            bad.append(f"số lượng {count}")
    return CheckResult("facts", not bad, ", ".join(bad))


def check_discount(
    texts: Iterable[str], rules: ContentRules, *, offer_pct: float | None
) -> CheckResult:
    cap = rules.discount_cap_pct
    said = _percents("\n".join(texts))
    values = [v for v in [offer_pct, *said] if v is not None and v > 0]
    if cap is None:
        return CheckResult("discount", not values, "bạn chưa đặt trần giảm giá" if values else "")
    over = [v for v in values if v > cap + 1e-9]
    return CheckResult("discount", not over, ", ".join(f"{v:g} %" for v in over))


def _words(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def check_video_length(script: VideoScript) -> CheckResult:
    issues: list[str] = []
    if len(script.hook_options) != 2:
        issues.append("cần đúng 2 phương án hook")
    issues += [
        f"hook dài {_words(h)} từ" for h in script.hook_options if _words(h) > MAX_HOOK_WORDS
    ]
    if not MIN_SCENES <= len(script.scenes) <= MAX_SCENES:
        issues.append(f"{len(script.scenes)} cảnh")
    if script.scenes:
        if script.scenes[0].t_from != 0:
            issues.append("cảnh đầu không bắt đầu từ 0 giây")
        end = max(s.t_to for s in script.scenes)
        if not MIN_VIDEO_S <= end <= MAX_VIDEO_S:
            issues.append(f"dài {end:g} giây")
        previous = 0.0
        for scene in script.scenes:
            if scene.t_to <= scene.t_from or scene.t_from < previous:
                issues.append("thời gian cảnh không liên tục")
                break
            previous = scene.t_to
        for scene in script.scenes:
            if len(scene.voiceover) > MAX_LINE_CHARS or len(scene.on_screen) > MAX_ON_SCREEN_CHARS:
                issues.append("có câu quá dài")
                break
        if not script.scenes[0].on_screen.strip():
            issues.append("hook cần chữ trên màn hình (xem không tiếng)")
    if script.product_on_screen_by_s > PRODUCT_ON_SCREEN_BY_S:
        issues.append(f"sản phẩm xuất hiện ở giây {script.product_on_screen_by_s:g}")
    if not script.cta.strip() or len(script.cta) > MAX_LINE_CHARS:
        issues.append("lời kêu gọi")
    if len(script.hashtags) > MAX_HASHTAGS or any(
        not h.startswith("#") or " " in h.strip() for h in script.hashtags
    ):
        issues.append("hashtag")
    return CheckResult("length", not issues, "; ".join(issues))


def check_live_length(plan: LivePlan, facts: DraftFacts) -> CheckResult:
    issues: list[str] = []
    for name, text in (("mở", plan.opening), ("trình diễn", plan.show), ("chốt", plan.close)):
        if not text.strip() or len(text) > MAX_LIVE_SECTION_CHARS:
            issues.append(f"phần {name}")
    basket = plan.basket_order
    if not 1 <= len(basket) <= MAX_BASKET:
        issues.append("thứ tự giỏ")
    else:
        positions = [b.position for b in basket]
        if sorted(positions) != list(range(1, len(basket) + 1)):
            issues.append("vị trí giỏ không liên tục")
        first = min(basket, key=lambda b: b.position)
        if facts.basket_skus and first.sku.strip() != facts.basket_skus[0]:
            issues.append("sản phẩm chính chưa ở vị trí 1")
        allowed = set(facts.basket_skus)
        if allowed and any(b.sku.strip() not in allowed for b in basket):
            issues.append("giỏ có sản phẩm không có trong shop")
    return CheckResult("length", not issues, "; ".join(issues))


def check_video(script: VideoScript, facts: DraftFacts, rules: ContentRules) -> Verdict:
    texts = _texts_video(script)
    return Verdict(
        [
            check_banned(texts, rules),
            check_protected(texts, rules),
            check_facts(texts, facts),
            check_discount(texts, rules, offer_pct=None),
            check_video_length(script),
        ]
    )


def check_live(plan: LivePlan, facts: DraftFacts, rules: ContentRules) -> Verdict:
    texts = _texts_live(plan)
    offer_pct = plan.offer.discount_pct if plan.offer.type != "none" else None
    return Verdict(
        [
            check_banned(texts, rules),
            check_protected(texts, rules),
            check_facts(texts, facts, discount_pct=offer_pct),
            check_discount(texts, rules, offer_pct=offer_pct),
            check_live_length(plan, facts),
        ]
    )


def check_edited_text(text: str, facts: DraftFacts, rules: ContentRules) -> Verdict:
    """The checks a seller's own edit of one block must pass (no length frame)."""
    texts = [text]
    return Verdict(
        [
            check_banned(texts, rules),
            check_protected(texts, rules),
            check_facts(texts, facts, discount_pct=rules.discount_cap_pct),
            check_discount(texts, rules, offer_pct=None),
        ]
    )


__all__ = [
    "BANNED_PATTERNS",
    "CHECKS_LINE_VI",
    "CHECK_LABELS",
    "CheckResult",
    "ContentRules",
    "DraftFacts",
    "Verdict",
    "check_banned",
    "check_discount",
    "check_edited_text",
    "check_facts",
    "check_live",
    "check_protected",
    "check_video",
]
