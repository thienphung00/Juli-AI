"""Map raw Kafka payloads to ``data`` repository upsert kwargs."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

TransformError = ValueError


def _unix_to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value is None:
        raise TransformError("missing update_time")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise TransformError(f"invalid datetime: {value}") from exc
    raise TransformError(f"unsupported update_time type: {type(value)}")


def _unwrap_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("type") and isinstance(payload.get("data"), dict):
        inner = dict(payload["data"])
        inner.setdefault("shop_id", payload.get("shop_id"))
        return inner
    return payload


def _transform_order(body: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    order_id = body.get("order_id")
    if not order_id:
        raise TransformError("order_id required")
    status = body.get("order_status") or body.get("status") or "UNKNOWN"
    amount = body.get("total_amount") or body.get("payment_amount") or 0
    return {
        "tiktok_order_id": str(order_id),
        "status": str(status),
        "buyer_id": body.get("buyer_id"),
        "total_amount": Decimal(str(amount)),
        "currency": str(body.get("currency") or "VND"),
        "update_time": _unix_to_datetime(
            body.get("update_time") or payload.get("timestamp")
        ),
    }


def _transform_product(body: dict[str, Any]) -> dict[str, Any]:
    product_id = body.get("product_id")
    if not product_id:
        raise TransformError("product_id required")
    return {
        "tiktok_product_id": str(product_id),
        "name": str(body.get("name") or body.get("title") or "Unknown"),
        "status": str(body.get("status") or "ACTIVE"),
        "revenue": Decimal(str(body.get("revenue", 0))),
        "units_sold": int(body.get("units_sold", 0)),
        "update_time": _unix_to_datetime(
            body.get("updated_at") or body.get("update_time")
        ),
    }


def _transform_inventory(body: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    sku_id = body.get("sku_id")
    if not sku_id:
        raise TransformError("sku_id required")
    return {
        "tiktok_product_id": str(
            body.get("product_id") or body.get("tiktok_product_id") or sku_id
        ),
        "tiktok_sku_id": str(sku_id),
        "quantity": int(
            body.get("available_quantity")
            if body.get("available_quantity") is not None
            else body.get("quantity", 0)
        ),
        "warehouse_id": body.get("warehouse_id"),
        "velocity": str(body.get("velocity") or "low"),
        "update_time": _unix_to_datetime(
            body.get("update_time") or body.get("updated_at") or payload.get("timestamp")
        ),
    }


def _transform_creator(body: dict[str, Any]) -> dict[str, Any]:
    creator_id = body.get("creator_id")
    if not creator_id:
        raise TransformError("creator_id required")
    update_time = body.get("update_time")
    return {
        "tiktok_creator_id": str(creator_id),
        "name": str(body.get("name") or "Unknown"),
        "follower_count": body.get("follower_count"),
        "update_time": _unix_to_datetime(update_time) if update_time else None,
    }


def _transform_livestream(body: dict[str, Any]) -> dict[str, Any]:
    livestream_id = body.get("livestream_id")
    if not livestream_id:
        raise TransformError("livestream_id required")
    update_time = body.get("update_time")
    return {
        "tiktok_livestream_id": str(livestream_id),
        "title": body.get("title"),
        "viewer_count": body.get("viewer_count"),
        "order_count": body.get("order_count"),
        "revenue": (
            Decimal(str(body["revenue"])) if body.get("revenue") is not None else None
        ),
        "update_time": _unix_to_datetime(update_time) if update_time else None,
    }


def _transform_settlement(body: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    settlement_id = body.get("settlement_id")
    if not settlement_id:
        raise TransformError("settlement_id required")
    return {
        "tiktok_settlement_id": str(settlement_id),
        "amount": Decimal(str(body.get("amount", 0))),
        "currency": str(body.get("currency") or "VND"),
        "status": str(body.get("status") or "pending"),
        "settlement_time": (
            _unix_to_datetime(body["settlement_time"])
            if body.get("settlement_time")
            else None
        ),
        "update_time": _unix_to_datetime(
            body.get("update_time") or payload.get("timestamp")
        ),
    }


def _topic_allowed(topic: str) -> bool:
    return topic in RAW_TOPICS or topic.startswith("tiktok.")


def transform_for_topic(topic: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return ``(entity_kind, upsert_kwargs_without_shop_id)`` for a Kafka message."""
    if not _topic_allowed(topic):
        raise TransformError(f"unsupported topic: {topic}")

    body = _unwrap_webhook(payload)

    if topic == "tiktok.orders.raw" or topic.startswith("tiktok.order") or body.get("order_id"):
        return "order", _transform_order(body, payload)

    if topic == "tiktok.products.raw" or body.get("product_id") and not body.get("sku_id"):
        return "product", _transform_product(body)

    if topic == "tiktok.inventory.raw" or body.get("sku_id"):
        return "inventory", _transform_inventory(body, payload)

    if topic in ("tiktok.creators.raw", "creator-events") or body.get("creator_id"):
        return "creator", _transform_creator(body)

    if topic in ("tiktok.livestreams.raw", "livestream-events") or body.get("livestream_id"):
        return "livestream", _transform_livestream(body)

    if topic in ("tiktok.settlements.raw", "settlement-events") or body.get("settlement_id"):
        return "settlement", _transform_settlement(body, payload)

    raise TransformError(f"no transformer for topic {topic}")
