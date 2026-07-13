"""TikTok Shop Products resource — thin wrapper over TikTokClient."""

from __future__ import annotations

from typing import Any

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    PRODUCT_BRANDS_PATH,
    PRODUCT_CATEGORIES_PATH,
    PRODUCT_CREATE_PATH,
    PRODUCT_FILE_UPLOAD_PATH,
    PRODUCT_IMAGE_UPLOAD_PATH,
    PRODUCT_PREREQUISITES_PATH,
    PRODUCT_SEARCH_PATH,
    PRODUCT_SEO_WORDS_PATH,
    PRODUCT_SUGGESTIONS_PATH,
    category_attributes_path,
    product_detail_path,
    product_edit_path,
    product_prices_update_path,
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

    def get_categories(self) -> dict:
        """List product categories (contract-collection.md §A-21)."""
        return self._client.get(PRODUCT_CATEGORIES_PATH)

    def check_listing_prerequisites(self, *, category_id: str) -> dict:
        """Verify seller/category eligibility (contract-collection.md §A-22)."""
        return self._client.get(
            PRODUCT_PREREQUISITES_PATH,
            params={"category_id": category_id},
        )

    def get_category_attributes(self, *, category_id: str) -> dict:
        """Fetch category attributes (contract-collection.md §A-9)."""
        return self._client.get(category_attributes_path(category_id))

    def get_brands(
        self,
        *,
        category_id: str,
        brand_name: str | None = None,
        page_size: int = 100,
        page_token: str | None = None,
    ) -> dict:
        """Resolve brand_id when required (contract-collection.md §A-22a)."""
        params = strip_nones({
            "category_id": category_id,
            "category_version": "v1",
            "is_authorized": "false",
            "brand_name": brand_name,
            "page_size": str(page_size),
            "page_token": page_token,
        })
        return self._client.get(PRODUCT_BRANDS_PATH, params=params)

    def get_seo_words(self, *, product_ids: list[str]) -> dict:
        """Fetch SEO word suggestions (contract-collection.md §A-23)."""
        return self._client.get(
            PRODUCT_SEO_WORDS_PATH,
            params={"product_ids": ",".join(product_ids)},
        )

    def get_suggestions(self, *, product_ids: list[str]) -> dict:
        """Fetch title/description suggestions (contract-collection.md §A-24)."""
        return self._client.get(
            PRODUCT_SUGGESTIONS_PATH,
            params={"product_ids": ",".join(product_ids)},
        )

    def upload_product_image(
        self,
        *,
        image_bytes: bytes,
        filename: str = "product-image.png",
        use_case: str = "MAIN_IMAGE",
    ) -> dict:
        """Upload listing image (contract-collection.md §B-2)."""
        return self._client.post_multipart(
            PRODUCT_IMAGE_UPLOAD_PATH,
            files={"data": (filename, image_bytes, "application/octet-stream")},
            data={"use_case": use_case},
        )

    def upload_product_file(
        self,
        *,
        file_bytes: bytes,
        filename: str,
    ) -> dict:
        """Upload supporting document (contract-collection.md §B-2a)."""
        return self._client.post_multipart(
            PRODUCT_FILE_UPLOAD_PATH,
            files={"data": (filename, file_bytes, "application/octet-stream")},
            data={"name": filename},
        )

    def update_prices(self, *, product_id: str, body: dict[str, Any]) -> dict:
        """Update SKU prices (contract-collection.md §B-20)."""
        return self._client.post(product_prices_update_path(product_id), body=body)
