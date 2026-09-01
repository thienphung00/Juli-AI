"""Reference capture provider (#1438): sizes of the bodies the record cites.

Deliberately trivial — its job is to prove the registry works end to end, not
to be interesting. It is also the template a Wave-2 slice copies: one module,
one ``PROVIDER_NAME``, one ``capture(context)`` returning one JSON object. No
edit to ``generate_status_records.py`` is needed to make this block appear.

It is still a real measurement rather than a placeholder. ``review.sha256`` and
``validation.sha256`` are opaque; a byte length beside them is the cheapest
observed-not-typed signal that distinguishes a substantive body from an empty
stub, and it is derived from the same bytes that were hashed into the record, so
it cannot describe a different file than the one the record cites.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from . import CaptureContext

PROVIDER_NAME = "artifactBytes"


def capture(context: CaptureContext) -> dict[str, Any]:
    """Return the byte sizes of the review and validation bodies."""
    return {
        "reviewBytes": len(context.review_bytes),
        "validationBytes": len(context.validation_bytes),
    }
