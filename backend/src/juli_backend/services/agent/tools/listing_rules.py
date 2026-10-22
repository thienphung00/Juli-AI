"""The shop's listing rules as a gate on the model's title / description (P64, D73.5).

Rules are data: the shop's "Từ không được dùng" (``shop_rules`` ``banned_terms``) and
the built-in default rule :data:`shop_rules.SOURCE_NAMES_RULE_VI` -- "no brand,
manufacturer or shop name the source title does not carry". The default rule's terms
are derived from the source listing itself: every free-text value (one TikTok did not
pick from its own option list, so it carries no option ``id``) of the source's
attributes and its ``brand`` name that the reference text does not contain. No brand
list, no pattern: the source title is the data the values are compared against.

The gate runs before the seller is asked (``ToolDomain.prechecks``: the model drafts
once more, then the run ends), at the consent step on the seller's edit
(``agent_runs.confirmations``) and once more at execution (the create handler).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from juli_backend.services.shop_rules.listing_edits import contains_term, find_term

ERROR_RULE_VIOLATION = "listing_rule_violation"
ERROR_SOURCE_NAME_NOT_IN_TITLE = "brand_not_in_source"

RULE_REFUSAL_SUMMARY_VI = "Nội dung Juli soạn chưa đúng quy tắc của shop, Juli soạn lại"


def source_terms_not_in(detail: Mapping[str, Any] | None, reference: str) -> list[str]:
    """Free-text attribute values and the brand name of ``detail`` that ``reference`` lacks."""
    if not isinstance(detail, Mapping):
        return []
    values: list[str] = []
    brand = detail.get("brand")
    if isinstance(brand, Mapping) and str(brand.get("name") or "").strip():
        values.append(str(brand["name"]).strip())
    for attribute in detail.get("product_attributes") or []:
        if not isinstance(attribute, Mapping):
            continue
        for value in attribute.get("values") or []:
            if isinstance(value, Mapping) and not value.get("id"):
                text = str(value.get("name") or "").strip()
                if text:
                    values.append(text)
    terms: list[str] = []
    for value in values:
        if not contains_term(reference, value) and value not in terms:
            terms.append(value)
    return terms


def redact_terms(text: str, terms: Sequence[str]) -> str:
    """``text`` without any of ``terms`` (whole word, case-insensitive)."""
    text = unicodedata.normalize("NFC", text)
    for term in sorted(terms, key=len, reverse=True):
        needle = unicodedata.normalize("NFC", term.strip())
        if needle:
            text = re.sub(rf"(?<!\w){re.escape(needle)}(?!\w)", "", text, flags=re.IGNORECASE)
    return re.sub(r"[ \t]{2,}", " ", text)


class ProposalRefusal(BaseModel):
    """A CONFIRM proposal refused before the pause (the model may draft again, once)."""

    error_code: str
    #: Shown to the seller: never repeats vendor text.
    summary_vi: str
    #: Read by the model only: what to change.
    model_hint: str


def check_proposal(
    values: Mapping[str, Any],
    *,
    banned_terms: Sequence[str],
    source_terms: Sequence[str],
) -> ProposalRefusal | None:
    """The first rule the drafted ``title`` / ``description`` breaks, or ``None``."""
    hit = find_term(values, banned_terms)
    if hit is not None:
        field, term = hit
        return ProposalRefusal(
            error_code=ERROR_RULE_VIOLATION,
            summary_vi=RULE_REFUSAL_SUMMARY_VI,
            model_hint=(
                f"error_code={ERROR_RULE_VIOLATION}: the {field} uses {term!r}, one of the "
                "shop's banned terms (shop_rules.banned_terms). Draft it again without it."
            ),
        )
    hit = find_term(values, source_terms)
    if hit is not None:
        field, term = hit
        return ProposalRefusal(
            error_code=ERROR_SOURCE_NAME_NOT_IN_TITLE,
            summary_vi=RULE_REFUSAL_SUMMARY_VI,
            model_hint=(
                f"error_code={ERROR_SOURCE_NAME_NOT_IN_TITLE}: the {field} uses {term!r}, a "
                "value the source title does not carry (shop_rules.rules: no brand, "
                "manufacturer or shop name that is not in the source title). Draft the "
                "title and description again without it, then call the tool again (once)."
            ),
        )
    return None


__all__ = [
    "ERROR_RULE_VIOLATION",
    "ERROR_SOURCE_NAME_NOT_IN_TITLE",
    "ProposalRefusal",
    "check_proposal",
    "redact_terms",
    "source_terms_not_in",
]
