"""The one order-status vocabulary of ``silver.orders`` (fast track P70, E15).

Every writer of ``silver.orders.status`` -- the commerce poll (``tiktok.orders.raw``),
the ORDER_STATUS_CHANGE webhook (``tiktok.order_status_change``), bronze promotion
and the repair command -- maps TikTok's status through :func:`canonical_order_status`,
so the table only ever holds :data:`CANONICAL_ORDER_STATUSES`.

E15: TikTok's webhook spells a cancellation ``CANCEL`` where Order Search says
``CANCELLED``; the old map knew only the second and stored the raw value lower-cased
(``cancel``), which no cancellation reader (B12 refresh, quick scan, KPIs) recognised.

Unknown values are never stored raw: they become :data:`UNKNOWN_ORDER_STATUS` and
log ``order_status_unrecognised`` (the value bounded and reduced to enum characters),
so a new TikTok status shows up in the logs instead of as a new column value.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

PENDING = "pending"
ON_HOLD = "on_hold"
CONFIRMED = "confirmed"
SHIPPED = "shipped"
DELIVERED = "delivered"
CANCELLED = "cancelled"
RETURNED = "returned"
UNKNOWN_ORDER_STATUS = "unknown"

CANONICAL_ORDER_STATUSES: frozenset[str] = frozenset(
    {PENDING, ON_HOLD, CONFIRMED, SHIPPED, DELIVERED, CANCELLED, RETURNED, UNKNOWN_ORDER_STATUS}
)
#: Paid and not cancelled / returned. ``on_hold`` is paid, inside the buyer's
#: cancel window (TikTok holds the order before the seller may ship it).
PAID_ORDER_STATUSES: frozenset[str] = frozenset({ON_HOLD, CONFIRMED, SHIPPED, DELIVERED})
#: Statuses that take an order out of GMV.
REVERSED_ORDER_STATUSES: frozenset[str] = frozenset({CANCELLED, RETURNED})

_ALIASES: dict[str, str] = {
    # Order Search / Order Detail (202309) and the ORDER_STATUS_CHANGE webhook.
    "UNPAID": PENDING,
    "ON_HOLD": ON_HOLD,
    "AWAITING_SHIPMENT": CONFIRMED,
    "PARTIALLY_SHIPPING": CONFIRMED,
    "AWAITING_COLLECTION": CONFIRMED,
    "IN_TRANSIT": SHIPPED,
    "SHIPPED": SHIPPED,
    "DELIVERED": DELIVERED,
    "COMPLETED": DELIVERED,
    "CANCELLED": CANCELLED,
    "CANCELED": CANCELLED,
    "CANCEL": CANCELLED,  # the webhook's spelling (E15)
    "RETURNED": RETURNED,
    "REFUNDED": RETURNED,
    # API v1 (legacy) numeric order_status codes.
    "100": PENDING,
    "105": ON_HOLD,
    "111": CONFIRMED,
    "112": CONFIRMED,
    "114": CONFIRMED,
    "121": SHIPPED,
    "122": DELIVERED,
    "130": DELIVERED,
    "140": CANCELLED,
}
# Canonical values map to themselves, so the function is idempotent.
_ALIASES.update({value.upper(): value for value in CANONICAL_ORDER_STATUSES})

_SEPARATORS = re.compile(r"[\s\-]+")
_LOGGABLE = re.compile(r"[^A-Za-z0-9_]")


def _key(value: Any) -> str:
    return _SEPARATORS.sub("_", str(value).strip()).upper()


def known_order_status(value: Any) -> str | None:
    """The canonical value for ``value``, or ``None`` when it is missing or unrecognised."""
    if value is None or isinstance(value, bool):
        return None
    key = _key(value)
    if not key:
        return None
    return _ALIASES.get(key)


def canonical_order_status(value: Any, *, warn: bool = True) -> str:
    """Map any TikTok order status (string, any case, or v1 numeric) to the canonical value.

    Missing or unrecognised -> :data:`UNKNOWN_ORDER_STATUS`; an unrecognised non-empty
    value also logs ``order_status_unrecognised`` unless ``warn`` is false.
    """
    known = known_order_status(value)
    if known is not None:
        return known
    if warn and value is not None and str(value).strip():
        logger.warning(
            "order_status_unrecognised",
            extra={
                "raw_status": _LOGGABLE.sub("", str(value))[:40],
                "stored_as": UNKNOWN_ORDER_STATUS,
            },
        )
    return UNKNOWN_ORDER_STATUS


def is_canonical_order_status(value: Any) -> bool:
    return isinstance(value, str) and value in CANONICAL_ORDER_STATUSES


__all__ = [
    "CANCELLED",
    "CANONICAL_ORDER_STATUSES",
    "PAID_ORDER_STATUSES",
    "REVERSED_ORDER_STATUSES",
    "UNKNOWN_ORDER_STATUS",
    "canonical_order_status",
    "is_canonical_order_status",
    "known_order_status",
]
