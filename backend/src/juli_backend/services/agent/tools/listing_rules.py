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
from juli_backend.services.shop_rules.listing_validator import (
    ListingViolation,
    ListingViolationCode,
)

ERROR_RULE_VIOLATION = "listing_rule_violation"
ERROR_SOURCE_NAME_NOT_IN_TITLE = "brand_not_in_source"

RULE_REFUSAL_SUMMARY_VI = "Nội dung Juli soạn chưa đúng quy tắc của shop, Juli soạn lại"
#: P76-4: the seller's line when a second refused draft ends the run (no redraft follows).
RULE_REFUSAL_FINAL_VI = (
    "Nội dung Juli soạn vẫn chưa đúng quy tắc của shop, Juli dừng và không sửa sản phẩm"
)


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
    #: P76-4: shown instead of ``summary_vi`` when this refusal ends the run (the
    #: second one for the same tool); ``None``: ``summary_vi`` again.
    final_summary_vi: str | None = None
    #: P79: the refusal ends the run cleanly (``concluded_without_changes``, not a
    #: failure) instead of inviting a redraft: there is nothing a text edit may fix.
    concludes_run: bool = False


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


#: P76-4: prompt v3 does not state the description rules; the first refusal says them.
DESCRIPTION_RETRY_HINT = (
    "The description must keep all of the existing text and only add or replace specific "
    "parts, and must be at least as long as the current one."
)


def validation_refusal(violations: Sequence[ListingViolation]) -> ProposalRefusal | None:
    """P76-4: the post-validator's violations as one refusal, every message for the model."""
    if not violations:
        return None
    points = "; ".join(f"[{violation.code.value}] {violation.message}" for violation in violations)
    over_limits = any(v.code is ListingViolationCode.LISTING_OVER_LIMITS for v in violations)
    retry = "" if over_limits else f" {DESCRIPTION_RETRY_HINT}"
    return ProposalRefusal(
        error_code=ERROR_RULE_VIOLATION,
        summary_vi=RULE_REFUSAL_SUMMARY_VI,
        model_hint=(
            f"error_code={ERROR_RULE_VIOLATION}: {points}{retry} Fix every point and call "
            "the tool again (once); a second refusal ends the run."
        ),
        final_summary_vi=f"{RULE_REFUSAL_FINAL_VI}: {violations[0].message_vi}",
    )


#: P76-6: the machine code a refused set of edit operations carries.
ERROR_LISTING_EDIT_REJECTED = "listing_edit_rejected"


def edit_refusal(code: str, message: str, *, retry: bool = True) -> ProposalRefusal:
    """P76-6: edit operations Juli could not apply, as one refusal (D78).

    ``code`` is the machine reason (an ``listing_structure.RejectionCode`` value, or
    ``edits_with_text`` / ``edits_change_nothing`` / ``listing_unavailable``) and
    ``message`` the English fix for the model's one redraft. The seller reads the same
    lines a rule refusal shows -- never the vendor text or the operations.
    """
    next_step = (
        "Fix it and call the tool again (once) with edits; a second refusal ends the run."
        if retry
        else "Do not call the tool again; end the run and say the listing cannot be edited."
    )
    return ProposalRefusal(
        error_code=ERROR_LISTING_EDIT_REJECTED,
        summary_vi=RULE_REFUSAL_SUMMARY_VI,
        model_hint=f"error_code={ERROR_LISTING_EDIT_REJECTED}: [{code}] {message} {next_step}",
        final_summary_vi=RULE_REFUSAL_FINAL_VI,
    )


#: P79: the machine code of a listing edit refused because no title / description code
#: is flagged (TikTok flags only images and Juli's own check finds nothing).
ERROR_LISTING_NEEDS_PHOTOS = "listing_needs_photos"
#: P79: the seller's line for that ending -- the text already meets TikTok's rules; the
#: card needs new photos, which Juli cannot upload.
LISTING_NEEDS_PHOTOS_VI = (
    "Tiêu đề và mô tả của sản phẩm đã đạt quy định của TikTok. Thẻ này cần thêm ảnh "
    "mới cho sản phẩm, việc Juli chưa thể tải ảnh lên thay bạn; sản phẩm giữ nguyên."
)


def needs_photos_refusal(not_for_text: Sequence[str]) -> ProposalRefusal:
    """P79: no code a text edit may cite -- end the run without a change (not a failure)."""
    codes = ", ".join(not_for_text) or "none"
    return ProposalRefusal(
        error_code=ERROR_LISTING_NEEDS_PHOTOS,
        summary_vi=LISTING_NEEDS_PHOTOS_VI,
        model_hint=(
            f"error_code={ERROR_LISTING_NEEDS_PHOTOS}: no title or description reason code is "
            f"flagged on this product (flagged: {codes}; image codes cannot be fixed by a "
            "text edit). The run ends without a listing change."
        ),
        final_summary_vi=LISTING_NEEDS_PHOTOS_VI,
        concludes_run=True,
    )


__all__ = [
    "ERROR_LISTING_NEEDS_PHOTOS",
    "LISTING_NEEDS_PHOTOS_VI",
    "DESCRIPTION_RETRY_HINT",
    "ERROR_LISTING_EDIT_REJECTED",
    "ERROR_RULE_VIOLATION",
    "ERROR_SOURCE_NAME_NOT_IN_TITLE",
    "RULE_REFUSAL_FINAL_VI",
    "RULE_REFUSAL_SUMMARY_VI",
    "ProposalRefusal",
    "check_proposal",
    "edit_refusal",
    "needs_photos_refusal",
    "redact_terms",
    "source_terms_not_in",
    "validation_refusal",
]
