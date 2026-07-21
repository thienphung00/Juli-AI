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

    if isinstance(result.get("refund_amount"), dict):
        refund_total = _nested_refund_total(result.get("refund_amount"))
        if refund_total is not None:
            result["refund_amount"] = refund_total
    elif result.get("refund_amount") is None:
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


def expand_inventory_search(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten Search Inventory nested ``inventory[] → skus[]`` into ETL rows."""
    data = raw.get("data") if isinstance(raw.get("data"), dict) else None
    inventory = (
        data.get("inventory")
        if data is not None
        else raw.get("inventory")
    )
    if not isinstance(inventory, list):
        return []

    rows: list[dict[str, Any]] = []
    for product in inventory:
        if not isinstance(product, dict):
            continue
        product_id = product.get("product_id")
        skus = product.get("skus")
        if not isinstance(skus, list):
            continue
        for sku in skus:
            if not isinstance(sku, dict):
                continue
            warehouse_id = None
            warehouses = sku.get("warehouse_inventory")
            if isinstance(warehouses, list):
                for warehouse in warehouses:
                    if isinstance(warehouse, dict) and warehouse.get("warehouse_id"):
                        warehouse_id = warehouse.get("warehouse_id")
                        break
            rows.append(
                {
                    "sku_id": sku.get("id") or sku.get("sku_id"),
                    "product_id": product_id,
                    "available_quantity": (
                        sku.get("total_available_quantity")
                        if sku.get("total_available_quantity") is not None
                        else sku.get("available_quantity")
                    ),
                    "warehouse_id": warehouse_id,
                    "seller_sku": sku.get("seller_sku"),
                }
            )
    return rows


def normalize_inventory(raw: dict[str, Any]) -> dict[str, Any]:
    """Map Search Inventory flat rows or #68 webhook snapshots to ETL contract."""
    result = dict(raw)

    if not result.get("sku_id"):
        sku_id = result.get("id")
        if sku_id is not None:
            result["sku_id"] = sku_id

    snapshot = result.get("quantity_snapshot_after_change")
    if isinstance(snapshot, dict):
        if result.get("available_quantity") is None:
            qty = snapshot.get("total_available_quantity")
            if qty is None:
                qty = snapshot.get("total_quantity")
            if qty is not None:
                result["available_quantity"] = qty
        if result.get("quantity") is None and result.get("available_quantity") is not None:
            result["quantity"] = result["available_quantity"]

    if result.get("available_quantity") is None and result.get("quantity") is not None:
        result["available_quantity"] = result["quantity"]

    if not result.get("product_id"):
        product_id = result.get("tiktok_product_id")
        if product_id is not None:
            result["product_id"] = product_id

    return result


# ---------------------------------------------------------------------------
# Analytics performance normalizers (#425)
# ---------------------------------------------------------------------------


def analytics_snapshot_key(
    *,
    grain: str,
    start_date: str,
    end_date: str | None = None,
    hour_index: int | None = None,
    product_id: str | None = None,
    sku_id: str | None = None,
    live_id: str | None = None,
) -> str:
    """Deterministic idempotency key: shop + grain + date window + entity ids."""
    return "|".join(
        [
            grain,
            start_date,
            end_date or "",
            str(hour_index) if hour_index is not None else "",
            product_id or "",
            sku_id or "",
            live_id or "",
        ]
    )


def _extract_gmv(value: Any) -> tuple[Any, Any]:
    if not isinstance(value, dict):
        return None, None
    target = value.get("overall") if isinstance(value.get("overall"), dict) else value
    amount = target.get("amount")
    if amount is None:
        return None, None
    currency = target.get("currency")
    return amount, currency


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_rate(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip().rstrip("%")
        return cleaned or None
    return value


def _base_analytics_payload(
    *,
    grain: str,
    start_date: str,
    end_date: str | None,
    synced_at: int,
    product_id: str | None = None,
    sku_id: str | None = None,
    live_id: str | None = None,
    hour_index: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "grain": grain,
        "start_date": start_date,
        "update_time": synced_at,
        "snapshot_key": analytics_snapshot_key(
            grain=grain,
            start_date=start_date,
            end_date=end_date,
            hour_index=hour_index,
            product_id=product_id,
            sku_id=sku_id,
            live_id=live_id,
        ),
    }
    if end_date:
        payload["end_date"] = end_date
    if product_id:
        payload["product_id"] = str(product_id)
    if sku_id:
        payload["sku_id"] = str(sku_id)
    if live_id:
        payload["live_id"] = str(live_id)
    if hour_index is not None:
        payload["hour_index"] = hour_index
    return payload


def _merge_metrics(payload: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    for key, value in metrics.items():
        if value is not None:
            payload[key] = value
    return payload


def expand_analytics_shop_performance(
    data: dict[str, Any], *, synced_at: int
) -> list[dict[str, Any]]:
    performance = data.get("performance") if isinstance(data, dict) else None
    intervals = performance.get("intervals") if isinstance(performance, dict) else None
    if not isinstance(intervals, list):
        return []

    rows: list[dict[str, Any]] = []
    for interval in intervals:
        if not isinstance(interval, dict):
            continue
        start_date = interval.get("start_date")
        if not start_date:
            continue
        end_date = interval.get("end_date")
        sales = interval.get("sales") if isinstance(interval.get("sales"), dict) else {}
        traffic = (
            interval.get("traffic") if isinstance(interval.get("traffic"), dict) else {}
        )
        gmv_amount, gmv_currency = _extract_gmv(sales.get("gmv"))
        payload = _base_analytics_payload(
            grain="shop",
            start_date=str(start_date),
            end_date=str(end_date) if end_date else None,
            synced_at=synced_at,
        )
        _merge_metrics(
            payload,
            {
                "gmv": gmv_amount,
                "gmv_currency": gmv_currency,
                "orders_count": _optional_int(sales.get("orders_count")),
                "sku_orders": _optional_int(sales.get("sku_orders_count")),
                "items_sold": _optional_int(sales.get("items_sold")),
                "visitors": _optional_int(traffic.get("avg_visitors")),
                "conversion_rate": _optional_rate(traffic.get("avg_conversation_rate")),
            },
        )
        rows.append(payload)
    return rows


def expand_analytics_shop_performance_per_hour(
    data: dict[str, Any], *, date: str, synced_at: int
) -> list[dict[str, Any]]:
    performance = data.get("performance") if isinstance(data, dict) else None
    intervals = performance.get("intervals") if isinstance(performance, dict) else None
    if not isinstance(intervals, list):
        return []

    rows: list[dict[str, Any]] = []
    for interval in intervals:
        if not isinstance(interval, dict):
            continue
        hour_index = _optional_int(interval.get("index"))
        if hour_index is None:
            continue
        gmv_amount, gmv_currency = _extract_gmv(interval.get("gmv"))
        payload = _base_analytics_payload(
            grain="shop",
            start_date=date,
            end_date=None,
            synced_at=synced_at,
            hour_index=hour_index,
        )
        _merge_metrics(
            payload,
            {
                "gmv": gmv_amount,
                "gmv_currency": gmv_currency,
                "items_sold": _optional_int(interval.get("items_sold")),
                "visitors": _optional_int(interval.get("visitors")),
                "customers": _optional_int(interval.get("customers")),
            },
        )
        rows.append(payload)
    return rows


def expand_analytics_sku_list_item(
    item: dict[str, Any],
    *,
    start_date: str,
    end_date: str,
    synced_at: int,
) -> dict[str, Any] | None:
    sku_id = item.get("id") or item.get("sku_id")
    if not sku_id:
        return None
    gmv_amount, gmv_currency = _extract_gmv(item.get("gmv"))
    payload = _base_analytics_payload(
        grain="sku",
        start_date=start_date,
        end_date=end_date,
        synced_at=synced_at,
        sku_id=str(sku_id),
        product_id=str(item["product_id"]) if item.get("product_id") else None,
    )
    return _merge_metrics(
        payload,
        {
            "gmv": gmv_amount,
            "gmv_currency": gmv_currency,
            "sku_orders": _optional_int(item.get("sku_orders")),
            "items_sold": _optional_int(item.get("units_sold") or item.get("items_sold")),
        },
    )


def expand_analytics_sku_detail(
    data: dict[str, Any], *, synced_at: int
) -> list[dict[str, Any]]:
    performance = data.get("performance") if isinstance(data, dict) else None
    if not isinstance(performance, dict):
        return []
    sku_id = performance.get("sku_id") or performance.get("id")
    product_id = performance.get("product_id")
    intervals = performance.get("intervals")
    if not isinstance(intervals, list):
        return []

    rows: list[dict[str, Any]] = []
    for interval in intervals:
        if not isinstance(interval, dict):
            continue
        start_date = interval.get("start_date")
        if not start_date:
            continue
        end_date = interval.get("end_date")
        gmv_amount, gmv_currency = _extract_gmv(interval.get("gmv"))
        payload = _base_analytics_payload(
            grain="sku",
            start_date=str(start_date),
            end_date=str(end_date) if end_date else None,
            synced_at=synced_at,
            sku_id=str(sku_id) if sku_id else None,
            product_id=str(product_id) if product_id else None,
        )
        _merge_metrics(
            payload,
            {
                "gmv": gmv_amount,
                "gmv_currency": gmv_currency,
                "sku_orders": _optional_int(interval.get("sku_orders")),
                "items_sold": _optional_int(interval.get("items_sold")),
            },
        )
        rows.append(payload)
    return rows


def expand_analytics_product_list_item(
    item: dict[str, Any],
    *,
    start_date: str,
    end_date: str,
    synced_at: int,
) -> dict[str, Any] | None:
    product_id = item.get("id") or item.get("product_id")
    if not product_id:
        return None
    total = item.get("total_performance")
    if not isinstance(total, dict):
        return None
    gmv_amount, gmv_currency = _extract_gmv(total.get("gmv"))
    payload = _base_analytics_payload(
        grain="product",
        start_date=start_date,
        end_date=end_date,
        synced_at=synced_at,
        product_id=str(product_id),
    )
    return _merge_metrics(
        payload,
        {
            "gmv": gmv_amount,
            "gmv_currency": gmv_currency,
            "orders_count": _optional_int(total.get("orders")),
            "sku_orders": _optional_int(total.get("sku_orders")),
            "items_sold": _optional_int(total.get("items_sold")),
            "customers": _optional_int(total.get("estimated_customers")),
            "ctr": _optional_rate(total.get("ctr")),
            "click_order_rate": _optional_rate(total.get("click_order_rate")),
        },
    )


def expand_analytics_product_detail(
    data: dict[str, Any], *, synced_at: int, product_id: str | None = None
) -> list[dict[str, Any]]:
    performance = data.get("performance") if isinstance(data, dict) else None
    intervals = performance.get("intervals") if isinstance(performance, dict) else None
    if not isinstance(intervals, list):
        return []

    resolved_product_id = product_id
    if resolved_product_id is None and isinstance(performance, dict):
        raw_product_id = performance.get("product_id")
        if raw_product_id:
            resolved_product_id = str(raw_product_id)

    rows: list[dict[str, Any]] = []
    for interval in intervals:
        if not isinstance(interval, dict):
            continue
        start_date = interval.get("start_date")
        if not start_date:
            continue
        end_date = interval.get("end_date")
        sales = interval.get("sales") if isinstance(interval.get("sales"), dict) else {}
        traffic = (
            interval.get("traffic") if isinstance(interval.get("traffic"), dict) else {}
        )
        gmv_amount, gmv_currency = _extract_gmv(sales.get("gmv"))
        ctr = None
        traffic_breakdowns = traffic.get("breakdowns")
        if isinstance(traffic_breakdowns, list) and traffic_breakdowns:
            first = traffic_breakdowns[0]
            if isinstance(first, dict):
                nested = first.get("traffic")
                if isinstance(nested, dict):
                    ctr = _optional_rate(nested.get("ctr"))
        payload = _base_analytics_payload(
            grain="product",
            start_date=str(start_date),
            end_date=str(end_date) if end_date else None,
            synced_at=synced_at,
            product_id=resolved_product_id,
        )
        _merge_metrics(
            payload,
            {
                "gmv": gmv_amount,
                "gmv_currency": gmv_currency,
                "orders_count": _optional_int(sales.get("orders")),
                "items_sold": _optional_int(sales.get("items_sold")),
                "ctr": ctr,
            },
        )
        rows.append(payload)
    return rows


def expand_analytics_live_session(
    session: dict[str, Any],
    *,
    start_date: str,
    end_date: str,
    synced_at: int,
) -> dict[str, Any] | None:
    live_id = session.get("id") or session.get("live_id")
    if not live_id:
        return None
    sales = (
        session.get("sales_performance")
        if isinstance(session.get("sales_performance"), dict)
        else {}
    )
    interaction = (
        session.get("interaction_performance")
        if isinstance(session.get("interaction_performance"), dict)
        else {}
    )
    gmv_amount, gmv_currency = _extract_gmv(sales.get("gmv"))
    payload = _base_analytics_payload(
        grain="live",
        start_date=start_date,
        end_date=end_date,
        synced_at=synced_at,
        live_id=str(live_id),
    )
    return _merge_metrics(
        payload,
        {
            "gmv": gmv_amount,
            "gmv_currency": gmv_currency,
            "sku_orders": _optional_int(sales.get("sku_orders")),
            "items_sold": _optional_int(sales.get("items_sold")),
            "customers": _optional_int(sales.get("customers")),
            "click_through_rate": _optional_rate(interaction.get("click_through_rate")),
            "click_to_order_rate": _optional_rate(sales.get("click_to_order_rate")),
            "impressions": _optional_int(interaction.get("product_impressions")),
            "visitors": _optional_int(interaction.get("viewers")),
        },
    )
