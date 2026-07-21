"""TDD: AnalyticsResource date-window + pagination contracts (#424).

Fixtures are sanitized payloads from contract-collection.md §A-31–A-39, A-25.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from juli_backend.integrations.tiktok.constants import (
    ANALYTICS_API_VERSION,
    ANALYTICS_BESTSELLING_PRODUCTS_PATH,
    ANALYTICS_BESTSELLING_VIDEOS_PATH,
    ANALYTICS_SHOP_PERFORMANCE_PATH,
    ANALYTICS_SHOP_PRODUCTS_LIST_API_VERSION,
    ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH,
    ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
    analytics_shop_performance_per_hour_path,
    analytics_shop_product_performance_path,
    analytics_shop_sku_performance_path,
    promotion_activity_path,
)
from juli_backend.integrations.tiktok.resources.analytics import AnalyticsResource
from juli_backend.integrations.tiktok.resources.promotion import PromotionResource

# Sanitized contract-collection.md responses (data payload only — client returns data).
A31_SKU_DETAIL = {
    "latest_available_date": "2026-07-15",
    "performance": {
        "sku_id": "{sku_id}",
        "product_id": "{product_id}",
        "intervals": [
            {
                "start_date": "2026-07-13",
                "end_date": "2026-07-14",
                "gmv": {"amount": "0", "currency": "VND"},
                "sku_orders": 0,
                "items_sold": 0,
            }
        ],
    },
}

A32_SKU_LIST = {
    "latest_available_date": "2026-07-15",
    "next_page_token": "{page_token}",
    "skus": [
        {
            "id": "{sku_id}",
            "product_id": "{product_id}",
            "gmv": {"amount": "916678.00", "currency": "VND"},
            "sku_orders": 4,
            "units_sold": 4,
        }
    ],
    "total_count": 12,
}

A33_PRODUCT_DETAIL = {
    "latest_available_date": "2026-07-15",
    "performance": {
        "intervals": [
            {
                "start_date": "2026-07-13",
                "end_date": "2026-07-14",
                "sales": {
                    "gmv": {"amount": "1881780.00", "currency": "VND"},
                    "items_sold": 11,
                    "orders": 10,
                    "breakdowns": [
                        {
                            "content_type": "VIDEO",
                            "sales": {
                                "gmv": {"amount": "1292003.00", "currency": "VND"},
                                "items_sold": 8,
                            },
                        }
                    ],
                },
                "traffic": {
                    "breakdowns": [
                        {
                            "content_type": "VIDEO",
                            "traffic": {"impressions": 4060, "ctr": "0.05"},
                        }
                    ]
                },
            }
        ]
    },
}

A34_PRODUCT_LIST = {
    "latest_available_date": "2026-07-14",
    "next_page_token": "{page_token}",
    "products": [
        {
            "id": "{product_id}",
            "total_performance": {
                "gmv": {"amount": "2430217.00", "currency": "VND"},
                "orders": 9,
                "sku_orders": 10,
                "items_sold": 10,
                "estimated_customers": 6,
                "ctr": "0.0759",
                "click_order_rate": "0.1064",
            },
        }
    ],
    "total_count": 34,
}

A36_SHOP_PERFORMANCE = {
    "latest_available_date": "2026-07-14",
    "performance": {
        "intervals": [
            {
                "start_date": "2026-07-13",
                "end_date": "2026-07-14",
                "sales": {
                    "gmv": {
                        "overall": {"amount": "6408074.00", "currency": "VND"},
                        "breakdowns": [
                            {
                                "type": "LIVE",
                                "gmv": {"amount": "2110729.00", "currency": "VND"},
                            }
                        ],
                    },
                    "orders_count": 26,
                    "sku_orders_count": 29,
                    "items_sold": 32,
                },
                "traffic": {
                    "avg_visitors": 303,
                    "avg_page_views": 609,
                    "avg_conversation_rate": "0.0759",
                },
            }
        ]
    },
}

A37_PER_HOUR = {
    "performance": {
        "latest_available_timestamp": 1784192270,
        "overall": {
            "visitors": 303,
            "customers": 23,
            "gmv": {"amount": "6408074.00", "currency": "VND"},
            "items_sold": 32,
        },
        "intervals": [
            {
                "index": 12,
                "visitors": 38,
                "customers": 4,
                "gmv": {"amount": "661750.00", "currency": "VND"},
                "items_sold": 4,
            }
        ],
    }
}

A38_BESTSELLING_PRODUCTS = {
    "products": [
        {
            "id": "{product_id}",
            "name": "[PRODUCT_NAME]",
            "rank": 1,
            "gmv_range": "VND{min}~VND{max}",
            "rating": "4.8",
            "shop_id": "{shop_id}",
            "shop_name": "[SHOP_NAME]",
            "product_image": {
                "uri": "tos-alisg-i-aphluv4xwc-sg/{image_uri}",
                "thumb_urls": ["https://..."],
            },
        }
    ]
}

A39_BESTSELLING_VIDEOS = {
    "videos": [
        {
            "id": "{video_id}",
            "rank": 1,
            "duration": 29,
            "views": 1929879,
            "likes": 7092,
            "comments": 0,
            "shares": 3796,
            "gmv_range": "VND{min}~VND{max}",
            "nick_name": "[NICK_NAME]",
            "publish_time": 1783348436,
            "product_infos": [
                {
                    "product_id": "{product_id}",
                    "product_name": "[PRODUCT_NAME]",
                }
            ],
        }
    ]
}

A25_ACTIVITY = {
    "activity_id": "7136104329798256386",
    "title": "FlashSale 20230707",
    "activity_type": "FIXED_PRICE",
    "status": "ONGOING",
    "products": [
        {
            "id": "7136011254174631686",
            "skus": [{"id": "7136382541418366725", "discount": "10"}],
        }
    ],
}


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get.return_value = {}
    client.get_all_pages_get.return_value = []
    return client


class TestAnalyticsResourceDateWindowAndPagination:
    def test_list_sku_performance_sends_date_window(self, mock_client):
        mock_client.get.return_value = A32_SKU_LIST
        resource = AnalyticsResource(mock_client)

        result = resource.list_sku_performance(
            start_date_ge="2026-07-13",
            end_date_lt="2026-07-14",
            page_token="tok-1",
        )

        mock_client.get.assert_called_once()
        path, kwargs = mock_client.get.call_args[0][0], mock_client.get.call_args[1]
        assert path == ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH
        assert kwargs["params"]["start_date_ge"] == "2026-07-13"
        assert kwargs["params"]["end_date_lt"] == "2026-07-14"
        assert kwargs["params"]["page_token"] == "tok-1"
        assert result["skus"][0]["id"] == "{sku_id}"
        assert result["skus"][0]["product_id"] == "{product_id}"

    def test_list_sku_performance_all_paginates(self, mock_client):
        mock_client.get_all_pages_get.return_value = A32_SKU_LIST["skus"]
        resource = AnalyticsResource(mock_client)

        result = resource.list_sku_performance_all(
            start_date_ge="2026-07-13",
            end_date_lt="2026-07-14",
            page_size=20,
        )

        mock_client.get_all_pages_get.assert_called_once_with(
            ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH,
            params={
                "version": ANALYTICS_API_VERSION,
                "start_date_ge": "2026-07-13",
                "end_date_lt": "2026-07-14",
            },
            items_key="skus",
            page_size=20,
        )
        assert result[0]["product_id"] == "{product_id}"

    def test_get_sku_performance_detail_uses_sku_id_path(self, mock_client):
        mock_client.get.return_value = A31_SKU_DETAIL
        resource = AnalyticsResource(mock_client)
        sku_id = "1736404513645233795"

        result = resource.get_sku_performance(
            sku_id=sku_id,
            start_date_ge="2026-07-13",
            end_date_lt="2026-07-14",
        )

        path = mock_client.get.call_args[0][0]
        params = mock_client.get.call_args[1]["params"]
        assert path == analytics_shop_sku_performance_path(sku_id)
        assert params["start_date_ge"] == "2026-07-13"
        assert params["end_date_lt"] == "2026-07-14"
        assert result["performance"]["sku_id"] == "{sku_id}"
        assert result["performance"]["product_id"] == "{product_id}"

    def test_list_product_performance_sends_date_window(self, mock_client):
        mock_client.get.return_value = A34_PRODUCT_LIST
        resource = AnalyticsResource(mock_client)

        result = resource.list_product_performance(
            start_date_ge="2026-07-13",
            end_date_lt="2026-07-14",
        )

        path = mock_client.get.call_args[0][0]
        params = mock_client.get.call_args[1]["params"]
        assert path == ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH
        assert params["start_date_ge"] == "2026-07-13"
        assert params["end_date_lt"] == "2026-07-14"
        assert result["products"][0]["id"] == "{product_id}"

    def test_list_product_performance_all_paginates(self, mock_client):
        mock_client.get_all_pages_get.return_value = A34_PRODUCT_LIST["products"]
        resource = AnalyticsResource(mock_client)

        result = resource.list_product_performance_all(
            start_date_ge="2026-07-13",
            end_date_lt="2026-07-14",
        )

        call = mock_client.get_all_pages_get.call_args
        assert call[0][0] == ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH
        assert call[1]["items_key"] == "products"
        assert call[1]["params"]["version"] == ANALYTICS_SHOP_PRODUCTS_LIST_API_VERSION
        assert call[1]["params"]["start_date_ge"] == "2026-07-13"
        assert result[0]["id"] == "{product_id}"

    def test_get_product_performance_detail_uses_product_id_path(self, mock_client):
        mock_client.get.return_value = A33_PRODUCT_DETAIL
        resource = AnalyticsResource(mock_client)
        product_id = "1736363193934775939"

        result = resource.get_product_performance(
            product_id=product_id,
            start_date_ge="2026-07-13",
            end_date_lt="2026-07-14",
        )

        path = mock_client.get.call_args[0][0]
        assert path == analytics_shop_product_performance_path(product_id)
        assert result["performance"]["intervals"][0]["sales"]["items_sold"] == 11

    def test_get_shop_performance_sends_date_window(self, mock_client):
        mock_client.get.return_value = A36_SHOP_PERFORMANCE
        resource = AnalyticsResource(mock_client)

        result = resource.get_shop_performance(
            start_date_ge="2026-07-13",
            end_date_lt="2026-07-14",
        )

        path = mock_client.get.call_args[0][0]
        params = mock_client.get.call_args[1]["params"]
        assert path == ANALYTICS_SHOP_PERFORMANCE_PATH
        assert params["start_date_ge"] == "2026-07-13"
        assert params["end_date_lt"] == "2026-07-14"
        assert result["performance"]["intervals"][0]["sales"]["items_sold"] == 32

    def test_get_shop_performance_per_hour_uses_date_path(self, mock_client):
        mock_client.get.return_value = A37_PER_HOUR
        resource = AnalyticsResource(mock_client)

        result = resource.get_shop_performance_per_hour(date="2026-07-13")

        path = mock_client.get.call_args[0][0]
        assert path == analytics_shop_performance_per_hour_path("2026-07-13")
        assert "start_date_ge" not in mock_client.get.call_args[1].get("params", {})
        assert result["performance"]["overall"]["items_sold"] == 32

    def test_get_bestselling_products_uses_date_and_time_slot(self, mock_client):
        mock_client.get.return_value = A38_BESTSELLING_PRODUCTS
        resource = AnalyticsResource(mock_client)

        result = resource.get_bestselling_products(date="2026-07-07", time_slot="1D")

        path = mock_client.get.call_args[0][0]
        params = mock_client.get.call_args[1]["params"]
        assert path == ANALYTICS_BESTSELLING_PRODUCTS_PATH
        assert params["date"] == "2026-07-07"
        assert params["time_slot"] == "1D"
        assert result["products"][0]["id"] == "{product_id}"

    def test_get_bestselling_videos_uses_identifier_catalog_spellings(self, mock_client):
        mock_client.get.return_value = A39_BESTSELLING_VIDEOS
        resource = AnalyticsResource(mock_client)

        result = resource.get_bestselling_videos(date="2026-07-07", time_slot="1D")

        path = mock_client.get.call_args[0][0]
        params = mock_client.get.call_args[1]["params"]
        assert path == ANALYTICS_BESTSELLING_VIDEOS_PATH
        assert params["date"] == "2026-07-07"
        assert params["time_slot"] == "1D"
        assert result["videos"][0]["id"] == "{video_id}"
        assert result["videos"][0]["product_infos"][0]["product_id"] == "{product_id}"


class TestPromotionActivityProductionRead:
    def test_get_activity_uses_activity_id_path(self, mock_client):
        mock_client.get.return_value = A25_ACTIVITY
        resource = PromotionResource(mock_client)
        activity_id = "7402881377634567979"

        result = resource.get_activity(activity_id)

        mock_client.get.assert_called_once_with(promotion_activity_path(activity_id))
        assert result["activity_id"] == "7136104329798256386"
        assert result["products"][0]["skus"][0]["id"] == "7136382541418366725"
