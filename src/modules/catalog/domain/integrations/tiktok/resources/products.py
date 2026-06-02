"""TikTok Shop Products resource — thin wrapper over TikTokClient."""

from __future__ import annotations

from typing import Optional

from src.modules.catalog.domain.integrations.tiktok.client import TikTokClient
from src.modules.catalog.domain.integrations.tiktok.resources import strip_nones


class ProductsResource:
    """Search, paginate, and fetch product details from TikTok Shop."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def search(
        self,
        *,
        status: Optional[str] = None,
        update_time_from: Optional[int] = None,
        update_time_to: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> dict:
        body = strip_nones({
            "status": status,
            "update_time_from": update_time_from,
            "update_time_to": update_time_to,
            "page_size": page_size,
        })
        return self._client.post("/api/products/search", body=body)

    def search_all(
        self,
        *,
        status: Optional[str] = None,
        update_time_from: Optional[int] = None,
        update_time_to: Optional[int] = None,
        page_size: int = 50,
    ) -> list[dict]:
        body = strip_nones({
            "status": status,
            "update_time_from": update_time_from,
            "update_time_to": update_time_to,
        })
        return self._client.get_all_pages(
            path="/api/products/search",
            body=body,
            items_key="products",
            page_size=page_size,
        )

    def get_details(self, product_id: str) -> dict:
        return self._client.get(
            "/api/products/details",
            params={"product_id": product_id},
        )
