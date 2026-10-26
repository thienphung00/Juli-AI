"""Deterministic filter for the model-drafted title / description of a NEW listing (P69).

The prompt asks for specific, plain copy, but a model still sometimes writes filler
("phù hợp cho nhu cầu sử dụng hằng ngày"), talks about Juli or its rules, or repeats a
sentence. This module is the code-side guarantee, run twice (``catalog_create``): before
the reviewer is asked (:func:`screen_listing_draft` -> a refusal makes the model draft
again) and again right before the write (:func:`clean_listing_draft`).

Rules (all deterministic, no model call):

1. Whitespace is normalised; HTML tags, markdown markers and emoji are removed.
2. A sentence that talks about Juli / the AI / the shop's rules, or that is a meta
   preamble ("Dưới đây là mô tả ...") is dropped.
3. A sentence that is generic filler (a known marketing cliche) is dropped when it carries
   no number / unit / material. One that does is cut down to those facts when nothing else
   is left ("Bình ... 750ml phù hợp cho nhu cầu sử dụng hằng ngày." -> "Bình ... 750ml."),
   and kept as it is when it says more than that.
4. A repeated sentence (same words, case and accents aside) is dropped.
5. The title keeps TikTok's length bounds (``TITLE_MIN_CHARS`` .. ``TITLE_MAX_CHARS``,
   ``shop_rules``): a longer title is cut on a word boundary, a shorter one is rejected.
   The description keeps ``DESCRIPTION_MIN_CHARS`` .. ``DESCRIPTION_MAX_CHARS`` the same
   way (cut on a sentence boundary).
6. An empty or too-short result is REJECTED, never shipped; anything else is REPLACED by the
   filtered text (:func:`normalize_create_product`), so the proposal the seller confirms is
   exactly what is written. The filter is idempotent.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from pydantic import BaseModel

from juli_backend.services.shop_rules.listing_edits import TITLE_MAX_CHARS, TITLE_MIN_CHARS

#: The tool input's bounds for a new listing's description (``CreateProductInput``).
DESCRIPTION_MIN_CHARS = 20
DESCRIPTION_MAX_CHARS = 5_000

ERROR_LISTING_TEXT_REJECTED = "listing_text_rejected"

REASON_META = "meta"
REASON_FILLER = "filler"
REASON_DUPLICATE = "duplicate"

_TAG = re.compile(r"<[^>]*>")
_MARKDOWN = re.compile(r"(\*\*|__|`|^#{1,6}\s*|^\s*[-*•]\s+)", re.MULTILINE)
_EMOJI = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f2ff️‍]")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_WRAPPING_QUOTES = " \t\"'“”‘’«»"

#: Talk about Juli, the model or the rules: never part of a product listing.
_META_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bjuli\b",
        r"(?-i:\bAI\b)|\b(?:chatgpt|gpt)\b",
        r"trí tuệ nhân tạo|mô hình ngôn ngữ|trợ lý ảo",
        r"quy tắc|từ cấm|kiểm tra độ dài|ký tự cho phép",
        r"^(?:dưới đây|sau đây) là\b",
        r"^(?:tiêu đề|mô tả)\s*(?:mới|đề xuất|gợi ý)?\s*:",
        r"\b(?:bản nháp|sandbox|đề xuất của tôi)\b",
    )
)

#: Marketing filler that says nothing about this product.
_FILLER_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"phù hợp (?:cho|với) (?:nhu cầu|mọi nhu cầu)(?: sử dụng)?(?: hằng| hàng| mỗi)? ?(?:ngày)?",
        r"đáp ứng (?:tốt |đầy đủ |mọi )?(?:nhu cầu|lượng \w+ cần thiết)",
        r"hoạt động năng động",
        r"(?:tiện (?:lợi )?mang theo|dễ dàng mang theo) khi đi học",
        r"lựa chọn (?:hoàn hảo|lý tưởng|tuyệt vời)",
        r"không thể thiếu trong",
        r"chất lượng (?:cao cấp|vượt trội|tuyệt vời)",
        r"thiết kế (?:chắc chắn|sang trọng|hiện đại|tinh tế),? tiện",
        r"mang (?:lại|đến) (?:trải nghiệm|sự tiện lợi)",
    )
)


#: A fact a filler sentence may carry: a number (size, capacity, quantity) or a material.
_SPECIFIC = re.compile(
    r"\d|thép không gỉ|inox|nhựa|gỗ|cotton|silicone|thủy tinh|gốm|sứ|nhôm|vải|tre\b",
    re.IGNORECASE,
)
_CONNECTIVES = frozenset({"giúp", "để", "và", "với", "cho", "trong", "ngày", "hằng", "hàng", ","})
#: What is left of a filler sentence may be at most this many words to be rewritten.
_MAX_REMAINDER_WORDS = 8


@dataclass(frozen=True)
class DroppedSentence:
    reason: str
    text: str


@dataclass(frozen=True)
class CleanedListing:
    title: str
    description: str
    #: Sentences removed from the description (meta / filler / duplicate).
    dropped: tuple[DroppedSentence, ...] = ()
    #: The title or description was cut to fit its length bound.
    truncated: bool = False


class ListingTextRejected(ValueError):
    """The draft cannot be shipped (empty, too short, or nothing specific left)."""

    def __init__(self, message: str, *, dropped: tuple[DroppedSentence, ...] = ()) -> None:
        super().__init__(message)
        self.dropped = dropped


@dataclass
class _Sentences:
    kept: list[str] = field(default_factory=list)
    dropped: list[DroppedSentence] = field(default_factory=list)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    letters = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", letters.lower()).strip()


def _strip_markup(text: str) -> str:
    text = _TAG.sub(" ", text)
    text = _MARKDOWN.sub("", text)
    return _EMOJI.sub("", text)


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _is_meta(sentence: str) -> bool:
    return any(p.search(sentence) for p in _META_PATTERNS)


def _filler_match(sentence: str) -> re.Match[str] | None:
    for pattern in _FILLER_PATTERNS:
        found = pattern.search(sentence)
        if found is not None:
            return found
    return None


def _trim_filler(sentence: str, found: re.Match[str]) -> str | None:
    """``None`` = drop the sentence; else the sentence to keep (possibly cut down)."""
    if _SPECIFIC.search(sentence) is None:
        return None
    rest = f"{sentence[: found.start()]} {sentence[found.end() :]}"
    tokens = [w.strip(".!?…") for w in rest.replace(",", " ").split()]
    words = [w for w in tokens if w and w.lower() != "giúp"]
    while words and words[-1].lower() in _CONNECTIVES:
        words.pop()
    if not words:
        return None
    if len(words) > _MAX_REMAINDER_WORDS:
        return sentence  # it says more than the filler phrase: keep it whole
    return " ".join(words) + "."


def _title_is_filler(title: str) -> bool:
    return _filler_match(title) is not None and _SPECIFIC.search(title) is None


def _clean_title(raw: str) -> tuple[str, bool]:
    title = _collapse(_strip_markup(raw)).strip(_WRAPPING_QUOTES).rstrip(".")
    truncated = False
    if len(title) > TITLE_MAX_CHARS:
        head = title[: TITLE_MAX_CHARS + 1]
        space = head.rfind(" ")
        title = (head[:space] if space >= TITLE_MIN_CHARS else title[:TITLE_MAX_CHARS]).rstrip(
            " ,;:-"
        )
        truncated = True
    return title, truncated


def _split_paragraphs(raw: str) -> list[list[str]]:
    paragraphs: list[list[str]] = []
    for block in re.split(r"\n\s*\n|\n", _strip_markup(raw)):
        sentences = [_collapse(s) for s in _SENTENCE_END.split(_collapse(block))]
        sentences = [s for s in sentences if s]
        if sentences:
            paragraphs.append(sentences)
    return paragraphs


def _fit_description(paragraphs: list[str]) -> tuple[str, bool]:
    """Join paragraphs with a newline; cut on a paragraph / sentence boundary at the cap."""
    text = "\n".join(paragraphs)
    if len(text) <= DESCRIPTION_MAX_CHARS:
        return text, False
    head = text[:DESCRIPTION_MAX_CHARS]
    cut = max(head.rfind(". "), head.rfind("\n"))
    return (head[: cut + 1] if cut > DESCRIPTION_MIN_CHARS else head).strip(), True


def clean_listing_draft(title: str, description: str) -> CleanedListing:
    """The shippable title / description, or :class:`ListingTextRejected`."""
    clean_title, title_cut = _clean_title(title)
    if not clean_title:
        raise ListingTextRejected("Tiêu đề trống.")
    if _is_meta(clean_title) or _title_is_filler(clean_title):
        raise ListingTextRejected("Tiêu đề nói về Juli, quy tắc hoặc là câu chung chung.")
    if len(clean_title) < TITLE_MIN_CHARS:
        raise ListingTextRejected(
            f"Tiêu đề chỉ có {len(clean_title)} ký tự, cần từ {TITLE_MIN_CHARS} ký tự."
        )

    state = _Sentences()
    seen: set[str] = set()
    paragraphs: list[str] = []
    for sentences in _split_paragraphs(description):
        kept_here: list[str] = []
        for sentence in sentences:
            if _is_meta(sentence):
                state.dropped.append(DroppedSentence(REASON_META, sentence))
            elif (found := _filler_match(sentence)) is not None and (
                (sentence := _trim_filler(sentence, found) or "") != found.string
            ):
                state.dropped.append(DroppedSentence(REASON_FILLER, found.string))
                if sentence and (key := _fold(sentence)) not in seen:
                    seen.add(key)
                    kept_here.append(sentence)
            elif (key := _fold(sentence)) in seen:
                state.dropped.append(DroppedSentence(REASON_DUPLICATE, sentence))
            else:
                seen.add(key)
                kept_here.append(sentence)
        if kept_here:
            paragraphs.append(" ".join(kept_here))
    dropped = tuple(state.dropped)
    if not paragraphs:
        raise ListingTextRejected(
            "Mô tả trống hoặc chỉ có câu chung chung / ghi chú ngoài lề.", dropped=dropped
        )
    clean_description, desc_cut = _fit_description(paragraphs)
    if len(clean_description) < DESCRIPTION_MIN_CHARS:
        raise ListingTextRejected(
            f"Mô tả chỉ có {len(clean_description)} ký tự, cần từ {DESCRIPTION_MIN_CHARS} ký tự.",
            dropped=dropped,
        )
    return CleanedListing(
        title=clean_title,
        description=clean_description,
        dropped=dropped,
        truncated=title_cut or desc_cut,
    )


def screen_listing_draft(title: str, description: str) -> str | None:
    """Why the draft must be written again (for the model), or ``None`` when it can ship.

    Only a draft that is empty / too short / nothing but filler or meta talk is refused;
    anything else is replaced by its filtered text before the seller is asked.
    """
    try:
        clean_listing_draft(title, description)
    except ListingTextRejected as rejection:
        return _hint(str(rejection), rejection.dropped)
    return None


def normalize_create_product(params: BaseModel) -> BaseModel | None:
    """The params with the filtered title / description, or ``None`` when nothing changes
    (or the draft is rejected: the pre-check then refuses it)."""
    title, description = getattr(params, "title", None), getattr(params, "description", None)
    if not isinstance(title, str) or not isinstance(description, str):
        return None
    try:
        cleaned = clean_listing_draft(title, description)
    except ListingTextRejected:
        return None
    if (cleaned.title, cleaned.description) == (title, description):
        return None
    return params.model_copy(update={"title": cleaned.title, "description": cleaned.description})


def _hint(message: str, dropped: tuple[DroppedSentence, ...]) -> str:
    lines = [
        f"error_code={ERROR_LISTING_TEXT_REJECTED}: {message}",
        "Draft the title and description again: Vietnamese, specific to THIS product "
        "(use the source title's real attributes: size, material, capacity, quantity), no "
        "generic marketing filler, no mention of Juli, the AI or any rule, no repeated "
        "sentence. Then call the tool again (once).",
    ]
    lines.extend(f"- {d.reason}: {d.text[:120]!r}" for d in dropped[:5])
    return "\n".join(lines)


__all__ = [
    "DESCRIPTION_MAX_CHARS",
    "DESCRIPTION_MIN_CHARS",
    "ERROR_LISTING_TEXT_REJECTED",
    "REASON_DUPLICATE",
    "REASON_FILLER",
    "REASON_META",
    "CleanedListing",
    "DroppedSentence",
    "ListingTextRejected",
    "clean_listing_draft",
    "normalize_create_product",
    "screen_listing_draft",
]
