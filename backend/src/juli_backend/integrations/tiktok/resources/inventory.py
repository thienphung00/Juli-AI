"""Product API inventory operations — thin wrapper over TikTokClient.

Inventory search and update are documented under the Product API in Partner Center
(https://partner.tiktokshop.com/docv2/page/products-api-overview), not a separate
Inventory API family.
"""

from __future__ import annotations

from typing import Any

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    INVENTORY_SEARCH_PATH,
    product_inventory_update_path,
)
from juli_backend.integrations.tiktok.resources import strip_nones


class InventoryResource:
    """Search and update SKU inventory via Product API endpoints."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def search(
        self,
        *,
        product_ids: list[str] | None = None,
        sku_ids: list[str] | None = None,
    ) -> dict:
        """Search Inventory (Product API §A-8).

        ``product_ids`` is required by the live endpoint (#1948) -- a call
        without it fails vendor-side with ``[12019008] Invalid Parameter``.
        Kept optional here (not enforced at this layer) only because
        ``services/execution/inventory_leakage.py`` still calls this with
        ``sku_ids`` alone; every caller that owns its own product-id list
        (``sync_inventory``) always supplies ``product_ids``.
        """
        body = strip_nones(
            {
                "product_ids": product_ids,
                "sku_ids": sku_ids,
            }
        )
        return self._client.post(INVENTORY_SEARCH_PATH, body=body)

    def update(
        self,
        *,
        product_id: str,
        sku_id: str,
        quantity: int,
        warehouse_id: str | None = None,
    ) -> dict:
        inventory_entry: dict[str, Any] = {"quantity": quantity}
        if warehouse_id is not None:
            inventory_entry["warehouse_id"] = warehouse_id
        return self._client.post(
            product_inventory_update_path(product_id),
            body={
                "skus": [
                    {
                        "id": sku_id,
                        "inventory": [inventory_entry],
                    }
                ]
            },
        )
