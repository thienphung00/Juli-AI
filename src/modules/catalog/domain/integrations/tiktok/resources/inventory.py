"""Product API inventory operations — thin wrapper over TikTokClient.

Inventory search and update are documented under the Product API in Partner Center
(https://partner.tiktokshop.com/docv2/page/products-api-overview), not a separate
Inventory API family.
"""

from __future__ import annotations

from typing import Optional

from src.modules.catalog.domain.integrations.tiktok.client import TikTokClient
from src.modules.catalog.domain.integrations.tiktok.constants import (
    INVENTORY_SEARCH_PATH,
    product_inventory_update_path,
)
from src.modules.catalog.domain.integrations.tiktok.resources import strip_nones


class InventoryResource:
    """Search and update SKU inventory via Product API endpoints."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def search(
        self,
        *,
        sku_ids: Optional[list[str]] = None,
    ) -> dict:
        body = strip_nones({
            "sku_ids": sku_ids,
        })
        return self._client.post(INVENTORY_SEARCH_PATH, body=body)

    def update(
        self,
        *,
        product_id: str,
        sku_id: str,
        warehouse_id: str,
        quantity: int,
    ) -> dict:
        return self._client.post(
            product_inventory_update_path(product_id),
            body={
                "skus": [
                    {
                        "id": sku_id,
                        "inventory": [
                            {
                                "warehouse_id": warehouse_id,
                                "quantity": quantity,
                            }
                        ],
                    }
                ]
            },
        )
