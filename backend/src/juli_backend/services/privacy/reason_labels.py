"""Cancel / return reasons: a platform reason is kept, anything else is ``"other"`` (decision A).

A reason field can hold free text a buyer typed, so a value is stored only when it
is a STANDARD platform reason (owner decision A, 2026-10-27; audit gap 5):

- a machine reason code -- identifier-shaped (:data:`REASON_CODE`, e.g.
  ``ecom_order_delivered_refund_and_return_reason_damaged``) -- is kept as-is;
- a display label is kept only when it is in this module's catalog for its
  (platform, field);
- every other value becomes :data:`OTHER`. ``None`` and ``""`` stay as they are.

Applied in the bronze payload allowlist (``payload_allowlist``: ``cancel_reason``,
``return_reason``, ``return_reason_text``, ``cancel_reason_text``), in the silver
transform (``orders.cancel_reason``, ``returns.return_reason``) and by the operator
clean-up for rows stored before it (``payload_cleanup``). Idempotent: ``"other"``,
a code and a catalog label all map to themselves.

THE CATALOG. TikTok publishes no enum for these fields (the bundled Partner API
OAS gives one example per field and links a reason appendix page). It is seeded
from those OAS examples and from the synthetic fixtures under
``tests/fixtures/tiktok_privacy/`` (built from the OAS shapes) -- never from
production data. Partner Center localises labels with the request's ``locale``, so
a Vietnamese label is ``"other"`` until it is added here from the published
appendix. Add a label only from Partner Center documentation.
"""

from __future__ import annotations

import re
from typing import Any

OTHER = "other"
#: A machine reason code: lower-case identifier, as TikTok's reason codes are.
REASON_CODE = re.compile(r"^[a-z0-9_.]{1,80}$")

_TIKTOK_ORDER_CANCEL_LABELS: frozenset[str] = frozenset(
    {
        # OAS order.json examples (orders/search, orders/detail: cancel_reason).
        "Pricing error",
        "Discount not as expected",
        # tests/fixtures/tiktok_privacy/order_search_202309_order.json.
        "Out of stock",
    }
)
_TIKTOK_RETURN_TEXT_LABELS: frozenset[str] = frozenset(
    {
        # OAS return_refund.json examples (return_reason_text, reason_text).
        "Order created by mistake",
        "Wrong product was sent",
        # tests/fixtures/tiktok_privacy/return_search_202309_return.json.
        "Wrong item",
    }
)
_TIKTOK_CANCEL_TEXT_LABELS: frozenset[str] = frozenset(
    {
        # OAS return_refund.json example (cancellations: cancel_reason_text).
        "Order created by mistake",
        # tests/fixtures/tiktok_privacy/cancellation_search_202309_cancellation.json.
        "Changed my mind",
    }
)

#: Display labels kept per (platform, field). ``returns.return_reason`` in silver can
#: hold any of the return / cancellation labels (``normalize_return`` /
#: ``normalize_cancellation`` copy the text field in when the code is missing).
LABELS: dict[tuple[str, str], frozenset[str]] = {
    ("tiktok", "cancel_reason"): _TIKTOK_ORDER_CANCEL_LABELS | _TIKTOK_CANCEL_TEXT_LABELS,
    ("tiktok", "cancel_reason_text"): _TIKTOK_CANCEL_TEXT_LABELS,
    ("tiktok", "return_reason_text"): _TIKTOK_RETURN_TEXT_LABELS,
    ("tiktok", "return_reason"): (
        _TIKTOK_RETURN_TEXT_LABELS | _TIKTOK_CANCEL_TEXT_LABELS | _TIKTOK_ORDER_CANCEL_LABELS
    ),
}


def safe_reason(platform: str, field: str, value: Any) -> Any:
    """``value`` if a reason code or a catalog label of (platform, field), else ``"other"``."""
    if value is None or value == "":
        return value
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return OTHER
    text = str(value)
    if REASON_CODE.match(text):
        return text if isinstance(value, str) else value
    if text in LABELS.get((platform, field), frozenset()):
        return text
    return OTHER
