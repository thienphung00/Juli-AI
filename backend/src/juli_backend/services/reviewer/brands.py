"""Brand words of a shop, for the reviewer mask's free-text pass (P86).

The dictionary (catalog titles, shop name) misses a brand written another way, a shortened
product name, or a brand that appears only inside product titles. This module derives
candidate brand words from data the catalog load already reads (the product titles, a
``brand`` / ``brand_name`` value in a payload, the shop name, ``REVIEWER_MASK_TERMS``) and
finds them in free text: case-insensitive, diacritics-insensitive, whole-word.

Deterministic and pure: no I/O. Display / reviewer only -- nothing here is ever sent to TikTok.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable

MIN_TERM = 3
#: A derived brand recurs in at least this many distinct titles (a one-off word is a name
#: of nothing in particular, and the structural mask already aliases the whole title).
MIN_TITLES = 2

#: Common Vietnamese / English product words, units and shop words: never a brand.
#: Compared diacritics-folded and lower-cased (:func:`fold`).
GENERIC_WORDS = frozenset(
    """
    noi binh thep inox chinh hang cao cap gia dung nha bep phong ngu sinh hoat loai tot
    moi hop bo set cai chiec cap doi may dien nuoc nong lanh giu nhiet cung kem theo
    qua tang tang khuyen mai combo freeship ship giao nhanh sale hot gia re uu dai
    nguoi lon tre em nam nu be gai trai mau den trang xanh do vang tim hong nau xam
    kich thuoc dung tich cong suat chat lieu thuan viet viet nam han quoc nhat ban trung
    quoc my duc thai lan cua hang thuong hieu san pham phu kien linh phan bien the
    chong dinh khong dau tran ap suat lo chien nuong hap nau com dun sieu toc cam tay
    ep trai cay xay sinh to ca phe tra am ly coc chen bat dia dua thia muong dao keo thot
    chao xoong ham quay dien tu tu lanh quat sach tui balo ao quan vay giay dep non kinh
    gau bong hoa den led usb pin sac cap bluetooth wifi smart pro max mini plus ultra
    lite basic classic premium deluxe standard new hot best sale off free gift set pack
    pcs pc kit with for and the one two size color black white red blue green pink grey
    gray gold silver steel stainless water bottle cup mug pot pan fryer air cooker
    kettle bag box case cover mat lamp light fan oil
    ml l lit kg g gr mg cm mm m inch w v ah mah hz
    """.split()
) | frozenset({"thuong", "hieu", "pham", "ban", "demo", "live", "video", "tep", "shop", "tiktok"})

_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)
_ALNUM_EDGE = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"


def fold(text: str) -> str:
    """Lower-cased, diacritics removed, one output character per input character.

    Each character keeps its position, so a match found in the folded text maps straight
    back onto the original (``đ`` → ``d``; a precomposed vowel → its base letter).
    """
    out: list[str] = []
    for char in text:
        base = unicodedata.normalize("NFD", char)[:1]
        lowered = base.lower()
        out.append("d" if base in ("đ", "Đ") else lowered if len(lowered) == 1 else base or char)
    return "".join(out)


def is_generic(term: str) -> bool:
    """True when every word of ``term`` is a generic product / unit / shop word."""
    words = _TOKEN.findall(fold(term))
    return not words or all(word in GENERIC_WORDS for word in words)


def _is_capitalised(token: str) -> bool:
    return token[:1].isupper()


def derive_from_titles(titles: Iterable[str]) -> tuple[str, ...]:
    """Capitalised Latin words recurring across ``titles`` that look like a brand.

    A candidate is a word of 3+ letters, capitalised in every title that has it, never
    written lower-case anywhere in the titles (a lower-case use means it is a common word),
    not a generic word, and present in at least :data:`MIN_TITLES` distinct titles.
    Returned sorted (stable) by folded form; the first-seen spelling stands for the word.
    """
    seen_in: dict[str, set[int]] = defaultdict(set)
    spelling: dict[str, str] = {}
    lowered: set[str] = set()
    for index, title in enumerate(dict.fromkeys(t.strip() for t in titles if t and t.strip())):
        for token in _TOKEN.findall(title):
            key = fold(token)
            if len(key) < MIN_TERM:
                continue
            if _is_capitalised(token):
                seen_in[key].add(index)
                spelling.setdefault(key, token)
            else:
                lowered.add(key)
    found = [
        spelling[key]
        for key, where in seen_in.items()
        if len(where) >= MIN_TITLES and key not in lowered and key not in GENERIC_WORDS
    ]
    return tuple(sorted(found, key=fold))


def usable(term: str | None) -> str | None:
    """``term`` stripped, or None when it is too short or a generic word."""
    text = (term or "").strip()
    if len(fold(text)) < MIN_TERM or is_generic(text):
        return None
    return text


def compile_terms(terms: Iterable[str]) -> re.Pattern[str] | None:
    """One pattern over the diacritics-folded text: whole-word, longest term first."""
    folded = {fold(t).strip() for t in terms if t and len(fold(t).strip()) >= MIN_TERM}
    if not folded:
        return None
    parts = [r"\s+".join(re.escape(w) for w in t.split()) for t in sorted(folded, key=len)[::-1]]
    left, right = _ALNUM_EDGE
    return re.compile(f"{left}(?:{'|'.join(parts)}){right}")


def scrub(text: str, pattern: re.Pattern[str] | None, replacement: str) -> str:
    """``text`` with every whole-word term replaced (spans found on the folded text)."""
    if pattern is None or not text:
        return text
    folded = fold(text)
    out: list[str] = []
    last = 0
    for match in pattern.finditer(folded):
        out.append(text[last : match.start()])
        out.append(replacement)
        last = match.end()
    out.append(text[last:])
    return "".join(out)


__all__ = [
    "GENERIC_WORDS",
    "MIN_TITLES",
    "compile_terms",
    "derive_from_titles",
    "fold",
    "is_generic",
    "scrub",
    "usable",
]
