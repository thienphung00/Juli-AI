"""Keyword combinations from a shop's own product titles (ADR-119, D81.4 / D81.6).

Pure and deterministic: same titles in, same candidates out, no I/O, no model.

A buyer searches a combination, not a word: "miếng rửa chén", "nước rửa chén 500ml",
"<brand> rửa chén". So each title is cut into facets and the facets are recombined:

- **tokens**: NFC, lower case, split on anything that is not a letter or digit; marketing
  noise ("chính hãng", "freeship", years …) is dropped. Each token keeps its display form
  (with diacritics) and a matching key (diacritics stripped, ``đ`` → ``d``); a token written
  without diacritics matches a lexicon entry by key, one written with them by its own form,
  so "dầu" never matches "đầu".
- **size**: a number with a unit -- ``500ml``, ``1,5l``, ``1kg``, ``30 viên``, ``2 cuộn``.
- **brand**: the operator's brand words (or the shop name) found in the title; without them,
  the leading words most titles share, if they are not a product word.
- **type / material** from a small lexicon (``miếng``, ``bàn chải`` …; ``xơ mướp``, ``tre``,
  ``inox`` …); **function** = a function verb (``rửa``, ``chống``, ``làm sạch`` …) plus the
  next word when it is no other facet (``rửa chén``, ``chống nắng``); a complete function
  (``giữ nhiệt``, ``dưỡng ẩm`` …) takes no object. A type directly followed by its function
  is read as one product phrase (``nước rửa chén``) when combined with the brand, a material
  or a size.
- **common phrase**: any 2-4 word run (no noise, no size) shared by two or more titles,
  kept only when no longer run has the same titles.

Patterns, in priority order (a combination produced by two patterns keeps the first):
``brand_type``, ``brand_function``, ``brand_material``, ``type_function_material``,
``type_function``, ``type_material``, ``function_material``, ``function_size``,
``type_size``, ``common_phrase``.

A candidate is kept when it appears in at least :data:`MIN_TITLES` titles, or it pairs the
brand with another facet. The operator trims the rest.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

MIN_TITLES = 2
MAX_KEYWORD_LENGTH = 200
MAX_FUNCTION_OBJECT = 1
PHRASE_MIN, PHRASE_MAX = 2, 4
#: Share of titles that must start with the same words for them to be read as the brand.
BRAND_SHARE = 0.6

PATTERNS: tuple[str, ...] = (
    "brand_type",
    "brand_function",
    "brand_material",
    "type_function_material",
    "type_function",
    "type_material",
    "function_material",
    "function_size",
    "type_size",
    "common_phrase",
)
BRAND_PATTERNS = frozenset(p for p in PATTERNS if p.startswith("brand_"))


def _words(text: str) -> tuple[str, ...]:
    """A comma-separated lexicon written as prose (one entry may hold spaces)."""
    entries = (" ".join(entry.split()) for entry in text.split(","))
    return tuple(entry for entry in entries if entry)


TYPES: tuple[str, ...] = _words(
    """
    miếng, bàn chải, khăn, chai, lọ, hũ, tuýp, nước, kem, dầu, xà phòng, xà bông, sữa tắm, sữa
    rửa mặt, gel, serum, tinh dầu, bột, viên, túi, hộp, cốc, ly, bình, nồi, chảo, dao, thớt,
    đũa, muỗng, thìa, cọ, chổi, giẻ, bông, găng tay, mút, mặt nạ, son, phấn, xịt, lăn, sáp,
    thảm, chiếu, gối, chăn, nệm, rèm, khay, rổ, giỏ, kệ, móc, áo, quần, váy, giày, dép, mũ, nón,
    tất, vớ, balo, ví, ốp, cáp, sạc, tai nghe, đèn, quạt, ghế, bàn, dây, băng, cuộn, lưới, đá,
    trà
    """
)
MATERIALS: tuple[str, ...] = _words(
    """
    xơ mướp, tre, gỗ, inox, nhựa, silicon, silicone, cotton, thủy tinh, thuỷ tinh, sứ, gốm,
    nhôm, vải, len, lụa, da bò, cao su, tự nhiên, hữu cơ, organic, thép, tơ tằm, nỉ, xốp, than
    tre, nha đam, trà xanh, nghệ, bồ kết, dừa, sả, tràm, quế, gừng, bạc hà, than hoạt tính
    """
)
FUNCTION_VERBS: tuple[str, ...] = _words(
    """
    rửa, lau, tẩy, khử, diệt, trị, giảm, chống, ngừa, làm sạch, làm trắng, làm mềm, làm đẹp,
    dưỡng, dưỡng ẩm, cấp ẩm, tắm, gội, massage, mát xa, bảo vệ, giữ nhiệt, giữ ấm, hút, lọc,
    sấy, đánh, chà, kỳ, hỗ trợ, tăng, kích thích, se khít, thơm, đuổi, bảo quản, đựng, treo
    """
)
#: Functions that are complete on their own: no object word is attached.
COMPLETE_FUNCTIONS: tuple[str, ...] = _words(
    """
    giữ nhiệt, giữ ấm, dưỡng ẩm, cấp ẩm, se khít, massage, mát xa, làm đẹp, bảo quản
    """
)
NOISE: tuple[str, ...] = _words(
    """
    chính hãng, freeship, free ship, giá rẻ, giá sỉ, sỉ, sale, hot, hot trend, mới, new, cao
    cấp, siêu rẻ, rẻ, tặng, quà tặng, khuyến mãi, loại 1, hàng, chuẩn, xịn, uy tín, official,
    store, shop, mall, chất lượng
    """
)
#: A common phrase never starts or ends on one of these.
CONNECTORS = frozenset(
    {"và", "cho", "của", "với", "dùng", "loại", "có", "các", "những", "để", "từ", "tại", "x"}
)

#: Metric units are written against the number ("500ml"), count units after a space.
_METRIC_UNITS = {
    "ml": "ml",
    "l": "l",
    "lit": "l",
    "g": "g",
    "gr": "g",
    "gram": "g",
    "kg": "kg",
    "mg": "mg",
    "cm": "cm",
    "mm": "mm",
    "m": "m",
    "oz": "oz",
}
_COUNT_UNITS = {
    "vien": "viên",
    "goi": "gói",
    "hop": "hộp",
    "chai": "chai",
    "tui": "túi",
    "mieng": "miếng",
    "cai": "cái",
    "ong": "ống",
    "tuyp": "tuýp",
    "cuon": "cuộn",
    "doi": "đôi",
    "set": "set",
}
_NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")
_NUMBER_UNIT = re.compile(r"^(\d+(?:[.,]\d+)?)([a-z]+)$")
_YEAR = re.compile(r"^20\d\d$")
#: A word, or a number that keeps its decimal part and a unit written against it ("1,5l").
_WORD = re.compile(r"\d+(?:[.,]\d+)*[^\W\d_]*|[^\W_]+", re.UNICODE)


def fold(text: str) -> str:
    """Matching key: lower case, diacritics stripped, ``đ`` → ``d``."""
    decomposed = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


@dataclass(frozen=True)
class Title:
    """One platform item's title."""

    item_id: str
    title: str


@dataclass(frozen=True)
class Candidate:
    """A keyword combination, the pattern it follows and the items it came from."""

    keyword: str
    pattern: str
    item_ids: tuple[str, ...]

    @property
    def title_count(self) -> int:
        return len(self.item_ids)


@dataclass(frozen=True)
class _Token:
    word: str
    key: str

    def matches(self, entry: _Token) -> bool:
        # A token written with diacritics must match exactly; a bare-ASCII one by key.
        return self.word == entry.word or (self.word == self.key and self.key == entry.key)


@dataclass(frozen=True)
class _Facet:
    kind: str  # brand | type | material | function | size
    words: tuple[str, ...]
    keys: tuple[str, ...]
    segment: int
    start: int

    @property
    def end(self) -> int:
        return self.start + len(self.words)

    @property
    def display(self) -> str:
        return " ".join(self.words)


def _tokens(text: str) -> list[_Token]:
    words = _WORD.findall(unicodedata.normalize("NFC", text.lower()))
    return [_Token(w, fold(w)) for w in words]


def _lexicon(entries: Iterable[str]) -> list[tuple[_Token, ...]]:
    # Longest first, so "bàn chải" wins over "bàn" and "sữa rửa mặt" over "sữa".
    seqs = [tuple(_tokens(e)) for e in entries]
    return sorted(seqs, key=len, reverse=True)


_TYPES = _lexicon(TYPES)
_MATERIALS = _lexicon(MATERIALS)
_VERBS = _lexicon(FUNCTION_VERBS)
_COMPLETE = _lexicon(COMPLETE_FUNCTIONS)
_NOISE = _lexicon(NOISE)


def _match(tokens: Sequence[_Token], at: int, lexicon: list[tuple[_Token, ...]]) -> int:
    """Length of the longest lexicon entry starting at ``at`` (0 = none)."""
    for entry in lexicon:
        end = at + len(entry)
        if end <= len(tokens) and all(t.matches(e) for t, e in zip(tokens[at:end], entry)):
            return len(entry)
    return 0


def _size_at(tokens: Sequence[_Token], at: int) -> tuple[int, str] | None:
    """A size token ("500ml", or "500" "ml") at ``at``: (length, display)."""
    key = tokens[at].key
    joined = _NUMBER_UNIT.match(key)
    if joined and (joined.group(2) in _METRIC_UNITS or joined.group(2) in _COUNT_UNITS):
        return 1, _size_display(joined.group(1), joined.group(2))
    if _NUMBER.match(key) and at + 1 < len(tokens):
        unit = tokens[at + 1].key
        if unit in _METRIC_UNITS or unit in _COUNT_UNITS:
            return 2, _size_display(key, unit)
    return None


def _size_display(number: str, unit: str) -> str:
    if unit in _METRIC_UNITS:
        return f"{number}{_METRIC_UNITS[unit]}"
    return f"{number} {_COUNT_UNITS[unit]}"


@dataclass
class _Parsed:
    item_id: str
    segments: list[list[_Token]]  # split at noise; a size is one token
    facets: list[_Facet]


def _clean(title: str) -> list[_Token | None]:
    """Tokens with noise removed (``None`` marks a break a phrase may not cross)."""
    raw = _tokens(title)
    out: list[_Token | None] = []
    i = 0
    while i < len(raw):
        noise = _match(raw, i, _NOISE)
        if noise or _YEAR.match(raw[i].key):
            out.append(None)
            i += noise or 1
            continue
        size = _size_at(raw, i)
        if size is not None:
            length, display = size
            out.append(_Token(display, fold(display)))
            i += length
            continue
        out.append(raw[i])
        i += 1
    return out


def _segments(tokens: list[_Token | None]) -> list[list[_Token]]:
    segments: list[list[_Token]] = [[]]
    for token in tokens:
        if token is None:
            if segments[-1]:
                segments.append([])
        else:
            segments[-1].append(token)
    return [s for s in segments if s]


def _is_size(token: _Token) -> bool:
    joined = _NUMBER_UNIT.match(token.key.replace(" ", ""))
    if joined is None:
        return False
    return joined.group(2) in _METRIC_UNITS or joined.group(2) in _COUNT_UNITS


def _facets(segment: list[_Token], index: int, brand: tuple[_Token, ...] | None) -> list[_Facet]:
    facets: list[_Facet] = []
    i = 0

    def take(kind: str, length: int) -> None:
        nonlocal i
        part = segment[i : i + length]
        words, keys = tuple(t.word for t in part), tuple(t.key for t in part)
        facets.append(_Facet(kind, words, keys, index, i))
        i += length

    def other_facet_at(at: int) -> bool:
        return bool(
            _match(segment, at, _TYPES)
            or _match(segment, at, _MATERIALS)
            or _match(segment, at, _VERBS)
            or _is_size(segment[at])
            or (brand and _brand_at(segment, at, brand))
        )

    while i < len(segment):
        if brand and _brand_at(segment, i, brand):
            take("brand", len(brand))
        elif _is_size(segment[i]):
            take("size", 1)
        elif length := _match(segment, i, _VERBS):
            end = i + length
            complete = _match(segment, i, _COMPLETE) == length
            while not complete and end < len(segment) and end - (i + length) < MAX_FUNCTION_OBJECT:
                if segment[end].key in CONNECTORS or other_facet_at(end):
                    break
                end += 1
            take("function", end - i)
        elif length := _match(segment, i, _MATERIALS):
            take("material", length)
        elif length := _match(segment, i, _TYPES):
            take("type", length)
        else:
            i += 1
    return facets


def _brand_at(segment: Sequence[_Token], at: int, brand: tuple[_Token, ...]) -> bool:
    end = at + len(brand)
    return end <= len(segment) and all(t.key == b.key for t, b in zip(segment[at:end], brand))


def _parse(title: Title, brand: tuple[_Token, ...] | None) -> _Parsed:
    segments = _segments(_clean(title.title))
    facets = [f for n, seg in enumerate(segments) for f in _facets(seg, n, brand)]
    return _Parsed(title.item_id, segments, facets)


def _infer_brand(titles: Sequence[Title]) -> tuple[_Token, ...] | None:
    """The leading 1-2 words most titles share, unless they are a product word."""
    if len(titles) < MIN_TITLES:
        return None
    leads: Counter[tuple[str, ...]] = Counter()
    spelled: dict[tuple[str, ...], tuple[_Token, ...]] = {}
    for title in titles:
        tokens = [t for t in _clean(title.title) if t is not None]
        for n in (2, 1):
            if len(tokens) >= n:
                keys = tuple(t.key for t in tokens[:n])
                leads[keys] += 1
                spelled.setdefault(keys, tuple(tokens[:n]))
    need = max(MIN_TITLES, int(len(titles) * BRAND_SHARE + 0.999))
    for keys, count in sorted(leads.items(), key=lambda kv: (-len(kv[0]), -kv[1], kv[0])):
        if count < need:
            continue
        seq = spelled[keys]
        if any(_match(seq, 0, lex) for lex in (_TYPES, _MATERIALS, _VERBS)) or _is_size(seq[0]):
            continue
        return seq
    return None


def _brand_tokens(brand: str | None) -> tuple[_Token, ...] | None:
    if not brand:
        return None
    tokens = tuple(t for t in _clean(brand) if t is not None)
    return tokens or None


def _combos(facets: list[_Facet]) -> list[tuple[str, tuple[_Facet, ...]]]:
    """(pattern, facets in keyword order) for one title, in pattern priority order."""
    first: dict[str, _Facet] = {}
    for facet in facets:
        first.setdefault(facet.kind, facet)
    # "nước" + "rửa chén" written together is the product phrase "nước rửa chén".
    kind_type, kind_function = first.get("type"), first.get("function")
    if (
        kind_type is not None
        and kind_function is not None
        and (kind_type.segment, kind_type.end) == (kind_function.segment, kind_function.start)
    ):
        first["product"] = _Facet(
            "product",
            kind_type.words + kind_function.words,
            kind_type.keys + kind_function.keys,
            kind_type.segment,
            kind_type.start,
        )
    out: list[tuple[str, tuple[_Facet, ...]]] = []
    by = {
        "brand_type": ("brand", "type"),
        "brand_function": ("brand", "function"),
        "brand_material": ("brand", "material"),
        "type_function_material": ("type", "function", "material"),
        "type_function": ("type", "function"),
        "type_material": ("type", "material"),
        "function_material": ("function", "material"),
        "function_size": ("function", "size"),
        "type_size": ("type", "size"),
    }
    for pattern, kinds in by.items():
        if pattern in ("brand_type", "type_material", "type_size") and "product" in first:
            kinds = tuple("product" if k == "type" else k for k in kinds)
        if all(k in first for k in kinds):
            out.append((pattern, tuple(first[k] for k in kinds)))
    return out


def _phrases(parsed: Sequence[_Parsed]) -> dict[tuple[str, ...], tuple[set[str], tuple[str, ...]]]:
    """Every 2-4 word run (by key) -> (item ids, first display form)."""
    found: dict[tuple[str, ...], tuple[set[str], tuple[str, ...]]] = {}
    for p in parsed:
        for segment, start in ((seg, i) for seg in p.segments for i in range(len(seg))):
            for n in range(PHRASE_MIN, PHRASE_MAX + 1):
                run = segment[start : start + n]
                if len(run) < n or any(_is_size(t) for t in run):
                    break
                if run[0].key in CONNECTORS or run[-1].key in CONNECTORS:
                    continue
                key = tuple(t.key for t in run)
                items, display = found.setdefault(key, (set(), tuple(t.word for t in run)))
                items.add(p.item_id)
    return found


def _maximal(
    phrases: dict[tuple[str, ...], tuple[set[str], tuple[str, ...]]],
) -> list[tuple[str, ...]]:
    """Shared runs with no longer shared run over the same titles."""
    shared = {k: v for k, v in phrases.items() if len(v[0]) >= MIN_TITLES}
    keep = []
    for key, (items, _) in shared.items():
        dominated = any(
            len(other) > len(key)
            and other_items == items
            and any(other[i : i + len(key)] == key for i in range(len(other) - len(key) + 1))
            for other, (other_items, _) in shared.items()
        )
        if not dominated:
            keep.append(key)
    return keep


def _inside_combo(padded: str, run_items: set[str], items: dict[str, set[str]]) -> bool:
    """A shared run cut out of a longer combination over the same titles adds nothing."""
    return any(ids == run_items and padded in f" {key} " for key, ids in items.items())


def decompose(titles: Sequence[Title], *, brand: str | None = None) -> list[Candidate]:
    """Keyword candidates for one shop's titles; see the module docstring."""
    usable = [t for t in titles if t.title and t.title.strip()]
    brand_seq = _brand_tokens(brand) or _infer_brand(usable)
    parsed = [_parse(t, brand_seq) for t in usable]

    items: dict[str, set[str]] = {}
    pattern_of: dict[str, str] = {}
    displays: dict[str, Counter[str]] = {}
    for p in parsed:
        for pattern, facets in _combos(p.facets):
            words = " ".join(f.display for f in facets)
            key = " ".join(" ".join(f.keys) for f in facets)
            if key not in pattern_of or PATTERNS.index(pattern) < PATTERNS.index(pattern_of[key]):
                pattern_of[key] = pattern
            items.setdefault(key, set()).add(p.item_id)
            displays.setdefault(key, Counter())[words] += 1

    phrases = _phrases(parsed)
    brand_key = " ".join(t.key for t in brand_seq) if brand_seq else None
    for run in _maximal(phrases):
        key = " ".join(run)
        run_items, display = phrases[run]
        if key in pattern_of:
            # A combination one title produced, shared verbatim by others: same pattern.
            items[key] |= run_items
            continue
        if key == brand_key or _inside_combo(f" {key} ", run_items, items):
            continue
        pattern_of[key] = "common_phrase"
        items[key] = set(run_items)
        displays[key] = Counter({" ".join(display): len(run_items)})

    out: list[Candidate] = []
    for key, pattern in pattern_of.items():
        ids = items[key]
        if len(ids) < MIN_TITLES and pattern not in BRAND_PATTERNS:
            continue
        # Most frequent spelling; on a tie the one with diacritics, then alphabetical order.
        spellings = displays[key].items()
        keyword = sorted(spellings, key=lambda kv: (-kv[1], kv[0] == fold(kv[0]), kv[0]))[0][0]
        if len(keyword) > MAX_KEYWORD_LENGTH:
            continue
        out.append(Candidate(keyword, pattern, tuple(sorted(ids))))
    out.sort(key=lambda c: (-c.title_count, PATTERNS.index(c.pattern), c.keyword))
    return out
