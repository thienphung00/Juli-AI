"""The listing family's pure core (contract 8: title, keyword, cover_image, price_display).

No I/O, no model: the same listing and keyword list always give the same proposal. A listing
is audited against the shop's own keyword key list (up to five "Chính" keywords per product,
ADR-120 d.11):

- ``missing``  -- a core keyword is not in the title;
- ``late``     -- it is there but ends beyond the first ``TITLE_VISIBLE_CHARS`` characters
  (the same test the product page applies: folded substring, ``product.keyword_block``);
- ``too_long`` -- the title is longer than ``MAX_TITLE_CHARS``.

``propose_title`` rewrites the title with the shop's own words and its own core keywords only:
a core keyword that is missing or late is written as a whole phrase at the head of the title
(highest search volume first), the rest of the title follows in its original order, words
that only repeat an inserted phrase are dropped, banned terms are stripped, and the result is
cut back to ``MAX_TITLE_CHARS`` at a word boundary. A keyword that cannot fit inside the
visible characters is reported as ``unplaced`` instead of being squeezed in.

Banned terms are the seller's "Từ không được dùng" plus the generic claim patterns the content
cards already refuse (``content_cards.guardrails``): the proposal passes the same
``check_banned`` the content drafts pass, or no card is made.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from juli_backend.services.content_cards.guardrails import (
    BANNED_PATTERNS,
    ContentRules,
    check_banned,
)
from juli_backend.services.shopee_analytics.fee_table import fold
from juli_backend.services.shopee_recommendations import config

_PUNCT = re.compile(r"[^\w]+", re.UNICODE)


# ---------------------------------------------------------------------------- the listing


@dataclass(frozen=True)
class Keyword:
    keyword: str
    role: str  # chinh | phu | thuong_hieu | loai_tru
    volume: int | None = None  # monthly searches (shopeeanalytics.com, collected by the owner)
    difficulty: float | None = None


@dataclass(frozen=True)
class Listing:
    """What the listing generators know about one product."""

    item_id: str
    title: str | None
    cover_url: str | None = None
    image_count: int = 0
    price: Decimal | None = None
    keywords: tuple[Keyword, ...] = ()

    def role(self, role: str) -> list[Keyword]:
        return [k for k in self.keywords if k.role == role]

    def core(self) -> list[Keyword]:
        """The "Chính" keywords, highest volume first (unknown last), then name."""
        return sorted(self.role("chinh"), key=_priority)[: config.MAX_CORE_KEYWORDS]


def _priority(k: Keyword) -> tuple[int, int, float, str]:
    return (
        0 if k.volume is not None else 1,
        -(k.volume or 0),
        k.difficulty if k.difficulty is not None else 1e9,
        k.keyword,
    )


# --------------------------------------------------------------------------- title audit


@dataclass(frozen=True)
class TitleAudit:
    chars: int
    too_long: bool
    placed: tuple[str, ...]
    missing: tuple[str, ...]
    late: tuple[str, ...]

    @property
    def issue_count(self) -> int:
        return len(self.missing) + len(self.late) + int(self.too_long)

    def json(self) -> dict[str, Any]:
        return {
            "chars": self.chars,
            "max_chars": config.MAX_TITLE_CHARS,
            "visible_chars": config.TITLE_VISIBLE_CHARS,
            "too_long": self.too_long,
            "core_placed": list(self.placed),
            "core_missing": list(self.missing),
            "core_late": list(self.late),
        }


def audit_title(title: str, core: Sequence[str]) -> TitleAudit:
    folded = fold(title)
    placed: list[str] = []
    missing: list[str] = []
    late: list[str] = []
    for kw in core:
        f = fold(kw)
        pos = folded.find(f) if f else -1
        if pos < 0:
            missing.append(kw)
        elif pos + len(f) > config.TITLE_VISIBLE_CHARS:
            late.append(kw)
        else:
            placed.append(kw)
    return TitleAudit(
        len(title),
        len(title) > config.MAX_TITLE_CHARS,
        tuple(placed),
        tuple(missing),
        tuple(late),
    )


# ----------------------------------------------------------------------- banned terms


def banned_phrases(seller_terms: Sequence[str]) -> list[str]:
    """The seller's own banned words first, then the generic claim patterns."""
    return list(dict.fromkeys([*(t for t in seller_terms if t.strip()), *BANNED_PATTERNS]))


def is_clean(text: str, seller_terms: Sequence[str]) -> bool:
    """The same check the content drafts pass (``check_banned``)."""
    return check_banned([text], ContentRules(banned_terms=tuple(seller_terms))).ok


def _tok(word: str) -> str:
    return _PUNCT.sub("", fold(word))


def _phrase_tokens(phrase: str) -> list[str]:
    return [t for t in (_tok(w) for w in phrase.split()) if t]


@dataclass
class _Word:
    text: str
    tok: str


def _find(words: Sequence[_Word], tokens: Sequence[str], skip: set[int] | None = None) -> int:
    n = len(tokens)
    if not n:
        return -1
    for i in range(len(words) - n + 1):
        if skip and any(j in skip for j in range(i, i + n)):
            continue
        if all(words[i + j].tok == tokens[j] for j in range(n)):
            return i
    return -1


def _strip_banned(words: list[_Word], phrases: Sequence[str]) -> tuple[list[_Word], list[str]]:
    removed: list[str] = []
    out = list(words)
    for phrase in phrases:
        tokens = _phrase_tokens(phrase)
        while (at := _find(out, tokens)) >= 0:
            removed.append(" ".join(w.text for w in out[at : at + len(tokens)]))
            del out[at : at + len(tokens)]
    return out, removed


def _hits(text: str, phrases: Sequence[str]) -> bool:
    toks = [_Word(w, _tok(w)) for w in text.split()]
    return any(_find(toks, _phrase_tokens(p)) >= 0 for p in phrases)


def _styled(keyword: str, words: Sequence[_Word]) -> str:
    """An inserted keyword is written in the title's own style (Title Case, UPPER or plain)."""
    letters = [w.text for w in words if any(c.isalpha() for c in w.text)]
    if letters and all(w.upper() == w for w in letters if len(w) > 1):
        return keyword.upper()
    if letters and sum(w[0].isupper() for w in letters) * 2 > len(letters):
        return keyword.title()
    return keyword


# --------------------------------------------------------------------------- the rewrite


@dataclass(frozen=True)
class TitleProposal:
    title: str
    before: TitleAudit
    after: TitleAudit
    inserted: tuple[str, ...] = ()
    moved: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    unplaced: tuple[str, ...] = ()
    banned_removed: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())

    def json(self) -> dict[str, Any]:
        return {
            "before": self.before.json(),
            "after": self.after.json(),
            "inserted": list(self.inserted),
            "moved": list(self.moved),
            "dropped_repeats": list(self.removed),
            "unplaced": list(self.unplaced),
            "banned_removed": list(self.banned_removed),
        }


def _joined(parts: Iterable[str]) -> str:
    return " ".join(p for p in parts if p)


def cut_title(text: str, limit: int | None = None) -> str:
    """``text`` cut back to ``limit`` (default ``MAX_TITLE_CHARS``) at a word boundary: trailing
    words go first, a single word longer than the limit is cut hard. Whitespace is normalised."""
    cap = config.MAX_TITLE_CHARS if limit is None else limit
    words = text.split()
    while words and len(" ".join(words)) > cap:
        words.pop()
    if not words:
        return text.strip()[:cap].rstrip()
    return " ".join(words)


def _build(
    words: list[_Word],
    order: list[str],
    move: set[str],
) -> tuple[list[str], list[_Word], set[str], set[str]]:
    """(head phrases, rest of the words, tokens of the inserted phrases, inserted keywords)."""
    head: list[str] = []
    consumed: set[int] = set()
    inserted_tokens: set[str] = set()
    inserted: set[str] = set()
    for kw in order:
        if kw not in move:
            continue
        tokens = _phrase_tokens(kw)
        at = _find(words, tokens, consumed)
        if at >= 0:
            head.append(_joined(w.text for w in words[at : at + len(tokens)]))
            consumed.update(range(at, at + len(tokens)))
        else:
            head.append(_styled(kw, words))
            inserted_tokens.update(tokens)
            inserted.add(kw)
    rest = [w for i, w in enumerate(words) if i not in consumed]
    return head, rest, inserted_tokens, inserted


def propose_title(
    title: str, core: Sequence[str], seller_banned: Sequence[str] = ()
) -> TitleProposal | None:
    """A better title from the product's own words and core keywords, or ``None`` when the
    title has nothing to fix or the rewrite would not improve it."""
    phrases = banned_phrases(seller_banned)
    before = audit_title(title, core)
    words = [_Word(w, _tok(w)) for w in title.split()]
    words, banned_removed = _strip_banned(words, phrases)
    words = [w for w in words if w.tok]  # a lone "-" or "|" carries nothing
    usable = [k for k in core if not _hits(k, phrases)]
    skipped_banned = [k for k in core if k not in usable]
    # a keyword inside a longer core keyword is covered by it
    order = [
        k
        for k in usable
        if not any(o != k and fold(k) in fold(o) for o in usable if len(fold(o)) > len(fold(k)))
    ]
    if before.issue_count == 0 and not banned_removed:
        return None
    audit0 = audit_title(_joined(w.text for w in words), order)
    move = set(audit0.missing) | set(audit0.late)
    unplaced: list[str] = list(skipped_banned)
    head: list[str] = []
    rest: list[_Word] = words
    dropped: list[str] = []
    inserted: set[str] = set()
    for _ in range(2 * len(order) + 2):
        head, rest, inserted_tokens, inserted = _build(words, order, move)
        protected: set[int] = set()
        for kw in order:
            if kw in move:
                continue
            tokens = _phrase_tokens(kw)
            at = _find(rest, tokens)
            if at >= 0:
                protected.update(range(at, at + len(tokens)))
        kept: list[_Word] = []
        dropped = []
        for i, w in enumerate(rest):
            if i not in protected and w.tok in inserted_tokens:
                dropped.append(w.text)
            else:
                kept.append(w)
        rest = kept
        while rest and len(_joined([*head, *(w.text for w in rest)])) > config.MAX_TITLE_CHARS:
            rest.pop()  # trailing words go first
        audit = audit_title(_joined([*head, *(w.text for w in rest)]), order)
        bad = set(audit.missing) | set(audit.late)
        if not bad:
            break
        if bad - move:
            move |= bad - move  # moving phrases pushed an untouched keyword out of view
            continue
        # a moved keyword cannot fit in the visible characters: give up the weakest one
        weakest = next(k for k in reversed(order) if k in bad)
        move.discard(weakest)
        order = [k for k in order if k != weakest]
        unplaced.append(weakest)
    else:
        return None
    title_out = _joined([*head, *(w.text for w in rest)])
    after = audit_title(title_out, core)
    if title_out == title or (after.issue_count >= before.issue_count and not banned_removed):
        return None
    if len(title_out) > config.MAX_TITLE_CHARS or not is_clean(title_out, seller_banned):
        return None
    return TitleProposal(
        title=title_out,
        before=before,
        after=after,
        inserted=tuple(k for k in core if k in inserted),
        moved=tuple(k for k in core if k in move and k not in inserted),
        removed=tuple(dropped),
        unplaced=tuple(dict.fromkeys(unplaced)),
        banned_removed=tuple(banned_removed),
    )


# -------------------------------------------------------------------- keyword promotion


@dataclass(frozen=True)
class KeywordProposal:
    promote: Keyword
    demote: Keyword | None
    core_before: tuple[str, ...]
    core_after: tuple[str, ...]
    reason: str

    def json(self) -> dict[str, Any]:
        return {
            "promote": self.promote.keyword,
            "promote_volume": self.promote.volume,
            "demote": None if self.demote is None else self.demote.keyword,
            "demote_volume": None if self.demote is None else self.demote.volume,
            "core_before": list(self.core_before),
            "core_after": list(self.core_after),
        }


def propose_keywords(
    listing: Listing, seller_banned: Sequence[str] = (), *, nth: int = 0
) -> KeywordProposal | None:
    """Promote the best "Phụ" keyword to "Chính": into a free slot, or in place of the weakest
    "Chính" one when its volume is at least ``KEYWORD_SWAP_FACTOR`` times higher. Needs the
    market volumes (shopeeanalytics.com, collected by the owner); no volume, no proposal."""
    phrases = banned_phrases(seller_banned)
    core = listing.role("chinh")
    pool = [
        k
        for k in listing.role("phu")
        if k.volume is not None
        and k.volume >= config.KEYWORD_MIN_VOLUME
        and not _hits(k.keyword, phrases)
    ]
    if not pool:
        return None
    ordered = sorted(pool, key=_priority)
    if nth >= len(ordered):
        return None
    best = ordered[nth]
    before = tuple(k.keyword for k in sorted(core, key=_priority))
    if len(core) < config.MAX_CORE_KEYWORDS:
        after = (*before, best.keyword)
        return KeywordProposal(
            best,
            None,
            before,
            after,
            f"Còn {config.MAX_CORE_KEYWORDS - len(core)} chỗ trống trong từ khoá Chính; "
            f"“{best.keyword}” có {best.volume} lượt tìm / tháng.",
        )
    known = [k for k in core if k.volume is not None]
    if len(known) < len(core):
        return None  # a core keyword without a number cannot be compared
    weakest = sorted(known, key=lambda k: (k.volume or 0, k.keyword))[0]
    if (best.volume or 0) < config.KEYWORD_SWAP_FACTOR * (weakest.volume or 0):
        return None
    after = tuple(k for k in before if k != weakest.keyword) + (best.keyword,)
    return KeywordProposal(
        best,
        weakest,
        before,
        after,
        f"“{best.keyword}” có {best.volume} lượt tìm / tháng, nhiều hơn “{weakest.keyword}” "
        f"({weakest.volume}); thay vào vị trí thứ {config.MAX_CORE_KEYWORDS} của từ khoá Chính.",
    )


# ------------------------------------------------------------------------ unit price

_UNITS: dict[str, tuple[str, Decimal, str]] = {
    # folded unit -> (base unit, factor to base, per-quantity label)
    "ml": ("ml", Decimal(1), "100ml"),
    "l": ("ml", Decimal(1000), "100ml"),
    "lit": ("ml", Decimal(1000), "100ml"),
    "g": ("g", Decimal(1), "100g"),
    "gr": ("g", Decimal(1), "100g"),
    "gram": ("g", Decimal(1), "100g"),
    "kg": ("g", Decimal(1000), "100g"),
    "vien": ("viên", Decimal(1), "viên"),
    "mieng": ("miếng", Decimal(1), "miếng"),
    "cai": ("cái", Decimal(1), "cái"),
    "goi": ("gói", Decimal(1), "gói"),
    "cuon": ("cuộn", Decimal(1), "cuộn"),
    "doi": ("đôi", Decimal(1), "đôi"),
    "tui": ("túi", Decimal(1), "túi"),
    "chai": ("chai", Decimal(1), "chai"),
    "hop": ("hộp", Decimal(1), "hộp"),
}
_SIZE = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)\s*([a-z]+)(?![\w])")


@dataclass(frozen=True)
class UnitPrice:
    size_text: str  # as written in the title, e.g. "500ml"
    quantity: Decimal  # in the base unit
    base_unit: str
    per_label: str
    per_price: Decimal  # VND per ``per_label``

    def line(self, price: Decimal) -> str:
        return f"{vnd(price)} / {self.size_text} ≈ {vnd(self.per_price)} mỗi {self.per_label}"


def vnd(value: Decimal | int | float) -> str:
    n = int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return f"{n:,}".replace(",", ".") + "đ"


def unit_price(title: str, price: Decimal | None) -> UnitPrice | None:
    """VND per 100 ml / 100 g / piece from the size written in the title (first one found)."""
    if price is None or price <= 0:
        return None
    for m in _SIZE.finditer(fold(title)):
        unit = _UNITS.get(m.group(2))
        if unit is None:
            continue
        try:
            number = Decimal(m.group(1).replace(",", "."))
        except ArithmeticError:
            continue
        if number <= 0:
            continue
        base, factor, per = unit
        quantity = number * factor
        per_qty = Decimal(100) if per.startswith("100") else Decimal(1)
        if quantity <= per_qty:
            continue  # the price is already per 100 ml / per piece
        raw = title[m.start() : m.end()] if len(title) == len(fold(title)) else m.group(0)
        return UnitPrice(raw.strip(), quantity, base, per, price / quantity * per_qty)
    return None


# ------------------------------------------------------------------ planned changes (p91 D-13)

#: Longest first line of a product description a card carries / the Connector fills.
MAX_DESCRIPTION_LINE_CHARS = 500
#: Most variations a restructure card lists, and the longest name / SKU of one.
MAX_VARIATIONS = 50
MAX_VARIATION_NAME_CHARS = 60
MAX_VARIATION_SKU_CHARS = 100
MAX_VARIATION_PRICE = 500_000_000
MAX_VARIATION_STOCK = 1_000_000


def check_variation(row: object) -> str | None:
    """Why one target variation (``name``, ``price``, ``sku``, ``stock``) is unusable, or None."""
    if not isinstance(row, dict):
        return "not_a_row"
    name = str(row.get("name") or "").strip()
    if not name or len(name) > MAX_VARIATION_NAME_CHARS:
        return "name"
    price, stock, sku = row.get("price"), row.get("stock"), row.get("sku")
    if isinstance(price, bool) or not isinstance(price, int | float) or not 0 < price:
        return "price"
    if price > MAX_VARIATION_PRICE:
        return "price"
    if stock is not None and (
        isinstance(stock, bool)
        or not isinstance(stock, int)
        or not 0 <= stock <= MAX_VARIATION_STOCK
    ):
        return "stock"
    if sku is not None and (not isinstance(sku, str) or len(sku) > MAX_VARIATION_SKU_CHARS):
        return "sku"
    return None


def check_planned(kind: str, inputs: dict[str, object], banned_terms: Sequence[str]) -> str | None:
    """Refusal code for the D-13 kinds' inputs (None = usable). Pure."""
    if kind == "description_first_line":
        line = str(inputs.get("first_line") or "").strip()
        if not line:
            return "description_empty"
        if len(line) > MAX_DESCRIPTION_LINE_CHARS or "\n" in line:
            return "description_too_long"
        if not is_clean(line, banned_terms):
            return "banned_term"
    elif kind == "variation_restructure":
        rows = inputs.get("variations")
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_VARIATIONS:
            return "variations_invalid:count"
        for n, row in enumerate(rows, 1):
            why = check_variation(row)
            if why:
                return f"variations_invalid:row{n}:{why}"
        names = [str(r["name"]).strip().casefold() for r in rows]
        if len(set(names)) != len(names):
            return "variations_invalid:duplicate"
    elif kind == "listing_relist":
        stock = inputs.get("stock")
        if stock is not None and (
            isinstance(stock, bool) or not isinstance(stock, int) or stock < 0
        ):
            return "stock_invalid"
    return None
