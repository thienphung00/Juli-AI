"""The order-status map every ``silver.orders`` writer shares (fast track P70, E15).

The commerce poll (``tiktok.orders.raw``), the ORDER_STATUS_CHANGE webhook
(``tiktok.order_status_change``) and bronze promotion all map TikTok's status through
:func:`canonical_order_status`, so the webhook and the poll store the same value.

The vocabulary is the one ``etl.transform._canonical_order_status`` has always written,
byte for byte -- ``confirmed`` / ``shipped`` / ``delivered`` / ... for the statuses it
mapped, TikTok's value lower-cased for every other -- because readers
(``OrdersRepo.confirm_shipment``, ``order_costs``, ``optimize_product``, the
orders-sourced report) depend on it. P70 only ADDS: every spelling of a cancellation
(``CANCEL`` -- the webhook's --, ``CANCELED``, any case or spacing) is ``cancelled``.
Before that the webhook's ``CANCEL`` was stored as ``cancel``, which no cancellation
reader recognised.

A value TikTok has never been seen to send is still stored lower-cased (unchanged
behaviour) but logs ``order_status_unrecognised`` (the value bounded and reduced to
enum characters), so a new status shows up in the logs. A missing status is
``unknown``, as before.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

CANCELLED = "cancelled"
UNKNOWN_ORDER_STATUS = "unknown"

#: TikTok status -> stored value; exactly the pre-P70 map.
_MAPPED: dict[str, str] = {
    "UNPAID": "pending",
    "AWAITING_SHIPMENT": "confirmed",
    "PARTIALLY_SHIPPING": "confirmed",
    "AWAITING_COLLECTION": "confirmed",
    "IN_TRANSIT": "shipped",
    "SHIPPED": "shipped",
    "DELIVERED": "delivered",
    "COMPLETED": "delivered",
    "CANCELLED": CANCELLED,
    "RETURNED": "returned",
}
#: Every spelling of a cancellation (P70, E15). Keys are normalised by :func:`_key`.
CANCELLED_SPELLINGS: frozenset[str] = frozenset({"CANCELLED", "CANCELED", "CANCEL"})
#: TikTok statuses stored lower-cased on purpose (no warning): ON_HOLD is paid,
#: inside the buyer's cancel window, and readers know it as ``on_hold``.
_PASSTHROUGH: frozenset[str] = frozenset({"ON_HOLD"})
#: Values already in the stored vocabulary (a re-normalisation is a no-op, no warning).
_STORED_VALUES: frozenset[str] = frozenset(
    {value.upper() for value in _MAPPED.values()} | {UNKNOWN_ORDER_STATUS.upper()}
)

_SEPARATORS = re.compile(r"[\s\-]+")
_LOGGABLE = re.compile(r"[^A-Za-z0-9_]")


def _key(value: Any) -> str:
    return _SEPARATORS.sub("_", str(value).strip()).upper()


def is_cancelled_status(value: Any) -> bool:
    """Whether ``value`` is any spelling of a cancelled order (``cancel``, ``CANCELED`` ...)."""
    return value is not None and _key(value) in CANCELLED_SPELLINGS


def canonical_order_status(value: Any, *, warn: bool = True) -> str:
    """The value ``silver.orders.status`` stores for TikTok status ``value``.

    Mapped statuses as before P70; any cancellation spelling -> ``cancelled``; a
    missing status -> ``unknown``; anything else lower-cased (as before), logging
    ``order_status_unrecognised`` unless ``warn`` is false or it is a known
    pass-through (``ON_HOLD``) or already a stored value.
    """
    if value is None or not str(value).strip():
        return UNKNOWN_ORDER_STATUS
    key = _key(value)
    if key in CANCELLED_SPELLINGS:
        return CANCELLED
    # The pre-P70 lookup key exactly (upper-cased, nothing else), so no other value moves.
    mapped = _MAPPED.get(str(value).upper())
    if mapped is not None:
        return mapped
    if warn and key not in _PASSTHROUGH and key not in _STORED_VALUES:
        logger.warning(
            "order_status_unrecognised",
            extra={"raw_status": _LOGGABLE.sub("", str(value))[:40]},
        )
    return str(value).lower()


__all__ = [
    "CANCELLED",
    "CANCELLED_SPELLINGS",
    "UNKNOWN_ORDER_STATUS",
    "canonical_order_status",
    "is_cancelled_status",
]
