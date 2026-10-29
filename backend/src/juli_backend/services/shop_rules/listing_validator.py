"""Post-validator for a drafted listing edit (fast track P76-4, D78).

Juli's Optimize Product run lets the model propose a new title / description for a
product the seller already sells. P76-3 (``listing_structure``) is the edit-ops half;
this module is the check every proposal passes before the seller is asked
(``product_write.precheck_update_product_listing``): it compares the proposal with the
listing as it is now and returns every rule it breaks. Pure; no model call, no I/O
beyond one structured log line for the drift guard.

Rules (each a :class:`ListingViolationCode`; the English ``message`` goes back to the
model for its one retry, ``message_vi`` is the seller's line):

* **Over limits (D78.3).** A listing whose current title is over ``TITLE_MAX_CHARS`` or
  whose current description is over ``DESCRIPTION_MAX_CHARS`` is refused and left
  unedited, whatever the proposal (``listing_over_limits``; no other rule is reported).
* **Title** (only when one is proposed): ``TITLE_MIN_CHARS`` (40, D78.1 -- TikTok's
  ``TITLE_LESS_THAN_40_CHARACTERS``) to ``TITLE_MAX_CHARS`` (255, VN is an "other
  region" of ``POST /product/202509/products/{id}``: ``[25, 255]``); not shorter than
  ``TITLE_MIN_KEEP_RATIO`` (80 %) of the current title; every **must-keep token** of
  the current title still present.
* **Description** (only when one is proposed), measured on its text after the P76-3
  parse (HTML stripped): at least the current description's text length and at least
  ``DESCRIPTION_MIN_TEXT_CHARS`` (500, ``DESC_LESS_THAN_FIVE_HUNDRED_CHARS``); more
  than one line or section (``DESC_NO_NEW_LINE``); the HTML at most
  ``DESCRIPTION_MAX_CHARS``.

Must-keep tokens are read off the CURRENT title: the shop's brand terms it carries, and
every quantity -- a number with a unit (``270mL``, ``1,5 lít``, ``500 ml``, ``12 Chai``,
``Thùng 24 Lon``, ``100%``) or a multiplier (``x2`` / ``2x``). They are compared after
folding case, Vietnamese diacritics, ``,``/``.`` decimals, unit spelling (``lít`` = ``l``)
and spacing, so ``500 ml`` keeps ``500mL``.

Warn-only, never a violation:

Kill switch: ``LISTING_VALIDATOR_ENFORCE=0`` (prompt v3 does not state these rules yet)
lets every violation but ``listing_over_limits`` / ``title_too_short`` pass, logged
(:func:`enforced_violations`).

* **Claim words** (:data:`CLAIM_WORDS`) the proposal adds that the current listing does
  not carry are logged and listed on the result.
* **Drift guard (D78.4).** The share of the current title's / description's words the
  proposal keeps is compared with :data:`TITLE_DRIFT_MIN_OVERLAP` /
  :data:`DESCRIPTION_DRIFT_MIN_OVERLAP`. LOG-ONLY on the first tag: a drifted proposal
  is logged (``listing_proposal_drift``) and flagged on :class:`ListingDrift`, never
  refused.
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from juli_backend.services.shop_rules.listing_edits import (
    DESCRIPTION_MAX_CHARS,
    TITLE_MAX_CHARS,
    TITLE_MIN_CHARS,
)
from juli_backend.services.shop_rules.listing_structure import (
    SectionKind,
    parse_description,
    section_text,
)

logger = logging.getLogger(__name__)

#: A proposed title keeps at least this share of the current title's length.
TITLE_MIN_KEEP_RATIO = 0.8
#: TikTok's ``DESC_LESS_THAN_FIVE_HUNDRED_CHARS``: description text, HTML stripped.
DESCRIPTION_MIN_TEXT_CHARS = 500
#: D78.4 drift guard thresholds (share of the current words the proposal keeps).
#: LOG-ONLY: below the threshold is logged and flagged, never refused.
TITLE_DRIFT_MIN_OVERLAP = 0.7
DESCRIPTION_DRIFT_MIN_OVERLAP = 0.6
#: Claim words, folded (no diacritics, lower case): logged when a proposal adds one.
CLAIM_WORDS: tuple[str, ...] = (
    "tot nhat",
    "so 1",
    "so mot",
    "top 1",
    "re nhat",
    "hang dau",
    "chinh hang",
    "cam ket",
    "dam bao",
    "100% tu nhien",
    "dieu tri",
    "chua khoi",
    "best",
)

#: P76-4 kill switch: ``0`` / ``false`` / ``no`` / ``off`` -> every violation except
#: :data:`HARD_VIOLATION_CODES` is logged (``listing_proposal_violation_logged``) and the
#: proposal passes. Read at call time (an env change + worker restart, no deploy).
LISTING_VALIDATOR_ENFORCE_ENV_VAR = "LISTING_VALIDATOR_ENFORCE"
DEFAULT_LISTING_VALIDATOR_ENFORCE = True
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})

Field = Literal["title", "description", "listing"]


class ListingViolationCode(str, Enum):
    LISTING_OVER_LIMITS = "listing_over_limits"
    TITLE_TOO_SHORT = "title_too_short"
    TITLE_TOO_LONG = "title_too_long"
    TITLE_SHRUNK = "title_shrunk"
    TITLE_MISSING_TOKENS = "title_missing_tokens"
    DESCRIPTION_SHORTER_THAN_CURRENT = "description_shorter_than_current"
    DESCRIPTION_TOO_SHORT = "description_too_short"
    DESCRIPTION_NO_LINE_BREAK = "description_no_line_break"
    DESCRIPTION_TOO_LONG = "description_too_long"


#: Refused even with the kill switch off: a listing already over TikTok's limits (D78.3)
#: and a title under TikTok's own 40-character minimum (D78.1).
HARD_VIOLATION_CODES = frozenset(
    {ListingViolationCode.LISTING_OVER_LIMITS, ListingViolationCode.TITLE_TOO_SHORT}
)


def listing_validator_enforced() -> bool:
    """Whether every violation refuses (``LISTING_VALIDATOR_ENFORCE``; unset -> on)."""
    raw = os.environ.get(LISTING_VALIDATOR_ENFORCE_ENV_VAR, "").strip().lower()
    if not raw:
        return DEFAULT_LISTING_VALIDATOR_ENFORCE
    return raw not in _FALSE_VALUES


@dataclass(frozen=True)
class ListingViolation:
    code: ListingViolationCode
    field: Field
    #: English, for the model's retry: what is wrong and what to do.
    message: str
    #: Vietnamese, for the seller.
    message_vi: str


@dataclass(frozen=True)
class ListingDrift:
    """D78.4: how much of the current wording a proposal keeps (``None``: not compared)."""

    title_overlap: float | None = None
    description_overlap: float | None = None
    title_drifted: bool = False
    description_drifted: bool = False
    claim_words_added: tuple[str, ...] = ()


@dataclass(frozen=True)
class ListingValidation:
    violations: tuple[ListingViolation, ...] = ()
    drift: ListingDrift = field(default_factory=ListingDrift)

    @property
    def ok(self) -> bool:
        return not self.violations


# --------------------------------------------------------------------------- folding


def _fold_char(char: str) -> str:
    if char in "đĐ":
        return "d"
    base = unicodedata.normalize("NFD", char)[0]
    lowered = base.lower()
    return lowered if len(lowered) == 1 else base


def fold(text: str) -> str:
    """Lower case, no Vietnamese diacritics, one character per NFC character."""
    return "".join(_fold_char(char) for char in unicodedata.normalize("NFC", text))


_SPACES = re.compile(r"\s+")
_WORD = re.compile(r"\w+")

#: Unit spellings -> the canonical unit a token is compared by.
_UNIT_ALIASES: dict[str, str] = {
    "ml": "ml",
    "l": "l",
    "lit": "l",
    "liter": "l",
    "litre": "l",
    "g": "g",
    "gr": "g",
    "gram": "g",
    "kg": "kg",
    "mg": "mg",
    "mcg": "mcg",
    "cm": "cm",
    "mm": "mm",
    "m": "m",
    "oz": "oz",
    "inch": "inch",
    "w": "w",
    "mah": "mah",
    "v": "v",
    "chai": "chai",
    "lon": "lon",
    "hop": "hop",
    "goi": "goi",
    "vien": "vien",
    "cai": "cai",
    "chiec": "chiec",
    "mieng": "mieng",
    "tui": "tui",
    "cuon": "cuon",
    "doi": "doi",
    "bich": "bich",
    "hu": "hu",
    "tuyp": "tuyp",
    "ong": "ong",
    "thanh": "thanh",
    "qua": "qua",
    "pcs": "pcs",
    "pc": "pcs",
    "sp": "sp",
}
_PACK_WORDS = ("thung", "hop", "loc", "set", "combo", "pack", "bo")
_UNITS_RE = "|".join(sorted(_UNIT_ALIASES, key=len, reverse=True))
_QUANTITY = re.compile(
    r"(?<![\w.,])"
    rf"(?:(?P<pack>{'|'.join(_PACK_WORDS)})\s*)?"
    r"(?P<num>\d+(?:[.,]\d+)?)"
    rf"(?:\s*(?P<unit>%|(?:{_UNITS_RE})(?!\w)))?"
)
_MULTIPLIER = re.compile(r"(?<!\w)x\s?(?P<a>\d+)(?![\w.,])|(?<![\w.,])(?P<b>\d+)\s?x(?!\w)")


@dataclass(frozen=True)
class MustKeepToken:
    #: The token as the current title writes it.
    text: str
    #: The folded comparison key.
    key: str


def _quantity_tokens(text: str) -> list[MustKeepToken]:
    nfc = unicodedata.normalize("NFC", text)
    folded = fold(nfc)
    tokens: list[MustKeepToken] = []
    for match in _QUANTITY.finditer(folded):
        pack, unit = match.group("pack"), match.group("unit")
        if not pack and not unit:
            continue  # a bare number (a model year, a code) is not a quantity
        number = match.group("num").replace(",", ".")
        canonical = "%" if unit == "%" else _UNIT_ALIASES.get(unit or "", "")
        key = f"{pack or ''}{number}{canonical}"
        tokens.append(MustKeepToken(_SPACES.sub(" ", nfc[match.start() : match.end()]), key))
    for match in _MULTIPLIER.finditer(folded):
        count = match.group("a") or match.group("b")
        tokens.append(MustKeepToken(nfc[match.start() : match.end()], f"x{count}"))
    return tokens


def _contains_folded(haystack_folded: str, needle: str) -> bool:
    folded = _SPACES.sub(" ", fold(needle)).strip()
    if not folded:
        return False
    return re.search(rf"(?<!\w){re.escape(folded)}(?!\w)", haystack_folded) is not None


def must_keep_tokens(title: str, brand_terms: Sequence[str] = ()) -> list[MustKeepToken]:
    """The brand terms and quantities ``title`` carries, each once, in title order."""
    folded = _SPACES.sub(" ", fold(title))
    tokens: list[MustKeepToken] = []
    for term in brand_terms:
        if _contains_folded(folded, term):
            tokens.append(MustKeepToken(term.strip(), "brand:" + _SPACES.sub(" ", fold(term))))
    tokens.extend(_quantity_tokens(title))
    unique: dict[str, MustKeepToken] = {}
    for token in tokens:
        unique.setdefault(token.key.strip(), token)
    return list(unique.values())


def missing_tokens(
    current_title: str, proposed_title: str, brand_terms: Sequence[str] = ()
) -> list[MustKeepToken]:
    """The must-keep tokens of ``current_title`` that ``proposed_title`` dropped."""
    proposed_folded = _SPACES.sub(" ", fold(proposed_title))
    proposed_keys = {token.key for token in _quantity_tokens(proposed_title)}
    missing: list[MustKeepToken] = []
    for token in must_keep_tokens(current_title, brand_terms):
        if token.key.startswith("brand:"):
            kept = _contains_folded(proposed_folded, token.text)
        else:
            kept = token.key in proposed_keys
        if not kept:
            missing.append(token)
    return missing


# ----------------------------------------------------------------------- description


def description_text(description_html: str) -> str:
    """The description's text after the P76-3 parse: sections joined by newline."""
    skeleton = parse_description(description_html or "")
    return "\n".join(
        section_text(section) for section in skeleton if section.kind is not SectionKind.RAW
    )


def _has_line_break(description_html: str) -> bool:
    texts = [
        section_text(section)
        for section in parse_description(description_html or "")
        if section.kind is not SectionKind.RAW
    ]
    return len(texts) > 1 or any("\n" in text for text in texts)


# ----------------------------------------------------------------------------- drift


def word_overlap(current: str, proposed: str) -> float | None:
    """Share of ``current``'s distinct words (folded) that ``proposed`` keeps."""
    current_words = set(_WORD.findall(fold(current)))
    if not current_words:
        return None
    kept = current_words & set(_WORD.findall(fold(proposed)))
    return len(kept) / len(current_words)


def _claims_added(current: str, proposed: str) -> list[str]:
    current_folded = _SPACES.sub(" ", fold(current))
    proposed_folded = _SPACES.sub(" ", fold(proposed))
    return [
        claim
        for claim in CLAIM_WORDS
        if _contains_folded(proposed_folded, claim) and not _contains_folded(current_folded, claim)
    ]


def _drift(
    current_title: str | None,
    current_description_html: str | None,
    proposed_title: str | None,
    proposed_description_html: str | None,
) -> ListingDrift:
    title_overlap = (
        word_overlap(current_title, proposed_title)
        if current_title and proposed_title is not None
        else None
    )
    description_overlap = (
        word_overlap(
            description_text(current_description_html),
            description_text(proposed_description_html),
        )
        if current_description_html and proposed_description_html is not None
        else None
    )
    current_all = " ".join(
        part
        for part in (current_title or "", description_text(current_description_html or ""))
        if part
    )
    proposed_all = " ".join(
        part
        for part in (proposed_title or "", description_text(proposed_description_html or ""))
        if part
    )
    return ListingDrift(
        title_overlap=title_overlap,
        description_overlap=description_overlap,
        title_drifted=title_overlap is not None and title_overlap < TITLE_DRIFT_MIN_OVERLAP,
        description_drifted=(
            description_overlap is not None and description_overlap < DESCRIPTION_DRIFT_MIN_OVERLAP
        ),
        claim_words_added=tuple(_claims_added(current_all, proposed_all)),
    )


# ------------------------------------------------------------------------- the rules


def _vi_count(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _over_limits(
    current_title: str | None, current_description_html: str | None
) -> ListingViolation | None:
    title_len = len(current_title or "")
    description_len = len(current_description_html or "")
    if title_len <= TITLE_MAX_CHARS and description_len <= DESCRIPTION_MAX_CHARS:
        return None
    return ListingViolation(
        ListingViolationCode.LISTING_OVER_LIMITS,
        "listing",
        "The current listing already exceeds TikTok's length limits (title "
        f"{title_len}/{TITLE_MAX_CHARS} characters, description "
        f"{description_len}/{DESCRIPTION_MAX_CHARS}); Juli does not edit it. Do not call "
        "update_product_listing again; conclude without changes.",
        "Sản phẩm này đang vượt giới hạn độ dài của TikTok (tiêu đề tối đa "
        f"{TITLE_MAX_CHARS} ký tự, mô tả tối đa {_vi_count(DESCRIPTION_MAX_CHARS)} ký tự), "
        "nên Juli không sửa.",
    )


def _title_violations(
    current_title: str | None, proposed_title: str, brand_terms: Sequence[str]
) -> list[ListingViolation]:
    out: list[ListingViolation] = []
    length = len(proposed_title)
    if length < TITLE_MIN_CHARS:
        out.append(
            ListingViolation(
                ListingViolationCode.TITLE_TOO_SHORT,
                "title",
                f"The title has {length} characters; it needs at least {TITLE_MIN_CHARS} "
                "(TikTok TITLE_LESS_THAN_40_CHARACTERS). Keep the current title's words and "
                "add specifics (material, size, use).",
                f"Tiêu đề cần ít nhất {TITLE_MIN_CHARS} ký tự (bản đề xuất có {length} ký tự).",
            )
        )
    if length > TITLE_MAX_CHARS:
        out.append(
            ListingViolation(
                ListingViolationCode.TITLE_TOO_LONG,
                "title",
                f"The title has {length} characters; the limit is {TITLE_MAX_CHARS}.",
                f"Tiêu đề tối đa {TITLE_MAX_CHARS} ký tự (bản đề xuất có {length} ký tự).",
            )
        )
    if current_title:
        floor = TITLE_MIN_KEEP_RATIO * len(current_title)
        if length < floor:
            out.append(
                ListingViolation(
                    ListingViolationCode.TITLE_SHRUNK,
                    "title",
                    f"The title has {length} characters, under "
                    f"{round(TITLE_MIN_KEEP_RATIO * 100)}% of the current title's "
                    f"{len(current_title)}. Keep the current title's words; only add or "
                    "reorder.",
                    f"Tiêu đề đề xuất ngắn hơn nhiều so với tiêu đề hiện tại ({length} so với "
                    f"{len(current_title)} ký tự).",
                )
            )
        missing = missing_tokens(current_title, proposed_title, brand_terms)
        if missing:
            quoted = ", ".join(f'"{token.text}"' for token in missing)
            out.append(
                ListingViolation(
                    ListingViolationCode.TITLE_MISSING_TOKENS,
                    "title",
                    f"The title drops {quoted} from the current title (brand, size, "
                    "quantity or pack). Keep every one of them exactly as written.",
                    f"Tiêu đề đề xuất bỏ mất {quoted} của tiêu đề hiện tại. "
                    "Cần giữ nguyên các thông tin này.",
                )
            )
    return out


def _description_violations(
    current_description_html: str | None, proposed_html: str
) -> list[ListingViolation]:
    out: list[ListingViolation] = []
    text_len = len(description_text(proposed_html))
    current_len = len(description_text(current_description_html or ""))
    if current_len and text_len < current_len:
        out.append(
            ListingViolation(
                ListingViolationCode.DESCRIPTION_SHORTER_THAN_CURRENT,
                "description",
                f"The description text has {text_len} characters, fewer than the current "
                f"description's {current_len}. Keep every section of the current description "
                "and only add to it.",
                f"Mô tả đề xuất ngắn hơn mô tả hiện tại ({_vi_count(text_len)} so với "
                f"{_vi_count(current_len)} ký tự).",
            )
        )
    if text_len < DESCRIPTION_MIN_TEXT_CHARS:
        out.append(
            ListingViolation(
                ListingViolationCode.DESCRIPTION_TOO_SHORT,
                "description",
                f"The description text has {text_len} characters (HTML not counted); it "
                f"needs at least {DESCRIPTION_MIN_TEXT_CHARS} (TikTok "
                "DESC_LESS_THAN_FIVE_HUNDRED_CHARS).",
                f"Mô tả cần ít nhất {DESCRIPTION_MIN_TEXT_CHARS} ký tự chữ "
                f"(bản đề xuất có {_vi_count(text_len)} ký tự).",
            )
        )
    if not _has_line_break(proposed_html):
        out.append(
            ListingViolation(
                ListingViolationCode.DESCRIPTION_NO_LINE_BREAK,
                "description",
                "The description is a single block with no line break (TikTok "
                "DESC_NO_NEW_LINE). Keep it in separate sections or lines.",
                "Mô tả cần chia thành nhiều đoạn hoặc nhiều dòng.",
            )
        )
    if len(proposed_html) > DESCRIPTION_MAX_CHARS:
        out.append(
            ListingViolation(
                ListingViolationCode.DESCRIPTION_TOO_LONG,
                "description",
                f"The description has {len(proposed_html)} characters (HTML included); the "
                f"limit is {DESCRIPTION_MAX_CHARS}.",
                f"Mô tả tối đa {_vi_count(DESCRIPTION_MAX_CHARS)} ký tự "
                f"(bản đề xuất có {_vi_count(len(proposed_html))} ký tự).",
            )
        )
    return out


def validate_listing_proposal(
    current_title: str | None,
    current_description_html: str | None,
    proposed_title: str | None,
    proposed_description_html: str | None,
    flagged_codes: Collection[str] = (),
    brand_terms: Sequence[str] = (),
) -> ListingValidation:
    """Every rule the proposal breaks, plus the (log-only) drift reading.

    ``current_*`` is the listing as the run read it (``None`` when unknown: the rules
    that compare with it are skipped); ``proposed_*`` is ``None`` for a field the
    proposal leaves alone. ``flagged_codes`` (TikTok's diagnosis codes on the product)
    only travel to the drift log line.
    """
    over = _over_limits(current_title, current_description_html)
    if over is not None:
        return ListingValidation(violations=(over,))
    violations: list[ListingViolation] = []
    if proposed_title is not None:
        violations.extend(_title_violations(current_title, proposed_title, brand_terms))
    if proposed_description_html is not None:
        violations.extend(
            _description_violations(current_description_html, proposed_description_html)
        )
    drift = _drift(
        current_title, current_description_html, proposed_title, proposed_description_html
    )
    if drift.title_drifted or drift.description_drifted or drift.claim_words_added:
        logger.warning(
            "listing_proposal_drift",
            extra={
                "title_overlap": drift.title_overlap,
                "description_overlap": drift.description_overlap,
                "title_drifted": drift.title_drifted,
                "description_drifted": drift.description_drifted,
                "claim_words_added": list(drift.claim_words_added),
                "flagged_codes": sorted(flagged_codes),
                "violation_codes": [violation.code.value for violation in violations],
                "blocking": False,
            },
        )
    return ListingValidation(violations=tuple(violations), drift=drift)


def enforced_violations(validation: ListingValidation) -> tuple[ListingViolation, ...]:
    """The violations that refuse the proposal under ``LISTING_VALIDATOR_ENFORCE``.

    Enforced (the default): all of them. Off: only :data:`HARD_VIOLATION_CODES`; each
    other one is logged (``listing_proposal_violation_logged``) and lets the proposal pass.
    """
    if listing_validator_enforced():
        return validation.violations
    for violation in validation.violations:
        if violation.code not in HARD_VIOLATION_CODES:
            logger.warning(
                "listing_proposal_violation_logged",
                extra={"code": violation.code.value, "field": violation.field, "blocking": False},
            )
    return tuple(v for v in validation.violations if v.code in HARD_VIOLATION_CODES)


__all__ = [
    "CLAIM_WORDS",
    "HARD_VIOLATION_CODES",
    "LISTING_VALIDATOR_ENFORCE_ENV_VAR",
    "DESCRIPTION_DRIFT_MIN_OVERLAP",
    "DESCRIPTION_MIN_TEXT_CHARS",
    "TITLE_DRIFT_MIN_OVERLAP",
    "TITLE_MIN_KEEP_RATIO",
    "ListingDrift",
    "ListingValidation",
    "ListingViolation",
    "ListingViolationCode",
    "MustKeepToken",
    "description_text",
    "enforced_violations",
    "fold",
    "listing_validator_enforced",
    "missing_tokens",
    "must_keep_tokens",
    "validate_listing_proposal",
    "word_overlap",
]
