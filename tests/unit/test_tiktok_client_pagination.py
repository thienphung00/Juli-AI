"""Pagination behavior for TikTokClient.get_all_pages."""

from unittest.mock import MagicMock

import pytest

from backend.integrations.catalog.domain.integrations.tiktok.client import TikTokClient


@pytest.fixture
def client():
    c = TikTokClient(
        app_key="key",
        app_secret="secret",
        access_token="token",
        shop_cipher="cipher",
    )
    c.post = MagicMock()
    return c


class TestGetAllPages:
    def test_reads_next_page_token_from_response(self, client):
        client.post.side_effect = [
            {"orders": [{"id": "o1"}], "next_page_token": "cursor-2"},
            {"orders": [{"id": "o2"}]},
        ]

        result = client.get_all_pages(
            path="/order/202309/orders/search",
            body={"order_status": "AWAITING_SHIPMENT"},
            items_key="orders",
            page_size=25,
        )

        assert [o["id"] for o in result] == ["o1", "o2"]
        assert client.post.call_count == 2
        second_params = client.post.call_args_list[1][1]["params"]
        assert second_params["page_token"] == "cursor-2"
        assert second_params["page_size"] == "25"

    def test_page_size_and_page_token_are_query_params_not_body(self, client):
        client.post.return_value = {"orders": [{"id": "o1"}]}

        client.get_all_pages(
            path="/order/202309/orders/search",
            body={"order_status": "UNPAID"},
            items_key="orders",
            page_size=10,
        )

        _, kwargs = client.post.call_args
        assert kwargs["body"] == {"order_status": "UNPAID"}
        assert "page_size" not in kwargs["body"]
        assert kwargs["params"]["page_size"] == "10"

    def test_falls_back_to_page_token_when_next_page_token_missing(self, client):
        client.post.side_effect = [
            {"orders": [{"id": "o1"}], "page_token": "legacy-cursor"},
            {"orders": [{"id": "o2"}]},
        ]

        result = client.get_all_pages(
            path="/api/orders/search",
            body={},
            items_key="orders",
        )

        assert len(result) == 2
        assert client.post.call_args_list[1][1]["params"]["page_token"] == "legacy-cursor"

    def test_stops_when_no_cursor_returned(self, client):
        client.post.return_value = {"orders": [{"id": "o1"}]}

        result = client.get_all_pages(
            path="/order/202309/orders/search",
            body={},
            items_key="orders",
        )

        assert result == [{"id": "o1"}]
        client.post.assert_called_once()
