"""The diagnosis codes a listing edit may cite, per field (fast track P79, edge case D33).

Live sandbox run dbd17987 (30/10): an Optimize Product card was raised by Juli's own
listing evidence (title 31 characters, an 80-character one-line description), but
TikTok's ``get_product_diagnoses`` lagged the listing and returned only
``MAIN_IMG_NUMBER_LESS_THAN_FIVE``. Forced to cite a TikTok code, the model put that
image code on a title op, was refused twice (``reason_code_wrong_field``) and the run
wrote nothing.

The codes an edit may cite are therefore the union of:

* ``tiktok``     -- what this run's ``get_product_diagnoses`` read;
* ``juli_check`` -- what Juli's own listing evidence finds on the CURRENT listing
  (``optimize_product.listing_signals.derive_local_evidence``: the same thresholds the
  scan uses, never re-implemented here), computed from the product detail the run
  already read -- no extra TikTok call;
* the action card's own evidence codes (``diagnosis.lever.evidence`` of its payload),
  tagged by the source the card recorded (``tiktok`` / ``local`` -> ``juli_check``).

:class:`EditCodes` splits them per field for the model (``for_model``) and gives
``apply_ops`` / the post-validator the flat set (``flagged``). Pure: no I/O.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.listing_signals import (
    EvidenceSource,
    derive_local_evidence,
    is_description_code,
    is_title_code,
    listing_signals_from_product,
)

SOURCE_TIKTOK = "tiktok"
SOURCE_JULI_CHECK = "juli_check"

#: Card evidence ``source`` values -> the tag the model reads.
_CARD_SOURCE_TAGS = {
    EvidenceSource.TIKTOK.value: SOURCE_TIKTOK,
    EvidenceSource.LOCAL.value: SOURCE_JULI_CHECK,
}


def local_text_codes(detail: Mapping[str, Any] | None) -> tuple[str, ...]:
    """The title / description codes Juli's own listing evidence finds on ``detail``."""
    if not isinstance(detail, Mapping):
        return ()
    config = StageDiagnosisConfig()
    signals = listing_signals_from_product(dict(detail), config)
    return tuple(
        evidence.code
        for evidence in derive_local_evidence(signals, config)
        if evidence.field_name in ("title", "description")
    )


def card_evidence_from_payload(payload: Any) -> tuple[tuple[str, str], ...]:
    """``(code, source tag)`` of an Optimize Product card's ``diagnosis.lever.evidence``.

    ``payload`` is the card's ``recommendation_payload`` (JSON text or a dict); anything
    unreadable is no evidence, never an error.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload or "{}")
        except ValueError:
            return ()
    if not isinstance(payload, Mapping):
        return ()
    diagnosis = payload.get("diagnosis")
    lever = diagnosis.get("lever") if isinstance(diagnosis, Mapping) else None
    entries = lever.get("evidence") if isinstance(lever, Mapping) else None
    out: list[tuple[str, str]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("code"), str):
            continue
        tag = _CARD_SOURCE_TAGS.get(str(entry.get("source") or ""))
        if tag is not None and entry["code"]:
            out.append((entry["code"], tag))
    return tuple(out)


@dataclass(frozen=True)
class EditCodes:
    """The codes this product's edits may cite, each with where it came from.

    ``codes`` keeps first-seen order (TikTok, then Juli's check, then the card), one
    entry per code; ``tiktok_read`` is whether TikTok's diagnoses were read this leg
    (``False``: not called, or unavailable -- so "no text code" is not a fact).
    """

    codes: tuple[tuple[str, str], ...]
    tiktok_read: bool

    @property
    def flagged(self) -> tuple[str, ...]:
        return tuple(code for code, _ in self.codes)

    def for_field(self, field: str) -> tuple[tuple[str, str], ...]:
        check = is_title_code if field == "title" else is_description_code
        return tuple(entry for entry in self.codes if check(entry[0]))

    @property
    def has_text_code(self) -> bool:
        return bool(self.for_field("title") or self.for_field("description"))

    def allowed_line(self, field: str) -> str:
        """One English sentence naming the codes a ``field`` op may cite."""
        entries = self.for_field(field)
        if not entries:
            return f"No {field} code is flagged on this product: leave the {field} unchanged."
        listed = ", ".join(f"{code} ({source})" for code, source in entries)
        return f"Allowed {field} reason codes: {listed}."

    def for_model(self) -> dict[str, Any]:
        """The ``edit_codes`` block of the product read: short, per field."""

        def rows(field: str) -> list[dict[str, str]]:
            return [{"code": code, "source": source} for code, source in self.for_field(field)]

        text = {code for code, _ in self.for_field("title") + self.for_field("description")}
        return {
            "title_codes": rows("title"),
            "description_codes": rows("description"),
            "not_for_text": [code for code, _ in self.codes if code not in text],
            "tiktok_read": self.tiktok_read,
        }


def edit_codes(
    *,
    tiktok_codes: Sequence[str] | None,
    detail: Mapping[str, Any] | None,
    card_evidence: Iterable[tuple[str, str]] = (),
) -> EditCodes:
    """TikTok's codes ∪ Juli's check of ``detail`` ∪ the card's evidence (P79).

    ``tiktok_codes`` ``None``: TikTok was not read (or could not be) this leg.
    """
    seen: dict[str, str] = {}
    sources: list[Iterable[tuple[str, str]]] = [
        ((code, SOURCE_TIKTOK) for code in tiktok_codes or ()),
        ((code, SOURCE_JULI_CHECK) for code in local_text_codes(detail)),
        card_evidence,
    ]
    for source in sources:
        for code, tag in source:
            if code and code not in seen:
                seen[code] = tag
    return EditCodes(codes=tuple(seen.items()), tiktok_read=tiktok_codes is not None)


__all__ = [
    "SOURCE_JULI_CHECK",
    "SOURCE_TIKTOK",
    "EditCodes",
    "card_evidence_from_payload",
    "edit_codes",
    "local_text_codes",
]
