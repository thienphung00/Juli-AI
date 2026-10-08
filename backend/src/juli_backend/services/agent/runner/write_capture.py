"""Before/after values of an agent WRITE (fast track P8-C, ADR-109 d.9).

Every WRITE that changes a listing field records, per field, the value read
from TikTok immediately before the write and the value after it. A "Hoàn tác"
run restores the before-values -- and only when the live listing still holds
Juli's after-value (S-FR-8: Juli never overwrites an external change).

This module is the pure half: which fields an operation touches, how to read
them off a raw ``products.get_details`` payload, how to diff two reads, and how
to compare a live value with a recorded one. ``ProductToolExecutor`` does the
reads around the dispatch and hands the diff to a ``WriteValueRecorder``;
``services/run_changes`` supplies the database-backed recorder.

**After-value source.** The after-value is what TikTok returns right after the
write. A listing edit can go to TikTok review, in which case the detail read
may still show the old value; then the value Juli sent is recorded instead and
marked ``intended``, so a revert still knows what Juli wrote.

**Fields.** ``update_product_listing`` touches ``title``, ``description`` and
``main_images`` (the ordered image URIs; attributes are passed through
unchanged by the tool today, so they are never recorded).
``update_product_price`` touches ``price`` (per SKU amount and currency). A
field whose value did not change is not recorded: there is nothing to undo.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from juli_backend.services.agent.runner.concurrency import ConcurrencyExhaustedError

AFTER_SOURCE_READ_BACK = "read_back"
AFTER_SOURCE_INTENDED = "intended"

LISTING_OPERATION = "update_product_listing"
PRICE_OPERATION = "update_product_price"

#: operation -> the fields it can change.
FIELDS_BY_OPERATION: Mapping[str, tuple[str, ...]] = {
    LISTING_OPERATION: ("title", "description", "main_images"),
    PRICE_OPERATION: ("price",),
}

RECORDED_OPERATIONS: frozenset[str] = frozenset(FIELDS_BY_OPERATION)


@dataclass(frozen=True)
class FieldWrite:
    """One field one WRITE changed."""

    field: str
    before: Any
    after: Any
    after_source: str


class WriteValueRecorder(Protocol):
    """Persists the before/after values of one WRITE dispatch.

    Best effort by contract: the vendor write has already happened when this is
    called, so an implementation logs its own failure instead of raising --
    failing the run after a successful write would misreport what happened.
    """

    def record(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        tiktok_product_id: str,
        writes: Sequence[FieldWrite],
    ) -> None: ...


class RevertTargetChangedError(ConcurrencyExhaustedError):
    """A "Hoàn tác" write found a field no longer holding Juli's after-value.

    Raised before the vendor call, so nothing is written. A subclass of
    ``ConcurrencyExhaustedError`` on purpose: ``WorkflowRunner`` already ends a
    run on that exception with ``stop_reason=concurrency_conflict`` at both of
    its dispatch sites -- the honest terminal state for "someone else changed
    this listing" -- so the revert needs no new stop reason or event type.
    """

    def __init__(self, *, operation: str, fields: Sequence[str]) -> None:
        super().__init__(operation=operation)
        self.fields = tuple(fields)


def _image_uris(raw: Mapping[str, Any]) -> list[str]:
    uris: list[str] = []
    for image in raw.get("main_images") or []:
        if isinstance(image, Mapping):
            uri = image.get("uri")
            if uri:
                uris.append(str(uri))
        elif image:
            uris.append(str(image))
    return uris


def _prices(raw: Mapping[str, Any]) -> list[dict[str, str]]:
    prices = []
    for sku in raw.get("skus") or []:
        if not isinstance(sku, Mapping):
            continue
        price = sku.get("price") or {}
        prices.append(
            {
                "sku_id": str(sku.get("id")),
                "amount": str(price.get("tax_exclusive_price") or price.get("amount") or ""),
                "currency": str(price.get("currency") or ""),
            }
        )
    return sorted(prices, key=lambda row: row["sku_id"])


def field_values(operation: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    """The current value of each field ``operation`` can change, from a detail read."""
    if operation == LISTING_OPERATION:
        return {
            "title": raw.get("title"),
            "description": raw.get("description"),
            "main_images": _image_uris(raw),
        }
    if operation == PRICE_OPERATION:
        return {"price": _prices(raw)}
    return {}


def _normalized(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def values_match(left: Any, right: Any) -> bool:
    """Whether a live value still equals a recorded one (surrounding whitespace ignored)."""
    return _normalized(left) == _normalized(right)


def diff_write(
    operation: str,
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    intended: Mapping[str, Any],
) -> list[FieldWrite]:
    """The fields this WRITE changed: read-back first, the sent value as fallback.

    ``before``/``after`` are ``field_values`` of the reads around the write;
    ``intended`` holds the values Juli sent (absent or ``None`` = not sent).
    """
    writes: list[FieldWrite] = []
    for field in FIELDS_BY_OPERATION.get(operation, ()):
        old = before.get(field)
        new = after.get(field)
        if not values_match(old, new):
            writes.append(FieldWrite(field, old, new, AFTER_SOURCE_READ_BACK))
            continue
        sent = intended.get(field)
        if sent is not None and not values_match(old, sent):
            writes.append(FieldWrite(field, old, sent, AFTER_SOURCE_INTENDED))
    return writes


def changed_fields(
    operation: str, *, live: Mapping[str, Any], expected: Mapping[str, Any]
) -> list[str]:
    """The fields in ``expected`` whose live value no longer matches it."""
    return [
        field
        for field in FIELDS_BY_OPERATION.get(operation, ())
        if field in expected and not values_match(live.get(field), expected[field])
    ]


__all__ = [
    "AFTER_SOURCE_INTENDED",
    "AFTER_SOURCE_READ_BACK",
    "FIELDS_BY_OPERATION",
    "LISTING_OPERATION",
    "PRICE_OPERATION",
    "RECORDED_OPERATIONS",
    "FieldWrite",
    "RevertTargetChangedError",
    "WriteValueRecorder",
    "changed_fields",
    "diff_write",
    "field_values",
    "values_match",
]
