"""OrdersResource — versioned Partner API paths and request schema."""

from unittest.mock import MagicMock

import pytest

from juli_backend.integrations.tiktok.constants import (
    ORDER_DETAIL_PATH,
    ORDER_SEARCH_PATH,
)
from juli_backend.integrations.tiktok.resources.orders import OrdersResource


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.post.return_value = {"orders": [], "next_page_token": ""}
    client.get.return_value = {"orders": []}
    client.get_all_pages.return_value = []
    return client


class TestOrdersResource:
    def test_search_uses_versioned_path_and_official_body_fields(self, mock_client):
        orders = OrdersResource(mock_client)

        orders.search(
            status="AWAITING_SHIPMENT",
            update_time_from=1_700_000_000,
            update_time_to=1_700_010_000,
            page_size=20,
            page_token="tok-1",
        )

        mock_client.post.assert_called_once()
        assert mock_client.post.call_args[0][0] == ORDER_SEARCH_PATH
        assert mock_client.post.call_args[1]["body"] == {
            "order_status": "AWAITING_SHIPMENT",
            "update_time_ge": 1_700_000_000,
            "update_time_lt": 1_700_010_000,
        }
        assert mock_client.post.call_args[1]["params"] == {
            "page_size": "20",
            "page_token": "tok-1",
        }

    def test_search_all_uses_versioned_path(self, mock_client):
        orders = OrdersResource(mock_client)

        orders.search_all(update_time_from=1_700_000_000, page_size=30)

        mock_client.get_all_pages.assert_called_once()
        kwargs = mock_client.get_all_pages.call_args[1]
        assert kwargs["path"] == ORDER_SEARCH_PATH
        assert kwargs["body"] == {
            "update_time_ge": 1_700_000_000,
        }
        assert kwargs["items_key"] == "orders"
        assert kwargs["page_size"] == 30

    def test_get_details_uses_get_with_ids_query(self, mock_client):
        orders = OrdersResource(mock_client)

        orders.get_details(["o1", "o2"])

        mock_client.get.assert_called_once_with(
            ORDER_DETAIL_PATH,
            params={"ids": "o1,o2"},
        )
