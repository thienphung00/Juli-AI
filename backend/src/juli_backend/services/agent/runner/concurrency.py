"""Basis-hash concurrency control — ADR-073 decision 4, issue #1122 / AGT-W3A.

TikTok exposes no product version number, so this module's basis hash *is*
the version: a server-held SHA-256 per mutable field (title, description,
price, images), computed from a raw `products.get_details`-shaped payload
and never — as a hash, a value, or a field name — placed anywhere an
`LLMService.complete()` call can see it. `RunState.basis_snapshots`
(`state.py`, #1118) is the durable home for the snapshot this module
produces; `state.py`'s own `conversation_window_for_llm` is what makes that
field structurally unreachable from the LLM-facing message list — this
module's job is producing and comparing the hash, not the storage seam.

**Field-scoped compare-before-write.** `FIELD_SCOPE_BY_OPERATION` names,
per WRITE tool, exactly which of the four mutable fields that tool changes:
`update_product_price` -> `("price",)`; `update_product_listing` ->
`("title", "description", "images")`. `ConcurrencyGuard.check_before_write`
recomputes the hash from a *fresh* re-read and compares only the scoped
subset against the stored basis — a seller editing the description never
conflicts a price-only write, and vice versa, because the out-of-scope
field's hash is never even looked at.

**Fail-closed, one bounded re-proposal (ADR-073 decision 4).** A scoped
mismatch on an operation's *first* attempt returns a `ConcurrencyConflict`
carrying a sanitized, LLM-safe payload (`{"conflict": True,
"current_values": {...}}`) — no basis hash, no raw vendor id, no vendor
endpoint — for exactly one corrected re-proposal. A *second* mismatch on
the *same* operation raises `ConcurrencyExhaustedError` instead of
returning a payload at all: this module never lets a caller ask a third
time. Unbounded revalidation against an actively-editing seller is the
design ADR-073 explicitly rejects.

**"Same operation" = the WRITE tool name, matching `ledger.py`'s
`operation` key exactly** (`ProductToolExecutor` passes `tool_name` as
both). This is a judgment call the issue text does not pin down further:
Optimize Product's playbook calls each WRITE tool at most once per run in
the common case, so tool-name granularity and "the specific tool-call
chain" coincide for every real scenario this epic ships. A `ConcurrencyGuard`
is constructed once per run (mirroring `ToolExecutionLedger` and
`ProductToolExecutor` themselves), so the conflict counter's lifetime is
already scoped to one run without needing `workflow_run_id` threaded
through every call.

**Conflict counts are monotonic for the guard's lifetime — never reset by
a fresh basis read.** A tempting alternative is to clear an operation's
conflict count whenever `record_basis` runs (the model called a READ tool
again). This module deliberately does not do that: `check_before_write`
itself re-reads the product on every call regardless, so a model could
otherwise dodge the two-attempt bound indefinitely by interleaving a cheap
`get_product_information` call before every retry — exactly the unbounded
revalidation ADR-073 rejects. The bound is per (guard lifetime, operation),
full stop.

**Post-write basis refresh (this module's own extension, not stated by the
issue text).** Without it, a *second* WRITE to the same operation later in
the same run — legitimate, since the first write is what changed the
value — would spuriously report a conflict: the stored basis still reflects
the pre-write value, but the fresh re-read (correctly) reflects what this
run itself just wrote. `ProductToolExecutor`'s wiring calls
`ConcurrencyGuard.record_basis` again immediately after a successful WRITE
dispatch (ledger-routed or direct) so the guard's own prior write is never
mistaken for a competing edit.

**What this module does NOT wire up (see `tool_executor.py`'s own
docstring for the mirrored caveat about the ledger).** `core.py` is out of
this issue's bounds (task scoping — the GitHub issue text permits a
"surface the conflict result" touch, but this slice's actual write-path
allowlist does not include it), and it does not thread `tool_call_id`
into `ToolExecutor.execute` at all today, so neither this guard nor
`ledger.py`'s idempotency machinery is reachable from a live run yet. This
module is fully unit-tested standalone and its `ProductToolExecutor` wiring
is opt-in and tested the same way #1121's ledger routing was — but calling
it "active in production" would be false. A later slice constructs
`ProductToolExecutor` per run, populates `ConcurrencyGuard` from
`RunState.basis_snapshots`, and threads `ConcurrencyExhaustedError` into a
`stop_reason=concurrency_conflict` termination — none of that exists yet.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from juli_backend.services.agent.status import StopReason

#: The four — and only the four — mutable product fields this epic's basis
#: hash governs (ADR-073 decision 4). `MutableProductFields` below is a
#: fixed-shape dataclass rather than an open `dict[str, Any]` precisely so a
#: fifth field (e.g. `status`) cannot structurally participate in the hash —
#: the "iff" half of "the hash changes iff one of the four fields changes"
#: is enforced by this shape, not by a runtime check.
MUTABLE_FIELD_NAMES: tuple[str, str, str, str] = ("title", "description", "price", "images")


@dataclass(frozen=True)
class MutableProductFields:
    """The exact and only inputs a basis hash is computed over.

    `price`/`images` are already-canonicalized, order-independent
    representations (see `extract_mutable_fields`) — sortable tuples/lists
    of primitives, not raw vendor response fragments — so two reads of an
    unchanged product always hash identically regardless of the vendor
    API's own field ordering.
    """

    title: str | None
    description: str | None
    price: Sequence[tuple[str, str, str]]
    images: Sequence[str]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _hash_field(field_name: str, value: Any) -> str:
    """SHA-256 hex digest of one field's canonical JSON representation,
    namespaced by `field_name` so two different fields holding the same
    value never collide."""
    payload = _canonical_json({field_name: value})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def capture_basis_snapshot(fields: MutableProductFields) -> dict[str, str]:
    """Per-field SHA-256 basis hash (ADR-073 decision 4).

    Returns one hash per `MUTABLE_FIELD_NAMES` entry. Because each field is
    hashed independently, a snapshot changes in *exactly* the field(s) whose
    value changed — the property `check_before_write`'s field-scoped compare
    relies on, and the property the acceptance criteria ask to be proven
    directly (each of the four changes its own hash; nothing else changes).
    """
    return {
        "title": _hash_field("title", fields.title),
        "description": _hash_field("description", fields.description),
        "price": _hash_field("price", fields.price),
        "images": _hash_field("images", fields.images),
    }


def extract_mutable_fields(raw: Mapping[str, Any]) -> MutableProductFields:
    """Build `MutableProductFields` from a raw `products.get_details()`-shaped
    vendor payload — the same field sourcing `tools/product.py`'s READ
    handler uses (`title`, `description`, `skus[].price`, `main_images`),
    reimplemented independently here rather than imported: this module never
    touches `services/agent/tools/` (out of this issue's write-path bounds),
    and a basis hash that never leaves the server has no reason to share
    ADR-070's provenance/capping machinery, which exists only for
    LLM-facing shaping.
    """
    skus = raw.get("skus") or []
    price_repr = tuple(
        sorted(
            (
                str(sku.get("id")),
                str((sku.get("price") or {}).get("tax_exclusive_price")),
                str((sku.get("price") or {}).get("currency")),
            )
            for sku in skus
        )
    )
    images = raw.get("main_images") or []
    images_repr = tuple(
        sorted(str(image.get("uri") if isinstance(image, dict) else image) for image in images)
    )
    return MutableProductFields(
        title=raw.get("title"),
        description=raw.get("description"),
        price=price_repr,
        images=images_repr,
    )


#: Which of the four mutable fields each WRITE tool changes (ADR-073
#: decision 4: "recomputes over the fields that write mutates"). Keyed by
#: tool name — the same string `ledger.py` calls `operation`.
FIELD_SCOPE_BY_OPERATION: Mapping[str, tuple[str, ...]] = {
    "update_product_price": ("price",),
    "update_product_listing": ("title", "description", "images"),
}


class UnknownConcurrencyScopedOperationError(ValueError):
    """`field_scope_for` was asked about a tool name not present in
    `FIELD_SCOPE_BY_OPERATION` — a wiring defect (every WRITE tool that
    mutates one of the four fields must have an entry), never a normal
    runtime outcome. Tools that do not mutate any of the four fields (e.g.
    `upload_product_image`, which only stages an upload) are never asked."""


def field_scope_for(operation: str) -> tuple[str, ...]:
    try:
        return FIELD_SCOPE_BY_OPERATION[operation]
    except KeyError as exc:
        raise UnknownConcurrencyScopedOperationError(
            f"No basis-hash field scope registered for operation {operation!r}."
        ) from exc


def _public_current_values(fields: MutableProductFields, scope: Sequence[str]) -> dict[str, Any]:
    """The sanitized, LLM-safe subset of `fields` for a conflict payload's
    `current_values` — scope-limited (never a field outside what this
    operation cares about) and, independently, never a raw vendor SKU id or
    image URI (ADR-070's "no raw vendor id" rule, upheld here even though
    this module is outside `services/agent/tools/` — the rule is about what
    reaches the LLM, not which module produces it)."""
    values: dict[str, Any] = {}
    if "title" in scope:
        values["title"] = fields.title
    if "description" in scope:
        values["description"] = fields.description
    if "price" in scope:
        values["price"] = sorted(
            {"amount": amount, "currency": currency} for (_sku_id, amount, currency) in fields.price
        )
    if "images" in scope:
        values["images"] = {"count": len(fields.images)}
    return values


@dataclass(frozen=True)
class ConcurrencyMatch:
    """Compare-before-write found every scoped field unchanged — the caller
    proceeds to sign and dispatch the write exactly as it would without
    this guard present."""


@dataclass(frozen=True)
class ConcurrencyConflict:
    """First mismatch on this operation. `payload` is the sanitized,
    LLM-safe structured result (`{"conflict": True, "current_values":
    {...}}`) for the caller to return as the tool result — never a basis
    hash, never a raw vendor id — for exactly one bounded re-proposal."""

    payload: Mapping[str, Any]


ConcurrencyCheckResult = ConcurrencyMatch | ConcurrencyConflict


class ConcurrencyExhaustedError(RuntimeError):
    """A *second* mismatch on the same operation (ADR-073 decision 4: "one
    bounded re-proposal... a second conflict on the same operation stops
    the run"). Carries `stop_reason` so whatever surfaces run termination
    (not this slice's job to wire — see module docstring) can read it
    directly rather than re-deriving it."""

    stop_reason: StopReason = StopReason.CONCURRENCY_CONFLICT

    def __init__(self, *, operation: str) -> None:
        self.operation = operation
        super().__init__(
            f"Second concurrency conflict on operation {operation!r} — refusing a "
            "third revalidation attempt (ADR-073 decision 4)."
        )


class ConcurrencyGuard:
    """Per-run compare-before-write state (ADR-073 decision 4).

    Constructed once per run — mirroring `ToolExecutionLedger` and
    `ProductToolExecutor` — optionally seeded with a basis snapshot already
    captured elsewhere (the durable form of which lives in
    `RunState.basis_snapshots`; this class holds the in-memory working copy
    a live run's `ProductToolExecutor` would consult, per the module
    docstring's "what this module does NOT wire up").
    """

    def __init__(self, *, basis_snapshot: Mapping[str, str] | None = None) -> None:
        self._basis_snapshot: dict[str, str] = dict(basis_snapshot or {})
        self._conflict_counts: dict[str, int] = {}
        # #1389: raw product detail from the read that captured this basis,
        # carried alongside the basis so the runner can persist both together.
        self._product_detail: Mapping[str, Any] | None = None

    @property
    def basis_snapshot(self) -> Mapping[str, str]:
        """A defensive copy — callers cannot mutate this guard's stored
        basis by mutating the returned mapping."""
        return dict(self._basis_snapshot)

    def record_basis(self, fields: MutableProductFields) -> None:
        """Capture (or refresh) the basis snapshot from a fresh product
        read. Deliberately does **not** reset any operation's conflict
        count — see the module docstring's "Conflict counts are monotonic"
        section for why."""
        self._basis_snapshot = capture_basis_snapshot(fields)

    def set_product_detail(self, raw: Mapping[str, Any]) -> None:
        """Store the raw product detail read during basis capture.

        Issue #1389: when get_product_information reads the product and
        record_basis is called, also store the raw detail so the runner can
        persist both the basis and its source together to RunState.
        """
        self._product_detail = raw

    def get_product_detail(self) -> Mapping[str, Any] | None:
        """Retrieve the raw product detail stored at basis capture time.

        Returns None if no product has been read yet (e.g. test doubles that
        never populate it).
        """
        return self._product_detail

    def check_before_write(
        self, *, operation: str, current_fields: MutableProductFields
    ) -> ConcurrencyCheckResult:
        """Immediately-before-write compare (ADR-073 decision 4).

        Recomputes the hash over exactly `field_scope_for(operation)` and
        compares against the stored basis for those fields only — an
        out-of-scope field's hash is never read, let alone compared, which
        is the whole of how per-operation field scoping holds.

        Returns `ConcurrencyMatch` on a full scoped match. Raises
        `ConcurrencyExhaustedError` on a second mismatch for this
        `operation` (this guard's lifetime, not reset by `record_basis`);
        otherwise returns a `ConcurrencyConflict` carrying the sanitized
        payload for the caller's one bounded re-proposal.
        """
        scope = field_scope_for(operation)
        recomputed = capture_basis_snapshot(current_fields)
        mismatched = [
            name for name in scope if self._basis_snapshot.get(name) != recomputed.get(name)
        ]

        if not mismatched:
            return ConcurrencyMatch()

        count = self._conflict_counts.get(operation, 0) + 1
        self._conflict_counts[operation] = count

        if count >= 2:
            raise ConcurrencyExhaustedError(operation=operation)

        return ConcurrencyConflict(
            payload={
                "conflict": True,
                "current_values": _public_current_values(current_fields, scope),
            }
        )


__all__ = [
    "MUTABLE_FIELD_NAMES",
    "ConcurrencyConflict",
    "ConcurrencyExhaustedError",
    "ConcurrencyGuard",
    "ConcurrencyMatch",
    "FIELD_SCOPE_BY_OPERATION",
    "MutableProductFields",
    "UnknownConcurrencyScopedOperationError",
    "capture_basis_snapshot",
    "extract_mutable_fields",
    "field_scope_for",
]
