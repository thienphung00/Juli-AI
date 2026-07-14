"""Stable event identifiers for idempotent consumption."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def extract_event_id(*, channel: str, shop_key: str, payload: dict[str, Any]) -> str:
    """Return a deterministic idempotency key for an ingest payload."""
    explicit = payload.get("event_id")
    if not explicit and isinstance(payload.get("data"), dict):
        explicit = payload["data"].get("event_id")
    if explicit:
        return str(explicit)

    if payload.get("type") and "data" in payload:
        event_type = str(payload["type"])
        timestamp = payload.get("timestamp", "")
        data = payload.get("data") or {}
        entity = (
            data.get("order_id")
            or data.get("product_id")
            or data.get("sku_id")
            or data.get("settlement_id")
            or data.get("livestream_id")
            or data.get("creator_id")
            or json.dumps(data, sort_keys=True)
        )
        return f"wh:{shop_key}:{event_type}:{timestamp}:{entity}"

    entity_id = (
        payload.get("return_id")
        or payload.get("order_id")
        or payload.get("product_id")
        or (
            f"{payload.get('tiktok_order_id')}:{payload.get('sku_id')}"
            if payload.get("tiktok_order_id") and payload.get("sku_id")
            else None
        )
        or payload.get("sku_id")
        or payload.get("creator_id")
        or payload.get("livestream_id")
        or payload.get("settlement_id")
    )
    version = payload.get("update_time") or payload.get("updated_at") or ""
    if entity_id is not None:
        return f"sync:{channel}:{shop_key}:{entity_id}:{version}"

    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:32]
    return f"hash:{channel}:{shop_key}:{digest}"
