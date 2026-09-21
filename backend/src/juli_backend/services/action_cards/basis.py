"""The **basis** a card was emitted on, and what counts as a change to it.

ADR-087 decision 6: *"A revision is legitimate when the subject's basis has
changed since the last executed revision's snapshot; otherwise the card is
suppressed with a named reason... What counts as material change is defined
per workflow key in the catalog, not globally -- a 2% price move and a stock
level crossing zero are not the same event."*

This module is that catalog. It answers exactly one question -- *has anything
material moved since the last card we emitted for this subject?* -- and it
answers it with a per-field SHA-256 fingerprint, the same idiom ADR-073
decision 4 already uses for the runner's write guard
(``services/agent/runner/concurrency.py::capture_basis_snapshot``): one hash
per field, namespaced by field name, over canonical JSON, so two reads of an
unchanged value always hash identically and a changed field is identifiable
rather than merely detectable.

**Materiality is expressed by the extractor, not by a threshold.** A hash can
only say "same" or "different", so a rule like "a 2% price move is not
material" cannot live in a comparison -- it has to live in what gets hashed.
Each field therefore carries its own projection:

* ``optimize_product_2``'s ``price`` is hashed **raw**, because changing the
  price is one of the things this workflow itself writes: any move is news
  to a listing-optimization card.
* ``optimize_product_2``'s stock is hashed as the **boolean**
  ``in_stock`` -- ADR-087's "crossing zero", not the level. Selling three
  units is not a reason to re-offer a listing rewrite; running out is.
* KPI signals are hashed by **severity bucket**, never by the raw metric.
  This is the general form of the "2% move" rule: a number that drifts
  without changing what Juli would say about it has not changed the basis.

What is deliberately **not** in the basis: ``computed_at``, priority, and the
generated copy. Those move on every scoring run by construction, and folding
any of them in would make ``basis_unchanged`` unreachable -- the suppression
would exist in the vocabulary and never fire, which is the shape of defect
this wave exists to prevent.

The fingerprint is stored in ``ActionCard.metadata_json`` under ``"basis"``.
No column and no migration: #1701 added every column this design needs, and
067-070 are reserved by other slices.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard, Product
from juli_backend.services.action_cards.subjects import (
    SUBJECT_TYPE_PRODUCT,
    CardSubject,
)
from juli_backend.services.scoring.types import DailyScoringResult, KpiId

#: Key under ``ActionCard.metadata_json`` holding the emitted card's basis
#: fingerprint. A card written before #1703 has no such key, which reads as
#: "no comparable basis" and therefore never suppresses a successor.
BASIS_METADATA_KEY = "basis"


@dataclass(frozen=True, slots=True)
class BasisField:
    """One material field of a subject: its name and how it is projected.

    The projection *is* the materiality rule (see the module docstring), so
    it lives next to the field name rather than in a comparison elsewhere.
    """

    name: str
    project: Callable[[Any], Any]


def _in_stock(product: Product) -> bool:
    """ADR-087 decision 6's "stock level crossing zero", as a boolean."""
    return (product.inventory or 0) > 0


#: Per-workflow-key material subject fields. A key absent from this table has
#: no subject fields in its basis -- its basis is its KPI severities alone,
#: which is the correct and only available answer for a card whose subject
#: this producer could not resolve (``services/action_cards/subjects.py``).
_SUBJECT_BASIS_FIELDS: dict[str, tuple[BasisField, ...]] = {
    "optimize_product_2": (
        BasisField("title", lambda product: product.title),
        BasisField("price", lambda product: product.price),
        BasisField("listing_status", lambda product: product.status),
        BasisField("in_stock", _in_stock),
    ),
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _hash_field(field_name: str, value: Any) -> str:
    """SHA-256 of one field's canonical JSON, namespaced by the field name so
    two different fields holding the same value never collide. Identical in
    construction to ``runner/concurrency.py::_hash_field`` (ADR-073 d.4)."""
    return hashlib.sha256(_canonical_json({field_name: value}).encode("utf-8")).hexdigest()


def _signal_severities(
    result: DailyScoringResult, source_kpi_ids: tuple[str, ...]
) -> dict[str, str]:
    """The severity bucket of each KPI this recommendation was derived from.

    A KPI the run could not compute is recorded as ``"unavailable"`` rather
    than omitted, so "the signal went dark" is itself a basis change and not
    silently identical to "the signal is healthy".
    """
    severities: dict[str, str] = {}
    for kpi_id in sorted(source_kpi_ids):
        signal = result.signals.kpis.get(cast(KpiId, kpi_id))
        severities[kpi_id] = signal.severity if signal is not None else "unavailable"
    return severities


async def compute_card_basis(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    workflow_key: str,
    subject: CardSubject,
    source_kpi_ids: tuple[str, ...],
    result: DailyScoringResult,
) -> dict[str, str]:
    """The basis fingerprint for a card about to be emitted.

    One entry per material field: the KPI severities behind the
    recommendation, plus this workflow key's material subject fields when the
    subject resolved to a real row. Field-wise rather than one blob hash so a
    future reader (or an on-call engineer staring at ``metadata_json``) can
    see *which* field moved, exactly as ADR-073 d.4's snapshot does.
    """
    basis = {"signals": _hash_field("signals", _signal_severities(result, source_kpi_ids))}

    fields = _SUBJECT_BASIS_FIELDS.get(workflow_key, ())
    if not fields or subject.subject_type != SUBJECT_TYPE_PRODUCT:
        return basis

    product = await session.get(Product, uuid.UUID(subject.subject_id))
    if product is None or product.shop_id != shop_id:
        # The subject vanished (or is not this shop's) between resolution and
        # here. Record nothing rather than hashing a stand-in: an absent
        # field is not equal to any prior value, so the next emission is
        # never suppressed on a basis we could not actually read.
        return basis

    for field in fields:
        basis[field.name] = _hash_field(field.name, field.project(product))
    return basis


def stored_basis(card: ActionCard) -> dict[str, str] | None:
    """The basis fingerprint recorded on *card*, or ``None`` if it has none.

    ``None`` -- a row emitted before #1703, or one whose metadata is
    unparseable -- means "no comparable basis". Callers must treat that as
    *changed*, never as unchanged: suppressing a successor on a basis we
    never recorded would freeze a subject forever.
    """
    if not card.metadata_json:
        return None
    try:
        metadata = json.loads(card.metadata_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(metadata, dict):
        return None
    basis = metadata.get(BASIS_METADATA_KEY)
    if not isinstance(basis, dict) or not basis:
        return None
    return {str(key): str(value) for key, value in basis.items()}


def basis_unchanged(previous: Mapping[str, str] | None, current: Mapping[str, str]) -> bool:
    """Whether *current* is materially identical to *previous*.

    Exact equality over the whole fingerprint, including its key set: a field
    entering or leaving the basis (a subject that became readable, a KPI that
    joined the recommendation) is itself a material change.
    """
    if previous is None:
        return False
    return dict(previous) == dict(current)


__all__ = [
    "BASIS_METADATA_KEY",
    "BasisField",
    "basis_unchanged",
    "compute_card_basis",
    "stored_basis",
]
