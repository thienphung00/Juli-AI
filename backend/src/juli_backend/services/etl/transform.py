"""Map raw ingest payloads to ``data`` repository upsert kwargs."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from juli_backend.integrations.tiktok.mapping import (
    normalize_creator,
    normalize_livestream,
    normalize_order,
    normalize_product,
    normalize_return,
    normalize_statement,
)
from juli_backend.services.etl.channels import RAW_CHANNELS

TransformError = ValueError


def _unix_to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)
    if value is None:
        raise TransformError("missing update_time")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC).replace(tzinfo=None)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return _unix_to_datetime(parsed)
        except ValueError as exc:
            raise TransformError(f"invalid datetime: {value}") from exc
    raise TransformError(f"unsupported update_time type: {type(value)}")


def _nested_payment_amount(payment: Any) -> Any:
    if not isinstance(payment, dict):
        return None
    return payment.get("total_amount") or payment.get("payment_amount")


def _coerce_int(value: Any, *, default: int = 0) -> int:
    if value is None:
        return default
    return int(value)


def _unwrap_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("type") and isinstance(payload.get("data"), dict):
        inner = dict(payload["data"])
        inner.setdefault("shop_id", payload.get("shop_id"))
        return inner
    return payload


def _transform_order(body: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    order_id = body.get("order_id") or body.get("id")
    if not order_id:
        raise TransformError("order_id required")
    status = body.get("order_status") or body.get("status") or "UNKNOWN"
    amount = (
        body.get("total_amount")
        or body.get("payment_amount")
        or _nested_payment_amount(body.get("payment"))
        or 0
    )
    order_value = Decimal(str(amount))
    return {
        "tiktok_order_id": str(order_id),
        "status": _canonical_order_status(status),
        "buyer_id": body.get("buyer_id"),
        "order_value": order_value,
        "total_amount": order_value,
        "currency": str(body.get("currency") or "VND"),
        "payment_time": _optional_datetime(body.get("payment_time")),
        "ship_time": _optional_datetime(body.get("ship_time") or body.get("shipping_time")),
        "delivery_time": _optional_datetime(
            body.get("delivery_time") or body.get("delivered_time")
        ),
        "tiktok_created_at": _optional_datetime(body.get("create_time")),
        "cancel_reason": body.get("cancel_reason"),
        "is_seller_fault": body.get("is_seller_fault"),
        "update_time": _unix_to_datetime(
            body.get("update_time") or payload.get("timestamp")
        ),
    }


def _optional_datetime(value: Any) -> datetime | None:
    return _unix_to_datetime(value) if value is not None else None


def _canonical_order_status(value: Any) -> str:
    status = str(value or "").upper()
    status_map = {
        "UNPAID": "pending",
        "AWAITING_SHIPMENT": "confirmed",
        "PARTIALLY_SHIPPING": "confirmed",
        "AWAITING_COLLECTION": "confirmed",
        "IN_TRANSIT": "shipped",
        "SHIPPED": "shipped",
        "DELIVERED": "delivered",
        "COMPLETED": "delivered",
        "CANCELLED": "cancelled",
        "RETURNED": "returned",
    }
    return status_map.get(status, str(value).lower())


def _transform_order_item(
    body: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    sku_id = body.get("sku_id")
    tiktok_order_id = body.get("tiktok_order_id")
    if not sku_id or not tiktok_order_id:
        raise TransformError("sku_id and tiktok_order_id required")
    quantity = _coerce_int(body.get("quantity"), default=1)
    unit_price = body.get("unit_price") or 0
    line_total = body.get("line_total")
    if line_total is None:
        line_total = Decimal(str(unit_price)) * quantity
    return {
        "tiktok_order_id": str(tiktok_order_id),
        "tiktok_product_id": (
            str(body["product_id"]) if body.get("product_id") is not None else None
        ),
        "tiktok_sku_id": str(sku_id),
        "quantity": quantity,
        "unit_price": Decimal(str(unit_price)),
        "line_total": Decimal(str(line_total)),
        "update_time": _unix_to_datetime(
            body.get("update_time") or payload.get("timestamp")
        ),
    }


def _transform_return(body: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return_id = body.get("return_id")
    if not return_id:
        raise TransformError("return_id required")
    tiktok_order_id = body.get("tiktok_order_id") or body.get("order_id")
    if not tiktok_order_id:
        raise TransformError("tiktok_order_id required")
    refund = body.get("refund_amount") or 0
    return {
        "tiktok_return_id": str(return_id),
        "tiktok_order_id": str(tiktok_order_id),
        "buyer_id": body.get("buyer_id"),
        "tiktok_product_id": (
            str(body["product_id"]) if body.get("product_id") is not None else None
        ),
        "tiktok_sku_id": str(body["sku_id"]) if body.get("sku_id") is not None else None,
        "return_type": str(body.get("return_type") or "other"),
        "return_condition": str(body.get("return_condition") or "unknown"),
        "return_reason": body.get("return_reason"),
        "refund_amount": Decimal(str(refund)),
        "status": str(body.get("status") or body.get("return_status") or "pending_review"),
        "update_time": _unix_to_datetime(
            body.get("update_time")
            or body.get("create_time")
            or payload.get("timestamp")
        ),
    }


def _transform_product(body: dict[str, Any]) -> dict[str, Any]:
    product_id = body.get("product_id") or body.get("id")
    if not product_id:
        raise TransformError("product_id required")
    price = body.get("price")
    audit_status = _canonical_audit_status(body.get("audit_status") or body.get("status"))
    return {
        "tiktok_product_id": str(product_id),
        "title": str(body.get("title") or body.get("name") or "Unknown"),
        "category": body.get("category"),
        "category_id": body.get("category_id"),
        "price": Decimal(str(price)) if price is not None else None,
        "price_currency": body.get("price_currency") or "VND",
        "inventory": (
            _coerce_int(body["inventory"]) if body.get("inventory") is not None else None
        ),
        "audit_status": audit_status,
        "tiktok_created_at": (
            _unix_to_datetime(body["create_time"]) if body.get("create_time") else None
        ),
        "name": str(body.get("name") or body.get("title") or "Unknown"),
        "status": str(body.get("status") or audit_status or "ACTIVE"),
        "revenue": Decimal(str(body.get("revenue", 0))),
        "units_sold": int(body.get("units_sold", 0)),
        "update_time": _unix_to_datetime(
            body.get("updated_at") or body.get("update_time")
        ),
    }


def _canonical_audit_status(value: Any) -> str:
    status = str(value or "active").lower()
    if status in {"on_sale", "active", "approved"}:
        return "active"
    if status in {"under_audit", "auditing", "reviewing"}:
        return "under_audit"
    if status in {"suspended", "blocked"}:
        return "suspended"
    if status in {"delisted", "inactive", "deleted"}:
        return "delisted"
    return status


def _transform_inventory(body: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    sku_id = body.get("sku_id")
    if not sku_id:
        raise TransformError("sku_id required")
    return {
        "tiktok_product_id": str(
            body.get("product_id") or body.get("tiktok_product_id") or sku_id
        ),
        "tiktok_sku_id": str(sku_id),
        "quantity": _coerce_int(
            body.get("available_quantity")
            if body.get("available_quantity") is not None
            else body.get("quantity"),
            default=0,
        ),
        "warehouse_id": body.get("warehouse_id"),
        "velocity": str(body.get("velocity") or "low"),
        "update_time": _unix_to_datetime(
            body.get("update_time") or body.get("updated_at") or payload.get("timestamp")
        ),
    }


def _transform_creator(body: dict[str, Any]) -> dict[str, Any]:
    body = normalize_creator(body)
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
    body = normalize_livestream(body)
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
    body = normalize_statement(body)
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


def _channel_allowed(channel: str) -> bool:
    return channel in RAW_CHANNELS or channel.startswith("tiktok.")


def transform_for_channel(
    channel: str, payload: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Return ``(entity_kind, upsert_kwargs_without_shop_id)`` for an ingest payload."""
    if not _channel_allowed(channel):
        raise TransformError(f"unsupported channel: {channel}")

    body = _unwrap_webhook(payload)

    if (
        channel == "tiktok.orders.raw"
        or (
            channel.startswith("tiktok.order")
            and channel != "tiktok.order_items.raw"
        )
        or (
            (body.get("order_id") or body.get("id"))
            and not body.get("return_id")
            and channel != "tiktok.order_items.raw"
            and channel != "tiktok.products.raw"
        )
    ):
        return "order", _transform_order(normalize_order(body), payload)

    if channel == "tiktok.order_items.raw":
        return "order_item", _transform_order_item(body, payload)

    if channel == "tiktok.returns.raw" or body.get("return_id"):
        return "return", _transform_return(normalize_return(body), payload)

    if (
        channel == "tiktok.products.raw"
        or (
            (body.get("product_id") or body.get("id"))
            and not body.get("sku_id")
            and not body.get("return_id")
        )
    ):
        return "product", _transform_product(normalize_product(body))

    if channel == "tiktok.inventory.raw" or (
        body.get("sku_id") and channel not in ("tiktok.order_items.raw", "tiktok.returns.raw")
    ):
        return "inventory", _transform_inventory(body, payload)

    if channel in ("tiktok.creators.raw", "creator-events") or body.get("creator_id"):
        return "creator", _transform_creator(body)

    if channel in ("tiktok.livestreams.raw", "livestream-events") or body.get("livestream_id"):
        return "livestream", _transform_livestream(body)

    if channel in ("tiktok.settlements.raw", "settlement-events") or body.get("settlement_id"):
        return "settlement", _transform_settlement(body, payload)

    raise TransformError(f"no transformer for channel {channel}")


def transform_for_topic(topic: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Deprecated alias for ``transform_for_channel``."""
    return transform_for_channel(topic, payload)
