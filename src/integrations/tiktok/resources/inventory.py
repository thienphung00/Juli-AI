"""TikTok Shop Inventory resource — thin wrapper over TikTokClient."""

from __future__ import annotations

from typing import Optional

from src.integrations.tiktok.client import TikTokClient
from src.integrations.tiktok.resources import strip_nones


class InventoryResource:
    """Query and update inventory levels on TikTok Shop."""

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
        return self._client.post("/api/inventory/search", body=body)

    def update(
        self,
        *,
        sku_id: str,
        warehouse_id: str,
        quantity: int,
    ) -> dict:
        return self._client.post(
            "/api/inventory/update",
            body={
                "sku_id": sku_id,
                "warehouse_id": warehouse_id,
                "available_quantity": quantity,
            },
        )
