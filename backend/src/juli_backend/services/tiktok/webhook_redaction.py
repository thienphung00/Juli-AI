"""Field allowlist for stored webhook deliveries (#392; owner decision D16, ADR-116 §4).

A webhook body is reduced to its kind's allowlist (``services/privacy/payload_allowlist``:
``webhook.order`` / ``webhook.return`` / ``webhook.other``, and ``webhook.unknown`` --
envelope only -- for a type the catalog does not know) before it is stored in
``webhook_raw_events.raw_body`` or ``workflow_webhook_signals.payload``. It replaces
the old key denylist, which let ``message``, ``note``, ``avatar``, ``buyer_id``,
``user_id``, ``comment`` and ``reason`` through: anything not listed is now dropped
at any depth.

``buyer_id`` is listed for order and return events so the callers can store it as
the shop's pseudonym (``services/privacy/pseudonym.py``). Where no shop is known
(an unauthenticated delivery, an unknown shop) it is dropped instead --
:func:`drop_buyer_ids`. Malformed JSON yields ``None`` (no body stored). The
serialized text is truncated at ``RAW_BODY_MAX_BYTES``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from juli_backend.services.privacy.payload_allowlist import (
    TIKTOK,
    WEBHOOK_ORDER,
    WEBHOOK_OTHER,
    WEBHOOK_RETURN,
    WEBHOOK_UNKNOWN,
    allowlist_payload,
)
from juli_backend.services.privacy.pseudonym import BUYER_ID_KEY
from juli_backend.services.tiktok.webhook_catalog import catalog_id_for_event

RAW_BODY_MAX_BYTES = 32 * 1024
TRUNCATION_SUFFIX = "…[TRUNCATED]"

#: Order lifecycle events: status change, address update (ids only), package, FBT MCF.
WEBHOOK_ORDER_CATALOG_IDS: frozenset[int] = frozenset({1, 3, 4, 58})
#: Reverse events: legacy reverse, cancellation, return, after-sales, RMA, refund.
WEBHOOK_RETURN_CATALOG_IDS: frozenset[int] = frozenset({2, 11, 12, 64, 65, 67})


def webhook_endpoint(event_type: Any) -> str:
    """The allowlist endpoint of a delivered ``type`` (catalog name or numeric id)."""
    raw = str(event_type).strip() if event_type is not None else ""
    catalog_id = catalog_id_for_event(raw) if raw else None
    if catalog_id is None:
        return WEBHOOK_UNKNOWN
    if catalog_id in WEBHOOK_ORDER_CATALOG_IDS:
        return WEBHOOK_ORDER
    if catalog_id in WEBHOOK_RETURN_CATALOG_IDS:
        return WEBHOOK_RETURN
    return WEBHOOK_OTHER


def allowlist_webhook(payload: Mapping[str, Any]) -> dict[str, Any]:
    """``payload`` (a delivery: envelope + ``data``) reduced to its kind's allowlist."""
    return allowlist_payload(TIKTOK, webhook_endpoint(payload.get("type")), payload)


def has_buyer_id(value: Any) -> bool:
    """``True`` when a non-empty ``buyer_id`` appears at any depth."""
    if isinstance(value, Mapping):
        return any(
            (key == BUYER_ID_KEY and child not in (None, "")) or has_buyer_id(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(has_buyer_id(item) for item in value)
    return False


def drop_buyer_ids(value: Any) -> Any:
    """A copy of ``value`` without any ``buyer_id`` key, at any depth."""
    if isinstance(value, Mapping):
        return {k: drop_buyer_ids(v) for k, v in value.items() if k != BUYER_ID_KEY}
    if isinstance(value, list):
        return [drop_buyer_ids(item) for item in value]
    return value


def parse_webhook_body(body: bytes) -> dict[str, Any] | None:
    """The body as a JSON object; ``None`` when it is not one."""
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def serialize_stored_body(payload: Mapping[str, Any]) -> str:
    """Compact JSON, truncated at ``RAW_BODY_MAX_BYTES``."""
    return _truncate(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _truncate(text: str) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= RAW_BODY_MAX_BYTES:
        return text
    budget = RAW_BODY_MAX_BYTES - len(TRUNCATION_SUFFIX.encode("utf-8"))
    if budget <= 0:
        return TRUNCATION_SUFFIX[:RAW_BODY_MAX_BYTES]
    truncated = encoded[:budget].decode("utf-8", errors="ignore")
    return truncated + TRUNCATION_SUFFIX


def redact_webhook_body(body: bytes) -> str | None:
    """The allowlisted body with no ``buyer_id``, or ``None`` when not a JSON object.

    For a caller that cannot resolve the shop; one that can pseudonymises the
    ``buyer_id`` instead (``webhook_raw_log.DatabaseRawWebhookEventRecorder``).
    """
    parsed = parse_webhook_body(body)
    if parsed is None:
        return None
    return serialize_stored_body(drop_buyer_ids(allowlist_webhook(parsed)))
