"""Inventory leakage workflow chains — P2-B7 (#380).

Parameters are resolved from Inventory Search and prior chain steps when not
supplied directly (FBS replenish / clear-excess paths only).
"""

from __future__ import annotations

from typing import Any

from juli_backend.integrations.tiktok.factories import SandboxWriteResources


def _first_inventory_match(search_result: dict[str, Any]) -> tuple[str, str]:
    for row in search_result.get("inventory") or []:
        product_id = row.get("product_id")
        if not product_id:
            continue
        for sku in row.get("skus") or []:
            sku_id = sku.get("id")
            if sku_id:
                return str(product_id), str(sku_id)
    raise ValueError("inventory search returned no matching product_id/sku_id")


def _resolve_product_sku(
    resources: SandboxWriteResources,
    payload: dict[str, Any],
) -> tuple[str, str]:
    product_id = payload.get("product_id")
    sku_id = payload.get("sku_id")
    if product_id and sku_id:
        return str(product_id), str(sku_id)

    sku_ids = payload.get("sku_ids")
    if not sku_ids:
        raise ValueError("replenish/clear_excess requires product_id+sku_id or sku_ids")

    search_result = resources.inventory.search(
        sku_ids=[str(value) for value in sku_ids],
    )
    return _first_inventory_match(search_result)


def run_replenish_inventory_chain(
    resources: SandboxWriteResources,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Workflow 3 (FBS): Inventory Search → Update Inventory."""
    product_id, sku_id = _resolve_product_sku(resources, payload)
    quantity = int(payload["quantity"])
    warehouse_id = payload.get("warehouse_id")

    api_result = resources.inventory.update(
        product_id=product_id,
        sku_id=sku_id,
        quantity=quantity,
        warehouse_id=str(warehouse_id) if warehouse_id is not None else None,
    )

    return {
        "tool_name": "inventory.replenish",
        "product_id": product_id,
        "sku_id": sku_id,
        "quantity": quantity,
        "api_result": api_result,
    }


def run_clear_excess_inventory_chain(
    resources: SandboxWriteResources,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Workflow 4: search → price markdown → promotion → zero floor stock (FBS)."""
    product_id, sku_id = _resolve_product_sku(resources, payload)
    warehouse_id = payload.get("warehouse_id")

    price_update = payload.get("price_update")
    if price_update:
        resources.products.update_prices(product_id=product_id, body=price_update)

    activity_id = payload.get("activity_id")
    activity_body = payload.get("activity")
    if not activity_id and activity_body:
        created = resources.promotion.create_activity(body=activity_body)
        activity_id = str(created.get("activity_id") or "")

    products = payload.get("products")
    if activity_id and products:
        resources.promotion.update_activity_products(
            activity_id=activity_id,
            body={"products": products},
        )

    target_quantity = int(payload.get("target_quantity", 0))
    api_result = resources.inventory.update(
        product_id=product_id,
        sku_id=sku_id,
        quantity=target_quantity,
        warehouse_id=str(warehouse_id) if warehouse_id is not None else None,
    )

    return {
        "tool_name": "inventory.clear_excess",
        "product_id": product_id,
        "sku_id": sku_id,
        "activity_id": activity_id,
        "target_quantity": target_quantity,
        "api_result": api_result,
    }
