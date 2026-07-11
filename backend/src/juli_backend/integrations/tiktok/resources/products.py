"""TikTok Shop Products resource — thin wrapper over TikTokClient."""

from __future__ import annotations

from typing import Any

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    PRODUCT_CREATE_PATH,
    PRODUCT_SEARCH_PATH,
    product_detail_path,
    product_edit_path,
)
from juli_backend.integrations.tiktok.resources import strip_nones
from juli_backend.integrations.tiktok.schemas import (
    ProductsSearchData,
    TikTokProduct,
    coerce_model,
)


class ProductsResource:
    """Search, paginate, and fetch product details from TikTok Shop."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def search(
        self,
        *,
        status: str | None = None,
        update_time_from: int | None = None,
        update_time_to: int | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
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
        parsed = coerce_model(
            ProductsSearchData,
            self._client.post(
                PRODUCT_SEARCH_PATH,
                body=body,
                params=params,
                response_model=ProductsSearchData,
            ),
        )
        return parsed.model_dump()

    def search_all(
        self,
        *,
        status: str | None = None,
        update_time_from: int | None = None,
        update_time_to: int | None = None,
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
        parsed = coerce_model(
            TikTokProduct,
            self._client.get(
                product_detail_path(product_id),
                response_model=TikTokProduct,
            ),
        )
        return parsed.model_dump()

    def create(self, *, body: dict[str, Any]) -> dict:
        """Create a product (Layer 2 sandbox write — contract-collection.md §17)."""
        return self._client.post(PRODUCT_CREATE_PATH, body=body)

    def edit(self, *, product_id: str, body: dict[str, Any]) -> dict:
        """Partial edit a product (Layer 2 sandbox write — contract-collection.md §18)."""
        return self._client.put(product_edit_path(product_id), body=body)
