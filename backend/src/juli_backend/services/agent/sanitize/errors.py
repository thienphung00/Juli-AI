"""Marketplace error translation at the sanitization boundary (ADR-070 decision 5).

Every failure a tool executor can raise while calling out to the marketplace —
a coded `TikTokAPIError`, a pre-signing `TransportGuardError`, or a bare
network transport failure underneath either — maps here to exactly one shape
the agent loop can act on::

    {"error": {"category": ..., "message": ..., "retryable": ...}}

- ``category`` reuses the existing `ExecutionErrorCategory` taxonomy
  (``validation`` | ``tiktok_api`` | ``transient`` | ``unknown``, from
  `juli_backend.services.execution.types`) — no parallel taxonomy is
  introduced. Critically, ``category`` and ``retryable`` are derived from the
  **same fact** (the curated code allowlist below), not from independent
  logic that could disagree: any code in `RETRYABLE_VENDOR_CODES` is
  ``transient`` regardless of which exception *class* happens to carry it,
  so a ``retryable: true`` decision can never pair with the ``tiktok_api``
  category's "will not succeed unmodified" message. See `_category_for`'s
  docstring for the specific defect this closes (36009003 arriving as a bare
  `TikTokAPIError`, not a dedicated subclass).
- ``message`` is a curated, business-language English sentence written for a
  nano-class model. It is never built from ``str(exc)`` or
  `TikTokAPIError.message`: the vendor's own error text is not written for an
  LLM audience and offers no guarantee against carrying vendor-code-shaped
  substrings.
- ``retryable`` derives from a **curated allowlist** of vendor codes —
  `RETRYABLE_VENDOR_CODES` (``{100005, 100006, 36009003}``, the same set
  `juli_backend.integrations.tiktok.client` proved safe to retry once) — plus
  bare transport-level failures (`requests.ConnectionError`,
  `requests.Timeout`), which are always retryable because the request never
  reached the vendor for it to reject deterministically. An uncatalogued
  vendor code is deliberately **not** retryable: fail-open here would let the
  agent loop thrash re-calling a deterministic failure forever.

Raw vendor codes, vendor request ids, and endpoint paths are emitted to
server-side logs only (see `translate_marketplace_error`'s ``logger.warning``
call) and never appear in the returned `TranslatedError` — asserted directly,
and adversarially, by `tests/unit/test_agent_sanitize_errors.py`.

The loop policy this signal enables — one in-loop re-call on
``retryable: True``, then the step fails and the run reports ``failed``
honestly — belongs to the WorkflowRunner (W3-A). This module only produces
the signal; it does not retry, back off, or loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

from juli_backend.integrations.tiktok import (
    RateLimitError,
    TikTokAPIError,
    TikTokSystemError,
    TransportGuardError,
)
from juli_backend.services.execution.types import ExecutionErrorCategory

logger = logging.getLogger(__name__)

#: Vendor codes curated as safe to retry once (ADR-070 decision 5). Mirrors
#: `juli_backend.integrations.tiktok.client._RETRYABLE_APP_CODES`: 100005 is
#: the documented rate limit, 100006 the documented transient system error,
#: and 36009003 was captured live on 2026-08-08 as the first orders/search
#: 500 body ever seen ("Internal error. Please try again."). An uncatalogued
#: code is not retryable — this set is not derived from any broader
#: "5xx implies retry" heuristic.
RETRYABLE_VENDOR_CODES: frozenset[int] = frozenset({100005, 100006, 36009003})

#: Transport-level exception types with no vendor code to consult at all —
#: retrying is always plausibly useful because the failure happened before
#: the request ever reached the vendor.
_TRANSPORT_ERROR_TYPES: tuple[type[BaseException], ...] = (
    requests.ConnectionError,
    requests.Timeout,
)

_TIKTOK_API_MESSAGE = "TikTok Shop rejected the request and it will not succeed unmodified."
_TRANSIENT_VENDOR_MESSAGE = "TikTok Shop reported a temporary problem; retrying may succeed."
_TRANSPORT_MESSAGE = "Could not reach TikTok Shop; retrying may succeed."
_GUARD_MESSAGE = "This action was blocked by an internal safety check before reaching TikTok Shop."
_UNKNOWN_MESSAGE = "The action failed for an unrecognized reason."


@dataclass(frozen=True)
class TranslatedError:
    """The agent-safe error decision: category, business message, retryable.

    ``to_dict()`` renders exactly the three fields ADR-070 decision 5
    specifies — never a fourth key, never a raw vendor code, request id, or
    endpoint path.
    """

    category: ExecutionErrorCategory
    message: str
    retryable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "message": self.message,
            "retryable": self.retryable,
        }


def _category_for(exc: BaseException) -> ExecutionErrorCategory:
    """Coarse category for a marketplace failure.

    Mirrors `juli_backend.services.execution.errors.classify_execution_error`
    for the branches this translator handles, with one deliberate widening:
    category is derived from the **same fact** `_is_retryable` uses — the
    curated code allowlist — rather than from which exception *class*
    happened to carry the code. `RateLimitError`/`TikTokSystemError` cover
    100005/100006, but 36009003 (the third allowlisted code, live-captured on
    an `orders/search` 500) has no dedicated subclass in
    `integrations/tiktok/exceptions.py._CODE_MAP` and arrives as a bare
    `TikTokAPIError`. Classifying it by subclass alone would leave a
    ``retryable: true`` decision paired with a ``tiktok_api`` category whose
    curated message ("will not succeed unmodified") flatly contradicts the
    decision — a defect a nano-class model reading only `message` cannot see
    through. So: any code in `RETRYABLE_VENDOR_CODES` is ``transient``
    (an allowlisted-retryable failure *is* transient by definition, whether
    or not a subclass exists for it); a `TransportGuardError` is a
    deterministic policy rejection (``validation``, same as the execution
    layer); every other vendor-coded failure is ``tiktok_api``; a bare
    transport failure (no vendor code exists at all) is also ``transient``.
    Anything else this translator doesn't recognize is ``unknown``.
    """
    if isinstance(exc, TransportGuardError):
        return ExecutionErrorCategory.VALIDATION
    if isinstance(exc, TikTokAPIError):
        if isinstance(exc, (RateLimitError, TikTokSystemError)):
            return ExecutionErrorCategory.TRANSIENT
        if exc.code in RETRYABLE_VENDOR_CODES:
            return ExecutionErrorCategory.TRANSIENT
        return ExecutionErrorCategory.TIKTOK_API
    if isinstance(exc, _TRANSPORT_ERROR_TYPES):
        return ExecutionErrorCategory.TRANSIENT
    return ExecutionErrorCategory.UNKNOWN


def _is_retryable(exc: BaseException) -> bool:
    """True only when a retry can plausibly change the outcome.

    A `TikTokAPIError` is retryable only through the curated allowlist — an
    uncatalogued code is a deliberate `False`, not a fail-open default (a
    thrashing agent loop is worse than a step that fails honestly). A
    `TransportGuardError` is a deterministic policy rejection: re-calling the
    same request hits the same guard, so it is never retryable. A bare
    transport-level failure is always retryable: there is no vendor code to
    consult, and the request may simply not have reached TikTok Shop.
    """
    if isinstance(exc, TransportGuardError):
        return False
    if isinstance(exc, TikTokAPIError):
        return exc.code in RETRYABLE_VENDOR_CODES
    if isinstance(exc, _TRANSPORT_ERROR_TYPES):
        return True
    return False


def _message_for(exc: BaseException, *, category: ExecutionErrorCategory) -> str:
    """Curated, business-language English — never the vendor's raw text.

    `TikTokAPIError.message`, `TransportGuardError`'s own message, and
    ``str(exc)`` (which for `TikTokAPIError` embeds the raw code, e.g.
    ``"[100006] Internal error"``) are never used here: this is a fixed,
    per-case sentence written for a nano-class model with a small context —
    short and information-dense, not a pass-through of vendor copy.
    """
    if isinstance(exc, TransportGuardError):
        return _GUARD_MESSAGE
    if isinstance(exc, _TRANSPORT_ERROR_TYPES):
        return _TRANSPORT_MESSAGE
    if category is ExecutionErrorCategory.TRANSIENT:
        return _TRANSIENT_VENDOR_MESSAGE
    if category is ExecutionErrorCategory.TIKTOK_API:
        return _TIKTOK_API_MESSAGE
    return _UNKNOWN_MESSAGE


def translate_marketplace_error(exc: BaseException) -> TranslatedError:
    """Translate a marketplace failure into the agent-safe error decision.

    Every raw detail available on ``exc`` — vendor code, vendor request id,
    endpoint path, and capability/method for a guard rejection — is emitted
    to server-side logs via ``logger.warning`` before this function returns.
    None of it is present in, or derivable from, the returned
    `TranslatedError`: its only fields are ``category``, ``message``, and
    ``retryable``.
    """
    logger.warning(
        "agent_marketplace_error_translated",
        extra={
            "exception_type": type(exc).__name__,
            "vendor_code": getattr(exc, "code", None),
            "vendor_request_id": getattr(exc, "request_id", None),
            "endpoint_path": getattr(exc, "path", None),
            "guard_capability": getattr(exc, "capability", None),
            "guard_method": getattr(exc, "method", None),
            "detail": str(exc)[:800],
        },
    )
    category = _category_for(exc)
    return TranslatedError(
        category=category,
        message=_message_for(exc, category=category),
        retryable=_is_retryable(exc),
    )


def to_error_envelope(error: TranslatedError) -> dict[str, Any]:
    """Wire shape: ``{"error": {"category", "message", "retryable"}}``."""
    return {"error": error.to_dict()}


__all__ = [
    "RETRYABLE_VENDOR_CODES",
    "TranslatedError",
    "to_error_envelope",
    "translate_marketplace_error",
]
