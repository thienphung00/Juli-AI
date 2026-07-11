"""Vendor → ingest field mapping for TikTok Shop Partner API responses."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def _nested_amount(payment: Any) -> Any:
    if not isinstance(payment, dict):
        return None
    return payment.get("total_amount") or payment.get("payment_amount")


def _nested_refund_total(refund: Any) -> Any:
    if isinstance(refund, dict):
        return refund.get("refund_total") or refund.get("total_amount")
    return refund


def normalize_order(raw: dict[str, Any]) -> dict[str, Any]:
    """Map official TikTok order JSON to the ETL ingest contract."""
    result = dict(raw)

    if not result.get("order_id"):
        order_id = result.get("id")
        if order_id is not None:
            result["order_id"] = order_id

    if not result.get("buyer_id"):
        buyer_id = result.get("user_id")
        if buyer_id is not None:
            result["buyer_id"] = buyer_id

    status = result.get("order_status") or result.get("status")
    if status is not None:
        result["order_status"] = status
        result.setdefault("status", status)

    if result.get("total_amount") is None:
        amount = _nested_amount(result.get("payment"))
        if amount is not None:
            result["total_amount"] = amount

    if result.get("currency") is None:
        payment = result.get("payment")
        if isinstance(payment, dict) and payment.get("currency") is not None:
            result["currency"] = payment["currency"]

    if result.get("is_seller_fault") is None:
        initiator = result.get("cancellation_initiator")
        if initiator is not None and str(status or "").upper() == "CANCELLED":
            result["is_seller_fault"] = str(initiator).upper() == "SELLER"

    return result


def expand_order_line_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten ``line_items[]`` from an order into ingest-ready payloads."""
    tiktok_order_id = str(order.get("order_id") or order.get("id") or "")
    if not tiktok_order_id:
        return []

    update_time = order.get("update_time")
    items: list[dict[str, Any]] = []
    for line in order.get("line_items") or []:
        if not isinstance(line, dict):
            continue
        sku_id = line.get("sku_id")
        if not sku_id:
            continue
        unit_price = line.get("sale_price") or line.get("unit_price") or 0
        quantity_raw = line.get("quantity")
        if quantity_raw is None:
            quantity = 1
        else:
            try:
                quantity = int(quantity_raw)
            except (TypeError, ValueError):
                quantity = 1
        try:
            line_total = Decimal(str(unit_price)) * quantity
        except (TypeError, ValueError):
            line_total = Decimal("0")
        items.append({
            "tiktok_order_id": tiktok_order_id,
            "product_id": line.get("product_id"),
            "sku_id": str(sku_id),
            "quantity": quantity,
            "unit_price": unit_price,
            "line_total": str(line_total),
            "update_time": update_time,
        })
    return items


def normalize_product(raw: dict[str, Any]) -> dict[str, Any]:
    """Map versioned product JSON to the ETL ingest contract."""
    result = dict(raw)

    if not result.get("product_id"):
        product_id = result.get("id")
        if product_id is not None:
            result["product_id"] = product_id

    audit = result.get("audit")
    if isinstance(audit, dict) and audit.get("status") and not result.get("status"):
        result["status"] = audit["status"]

    if not result.get("name"):
        title = result.get("title")
        if title is not None:
            result["name"] = title

    if not result.get("title") and result.get("name"):
        result["title"] = result["name"]

    if result.get("price") is None or result.get("inventory") is None:
        sku = _first_dict(result.get("skus"))
        if sku is not None:
            if result.get("price") is None:
                price = _extract_sku_price(sku)
                if price is not None:
                    result["price"] = price
            if result.get("price_currency") is None:
                currency = _extract_sku_currency(sku)
                if currency is not None:
                    result["price_currency"] = currency
            if result.get("inventory") is None:
                inventory = _sum_sku_inventory(sku)
                if inventory is not None:
                    result["inventory"] = inventory

    if result.get("price_currency") is None:
        result["price_currency"] = "VND"

    return result


def _first_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    if isinstance(value, dict):
        return value
    return None


def _extract_sku_price(sku: dict[str, Any]) -> Any:
    price = sku.get("price")
    if isinstance(price, dict):
        return (
            price.get("sale_price")
            or price.get("list_price")
            or price.get("original_price")
            or price.get("amount")
        )
    return price


def _extract_sku_currency(sku: dict[str, Any]) -> Any:
    price = sku.get("price")
    if isinstance(price, dict):
        return price.get("currency")
    return sku.get("currency")


def _sum_sku_inventory(sku: dict[str, Any]) -> int | None:
    inventory = sku.get("inventory")
    if isinstance(inventory, list):
        total = 0
        seen = False
        for row in inventory:
            if not isinstance(row, dict):
                continue
            quantity = row.get("quantity") or row.get("available_quantity")
            if quantity is None:
                continue
            total += int(quantity)
            seen = True
        return total if seen else None
    if isinstance(inventory, dict):
        quantity = inventory.get("quantity") or inventory.get("available_quantity")
        return int(quantity) if quantity is not None else None
    return int(inventory) if inventory is not None else None


def derive_return_type(
    *,
    return_condition: str | None,
    api_return_type: str | None = None,
) -> str:
    """Map API inspection fields to canonical return_type enum."""
    condition = (return_condition or "").lower()
    if condition in ("wrong_item",):
        return "item_swap"
    if condition in ("empty_parcel",):
        return "empty_return"
    if api_return_type and str(api_return_type).upper() == "REPLACEMENT":
        return "item_swap"
    return "other"


def derive_return_condition(raw: dict[str, Any]) -> str:
    explicit = raw.get("return_condition")
    if explicit:
        return str(explicit)
    return "unknown"


def normalize_return(raw: dict[str, Any]) -> dict[str, Any]:
    """Map official TikTok return JSON to the ETL ingest contract."""
    result = dict(raw)

    if not result.get("return_id"):
        return_id = result.get("id")
        if return_id is not None:
            result["return_id"] = return_id

    tiktok_order_id = result.get("tiktok_order_id") or result.get("order_id")
    if tiktok_order_id is not None:
        result["tiktok_order_id"] = str(tiktok_order_id)
        result.setdefault("order_id", str(tiktok_order_id))

    if not result.get("buyer_id"):
        buyer_id = result.get("user_id")
        if buyer_id is not None:
            result["buyer_id"] = buyer_id

    if result.get("refund_amount") is None:
        refund_total = _nested_refund_total(result.get("refund"))
        if refund_total is not None:
            result["refund_amount"] = refund_total

    line_items = result.get("return_line_items") or []
    if line_items and isinstance(line_items[0], dict):
        first = line_items[0]
        result.setdefault("sku_id", first.get("sku_id"))
        result.setdefault("product_id", first.get("product_id"))

    if not result.get("return_reason"):
        reason = result.get("return_reason_text")
        if reason is not None:
            result["return_reason"] = reason

    api_return_type = result.get("return_type")
    condition = derive_return_condition(result)
    result["return_condition"] = condition
    result["return_type"] = derive_return_type(
        return_condition=condition,
        api_return_type=str(api_return_type) if api_return_type else None,
    )

    return result


def normalize_creator(raw: dict[str, Any]) -> dict[str, Any]:
    """Map marketplace creator JSON to the ETL ingest contract."""
    result = dict(raw)

    if not result.get("creator_id"):
        creator_id = result.get("creator_user_id") or result.get("id")
        if creator_id is not None:
            result["creator_id"] = creator_id

    if not result.get("name"):
        name = result.get("nickname") or result.get("display_name")
        if name is not None:
            result["name"] = name

    return result


def normalize_livestream(raw: dict[str, Any]) -> dict[str, Any]:
    """Map creator content detail JSON to the livestream ingest contract."""
    result = dict(raw)

    if not result.get("livestream_id"):
        livestream_id = (
            result.get("room_id")
            or result.get("content_id")
            or result.get("id")
        )
        if livestream_id is not None:
            result["livestream_id"] = livestream_id

    if result.get("viewer_count") is None:
        viewers = result.get("total_viewers") or result.get("total_views")
        if viewers is not None:
            result["viewer_count"] = viewers

    if result.get("order_count") is None:
        orders = result.get("orders_placed")
        if orders is not None:
            result["order_count"] = orders

    if result.get("revenue") is None:
        revenue = result.get("total_sale_gmv") or result.get("total_sale_gmv_amt")
        if revenue is not None:
            result["revenue"] = revenue

    if result.get("update_time") is None:
        update_time = result.get("end_time") or result.get("create_time")
        if update_time is not None:
            result["update_time"] = update_time

    return result


def normalize_statement(raw: dict[str, Any]) -> dict[str, Any]:
    """Map finance statement JSON to the settlement ingest contract."""
    result = dict(raw)

    if not result.get("settlement_id"):
        settlement_id = result.get("statement_id") or result.get("id")
        if settlement_id is not None:
            result["settlement_id"] = settlement_id

    if result.get("amount") is None:
        amount = (
            result.get("settlement_amount")
            or result.get("revenue_amount")
            or result.get("net_sales")
            or result.get("total_amount")
        )
        if amount is not None:
            result["amount"] = amount

    if result.get("settlement_time") is None:
        statement_time = result.get("statement_time")
        if statement_time is not None:
            result["settlement_time"] = statement_time

    if result.get("update_time") is None:
        update_time = result.get("statement_time")
        if update_time is not None:
            result["update_time"] = update_time

    if not result.get("status"):
        status = result.get("payment_status")
        if status is not None:
            result["status"] = status

    return result
