"""The shop's own listing voice, read off its listings (fast track P76-6, D78 step 6).

Optimize Product prompt v4 asks the model to edit a listing *in the shop's voice*.
This module is the deterministic half of that: no model call, no I/O. The caller
(the agent worker, ``workers/tasks/agent_workflow.py``) hands in the shop's listings
-- best sellers first when it knows per-product sales, else catalog order -- and gets
a :class:`VoiceProfile` back, then :func:`voice_profile_context` turns it into the
``voice_profile`` block of the run's opening ``source: "juli"`` context message.

Profile fields
--------------
* ``title_pattern`` -- the most common token-class sequence of the titles, e.g.
  ``[pack/size] [product] [brand] [volume] [benefit]``. Each title is split on
  whitespace, every token classed (``pack/size``, ``volume``, ``brand``, ``number``,
  ``emoji``, else a word), runs of one class collapsed, the first word run named
  ``product`` and every later one ``benefit``. Ties go to the best seller's pattern.
* ``median_title_chars`` / ``median_description_text_chars`` -- medians over the
  listings that carry one (description text after the P76-3 parse, HTML stripped).
* ``emoji_rate`` -- share of listings whose title or description has an emoji.
* ``all_caps_rate`` -- share of the titles' alphabetic words (2+ letters) in capitals.
* ``addressing`` -- how the shop addresses the buyer: ``ban`` (bạn), ``anh_chi``
  (anh chị), ``chi_em`` (chị em) or ``none``; the most frequent wins.
* ``description_style`` -- ``bullets`` / ``paragraphs`` / ``mixed`` / ``unknown``.
* ``recurring_phrases`` -- 2-3 word phrases found in at least two listings, top
  :data:`MAX_PHRASES` by listing count.
* ``examples`` -- up to :data:`MAX_EXAMPLES` of the shop's own listings (the bound
  product excluded by the caller), title + description text capped at
  :data:`EXAMPLE_CHAR_CAP` characters each.

Untrusted data (ADR-070)
------------------------
The examples and phrases are the seller's own vendor text. :func:`voice_profile_context`
wraps each one as a ``VendorText`` provenance envelope (capped) and passes the whole
block through ``guard_inbound_tool_result`` -- hidden text stripped, banned patterns
scanned. On a hit the examples and phrases are dropped and only the numeric profile
travels. The block lives in the run's conversation state only; no reviewer route
returns it (the reviewer mask, ``services/reviewer/masking.py``, applies to route
payloads, and none carries the opening context).

Cache
-----
:class:`VoiceProfileCache` keeps one built context per shop for :data:`CACHE_TTL`
(in-process, like the worker's other per-process caches), so a shop's later runs in
the same worker reuse it with no new database or TikTok read.
"""

from __future__ import annotations

import re
import statistics
import threading
import unicodedata
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from juli_backend.services.agent.sanitize import VendorText, cap_text, to_json_safe
from juli_backend.services.agent.sanitize.chokepoints import guard_inbound_tool_result
from juli_backend.services.shop_rules.listing_structure import (
    SectionKind,
    parse_description,
    section_text,
)

#: How many listings the profile reads (best sellers first).
MAX_LISTINGS = 30
#: How many of the shop's own listings travel as examples.
MAX_EXAMPLES = 3
#: Each example's title + description is cut at this many characters.
EXAMPLE_CHAR_CAP = 1500
#: How many recurring phrases travel.
MAX_PHRASES = 8
#: How long one shop's profile is reused in a worker process.
CACHE_TTL = timedelta(hours=6)
#: Most shops one worker process keeps a profile for.
CACHE_MAX_SHOPS = 256

_PACK_WORDS = frozenset(
    ("combo", "set", "pack", "bộ", "hộp", "thùng", "lốc", "gói", "túi", "chai", "lọ", "hũ")
    + ("cặp", "đôi")
)
_UNITS = "ml|l|lit|lít|g|gr|gram|kg|mg|cm|mm|m|oz|vien|viên|cai|cái|chiec|chiếc|mieng|miếng"
_VOLUME_RE = re.compile(rf"^\d+(?:[.,]\d+)?(?:{_UNITS})$", re.IGNORECASE)
_MULTIPLIER_RE = re.compile(r"^(?:x\d+|\d+x)$", re.IGNORECASE)
_NUMBER_RE = re.compile(r"^\d+(?:[.,]\d+)?%?$")
_UNIT_ONLY_RE = re.compile(rf"^(?:{_UNITS})$", re.IGNORECASE)
_EDGE_PUNCT = "[](){}<>|,.;:!?\"'-_/+*#"
_WORD_RE = re.compile(r"[^\W\d_]+")
_BULLET_PREFIXES = ("-", "•", "*", "+", "✔", "✓", "✅", "👉", "🔸", "🔹", "▪", "❤", "⭐", "🌟")

_ADDRESSING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anh_chi", re.compile(r"(?<!\w)anh\s*/?\s*chị(?!\w)", re.IGNORECASE)),
    ("chi_em", re.compile(r"(?<!\w)chị\s+em(?!\w)", re.IGNORECASE)),
    ("ban", re.compile(r"(?<!\w)bạn(?!\w)", re.IGNORECASE)),
)


@dataclass(frozen=True)
class ShopListing:
    """One of the shop's listings, as the caller read it."""

    title: str
    description_html: str | None = None
    #: The brand TikTok has on this listing (``brand.name``), if read.
    brand: str | None = None


@dataclass(frozen=True)
class VoiceExample:
    title: str
    description_text: str


@dataclass(frozen=True)
class VoiceProfile:
    listings_read: int
    title_pattern: tuple[str, ...]
    median_title_chars: int | None
    median_description_text_chars: int | None
    emoji_rate: float
    all_caps_rate: float
    addressing: str
    description_style: str
    recurring_phrases: tuple[str, ...] = ()
    examples: tuple[VoiceExample, ...] = field(default_factory=tuple)


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _is_emoji(char: str) -> bool:
    return unicodedata.category(char) == "So" or 0x1F000 <= ord(char) <= 0x1FAFF


def _has_emoji(text: str) -> bool:
    return any(_is_emoji(char) for char in text)


def _token_class(token: str, brands: frozenset[str]) -> str | None:
    """The class of one title token; ``None`` for pure punctuation."""
    if token and all(_is_emoji(char) for char in token):
        return "emoji"
    bare = token.strip(_EDGE_PUNCT)
    if not bare:
        return None
    lowered = bare.lower()
    if lowered in brands:
        return "brand"
    if _VOLUME_RE.match(bare):
        return "volume"
    if _MULTIPLIER_RE.match(bare) or lowered in _PACK_WORDS:
        return "pack/size"
    if _NUMBER_RE.match(bare):
        return "number"
    if _UNIT_ONLY_RE.match(bare):
        return "volume"
    letters = "".join(_WORD_RE.findall(bare))
    if len(letters) >= 2 and letters.isupper():
        return "brand"
    return "word"


def title_pattern(title: str, brand_terms: Sequence[str] = ()) -> tuple[str, ...]:
    """``title`` as a collapsed token-class sequence (see the module docstring)."""
    brands = frozenset(_nfc(term).lower() for term in brand_terms if term.strip())
    lowered_title = _nfc(title).lower()
    classes: list[str] = []
    # A multi-word brand is one token class wherever it sits in the title.
    text = _nfc(title)
    for brand in sorted(brands, key=len, reverse=True):
        if " " in brand and brand in lowered_title:
            start = lowered_title.index(brand)
            text = text[:start] + "\x00" + text[start + len(brand) :]
            lowered_title = text.lower()
    for token in text.split():
        cls = "brand" if token == "\x00" else _token_class(token, brands)
        if cls is None or (classes and classes[-1] == cls):
            continue
        if cls == "number" and classes and classes[-1] in {"volume", "pack/size"}:
            continue
        classes.append(cls)
    named: list[str] = []
    seen_word = False
    for cls in classes:
        if cls == "word":
            cls = "benefit" if seen_word else "product"
            seen_word = True
        named.append(cls)
    return tuple(named)


def _description_lines(description_html: str) -> list[tuple[str, bool]]:
    """``(line, is_bullet)`` for every text line of the description."""
    lines: list[tuple[str, bool]] = []
    for section in parse_description(description_html):
        if section.kind is SectionKind.LIST:
            lines.extend((item.text, True) for item in section.items)
        elif section.kind is SectionKind.PARAGRAPH:
            lines.extend((line, line.startswith(_BULLET_PREFIXES)) for line in section.lines)
    return lines


def description_plain_text(description_html: str) -> str:
    """The description's text, one section per line, no markup (P76-3 parse)."""
    return "\n".join(
        section_text(section)
        for section in parse_description(description_html)
        if section.kind is not SectionKind.RAW
    )


def _median(values: Sequence[int]) -> int | None:
    return int(statistics.median(values)) if values else None


def _addressing(texts: Sequence[str]) -> str:
    counts = Counter[str]()
    for text in texts:
        for name, pattern in _ADDRESSING_PATTERNS:
            counts[name] += len(pattern.findall(_nfc(text)))
    if not counts or max(counts.values()) == 0:
        return "none"
    order = [name for name, _ in _ADDRESSING_PATTERNS]
    return min(counts, key=lambda name: (-counts[name], order.index(name)))


def _description_style(descriptions: Sequence[str]) -> str:
    lines = [line for html in descriptions for line in _description_lines(html)]
    if not lines:
        return "unknown"
    bullet_share = sum(1 for _, is_bullet in lines if is_bullet) / len(lines)
    if bullet_share >= 0.5:
        return "bullets"
    if bullet_share < 0.2:
        return "paragraphs"
    return "mixed"


def _phrases(texts: Sequence[str]) -> tuple[str, ...]:
    """2-3 word phrases in at least two listings, by listing count then frequency."""
    listing_count = Counter[str]()
    total = Counter[str]()
    for text in texts:
        words = _WORD_RE.findall(_nfc(text).lower())
        grams = [
            " ".join(words[i : i + size]) for size in (2, 3) for i in range(len(words) - size + 1)
        ]
        total.update(grams)
        listing_count.update(set(grams))
    ranked = sorted(
        (gram for gram, count in listing_count.items() if count >= 2),
        key=lambda gram: (-listing_count[gram], -total[gram], -gram.count(" "), gram),
    )
    picked: list[str] = []
    for gram in ranked:
        # A 2-word phrase inside an already-picked 3-word one adds nothing.
        if any(gram in longer for longer in picked):
            continue
        picked.append(gram)
        if len(picked) == MAX_PHRASES:
            break
    return tuple(picked)


def _example(listing: ShopListing) -> VoiceExample:
    title = _nfc(listing.title.strip())
    budget = max(EXAMPLE_CHAR_CAP - len(title), 0)
    text = description_plain_text(listing.description_html or "")
    return VoiceExample(title=title[:EXAMPLE_CHAR_CAP], description_text=text[:budget])


def build_voice_profile(
    listings: Sequence[ShopListing],
    *,
    example_listings: Sequence[ShopListing] = (),
) -> VoiceProfile:
    """The shop's voice from ``listings`` (best sellers first; at most
    :data:`MAX_LISTINGS` read). ``example_listings`` (best first, the bound product
    already left out) supply up to :data:`MAX_EXAMPLES` examples. Pure and deterministic.
    """
    read = [listing for listing in listings if listing.title.strip()][:MAX_LISTINGS]
    brand_terms = tuple({listing.brand for listing in read if listing.brand})
    titles = [_nfc(listing.title.strip()) for listing in read]
    descriptions = [listing.description_html for listing in read if listing.description_html]

    patterns = [title_pattern(title, brand_terms) for title in titles]
    counts = Counter(patterns)
    pattern = (
        min(counts, key=lambda p: (-counts[p], patterns.index(p))) if patterns else tuple[str]()
    )
    words = [
        letters
        for title in titles
        for token in title.split()
        if len(letters := "".join(_WORD_RE.findall(token))) >= 2
    ]
    all_caps = sum(1 for word in words if word.isupper())
    emoji = sum(
        1
        for listing in read
        if _has_emoji(listing.title) or _has_emoji(listing.description_html or "")
    )
    texts = [
        f"{listing.title}\n{description_plain_text(listing.description_html or '')}"
        for listing in read
    ]
    examples = tuple(_example(listing) for listing in example_listings if listing.description_html)[
        :MAX_EXAMPLES
    ]
    return VoiceProfile(
        listings_read=len(read),
        title_pattern=pattern,
        median_title_chars=_median([len(title) for title in titles]),
        median_description_text_chars=_median(
            [len(description_plain_text(html)) for html in descriptions]
        ),
        emoji_rate=round(emoji / len(read), 2) if read else 0.0,
        all_caps_rate=round(all_caps / len(words), 2) if words else 0.0,
        addressing=_addressing(texts),
        description_style=_description_style(descriptions),
        recurring_phrases=_phrases(texts),
        examples=examples,
    )


def _vendor(text: str) -> dict[str, Any]:
    payload: dict[str, Any] = to_json_safe(VendorText(text=cap_text(text).text))
    return payload


def voice_profile_context(profile: VoiceProfile) -> dict[str, Any] | None:
    """The ``voice_profile`` block of the opening context message; ``None`` when the
    profile read no listing. Vendor text (examples, phrases) is provenance-wrapped and
    passed through the inbound chokepoint; a guard hit drops it (see module docstring).
    """
    if profile.listings_read == 0:
        return None
    block: dict[str, Any] = {
        "listings_read": profile.listings_read,
        "title_pattern": " ".join(f"[{cls}]" for cls in profile.title_pattern),
        "median_title_chars": profile.median_title_chars,
        "median_description_text_chars": profile.median_description_text_chars,
        "emoji_rate": profile.emoji_rate,
        "all_caps_rate": profile.all_caps_rate,
        "addressing": profile.addressing,
        "description_style": profile.description_style,
    }
    vendor: dict[str, Any] = {}
    if profile.recurring_phrases:
        vendor["recurring_phrases"] = [_vendor(phrase) for phrase in profile.recurring_phrases]
    if profile.examples:
        vendor["examples"] = [
            {"title": _vendor(example.title), "description": _vendor(example.description_text)}
            for example in profile.examples
        ]
    if vendor:
        guarded = guard_inbound_tool_result(vendor, tool_name="voice_profile")
        if "error" not in guarded:
            block.update(guarded)
    return {key: value for key, value in block.items() if value is not None}


class VoiceProfileCache:
    """One shop's ``voice_profile`` block per :data:`CACHE_TTL`, in-process.

    ``clock`` is injected for tests. Thread-safe; oldest entry evicted past
    :data:`CACHE_MAX_SHOPS`.
    """

    def __init__(self, *, clock: Callable[[], datetime], ttl: timedelta = CACHE_TTL) -> None:
        self._clock = clock
        self._ttl = ttl
        self._entries: dict[uuid.UUID, tuple[datetime, Mapping[str, Any] | None]] = {}
        self._lock = threading.Lock()

    def get(self, shop_id: uuid.UUID) -> tuple[bool, Mapping[str, Any] | None]:
        """``(hit, block)``; a cached ``None`` (a shop with no listing) is a hit."""
        with self._lock:
            entry = self._entries.get(shop_id)
            if entry is None or self._clock() - entry[0] >= self._ttl:
                return False, None
            return True, entry[1]

    def put(self, shop_id: uuid.UUID, block: Mapping[str, Any] | None) -> None:
        with self._lock:
            self._entries.pop(shop_id, None)
            self._entries[shop_id] = (self._clock(), block)
            while len(self._entries) > CACHE_MAX_SHOPS:
                self._entries.pop(next(iter(self._entries)))

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


__all__ = [
    "CACHE_TTL",
    "EXAMPLE_CHAR_CAP",
    "MAX_EXAMPLES",
    "MAX_LISTINGS",
    "MAX_PHRASES",
    "ShopListing",
    "VoiceExample",
    "VoiceProfile",
    "VoiceProfileCache",
    "build_voice_profile",
    "description_plain_text",
    "title_pattern",
    "voice_profile_context",
]
