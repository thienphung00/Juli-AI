"""Validate a seller's edit of Juli's proposed title / description (fast track P10-A).

ADR-109 amendment 1 decision 4, contract ``fasttrack/contracts/p10-quyet-dinh.md``
§3: at the consent step the seller may edit the proposed title and description;
Juli checks the edit against the shop's rules and then writes exactly it.

Rules checked, in this order, per field:

1. the field is one Juli proposed to change in this run (the seller edits the
   proposal; widening it to another field would be a change nobody reviewed);
2. TikTok's length limits for the listing -- title 25 to 255 characters (VN is
   one of the "other regions" of ``POST /product/202309/products/{id}``:
   ``[25, 255]``), description non-empty and at most 10,000 characters (the same
   endpoint's documented maximum, HTML included);
3. the shop's protected terms (``shop_rules`` ``protected_terms``, ADR-109 d.12
   "Từ / thông tin không được sửa"): every term the current listing field
   contains -- or, when the current value is unknown, Juli's proposal contains
   -- must still be in the edit (case-insensitive);
4. the shop's banned terms (``shop_rules`` ``banned_terms``, D24.21 (5) "Từ
   không được dùng"): the edit must not contain any of them (whole word,
   case-insensitive). :func:`check_banned_terms` applies the same check to
   whatever title / description is about to be written -- Juli's own proposal
   included (``agent_runs.confirmations`` at approve).

The first failure raises :class:`ListingEditViolation` with the field and a
Vietnamese message for the seller. Pure.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

TITLE_MIN_CHARS = 25
TITLE_MAX_CHARS = 255
DESCRIPTION_MAX_CHARS = 10_000

EDITABLE_FIELDS: tuple[str, ...] = ("title", "description")
FIELD_LABELS_VI: Mapping[str, str] = {"title": "Tiêu đề", "description": "Mô tả"}


class ListingEditViolation(ValueError):
    """The edit breaks one of the shop's rules; ``message_vi`` says which, for the seller."""

    def __init__(self, field: str, message_vi: str) -> None:
        super().__init__(f"{field}: {message_vi}")
        self.field = field
        self.message_vi = message_vi


def _vnd_count(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _check_length(field: str, value: str) -> None:
    length = len(value)
    if field == "title" and not TITLE_MIN_CHARS <= length <= TITLE_MAX_CHARS:
        raise ListingEditViolation(
            field,
            f"Tiêu đề cần từ {TITLE_MIN_CHARS} đến {TITLE_MAX_CHARS} ký tự "
            f"(bản sửa có {length} ký tự).",
        )
    if field == "description":
        if not value.strip():
            raise ListingEditViolation(field, "Mô tả không được để trống.")
        if length > DESCRIPTION_MAX_CHARS:
            raise ListingEditViolation(
                field,
                f"Mô tả tối đa {_vnd_count(DESCRIPTION_MAX_CHARS)} ký tự "
                f"(bản sửa có {_vnd_count(length)} ký tự).",
            )


def _check_protected_terms(
    field: str, value: str, reference: str | None, protected_terms: Sequence[str]
) -> None:
    if not reference:
        return
    reference_folded = reference.casefold()
    edited_folded = value.casefold()
    for term in protected_terms:
        folded = term.strip().casefold()
        if folded and folded in reference_folded and folded not in edited_folded:
            label = FIELD_LABELS_VI[field]
            raise ListingEditViolation(
                field,
                f'{label} đã bỏ mất "{term.strip()}" — từ bạn đặt là không được sửa. '
                "Hãy giữ nguyên từ này.",
            )


def _contains_term(text: str, term: str) -> bool:
    needle = term.strip().casefold()
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", text.casefold()) is not None


def check_banned_terms(values: Mapping[str, Any], banned_terms: Sequence[str]) -> None:
    """Raise :class:`ListingEditViolation` if a title / description uses a banned term."""
    for field in EDITABLE_FIELDS:
        value = values.get(field)
        if not isinstance(value, str):
            continue
        for term in banned_terms:
            if _contains_term(value, term):
                label = FIELD_LABELS_VI[field]
                raise ListingEditViolation(
                    field,
                    f'{label} có "{term.strip()}" — từ bạn đặt là không được dùng. '
                    "Hãy bỏ hoặc thay từ này.",
                )


def validate_listing_edits(
    edited: Mapping[str, str],
    *,
    proposed: Mapping[str, Any],
    current: Mapping[str, Any] | None,
    protected_terms: Sequence[str],
    banned_terms: Sequence[str] = (),
) -> dict[str, str]:
    """Return the edits that differ from Juli's proposal, or raise :class:`ListingEditViolation`.

    ``proposed`` is the paused tool call's arguments; ``current`` the listing as
    the run read it (``title`` / ``description``), ``None`` when unknown.
    """
    changed: dict[str, str] = {}
    for field, value in edited.items():
        if field not in EDITABLE_FIELDS:
            raise ListingEditViolation(field, "Chỉ sửa được tiêu đề và mô tả.")
        if proposed.get(field) is None:
            raise ListingEditViolation(
                field,
                f"Lượt này Juli không đề xuất sửa {FIELD_LABELS_VI[field].lower()}, "
                "nên không áp dụng được bản sửa cho phần này.",
            )
        if not isinstance(value, str):
            raise ListingEditViolation(field, f"{FIELD_LABELS_VI[field]} phải là văn bản.")
        _check_length(field, value)
        reference = (current or {}).get(field) if current else None
        if not isinstance(reference, str) or not reference:
            proposal = proposed.get(field)
            reference = proposal if isinstance(proposal, str) else None
        _check_protected_terms(field, value, reference, protected_terms)
        check_banned_terms({field: value}, banned_terms)
        if value != proposed.get(field):
            changed[field] = value
    return changed
