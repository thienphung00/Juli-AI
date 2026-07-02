"""TDD tests for TikTok resource modules (creators, livestreams, settlements)."""

import pytest
from unittest.mock import MagicMock

from backend.integrations.catalog.domain.integrations.tiktok.constants import (
    CREATOR_CONTENT_DETAILS_PATH,
    FINANCE_STATEMENTS_PATH,
    MARKETPLACE_CREATORS_SEARCH_PATH,
    marketplace_creator_path,
)
from backend.integrations.catalog.domain.integrations.tiktok.resources.creators import CreatorsResource
from backend.integrations.catalog.domain.integrations.tiktok.resources.livestreams import LivestreamsResource
from backend.integrations.catalog.domain.integrations.tiktok.resources.settlements import SettlementsResource


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.post.return_value = {}
    client.get.return_value = {}
    client.get_all_pages.return_value = []
    client.get_all_pages_get.return_value = []
    return client


class TestCreatorsResourceListPaginated:
    def test_list_posts_to_versioned_path(self, mock_client):
        creators = CreatorsResource(mock_client)
        creators.list()

        mock_client.post.assert_called_once()
        assert mock_client.post.call_args[0][0] == MARKETPLACE_CREATORS_SEARCH_PATH

    def test_list_passes_page_size_as_query_param(self, mock_client):
        creators = CreatorsResource(mock_client)
        creators.list(page_size=20)

        params = mock_client.post.call_args[1]["params"]
        assert params["page_size"] == "20"
        assert mock_client.post.call_args[1]["body"] == {}

    def test_list_all_uses_get_all_pages(self, mock_client):
        mock_client.get_all_pages.return_value = [
            {"creator_user_id": "c1", "nickname": "Creator One"},
            {"creator_user_id": "c2", "nickname": "Creator Two"},
        ]
        creators = CreatorsResource(mock_client)

        result = creators.list_all(page_size=25)

        mock_client.get_all_pages.assert_called_once()
        call_args = mock_client.get_all_pages.call_args
        assert call_args[1]["path"] == MARKETPLACE_CREATORS_SEARCH_PATH
        assert call_args[1]["items_key"] == "marketplace_creators"
        assert result[0]["creator_id"] == "c1"
        assert result[0]["name"] == "Creator One"

    def test_get_fetches_marketplace_creator(self, mock_client):
        mock_client.get.return_value = {
            "creator_user_id": "c1",
            "nickname": "Top Seller",
            "follower_count": 50000,
        }
        creators = CreatorsResource(mock_client)

        result = creators.get("c1")

        mock_client.get.assert_called_once_with(marketplace_creator_path("c1"))
        assert result["creator_id"] == "c1"
        assert result["name"] == "Top Seller"


class TestLivestreamsResourceGetSessionMetrics:
    def test_list_uses_creator_content_details_path(self, mock_client):
        livestreams = LivestreamsResource(mock_client)
        livestreams.list()

        mock_client.get.assert_called_once()
        assert mock_client.get.call_args[0][0] == CREATOR_CONTENT_DETAILS_PATH

    def test_list_passes_creator_id_filter(self, mock_client):
        livestreams = LivestreamsResource(mock_client)
        livestreams.list(creator_id="c1")

        params = mock_client.get.call_args[1]["params"]
        assert params["creator_id"] == "c1"

    def test_list_all_paginates_via_get(self, mock_client):
        mock_client.get_all_pages_get.return_value = [
            {
                "room_id": "ls1",
                "title": "Stream 1",
                "total_viewers": 1200,
                "orders_placed": 45,
                "total_sale_gmv": "500.00",
                "end_time": 1700000000,
            },
        ]
        livestreams = LivestreamsResource(mock_client)

        result = livestreams.list_all(creator_id="c1")

        mock_client.get_all_pages_get.assert_called_once()
        call_args = mock_client.get_all_pages_get.call_args
        assert call_args[0][0] == CREATOR_CONTENT_DETAILS_PATH
        assert call_args[1]["items_key"] == "creator_content_details"
        assert result[0]["livestream_id"] == "ls1"
        assert result[0]["viewer_count"] == 1200

    def test_get_returns_session_metrics(self, mock_client):
        mock_client.get.return_value = {
            "creator_content_details": [
                {
                    "room_id": "ls1",
                    "duration_seconds": 3600,
                    "total_viewers": 1200,
                    "orders_placed": 45,
                    "total_sale_gmv": "900.00",
                    "end_time": 1700000000,
                }
            ],
        }
        livestreams = LivestreamsResource(mock_client)

        result = livestreams.get("ls1")

        assert result["livestream_id"] == "ls1"
        assert result["viewer_count"] == 1200
        assert result["order_count"] == 45


class TestSettlementsResourceFilterByDateRange:
    def test_list_uses_finance_statements_path(self, mock_client):
        settlements = SettlementsResource(mock_client)
        settlements.list()

        mock_client.get.assert_called_once()
        assert mock_client.get.call_args[0][0] == FINANCE_STATEMENTS_PATH

    def test_list_filters_by_statement_time_range(self, mock_client):
        settlements = SettlementsResource(mock_client)
        settlements.list(settle_time_from=1700000000, settle_time_to=1700100000)

        params = mock_client.get.call_args[1]["params"]
        assert params["sort_field"] == "statement_time"
        assert params["statement_time_ge"] == "1700000000"
        assert params["statement_time_lt"] == "1700100000"

    def test_list_all_paginates_statements(self, mock_client):
        mock_client.get_all_pages_get.return_value = [
            {
                "statement_id": "s1",
                "settlement_amount": "85.00",
                "statement_time": 1700000500,
                "payment_status": "CONFIRMED",
            },
            {
                "statement_id": "s2",
                "settlement_amount": "120.00",
                "statement_time": 1700000600,
            },
        ]
        settlements = SettlementsResource(mock_client)

        result = settlements.list_all(settle_time_from=1700000000)

        mock_client.get_all_pages_get.assert_called_once()
        call_args = mock_client.get_all_pages_get.call_args
        assert call_args[0][0] == FINANCE_STATEMENTS_PATH
        assert call_args[1]["items_key"] == "statements"
        assert result[0]["settlement_id"] == "s1"
        assert result[0]["amount"] == "85.00"
