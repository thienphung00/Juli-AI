"""TikTok Shop Products resource — thin wrapper over TikTokClient."""

from __future__ import annotations

from typing import Optional

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    PRODUCT_SEARCH_PATH,
    product_detail_path,
)
from juli_backend.integrations.tiktok.resources import strip_nones


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
        page_token: Optional[str] = None,
    ) -> dict:
        body = strip_nones({"status": status})
        params = strip_nones({
            "page_size": str(page_size) if page_size is not None else None,
            "page_token": page_token,
        })
        if update_time_from is not None:
            body["update_time_ge"] = update_time_from
        if update_time_to is not None:
            body["update_time_lt"] = update_time_to
        return self._client.post(PRODUCT_SEARCH_PATH, body=body, params=params)

    def search_all(
        self,
        *,
        status: Optional[str] = None,
        update_time_from: Optional[int] = None,
        update_time_to: Optional[int] = None,
        page_size: int = 50,
    ) -> list[dict]:
        body = strip_nones({"status": status})
        if update_time_from is not None:
            body["update_time_ge"] = update_time_from
        if update_time_to is not None:
            body["update_time_lt"] = update_time_to
        return self._client.get_all_pages(
            path=PRODUCT_SEARCH_PATH,
            body=body,
            items_key="products",
            page_size=page_size,
        )

    def get_details(self, product_id: str) -> dict:
        return self._client.get(product_detail_path(product_id))
