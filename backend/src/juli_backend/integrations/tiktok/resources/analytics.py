"""TikTok Shop Analytics resource — thin GET wrappers (contract-collection A-31–A-39).

Date-range queries use Partner API identifier catalog spellings:
``start_date_ge``, ``end_date_lt``, ``sku_id``, ``product_id``, ``date``, ``time_slot``.
LIVE A-26–A-29 are intentionally omitted (reference-tier only).
"""

from __future__ import annotations

from typing import Any

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_API_VERSION,
    ANALYTICS_BESTSELLING_API_VERSION,
    ANALYTICS_BESTSELLING_PRODUCTS_PATH,
    ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PER_HOUR_API_VERSION,
    ANALYTICS_SHOP_PRODUCTS_LIST_API_VERSION,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    analytics_shop_performance_per_hour_path,
    analytics_shop_product_performance_path,
    analytics_shop_sku_performance_path,
)
from juli_backend.integrations.tiktok.resources import strip_nones


class AnalyticsResource:
    """Fetch shop / product / SKU analytics with date windows and pagination."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def list_sku_performance(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """A-32 Get Shop SKU Performance List."""
        params = strip_nones({
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
            "page_size": str(page_size) if page_size is not None else None,
            "page_token": page_token,
        })
        return self._client.get(ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH, params=params)

    def list_sku_performance_all(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """A-32 paginated SKU performance list."""
        params = {
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
        }
        return self._client.get_all_pages_get(
            ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
            params=params,
            items_key="skus",
            page_size=page_size,
        )

    def get_sku_performance(
        self,
        *,
        sku_id: str,
        start_date_ge: str,
        end_date_lt: str,
    ) -> dict[str, Any]:
        """A-31 Get Shop SKU Performance Detail."""
        params = {
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
        }
        return self._client.get(
            analytics_shop_sku_performance_path(sku_id),
            params=params,
        )

    def list_product_performance(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """A-34 Get Shop Product Performance List."""
        params = strip_nones({
            "version": ANALYTICS_SHOP_PRODUCTS_LIST_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
            "page_size": str(page_size) if page_size is not None else None,
            "page_token": page_token,
        })
        return self._client.get(ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH, params=params)

    def list_product_performance_all(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """A-34 paginated product performance list."""
        params = {
            "version": ANALYTICS_SHOP_PRODUCTS_LIST_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
        }
        return self._client.get_all_pages_get(
            ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
            params=params,
            items_key="products",
            page_size=page_size,
        )

    def get_product_performance(
        self,
        *,
        product_id: str,
        start_date_ge: str,
        end_date_lt: str,
    ) -> dict[str, Any]:
        """A-33 Get Shop Product Performance Detail."""
        params = {
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
        }
        return self._client.get(
            analytics_shop_product_performance_path(product_id),
            params=params,
        )

    def get_shop_performance(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
    ) -> dict[str, Any]:
        """A-36 Get Shop Performance."""
        params = {
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
        }
        return self._client.get(ANALYTICS_SHOP_PERFORMANCE_PATH, params=params)

    def get_shop_performance_per_hour(self, *, date: str) -> dict[str, Any]:
        """A-37 Get Shop Performance Per Hour (`date` = YYYY-MM-DD)."""
        params = {"version": ANALYTICS_SHOP_PERFORMANCE_PER_HOUR_API_VERSION}
        return self._client.get(
            analytics_shop_performance_per_hour_path(date),
            params=params,
        )

    def get_bestselling_products(
        self,
        *,
        date: str,
        time_slot: str = "1D",
    ) -> dict[str, Any]:
        """A-38 Get Bestselling Products."""
        params = {
            "version": ANALYTICS_BESTSELLING_API_VERSION,
            "date": date,
            "time_slot": time_slot,
        }
        return self._client.get(ANALYTICS_BESTSELLING_PRODUCTS_PATH, params=params)

    def get_bestselling_videos(
        self,
        *,
        date: str,
        time_slot: str = "1D",
    ) -> dict[str, Any]:
        """A-39 Get Bestselling Videos."""
        params = {
            "version": ANALYTICS_BESTSELLING_API_VERSION,
            "date": date,
            "time_slot": time_slot,
        }
        return self._client.get(ANALYTICS_BESTSELLING_VIDEOS_PATH, params=params)

    def list_live_performance(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int | None = None,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """A-28 Get Shop LIVE Performance List."""
        params = strip_nones({
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
            "page_size": str(page_size) if page_size is not None else None,
            "page_token": page_token,
        })
        return self._client.get(ANALYTICS_LIVE_PERFORMANCE_LIST_PATH, params=params)

    def list_live_performance_all(
        self,
        *,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """A-28 paginated LIVE session list."""
        params = {
            "version": ANALYTICS_API_VERSION,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
        }
        return self._client.get_all_pages_get(
            ANALYTICS_LIVE_PERFORMANCE_LIST_PATH,
            params=params,
            items_key="live_stream_sessions",
            page_size=page_size,
        )
