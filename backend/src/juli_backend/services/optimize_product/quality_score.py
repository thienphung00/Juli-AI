"""Quality Score, layer 1 (D30.2): a rule-based 0–100 per product. Pure, no OpenAI.

Built only from what the pipeline already has; a part whose input is unknown is
``None`` and left out of the score (never scored as 0 -- deriving a fault from an
empty value invents it, OP-NFR-2):

- ``title``: length against TikTok VN's 40-character floor, minus TikTok title codes;
- ``search_fit``: share of the shop's SEO / Opportunities words found in the title
  (only when those words were already fetched);
- ``image``: TikTok image codes, else the sub-image count (≥ 3) when known;
- ``description``: TikTok description codes, else ≥ 200 text characters with
  sections when the description is known;
- ``video`` / ``attributes``: when known (the D30.1 snapshot will carry them);
- ``category``: the category check against TikTok's Recommend Category (a hook);
- ``compliance``: a small rule list of risky claims in the title / description --
  absolute claims everywhere, health claims for food and beverage (Vietnamese terms).

D30.5: internal. The score goes into the card payload (``quality``) for debugging and
into the ranking (:func:`lever_weight`: a lever whose part is weak ranks higher for
that lever); nothing seller-facing shows it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from juli_backend.services.optimize_product.listing_signals import (
    Evidence,
    is_description_code,
    is_image_code,
    is_title_code,
)

#: Part weights (sum 100); the score is the weighted mean over the known parts.
WEIGHTS: Mapping[str, int] = {
    "title": 25,
    "image": 20,
    "description": 15,
    "search_fit": 15,
    "compliance": 10,
    "video": 5,
    "attributes": 5,
    "category": 5,
}

#: TikTok VN listing-quality reference: title ≥ 40 characters (listing_signals);
#: D30.2: description ≥ 200 characters with sections, ≥ 3 sub-images.
TITLE_MIN_CHARS = 40
DESCRIPTION_MIN_CHARS = 200
SUB_IMAGES_MIN = 3
CODE_PENALTY = 30

#: Absolute claims TikTok Shop VN policy treats as misleading in any category.
RISKY_CLAIMS_ANY: tuple[str, ...] = (
    "tốt nhất thế giới",
    "số 1 thế giới",
    "số một thế giới",
    "rẻ nhất",
    "cam kết 100%",
    "hiệu quả 100%",
    "an toàn tuyệt đối",
)
#: Health claims a food / beverage listing may not make (thực phẩm không phải thuốc).
RISKY_CLAIMS_FOOD: tuple[str, ...] = (
    "chữa bệnh",
    "chữa khỏi",
    "điều trị",
    "trị dứt điểm",
    "khỏi hẳn",
    "thần dược",
    "thay thế thuốc",
    "giảm cân cấp tốc",
    "hết tiểu đường",
    "ngừa ung thư",
    "chống ung thư",
    "tăng chiều cao",
    "đặc trị",
)
FOOD_CATEGORY_HINTS: tuple[str, ...] = (
    "thực phẩm",
    "đồ uống",
    "thức uống",
    "nước uống",
    "đồ ăn",
    "food",
    "beverage",
    "drink",
    "trà",
    "cà phê",
)

#: Which part a lever improves (price / promotion levers improve none).
LEVER_PART: Mapping[str, str] = {
    "cover_image": "image",
    "title": "title",
    "description": "description",
}
#: How much a fully weak part (score 0) lifts its lever's ranking: weight 1 + 0.5.
WEAK_PART_BOOST = 0.5


@dataclass(frozen=True)
class ListingFacts:
    """What is known about one listing; ``None`` = not known (no snapshot yet)."""

    title: str
    category: str | None = None
    description: str | None = None
    sub_image_count: int | None = None
    has_video: bool | None = None
    attributes_filled_share: float | None = None
    #: Category matches TikTok's Recommend Category (hook; ``None`` until checked).
    category_ok: bool | None = None
    #: The shop's SEO / Opportunities words, when already fetched.
    seo_words: Sequence[str] | None = None
    #: Product ids TikTok was asked about count their (possibly empty) code list.
    tiktok_asked: bool = False


@dataclass(frozen=True)
class QualityScore:
    score: int
    parts: dict[str, int | None]
    issues: tuple[str, ...] = field(default_factory=tuple)

    def gap(self, lever_code: str) -> int | None:
        """100 − the lever's part score; ``None`` when the lever has no part or it is unknown."""
        part = LEVER_PART.get(lever_code)
        value = self.parts.get(part) if part else None
        return None if value is None else 100 - value

    def to_json(self) -> dict[str, Any]:
        return {"score": self.score, "parts": dict(self.parts), "issues": list(self.issues)}


_SPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_SECTION_RE = re.compile(r"<br\s*/?>|</p>|<li[\s>]|\n", re.IGNORECASE)


def _norm(text: str) -> str:
    return _SPACE_RE.sub(" ", text.lower()).strip()


def risky_claims(text: str, category: str | None) -> list[str]:
    """The risky claims found in ``text`` (lower-cased substring match)."""
    lowered = _norm(text)
    found = [c for c in RISKY_CLAIMS_ANY if c in lowered]
    food = category is not None and any(h in _norm(category) for h in FOOD_CATEGORY_HINTS)
    if food:
        found += [c for c in RISKY_CLAIMS_FOOD if c in lowered]
    return found


def _clip(value: float) -> int:
    return int(max(0, min(100, round(value))))


def _code_part(codes: Iterable[str], matcher: Any) -> int:
    return _clip(100 - CODE_PENALTY * sum(1 for c in codes if matcher(c)))


def quality_score(facts: ListingFacts, evidence: Iterable[Evidence] = ()) -> QualityScore:
    """D30.2 for one product. ``evidence`` = TikTok codes and Juli's local title codes."""
    items = list(evidence)
    tiktok_codes = [e.code for e in items if e.source.value == "tiktok"]
    issues: list[str] = []
    parts: dict[str, int | None] = {k: None for k in WEIGHTS}

    title = facts.title or ""
    length_part = 100 * min(len(title), TITLE_MIN_CHARS) / TITLE_MIN_CHARS
    title_codes = sum(1 for c in tiktok_codes if is_title_code(c))
    title_score = _clip(length_part - CODE_PENALTY * title_codes)
    parts["title"] = title_score
    if len(title) < TITLE_MIN_CHARS:
        issues.append(f"title_under_{TITLE_MIN_CHARS}_chars")

    if facts.seo_words:
        words = [_norm(w) for w in facts.seo_words if w and w.strip()]
        if words:
            lowered = _norm(title)
            parts["search_fit"] = _clip(100 * sum(1 for w in words if w in lowered) / len(words))

    if facts.tiktok_asked:
        parts["image"] = _code_part(tiktok_codes, is_image_code)
    elif facts.sub_image_count is not None:
        parts["image"] = _clip(100 * min(facts.sub_image_count, SUB_IMAGES_MIN) / SUB_IMAGES_MIN)

    if facts.tiktok_asked:
        parts["description"] = _code_part(tiktok_codes, is_description_code)
    elif facts.description is not None:
        text = _TAG_RE.sub("", facts.description).strip()
        sectioned = bool(_SECTION_RE.search(facts.description))
        length = 100 * min(len(text), DESCRIPTION_MIN_CHARS) / DESCRIPTION_MIN_CHARS
        parts["description"] = _clip(length if sectioned else min(length, 60))

    if facts.has_video is not None:
        parts["video"] = 100 if facts.has_video else 0
    if facts.attributes_filled_share is not None:
        parts["attributes"] = _clip(100 * facts.attributes_filled_share)
    if facts.category_ok is not None:
        parts["category"] = 100 if facts.category_ok else 0
        if not facts.category_ok:
            issues.append("category_mismatch")

    claims = risky_claims(" ".join([title, facts.description or ""]), facts.category)
    parts["compliance"] = _clip(100 - 50 * len(claims))
    issues.extend(f"risky_claim:{c}" for c in claims)

    known = {k: v for k, v in parts.items() if v is not None}
    total = sum(WEIGHTS[k] for k in known)
    score = _clip(sum(WEIGHTS[k] * v for k, v in known.items()) / total) if total else 0
    return QualityScore(score=score, parts=parts, issues=tuple(issues))


def lever_weight(quality: QualityScore | None, lever_code: str) -> float:
    """Ranking weight for one lever: 1 + 0.5 × (its part's gap / 100); 1 when unknown."""
    if quality is None:
        return 1.0
    gap = quality.gap(lever_code)
    return 1.0 if gap is None else 1.0 + WEAK_PART_BOOST * gap / 100


__all__ = [
    "LEVER_PART",
    "RISKY_CLAIMS_ANY",
    "RISKY_CLAIMS_FOOD",
    "WEIGHTS",
    "ListingFacts",
    "QualityScore",
    "lever_weight",
    "quality_score",
    "risky_claims",
]
